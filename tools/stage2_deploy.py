#!/usr/bin/env python3
"""Stage-2 deploy for raphael cDSP FastRPC (runs on the Windows host over SSH).

Steps (idempotent, all changes backed up):
  1. Patch the decompiled DTS:
       - remoteproc@2400000 (slpi), @4080000 (mpss), @17300000 (adsp)
         -> status = "disabled"   (keep @8300000 cdsp okay)
       - every compute-cb@N -> add dma-coherent;
  2. dtc recompile, pull the new DTB back, and VERIFY it with fdt_inspect.py.
     Abort without writing anything if verification fails.
  3. Write: patched DTB (backup .bak.stage2), modprobe.d (unblock
     qcom_q6v5_pas), refind first entry (drop modprobe.blacklist), udev rule
     (cdsp recovery=disabled).
  4. Do NOT reboot - caller decides after reviewing the output.

Run from the project root:  python3 tmp/boot_probe/stage2_deploy.py
"""
import logging
import re
import sys

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
import paramiko

HOST, USER, PWD = "172.16.42.1", "root", "<REDACTED>"
DTB = "/boot/dtbs/qcom/sm8150-xiaomi-raphael.dtb"
LOCAL_DTB = "tmp/boot_probe/raphael-stage2.dtb"

sys.path.insert(0, "tmp/boot_probe")
from fdt_inspect import parse, text  # noqa: E402

PATCH_DTS = r'''
import re, difflib
SRC = "/tmp/raphael-s2.dts"
DST = "/tmp/raphael-s2-patched.dts"
DISABLE = {"remoteproc@2400000", "remoteproc@4080000", "remoteproc@17300000"}
lines = open(SRC, encoding="utf-8").read().splitlines(True)
out, cur, depth, changed = [], None, 0, set()
node_re = re.compile(r'^\s*([A-Za-z0-9_,.+@-]+)\s*\{\s*$')
for ln in lines:
    if cur is None:
        m = node_re.match(ln)
        if m and m.group(1) in DISABLE:
            cur, depth = m.group(1), 1
        out.append(ln)
        continue
    if depth == 1 and 'status = "okay";' in ln and cur not in changed:
        ln = ln.replace('status = "okay";', 'status = "disabled";')
        changed.add(cur)
    out.append(ln)
    depth += ln.count('{') - ln.count('}')
    if depth <= 0:
        cur = None

out2, cb = [], 0
for ln in out:
    out2.append(ln)
    m = re.match(r'^(\s*)(compute-cb@[0-9a-fA-F]+)\s*\{\s*$', ln)
    if m:
        out2.append(m.group(1) + '\t' + 'dma-coherent;\n')
        cb += 1
open(DST, "w", encoding="utf-8").write("".join(out2))

print("STATUS_CHANGED=%s" % sorted(changed))
print("CB_DMA_COHERENT_ADDED=%d" % cb)
d = list(difflib.unified_diff(lines, out2, n=0))
plus = [x.rstrip() for x in d if x.startswith('+') and not x.startswith('+++')]
minus = [x.rstrip() for x in d if x.startswith('-') and not x.startswith('---')]
print("DIFF_PLUS=%d DIFF_MINUS=%d" % (len(plus), len(minus)))
for x in plus: print("  " + x)
for x in minus: print("  " + x)
assert len(changed) == 3, "expected 3 status changes, got %s" % changed
assert cb == 12, "expected 12 compute-cb nodes, got %d" % cb
print("PATCH_OK")
'''

MODPROBE = """# Stage-2 (2026-11-05): qcom_q6v5_pas unblocked.
# DTB now has adsp/mpss/slpi remoteproc nodes status="disabled" and only
# cdsp (@8300000) enabled, so loading the shared PAS driver boots cDSP only
# (no modem -> no WLAN PD -> no SM8150 QMI CAL_REPORT fabric lock).
# Legacy self-authenticating drivers stay blacklisted (no matching DT nodes).
blacklist qcom_q6v5_adsp
blacklist qcom_q6v5_mss
install qcom_q6v5_adsp /bin/false
install qcom_q6v5_mss /bin/false
"""


