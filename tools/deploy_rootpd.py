#!/usr/bin/env python3
"""DEPRECATED - DO NOT RUN (2026-11-06, before any device execution).

The "suppress nr=10 in cdsprpcd" experiment was disproved by source-level
review: INIT_CREATE does not go through MEM_MAP, cdsprpcd never issues
INIT_CREATE, and faking a successful MEM_MAP would insert a vaddrout=0 bogus
mapping (PR#319 v2 hazard).  Use deploy_pdscan.py instead.
See docs/05-Hexagon690-DSP调用研究.md §14.3.

---------------------------------------------------------------------------
ZERO-FLASH root-PD experiment on raphael (no kernel flash, no DTB change).

Host-side driver.  The device is reached only over USB-NCM / SSH.

  python3 tmp/boot_probe/deploy_rootpd.py check      # link + clean baseline + unit info
  python3 tmp/boot_probe/deploy_rootpd.py build      # upload shim .c, gcc it on device
  python3 tmp/boot_probe/deploy_rootpd.py e0         # baseline trace (no shim on daemon)
  python3 tmp/boot_probe/deploy_rootpd.py e1         # restart daemon WITHOUT shim, re-measure
  python3 tmp/boot_probe/deploy_rootpd.py install    # add systemd drop-in with shim, restart daemon
  python3 tmp/boot_probe/deploy_rootpd.py e2         # measure with nr=10 short-circuited
  python3 tmp/boot_probe/deploy_rootpd.py e3         # also short-circuit nr=10 in the client
  python3 tmp/boot_probe/deploy_rootpd.py restore    # remove drop-in, restart, verify baseline
  python3 tmp/boot_probe/deploy_rootpd.py reboot     # normal systemctl reboot (NEVER kexec)

Safety:
 * nr=10 is short-circuited BEFORE it reaches the driver, so no new RMID is
   emitted to the cDSP (PR#319 v2 wedged glink by emitting RMID_INIT_MMAP).
 * No library, kernel, DTB or firmware file is replaced.  Only a systemd
   drop-in is added, and `restore` moves it aside instead of deleting it.
 * Every measurement is written to logs/rootpd-exp/ for offline comparison.
"""
import os
import sys
import base64
import time
import paramiko

HOST = '172.16.42.1'
USER = 'root'
PASSWORD = '<REDACTED>'
LOCAL_C = os.path.join('tmp', 'boot_probe', 'fastrpc_nomemmap.c')
REMOTE_DIR = '/opt/rootpd-exp'
REMOTE_C = REMOTE_DIR + '/fastrpc_nomemmap.c'
REMOTE_SO = REMOTE_DIR + '/fastrpc_nomemmap.so'
DROPIN_DIR = '/etc/systemd/system/cdsprpcd.service.d'
DROPIN = DROPIN_DIR + '/20-rootpd-exp.conf'
BACKUP_DIR = REMOTE_DIR + '/backup'
LOGDIR = os.path.join('logs', 'rootpd-exp')

ENV = ("LD_LIBRARY_PATH=/usr/local/lib "
       "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
       "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx'")
SHIM = "/opt/rootpd-exp/fastrpc_nomemmap.so"


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    # fail fast on the wedged-sshd symptom instead of hanging for minutes
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
    """Small files only: base64 through exec_command, no SFTP session at all."""
    b64 = base64.b64encode(text.encode('utf-8')).decode('ascii')
    cmd = "mkdir -p %s && printf '%%s' '%s' | base64 -d > %s && chmod 644 %s" % (
        os.path.dirname(path), b64, path, path)
    return run(c, cmd, 60)


def device_state(c, tag):
    return run(c,
        'echo "=== %s ==="; date; uptime; '
        'echo "-- remoteproc --"; cat /sys/class/remoteproc/remoteproc0/state 2>&1; '
        'echo "-- nodes --"; ls -l /dev/fastrpc-cdsp* 2>&1; '
        'echo "-- daemon --"; systemctl is-active cdsprpcd.service; '
        'echo "-- daemon env --"; p=$(pidof cdsprpcd | cut -d" " -f1); '
        'echo PID=$p; '
        'if [ -n "$p" ]; then tr "\\0" "\\n" < /proc/$p/environ | '
        'grep -E "^(LD_PRELOAD|FR_)" || echo NO_SHIM_ENV; '
        'grep -c fastrpc_nomemmap /proc/$p/maps || true; fi; '
        'echo "-- libs --"; sha256sum /usr/local/lib/libcdsprpc.so.1.0.0 '
        '/usr/local/lib/libcdsp_default_listener.so.1.0.0; '
        'echo "-- drop-in --"; ls -l %s 2>&1' % (tag, DROPIN_DIR),
        90, 'DEVICE STATE ' + tag, save='state-%s.txt' % tag)


def measure(c, tag, extra_client=''):
    """One measurement pass: client trace + host_main + fastrpc_test + logs."""
    trace = '/tmp/rootpd-exp-%s.trace' % tag
    shim_env = ('LD_PRELOAD=%s FR_TRACE_ALL=1 FR_TRACE_FILE=%s %s'
                % (SHIM, trace, extra_client))
    env = '%s %s' % (ENV, shim_env)
    run(c, 'rm -f %s 2>/dev/null; echo trace=%s' % (trace, trace), 30)
    run(c, 'cd /data/local/tmp/hvx && %s timeout 90 ./host_main 2>&1 | head -40; '
           'echo HOST_DONE' % env, 150, 'HOST_MAIN ' + tag,
        save='host-main-%s.txt' % tag)
    run(c, '%s timeout 90 fastrpc_test -d 3 -U 1 2>&1 | '
           'grep -iE "ERROR|PASS|FAIL|selector|Summary|RESULT|rc=" | head -30; '
           'echo TEST_DONE' % shim_env, 150, 'FASTRPC_TEST ' + tag,
        save='fastrpc-test-%s.txt' % tag)
    run(c, 'echo "=== client trace ==="; cat %s 2>&1 | tail -60; '
           'echo "=== daemon trace ==="; tail -40 /tmp/rootpd-exp.trace 2>&1; '
           'echo "=== dmesg ==="; dmesg | grep -iE "fastrpc|mem mmap|glink" | tail -25; '
           'echo "=== daemon journal ==="; '
           'journalctl -u cdsprpcd.service --since "3 min ago" --no-pager -o cat | tail -35'
           % trace, 120, 'TRACES ' + tag, save='traces-%s.txt' % tag)


