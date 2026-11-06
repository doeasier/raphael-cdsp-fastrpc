#!/system/bin/sh
###############################################################################
# twrp_rollback.sh — 在 TWRP / recovery 里把 cDSP 固件恢复到 2021-07-30 替换前
#
# 适用：systemctl reboot 后系统进不去（SSH 不通），无法在 Ubuntu 里跑
#       /root/cdsp-rollback.sh 时。
# 用法（Windows 主机，TWRP 已启动且 adb 可用）：
#   adb push <WORKSPACE>/tmp/boot_probe/twrp_rollback.sh /tmp/
#   adb shell chmod +x /tmp/twrp_rollback.sh
#   adb shell /tmp/twrp_rollback.sh
#   adb reboot   (或手动重启；绝不 kexec)
#
# 前提：替换前的备份已在设备 rootfs 里（本次已生成）：
#   /root/cdsp-firmware-backup-20201211-pre-20210730.tar.gz
#   /root/cdsp-firmware-backup-20201211-pre-20210730/{pil,dsp,SHA256SUMS}
###############################################################################
set -e

MNT=/tmp/userdata
BKREL=root/cdsp-firmware-backup-20201211-pre-20210730
PILREL=usr/lib/firmware/qcom/sm8150/Xiaomi/raphael
DSPREL=usr/share/qcom/dsp/cdsp

echo "=== find userdata partition ==="
DEV=""
for d in /dev/block/sda31 /dev/block/by-name/userdata /dev/block/by-name/data; do
    if [ -b "$d" ]; then DEV="$d"; break; fi
done
[ -n "$DEV" ] || { echo "FATAL: userdata partition not found"; exit 1; }
echo "userdata = $DEV"

mkdir -p "$MNT"
mount -t ext4 -o rw "$DEV" "$MNT" || {
    echo "mount failed, trying remount"; umount "$MNT" 2>/dev/null || true
    mount -t ext4 -o rw "$DEV" "$MNT" || { echo "FATAL: cannot mount userdata"; exit 1; }
}

echo "=== verify backup exists ==="
ls -l "$MNT/root/cdsp-firmware-backup-20201211-pre-20210730.tar.gz" || {
    echo "FATAL: backup tar.gz missing"; umount "$MNT"; exit 1; }

echo "=== extract backup (idempotent) ==="
tar -xzf "$MNT/root/cdsp-firmware-backup-20201211-pre-20210730.tar.gz" -C "$MNT/root/"

echo "=== restore PIL (split mdt+bXX, lowercase) ==="
cp -a "$MNT/$BKREL/pil/." "$MNT/$PILREL/"
chmod 755 "$MNT/$PILREL"/cdsp.mdt "$MNT/$PILREL"/cdsp.b* "$MNT/$PILREL"/cdspr.jsn

echo "=== restore the 21 stock DSP libs (leave libhvx_add_skel.so alone) ==="
cp -a "$MNT/$BKREL/dsp/." "$MNT/$DSPREL/"
chmod 644 "$MNT/$DSPREL"/*

echo "=== verify ==="
( cd "$MNT/$BKREL" && sha256sum -c SHA256SUMS ) | tail -5 || \
    echo "WARNING: checksum mismatch - inspect manually"
echo "PIL now:"; ls -l "$MNT/$PILREL"/cdsp.mdt "$MNT/$PILREL"/cdsp.b02 "$MNT/$PILREL"/cdsp.b05
echo "shell now:"; sha256sum "$MNT/$DSPREL"/fastrpc_shell_unsigned_3

sync
umount "$MNT"
echo "=== ROLLBACK DONE. Now reboot normally (adb reboot / power menu). ==="
echo "=== Do NOT use kexec. ==="
