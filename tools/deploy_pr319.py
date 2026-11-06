#!/usr/bin/env python3
"""Build the PR#319 (AEE_EUNSUPPORTED -> legacy MMAP_64) fastrpc userspace on
the raphael device, WITHOUT touching the installed libraries or the kernel.

Host:  python3 tmp/boot_probe/deploy_pr319.py build
       python3 tmp/boot_probe/deploy_pr319.py install   (swap in, with backup)
       python3 tmp/boot_probe/deploy_pr319.py restore   (put the originals back)
       python3 tmp/boot_probe/deploy_pr319.py test      (run the experiments)

Everything lives on the healthy / partition; /data2 is unreadable (ext4 EIO).
"""
import os
import sys
import posixpath
import paramiko

HOST = '172.16.42.1'
USER = 'root'
PASSWORD = '<REDACTED>'
TARBALL = os.path.join('tmp', 'boot_probe', 'fastrpc-pr319.tar.gz')
REMOTE_TAR = '/opt/fastrpc-pr319.tar.gz'
SRC = '/opt/fastrpc-pr319'
BACKUP = '/opt/fastrpc-backup-20261106'
LIBDIR = '/usr/local/lib'


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False)
    return c


def run(c, cmd, timeout=600, label=None):
    if label:
        print('\n===== %s =====' % label)
    _in, out, err = c.exec_command(cmd, timeout=timeout)
    o = out.read().decode(errors='replace')
    e = err.read().decode(errors='replace')
    if o.strip():
        print(o.strip()[:9000])
    if e.strip():
        print('STDERR:', e.strip()[:2000])
    rc = out.channel.recv_exit_status()
    print('[rc=%d]' % rc)
    return rc, o, e


def build(c):
    if not os.path.isfile(TARBALL):
        print('missing tarball', TARBALL)
        return 1
    s = c.open_sftp()
    print('uploading %s (%.1f KB)' % (TARBALL, os.path.getsize(TARBALL) / 1024.0))
    s.put(TARBALL, REMOTE_TAR)
    s.close()
    rc, _, _ = run(c, 'cd /opt && rm -rf %s && tar xzf %s && ls -ld %s && '
                      'grep -n "AEE_EUNSUPPORTED" %s/src/apps_mem_imp.c | head'
                   % (SRC, REMOTE_TAR, SRC, SRC), 120, 'EXTRACT + PATCH CHECK')
    if rc:
        return rc
    # A Windows tarball carries CRLF text files and loses the exec bit.  A CRLF
    # shebang ("#!/bin/bash\r") makes the kernel look for a nonexistent
    # interpreter, so normalise before autoreconf.
    rc, _, _ = run(c, "python3 - <<'PY'\n"
                      "import os\n"
                      "root = '%s'\n"
                      "n = 0\n"
                      "for dp, dn, fn in os.walk(root):\n"
                      "    for f in fn:\n"
                      "        p = os.path.join(dp, f)\n"
                      "        b = open(p, 'rb').read()\n"
                      "        if b'\\x00' in b[:4096]:\n"
                      "            continue\n"
                      "        nb = b.replace(b'\\r\\n', b'\\n')\n"
                      "        if nb != b:\n"
                      "            open(p, 'wb').write(nb)\n"
                      "            n += 1\n"
                      "print('CRLF_FIXED', n)\n"
                      "PY\n"
                      "chmod +x %s/gitcompile %s/autogen.sh\n"
                      "echo SHEBANG; head -1 %s/gitcompile | od -c | head -2"
                   % (SRC, SRC, SRC, SRC), 120, 'NORMALIZE LINE ENDINGS')
    if rc:
        return rc
    # autoreconf -is via gitcompile, then make separately with parallelism.
    rc, _, _ = run(c, 'cd %s && mkdir -p m4 && '
                      'GITCOMPILE_NO_MAKE=1 ./gitcompile --prefix=/usr/local '
                      '> /tmp/pr319-configure.log 2>&1; echo RC=$?; '
                      'tail -25 /tmp/pr319-configure.log' % SRC, 300, 'CONFIGURE')
    if rc:
        return rc
    rc, _, _ = run(c, 'cd %s && make -j6 > /tmp/pr319-make.log 2>&1; echo RC=$?; '
                      'tail -40 /tmp/pr319-make.log' % SRC, 900, 'MAKE')
    if rc:
        return rc
    run(c, 'echo "=== artifacts ==="; ls -l %s/src/.libs/libcdsprpc.so* '
           '%s/src/.libs/libcdsp_default_listener.so* %s/src/cdsprpcd 2>&1; '
           'echo "=== ldd daemon ==="; ldd %s/src/.libs/cdsprpcd 2>&1 | head -15; '
           'echo "=== ldd installed daemon ==="; ldd /usr/local/sbin/cdsprpcd 2>&1 | head -15; '
           'echo "=== patched symbol check ==="; '
           'strings %s/src/.libs/libcdsprpc.so.1.0.0 | grep -c "fastrpc_mmap_internal"'
        % (SRC, SRC, SRC, SRC, SRC), 120, 'ARTIFACTS')
    return 0


