#!/usr/bin/env python3
"""Wait for the raphael device to come back after a PHYSICAL reboot, then run
the zero-flash PD-protocol experiment unattended.

  python3 tmp/boot_probe/run_rootpd_experiment.py [wait_minutes]
  python3 tmp/boot_probe/run_rootpd_experiment.py 0     # wait indefinitely

Stages are the same ones a human would run by hand:
  check -> build -> p0 -> p1 -> p2 -> restore

(The earlier E0-E3 "suppress nr=10" matrix was DISPROVED before execution and
 is NOT used here; see deploy_pdscan.py and docs/05 §14.3.)

If any stage fails, `restore` is attempted immediately so cdsprpcd is never
left stopped.  Every stage's stdout/stderr goes to logs/pdscan/auto-<stage>.log
and a summary is written at the end.

The device must be rebooted by the user (long-press power, or TWRP -> reboot
system).  The script does NOT reboot the device by itself.
"""
import os
import sys
import time
import subprocess
import socket

HERE = os.path.dirname(os.path.abspath(__file__))
DRIVER = os.path.join(HERE, 'deploy_pdscan.py')
LOGDIR = os.path.join('logs', 'pdscan')
HOST = '172.16.42.1'
STAGES = ['check', 'build', 'p0', 'p1', 'p2']
PY = sys.executable


def log(msg):
    line = '[%s] %s' % (time.strftime('%Y-%m-%d %H:%M:%S'), msg)
    print(line, flush=True)
    os.makedirs(LOGDIR, exist_ok=True)
    with open(os.path.join(LOGDIR, 'auto-summary.txt'), 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def port_banner_ok():
    """TCP connect + read the SSH banner ONLY, never authenticate.

    A full SSH login that reaches USERAUTH_SUCCESS leaves one sshd monitor
    wedged in pam_open_session() for up to 120s.  A banner-only probe stays in
    pre-auth, so it cannot feed that positive feedback loop.  A phone reboot
    makes port 22 (and usually ping) disappear briefly, which is the signal we
    watch for.
    """
    try:
        s = socket.create_connection((HOST, 22), timeout=3)
        s.settimeout(3)
        b = s.recv(96)
        s.close()
        return b.startswith(b'SSH-')
    except Exception:
        return False


def link_ok():
    """One short, fully closed SSH transaction; returns True only if a
    channel can really be opened (the wedged-sshd symptom fails here)."""
    try:
        import paramiko
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username='root', password='<REDACTED>', timeout=8,
                  look_for_keys=False, allow_agent=False,
                  banner_timeout=8, auth_timeout=8)
        ch = c.get_transport().open_session(timeout=8)
        ch.exec_command('echo LINK_OK')
        out = ch.recv(1024)
        ch.close()
        c.close()
        return b'LINK_OK' in out
    except Exception:
        return False


def host_ping():
    try:
        r = subprocess.run(['ping', '-n', '1', '-w', '800', HOST],
                           capture_output=True, timeout=5)
        return b'TTL=' in r.stdout or b'ttl=' in r.stdout
    except Exception:
        return False


def fix_ncm():
    """After a phone reboot Windows may re-enumerate the NCM adapter and lose
    both 172.16.42.2/24 and the explicit route that bypasses MihomoTun."""
    log('NCM: host cannot ping device; re-running usb-ncm-up.ps1')
    try:
        p = subprocess.run(['powershell', '-ExecutionPolicy', 'Bypass', '-File',
                            os.path.join('scripts', 'host', 'usb-ncm-up.ps1'),
                            '-WaitSec', '25'],
                           capture_output=True, timeout=110)
        out = (p.stdout + p.stderr).decode('gbk', errors='replace')
        log('NCM FIX rc=%d\n%s' % (p.returncode, out[-1400:]))
    except Exception as e:
        log('NCM FIX ERR %s' % e)


def stage(name, timeout=900):
    path = os.path.join(LOGDIR, 'auto-%s.log' % name)
    log('STAGE START %s' % name)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            rc = subprocess.call([PY, DRIVER, name], stdout=f,
                                 stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        rc = 124
        log('STAGE %s TIMEOUT (%ss)' % (name, timeout))
    with open(path, encoding='utf-8', errors='replace') as f:
        tail = f.read()[-1500:]
    log('STAGE END %s rc=%d\n%s' % (name, rc, tail))
    return rc


def main():
    wait_min = float(sys.argv[1]) if len(sys.argv) > 1 else 25.0
    # 0 (or negative) = wait indefinitely.  Two timed windows (30 min and
    # 90 min) already expired with the phone untouched; a permanent watcher
    # avoids repeated timeout noise while keeping the "reboot then auto-run"
    # behaviour.  It exits only when the experiment finishes.
    deadline = None if wait_min <= 0 else time.time() + wait_min * 60
    log('WAITING for device (%s). Please physically reboot the phone.'
        % ('NO TIMEOUT' if deadline is None else 'max %.0f min' % wait_min))
    last_fix = 0.0
    last_full_probe = 0.0
    seen_down = False
    fast_retries = 0
    poll_sec = 30
    full_probe_interval = 300          # 5 min fallback only

    while deadline is None or time.time() < deadline:
        p_ok = host_ping()
        b_ok = port_banner_ok()

        if not p_ok or not b_ok:
            if not seen_down:
                log('DEVICE LINK WENT DOWN (phone rebooting / USB re-enumerating)')
            seen_down = True
        if not p_ok and time.time() - last_fix > 120:
            fix_ncm()
            last_fix = time.time()

        if seen_down and p_ok and b_ok:
            # One full SSH probe per observed reboot.  sshd may still be
            # starting, so allow a few 30s retries before falling back.
            seen_down = False
            fast_retries = 3
            last_full_probe = time.time()
            log('DEVICE CAME BACK UP; running one full SSH probe')
            if link_ok():
                log('DEVICE LINK RECOVERED')
                break
            log('link still wedged after reboot; scheduling fast retries')
        elif p_ok and b_ok and (
                (fast_retries > 0 and time.time() - last_full_probe >= poll_sec)
                or time.time() - last_full_probe >= full_probe_interval):
            if fast_retries > 0:
                fast_retries -= 1
            last_full_probe = time.time()
            if link_ok():
                log('DEVICE LINK RECOVERED')
                break

        time.sleep(poll_sec)
    else:
        log('TIMEOUT: device never recovered; nothing was changed on the device.')
        return 2

    failed = None
    for s in STAGES:
        rc = stage(s)
        if rc != 0:
            failed = s
            log('ABORT after failed stage %s (rc=%d)' % (s, rc))
            break
    # Always restore: restart cdsprpcd and re-measure the clean baseline.
    rc = stage('restore')
    if failed:
        log('FINISHED WITH FAILURE at %s; restore rc=%d' % (failed, rc))
        return 1
    log('FINISHED OK; all stage logs in %s' % LOGDIR)
    return 0


if __name__ == '__main__':
    sys.exit(main())
