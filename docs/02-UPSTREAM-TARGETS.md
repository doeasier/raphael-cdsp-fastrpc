# 上游提交目标清单（2026-11-06 核实）

> 目的：把「换整套配套固件解决 cDSP `AEE_EBADASID` / 打通 Unsigned PD」这个成果
> 提交到能被后人检索到的上游仓库。**本清单只是建议 + 已备好的报告文本，
> 尚未向任何上游仓库 / issue / 邮件列表发送**；对外提交需要用户确认与相应账号。
>
> **兜底已落地（2026-11-06）**：成果已自存档到本人公开仓库
> **https://github.com/doeasier/raphael-cdsp-fastrpc**（tag `archive-2026-11-06`）。
> 该仓库含完整研究日志、英文报告、验收原始日志、复现脚本与示例源码（已脱敏，
> **不含厂商固件二进制**）。**每个上游 issue / PR / FYI 邮件正文都应链到它**，
> 这样即使 issue 被关闭或标 stale，证据链仍可引用。英文报告 §6 已改成公开资产清单。
>
> 主报告（英文，可直接贴）：`tmp/firmware/upstream-report.txt`
> 完整证据链（中文）：`docs/05-Hexagon690-DSP调用研究.md` §11 / §16 / §17.6 / §18
> 验收原始日志：`logs/firmware/postboot-verify.txt`、`hostmain-uri-fix.txt`

---

## 一、结论速览

| 优先级 | 仓库 | 提交形式 | 为什么是它 |
|---|---|---|---|
| **① 最高** | `qualcomm/fastrpc`（原 `quic/fastrpc`）<br>https://github.com/qualcomm/fastrpc/issues/400 | **在 #400 下面评论**（不要贴 #325） | #400 是「CDSP 固件拒绝创建 user PD、`AEE_EQURTBADASID`」的开放 issue；maintainer 已明确指出「shell 与 firmware 必须同 build」「`adsp_process_group_create_mpd_attrs` 里有 hash matching」，而 reporter 的配套集正是 "same line, not the same build"。我们的 A/B 实证（换整套 → 3/3 PASS）**正好回答并验证了这条判断**，且该 issue 已被标 stale |
| **② 高** | `GengWei1997/kernel-deb`<br>https://github.com/GengWei1997/kernel-deb/issues/new | **新建 Issue**（中文即可） | 设备上 `firmware-xiaomi-raphael.deb` 的发布源。包里是 2020-12 版（shell 933772 B），**所有用它装 raphael Ubuntu 的人都会踩 `0x80000453`**。受众 100% 命中，且维护者活跃（2026-10-14 有提交，`kernel-v7.3` Latest） |
| **③ 中高** | `linux-msm/hexagon-dsp-binaries`<br>https://github.com/linux-msm/hexagon-dsp-binaries/issues | **先开 Issue 征询，不要直接提二进制 PR** | 上游集中分发 `fastrpc_shell_*` / skel 的仓库，`config.txt` 有 sm8250/RB5、sdm845/db845c，**没有 sm8150/raphael**。README 明确写「binaries tied to SoC + firmware revision」——正是我们的结论。但新增条目要动 `WHENCE` / `config.txt` / `make check`，且涉及厂商二进制再分发许可，必须先问 |
| **④ 中** | `GengWei1997/linux-xiaomi-raphael-uefi`<br>https://github.com/GengWei1997/linux-xiaomi-raphael-uefi | **README / Wiki 补充说明 PR** | 同源发行链、中文、已有「常见问题 / 硬件适配表 / USB-NCM 172.16.42.1」章节，可同时承接「固件版本配套表」和「DTB stage2 只留 cdsp、12 个 compute-cb 加 dma-coherent、recovery=disabled」经验 |
| **⑤ 高（同 ① 仓库）** | `qualcomm/fastrpc` 的 `Docs/`<br>https://github.com/qualcomm/fastrpc/tree/development/Docs | **文档 PR**（须先开 issue 讨论） | `Docs/` 现有 adspmsgd.md / apps_mem.md / conf_guideline.md / daemons.md，**没有任何固件-shell 兼容性或 troubleshooting 文档**。这是唯一能把结论沉淀成「上游可维护文档」而非一条会沉底的 issue 的位置 |

