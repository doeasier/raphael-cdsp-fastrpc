# raphael / SM8150 — Hexagon 690 cDSP Unsigned PD on mainline Linux

> **Self-archive, 2026-11-06.** 本仓库把一次完整、可回滚、A/B 可复核的实验结果固定下来，
> 目的是防止上游 issue 沉底后证据失联，并为后续向上游提交报告提供可引用的永久链接。
> **厂商固件二进制不在本仓库分发**（许可原因），只包含文档、日志、示例源码与复现脚本。

## TL;DR (EN)

On a Redmi K20 Pro / Mi 9T Pro (**raphael**, SM8150, Hexagon 690 / V66 cDSP) running a
**mainline Linux 7.0** kernel with an Ubuntu 24.04 rootfs, `FASTRPC_IOCTL_INIT_CREATE` on
`/dev/fastrpc-cdsp` (`domain=3`, Unsigned PD) consistently failed with
**`AEE_EBADASID` (`0x80000453`)**. The device had a **mismatched DSP set**: a
`00131`-branch PIL (`cdsp.mdt` + `cdsp.b00..b10`, 2020-12) paired with a
`00171`-branch `fastrpc_shell_unsigned_3` from 2020-12. Replacing the **entire matched set**
with the 2021-07-30 MIUI China Stable `V12.5.6.0.RFKCNXM` build (split PIL + 21 files under
`/usr/share/qcom/dsp/cdsp/`) and doing one cold `systemctl reboot` made PAS authentication
succeed, cDSP `running`, `fastrpc_test -d 3 -U 1` **3/3 PASS**, and a hand-written
`libhvx_add_skel.so` verify **1000/1000** HVX vector-add results
(`host: PASS - all 1000 elements verified correct.`).

**No kernel patch, no `fastrpc.ko` rebuild, no userspace-library change, no partition flash
was needed.** The earlier plan to rebuild the kernel (K5/K6/K7) was cancelled.

## 结果矩阵

| | 替换前 | 替换后 |
|---|---|---|
| PIL 固件 | `CDSP.HT.2.0.1-**00131**-SM8150-1`（2020-12 老分支，split `cdsp.mdt`+`bXX`） | `CDSP.HT.2.0.1-**00171**-SM8150-1.357350.2.419065.1_20210730_070147` |
| `fastrpc_shell_unsigned_3` | 933772 B，sha256 `1d03f6ca…`（`357350.2_20201211_224311`） | 935256 B，sha256 `f94a2062…`（同 build，另有 signed shell 939664 B `f12bf733…`） |
| 配套关系 | ❌ PIL 与 shell **不同 build** | ✅ PIL + shells + skels 全部同一 DSP build |
| `INIT_CREATE` | `0x80000453 AEE_EBADASID` | 成功 |
| `fastrpc_test -d 3 -U 1` | 全 FAIL | **3/3 PASS**（`Sum = 499500`、`Max value = 999`） |
| 自写 skel / `host_main` | 无法创建 user PD | `host: PASS - all 1000 elements verified correct.` |
| 内核 / 模块 | 7.0.0-sm8150 `fastrpc` builtin | **完全未改动** |

`AEE_EBADASID` 的数值来源公开可查：`inc/AEEStdErr.h` 中 DSP 侧
`AEE_EOFFSET = 0x80000400`、`AEE_EBADASID = AEE_EOFFSET + 0x053` → `0x80000453`。
`qualcomm/fastrpc#400` 的维护者评论也给出了机制依据：

> "Both shell and firmware files need to come from the same DSP build…"
> "There is a hash-matching that happens during `adsp_process_group_create_mpd_attrs`…"

本仓库提供的是这条原则在 **SM8150 + mainline** 上「整套替换后成功」的正面实证。

## 环境

| 项 | 值 |
|---|---|
| 设备 | Redmi K20 Pro / Mi 9T Pro，`raphael`，SM8150（骁龙 855），Hexagon 690 cDSP V66 |
| 内核 | `7.0.0-sm8150-gc526b7bf7ebc-dirty`（mainline，`CONFIG_QCOM_FASTRPC` builtin） |
| 用户态 | Ubuntu 24.04 aarch64 rootfs；mainline `quic/fastrpc` → `libcdsprpc.so` + `fastrpc_test` |
| 启动 | UEFI / rEFInd，DTB `sm8150-xiaomi-raphael.dtb`；Secure Boot disabled |
| 网络 | USB-NCM `172.16.42.1`（WiFi/modem 在 DT 中禁用） |
| cDSP 配置 | DTB stage2：只留 `cdsp`（adsp/mpss/slpi disabled）；12 个 `compute-cb@N` 加 `dma-coherent`；`cdsp recovery=disabled` |

