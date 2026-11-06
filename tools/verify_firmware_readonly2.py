#!/usr/bin/env python3
"""Round-2 READ-ONLY forensics: PIL ELF phdr comparison + ESP/rEFInd locator.

Downloads only two tiny files (cdsp.mdt 7580 B, cdsp.b00 436 B) from the device.
Everything else is a read-only shell command.  No device file is modified.
"""
import os
import sys
import hashlib
import struct
import paramiko

HOST, USER, PASSWORD = '172.16.42.1', 'root', '<REDACTED>'
FW = os.path.join('tmp', 'firmware')
PIL = os.path.join(FW, 'raphael-20210730', 'pil')
BASE = os.path.join(FW, 'baseline-v1.3')
LOGDIR = os.path.join('logs', 'firmware')

REMOTE_PIL = '/lib/firmware/qcom/sm8150/Xiaomi/raphael/'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def phdrs(data):
    """Parse ELF32 program headers (Hexagon QDSP6 is ELF32 LE)."""
    if data[:4] != b'\x7fELF':
        return None, 'not ELF'
    e_phoff, = struct.unpack_from('<I', data, 28)
    e_phentsize, e_phnum = struct.unpack_from('<HH', data, 42)
    rows = []
    for i in range(e_phnum):
        off = e_phoff + i * e_phentsize
        p_type, p_offset, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = \
            struct.unpack_from('<IIIIIIII', data, off)
        rows.append((i, p_type, p_offset, p_filesz, p_flags, p_align))
    return rows, None


def dump(name, data, limit=436):
    rows, err = phdrs(data)
    print('\n--- %s (%d bytes, sha=%s) ---' % (name, len(data), sha(data)))
    print('  first %d bytes sha = %s' % (limit, sha(data[:limit])))
    if err:
        print('  phdr: ' + err)
        return
    print('  %-3s %-10s %-12s %-12s %-12s' % ('#', 'type', 'offset', 'filesz', 'flags'))
    for i, t, o, f, fl, a in rows:
        print('  %-3d 0x%-8x 0x%-10x %-12d 0x%-10x align=0x%x' % (i, t, o, f, fl, a))


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASSWORD, timeout=12,
              look_for_keys=False, allow_agent=False,
              banner_timeout=15, auth_timeout=15)
    ch = c.get_transport().open_session(timeout=10)
    ch.close()
    return c


def run(c, cmd, label, timeout=90):
    print('\n===== %s =====' % label)
    try:
        _in, out, err = c.exec_command(cmd, timeout=timeout)
        o = out.read().decode(errors='replace')
        e = err.read().decode(errors='replace')
        rc = out.channel.recv_exit_status()
    except Exception as ex:
        o, e, rc = '', repr(ex), -1
    text = o + (('\n[STDERR]\n' + e) if e.strip() else '')
    sys.stdout.write(text[:14000])
    print('\n[rc=%d]' % rc)
    return text


