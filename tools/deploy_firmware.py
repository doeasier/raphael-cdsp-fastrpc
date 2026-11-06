#!/usr/bin/env python3
"""Staged, fully-reversible deployment of the 2021-07-30 cDSP firmware set.

Actions (run one at a time, in this order):
  upload      chunked upload + sha256 verify + untar + per-file manifest verify
  backup      back up current pil/ + dsp/ (+ tar.gz + SHA256SUMS + rollback.sh)
  precheck    read-only baseline check right before replacing
  replace     copy all 32 files into place (NO reboot)
  verify      sha256 check after replacement (NO reboot)
  reboot      systemctl reboot  (NEVER kexec)
  postcheck   after the device is back: dmesg / remoteproc / build-id / host_main
  rollback    restore from backup (then reboot manually)
  status      read-only current state

All device paths are ordinary rootfs files; nothing is flashed, no DTB/kernel
change, no drop-in, no deletions.  Safe-delete on the Windows host is avoided
by never calling os.unlink().
"""
import io
import os
import sys
import time
import hashlib
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'

ROOT = os.path.join('tmp', 'firmware', 'raphael-20210730')
BUNDLE = os.path.join(ROOT, 'deploy-bundle.tar.gz')
MANIFEST = os.path.join(ROOT, 'deploy-manifest.txt')
PARTS_DIR = os.path.join(ROOT, 'parts')
LOGDIR = os.path.join('logs', 'firmware')

BUNDLE_SHA = 'a3f1d8790073050f9e35e747641c1c0b765e166ba90b1516c712f7539e2c38ec'
CHUNK = 1024 * 1024

STAGE = '/root/cdsp-20210730-staging'
BK = '/root/cdsp-firmware-backup-20201211-pre-20210730'
BK_TAR = BK + '.tar.gz'
PIL = '/lib/firmware/qcom/sm8150/Xiaomi/raphael'
DSP = '/usr/share/qcom/dsp/cdsp'

PIL_FILES = ['cdsp.mdt', 'cdsp.b00', 'cdsp.b01', 'cdsp.b02', 'cdsp.b03',
             'cdsp.b04', 'cdsp.b05', 'cdsp.b06', 'cdsp.b08', 'cdsp.b10',
             'cdspr.jsn']

# The 21 files from deploy-manifest.txt (dsp/ entries); libhvx_add_skel.so is
# deliberately NOT in this list - it is our own compiled skel and must survive.
DSP_FILES = [
    'fastrpc_shell_3', 'fastrpc_shell_unsigned_3', 'libbenchmark_skel.so',
    'libc++.so.1', 'libc++abi.so.1', 'libhcp_rpc_skel.so', 'libhta_dsp_skel.so',
    'libimmotion_skel.so', 'libstabilitydomain_skel.so', 'libsysmon_skel.so',
    'libsysmondomain_skel.so', 'libsysmonhvxthrottle_skel.so',
    'libsysmonquery_skel.so', 'libvpp_aie.so', 'libvpp_frc.so',
    'libvpp_mvp.so', 'libvpp_nr.so', 'libvpp_qbr.so', 'libvpp_svc_skel.so',
    'map_SHARED_LIBS_855.cdsp.prodQ.txt', 'ubwcdma_dynlib.so',
]

ROLLBACK_SH = '''#!/bin/bash
# Restore the pre-2021-07-30 cDSP firmware. Run as root, then: systemctl reboot
set -e
BK="%s"
PIL="%s"
DSP="%s"
echo "== restore PIL (split mdt+bXX) =="
cp -a "$BK/pil/." "$PIL/"
echo "== restore DSP libs (21 files, libhvx_add_skel.so untouched) =="
cp -a "$BK/dsp/." "$DSP/"
echo "== verify =="
( cd "$BK" && sha256sum -c SHA256SUMS ) || echo "WARNING: checksum mismatch"
echo "== done. NOW RUN: systemctl reboot =="
''' % (BK, PIL, DSP)

README = '''cDSP firmware backup - pre 2021-07-30 swap
created: %s
device : Redmi K20 Pro / raphael / SM8150 / Ubuntu 24.04 / mainline 7.0
source : /lib/firmware/qcom/sm8150/Xiaomi/raphael/ (cdsp.mdt + cdsp.bXX)
         /usr/share/qcom/dsp/cdsp/ (21 stock files)

IMPORTANT version note:
  DSP shell / skel are build  CDSP.HT.2.0.1-00171-SM8150-1.357350.2_20201211_224311
  but the PIL actually loaded is an OLDER, DIFFERENT branch:
  cdsp.mdt phdr b02=227348 b05=2710852, cdsp.b05 QC_IMAGE_VERSION_STRING
  = CDSP.HT.2.0.1-00131-SM8150-1.  They were NOT a matched set.
  Do not assume this backup is a single coherent build.

Excluded: /usr/share/qcom/dsp/cdsp/libhvx_add_skel.so (our own 7160 B skel),
          /usr/lib/rfsa/adsp/ symlinks, and all non-cdsp firmware files.
Rollback: bash /root/cdsp-rollback.sh ; then systemctl reboot (NEVER kexec)
'''


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    return c


