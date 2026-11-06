#!/system/bin/sh
###############################################################################
# twrp_add_rollback_entry.sh — 在 TWRP 里把「不加载任何 DSP 固件」的启动项设为默认
#
# 为什么需要：EFI/BOOT/refind.conf 是 `timeout -1`，默认立即启动第一项，
#   开机瞬间不按键根本看不到菜单。若新 cDSP 固件让启动期卡住，光有
#   「第二项可回滚」没用 —— 必须把带 modprobe.blacklist=qcom_q6v5_pas 的项放到第一行。
#
# 用法（TWRP 已启动且 adb 可用）：
#   adb push <WORKSPACE>/tmp/boot_probe/twrp_add_rollback_entry.sh /tmp/
#   adb shell chmod +x /tmp/twrp_add_rollback_entry.sh
#   adb shell /tmp/twrp_add_rollback_entry.sh
#   然后重启，系统应能进 multi-user（usb-ncm 未 mask，SSH 可用），再执行：
#     bash /root/cdsp-rollback.sh && systemctl reboot
#
# 撤销：把 boot 分区里的 refind_linux.conf.pre-fw-rollback 改回 refind_linux.conf。
#
# 注意：运行系统 `by-partlabel boot -> /dev/sde49`，而旧 TWRP 脚本用
#   /dev/block/sde53；编号会随启动环境变，脚本按候选顺序现场探测。
###############################################################################
set -e

MNT=/tmp/realboot
ENTRY='"Boot ROLLBACK (no DSP / restore files)"  "root=UUID=ee8d3593-59b1-480e-a3b6-4fefb17ee7d8 rw console=ttyMSM0,115200 console=tty0 loglevel=4 systemd.show_status=1 rd.systemd.show_status=1 systemd.log_level=info rd.udev.log_priority=info udev.log_priority=info plymouth.enable=0 panic=0 systemd.unit=multi-user.target modprobe.blacklist=qcom_q6v5_pas,qcom_q6v5_adsp,qcom_q6v5_mss,qcom_q6v5_common,qcom_sysmon,qcom_pil_info systemd.mask=hexagonrpcd-sdsp.service systemd.mask=hexagonrpcd-sdsp.path systemd.mask=raphael-sensors.service systemd.mask=raphael-sensors-persist-perms.service systemd.mask=raphael-slpi-client2slpi.service systemd.mask=raphael-slpi-bl-notify.service systemd.mask=raphael-slpi-oled-gate.service systemd.mask=raphael-gpsd-bridge.service systemd.mask=raphael-sim-init.service dtb=\dtbs\qcom\sm8150-xiaomi-raphael.dtb"'

echo "=== locate boot partition ==="
DEV=""
for d in /dev/block/by-name/boot /dev/block/sde49 /dev/block/sde53 /dev/block/sda30; do
    if [ -b "$d" ]; then echo "candidate: $d"; [ -z "$DEV" ] && DEV="$d"; fi
done
[ -n "$DEV" ] || { echo "FATAL: boot partition not found"; exit 1; }
echo "using $DEV"

mkdir -p "$MNT"
umount "$MNT" 2>/dev/null || true
OK=0
for fs in ext4 vfat; do
    if mount -t "$fs" -o rw "$DEV" "$MNT" 2>/dev/null; then echo "mounted as $fs"; OK=1; break; fi
done
[ "$OK" = 1 ] || { echo "FATAL: cannot mount boot partition"; exit 1; }

echo "=== locate refind_linux.conf ==="
CONF=""
for p in "$MNT/refind_linux.conf" "$MNT/EFI/BOOT/refind_linux.conf"; do
    [ -f "$p" ] && CONF="$p" && break
done
if [ -z "$CONF" ]; then
    CONF=$(find "$MNT" -maxdepth 3 -iname 'refind_linux.conf' 2>/dev/null | head -1)
fi
[ -n "$CONF" ] || { echo "FATAL: refind_linux.conf not found"; umount "$MNT"; exit 1; }
echo "config = $CONF"

echo "=== back up original ==="
if [ ! -f "$CONF.pre-fw-rollback" ]; then
    cp -a "$CONF" "$CONF.pre-fw-rollback"
else
    echo "backup already exists, keeping it"
fi

echo "=== put the no-DSP entry FIRST (timeout -1 boots entry 1) ==="
if grep -q 'Boot ROLLBACK (no DSP' "$CONF"; then
    echo "rollback entry already present; promoting it to first line"
    grep -v 'Boot ROLLBACK (no DSP' "$CONF" > "$CONF.tmp"
else
    cp "$CONF" "$CONF.tmp"
fi
{
    printf '%s\n' "$ENTRY"
    cat "$CONF.tmp"
} > "$CONF.new"
mv "$CONF.new" "$CONF"
rm -f "$CONF.tmp"
chmod 644 "$CONF"

echo "=== new first lines ==="
head -3 "$CONF"
sync
umount "$MNT"
echo "=== DONE. Reboot now; after SSH works run: bash /root/cdsp-rollback.sh ==="
echo "=== Then restore the original boot order: mv refind_linux.conf.pre-fw-rollback refind_linux.conf ==="