def run(c, cmd, timeout=90):
    _, so, se = c.exec_command(cmd, timeout=timeout)
    return so.read().decode("utf-8", "replace"), se.read().decode("utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PWD, timeout=10, banner_timeout=10,
              auth_timeout=10, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()

    print("=== 1. decompile current DTB ===")
    out, err = run(c, "dtc -I dtb -O dts -o /tmp/raphael-s2.dts %s 2>/tmp/dtc-s2.warn; "
                      "ls -l /tmp/raphael-s2.dts" % DTB)
    print(out.strip(), err.strip()[:300])

    print("\n=== 2. patch DTS ===")
    out, err = run(c, "python3 - <<'PY'\n" + PATCH_DTS + "\nPY")
    print(out.strip()[:6000])
    if err.strip():
        print("STDERR:", err.strip()[:800])
    if "PATCH_OK" not in out:
        print("ABORT: DTS patch did not pass its own assertions")
        return 1

    print("\n=== 3. recompile DTB ===")
    out, err = run(c, "dtc -I dts -O dtb -o /tmp/raphael-stage2.dtb "
                      "/tmp/raphael-s2-patched.dts 2>/tmp/dtc-s2b.warn; "
                      "ls -l /tmp/raphael-stage2.dtb; tail -3 /tmp/dtc-s2b.warn")
    print(out.strip(), err.strip()[:300])

    print("\n=== 4. pull & independently verify ===")
    sftp.get("/tmp/raphael-stage2.dtb", LOCAL_DTB)
    nodes = parse(LOCAL_DTB)
    rp = {p: props for p, props in nodes.items()
          if re.match(r'^/soc@0/remoteproc@[0-9a-f]+$', p)}
    print("remoteproc nodes found: %d" % len(rp))
    ok = True
    for p, props in sorted(rp.items()):
        st = text(props.get("status", b"")) or "<absent=>okay>"
        comp = text(props.get("compatible", b""))
        print("  %-32s %-28s status=%s" % (p, comp, st))
        if "cdsp" in comp:
            ok &= (st in ("okay", "<absent=>okay>"))
        elif comp:
            ok &= (st == "disabled")
    cbn = {p: pr for p, pr in nodes.items() if "compute-cb@" in p}
    with_coherent = [p for p, pr in cbn.items() if "dma-coherent" in pr]
    print("compute-cb nodes: %d, with dma-coherent: %d" % (len(cbn), len(with_coherent)))
    ok &= (len(cbn) == 12 and len(with_coherent) == 12)
    if not ok:
        print("ABORT: verification failed, NOTHING written to the device")
        return 1
    print("VERIFY_OK")

    print("\n=== 5. write changes (all backed up) ===")
    run(c, "cp %s %s.bak.stage2 2>/dev/null || cp %s %s.bak.stage2" % (DTB, DTB, DTB, DTB))
    run(c, "cp /etc/modprobe.d/99-raphael-dsp-debug.conf "
           "/etc/modprobe.d/99-raphael-dsp-debug.conf.bak.stage2")
    run(c, "cp /boot/refind_linux.conf /boot/refind_linux.conf.bak.stage2")
    run(c, "cp /etc/udev/rules.d/99-raphael-modem-norecover.rules "
           "/etc/udev/rules.d/99-raphael-modem-norecover.rules.bak.stage2")
    # DTB
    run(c, "cp /tmp/raphael-stage2.dtb %s && sync" % DTB)
    # modprobe.d
    with sftp.open("/etc/modprobe.d/99-raphael-dsp-debug.conf", "w") as f:
        f.write(MODPROBE.encode())
    # refind: only touch the first (stage1) entry
    with sftp.open("/boot/refind_linux.conf") as f:
        ref = f.read().decode("utf-8")
    lines = ref.splitlines(True)
    for i, ln in enumerate(lines):
        if ln.startswith('"Boot stage1') or ln.startswith('"Boot stage2'):
            ln = re.sub(r'^"Boot stage1 \(usb-net only\)"', '"Boot stage2 (cdsp)"', ln)
            ln = re.sub(r' modprobe\.blacklist=[^ ]+', '', ln)
            lines[i] = ln
            break
    with sftp.open("/boot/refind_linux.conf", "w") as f:
        f.write("".join(lines).encode())
    # udev: add cdsp recovery=disabled
    with sftp.open("/etc/udev/rules.d/99-raphael-modem-norecover.rules") as f:
        udev = f.read().decode("utf-8")
    if 'ATTR{name}=="cdsp"' not in udev:
        udev += ('\n# cDSP: never trigger SSR/reboot on a DSP crash\n'
                 'SUBSYSTEM=="remoteproc", ACTION=="add", ATTR{name}=="cdsp", '
                 'ATTR{recovery}="disabled"\n')
    with sftp.open("/etc/udev/rules.d/99-raphael-modem-norecover.rules", "w") as f:
        f.write(udev.encode())
    run(c, "sync")

    print("\n=== 6. verify on device ===")
    out, _ = run(c, "ls -l %s*; echo '--- modprobe.d ---'; cat /etc/modprobe.d/99-raphael-dsp-debug.conf; "
                    "echo '--- refind entries ---'; grep '^\"Boot' /boot/refind_linux.conf | cut -c1-110; "
                    "echo '--- udev ---'; tail -3 /etc/udev/rules.d/99-raphael-modem-norecover.rules; "
                    "echo '--- new dtb coherent count ---'; "
                    "dtc -I dtb -O dts %s 2>/dev/null | grep -c 'dma-coherent'" % (DTB, DTB))
    print(out.strip()[:4000])
    print("\n=== DONE (no reboot issued) ===")
    sftp.close()
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
