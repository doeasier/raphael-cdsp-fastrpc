#!/usr/bin/env python3
"""ZERO-FLASH, NO-SHIM PD-protocol experiment on raphael (USB-NCM / SSH).

This REPLACES the earlier "suppress nr=10 in cdsprpcd" plan, which was
disproved by source-level evidence:
  * kernel fastrpc_init_create_process() does NOT call fastrpc_req_mem_map();
  * cdsprpcd never issues INIT_CREATE (only INIT_ATTACH + MEM_MAP on ROOT_PD);
  * faking a successful MEM_MAP would insert a bogus vaddrout=0 mapping.

Instead: stop cdsprpcd entirely (removing all userspace root-PD influence) and
re-run a raw-UAPI probe that links NO libcdsprpc.  Each probe process sends one
PD-creation ioctl, so measurements are independent.

  python3 tmp/boot_probe/deploy_pdscan.py check
  python3 tmp/boot_probe/deploy_pdscan.py build
  python3 tmp/boot_probe/deploy_pdscan.py p0        # daemon running (baseline)
  python3 tmp/boot_probe/deploy_pdscan.py p1        # daemon STOPPED, same matrix
  python3 tmp/boot_probe/deploy_pdscan.py p2        # extra RMID6/7 combinations
  python3 tmp/boot_probe/deploy_pdscan.py p2static  # OPTIONAL: RMID8 static PD (new RMID, small risk)
  python3 tmp/boot_probe/deploy_pdscan.py restore   # start daemon, verify clean baseline
  python3 tmp/boot_probe/deploy_pdscan.py forensics # read-only logind evidence (also runs in check)
  python3 tmp/boot_probe/deploy_pdscan.py reboot    # normal systemctl reboot (NEVER kexec)

No kernel, DTB, firmware or installed library is changed.  Only cdsprpcd is
stopped/started.  All output goes to logs/pdscan/.
"""
import os
import sys
import base64
import paramiko

HOST = '172.16.42.1'
USER = 'root'
PASSWORD = '<REDACTED>'
LOCAL_C = os.path.join('tmp', 'boot_probe', 'fastrpc_pdscan.c')
REMOTE_DIR = '/opt/rootpd-exp'
REMOTE_C = REMOTE_DIR + '/fastrpc_pdscan.c'
REMOTE_BIN = REMOTE_DIR + '/fastrpc_pdscan'
LOGDIR = os.path.join('logs', 'pdscan')

ENV = ("LD_LIBRARY_PATH=/usr/local/lib "
       "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
       "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx'")

# (device node, attach mode, attrs, optional "static")
SAFE_MATRIX = [
    ('/dev/fastrpc-cdsp',        'noattach', '0x8'),
    ('/dev/fastrpc-cdsp',        'noattach', '0x0'),
    ('/dev/fastrpc-cdsp',        'attach',   '0x8'),
    ('/dev/fastrpc-cdsp-secure', 'noattach', '0x8'),
    ('/dev/fastrpc-cdsp-secure', 'attach',   '0x8'),
]
EXTRA_MATRIX = [
    ('/dev/fastrpc-cdsp',        'attach',   '0x0'),
    ('/dev/fastrpc-cdsp-secure', 'noattach', '0x0'),
    ('/dev/fastrpc-cdsp-secure', 'attach',   '0x0'),
]
STATIC_MATRIX = [
    ('/dev/fastrpc-cdsp',        'attach',   '0x0', 'static'),
    ('/dev/fastrpc-cdsp',        'noattach', '0x0', 'static'),
]


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    return c


def run(c, cmd, timeout=180, label=None, save=None):
    if label:
        print('\n===== %s =====' % label)
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors='replace')
    e = err.read().decode(errors='replace')
    rc = out.channel.recv_exit_status()
    if o.strip():
        print(o.strip()[:12000])
    if e.strip():
        print('STDERR:', e.strip()[:3000])
    print('[rc=%d]' % rc)
    if save:
        os.makedirs(LOGDIR, exist_ok=True)
        with open(os.path.join(LOGDIR, save), 'w', encoding='utf-8') as f:
            f.write('CMD: %s\nRC: %d\n--- stdout ---\n%s\n--- stderr ---\n%s\n'
                    % (cmd, rc, o, e))
    return rc, o, e


def put_text(c, path, text):
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    return run(c, "mkdir -p %s && printf '%%s' '%s' | base64 -d > %s && chmod 644 %s"
               % (os.path.dirname(path), b64, path, path), 60)