## 三个最容易踩的坑

1. **PIL 是 split 形态，不是 `cdsp.mbn`。** 设备 DT 的 `firmware-name` 是
   `qcom/sm8150/Xiaomi/raphael/cdsp.mdt`，内核日志 `Booting fw image …/cdsp.mdt, size 7580`。
   目录里只有 `cdsp.mdt` + `cdsp.b00..b10`（小写）。把 3.4 MB 合并 `cdsp.mbn` 放进去
   **不会被加载，是一次静默 no-op**。部署必须把 `CDSP.MDT`/`CDSP.Bxx` 改名小写后覆盖同目录，
   共 10 个 split 文件（另 `cdspr.jsn` 新旧相同）。
2. **skel URI 必须用裸文件名。** 换成新固件后 `host_main` 的新错误是 `0x80000406`，
   DSP 侧 dlopen 日志：
   `Absolute path or ./obj_name required for shared object data/local/t…` ——
   `file:///data/local/tmp/hvx/libhvx_add_skel.so` 的首个 `/` 被剥掉变成相对路径而被拒。
   改成 `file:///libhvx_add_skel.so?...` 靠 `ADSP_LIBRARY_PATH` 搜索即通过。
3. **别去打内核补丁。** PR #319 的 `AEE_EUNSUPPORTED → legacy MMAP_64` fallback 在本机
   实测让 cDSP glink/RPC 通道挂死（`INIT_ATTACH` 变 `errno=110`），已按 sha256 回滚。
   `fastrpc_init_create_process()` 也不经 `MEM_MAP`，用户态换库不会改变内核构造的
   `RMID_INIT_CREATE`。已证伪路线见 `docs/00-RESEARCH-LOG.md` §11–§13。

## 复现路径（不含固件二进制）

1. 从 MIUI China Stable **`V12.5.6.0.RFKCNXM` (2021-07-30)** 官方包提取 `NON-HLOS.bin` 中的
   `CDSP.MDT` + `CDSP.Bxx`，并按 MDT 的 12 个 phdr `p_offset` 校验段长度；产出清单与哈希见
   `docs/04-FIRMWARE-MANIFEST.json`、`docs/05-BASELINE-COMPARE.txt`。
2. `tools/pack_firmware.py` 打包 32 个文件（PIL 11 + dsp 21，小写归一化）；
   `tools/deploy_firmware.py` 提供 `upload → backup → precheck → replace → verify →
   reboot → early → postcheck → rollback` 分阶段动作，每步可单独刹车。
3. 备份落在 `/root/cdsp-firmware-backup-20201211-pre-20210730/`（含 tar.gz 与
   `/root/cdsp-rollback.sh`）。**回滚靠文件级备份**，不是 rEFInd 菜单项：本机 ESP
   (`/dev/sda30`) 只有 `BOOTAA64.EFI` + 默认样例 `refind.conf`，没有第二个内核。
4. 冷启动一律 `systemctl reboot`，**绝不 kexec**。验收原始输出在
   `evidence/postboot-verify.txt`（PAS、build id、remoteproc、`fastrpc_test`）。
5. 示例工程在 `example/`：QAIC IDL → stub/skel → `host_main`。设备侧编译
   `gcc host_main.c hvx_add_stub.c -I. -L/usr/local/lib -lcdsprpc -lpthread -ldl`。

> 部署预案全文见 `docs/03-DEPLOY-PLAN.txt`。**当前设备保持新固件、不要回滚**；
> 回滚脚本仅作应急保留。

## 上游投递状态

**截至归档时，报告与 Issue 文本尚未投递到任何上游仓库或邮件列表**（自存档即本仓库）。
完整投递清单、贴法、可直接复制的 Issue 正文见 `docs/02-UPSTREAM-TARGETS.md`；
英文主报告（可直接贴 `qualcomm/fastrpc#400`，正文 §6 已链到本仓库）见
`docs/01-UPSTREAM-REPORT.txt`。

| 优先 | 目标 | 形式 |
|---|---|---|
| ① | `qualcomm/fastrpc#400` | 追加评论（同类 `*BADASID` + 固件/shell 配套，已标 stale） |
| ② | `GengWei1997/kernel-deb` | 新建中文 Issue（`firmware-xiaomi-raphael.deb` 发布源，受众最准） |
| ③ | `qualcomm/fastrpc` `Docs/` | 新建 `firmware_shell_compatibility.md` 文档 PR（须先开 issue 定 scope、`git commit -s`、`development` 分支） |
| ④ | `linux-msm/hexagon-dsp-binaries` | 先开 Issue 征询，沉淀 SM8150 固件配套矩阵；**不要直接提二进制 PR** |
| ⑤ | `GengWei1997/linux-xiaomi-raphael-uefi` | README 补充（同时承接 DTB stage2 / USB-NCM 经验） |
| 可选 | `linux-arm-msm@vger.kernel.org` | 不带 `[PATCH]` 的 FYI，把「内核无需补丁」送进 lore 归档 |