def install(c):
    # Only swap the two shared objects.  The daemon is a thin dlopen() shell,
    # so the patched logic is picked up through libcdsprpc.so.
    rc, _, _ = run(c, 'set -e; '
                      'for f in libcdsprpc.so.1.0.0 libcdsp_default_listener.so.1.0.0; do '
                      '  [ -f %s/$f ] || cp -a /usr/local/lib/$f %s/$f.pre-pr319; '
                      'done; '
                      'cp -a %s/src/.libs/libcdsprpc.so.1.0.0 /usr/local/lib/; '
                      'cp -a %s/src/.libs/libcdsp_default_listener.so.1.0.0 /usr/local/lib/; '
                      'ldconfig; '
                      'echo "=== installed ==="; ls -l /usr/local/lib/libcdsprpc.so.1.0.0 '
                      '/usr/local/lib/libcdsp_default_listener.so.1.0.0; '
                      'echo "=== pre-pr319 backups ==="; '
                      'ls -l %s/*.pre-pr319 2>/dev/null || echo "(originals already in backup dir)"'
                   % (BACKUP, BACKUP, SRC, SRC, BACKUP), 120, 'SWAP IN PR319 BUILD')
    if rc:
        return rc
    run(c, 'systemctl restart cdsprpcd.service; sleep 3; '
           'systemctl is-active cdsprpcd.service; '
           'echo "=== cdsprpcd journal ==="; '
           'journalctl -u cdsprpcd.service --since "1 min ago" --no-pager -o cat | tail -30',
        120, 'RESTART DAEMON')
    return 0


def restore(c):
    return run(c, 'set -e; '
                  'cp -a %s/libcdsprpc.so.1.0.0 /usr/local/lib/; '
                  'cp -a %s/libcdsp_default_listener.so.1.0.0 /usr/local/lib/; '
                  'ldconfig; systemctl restart cdsprpcd.service; sleep 2; '
                  'echo RESTORED; systemctl is-active cdsprpcd.service'
               % (BACKUP, BACKUP), 120, 'RESTORE ORIGINAL')[0]


def test(c):
    env = ("LD_LIBRARY_PATH=/usr/local/lib "
           "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
           "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx'")
    run(c, 'echo "=== fastrpc_test -d 3 -U 1 ==="; timeout 90 fastrpc_test -d 3 -U 1 2>&1 '
           '| grep -iE "ERROR|PASS|FAIL|selector|Summary|RESULT" | head -25; echo TEST_DONE',
        150, 'FASTRPC_TEST')
    run(c, 'echo "=== host_main ==="; cd /data/local/tmp/hvx && %s timeout 90 ./host_main 2>&1 '
           '| head -25; echo HOST_DONE' % env, 150, 'HOST_MAIN')
    run(c, 'echo "=== dmesg fastrpc tail ==="; dmesg | grep -iE "fastrpc|mem mmap" | tail -20',
        90, 'DMESG')
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    action = sys.argv[1]
    c = connect()
    try:
        return {'build': build, 'install': install,
                'restore': restore, 'test': test}[action](c)
    finally:
        c.close()


if __name__ == '__main__':
    sys.exit(main())
