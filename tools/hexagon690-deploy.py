#!/usr/bin/env python3
"""Deploy the Hexagon 690 (cDSP) HVX vector-add example to the K20 Pro and run it.

Mainline fastrpc stack (github.com/qualcomm/fastrpc, built natively on device):
  - host links libcdsprpc.so (cDSP client lib; exports remote_handle64_open/invoke/close
    + remote_session_control) installed at /usr/local/lib.
  - the skel .so is loaded onto the DSP by the root-PD daemon via remotectl_open, so
    cdsprpcd MUST be running for cDSP. We start /usr/local/sbin/cdsprpcd (the matched
    daemon built from the same source as libcdsprpc).
  - header: /usr/local/include/fastrpc/remote.h ; SDK incs/ supplies AEEStdDef.h/AEEStdErr.h.

Pipeline:
  1) Upload DSP skel .so -> /usr/lib/rfsa/cdsp/ and /usr/share/qcom/dsp/cdsp/
  2) Upload generated stub/host sources + SDK incs -> /data/local/tmp/hvx/
  3) Compile host_main.c natively on device, linking libcdsprpc.
  4) Start cdsprpcd rootpd cdsp (kill any stray cdsp daemon first).
  5) Run host_main (bare-filename skel URI resolved via ADSP_LIBRARY_PATH).
"""
import os
import sys
import paramiko

LOCAL = "<WORKSPACE>/src/hexagon690"
HOST = dict(host="192.168.x.x", port=22, user="root", pw="<REDACTED>")
REMOTE_SKEL_DIR = "/usr/lib/rfsa/cdsp"
REMOTE_SKEL_SERVED = "/usr/share/qcom/dsp/cdsp"
REMOTE_WORK = "/data/local/tmp/hvx"
CDSPRPCD = "/usr/local/sbin/cdsprpcd"

UPLOADS = [
    (os.path.join(LOCAL, "libhvx_add_skel.so"), "libhvx_add_skel.so"),
    (os.path.join(LOCAL, "gen/hvx_add.h"), "hvx_add.h"),
    (os.path.join(LOCAL, "gen/hvx_add_stub.c"), "hvx_add_stub.c"),
    (os.path.join(LOCAL, "host_main.c"), "host_main.c"),
]


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST["host"], port=HOST["port"], username=HOST["user"],
              password=HOST["pw"], timeout=15, look_for_keys=False, allow_agent=False)
    return c


def run_cmd(c, cmd, timeout=120):
    stdin, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def sftp_put_dir(sftp, local_dir, remote_dir):
    for root, _dirs, files in os.walk(local_dir):
        rel = os.path.relpath(root, local_dir)
        rdir = os.path.join(remote_dir, rel).replace("\\", "/")
        try:
            sftp.stat(rdir)
        except IOError:
            sftp.mkdir(rdir)
        for f in files:
            sftp.put(os.path.join(root, f), os.path.join(rdir, f).replace("\\", "/"))


def main():
    c = connect()
    sftp = c.open_sftp()

    print("[1] ensure remote dirs")
    run_cmd(c, "mkdir -p %s %s %s" % (REMOTE_SKEL_DIR, REMOTE_SKEL_SERVED, REMOTE_WORK))
    run_cmd(c, "mkdir -p %s/incs/stddef" % REMOTE_WORK)

    print("[2] upload files")
    for local, remote in UPLOADS:
        if not os.path.exists(local):
            print("  MISSING:", local)
            continue
        rpath = (REMOTE_WORK + "/" + remote).replace("\\", "/")
        sftp.put(local, rpath)
        print("  ->", rpath)
    print("  -> (recursive) incs/")
    sftp_put_dir(sftp, os.path.join(LOCAL, "incs"), REMOTE_WORK + "/incs")
    sftp.put(os.path.join(LOCAL, "libhvx_add_skel.so"),
             (REMOTE_SKEL_DIR + "/libhvx_add_skel.so").replace("\\", "/"))
    print("  ->", REMOTE_SKEL_DIR + "/libhvx_add_skel.so")
    sftp.put(os.path.join(LOCAL, "libhvx_add_skel.so"),
             (REMOTE_SKEL_SERVED + "/libhvx_add_skel.so").replace("\\", "/"))
    print("  ->", REMOTE_SKEL_SERVED + "/libhvx_add_skel.so")
    sftp.close()

    print("[3] cDSP remoteproc state + device node")
    rc, out, err = run_cmd(c,
        "ls -l /dev/fastrpc-cdsp; for d in /sys/class/remoteproc/remoteproc*/; do "
        "n=$(cat $d/name 2>/dev/null); st=$(cat $d/state 2>/dev/null); "
        "[ \"$n\" = '8300000.remoteproc' ] && echo \"$n -> $st\"; done")
    print(out)
    if err.strip():
        print("[stderr]", err)

    print("[4] compile host natively (link mainline libcdsprpc)")
    # Compile against the SDK headers (define int32 etc., ABI-identical to
    # libcdsprpc); only the link target changes to the mainline libcdsprpc.
    cc = ("cd %s && gcc host_main.c hvx_add_stub.c "
          "-I. -Iincs -Iincs/stddef "
          "-o host_main -L/usr/local/lib -lcdsprpc -lpthread -ldl 2>&1") % REMOTE_WORK
    rc, out, err = run_cmd(c, cc, timeout=180)
    print(out)
    if err.strip():
        print("[stderr]", err)
    if rc != 0:
        print("COMPILE FAILED rc=%d" % rc)
        c.close()
        sys.exit(rc)

    print("[5] start cdsprpcd (matched daemon for libcdsprpc), kill strays first")
    run_cmd(c,
        "pkill -f 'cdsprpcd' 2>/dev/null; pkill -f 'hexagonrpcd.*fastrpc-cdsp' 2>/dev/null; "
        "sleep 1; setsid nohup %s rootpd cdsp >/tmp/cdsprpcd.log 2>&1 &" % CDSPRPCD)
    rc, out, err = run_cmd(c, "sleep 2; pgrep -af cdsprpcd")
    print(out or "(no cdsprpcd process?)")

    print("[6] run host (bare-filename skel URI via ADSP_LIBRARY_PATH)")
    rc, out, err = run_cmd(c,
        "cd %s && LD_LIBRARY_PATH=/usr/local/lib "
        "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;%s' "
        "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;%s' ./host_main"
        % (REMOTE_WORK, REMOTE_WORK, REMOTE_WORK),
        timeout=120)
    print(out)
    if err.strip():
        print("[stderr]", err)

    if "host: PASS" in out:
        print("\n===== RESULT: PASS (host<->cDSP FastRPC path working) =====")
        c.close()
        return

    print("[6b] not PASS; diagnostics")
    rc, lout, _ = run_cmd(c, "echo '--- cdsprpcd.log ---'; tail -25 /tmp/cdsprpcd.log 2>/dev/null; "
                              "echo '--- dmesg fastrpc ---'; dmesg 2>/dev/null | grep -i fastrpc | tail -15")
    print(lout)
    print("\n===== RESULT: did not see PASS; inspect diagnostics above =====")
    c.close()


if __name__ == "__main__":
    main()