def check(c):
    device_state(c, 'check')
    run(c, 'echo "=== unit ==="; systemctl cat cdsprpcd.service --no-pager; '
           'echo "=== gcc ==="; gcc --version | head -1; '
           'echo "=== probe binaries ==="; ls -l /data/local/tmp/hvx/host_main '
           '/usr/local/bin/fastrpc_test 2>&1; '
           'echo "=== stage2 dtb sanity ==="; '
           'grep -c "dma-coherent" /proc/device-tree/soc@0/rpmsg/* 2>/dev/null || true',
        90, 'UNIT + TOOLCHAIN', save='unit.txt')
    return 0


def build(c):
    if not os.path.isfile(LOCAL_C):
        print('missing', LOCAL_C)
        return 1
    with open(LOCAL_C, encoding='utf-8') as f:
        src = f.read()
    run(c, 'mkdir -p %s %s %s; echo DIRS_OK' % (REMOTE_DIR, BACKUP_DIR, DROPIN_DIR), 30)
    put_text(c, REMOTE_C, src)
    rc, _, _ = run(c, 'gcc -shared -fPIC -O0 -Wall -o %s %s -ldl 2>&1; '
                      'echo BUILD_RC=$?; ls -l %s; file %s'
                   % (REMOTE_SO, REMOTE_C, REMOTE_SO, REMOTE_SO),
                   120, 'BUILD SHIM ON DEVICE')
    return rc


def e0(c):
    device_state(c, 'e0')
    measure(c, 'e0')
    return 0


def e1(c):
    run(c, 'systemctl restart cdsprpcd.service; sleep 3; '
           'systemctl is-active cdsprpcd.service; '
           'journalctl -u cdsprpcd.service --since "1 min ago" --no-pager -o cat | tail -25',
        120, 'E1 RESTART DAEMON WITHOUT SHIM')
    device_state(c, 'e1')
    measure(c, 'e1')
    return 0


def install(c):
    conf = ('[Service]\n'
            'Environment=LD_PRELOAD=%s\n'
            'Environment=FR_SKIP_MEMMAP=1\n'
            'Environment=FR_TRACE_ALL=1\n'
            'Environment=FR_TRACE_FILE=/tmp/rootpd-exp.trace\n' % SHIM)
    run(c, 'mkdir -p %s %s; '
           '[ -f %s ] && mv %s %s/20-rootpd-exp.conf.prev || echo NO_OLD_DROPIN'
           % (DROPIN_DIR, BACKUP_DIR, DROPIN, DROPIN, BACKUP_DIR), 30)
    put_text(c, DROPIN, conf)
    rc, _, _ = run(c, 'systemctl daemon-reload; systemctl restart cdsprpcd.service; '
                      'sleep 3; systemctl is-active cdsprpcd.service; '
                      'echo "=== effective env ==="; '
                      'p=$(pidof cdsprpcd | cut -d" " -f1); echo PID=$p; '
                      'tr "\\0" "\\n" < /proc/$p/environ | grep -E "^(LD_PRELOAD|FR_)"; '
                      'echo "=== shim mapped ==="; grep fastrpc_nomemmap /proc/$p/maps | head -3; '
                      'echo "=== journal ==="; '
                      'journalctl -u cdsprpcd.service --since "1 min ago" --no-pager -o cat | tail -25',
                   150, 'INSTALL DROP-IN + RESTART DAEMON')
    return rc


def e2(c):
    device_state(c, 'e2')
    measure(c, 'e2')
    return 0


def e3(c):
    device_state(c, 'e3')
    measure(c, 'e3', extra_client='FR_SKIP_MEMMAP=1')
    return 0


def restore(c):
    rc, _, _ = run(c, 'if [ -f %s ]; then mv %s %s/20-rootpd-exp.conf.used; '
                      'echo DROPIN_MOVED; else echo NO_DROPIN; fi; '
                      'systemctl daemon-reload; systemctl restart cdsprpcd.service; '
                      'sleep 3; systemctl is-active cdsprpcd.service; '
                      'echo "=== env after restore ==="; '
                      'p=$(pidof cdsprpcd | cut -d" " -f1); '
                      'tr "\\0" "\\n" < /proc/$p/environ | grep -E "^(LD_PRELOAD|FR_)" '
                      '|| echo NO_SHIM_ENV; '
                      'echo "=== libs ==="; '
                      'sha256sum /usr/local/lib/libcdsprpc.so.1.0.0'
                   % (DROPIN, DROPIN, BACKUP_DIR),
                   150, 'RESTORE DROP-IN')
    if rc:
        return rc
    measure(c, 'restored')
    return 0


def reboot(c):
    return run(c, 'echo issuing-normal-reboot; systemctl reboot', 30,
               'NORMAL REBOOT (NO KEXEC)')[0]


def main():
    actions = {'check': check, 'build': build, 'e0': e0, 'e1': e1,
               'install': install, 'e2': e2, 'e3': e3,
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
