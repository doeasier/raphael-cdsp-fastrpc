#!/bin/sh
# One-shot diagnostic to run once the phone is back in TWRP.
ADB="/d/Tools/Mindows工具箱V8/bin/tool/Windows/adb.exe"
"$ADB" shell '
mkdir -p /tmp/data /tmp/realboot
mount -t ext4 /dev/block/sda31 /tmp/data 2>/dev/null
mount -t ext4 /dev/block/sde53 /tmp/realboot 2>/dev/null
echo "===== newest journal files (how many boot cycles?) ====="
ls -lat /tmp/data/var/log/journal/*/ | head -12
echo "===== boot markers (did we ever reach basic/multi-user?) ====="
cat /tmp/data/var/log/boot-marker.txt 2>/dev/null || echo "[none]"
echo "===== fstab active lines ====="
grep -vE "^#|^$" /tmp/data/etc/fstab
echo "===== active refind boot entries ====="
grep "^\"Boot" /tmp/realboot/refind_linux.conf | cut -c1-90
'
J=$(MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' "$ADB" shell 'ls -t /tmp/data/var/log/journal/*/system.journal | head -1' | tr -d '\r')
echo "NEWEST_JOURNAL=$J"
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' "$ADB" pull "$J" tmp/boot_probe/latest.journal 2>&1 | tail -1
python3 -c "
import re
b=open('tmp/boot_probe/latest.journal','rb').read().decode('ascii','replace')
m=re.search(r'MESSAGE=Kernel command line: ([^\x00]{0,900})',b)
print('KERNEL_CMDLINE:', m.group(1)[:900] if m else 'NOT FOUND')
print('has modprobe.blacklist:', 'modprobe.blacklist' in b)
print('has console=tty0:', 'console=tty0' in b)
msgs=[x.group(0)[8:200] for x in re.finditer(r'MESSAGE=[\x20-\x7e]{8,}',b)]
print('--- last 25 messages ---')
for x in msgs[-25:]: print('  ',x)
"