def main():
    os.makedirs(LOGDIR, exist_ok=True)
    buf = []
    c = connect()
    print('ssh OK')

    # --- download the two tiny files ---
    sftp = c.open_sftp()
    for remote_name, local_name in [('cdsp.mdt', 'device-cdsp.mdt'),
                                    ('cdsp.b00', 'device-cdsp.b00')]:
        lp = os.path.join(FW, local_name)
        sftp.get(REMOTE_PIL + remote_name, lp)
        print('downloaded %s -> %s (%d B)' % (remote_name, lp, os.path.getsize(lp)))
    sftp.close()

    # --- read-only shell checks ---
    cmds = [
        ('pil-buildid', "for f in " + REMOTE_PIL + "cdsp.b*; do echo -n \"$f: \"; grep -a -o -E 'QC_IMAGE_VERSION_STRING.{0,80}' \"$f\" 2>/dev/null | head -1; grep -a -o -E '[0-9]{6,}\\.[0-9]+_[0-9]{8}_[0-9]{6}' \"$f\" 2>/dev/null | sort -u | head -3; done"),
        ('block-dev', "lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,MOUNTPOINT 2>&1 | head -60; echo ---; cat /proc/partitions; echo ---; ls -la /dev/disk/by-partlabel/ 2>&1 | head -40"),
        ('esp-locator', "echo '== likely ESP =='; for p in /dev/sda1 /dev/sda2 /dev/sda3 /dev/nvme0n1p1; do [ -b \"$p\" ] && echo \"$p $(blkid -o value -s TYPE $p 2>/dev/null) $(blkid -o value -s LABEL $p 2>/dev/null)\"; done; echo '== mounts =='; mount | head -30; echo '== efibootmgr =='; command -v efibootmgr || echo 'efibootmgr: not installed'; echo '== efivars =='; ls /sys/firmware/efi/efivars/ 2>&1 | head -20"),
        ('boot-marker', "echo '== /boot contents =='; find /boot -maxdepth 2 -printf '%p %s\\n' 2>/dev/null | head -40; echo '== refind conf anywhere =='; find / -maxdepth 4 -iname 'refind*.conf' -o -iname 'refind*.efi' 2>/dev/null | head -30"),
        ('secureboot', "for v in /sys/firmware/efi/efivars/SecureBoot-* /sys/firmware/efi/efivars/SetupMode-*; do [ -f \"$v\" ] && echo \"$v: $(od -An -tx1 \"$v\" | tail -1)\"; done; echo ---; dmesg 2>/dev/null | grep -iE 'secure|uefi|stub' | tail -10"),
    ]
    for label, cmd in cmds:
        buf.append('\n===== %s =====\nCMD: %s\n' % (label, cmd))
        buf.append(run(c, cmd, label))
    c.close()

    # --- local ELF comparison ---
    print('\n\n===== LOCAL BINARY FORENSICS =====')
    dev_mdt = open(os.path.join(FW, 'device-cdsp.mdt'), 'rb').read()
    dev_b00 = open(os.path.join(FW, 'device-cdsp.b00'), 'rb').read()
    new_mdt = open(os.path.join(PIL, 'CDSP.MDT'), 'rb').read()
    new_b00 = open(os.path.join(PIL, 'CDSP.B00'), 'rb').read()
    new_mbn = open(os.path.join(PIL, 'cdsp.mbn'), 'rb').read()

    print('device cdsp.mdt sha =', sha(dev_mdt))
    print('device cdsp.b00 sha =', sha(dev_b00))
    print('new    CDSP.MDT sha =', sha(new_mdt))
    print('new    CDSP.B00 sha =', sha(new_b00))
    print('new    cdsp.mbn sha =', sha(new_mbn))
    print('device mdt[:436] == new b00 ? ', dev_mdt[:436] == new_b00)
    print('device mdt[:436] == device b00 ? ', dev_mdt[:436] == dev_b00)
    print('new mdt[:436]    == new b00 ? ', new_mdt[:436] == new_b00)
    print('new mbn[:436]    == new b00 ? ', new_mbn[:436] == new_b00)
    print('device mdt[:436] == new mbn[:436] ? ', dev_mdt[:436] == new_mbn[:436])

    # find baseline mbn
    base_mbn = None
    for root, dirs, files in os.walk(BASE):
        for f in files:
            if f == 'cdsp.mbn':
                base_mbn = os.path.join(root, f)
                break
    if base_mbn:
        bm = open(base_mbn, 'rb').read()
        print('\nbaseline mbn:', base_mbn, len(bm), sha(bm))
        print('baseline mbn[:436] == device b00 ? ', bm[:436] == dev_b00)
        print('baseline mbn[:436] == new b00 ? ', bm[:436] == new_b00)
        print('baseline mbn[:436] == new mbn[:436] ? ', bm[:436] == new_mbn[:436])
        dump('BASELINE mbn (deb)', bm)
    else:
        print('\nbaseline cdsp.mbn NOT FOUND under', BASE)
        # list what is there
        for root, dirs, files in os.walk(BASE):
            rel = os.path.relpath(root, BASE)
            if any('cdsp' in f.lower() for f in files):
                print('  ', rel, [f for f in files if 'cdsp' in f.lower()])

    dump('DEVICE cdsp.mdt', dev_mdt)
    dump('NEW CDSP.MDT', new_mdt)
    dump('NEW rebuilt cdsp.mbn', new_mbn)

    # phdr filesz vs actual device bXX sizes
    rows, err = phdrs(dev_mdt)
    if not err:
        print('\n--- device phdr.filesz vs device bXX sizes (from round-1 audit) ---')
        dev_sizes = {0: 436, 1: 7144, 2: 227348, 3: 104284, 4: 1200,
                     5: 2710852, 6: 48596, 8: 209184, 10: 54932}
        for i, t, o, f, fl, a in rows:
            if f:
                print('  phdr[%2d] filesz=%-9d device b%02d=%-9s match=%s' %
                      (i, f, i, dev_sizes.get(i, '?'), dev_sizes.get(i) == f))

    with open(os.path.join(LOGDIR, 'readonly-audit2.txt'), 'w', encoding='utf-8') as f:
        f.write('ROUND-2 READ-ONLY AUDIT\n' + ''.join(buf))
    print('\nSaved ->', os.path.join(LOGDIR, 'readonly-audit2.txt'))


if __name__ == '__main__':
    main()