**首创性口径**：错误码数值与宏名本身早已公开（不是新发现）；本仓库的主张是
「`0x80000453` 这一具体根因（PIL 与 shell 代际不配套）与解法（整套换同代固件）」
在 SM8150 + mainline 上被完整 A/B 实证。相关但不同的公开记录：`#325`（closed）、
`#401`（closed）、`#188`（closed）、`#269`（closed）、`#405`（open）。

## 目录

| 路径 | 内容 |
|---|---|
| `docs/00-RESEARCH-LOG.md` | 研究全记录（V1–V54、K1–K9、验证项/工作计划标记、§17.6 最终结论、§18 上游清单） |
| `docs/01-UPSTREAM-REPORT.txt` | 英文主报告（最终版，可直接贴上游） |
| `docs/02-UPSTREAM-TARGETS.md` | 投递目标清单、注意事项、中文 Issue 正文 |
| `docs/03-DEPLOY-PLAN.txt` | 部署与回滚预案 v2（按 split 形态实测修正） |
| `docs/04-FIRMWARE-MANIFEST.json`、`05-BASELINE-COMPARE.txt`、`07-DEPLOY-MANIFEST.txt` | 32 文件哈希、新旧固件逐项对比、部署清单 |
| `docs/06-TURNIP-VULKAN-NOTES.md` | 另一项独立成果：Adreno 640 / Mesa 25.2.8 `MSM_INFO_SET_IOVA -28 ENOSPC` 的 workaround |
| `evidence/` | 冷启动验收、URI 修复、诊断、四次只读审计、P0–P2 判别矩阵；`KEY-EXCERPTS.md` 为关键行索引 |
| `tools/` | 固件打包/部署/回滚、只读取证、UAPI 探针、PR#319 实验、TWRP 应急脚本 |
| `example/` | 自写 HVX 示例工程源码（IDL / stub / skel / host / Makefile） |

⚠️ `tools/` 中的部分脚本是**已证伪的历史实验**，保留仅作负结果证据，不要执行：
`stage2b_memory_region.py`（memory-region 假设，DEPRECATED 且从未执行）、
`deploy_rootpd.py` / `fastrpc_nomemmap.c`（nr=10 短路实验，源码取证后被推翻）、
`deploy_pr319.py` / `pr319.diff`（legacy MMAP fallback 会挂死 cDSP，已回滚）。

## 脱敏与许可

- 所有脚本/文档中的设备 SSH 口令已替换为 `<REDACTED>`，Wi-Fi 内网地址替换为
  `192.168.x.x`，本机工作区路径替换为 `<WORKSPACE>`；归档前做过自动化泄漏扫描。
- **不分发任何厂商固件二进制**（`cdsp.mdt`/`bXX`/`mbn`、`fastrpc_shell_*`、
  skel、`NON-HLOS.bin`、`.deb`、编译产物 `.so`）。这些文件的版权与再分发许可归各自权利人；
  请自行从官方 MIUI 包提取并核对 `docs/04` 中的哈希。详见 `NOTICE.md`。
- 对设备的操作有风险（PAS 验签失败会令 cDSP 不可用），务必保留完整备份、可用的
  回滚启动项与 Secure Boot disabled 状态，并且在理解每一步之前不要照抄执行。

## 核验

```bash
# 新固件在位判据（设备侧）
sha256sum /usr/share/qcom/dsp/cdsp/fastrpc_shell_unsigned_3   # f94a2062…
grep -a -o -E '[0-9]{6,}\.[0-9]+_[0-9]{8}_[0-9]{6}' \
    /usr/share/qcom/dsp/cdsp/fastrpc_shell_unsigned_3 | sort -u   # 419065.1_20210730_070147

# 功能判据
fastrpc_test -d 3 -U 1      # Total 3 / Passed 3 / Failed 0
./host_main                  # host: PASS - all 1000 elements verified correct.
```

回滚基线 sha256：`cdsp.mdt=c87b5fa0…`、`cdsp.b02=a0aaa879…`、`cdsp.b05=85086ea8…`、
`fastrpc_shell_unsigned_3=1d03f6ca…`（2020-12 build）。