> 若只做两件事：**①（评论） + ②（Issue）** 就足以把成果留在公开可检索处；
> ⑤ 是让结论长期可维护的最佳加项，③④ 可等维护者回应后再做。

### 可选 / 不要投

- **✅ 可选第三动作：LKML / `linux-arm-msm` 的 FYI 经验报告**（不是「不建议」，但排在 ①②⑤ 之后）。我们没有内核补丁，结论恰恰是「`fastrpc.c` 无需修改」，所以**不能**发 `[PATCH]`，也不能改内核 `Documentation/`（那里只收 DT binding / uAPI，不收厂商 blob 经验）。但 `submitting-patches.html` 只规范补丁、并未禁止不带 `[PATCH]` 的非补丁邮件讨论；发一封**自包含的纯文本 FYI** 到 `linux-arm-msm@vger.kernel.org`（cc 维护者）能把「别再往内核打补丁、根因在固件代际」送进 `lore.kernel.org` 永久归档。缺点是受众偏内核、不产生可维护文档。`MAINTAINERS` 的 `QUALCOMM FASTRPC DRIVER` 条目为
  `M: Srinivas Kandagatla <srinivas.kandagatla@linaro.org>`、`M: Amol Maheshwari <amahesh@qti.qualcomm.com>`、`L: linux-arm-msm@vger.kernel.org`、`L: dri-devel@lists.freedesktop.org`、`S: Maintained`、`F: drivers/misc/fastrpc.c` / `include/uapi/misc/fastrpc.h` / `Documentation/devicetree/bindings/misc/qcom,fastrpc.yaml`
  （2024-07 patch `c66c0e7c511c` 加入 dri-devel）。抄送务必克制，勿群发无关列表。
- **`edk2-porting/edk2-msm`（Renegade Project）**：层级不符 —— 我们的改动都在 DTS/rootfs/固件文件，不在 UEFI。注意 `github.com/renegade-project` 是**空组织**，正确组织是 `github.com/edk2-porting`。
- **gitlab.com/sm8150-mainline/linux**：已 Archived，主仓库迁到 https://gitlab.postmarketos.org/soc/qualcomm-sm8150/linux 。只适合开 issue 作 SoC 级反馈，**勿贸然提 MR**（我们的内容是本地 workaround）；GitHub 上的 `sm8150-mainline/linux` 停更于 2022-07。
- **Mesa / Turnip**（`gitlab.freedesktop.org/mesa/mesa`）：属于**另一项成果**（`MSM_INFO_SET_IOVA` 在旧 msm 内核上 `-28 ENOSPC`，强制关闭该能力后 vulkaninfo 正常）。若要做，单独开 issue，标题点明 SET_IOVA / -28 ENOSPC / old msm，关联 MR !15676、!32533、work item 14656；**不要和本报告混在一起**，也不要直接提 MR（兼容策略需先与上游讨论探测方式）。
- **`xiaomi-sm8150-devs`（LineageOS vendor blobs）**：Android vendor blob，与 mainline PIL 固件 / cDSP 无关，受众不重合，**不值得同步**。
- **`dipa-studio/ios-sweet`、`oosexgang/hackios-xnu-kernel`**：项目主线（跑 iOS）上游，与 cDSP 研究无交集，不必投。
- **门槛高的备选归档位**：CodeLinaro 的 Linaro *Testing FastRPC* wiki
  https://git.codelinaro.org/linaro/qcomlt/fastrpc/-/wikis/Testing-FastRPC
  （即官方 README "Resources → Linaro documentation" 指向处，针对 sm8650、明确要求 `.mbn` 与
  `fastrpc_shell_*` 配套；2024-07 后未更新、需 CodeLinaro 账号）天然适合补一节，
  但外部编辑门槛高。`linux-firmware` 只收 blob、不收经验文档；
  Qualcomm 旧论坛已迁到 mysupport.qualcomm.com，旧路径不稳、发帖入口未确认 → 均不作首选。