def run(c, cmd, timeout=180, quiet=False):
    if not quiet:
        print('\n$ ' + cmd[:400])
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors='replace')
    e = err.read().decode(errors='replace')
    rc = out.channel.recv_exit_status()
    if not quiet:
        if o.strip():
            sys.stdout.write(o[:14000])
        if e.strip():
            print('[STDERR] ' + e[:3000])
        print('[rc=%d]' % rc)
    return o, e, rc


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def local_manifest():
    """return {arcname: (size, sha)} from deploy-manifest.txt"""
    d = {}
    for line in open(MANIFEST, encoding='utf-8'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        h, size, name = line.split()
        d[name] = (int(size), h)
    return d


def action_upload():
    os.makedirs(PARTS_DIR, exist_ok=True)
    blob = open(BUNDLE, 'rb').read()
    assert sha_bytes(blob) == BUNDLE_SHA, 'local bundle sha mismatch'
    n = (len(blob) + CHUNK - 1) // CHUNK
    print('bundle %d B / %d chunks' % (len(blob), n))
    names = []
    for i in range(n):
        part = blob[i * CHUNK:(i + 1) * CHUNK]
        name = 'part.%02d' % i
        lp = os.path.join(PARTS_DIR, name)
        with open(lp, 'wb') as f:
            f.write(part)
        names.append((name, lp, sha_bytes(part)))

    c = connect()
    run(c, 'mkdir -p ' + STAGE)
    # one SFTP connection, small chunks, verify each chunk immediately
    sftp = c.open_sftp()
    for name, lp, h in names:
        rp = STAGE + '/' + name
        sftp.put(lp, rp)
        o, e, rc = run(c, 'sha256sum ' + rp, quiet=True)
        got = o.split()[0] if o.strip() else ''
        print('  %s  local=%s remote=%s %s' %
              (name, h[:12], got[:12], 'OK' if got == h else 'MISMATCH'))
        if got != h:
            raise SystemExit('chunk sha mismatch, ABORT: ' + name)
    sftp.close()

    cat = 'cat ' + ' '.join(STAGE + '/' + n0 for n0, _, _ in names) + ' > ' + STAGE + '/deploy-bundle.tar.gz'
    run(c, cat)
    o, e, rc = run(c, 'sha256sum ' + STAGE + '/deploy-bundle.tar.gz', quiet=True)
    whole = o.split()[0] if o.strip() else ''
    print('whole bundle sha = %s (expect %s)' % (whole, BUNDLE_SHA))
    if whole != BUNDLE_SHA:
        raise SystemExit('merged bundle sha mismatch, ABORT')
    run(c, 'cd ' + STAGE + ' && tar -xzf deploy-bundle.tar.gz && ls -la && echo --- && ls -la pil dsp | head -60')
    c.close()

    # write a canonical sha256 -c manifest into staging (LF bytes, no CRLF)
    mf = local_manifest()
    want = ''.join('%s  %s\n' % (mf[n][1], n) for n in sorted(mf))
    c = connect()
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(want.encode('utf-8')), STAGE + '/want.sha')
    sftp.close()
    o, e, rc = run(c, 'cd %s && LC_ALL=C sha256sum -c want.sha 2>&1 | tail -40' % STAGE)
    n_ok = o.count(': OK')
    print('\nper-file verification: %d expected, %d OK' % (len(mf), n_ok))
    if n_ok != len(mf):
        raise SystemExit('staging verification FAILED - device firmware still untouched')
    if 'FAILED' in o or rc != 0:
        raise SystemExit('staging sha256 -c reported failure - ABORT')
    c.close()
    print('UPLOAD OK - device firmware files are still 100% untouched.')


