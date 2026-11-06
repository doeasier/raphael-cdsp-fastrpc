#!/bin/sh
# 修复 cDSP root-PD shell 搜索路径，然后重启 cdsprpcd。
# 根因：libcdsprpc 用 ADSP_LIBRARY_PATH(";" 分隔) 找 fastrpc_shell_unsigned_3，
# 默认路径 /usr/lib/rfsa/adsp、/usr/lib/dsp、/vendor/dsp 在本机都不存在，
# 而 shell 实际装在 /usr/share/qcom/dsp/cdsp/。

set -x

mkdir -p /usr/lib/rfsa/adsp /usr/lib/dsp /vendor/dsp
for f in /usr/share/qcom/dsp/cdsp/*; do
    ln -sf "$f" /usr/lib/rfsa/adsp/ 2>/dev/null
done
ln -sf /data/local/tmp/hvx/libhvx_add_skel.so /usr/lib/rfsa/adsp/

mkdir -p /etc/systemd/system/cdsprpcd.service.d
cat > /etc/systemd/system/cdsprpcd.service.d/10-searchpath.conf <<'EOF'
[Service]
Environment="ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx"
Environment="DSP_LIBRARY_PATH=/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx"
EOF
chmod 644 /etc/systemd/system/cdsprpcd.service.d/10-searchpath.conf

systemctl daemon-reload
systemctl restart cdsprpcd.service
sleep 3

echo "### cdsprpcd status"
systemctl is-active cdsprpcd.service
ps -o pid,stat,wchan:28,cmd -p "$(pgrep -f '/usr/local/sbin/cdsprpcd' | head -1)"
echo "### search-path links (first 20)"
ls -l /usr/lib/rfsa/adsp/ | head -20
echo "### shells now visible"
ls -l /usr/lib/rfsa/adsp/fastrpc_shell* 2>&1
echo "### fastrpc_test skels present?"
find / -name 'libhap_example_skel.so' -o -name 'libcalculator_skel.so' 2>/dev/null | head -10

echo "### SMOKE fastrpc_test -d 3 -U 1"
timeout 75 fastrpc_test -d 3 -U 1 > /tmp/ft-stage2.log 2>&1
echo "FS_RC=$?"
tail -40 /tmp/ft-stage2.log
