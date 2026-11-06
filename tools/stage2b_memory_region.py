#!/usr/bin/env python3
"""Stage-2b: add memory-region=<&fastrpc reserved pool> to the cDSP fastrpc node.

!! DEPRECATED / DO NOT RUN (2026-11-06) -------------------------------------
This patch was based on a wrong hypothesis and was NEVER executed. Do not run it.

Verified reasons:
  * mainline drivers/misc/fastrpc.c prints "no reserved DMA memory for FASTRPC"
    with dev_dbg() and does NOT abort probe -- it is not an error.
  * fastrpc_init_reserved_mem() starts with:
        /* Only SDSP and ADSP domains use a reserved remote heap region */
        if (domain_id != SDSP_DOMAIN_ID && domain_id != ADSP_DOMAIN_ID)
            return 0;
    i.e. the CDSP domain never reads this region at all.
  * upstream mainline arch/arm64/boot/dts/qcom/sm8150.dtsi has NEITHER
    memory-region NOR qcom,vmids on the cdsp fastrpc node; the sdsp node in
    raphael's DTB has them only as downstream/vendor leftovers.
  * qcom,vmids is only consumed for FASTRPC_ATTR_SECUREMAP buffers, not for
    user-PD/ASID creation.
  * Radxa forum thread 31391 independently reports that adding the
    shared-dma-pool memory-region removes the warning but INIT_CREATE still
    fails. See docs/05-Hexagon690-DSP调用研究.md section 11.

The real blocker is a firmware/userspace protocol mismatch on
FASTRPC_IOCTL_INIT_CREATE (AEE_EBADASID), documented in section 11.
---------------------------------------------------------------------------

Evidence: dmesg 'no reserved DMA memory for FASTRPC' + 'compute-cb@1: mem mmap
error' + fastrpc_test 0x80000453. Same failure signature as Radxa Dragon Q6A
where the fix was adding memory-region to the FastRPC node. In raphael's DTB
only the sdsp fastrpc node references the shared-dma-pool (phandle 0x7b).

Run from project root: python3 tmp/boot_probe/stage2b_memory_region.py
Does NOT reboot.
"""
import logging
import re
import sys

logging.getLogger("paramiko").setLevel(logging.CRITICAL)
import paramiko

HOST, USER, PWD = "172.16.42.1", "root", "<REDACTED>"
DTB = "/boot/dtbs/qcom/sm8150-xiaomi-raphael.dtb"
LOCAL_DTB = "tmp/boot_probe/raphael-stage2b.dtb"

sys.path.insert(0, "tmp/boot_probe")
from fdt_inspect import parse, text  # noqa: E402

PATCH = r'''
import re
SRC = "/tmp/raphael-s2b.dts"
DST = "/tmp/raphael-s2b-patched.dts"
lines = open(SRC, encoding="utf-8").read().splitlines(True)
out = list(lines)
label_i = next(i for i, l in enumerate(lines) if re.match(r'^\s*label = "cdsp";\s*$', l))
size_i = next(i for i in range(label_i, label_i + 20)
              if re.match(r'^\s*#size-cells = <0x00>;\s*$', lines[i]))
assert "memory-region" not in "".join(lines[label_i - 8:size_i + 2]), "already patched"
indent = re.match(r'^(\s*)', lines[size_i]).group(1)
out.insert(size_i + 1, indent + "memory-region = <0x7b>;\n")
open(DST, "w", encoding="utf-8").write("".join(out))
print("INSERTED_AT_LINE=%d indent=%d" % (size_i + 2, len(indent)))
print("CONTEXT:")
for l in out[label_i - 3:size_i + 4]:
    print("  " + l.rstrip())
'''


def run(c, cmd, timeout=90):
    _, so, se = c.exec_command(cmd, timeout=timeout)
    return so.read().decode("utf-8", "replace"), se.read().decode("utf-8", "replace")


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PWD, timeout=10, banner_timeout=10,
              auth_timeout=10, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()

    print("=== 1. decompile active DTB ===")
    out, _ = run(c, "dtc -I dtb -O dts -o /tmp/raphael-s2b.dts %s 2>/dev/null; "
                    "ls -l /tmp/raphael-s2b.dts" % DTB)
    print(out.strip())

    print("\n=== 2. insert memory-region ===")
    out, err = run(c, "python3 - <<'PY'\n" + PATCH + "\nPY")
    print(out.strip()[:3000])
    if err.strip():
        print("STDERR:", err.strip()[:500])
    if "INSERTED_AT_LINE" not in out:
        print("ABORT: patch failed")
        return 1

    print("\n=== 3. recompile + pull + verify ===")
    out, _ = run(c, "dtc -I dts -O dtb -o /tmp/raphael-stage2b.dtb "
                    "/tmp/raphael-s2b-patched.dts 2>/dev/null; ls -l /tmp/raphael-stage2b.dtb")
    print(out.strip())
    sftp.get("/tmp/raphael-stage2b.dtb", LOCAL_DTB)
    n = parse(LOCAL_DTB)
    cdsp = n["/soc@0/remoteproc@8300000/glink-edge/fastrpc"]
    pool = n["/reserved-memory/fastrpc"]
    ph = int.from_bytes(pool["phandle"], "big")
    mr = int.from_bytes(cdsp.get("memory-region", b""), "big") if cdsp.get("memory-region") else None
    print("reserved-memory/fastrpc phandle = 0x%x, compatible=%s, size=%s" %
          (ph, text(pool.get("compatible", b"")), pool.get("size", b"").hex()))
    print("cdsp fastrpc memory-region      = %s" % ("0x%x" % mr if mr else "MISSING"))
    rp = {p: pr for p, pr in n.items() if re.match(r'^/soc@0/remoteproc@[0-9a-f]+$', p)}
    states = {text(pr.get("compatible", b"")): (text(pr.get("status", b"")) or "okay")
              for pr in rp.values()}
    cb = [p for p, pr in n.items() if "compute-cb@" in p and "dma-coherent" in pr]
    print("remoteproc states:", states)
    print("compute-cb with dma-coherent: %d" % len(cb))
    ok = (mr == ph and len(cb) == 12 and
          states.get("qcom,sm8150-cdsp-pas") == "okay" and
          states.get("qcom,sm8150-mpss-pas") == "disabled" and
          states.get("qcom,sm8150-adsp-pas") == "disabled" and
          states.get("qcom,sm8150-slpi-pas") == "disabled")
    if not ok:
        print("ABORT: verification failed, nothing written")
        return 1
    print("VERIFY_OK")

    print("\n=== 4. write DTB (backup .bak.stage2b) ===")
    run(c, "cp %s %s.bak.stage2b" % (DTB, DTB))
    run(c, "cp /tmp/raphael-stage2b.dtb %s && sync" % DTB)
    out, _ = run(c, "ls -l %s*; echo '--- live check ---'; "
                    "dtc -I dtb -O dts %s 2>/dev/null | grep -A9 'label = \"cdsp\"' | head -10"
                    % (DTB, DTB))
    print(out.strip()[:2000])
    print("\n=== DONE (no reboot issued) ===")
    sftp.close()
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