- ③ 仓库细节【已核实】：默认分支 `trunk`、MIT、`has_issues:true` / `has_wiki:false` /
  `has_discussions:false`、21 stars、2026-11-05 仍有 push；维护者在 #325 里亲自推荐
  从这里取固件，所以「配套矩阵」放这里受众最准。

---

## 二、各目标具体贴法

### ① `qualcomm/fastrpc#400`

- 地址：https://github.com/qualcomm/fastrpc/issues/400
- 形式：**评论**（issue 目前 open 但被标 stale；评论会让它重新活跃，比新开 issue 更能被看到）。
- 正文：直接贴 `tmp/firmware/upstream-report.txt` 分隔线以下的英文全文；若嫌长，贴 §0 + §2 + §4 + §5，并附一句「full matrix + repro assets available」。
- 报告已按该仓库 README 的 **Bug Reporting Guidelines** 组织（Platform/SoC、HLOS、Kernel、userspace lib version、stdout/stderr、dmesg、Tests Run & Parameters、Custom Test Code），无需再补字段。
- ⚠️ 三个措辞注意：
  1. 错误码不同：我们 `0x80000453 AEE_EBADASID`，#400 `0x8000054f AEE_EQURTBADASID` —— 报告里已明确写成「same class, different code」，**不要声称是同一个 bug**。
  2. 我们的是 SM8150 / kernel 7.0 / 2020→2021 固件，对方是 SM8550 / 7.2.3 / 2024 固件，结论是「版本配套」机制的实证，**不是**给对方的直接解法。
  3. `qualcomm/fastrpc` 是 `quic/fastrpc` 的组织迁移名；README 里 clone 命令仍写 `quic/fastrpc`，两个 URL 都能到同一个仓库，写报告时以 `qualcomm/fastrpc` 为准。
- 附带价值：`fastrpc_test` 的 skel URI 陷阱（`file:///abs/path` 会剥掉首个 `/`，必须用裸文件名靠 `ADSP_LIBRARY_PATH` 搜索）值得单独提一个 docs issue 或 PR；PR#319 的 legacy MMAP fallback 挂死 cDSP（`errno=110`）也值得在其后续 PR 讨论里留一条负结果（该 PR 已 closed、**未合并**，别写成「已合入」）。
- **仓库流程（已核实）**：`has_issues:true` / `has_discussions:false`（**没有 Discussions，只能 issue/PR**）/ 默认分支 `development` / 48 个 open issue、持续活跃。`CONTRIBUTING.md` 要求：新功能或 bugfix **先开 issue 与维护者讨论**，否则 PR 可能被拒；fork 后基于 `development` 提 PR 回 `development`；每个 commit 必须 `git commit -s`（DCO）；CI/静态检查全绿。→ 想做 ⑤ 的 `Docs/` PR，**先开一个 scope issue**，不要直接甩 PR。
- **可一并关联/引用的 issue**（都已核实状态）：`#400`（open + Stale，主落点）、`#401`（closed，kalama 上 `INIT_CREATE` 恒 `0x80000416`，试过各代 shell，追问是否固件侧限制）、`#188`（closed，`0x8000054f`，维护者把 shell-firmware mismatch 列为可能但未确认）、`#269`（closed，SDM660，仓库内**唯一**命中 `0x80000453` 的条目）、`#405`（open，glink `-110` 挂死，与 PR#319 v2 症状同类但平台/成因不同）、`#325`（**closed 2026-06-30**，主题「跑独立程序」，维护者当时也在追问固件/二进制来源与库版本 → 只作背景，不要再往里贴）、PR `#319`（closed、未合并）。
- **⑤ `Docs/` 文档 PR 建议内容**：新增 `Docs/firmware_shell_compatibility.md`，写清三条 —— ① PIL 与 `fastrpc_shell_unsigned_3`/skel 必须同一 DSP build，DSP 侧 `adsp_process_group_create_mpd_attrs` 有 hash 匹配（引用 #400 维护者说法）；② DT `firmware-name` 决定加载 `cdsp.mdt`+`bXX` 还是合并 `cdsp.mbn`，split 设备上放 mbn 是静默 no-op；③ skel URI 用裸文件名走 `ADSP_LIBRARY_PATH`。附本报告作为实证链接。