def state(c, tag):
    return run(c,
        'echo "=== %s ==="; date; uptime; '
        'echo "-- remoteproc --"; cat /sys/class/remoteproc/remoteproc0/state 2>&1; '
        'echo "-- nodes --"; ls -l /dev/fastrpc-cdsp* 2>&1; '
        'echo "-- daemon --"; systemctl is-active cdsprpcd.service; '
        'echo "-- libs --"; sha256sum /usr/local/lib/libcdsprpc.so.1.0.0 '
        '/usr/local/lib/libcdsp_default_listener.so.1.0.0; '
        'echo "-- drop-ins --"; ls -l /etc/systemd/system/cdsprpcd.service.d/ 2>&1',
        90, 'DEVICE STATE ' + tag, save='state-%s.txt' % tag)


def matrix(c, tag, rows):
    cmds = []
    for r in rows:
        dev, attach, attrs = r[0], r[1], r[2]
        extra = ' ' + r[3] if len(r) > 3 else ''
        name = '%s-%s-%s%s' % (dev.split('/')[-1], attach, attrs,
                               '-static' if extra else '')
        cmds.append('echo "### %s"; timeout 25 %s %s %s %s%s 2>&1; '
                    'echo "RC=$?"' % (name, REMOTE_BIN, dev, attach, attrs, extra))
    return run(c, '\n'.join(cmds), 300, 'PD MATRIX ' + tag, save='matrix-%s.txt' % tag)


def client_baseline(c, tag):
    run(c, 'cd /data/local/tmp/hvx && %s timeout 90 ./host_main 2>&1 | head -30; '
           'echo HOST_DONE' % ENV, 150, 'HOST_MAIN ' + tag,
        save='host-main-%s.txt' % tag)
    run(c, 'timeout 90 fastrpc_test -d 3 -U 1 2>&1 | '
           'grep -iE "ERROR|PASS|FAIL|selector|Summary|RESULT|rc=" | head -25; '
           'echo TEST_DONE', 150, 'FASTRPC_TEST ' + tag,
        save='fastrpc-test-%s.txt' % tag)


def logs(c, tag):
    return run(c,
        'echo "=== dmesg ==="; dmesg | grep -iE "fastrpc|mem mmap|glink|rpmsg" | tail -30; '
        'echo "=== journal ==="; '
        'journalctl -u cdsprpcd.service --since "5 min ago" --no-pager -o cat | tail -40',
        120, 'KERNEL + DAEMON LOGS ' + tag, save='logs-%s.txt' % tag)


def forensics(c):
    """READ-ONLY evidence for the §14.2b '23MB SFTP -> logind saturation'
    hypothesis.  All local journals are from 11-05, so the incident boot can
    only be inspected once the device is back (persistent journal permitting).
    Every probe is timeout-wrapped: loginctl itself can hang when logind wedges.
    """
    return run(c,
        'echo "=== boots ==="; timeout 15 journalctl --list-boots --no-pager 2>&1 | tail -12; '
        'echo "=== previous boot: logind / ssh ==="; '
        'timeout 25 journalctl -b -1 -u systemd-logind -u ssh --no-pager '
        '-o short-precise 2>&1 | tail -80; '
        'echo "=== 11-06 window: logind / ssh ==="; '
        'timeout 25 journalctl --since "2026-11-06 00:00" --until "2026-11-06 23:59" '
        '-u systemd-logind -u ssh --no-pager -o short-precise 2>&1 | tail -80; '
        'echo "=== 11-06 window: pam/session keywords ==="; '
        'timeout 25 journalctl --since "2026-11-06 00:00" --until "2026-11-06 23:59" '
        '--no-pager -o short-precise 2>&1 | '
        'grep -iE "pam_systemd|Failed to create session|Maximum number of sessions|'
        'Connection timed out|sshd|sftp|session" | tail -80; '
        'echo "=== current logind ==="; p=$(pidof systemd-logind | cut -d" " -f1); echo PID=$p; '
        'if [ -n "$p" ]; then echo WCHAN=$(cat /proc/$p/wchan 2>/dev/null); '
        'echo FD_COUNT=$(ls /proc/$p/fd 2>/dev/null | wc -l); '
        'echo STATE=$(ps -o stat= -p $p 2>/dev/null); fi; '
        'echo "=== sessions ==="; timeout 10 loginctl list-sessions --no-legend 2>&1 | head -25; '
        'echo "=== hung tasks ==="; dmesg 2>/dev/null | '
        'grep -iE "hung task|blocked for more than|D state" | tail -20; '
        'echo FORENSICS_DONE',
        180, 'LOGIND FORENSICS (incident boot, read-only)', save='forensics.txt')


