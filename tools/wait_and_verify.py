#!/usr/bin/env python3
"""Wait for the post-reboot device to come back, then run the acceptance suite.

Bounded poll (max ~20 min).  Saves everything to logs/firmware/postboot-verify.txt.
This is waiting on an external reboot, not a retry loop for a failing command.
"""
import os
import sys
import time
import socket
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'
LOG = os.path.join('logs', 'firmware', 'postboot-verify.txt')
MAX_POLLS = 120          # 10 s each
UPTIME_LIMIT = 1500      # seconds; reboot issued 21:40:41, old uptime was ~9720 s

DSP = '/usr/share/qcom/dsp/cdsp'
PIL = '/lib/firmware/qcom/sm8150/Xiaomi/raphael'

ACCEPT = [
    ('identity', 'uptime; echo ---; cat /proc/uptime; echo ---; cat /proc/cmdline'),
    ('kernel-log', "journalctl -b -k --no-pager 2>/dev/null | grep -iE "
                   "'cdsp|q6v5|qcom_mdt|remoteproc|pas_|scm|firmware|auth|rollback|failed' | tail -100"),
    ('pas-errors', "dmesg 2>/dev/null | grep -iE 'cdsp|pas|mdt|auth|rollback|failed to load' | tail -60"),
    ('state', "echo '== remoteproc =='; cat /sys/class/remoteproc/remoteproc0/state 2>&1; "
              "echo '== devnodes =='; ls -l /dev/fastrpc-cdsp* 2>&1; "
              "echo '== daemon =='; systemctl is-active cdsprpcd 2>&1; "
              "echo '== failed units =='; systemctl --failed --no-pager 2>&1 | head -20"),
    ('buildid', "echo '== shell build id =='; grep -a -o -E "
                "'[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}' %s/fastrpc_shell_unsigned_3 | sort -u | head -5; "
                "echo '== PIL version =='; grep -a -o -E 'CDSP.HT.2.0.1.{0,80}' %s/cdsp.b05 | head -4; "
                "echo '== QC_IMAGE_VERSION_STRING =='; grep -a -o -E "
                "'QC_IMAGE_VERSION_STRING.{0,80}' %s/cdsp.b05 | head -2" % (DSP, PIL, PIL)),
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
    """Return uptime seconds if SSH is fully usable, else None."""
    try:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username=USER, password=PASSWORD, timeout=8,
                  look_for_keys=False, allow_agent=False,
                  banner_timeout=10, auth_timeout=10)
        ch = c.get_transport().open_session(timeout=8)
        ch.close()
        _in, out, err = c.exec_command('cat /proc/uptime', timeout=10)
        up = float(out.read().decode().split()[0])
        c.close()
        return up
    except Exception as ex:
        return None


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    lines = ['POST-REBOOT ACCEPTANCE  started %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
             'reboot was issued at 21:40:41; old uptime was ~9720 s', '']
    print('waiting for device ...', flush=True)
    up = None
    for i in range(MAX_POLLS):
        up = probe()
        if up is not None and up < UPTIME_LIMIT:
            print('device back, uptime=%.0f s after %d polls' % (up, i), flush=True)
            break
        if i % 6 == 0:
            print('  poll %d: %s' % (i, 'ssh not ready' if up is None else
                                     'still old session (uptime=%.0f)' % up), flush=True)
        time.sleep(10)
    else:
        msg = 'TIMEOUT: device did not come back within %d s' % (MAX_POLLS * 10)
        print(msg, flush=True)
        lines.append(msg)
        open(LOG, 'w', encoding='utf-8').write('\n'.join(lines))
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
    c.close()
    lines.append('\nfinished %s' % time.strftime('%Y-%m-%d %H:%M:%S'))
    with open(LOG, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    print('\nSaved -> ' + LOG, flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