### ② `GengWei1997/kernel-deb`（中文 Issue 正文可直接复制）

- 地址：https://github.com/GengWei1997/kernel-deb/issues/new
- 该仓库 **无 README、Discussions 未开启、Issues 为空** → 只能新建 Issue，不要提 README PR。
- 建议标题：`firmware-xiaomi-raphael.deb 的 cDSP 固件版本过旧，导致 FastRPC unsigned PD 报 AEE_EBADASID（附已验证的 2021-07-30 配套集）`

建议正文：

```
环境：raphael / SM8150 / 内核 v7.0（本仓库 kernel-v7.0 release）、Ubuntu 24.04，
使用 release 内附的 firmware-xiaomi-raphael.deb。

现象：cDSP remoteproc 正常（cdsp is now up）、/dev/fastrpc-cdsp 与
cdsprpcd 都在，但 FASTRPC_IOCTL_INIT_CREATE 恒定返回
0x80000453 AEE_EBADASID，fastrpc_test -d 3 -U 1 三项全失败。

定位结果：这不是内核或 libcdsprpc 的问题，而是 PIL 固件与 DSP shell
不是同一个 build。设备上实际加载的是 split 形态
  /lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.mdt + cdsp.b00..b10
（DT firmware-name 就是 cdsp.mdt，注意**不是** deb 里那个合并的
cdsp.mbn；直接放 mbn 不会被加载）。
其程序头是 b02=227348 / b05=2710852、版本串 00131 分支，而
/usr/share/qcom/dsp/cdsp/ 里的 shell 是 2020-12 的
CDSP.HT.2.0.1-00171-SM8150-1.357350.2_20201211_224311（933772 B）——
两者不配套。

已验证的解法：换成小米 China Stable V12.5.6.0.RFKCNXM (2021-07-30)
里的整套配套固件（CDSP.MDT + B00..B10 九个分段改小写覆盖 + 21 个
dsp/cdsp 文件，PIL/shell/skel 全部同一 build
...357350.2.419065.1_20210730_070147，shell 935256 / 939664 B），
systemctl reboot 后 PAS 验签通过、cdsp running，
fastrpc_test -d 3 -U 1 → 3/3 PASS，自写 HVX skel 也跑通
（host: PASS - all 1000 elements verified correct）。
无需刷内核、无需改 fastrpc.ko。

建议：把 firmware-xiaomi-raphael.deb 里的 cDSP 部分更新到 2021-07-30
配套集，或在 README/Release notes 里注明「PIL 与 shell 必须同 build、
且设备是 split 形态」。需要的话我可以提供完整文件清单、sha256、
以及从 NON-HLOS.bin 提取/校验的脚本（不直接上传厂商二进制，
许可问题请先确认）。
```

### ③ `linux-msm/hexagon-dsp-binaries`

- 地址：https://github.com/linux-msm/hexagon-dsp-binaries/issues
- 形式：**先开 Issue 问「是否接受 sm8150/Xiaomi/raphael 条目」**，附：
  - 2021-07-30 完整配套 build string 与 32 文件清单/sha256（见 `tmp/firmware/raphael-20210730/manifest.json`）；
  - 来源 ROM 版本号 `fw_raphael_miui_RAPHAEL_V12.5.6.0.RFKCNXM_...zip`、`NON-HLOS.bin`；
  - A/B 实测结论（旧不配套 → `AEE_EBADASID`，新配套 → 3/3 PASS）；
  - 明确说「redistribution license 由维护者判断，我们可以只提供 `WHENCE`/`config.txt` 片段或纯文档」。
- 若维护者同意再按 README 的 Maintainer workflow 提 PR：新增目录 → `WHENCE` 加 `Dir:`/`Device:`/`Licence:`/`Status:` → `config.txt` 加 `Install:` → `make check` → `./scripts/checkfw.py`。
- ⚠️ **不要**把 32 个厂商二进制直接 push 上去；许可（`LICENSE.qcom` / `LICENSE.qcom-2`）和来源合法性必须先问。