def check(c):
    state(c, 'check')
    run(c, 'echo "=== unit ==="; systemctl cat cdsprpcd.service --no-pager; '
           'echo "=== gcc ==="; gcc --version | head -1; '
           'echo "=== UAPI header ==="; '
           'ls -l /usr/src/linux-headers-$(uname -r)/include/uapi/misc/fastrpc.h 2>&1; '
           'grep -n "INIT_CREATE_STATIC" '
           '/usr/src/linux-headers-$(uname -r)/include/uapi/misc/fastrpc.h 2>&1; '
           'echo "=== client binaries ==="; ls -l /data/local/tmp/hvx/host_main '
           '/usr/local/bin/fastrpc_test 2>&1',
        90, 'UNIT + TOOLCHAIN', save='unit.txt')
    forensics(c)
    return 0


def build(c):
    if not os.path.isfile(LOCAL_C):
        print('missing', LOCAL_C)
        return 1
    with open(LOCAL_C, encoding='utf-8') as f:
        src = f.read()
    run(c, 'mkdir -p %s; echo DIRS_OK' % REMOTE_DIR, 30)
    put_text(c, REMOTE_C, src)
    return run(c,
        'gcc -O0 -g -Wall -I/usr/src/linux-headers-$(uname -r)/include/uapi '
        '-o %s %s 2>&1; echo BUILD_RC=$?; ls -l %s; file %s'
        % (REMOTE_BIN, REMOTE_C, REMOTE_BIN, REMOTE_BIN),
        120, 'BUILD RAW PROBE ON DEVICE')[0]


def p0(c):
    state(c, 'p0')
    client_baseline(c, 'p0')
    matrix(c, 'p0-daemon-on', SAFE_MATRIX)
    logs(c, 'p0')
    return 0


def p1(c):
    run(c, 'systemctl stop cdsprpcd.service; sleep 2; '
           'systemctl is-active cdsprpcd.service || true; '
           'echo DAEMON_STOPPED', 90, 'STOP cdsprpcd')
    state(c, 'p1')
    matrix(c, 'p1-daemon-off', SAFE_MATRIX)
    logs(c, 'p1')
    return 0


def p2(c):
    state(c, 'p2')
    matrix(c, 'p2-extra', EXTRA_MATRIX)
    logs(c, 'p2')
    return 0


def p2static(c):
    """OPTIONAL / HIGHER RISK: emits RMID8 (INIT_CREATE_STATIC), a message the
    2020-12 firmware has never seen in our logs.  Run only after reviewing
    p0/p1, and be ready for a physical reboot if glink wedges."""
    state(c, 'p2static')
    matrix(c, 'p2static', STATIC_MATRIX)
    logs(c, 'p2static')
    return 0


def restore(c):
    rc, _, _ = run(c, 'systemctl start cdsprpcd.service; sleep 3; '
                      'systemctl is-active cdsprpcd.service; '
                      'echo "=== env ==="; p=$(pidof cdsprpcd | cut -d" " -f1); '
                      'tr "\\0" "\\n" < /proc/$p/environ | grep -E "^(LD_PRELOAD|FR_)" '
                      '|| echo NO_SHIM_ENV', 120, 'START cdsprpcd AGAIN')
    if rc:
        return rc
    state(c, 'restored')
    client_baseline(c, 'restored')
    logs(c, 'restored')
    return 0


def reboot(c):
    return run(c, 'echo issuing-normal-reboot; systemctl reboot', 30,
               'NORMAL REBOOT (NO KEXEC)')[0]


def main():
    actions = {'check': check, 'build': build, 'p0': p0, 'p1': p1,
               'p2': p2, 'p2static': p2static, 'forensics': forensics,
               'restore': restore, 'reboot': reboot}
    if len(sys.argv) < 2 or sys.argv[1] not in actions:
        print(__doc__)
        return 2
    c = connect()
    try:
        return actions[sys.argv[1]](c)
    finally:
        c.close()


if __name__ == '__main__':
    sys.exit(main())
