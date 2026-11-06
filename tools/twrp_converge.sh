#!/bin/sh
# TWRP 下一次性执行：先读日志完成定性，再解除 usb-ncm.service 的 mask 恢复 USB 网络。
# 阶段 1 只改这一个变量，DSP 屏蔽全部保留 —— 解封 qcom_q6v5_pas 会启动 modem，
# 而 SM8150 mainline 的 WLAN PD 已知能把整个 SoC fabric 锁死（见 refind 注释）。
# 阶段 2（DT 只留 cdsp + compute-cb dma-coherent）等联网后在线做，不在本脚本内。
#
# 前提：手机在 TWRP，USB 数据线已连，adb devices 能看到 recovery。
# 用法：bash tmp/boot_probe/twrp_converge.sh
# 改动全部有 .bak.20261105d 备份，随时可回滚；脚本不会自动重启手机。

ADB="/d/Tools/Mindows工具箱V8/bin/tool/Windows/adb.exe"
cd /f/work/WorkBuddy/k20pro || exit 1

echo "========== 0. adb state =========="
"$ADB" devices -l || exit 1

echo "========== 1. mount userdata(/data) + vendor(/boot) =========="
"$ADB" shell '
mkdir -p /tmp/data /tmp/realboot
mount -t ext4 /dev/block/sda31 /tmp/data 2>/dev/null
mount -t ext4 /dev/block/sde53 /tmp/realboot 2>/dev/null
ls /tmp/data/etc/fstab /tmp/realboot/refind_linux.conf
'

echo "========== 2. 定性：本次启动的 cmdline / 是否到达 multi-user =========="
bash tmp/boot_probe/twrp_check.sh

echo "========== 3. 备份（务必确认输出里有 .bak.20261105d） =========="
"$ADB" shell '
cp /tmp/realboot/refind_linux.conf /tmp/realboot/refind_linux.conf.bak.20261105d
cp /tmp/data/etc/modprobe.d/99-raphael-dsp-debug.conf /tmp/data/etc/modprobe.d/99-raphael-dsp-debug.conf.bak.20261105d
ls -l /tmp/realboot/refind_linux.conf* /tmp/data/etc/modprobe.d/99-raphael-dsp-debug.conf*
'

echo "========== 4. push 收敛配置（阶段1 只改 refind，modprobe.d 保持不动） =========="
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' "$ADB" push tmp/boot_probe/refind_linux.conf.converged /tmp/refind.converged || exit 1
"$ADB" shell '
cp /tmp/refind.converged /tmp/realboot/refind_linux.conf
chmod 644 /tmp/realboot/refind_linux.conf
'

echo "========== 5. 恢复 usb-ncm.service 自启 symlink =========="
"$ADB" shell '
if [ -f /tmp/data/etc/systemd/system/usb-ncm.service ]; then
  UNIT=/etc/systemd/system/usb-ncm.service
elif [ -f /tmp/data/lib/systemd/system/usb-ncm.service ]; then
  UNIT=/lib/systemd/system/usb-ncm.service
else
  UNIT=
  echo "WARN: usb-ncm.service unit not found, skip symlink"
fi
if [ -n "$UNIT" ]; then
  mkdir -p /tmp/data/etc/systemd/system/multi-user.target.wants
  ln -sf "$UNIT" /tmp/data/etc/systemd/system/multi-user.target.wants/usb-ncm.service
  echo "linked: $UNIT"
fi
ls -l /tmp/data/etc/systemd/system/multi-user.target.wants/usb-ncm.service 2>/dev/null
echo "--- timeout drop-in (should still exist) ---"
cat /tmp/data/etc/systemd/system/usb-ncm.service.d/timeout.conf 2>/dev/null
'

echo "========== 6. 校验 =========="
"$ADB" shell '
echo "--- refind entries ---"
grep "^\"Boot" /tmp/realboot/refind_linux.conf | cut -c1-70
echo "--- modprobe.d active ---"
grep -vE "^#|^$" /tmp/data/etc/modprobe.d/99-raphael-dsp-debug.conf
echo "--- fstab active ---"
grep -vE "^#|^$" /tmp/data/etc/fstab
echo "--- DTB state (阶段1 不动 DTB) ---"
if cmp -s /tmp/realboot/dtbs/qcom/sm8150-xiaomi-raphael.dtb /tmp/realboot/dtbs/qcom/sm8150-xiaomi-raphael.dtb.orig; then echo DTB_ORIGINAL; else echo DTB_DIFFERENT; fi
sync
'

echo "========== DONE =========="
echo "预期：Wi-Fi 仍不可用（qcom_q6v5_pas 仍屏蔽），网络唯一通道 = USB-NCM 172.16.42.1。"
echo "下一步：在 TWRP 里执行  adb reboot  （或手动重启到系统），不要进 kexec。"
echo "起来后主机侧运行： powershell -ExecutionPolicy Bypass -File scripts/host/usb-ncm-up.ps1 -WaitSec 90"
echo "联网后阶段 2：核对 DTB remoteproc 节点 -> 只留 cdsp -> 补 dma-coherent -> 正常 reboot -> 跑 D8。"
