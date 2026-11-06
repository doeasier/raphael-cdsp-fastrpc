#!/usr/bin/env python3
"""READ-ONLY pre-deployment audit for the 2021-07-30 cDSP firmware swap.

Runs over USB-NCM SSH (root@172.16.42.1).  Every command below is strictly
read-only: no writes, no service changes, no reboots.  Results are saved to
logs/firmware/readonly-audit.txt for the record.
"""
import os
import sys
import time
import paramiko

HOST = '172.16.42.1'
USER = 'root'
PASSWORD = '<REDACTED>'
LOGDIR = os.path.join('logs', 'firmware')
OUTFILE = os.path.join(LOGDIR, 'readonly-audit.txt')

CHECKS = [
    ('identity', "uname -a; echo ---; head -4 /etc/os-release; echo ---; uptime; echo ---; cat /proc/cmdline"),
    ('usrmerge', "ls -ld /lib /usr/lib; echo ---; readlink -f /lib/firmware; echo ---; readlink -f /usr/share/qcom/dsp/cdsp"),
    ('pil-dir', "echo '== /lib/firmware/qcom/sm8150/Xiaomi/raphael =='; ls -la /lib/firmware/qcom/sm8150/Xiaomi/raphael/ 2>&1; echo '== any cdsp* under /lib/firmware/qcom =='; find /lib/firmware/qcom -maxdepth 4 -iname 'cdsp*' -printf '%p %s bytes\\n' 2>/dev/null | sort"),
    ('pil-sha', "cd /lib/firmware/qcom/sm8150/Xiaomi/raphael/ 2>/dev/null && sha256sum * 2>/dev/null | sort -k2"),
    ('dsp-dir', "echo '== /usr/share/qcom/dsp/cdsp =='; ls -la /usr/share/qcom/dsp/cdsp/ 2>&1; echo '== /usr/lib/dsp/cdsp =='; ls -la /usr/lib/dsp/cdsp/ 2>&1 | head -30; echo '== /usr/lib/rfsa/adsp =='; ls -la /usr/lib/rfsa/adsp/ 2>&1 | head -30"),
    ('dsp-sha', "cd /usr/share/qcom/dsp/cdsp/ 2>/dev/null && sha256sum * 2>/dev/null | sort -k2"),
    ('shell-buildid', "for f in /usr/share/qcom/dsp/cdsp/fastrpc_shell_3 /usr/share/qcom/dsp/cdsp/fastrpc_shell_unsigned_3; do echo \"== $f ==\"; grep -a -o -E 'QC_IMAGE_VERSION_STRING.{0,90}' \"$f\" 2>/dev/null | head -2; grep -a -o -E '[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}' \"$f\" 2>/dev/null | sort -u | head -6; done"),
    ('remoteproc', "for f in /sys/class/remoteproc/remoteproc*/name; do echo \"$f = $(cat $f 2>/dev/null)\"; done; echo ---; for f in /sys/class/remoteproc/remoteproc*/state; do echo \"$f = $(cat $f 2>/dev/null)\"; done; echo ---; ls -l /dev/fastrpc-* /dev/adsprpc-* 2>&1"),
    ('daemon', "systemctl is-active cdsprpcd 2>&1; systemctl is-enabled cdsprpcd 2>&1; echo ---; systemctl show cdsprpcd -p ExecStart -p Environment -p FragmentPath --no-pager 2>&1 | head -30; echo ---; ls -la /etc/systemd/system/cdsprpcd.service.d/ 2>&1"),
    ('boot-efi', "echo '== mounts =='; mount | grep -iE 'efi|boot' | head -10; echo '== /boot =='; ls -la /boot/ 2>&1 | head -40; echo '== /boot/efi/EFI =='; ls -la /boot/efi/EFI/ 2>&1 | head -20; echo '== refind =='; ls -la /boot/efi/EFI/refind/ 2>&1 | head -30"),
    ('refind-conf', "for f in /boot/efi/EFI/refind/refind.conf /boot/refind_linux.conf /boot/efi/EFI/refind/refind_linux.conf /etc/refind_linux.conf; do if [ -f \"$f\" ]; then echo \"===== $f =====\"; grep -nE 'menuentry|volume|loader|initrd|options|title|dtb' \"$f\" | head -80; fi; done; echo '== all refind_linux.conf =='; find /boot /boot/efi -iname 'refind_linux.conf' -o -iname '*.efi' 2>/dev/null | head -40"),
    ('secureboot', "mokutil --sb-state 2>&1 | head -5; echo ---; dmesg 2>/dev/null | grep -iE 'secure boot|efi:' | tail -6"),
    ('space', "df -h / /boot /boot/efi /root 2>&1; echo ---; ls -ld /root/cdsp-firmware-backup* /root/cdsp-20210730-staging* 2>&1; echo ---; ls -la /root/ 2>&1 | head -40"),
    ('pkg', "dpkg -l 2>/dev/null | grep -iE 'firmware-xiaomi|linux-image|linux-headers' | head -20; echo '== dpkg -V =='; dpkg -V firmware-xiaomi-raphael 2>&1 | head -20"),
    ('kernel-log', "journalctl -b -k --no-pager 2>/dev/null | grep -iE 'cdsp|q6v5|qcom_mdt|remoteproc|pas_|scm' | tail -60"),
    ('farf-cache', "find / -maxdepth 6 -name '*.farf' -o -name '.farf' 2>/dev/null | head -30; echo ---; ls -la /data/local/tmp/hvx/ 2>&1 | head -20"),
]


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    # explicit session probe: this is where the earlier logind/PAM stall showed up
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    return c


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    buf = []
    print('connecting to %s ...' % HOST)
    c = connect()
    print('ssh OK\n')
    for label, cmd in CHECKS:
        print('===== %s =====' % label)
        buf.append('\n===== %s =====\nCMD: %s\n' % (label, cmd))
        try:
            _in, out, err = c.exec_command(cmd, timeout=90)
            o = out.read().decode(errors='replace')
            e = err.read().decode(errors='replace')
            rc = out.channel.recv_exit_status()
            text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
        except Exception as ex:
            text = '[EXCEPTION] %r\n' % (ex,)
            rc = -1
        buf.append('RC: %d\n%s\n' % (rc, text))
        sys.stdout.write(text[:12000])
        print('\n[rc=%d]' % rc)
    c.close()
    with open(OUTFILE, 'w', encoding='utf-8') as f:
        f.write('READ-ONLY AUDIT %s\nHOST %s\n%s\n' %
                (time.strftime('%Y-%m-%d %H:%M:%S'), HOST, ''.join(buf)))
    print('\nSaved -> %s' % OUTFILE)


if __name__ == '__main__':
    main()