def action_backup():
    c = connect()
    run(c, 'test ! -e %s && echo "backup dir is new" || echo "WARNING: backup dir already exists"' % BK)
    run(c, 'mkdir -p %s/pil %s/dsp' % (BK, BK))
    pil_list = ' '.join(PIL + '/' + f for f in PIL_FILES)
    dsp_list = ' '.join(DSP + '/' + f for f in DSP_FILES)
    run(c, 'cp -a %s %s/pil/ && cp -a %s %s/dsp/' % (pil_list, BK, dsp_list, BK))
    run(c, 'cd %s && sha256sum pil/* dsp/* > SHA256SUMS && wc -l SHA256SUMS' % BK)
    run(c, 'cd /root && tar -czf %s %s && ls -l %s' %
        (BK_TAR, os.path.basename(BK), BK_TAR))
    # write README + rollback.sh as bytes (LF only, no CRLF)
    sftp = c.open_sftp()
    readme = README % time.strftime('%Y-%m-%d %H:%M:%S')
    sftp.putfo(io.BytesIO(readme.encode('utf-8')), BK + '/README.txt')
    sftp.putfo(io.BytesIO(ROLLBACK_SH.encode('utf-8')), '/root/cdsp-rollback.sh')
    sftp.close()
    run(c, 'chmod +x /root/cdsp-rollback.sh && head -5 /root/cdsp-rollback.sh && echo --- '
           '&& cat %s/README.txt | head -12' % BK)
    o, e, rc = run(c, 'cd %s && sha256sum -c SHA256SUMS | tail -3; echo ---; '
                      'tar -tzf %s | wc -l; echo ---; ls -la %s/pil %s/dsp | head -50' %
                   (BK, BK_TAR, BK, BK), quiet=False)
    c.close()
    print('\nBACKUP OK ->', BK, 'and', BK_TAR)


def action_precheck():
    c = connect()
    run(c, 'echo "== cmdline =="; cat /proc/cmdline; echo "== remoteproc =="; '
           'cat /sys/class/remoteproc/remoteproc0/state; '
           'echo "== devnodes =="; ls -l /dev/fastrpc-cdsp*; '
           'echo "== daemon =="; systemctl is-active cdsprpcd; '
           'echo "== secure boot =="; od -An -tx1 /sys/firmware/efi/efivars/SecureBoot-* | tail -1; '
           'echo "== backup =="; ls -l %s %s; ' % (BK_TAR, '/root/cdsp-rollback.sh'))
    c.close()


def action_replace():
    mf = local_manifest()
    c = connect()
    # staged files must still verify
    o, e, rc = run(c, 'cd %s && LC_ALL=C sha256sum -c want.sha 2>&1 | grep -c ": OK"' % STAGE,
                   quiet=True)
    ok = int(o.strip() or 0)
    if ok != len(mf):
        raise SystemExit('staging no longer verifies (%d/%d) - ABORT' % (ok, len(mf)))
    print('staging verified: %d/%d files' % (ok, len(mf)))

    # PIL: keep original 0755; DSP: keep original 0644. cp -a preserves staged
    # mode (0644), so chmod explicitly afterwards.
    pil_src = ' '.join('%s/pil/%s' % (STAGE, f) for f in PIL_FILES)
    dsp_src = ' '.join('%s/dsp/%s' % (STAGE, f) for f in DSP_FILES)
    run(c, 'cp -f %s %s/ && chmod 755 %s/cdsp.* %s/cdspr.jsn && '
           'cp -f %s %s/ && chmod 644 %s/*' %
           (pil_src, PIL, PIL, PIL, dsp_src, DSP, DSP))
    run(c, 'echo "== new PIL sizes =="; ls -l %s/cdsp.mdt %s/cdsp.b0* %s/cdsp.b10; '
           'echo "== hvx skel still present =="; sha256sum %s/libhvx_add_skel.so; '
           'echo "== rfsa links =="; ls -l /usr/lib/rfsa/adsp/libhvx_add_skel.so' %
           (PIL, PIL, PIL, DSP))
    c.close()
    print('\nREPLACE done. NOT rebooted yet. Run: python3 ... verify')


def action_verify():
    mf = local_manifest()
    c = connect()
    o, e, rc = run(c, 'sha256sum %s/cdsp.mdt %s/cdsp.b* %s/cdspr.jsn %s/* 2>/dev/null' %
                   (PIL, PIL, PIL, DSP), quiet=True)
    got = {}
    for line in o.splitlines():
        p = line.split(None, 1)
        if len(p) == 2:
            got[os.path.basename(p[1].strip())] = p[0]
    bad = []
    for name, (size, h) in sorted(mf.items()):
        base = os.path.basename(name)
        g = got.get(base)
        if g != h:
            bad.append((name, h[:12], (g or 'MISSING')[:12]))
    c.close()
    print('post-replace verification: %d expected, %d mismatches' % (len(mf), len(bad)))
    for b in bad:
        print('  MISMATCH', b)
    if bad:
        raise SystemExit('post-replace verification FAILED - run rollback before reboot')
    print('VERIFY OK - all 32 files in place, still not rebooted.')