### ④ `GengWei1997/linux-xiaomi-raphael-uefi`

- README 已有「常见问题 / 硬件适配表 / USB-NCM 172.16.42.1」结构，适合追加一节「cDSP / FastRPC」：
  - 固件版本配套表（2020-12 失败 ↔ 2021-07-30 成功）；
  - split PIL 形态与大小写坑；
  - DTB stage2 只留 cdsp、12 个 compute-cb 加 `dma-coherent`、`recovery=disabled`；
  - `fastrpc_test -d 3 -U 1` 与自写 skel 的最小验证命令；
  - 明确「换固件是 rootfs 文件替换 + reboot，不是刷分区」，以及安全风险（先备份、保留带 `modprobe.blacklist=qcom_q6v5_pas` 的启动项）。

---

## 三、提交前必做的四件事

1. **核对引用值**：`cdsp.mdt=4b82459c…`、`cdsp.b02=a14316ec…`、`cdsp.b05=85e67884…`、
   `fastrpc_shell_unsigned_3=f94a2062…`（935256 B）、`fastrpc_shell_3=f12bf733…`（939664 B）；
   回滚基线 `cdsp.mdt=c87b5fa0…`、`fastrpc_shell_unsigned_3=1d03f6ca…`（933772 B）。
   全部出自 `logs/firmware/postboot-verify.txt` 与 `tmp/firmware/raphael-20210730/manifest.json`。
2. **别把旧草稿发出去**：`upstream-report.txt` 在 2026-11-06 已整篇重写。旧版结论是
   「INIT_CREATE 恒失败、求版本配对建议」，且把 PIL 误写成 `cdsp.mbn` —— 已被证伪。
3. **对外动作需确认**：需要 GitHub / GitLab 账号；**用户侧自存档已完成**
   （https://github.com/doeasier/raphael-cdsp-fastrpc），但报告与所有 Issue 文本
   **尚未投递到任何上游仓库 / 邮件列表**。每份正文结尾都加一行指向自存档的链接。
4. **「首创性」措辞要精确，别一刀切否认也别夸大**：
   - 【公开】错误码定义本身在 `inc/AEEStdErr.h`：`AEE_EOFFSET = 0x80000400`（DSP 侧）、
     `AEE_EBADASID = AEE_EOFFSET + 0x053` → **0x80000453**；同族
     `AEE_EQURTBADASID(0x14F)=0x8000054f`（#400）、
     `AEE_ERESOURCENOTFOUND=0x80000416`（#401）。数值/宏名不是新发现。
     `0x80000453` 也出现在 XDA 的 Android/vendor 栈日志（instantnoodlep）；
     「固件与 shell 须配套」在 Radxa Q6A 与 TrailCurrentPlaybill *Lessons Learned*
     里也有记录（那边是 QCS6490 / `0x80000600 AEE_EFATAL`）。
   - 【很可能新】`qualcomm/fastrpc` 全仓 issue/PR 搜 `AEE_EBADASID` / `EBADASID`
     **零命中**，`0x80000453` 仅 #269 一处且未归因；#400 只有抽象配套原则、
     没有成功案例。公开检索也未见「该码的根因是 PIL 与 shell 代际不配套 →
     整套换同代固件即解决」的实证。故报告 §5.5 的口径是：
     **不是「错误码首次公开」，而是「该错误码这一具体根因与解法首次被公开实证」**
     （基于多源检索未命中，非穷尽全网）。别写成「first report of AEE_EBADASID」。

## 四、兜底：先让自己这份成果可引用

上游 issue 可能被关、被标 stale（#400 已经是这样）。最稳妥的是同时留一份**自己可控制的永久归档**：
把 `docs/05 §17.6` + `upstream-report.txt` + `logs/firmware/postboot-verify.txt`
整理成一个独立仓库（或 Gist / 个人博客 / XDA 帖），标题带
`SM8150 raphael AEE_EBADASID fastrpc unsigned PD 2021-07-30 firmware` 这类关键词，
然后在上述每个 issue 里链过去。这样即使上游讨论沉底，成果仍然可被搜索到。
