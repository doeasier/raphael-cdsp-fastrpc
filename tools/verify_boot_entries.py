#!/usr/bin/env python3
"""READ-ONLY UEFI/rEFInd locator.  No mounts, no writes."""
import sys
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'

CMDS = [
    ('efibootmgr', "efibootmgr -v 2>&1; echo ---; efibootmgr 2>&1"),
    ('vfat-parts', "echo '== vfat filesystems =='; blkid 2>/dev/null | grep -iE 'vfat|fat16|fat32' | head -30; echo '== by-partlabel esp/efi/boot =='; find /dev/disk/by-partlabel -maxdepth 1 -printf '%f -> %l\\n' 2>/dev/null | grep -iE 'esp|efi|boot|uefi|refind' | head -30; echo '== all partlabels tail =='; find /dev/disk/by-partlabel -maxdepth 1 -printf '%f -> %l\\n' 2>/dev/null | tail -40"),
    ('boot-vars', "for v in /sys/firmware/efi/efivars/Boot* /sys/firmware/efi/efivars/BootOrder-*; do echo \"== $v ==\"; od -An -c \"$v\" 2>/dev/null | head -12; done"),
    ('efi-apps', "echo '== any refind / efi files on mounted fs =='; find / -xdev -maxdepth 5 \\( -iname 'refind*.efi' -o -iname 'refind.conf' -o -iname 'refind_linux.conf' -o -iname 'vmlinuz*' -o -iname 'initrd.img*' \\) -printf '%p %s\\n' 2>/dev/null | head -40"),
    ('firmware-name', "echo '== remoteproc firmware-name from DT =='; for p in /sys/firmware/devicetree/base/remoteproc* /sys/firmware/devicetree/base/soc@0/remoteproc*; do [ -d \"$p\" ] || continue; echo \"$p\"; for a in compatible firmware-name; do [ -f \"$p/$a\" ] && echo \"  $a: $(tr -d '\\0' < \"$p/$a\")\"; done; done; echo '== /sys/module/qcom_q6v5_pas =='; ls /sys/module/qcom_q6v5_pas/ 2>&1 | head"),
]


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    out_all = []
    for label, cmd in CMDS:
        print('\n===== %s =====' % label)
        _in, out, err = c.exec_command(cmd, timeout=90)
        o = out.read().decode(errors='replace')
        e = err.read().decode(errors='replace')
        rc = out.channel.recv_exit_status()
        text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
        sys.stdout.write(text[:14000])
        print('\n[rc=%d]' % rc)
        out_all.append('===== %s =====\nCMD: %s\nRC: %d\n%s\n' % (label, cmd, rc, text))
    c.close()
    with open('logs/firmware/readonly-boot.txt', 'w', encoding='utf-8') as f:
        f.write('READ-ONLY UEFI/BOOT AUDIT\n' + ''.join(out_all))
    print('\nSaved -> logs/firmware/readonly-boot.txt')


if __name__ == '__main__':
    main()
