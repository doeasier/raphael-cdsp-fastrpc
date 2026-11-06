#!/usr/bin/env python3
"""Long-lived, low-noise post-reboot watcher for the cDSP firmware experiment.

Replaces wait_and_verify.py (which timed out after ~36 min of banner timeouts).
Waits up to ~2 h for SSH to come back, then runs the full acceptance suite.
Appends to logs/firmware/postboot-verify.txt so the earlier TIMEOUT is kept.

This waits on an external reboot, not a retry loop for a failing command.
"""
import os
import sys
import time
import logging
import paramiko

logging.getLogger('paramiko').setLevel(logging.CRITICAL)
logging.getLogger('paramiko.transport').setLevel(logging.CRITICAL)

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'
LOG = os.path.join('logs', 'firmware', 'postboot-verify.txt')
MAX_POLLS = 900           # ~8 s each => ~2 h
POLL_SLEEP = 8
UPTIME_LIMIT = 3600       # a fresh boot will have uptime well under 1 h

DSP = '/usr/share/qcom/dsp/cdsp'
PIL = '/lib/firmware/qcom/sm8150/Xiaomi/raphael'

NEW_MDT = '4b82459c883f4d9b75cc41c916db41c5c982c3e299c74fa59a550cf8d6f62177'
NEW_SHELL = 'f94a206286adc2aa17df70c9468884702445e0490711adeefbdb26a05c25ef31'
OLD_MDT = 'c87b5fa07e97cb03895936f80bef7f74e4dcff8680084466cb7efae4e21eec87'
OLD_SHELL = '1d03f6ca76c2d2d21142ef50bedb52dbfe10356afa5168295f8dd8205f2afd43'

ACCEPT = [
    ('identity', 'uptime; echo ---; cat /proc/uptime; echo ---; cat /proc/cmdline'),
    ('firmware-version', "echo '== PIL mdt / b02 / b05 =='; sha256sum %s/cdsp.mdt %s/cdsp.b02 %s/cdsp.b05; "
                         "echo '== unsigned shell =='; sha256sum %s/fastrpc_shell_unsigned_3; "
                         "echo '== build ids =='; grep -a -o -E "
                         "'[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}' %s/fastrpc_shell_unsigned_3 | sort -u | head -5; "
                         "grep -a -o -E 'CDSP.HT.2.0.1.{0,80}' %s/cdsp.b05 | head -3" %
                         (PIL, PIL, PIL, DSP, DSP, PIL)),
    ('kernel-log', "journalctl -b -k --no-pager 2>/dev/null | grep -iE "
                   "'cdsp|q6v5|qcom_mdt|remoteproc|pas_|scm|firmware|auth|rollback|failed' | tail -100"),
    ('pas-errors', "dmesg 2>/dev/null | grep -iE 'cdsp|pas|mdt|auth|rollback|failed to load' | tail -60"),
    ('state', "echo '== remoteproc =='; cat /sys/class/remoteproc/remoteproc0/state 2>&1; "
              "echo '== devnodes =='; ls -l /dev/fastrpc-cdsp* 2>&1; "
              "echo '== daemon =='; systemctl is-active cdsprpcd 2>&1; "
              "echo '== failed units =='; systemctl --failed --no-pager 2>&1 | head -20"),
    ('host-main', "cd /data/local/tmp/hvx && timeout 90 env LD_LIBRARY_PATH=/usr/local/lib "
                  "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
                  "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
                  "./host_main 2>&1 | tail -50; echo HOST_MAIN_RC=$?"),
    ('fastrpc-test', "timeout 90 env LD_LIBRARY_PATH=/usr/local/lib "
                     "ADSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
                     "DSP_LIBRARY_PATH='/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx' "
                     "fastrpc_test -d 3 -U 1 2>&1 | tail -40; echo FASTRPC_TEST_RC=$?"),
]


def probe():
    """Return uptime seconds if SSH is fully usable, else None. Quiet on failure."""
    c = None
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username=USER, password=PASSWORD, timeout=5,
                  look_for_keys=False, allow_agent=False,
                  banner_timeout=4, auth_timeout=5)
        ch = c.get_transport().open_session(timeout=5)
        ch.close()
        _in, out, err = c.exec_command('cat /proc/uptime', timeout=8)
        up = float(out.read().decode().split()[0])
        c.close()
        return up
    except Exception:
        try:
            if c:
                c.close()
        except Exception:
            pass
        return None


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    lines = ['', '=' * 70,
             'POST-REBOOT WATCHER RUN 2  started %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
             'max wait ~%d s; previous run timed out with no SSH banner' % (MAX_POLLS * POLL_SLEEP),
             '']
    print('watching for device (max ~%d min) ...' % (MAX_POLLS * POLL_SLEEP // 60), flush=True)
    up = None
    for i in range(MAX_POLLS):
        up = probe()
        if up is not None and up < UPTIME_LIMIT:
            print('DEVICE BACK at poll %d, uptime=%.0f s' % (i, up), flush=True)
            break
        if i % 15 == 0:
            print('  poll %3d (~%d min): ssh %s' %
                  (i, i * POLL_SLEEP // 60,
                   'not ready' if up is None else 'old session (up=%.0f)' % up), flush=True)
        time.sleep(POLL_SLEEP)
    else:
        msg = 'TIMEOUT RUN 2: still no SSH after ~%d s' % (MAX_POLLS * POLL_SLEEP)
        print(msg, flush=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write('\n'.join(lines + [msg]) + '\n')
        return 2

    lines.append('device uptime at acceptance: %.0f s' % up)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    for label, cmd in ACCEPT:
        print('\n===== %s =====' % label, flush=True)
        lines.append('\n===== %s =====\nCMD: %s' % (label, cmd))
        try:
            _in, out, err = c.exec_command(cmd, timeout=150)
            o = out.read().decode(errors='replace')
            e = err.read().decode(errors='replace')
            rc = out.channel.recv_exit_status()
        except Exception as ex:
            o, e, rc = '', repr(ex), -1
        text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
        sys.stdout.write(text[:16000])
        print('\n[rc=%d]' % rc, flush=True)
        lines.append('RC: %d\n%s' % (rc, text))
        if label == 'firmware-version':
            is_new = (NEW_MDT in o and NEW_SHELL in o)
            is_old = (OLD_MDT in o and OLD_SHELL in o)
            verdict = ('NEW 2021-07-30 FIRMWARE IN PLACE' if is_new else
                       'ROLLED BACK to 2020 baseline' if is_old else
                       'MIXED / UNKNOWN firmware state - inspect manually')
            print('>>> VERDICT: ' + verdict, flush=True)
            lines.append('>>> VERDICT: ' + verdict)
    c.close()
    lines.append('\nfinished %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\nAppended -> ' + LOG, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
