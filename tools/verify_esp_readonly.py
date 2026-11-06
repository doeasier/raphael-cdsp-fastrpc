#!/usr/bin/env python3
"""ONE read-only mount of the ESP to inspect rEFInd config, then unmount.

Mounts /dev/sda30 read-only on the existing empty /mnt, inspects, unmounts in
a finally block.  No file on the ESP or rootfs is created or modified.
"""
import sys
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'

INSPECT = (
    "echo '== ESP tree (maxdepth 3) =='; "
    "find /mnt -maxdepth 3 -printf '%y %p %s\\n' 2>/dev/null | head -120; "
    "echo '== refind.conf menuentries =='; "
    "for f in $(find /mnt -maxdepth 4 -iname 'refind.conf' 2>/dev/null); do "
    "  echo \"--- $f ---\"; grep -nE 'menuentry|volume|loader|initrd|options|title|dtb|default_selection|timeout' \"$f\" | head -120; "
    "done; "
    "echo '== refind_linux.conf / all conf =='; "
    "for f in $(find /mnt -maxdepth 4 \\( -iname 'refind_linux.conf' -o -iname '*.conf' \\) 2>/dev/null | head -20); do "
    "  echo \"--- $f ---\"; head -50 \"$f\"; done; "
    "echo '== kernel / initrd / dtb files =='; "
    "find /mnt -maxdepth 4 \\( -iname 'vmlinuz*' -o -iname 'initrd*' -o -iname '*.dtb' -o -iname '*.efi' \\) -printf '%p %s\\n' 2>/dev/null | head -60"
)


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()

    def run(cmd, label, timeout=60):
        print('\n===== %s =====' % label)
        _in, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode(errors='replace')
        e = err.read().decode(errors='replace')
        rc = out.channel.recv_exit_status()
        sys.stdout.write(o[:16000])
        if e.strip():
            print('[STDERR] ' + e[:2000])
        print('[rc=%d]' % rc)
        return o, e, rc

    mounted = False
    try:
        o, e, rc = run('mount -t vfat -o ro /dev/sda30 /mnt 2>&1; echo MOUNT_RC=$?; mount | grep /mnt',
                       'mount ESP read-only')
        mounted = ('/dev/sda30' in o) or ('MOUNT_RC=0' in o)
        if mounted:
            o2, e2, rc2 = run(INSPECT, 'ESP contents')
        else:
            o2 = 'ESP readonly mount failed; skipping inspection\n'
            print(o2)
    finally:
        if mounted:
            run('umount /mnt 2>&1; echo UMOUNT_RC=$?; mount | grep -c " /mnt "', 'unmount ESP')
        c.close()

    with open('logs/firmware/readonly-esp.txt', 'w', encoding='utf-8') as f:
        f.write('READ-ONLY ESP INSPECTION (/dev/sda30)\n')
        f.write('mounted=%s\n' % mounted)
        if mounted:
            f.write(o2)
    print('\nSaved -> logs/firmware/readonly-esp.txt')


if __name__ == '__main__':
    main()