def action_reboot():
    c = connect()
    print('issuing systemctl reboot (NEVER kexec) ...')
    try:
        c.exec_command('systemctl reboot', timeout=5)
    except Exception as ex:
        print('expected disconnect: %r' % (ex,))
    try:
        c.close()
    except Exception:
        pass
    print('reboot issued. Wait for the device, then run: python3 ... postcheck')


def action_early():
    """Lightweight post-reboot check: PAS verdict, remoteproc, build ids.
    Does NOT run host_main (which could hang if the cDSP RPC channel died)."""
    c = connect()
    run(c, 'echo "== uptime / cmdline =="; uptime; cat /proc/uptime; cat /proc/cmdline; '
           'echo "== PAS / cdsp kernel log =="; journalctl -b -k --no-pager 2>/dev/null | '
           'grep -iE "cdsp|q6v5|qcom_mdt|remoteproc|pas_|scm|firmware|auth|rollback" | tail -80')
    run(c, 'echo "== remoteproc state =="; cat /sys/class/remoteproc/remoteproc0/state 2>&1; '
           'echo "== devnodes =="; ls -l /dev/fastrpc-cdsp* 2>&1; '
           'echo "== daemon =="; systemctl is-active cdsprpcd 2>&1; '
           'echo "== new shell build id =="; '
           'grep -a -o -E "[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}" %s/fastrpc_shell_unsigned_3 | sort -u | head -5; '
           'echo "== new PIL build id =="; grep -a -o -E "QC_IMAGE_VERSION_STRING.{0,60}" %s/cdsp.b05 | head -2; '
           'echo "== new PIL version strings =="; grep -a -o -E "CDSP.HT.2.0.1.{0,70}" %s/cdsp.b05 | head -3' %
           (DSP, PIL, PIL))
    c.close()


def action_postcheck():
    c = connect()
    run(c, 'echo "== uptime / cmdline =="; uptime; cat /proc/cmdline; '
           'echo "== PAS / cdsp kernel log =="; journalctl -b -k --no-pager 2>/dev/null | '
           'grep -iE "cdsp|q6v5|qcom_mdt|remoteproc|pas_|scm|firmware" | tail -80')
    run(c, 'echo "== remoteproc state =="; cat /sys/class/remoteproc/remoteproc0/state; '
           'echo "== devnodes =="; ls -l /dev/fastrpc-cdsp*; '
           'echo "== daemon =="; systemctl is-active cdsprpcd; '
           'echo "== new shell build id =="; '
           'grep -a -o -E "[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}" %s/fastrpc_shell_unsigned_3 | sort -u | head -5; '
           'echo "== new PIL build id =="; grep -a -o -E "QC_IMAGE_VERSION_STRING.{0,60}" %s/cdsp.b05 | head -2' %
           (DSP, PIL))
    run(c, 'cd /data/local/tmp/hvx && LD_LIBRARY_PATH=/usr/local/lib '
           'ADSP_LIBRARY_PATH="/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx" '
           'DSP_LIBRARY_PATH="/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx" '
           './host_main 2>&1 | tail -40')
    c.close()


def action_rollback():
    c = connect()
    run(c, 'bash /root/cdsp-rollback.sh 2>&1 | tail -40')
    c.close()
    print('rollback files restored. NOW: python3 ... reboot  (systemctl reboot)')


def action_status():
    c = connect()
    run(c, 'echo "== PIL =="; sha256sum %s/cdsp.mdt %s/cdsp.b02 %s/cdsp.b05; '
           'echo "== DSP shell =="; sha256sum %s/fastrpc_shell_unsigned_3; '
           'echo "== remoteproc =="; cat /sys/class/remoteproc/remoteproc0/state; '
           'echo "== staging =="; ls %s 2>/dev/null | head; '
           'echo "== backup =="; ls -l %s' % (PIL, PIL, PIL, DSP, STAGE, BK_TAR))
    c.close()


ACTIONS = {
    'upload': action_upload, 'backup': action_backup, 'precheck': action_precheck,
    'replace': action_replace, 'verify': action_verify,     'reboot': action_reboot,
    'early': action_early, 'postcheck': action_postcheck,
    'rollback': action_rollback, 'status': action_status,
}

if __name__ == '__main__':
    os.makedirs(LOGDIR, exist_ok=True)
    act = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if act not in ACTIONS:
        raise SystemExit('usage: deploy_firmware.py <%s>' % '|'.join(ACTIONS))
    print('=== ACTION: %s @ %s ===' % (act, time.strftime('%Y-%m-%d %H:%M:%S')))
    ACTIONS[act]()
