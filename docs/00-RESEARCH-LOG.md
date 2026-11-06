# 05 · 在红米 K20 Pro 上打通 Hexagon 690（SM8150 / V66）DSP 调用 · 研究方案

> **目标**：研究性打通骁龙 855 的 Hexagon 690 DSP 调用（FastRPC + 自定义 HVX 代码）。
> **不是**为了给大模型加速——855 的代际（V66）与算力决定了 LLM 不现实，本课题定位"能否调通"。
> 本文件是**活文档**：验证项与开发任务完成后由主 AGENT 打 `✅`/`❌` 标记并附证据。

---

## 1. 硬件与平台事实（已确认）

| 项 | 值 |
|---|---|
| 设备 | 红米 K20 Pro / Mi 9T Pro（raphael） |
| SoC | 骁龙 855（SM8150） |
| cDSP | Hexagon 690 = **V66** 代 |
| 向量单元 | 4× HVX，每路 128 字节（1024 bit） |
| 加速器 | HTA（Hexagon Tensor Accelerator） |
| 关键便利 | 855/865 特批 **Unsigned PD**：无签名动态库可直接在 cDSP 执行 |
| QNN HTP | 从 V68 起才有 skel；855 仅遗留 `DSP(V66)` 后端 |

**结论**：QNN 的 LLM 加速路线在 855 上不可行；但"绕过 QNN、直接用 Hexagon SDK + FastRPC 调 Hexagon 690"是干净且有先例的研究课题（TVM、Halide、IRIS 均在 855 上验证过自定义 Hexagon 代码）。

---

## 2. 两条技术路径

- **路径 A（推荐，纯研究）**：Hexagon SDK 4.1.0 + QAIC + FastRPC + 自定义 HVX skel。
  写 IDL → QAIC 生成 stub/skel → `hexagon-clang` 编 DSP 侧 → open-fastrpc 编 host 侧 → 部署到 cDSP 的 Unsigned PD。
- **路径 B（高层，对照）**：QNN 遗留 `DSP(V66)` 后端（`libQnnDspV66Skel.so`）跑小图，作"打通 QNN→Hexagon"里程碑；legacy、上层运行时几乎不覆盖，仅作对照。

---

## 3. 环境现状（本次核实）

- ✅ 主环境 Windows + **WSL 已安装（2 个发行版）**。注意：本 AGENT 沙箱拦截 `wsl.exe` 启动，但本机 WSL 本身可用 → x86_64 Linux 构建机成立（在 WSL 内执行 Hexagon SDK 交叉编译）。
- ✅ K20 Pro 可达：`root@192.168.x.x:22`（SSH 口令已脱敏），22 端口 OPEN。
- ✅ `/data2` 挂载 400+GB → 项目根 `root@k20pro:/data2/hexagon690`。
- ⚠️ 构建机若需本 AGENT 直接驱动，需放行沙箱的 `wsl.exe`（或用户在 WSL 内自行执行构建步骤）。

---

## 4. 验证项清单（Phase 0）

格式：`[ ] 编号 描述 — 状态`；完成后改 `[x]` 并附 `✅`/`❌` 与证据。

### 4.1 设备侧（K20 Pro，SSH root@192.168.x.x）
> 现状（SubA 实测，2026-11-03）：DSP 底层栈（内核 + 节点 + CDSP remoteproc + 固件）已就绪；唯一缺口在用户态 rfsa 库（社区 ROM 预期内不含，需自部署 skel）。

- [x] **V1** 内核 `CONFIG_QCOM_FASTRPC` 开启 — ✅ `CONFIG_QCOM_FASTRPC=y`（编进内核）
- [x] **V2** `/dev/fastrpc-cdsp` 设备节点存在 — ✅ 另含 `fastrpc-cdsp-secure`/`fastrpc-adsp`/`fastrpc-sdsp`；属主 0600（调用需注意 fastrpc 组/权限）
- [x] **V3** `remoteproc` 中 `cdsp` 状态为 `running` — ✅ remoteproc2 `name=cdsp state=running`（slpi/modem/adsp 亦 running）
- [x] **V4** `cdsp` 固件存在于 `/lib/firmware` — ✅ 实测为 **MDT+分段**格式：`/lib/firmware/qcom/sm8150/Xiaomi/raphael/cdsp.mdt`(+b00~b10)，remoteproc2 据此加载 running（非 .mbn，原搜索脚本假设不符）
- [ ] **V5** DSP 用户态库目录 `/usr/lib/rfsa/cdsp`（或 `adsp`）存在 — ❌ 缺失（预期内）；**经 V7 排查确认设备完全未装 fastrpc 用户态栈**（无 `libfastrpc`/`libcdsprpc`、无 `remote.h`、无 `adsprpcd`/`cdsprpcd` 守护进程，仅内核 uapi 头 `/usr/include/misc/fastrpc.h`）。D4 将通过 `qualcomm/fastrpc` 交叉编译补齐用户态（lib+守护进程），D7 部署自编 skel 到 `/usr/lib/rfsa/cdsp`。
- [x] **V6** 设备具备 `gcc`/`make`（编 host stub 用）— ✅ `gcc`/`make`/`aarch64-linux-gnu-gcc` 均在 /usr/bin
- [x] **V7** `Unsigned PD` 能力（CDSP_DOMAIN_ID=`3` + `UNSIGNED_PD_SUPPORT`=`1`）— ✅ 实测 capability=**1**。设备 `/dev/fastrpc-cdsp` 经 `ioctl(FASTRPC_IOCTL_GET_DSP_INFO)` 直接命中内核 uapi 取得。交叉验证（同一 ioctl 探属性 0..6）：`HVX_SUPPORT_128B=4`、`VTCM_PAGE=0x40000(256KB)`、`VTCM_COUNT=1`、`ARCH_VER=99430` —— 各项互不相同且符合 Hexagon 690/V66 规格，证明 DSP 真实返回能力数据（非空返回）。**结论：855 cDSP 可加载无签名 skel，研究路线可行性闭环。**

### 4.2 构建环境（WSL x86_64 Linux）
> 现状（SubB 研究，2026-11-03）：WSL 已装（2 发行版）；SDK/Tools/fastrpc 的获取与构建路径已完全明确，待用户登录 Qualcomm 账号下载（需 Qualcomm ID，免费注册 developer.qualcomm.com）。

- [x] **B1** WSL 发行版可启动并拿到 x86_64 Linux shell — ✅ 注册表 2 个发行版，本机 WSL 可用（仅本 AGENT 沙箱拦 `wsl.exe` 启动）
- [ ] **B2** 可获取 **Hexagon SDK 4.1.0**（或半易得的 **4.3.0**，同含 v66 目标）— ⏳ 方案已明确：QPM3 网页或 Qualcomm Software Center 桌面 App 登录下载；4.3.0 在 QPM3 更易拿（TVM 已验证 4.3.0 + `USE_HEXAGON_ARCH=v66` 可编 855）
- [ ] **B3** 可获取匹配版本 **Hexagon Tools 8.4.06**（v66，不随 SDK 预打包，需单独下到 `$HEXAGON_SDK_ROOT/tools/HEXAGON_Tools/8.4.06`）— ⏳ 同 B2 渠道
- [ ] **B4** 可 clone `qualcomm/fastrpc` 并交叉编译（device aarch64-linux-gnu）— ⏳ 方案已明确：`./gitcompile --host=aarch64-linux-gnu`；若报 libbsd 缺失需先交叉编 libbsd

### 4.3 阶段 2 之后的实测验证项（2026-11-05 ~ 11-06）

> 环境已变：**WSL 实际不可用**（`wsl.exe` 被安全策略拦），全部构建在 Windows 宿主 + 设备原生 gcc 完成；
> 网络从 WiFi 切到 **USB-NCM `root@172.16.42.1`（SSH 口令已脱敏）**，WiFi 因 DT 禁用 modem 而永久放弃。
> SDK 实际安装版本为 **`C:/Qualcomm/Hexagon_SDK/4.3.0.0/`**（不是 4.1.0/4.3.0 的假设）。

- [x] **V8** 阶段 1 USB-NCM 网络恢复 — ✅ `usb-ncm.service active/enabled`，`usb0=172.16.42.1/24`，Windows `UsbNcm Host Device #2` 无 code 28
- [x] **V9** 阶段 2 DT 只留 cDSP — ✅ `adsp/mpss/slpi` 三个 remoteproc `status=disabled`，`cdsp=okay`；12 个 `compute-cb` 全带 `dma-coherent`
- [x] **V10** cDSP remoteproc 启动 & 设备节点 — ✅ `remoteproc0 name=cdsp state=running recovery=disabled`；`/dev/fastrpc-cdsp`(10,267)、`/dev/fastrpc-cdsp-secure`(10,266) 均在
- [x] **V11** root-PD shell 搜索路径修复 — ✅ `cdsprpcd.service.d/10-searchpath.conf` 设置 `ADSP_LIBRARY_PATH`/`DSP_LIBRARY_PATH`；日志出现 `Successfully opened file fastrpc_shell_unsigned_3`
- [x] **V12** 内核 ↔ DSP 基础 RPC 通道 — ✅ 原始 ioctl 探针：`GET_DSP_INFO`(nr=13) attr 0..8 全 rc=0 且返回真实 capability（attr=6 → `0x00018466`，低位 `0x66` = V66）；`INIT_ATTACH`(nr=4) **rc=0**
- [x] **V13** 定位 `0x80000453` 的确切来源 — ✅ 本地 `AEEStdErr.h`：`AEE_EOFFSET=0x80000400`，`+0x53` = **`AEE_EBADASID`（Bad ASID）**；同理 `0x80000414`=`AEE_EUNSUPPORTED`、`0x8000041d`=`AEE_EMEMPTR`、`0x8000041a`=`AEE_EALREADY`
- [x] **V14** 排除「cDSP 缺 `memory-region`」假设 — ❌ **假设被证伪，stage2b 补丁弃用且从未执行**。内核源码 `fastrpc_init_reserved_mem()` 明确只对 ADSP/SDSP 生效；上游 `sm8150.dtsi` 的 cdsp 节点本就无此属性；`no reserved DMA memory` 只是 `dev_dbg`；Radxa 31391 实测补完仍失败
- [x] **V15** 排除设备节点 / attach 顺序 / PD 类型 — ❌ 全部无效：secure ↔ 非 secure 重定向不变；`-U 0/1`、`-a v68/v75` 四组全同错；补发 `INIT_ATTACH` 只把错误从 `EBADASID` 变 `EALREADY`；`ADSP_LISTENER_MEM_CACHE_SIZE=0` 不能消除 `MEM_MAP`
- [x] **V16** 排除固件/shell 版本混拼 — ❌ `firmware-xiaomi-raphael 1.3` 经 `dpkg -V` 完整，`cdsp.mdt`/`cdsp.bXX`/`fastrpc_shell_unsigned_3` 同包同源（`map_SHARED_LIBS_855.cdsp.prodQ.txt`）
- [x] **V17** 定性固件版本 — ✅ shell 内编译路径暴露固件为 **`CDSP.HT.2.0.1-00171-SM8150-1.357350.2_20201211_224311`（2020-12-11）**；而 `FASTRPC_RMID_INIT_MEM_MAP`/`FASTRPC_IOCTL_MEM_MAP` 是 2022-02 才进内核 → **协议代际不兼容**
- [x] **V18** `FASTRPC_IOCTL_INIT_CREATE` 成功创建 user PD — ✅ **2026-11-06 22:31 达成**（换 2021-07-30 整套固件后）
  日志 `Created user PD on domain 3 ... Unsigned:Y`，`fastrpc_test -d 3 -U 1` 3/3 PASS，
  `host_main` 最终打印 `PASS`。旧固件下的 `AEE_EBADASID (0x80000453)` 已消失。
  ⚠️ 但 V19 当时记录的 `0x80000406` 语义需区分：**V19 是 PD 没建起来时的 `AEE_EUNABLETOLOAD` 同类症状**，
  §17.6 里新固件下的 `0x80000406` 是 **DSP 侧 dlopen 路径格式错误**，两者根因不同。
- [ ] **V19** 吞掉 `INIT_CREATE` 错误码能否继续 — ❌ 改写为 0 后后续 `INVOKE` 全部 `39 (AEE_ENOSUCH)` / `0x80000406 (AEE_EUNABLETOLOAD)`，证明 PD 确实没建起来，不是用户态误判

---

## 5. 开发工作计划

> 标记：✅ 完成 / 🔄 进行中 / ⏳ 待开始 / 🅰️ 子AGENT负责。负责人列于末尾。

### 阶段 0 · 验证（设备侧 + 构建环境）
- [x] **D1** 搭建 `scripts/device/ssh_run.py` 设备命令通道 — ✅ 主AGENT 完成
- [x] **D2** Phase 0 设备侧 V1–V6 — ✅ 子A(device-verify) 实测通过（见 §4.1）
- [x] **D2b** Phase 0 设备侧 **V7（Unsigned PD 能力）** — ✅ 子A(device-unsigned-pd) 实测 capability=1（见 §4.1）
- [⏳] **D2c** 构建环境 B2/B3/B4（SDK/Tools/fastrpc 就位）— ⏳ 待用户在 WSL 执行脚本（B1 已✅）

> ⚠️ **2026-11-06 校准**：下面 D3/D4/D6/D7 的「待 WSL 执行」描述是早期规划，**实际已全部走通**（Windows 宿主 SDK 4.3.0.0 + 设备侧原生构建），状态以本节修订标记为准。

### 阶段 1 · 工具链落地（已完成，路径与早期规划不同）
- [x] **D3** Hexagon SDK 就位 — ✅ 实际为 Windows `C:/Qualcomm/Hexagon_SDK/4.3.0.0/`（含 `qaic.exe`、`hexagon-clang 8.4.11`、`incs/`）
- [x] **D4** fastrpc 用户态构建 — ✅ 未用 WSL；设备侧 `/data2/fastrpc` clone `quic/fastrpc` + `./gitcompile` + `make install`，产出 `/usr/local/lib/libcdsprpc.so*`、`/usr/local/sbin/cdsprpcd`、`/usr/local/bin/fastrpc_test`
- [x] **D4b** 部署用户态 — ✅ 同上；另建 `cdsprpcd.service` + `10-searchpath.conf` drop-in 修 root-PD shell 搜索路径

### 阶段 2 · 示例工程（已全部完成）
- [x] **D5** 最小 HVX 示例（IDL + skel + host + Makefile）— ✅ `src/hexagon690/`
- [x] **D6** QAIC 生成 stub/skel + `hexagon-clang` 编 DSP skel（v66）— ✅ `libhvx_add_skel.so` 7160 B，Hexagon 32-bit DSP6 ELF，已部署到 `/data/local/tmp/hvx/`、`/usr/lib/rfsa/adsp/`、`/usr/share/qcom/dsp/cdsp/`
- [x] **D7** 编 host stub + 部署 — ✅ `host_main` 设备侧 gcc 编译，链 `-lcdsprpc`；`LD_LIBRARY_PATH=/usr/local/lib`
- [x] **D8** 设备运行输出 `host: PASS` — ✅ **2026-11-06 22:34 达成**：`host: PASS - all 1000 elements verified correct.`
  修法分两步：① 整套换成 2021-07-30 配套固件（§17，消除 `AEE_EBADASID 0x80000453`）；
  ② 把 skel URI 从绝对路径改成裸文件名（§17.6，消除 `0x80000406` 动态加载失败）。
  早期「固件与内核协议代际不兼容、需换内核」的结论已被 §16/§17 修正，**无需刷内核或改 fastrpc.ko**。

### 阶段 3 · 可选深化
- [⏳] **D9**（可选）QNN 遗留 `DSP(V66)` 后端跑小图
- [⏳] **D10**（可选）HVX kernel 升级为有意义算子（如 INT8 卷积 / 分块矩阵乘）

### 负责人速查
- 主AGENT：方向把控、文档标记、结果整合
- 子A·device-verify：V1–V6 实测（✅ 完成）
- 子A·device-unsigned-pd：V7 实测 + 设备 fastrpc 用户态现状（✅ 完成）
- 子B·toolchain-research：SDK/Tools/fastrpc 构建方案（✅ 完成，见 §9）
- 子C·hvx-example：示例工程起草（✅ 完成）
- 子C·example-refine：示例工具链 TODO 回填（✅ 完成）
- 子B·wsl-toolchain-scripts：WSL 构建/部署脚本起草（✅ 完成）

---

## 6. 子 AGENT 分工与轮次（本会话）

**第 1 轮（已完成）**
- 子A·device-verify：设备侧 V1–V6 实测 ✅
- 子B·toolchain-research：SDK/Tools/fastrpc/QAIC 工具链方案 ✅（结论见 §9）
- 子C·hvx-example：示例工程起草（IDL+skel+host+Makefile）✅ → `src/hexagon690/`

**第 2 轮（并行进行中）**
- 子A·device-unsigned-pd：V7（Unsigned PD 能力）实测 + 设备 fastrpc 用户态现状 🔄
- 子B·wsl-toolchain-scripts：WSL 下 `00_install_sdk.sh` / `01_build_fastrpc.sh` / `02_deploy_fastrpc.sh` 起草 🔄
- 子C·example-refine：示例工程 `TODO(工具链)` 回填（Unsigned PD 启用、HVX 头/intrinsic 收敛、Makefile 版本号修正）🔄

**主AGENT**：把握方向、回收结果、更新本文档标记、按设备/工具链现状调整计划。

---

## 7. 风险与边界

- **LLM 不现实**：855 HVX 算力有限、VTCM 小、无 HTP INT4 路径。本课题定位"能调通"，不为性能。
- **Phase 0 最大未知数**：社区 Ubuntu 是否带全 cDSP 栈（remoteproc / `cdsp.mbn` / ION）。若 `cdsp` 起不来，需从 stock vendor 固件抽 `cdsp.mbn` 并配设备树——整条路最可能卡的点。
- **SDK 版本老**：Hexagon SDK 4.1.0 为 2019 年版本，需从 qpm 找老版本与配套 Hexagon Tools，较折腾。
- **沙箱拦 `wsl.exe`**：本 AGENT 直接驱动构建需放行，否则由用户在 WSL 内执行。

---

## 8. 参考

- Qualcomm Hexagon SDK / AI Engine Direct 文档（qpm.qualcomm.com）
- `qualcomm/fastrpc` GitHub（开源 FastRPC 用户态 + 内核驱动）
- TVM `hexagon_launcher`（855/865/888，`USE_HEXAGON_ARCH=v66`）
- IRIS / Halide HVX 后端（含 855 先例）
- 既往会话：QNN 在 855 不可行、Vulkan/Turnip IOVA 修复（docs/04-GPU-Vulkan编译要点.md）

---

## 9. 工具链与构建结论（SubB 研究，2026-11-03）

> 完整研究见子 AGENT「toolchain-research」回报；以下为可执行要点。

### 9.1 版本映射（关键）
| 目标 | Hexagon SDK | Hexagon Tools |
|---|---|---|
| V66 (855) | **4.1.0**（官方对应）；**4.3.0 也含 v66 目标**（推荐，QPM3 更易下载，TVM 已验证） | **8.4.06**（不随 SDK 预打包，需单独下） |

### 9.2 获取（需 Qualcomm ID，免费注册 developer.qualcomm.com）
- QPM3 网页：https://qpm.qualcomm.com → 搜 "Hexagon SDK" 选 4.1.0/4.3.0 安装到 `~/Qualcomm/Hexagon_SDK/4.1.0`
- 若 QPM3 无 4.1.0，改用 Qualcomm Software Center 桌面 App（https://softwarecenter.qualcomm.com/）
- 同渠道搜 "Hexagon Tools" → 8.4.06 → 解压到 `$HEXAGON_SDK_ROOT/tools/HEXAGON_Tools/8.4.06/`
- 装后 `source $HEXAGON_SDK_ROOT/setup_sdk_env.source`（导出 HEXAGON_SDK_ROOT / HEXAGON_QAIC_EXE / PATH）

### 9.3 QAIC 生成 stub/skel
```bash
export QAIC=$HEXAGON_SDK_ROOT/tools/qaic/Linux/qaic
export SDK_INC=$HEXAGON_SDK_ROOT/incs
$QAIC -I$SDK_INC hvx_add.idl        # 生成 hvx_add.h / hvx_add_skel.c / hvx_add_stub.c
```

### 9.4 hexagon-clang 编 DSP skel（v66）
```bash
export TOOL=$HEXAGON_SDK_ROOT/tools/HEXAGON_Tools/8.4.06/Tools
export QURT=$HEXAGON_SDK_ROOT/libs/common/qurt/computev66
$TOOL/bin/hexagon-clang -mv66 -mhvx -G0 -fPIC -O3 \
  -Iout -I$HEXAGON_SDK_ROOT/incs -I$QURT/include -I$QURT/include/posix \
  out/hvx_add_skel.c hvx_add_imp.c \
  -shared -o libhvx_add_skel.so \
  -L$QURT/lib -lqurt -lposix -Wl,--no-threads
```

### 9.5 fastrpc 构建与部署
- 仓库 https://github.com/qualcomm/fastrpc ；device 侧交叉：`./gitcompile --host=aarch64-linux-gnu`（若报 libbsd 缺失，先交叉编 libbsd）
- skel .so 部署：`/usr/lib/rfsa/cdsp/`（cDSP），可用 `CDSP_LIBRARY_PATH` 覆盖搜索路径（稳健做法）

### 9.6 Unsigned PD（cDSP 跑无签名 skel 的关键，必须在首次 FastRPC 调用前）
```c
#include <remote.h>
#pragma weak remote_session_control
if (remote_session_control) {
    struct remote_rpc_control_unsigned_module data;
    data.enable = 1; data.domain = CDSP_DOMAIN_ID;   // domain 3 = cDSP
    remote_session_control(DSPRPC_CONTROL_UNSIGNED_MODULE, &data, sizeof(data));
}
// 能力查询：remote_dsp_capability{CDSP_DOMAIN_ID, UNSIGNED_PD_SUPPORT} → capability==1 即支持
```
依据：Pwn2Own2020 + 小米 mace #581 实测 855 cDSP 可加载无签名 skel；TVM launcher 默认 `enable_unsigned_pd(true)`。

### 9.7 示例工程剩余 TODO（example-refine 收敛后，均为 SDK 就位后按版本微调）
1. Hexagon SDK 4.1.0 确切下载文件名与安装路径（推荐用 4.3.0 规避）。
2. QAIC 生成参数选择（`-mdll` vs 其他组合）。
3. HVX 头文件确切名随 SDK 版本（`Hvx_Vector.h` / `hvx_inlines.h` / `q6op.h` / `hexagon_protos.h`）。
4. HVX intrinsic 名随 SDK 版本。
5. HVX 加锁 API 名随 SDK 版本（`HAP_hvx_lock` / `qurt_hvx_lock`）。
6. `hvx_add_open` 的 uri 形式（`"hvx_add_skel.so"` vs 带路径）。
7. 设备部署细节：host 是否需随附 `libfastrpc.so`、SELinux/verity 处理。
（另：`hvx_add_skel.c` 注释标记 QAIC 生成的 skel 分派入口符号名以生成文件为准。）
> 上述 7 项不影响首次编译框架——SDK 就位后 `make idl skel host` 报错再按版本对应调整即可。

### 9.8 V7 探针方法（实测可用，可复用）
设备侧无 `remote.h`，故直接命中内核 uapi：`/dev/fastrpc-cdsp` + `ioctl(FASTRPC_IOCTL_GET_DSP_INFO, &cap)`，
`cap={domain=CDSP_DOMAIN_ID(3), attribute_id=UNSIGNED_PD_SUPPORT(1), capability=0}`，返回 `capability==1` 即支持。
探针源码（已落到设备 `/tmp/probe_unsigned_pd.c`，root 用设备 gcc 编译运行）与扩展属性探测（HVX_128B/VTCM 等）由子A(device-unsigned-pd) 完成并回报。
D4 编出 fastrpc 用户态后，也可改用标准接口 `remote_handle_control(DSPRPC_GET_DSP_INFO, &cap, sizeof(cap))` 复测，结论应一致。

---

## 10. 下一步 · 用户在 WSL 的执行清单（阶段 1 → 2 关键路径）

> 本 AGENT 沙箱无 WSL，下列步骤由用户在**本机 WSL（x86_64 Ubuntu 20.04/22.04）**内执行。脚本均已写好在 `scripts/hexagon690/`。

### Step 1 — 一次性手动准备（无法自动化，需 Qualcomm 账号）
1. 注册免费 Qualcomm ID：https://developer.qualcomm.com
2. 从 QPM3 网页（https://qpm.qualcomm.com）或 Qualcomm Software Center（https://softwarecenter.qualcomm.com/）下载：
   - **Hexagon SDK 4.3.0**（或 4.1.0，TVM 已验证 4.3.0+`USE_HEXAGON_ARCH=v66` 可编 855）
   - **Hexagon Tools 8.4.06**（v66，不随 SDK 打包，单独下到 `$HEXAGON_SDK_ROOT/tools/HEXAGON_Tools/8.4.06/`）
3. （建议）对设备 `ssh-copy-id root@192.168.x.x` 免密，避免部署脚本写密码。

### Step 2 — WSL 内跑脚本（顺序 00 → 01 → 02）
```bash
cd /mnt/f/work/WorkBuddy/k20pro/scripts/hexagon690   # 或把项目拷进 WSL 家目录
bash 00_install_sdk.sh      # 校验 SDK/Tools 就位，source 环境，打印 hexagon-clang/qaic 版本
bash 01_build_fastrpc.sh    # host + device(aarch64) 交叉编译 qualcomm/fastrpc，产出到 ~/staging/fastrpc
bash 02_deploy_fastrpc.sh   # 推 libfastrpc.so+守护进程+udev 到设备，建 fastrpc 组
```
> 若 `01_build_fastrpc.sh` 报 libbsd 缺失，按其注释先交叉编 libbsd 再重跑。

### Step 3 — 编示例 + 部署 + 运行（里程碑 D8）
```bash
cd /mnt/f/work/WorkBuddy/k20pro/src/hexagon690
make idl      # QAIC 生成 hvx_add.h/_skel.c/_stub.c
make skel     # hexagon-clang -mv66 -mhvx 编 libhvx_add_skel.so
make host     # gcc 编 host_main，链接 -lfastrpc
make deploy   # scp .so 到设备 /usr/lib/rfsa/cdsp
make run      # 设备上运行，预期打印逐元素校验 PASS
```
> 预期：host 经 FastRPC 调 cDSP 上自编 HVX 向量加，Unsigned PD 加载成功，输出 `PASS`。
> 若 `make` 报错，按 §9.7 的 7 类 SDK 版本差异逐项微调（主要是 HVX 头/intrinsic/加锁 API 名）。

### 当前卡点（已过时，见 §11/§12）
~~只剩 Step 1 的手动 SDK 下载。~~ SDK、工具链、示例工程、部署均已完成；**当前卡点已变为 DSP 侧 `INIT_CREATE` 协议不兼容**，详见下节。

---

## 11. D8 阻塞的定性结论（2026-11-05 ~ 11-06）

### 11.1 已经走通的完整链路

```
rEFInd → vmlinuz-7.0.0-sm8150 + 独立 DTB（只留 cdsp / 12× dma-coherent）
       → qcom_q6v5_pas 解封 → remoteproc0 cdsp=running
       → /dev/fastrpc-cdsp + /dev/fastrpc-cdsp-secure
       → cdsprpcd（root-PD daemon，10-searchpath.conf 修好搜索路径）
       → GET_DSP_INFO ✅  /  INIT_ATTACH ✅  /  INVOKE 基础调用 ✅
       → INIT_CREATE ❌ AEE_EBADASID  ← 唯一硬阻塞
```

网络：USB-NCM `172.16.42.1`；启动项 `"Boot stage2 (cdsp)"`；**全程用 `systemctl reboot`，绝不 kexec**。
Wi-Fi 因 DT 禁用 modem（`QMI_WLFW_CAL_REPORT_REQ` 会锁死 SoC fabric）而主动放弃，不是故障。

### 11.2 决定性实验数据

用两个新建的诊断资产（不依赖 strace/外网）取得：

| 资产 | 路径 | 作用 |
|---|---|---|
| 原始 ioctl 探针 | `tmp/boot_probe/fastrpc_probe.c` | 只用内核 UAPI，绕过 `libcdsprpc`，逐个发 `GET_DSP_INFO`/`INIT_ATTACH`/`INIT_CREATE` |
| LD_PRELOAD 追踪 shim | `tmp/boot_probe/ioctl_trace.c` | dump 每次 `'R'` 族 ioctl 及 `struct fastrpc_init_create` 内容 |
| LD_PRELOAD 注入 shim | `tmp/boot_probe/fastrpc_inject.c` | 环境变量控制：节点重定向 / 补发 attach / 改写错误码 |

关键结果：

```text
# host_main / fastrpc_test 实际只发两步
[OPEN ] /dev/fastrpc-cdsp-secure -> fd=5
[IOCTL] nr=13 GET_DSP_INFO      -> rc=0
[IOCTL] nr=5  INIT_CREATE       -> rc=-2147482541 (0x80000453)
        create{filelen=933772, filefd=7, attrs=0x8(UNSIGNED), siglen=0, file=mmap}

# 原始探针（同一节点）
GET_DSP_INFO attr 0..8 全部 rc=0   (attr=6 -> 0x00018466，低位 0x66 = V66)
INIT_ATTACH                       -> rc=0 ✅
INIT_CREATE (含 attach)           -> 0x8000041a AEE_EALREADY
INIT_CREATE (跳过 attach)         -> 0x80000453 AEE_EBADASID   ← 与上面完全一致

# cdsprpcd
INIT_ATTACH (nr=4)                -> rc=0 ✅
MEM_MAP    (nr=10)                -> 0x80000414 AEE_EUNSUPPORTED
后续 INVOKE                       -> 0x14 / 0x8000041d / EPERM
```

### 11.3 错误码对照（设备 `/usr/local/include/fastrpc/AEEStdErr.h`，`AEE_EOFFSET=0x80000400`）

| 值 | 宏 | 含义 |
|---|---|---|
| `0x80000414` | `AEE_EUNSUPPORTED` | API not implemented（DSP 拒绝 `INIT_MEM_MAP`） |
| `0x8000041a` | `AEE_EALREADY` | 同一 fd 已 attach 为 root PD 后再 create |
| `0x8000041d` | `AEE_EMEMPTR` | bad memory pointer, expected NULL |
| `0x80000453` | **`AEE_EBADASID`** | **Bad ASID — user PD 创建失败** |
| `39` | `AEE_ENOSUCH` | 吞掉错误码后 invoke 找不到对象，反证 PD 没建立 |

### 11.4 已排除的假设（都不要重复试）

1. **cDSP 缺 `memory-region` → 证伪，`stage2b_memory_region.py` 已标记 DEPRECATED 且从未执行。**
   内核 `fastrpc_init_reserved_mem()`：*「Only SDSP and ADSP domains use a reserved remote heap region」*，`domain_id != SDSP && != ADSP` 直接 `return 0`；`no reserved DMA memory for FASTRPC` 是 `dev_dbg` 非致命；上游 `sm8150.dtsi` 的 cdsp 节点本就无 `memory-region`/`qcom,vmids`；`qcom,vmids` 只服务 `FASTRPC_ATTR_SECUREMAP`；Radxa 31391 补完仍失败。
2. **设备节点选错** → `-secure` 重定向到非 secure，错误码不变。
3. **PD 类型 / arch 版本** → `-U 0/1` × `-a v68/v75` 四组全同。
4. **attach 顺序** → 补发 `INIT_ATTACH` 只把 `EBADASID` 变 `EALREADY`，仍失败。
5. **listener heap / MEM_MAP** → `ADSP_LISTENER_MEM_CACHE_SIZE=0` 不消除 nr=10；FARF 实验也显示 `adspmsgd not supported`、`set_logging_params` 返回 `0x4e`。
6. **固件版本混拼** → `firmware-xiaomi-raphael 1.3` 经 `dpkg -V` 完整，cdsp 固件与 shell 同包同源。
7. **用户态误判** → 把 `INIT_CREATE` 错误码改写成 0 后，后续 `INVOKE` 全部 `AEE_ENOSUCH`/`AEE_EUNABLETOLOAD`，PD 确实没建起来。

### 11.5 根因（已定性）

`fastrpc_shell_unsigned_3` 的编译路径暴露固件版本：

```text
/local/mnt/workspace/CRMBuilds/CDSP.HT.2.0.1-00171-SM8150-1.357350.2_20201211_224311/
    b/cdsp_proc/platform/mod_table/src/mod_table.c
```

即 **2020-12-11 的 SM8150 `CDSP.HT.2.0.1` cDSP 固件**。而这套系统用的是：

- 内核 `7.0.0-sm8150`（`fastrpc` **builtin**，无 `.ko` 可换，设备上只有 headers 无源码）
- `libcdsprpc` / `cdsprpcd` / `fastrpc_test` 来自 `quic/fastrpc`（该仓库首个提交 2024-05，**没有 2019/2020 tag**）

`FASTRPC_IOCTL_MEM_MAP` / `FASTRPC_RMID_INIT_MEM_MAP=10` 是 **2022-02 的 LKML patch v4** 才加进内核的；`set_logging_params`、method 8 等新 RPC 更晚。**2020 固件整批不实现这些新 RMID**，日志里 `AEE_EUNSUPPORTED (0x80000414)` 反复出现即为证据。

LKML 2026-05 的「Reduce log level for DSP info and reserved memory messages」补丁讨论也明确：某些 SoC 的 DSP 固件不实现 attribute RPC 属正常配置，社区只把日志从 `dev_err/dev_info` 降为 `dev_dbg`，**并不视为错误**——所以 dmesg 的 `no reserved DMA memory` 与 `mem mmap error` 是噪声，不是 D8 的根因。

另有旁证：XiaoMi/mace#581 记录 **SM8150 2019 固件对 unsigned PD 有已知错误限制**（Qualcomm 后修，存量设备未同步）；Qualcomm 官方 `fastrpc#325` 里 maintainer 处理同类 `remote_init failed` 时首要核对的就是 **DSP payload/shell 来源与 libcdsprpc 版本配对**；SDM660 的 LKML 讨论里 Qualcomm 工程师确认「老平台 CDSP 固件不支持 unsigned offload 时应直接返回失败」。

**结论：D8 的阻塞是「固件协议代际不兼容」，不是 DTB、路径、权限、节点、PD 类型或启动配置问题。** 所有低风险旋钮已扫完，剩下的修复都需要动内核或换栈。

---

## 12. 后续路线（需要决策，按成本/风险排序）

> 当前设备状态是**干净且稳定**的：cdsp running、USB-NCM 可达、cdsprpcd active、DTB 为 stage2 版、无实验残留。
> 任何下一步都要用 `systemctl reboot`，**绝不 kexec**。改 DTB 前先 `cp .bak.stage2b`。

| # | 路线 | 成本 / 风险 | 判断 |
|---|---|---|---|
| 1 | **抓 DSP 侧 mini-dm/FARF 日志**，把 `AEE_EBADASID` 从「推测」变成「确证」 | 低 | 建议先做。放 `<进程名>.farf`（`0xffffffff`）到 `ADSP_LIBRARY_PATH`，但本机 `adspmsgd` 因 API 不支持起不来，可能拿不到；若无果则直接转 2 |
| 2 | **重编 7.0 内核的 `fastrpc` 驱动** | 高 | ~~需完整内核源码树 + 交叉工具链 + 重编 vmlinux~~ → **本轮已改写，见 §13**：找到同源官方预编译内核（`fastrpc=m`，自带 `fastrpc.ko`），刷入后只需重编单个模块；设备原生编译依赖齐全（§13.4）。**唯一未解决的是"补丁内容"，不是"能不能编"** |
| 3 | **换更新版 SM8150 cDSP 固件**（若存在晚于 2020-12 的 `CDSP.HT.2.x`） | **中 / 风险重估为文件级可回滚** | ⚠️ **本行原结论已被 §16 证伪并改写**：`linux-msm/dsp-binaries/config.txt` 确实无 sm8150 条目，但**小米官方后续 MIUI 包里有** `CDSP.HT.2.0.1-...419065.1_20210730_070147`（晚 7 个月）的整机同版本配套集；mainline 从根文件系统加载，属**文件替换 + reboot**，不刷分区、不碰 PBL/XBL。**→ 升为首选路线，见 §16** |
| 4 | **降级用户态到 AOSP 2020 `platform/external/fastrpc`** | 高 | ⚠️ **本行 ABI 判断已被 §16 修正**：公开可取的同代 AOSP 2019 源码用的就是 `/dev/fastrpc-cdsp` + nr 1–7 + `ALLOC_DMA_BUFF`，与 mainline **ABI 兼容**（downstream BSP 变体才用 `adsprpc-smd`/ION）。但 `INIT_CREATE` 发给 DSP 的 RMID 由**内核** `fastrpc_init_create_process()` 构造，换用户态库不改变 DSP 看到的请求 → **明确降级，不作主线** |
| 5 | **用 `hexagonrpcd` 走 sensors PD 作对照** | 低 | 同款 K20 Pro / SM8150 / 7.3-rc 上 LKML 2610.0/05977 已验证可 attach sensors PD 且零 SMMU fault；但当前 DT 把 slpi 禁用了，且它只服务 `/dev/fastrpc-sdsp`，**不能直接达成 D8**，仅用于证明「HexagonRPC 通道本身能通」 |
| 6 | 接受 D8 受阻，转做「iOS 外观 / 路线 A 真机移植」等其它目标 | — | 由用户决定 |

**维护项（不阻塞 D8，随时可做）**
- `chmod 644 /etc/systemd/system/usb-ncm.service.d/timeout.conf` 消除 world-writable 警告
- `/data2`（`loop0`，418G 空闲）出现 EXT4 dirblock checksum 错误，需卸载后 `e2fsck -D`；目前 `/data2/fastrpc` 源码已读不出
- `src/hexagon690/Makefile` 仍写死旧 SDK 路径 `4.1.0/8.4.06`，应改为 `4.3.0.0`
- `hvx_add_imp.c` 仍是标量循环，可升级为真正 1024-bit HVX 向量化

**回滚路径**：`/boot/dtbs/qcom/sm8150-xiaomi-raphael.dtb.orig`（原始）、`.bak.stage2`（阶段 1）、`/boot/refind_linux.conf.bak.*`（各阶段启动项）。

---

## 13. 方案 1 落地评估 + 用户态降级实验（2026-11-06）

> 用户选择路线 2（重编内核）后，本轮先做「主机侧 + 设备侧准备评估」，再动设备。
> **结果：准备工作全部完成，但发现方案形态需要改写，且补丁内容仍未确定。**

### 13.1 结论速览

1. **设备内核来源已定位**（此前记为"找不到源码"）：`GengWei1997/kernel-deb` 的 `7.0` 分支 CI，工具链/配置/产物指纹与设备逐项吻合。
2. **存在比"从头重编内核"好得多的路径**：同源官方 release 自带 `fastrpc.ko`（`CONFIG_QCOM_FASTRPC=m`）。刷入该内核后，`fastrpc` 从 builtin 变成可单独替换的模块，后续迭代只需重编一个 `.ko`。
3. **但"补丁改什么"仍未确定**：本轮用社区现成补丁做了用户态降级实验，结果证明 **legacy `RMID_INIT_MMAP` 会把这块 2020 固件的 cDSP RPC 通道挂死**。因此 §12 里设想的「`AEE_EUNSUPPORTED → RMID_INIT_MMAP` fallback」不是可用补丁。
4. ~~**没有更新的固件可换**：同源官方固件包里的 `fastrpc_shell_unsigned_3` 是 933772 字节，与设备 `INIT_CREATE` 的 `filelen=933772` 完全一致，即同一套 2020-12 固件。~~ ⚠️ **该结论已于 §16 被证伪**：它只能说明「同源官方 *kernel-deb* 固件包与设备同版」，不代表不存在更新固件。小米 China Stable `V12.5.6.0.RFKCNXM` 包里有 **2021-07-30 build**，shell 为 939664 / 935256 B，与设备不同。
5. 设备已 **正常重启复位**，回到干净基线 `0x80000453`；实验期间改过的两个 `.so` 已按 sha256 还原。

### 13.2 内核源码溯源（决定性，已证实）

| 项 | 内容 |
|---|---|
| 构建仓库 / 分支 | `github.com/GengWei1997/kernel-deb` @ `7.0` |
| workflow | `.github/workflows/编译kernel.yml`，`runs-on: ubuntu-24.04-arm` |
| 工具链 | `apt.llvm.org/llvm.sh 22` → `make ARCH=arm64 LLVM=-22`（clang/LLD 22.1.8） |
| 内核树 | `GengWei1997/linux` @ `raphael-7.0`（**该分支现已被删除，404**；全局搜索 `c526b7bf7ebc` 也是 0 命中） |
| 配置 | `raphael.config` 片段，`CONFIG_LOCALVERSION="-sm8150"`、`LOCALVERSION_AUTO=y`；`make defconfig raphael.config` 合成 251KB `.config` |
| 构建 | `patch scripts/package/builddeb < builddeb.patch` → `make ... deb-pkg`（`builddeb.patch` 把 SM8150 DTB 装进 `/boot/dtbs/qcom/`） |
| 安装侧 | `github.com/GavinLiuOnline/xiaomi_raphael_build_rootfs`：vendor=`\boot`、userdata=`/`、cust=rEFInd EFI，`dtb=\dtbs\qcom\sm8150-xiaomi-raphael.dtb` |
| 指纹 | `root@runnervmrvz09`（GitHub 托管 runner + sudo 编译）、vmlinuz 14MB、config 251KB、DTB 路径、`EFI_ARMSTUB_DTB_LOADER=y`、`Q6V5_PAS=m` 全部吻合 |
| **设备差异** | 官方版 `CONFIG_QCOM_FASTRPC=m`，设备是 `=y`；`-dirty` 表示构建时已跟踪文件有未提交改动（很可能是把 config 的 `m` 改成 `y`） |

`runnervm*` 是 GitHub 托管 runner 的命名模式（`fv-az*` 为旧式），主机名不含 org/repo 信息，定位靠的是产物指纹而非主机名。

### 13.3 官方 `kernel-v7.0` 产物清单（已下载解包验证）

release 资产：`linux-image-xiaomi-raphael.deb`、`linux-headers-xiaomi-raphael.deb`、`firmware-xiaomi-raphael.deb`、`alsa-xiaomi-raphael.deb`。

| 文件 | 本机路径 | 大小 / 校验 |
|---|---|---|
| linux-image | `tmp/kernel/linux-image-xiaomi-raphael-v7.0.deb` | 24,062,614 B，sha256 `224ec0668e90247617bc2df43bbf17d9bb095ffbf33ae4879063ad505980cd0e` |
| linux-headers | `tmp/kernel/v7.0-linux-headers-xiaomi-raphael.deb` | 9,341,184 B |
| firmware | `tmp/kernel/v7.0-firmware-xiaomi-raphael.deb` | 58,677,214 B |
| 官方 config | `tmp/kernel/official-v7.0.config` | 251,427 B |

`linux-image` 解包结果（主机用 Python 解析 ar + `zstandard.stream_reader`，**注意 zstd 帧没有 content size，必须流式解压**）：

```text
./boot/vmlinuz-7.0.0-sm8150-g0a80d398394a            13,644,288 B
./boot/config-7.0.0-sm8150-g0a80d398394a                251,427 B
./boot/System.map-...                                 6,418,244 B
./boot/dtbs/qcom/sm8150-xiaomi-raphael.dtb               105,436 B   （共 11 个 DTB）
./lib/modules/.../kernel/drivers/misc/fastrpc.ko          44,600 B  ★
共 911 个 .ko
```

关键配置：`CONFIG_QCOM_FASTRPC=m`、`QCOM_Q6V5_PAS=m`、`EFI_ARMSTUB_DTB_LOADER=y`、`IKCONFIG=y`、`KALLSYMS_ALL=y`、`DEBUG_INFO=y`、`DEBUG_INFO_BTF`/`LIVEPATCH` 未启用、`FTRACE`/`KPROBES` 关闭。

`firmware` 包内容：`cdsp.mbn` 3.4MB、`fastrpc_shell_3` 938172 B、**`fastrpc_shell_unsigned_3` 933772 B**（与设备同版）、`map_SHARED_LIBS_855.cdsp.prodQ.txt` 等。

### 13.4 设备原生编译能力盘点（推翻此前"缺依赖"的判断）

| 项 | 实测 |
|---|---|
| 内存 / CPU / 磁盘 | **11 Gi / 8 核 / `/` 436G 可用**（此前记为 ~6GB 是错的，Ubuntu 官方建议 ≥8GB 已满足） |
| 编译器 | gcc 13.3.0、GNU ld 2.42、Make 4.3 |
| 已有构建依赖 | `build-essential`、`bc`、`bison 3.8.2`、`flex 2.6.4`、`dtc 1.7.0`、`cpio`、`zstd`、`libssl-dev`、`initramfs-tools`、`kmod`、`pkg-config`、`yaml-0.1`、`libbsd-overlay` **全部在位** |
| 缺失 | `pahole`/`dwarves`、`clang`、`ld.lld` —— 但官方 config 无 `DEBUG_INFO_BTF`，**不需要 pahole**；纯用 gcc 可编 |
| 内核 config | `/proc/config.gz` 与 `/boot/config-7.0.0-...` 都在，已拉回 `tmp/boot_probe/kernel-7.0.0-raphael.config{,.gz}` |
| 内核源码 | **设备上完全没有**，只有 `/usr/src/linux-headers-...`；`/data2` ext4 损坏严重（`fsck.ext4 -n` 报 inode 7 大量非法块后中止），不能指望从那里恢复 |
| 网络 | 设备无外网（DNS 不可用），大文件靠主机下载 + SFTP；**23MB SFTP 曾卡住并导致 sshd 会话耗尽**，后续改用小批量或主机侧预处理 |

结论：**设备原生编译内核/模块完全可行**，主机侧也可 `git clone torvalds/linux@v7.0`（已完成，`tmp/kernel/linux-v7.0`，2.0G）作为源码参考。

### 13.5 用户态降级实验（PR #319，已完整回滚）

**动机**：子代理取证发现 `FASTRPC_IOCTL_MEM_MAP (nr=10)` 是**用户态主动发的**，内核只是被动分发；内核里 `nr=6` 的 legacy `fastrpc_req_mmap()` 完整实现仍在。社区 `qualcomm/fastrpc` **PR #319**（`apps_mem: fallback to legacy mmap/unmap when internal API fails`）专治 `AEE_EUNSUPPORTED`，reviewer "Change LGTM"、LAVA 三平台 Passed（但**未合并**，被方向相反的 #338 取代）。

**做法**：主机 clone `qualcomm/fastrpc` 到 PR 基线 `3afb4a0`，`git apply --check` + apply PR319 diff（29+/7-，只改 `src/apps_mem_imp.c`），打包传到设备 `/opt/fastrpc-pr319`（避开损坏的 `/data2`），`./gitcompile` + `make -j6`，只替换 `libcdsprpc.so.1.0.0` 与 `libcdsp_default_listener.so.1.0.0`（daemon 是薄壳，`ldd` 只链 libc，通过 dlopen listener 加载补丁逻辑）。完整备份在设备 `/opt/fastrpc-backup-20261106/`。

> 坑：Windows tarball 带 CRLF，`#!/bin/bash\r` 会让设备报"找不到需要的文件"，且丢可执行位。部署脚本已加 `CRLF_FIXED 171` 归一化步骤 + `chmod +x`。

**实验矩阵与结果**：

| 版本 | ioctl trace | 结果 |
|---|---|---|
| 未打补丁（基线） | `nr=10 → 0x80000414`，**无 nr=6** | `0x80000453` |
| **v1**（PR319 原样） | `nr=10 → 0x80000414` → **`nr=6 → -1, errno=22 EINVAL`** | `0x80000453` 不变 |
| **v2**（flags 修正） | nr=6 不再被 flags 校验挡住 | **`fastrpc_test`/`host_main` 变 `-1`**；最小探针连 `INIT_ATTACH` 都变 `-1 / errno=110 Connection timed out` |

**v1 的 EINVAL 已精确定位**：内核 v7.0 `fastrpc_req_mmap()` 第 1919 行硬校验
```c
if (req.flags != ADSP_MMAP_ADD_PAGES && req.flags != ADSP_MMAP_REMOTE_HEAP_ADDR)
    return -EINVAL;          /* ADSP_MMAP_ADD_PAGES = 0x1000 */
if (req.vaddrin) return -EINVAL;
```
PR319 的 fallback 原样传 `rflags=0x0`，被挡在参数校验，RMID 根本没发到 DSP。

**v2** 把 fallback 改为 `remote_mmap64_internal(fd, ADSP_MMAP_ADD_PAGES, 0, len, vadsp)` 后：dmesg 不再出现 `flag not supported 0x0`（说明 `nr=6` 已通过内核校验、发出 `RMID_INIT_MMAP(4)`），但随后 **cDSP 的 glink/RPC 通道挂死**：`GET_DSP_INFO` 还能回，`INIT_ATTACH` 变 `errno=110 timeout`，`remoteproc0` 因 `recovery=disabled` 仍显示 `running`。

**处置**：恢复原始 `.so`（sha256 `89d89378…` 比对一致）后仍为 `-1`，确认是 DSP 侧状态而非库文件问题 → 执行正常 `systemctl reboot`（**未用 kexec**）→ 重跑 `usb-ncm-up.ps1` 重连 → **基线完全恢复**：`fastrpc_test` / `host_main` 回到 `0x80000453`，cdsp `running`、`/dev/fastrpc-cdsp[-secure]` 在位、`cdsprpcd active`。

**结论（重要）**：legacy `RMID_INIT_MMAP` 对这块 2020-12 固件**不是可用降级路径**；它至少在当前参数形态下会让 DSP 挂死。因此 §12 设想的内核补丁「`AEE_EUNSUPPORTED → RMID_INIT_MMAP` fallback」**方向不成立**，不能直接照做。（限定：这是用户态 fallback 的参数形态；内核侧复用 dma-buf mapping 的等价补丁尚未验证，不能由本实验直接外推为"必然也挂死"。）

### 13.6 新增验证项（V20–V28）

| ID | 项 | 状态 |
|---|---|---|
| V20 | 设备内核源码来源可定位 | ✅ `GengWei1997/kernel-deb@7.0` + `raphael-7.0`（已删） |
| V21 | 同源官方预编译内核自带 `fastrpc.ko` | ✅ 44,600 B，`CONFIG_QCOM_FASTRPC=m` |
| V22 | 设备具备原生内核编译能力 | ✅ 11Gi/8核/436G，依赖齐全，无需 pahole（BTF 关闭） |
| V23 | 官方固件包含更新版 cDSP payload | ❌ 同版（shell 933772 B 一致） |
| V24 | 用户态 PR319 能触发 legacy fallback | ✅ `nr=10 → nr=6` 首次出现 |
| V25 | `nr=6` 被内核 EINVAL 的根因 | ✅ `fastrpc_req_mmap()` flags 校验（1919 行） |
| V26 | 修正 flags 后 legacy mmap 能让 D8 通过 | ❌ DSP 挂死（`errno=110`），需整机复位 |
| V27 | `INIT_CREATE` 的 attrs/RMID 选择是根因 | ❌ 已证伪：内核 `attrs!=0→RMID7 / =0→RMID6`，而探针 signed(=0) 与 unsigned(0x8) 都返回 `0x80000453` |
| V28 | 实验可完整回滚 | ✅ 原始 `.so` sha256 复原 + 重启后基线可复现 |

### 13.7 方案 1 的新形态与尚未解决的决策点

**新形态**（比原计划省一大截）：

1. 把设备内核换为官方 `kernel-v7.0`：`vmlinuz-7.0.0-sm8150-g0a80d398394a` + `lib/modules/...`（911 个 .ko）+ `linux-headers` 包；
2. **必须保留我们改过的 stage2 DTB**（只留 cdsp + 12 个 `dma-coherent`），不要用官方 .deb 里的 `sm8150-xiaomi-raphael.dtb` 覆盖；
3. 新增 rEFInd 启动项，**默认仍指向旧内核**，`default_selection` 显式写旧项标题，保证可回滚；
4. 之后 `fastrpc` 是 `.ko`，用 `linux-headers` + `fastrpc.c` 即可单独重编迭代（不必反复整包编译）。

**部署硬约束**（已证实）：`CONFIG_EFI_ARMSTUB_DTB_LOADER=y` + Secure Boot disabled，否则 EFI stub 忽略 `dtb=` 直接起不来；新文件名不覆盖旧 `vmlinuz`/`initrd`；`update-initramfs -c -k <ver>` 生成新 initrd（版本目录名必须与 `/lib/modules/<ver>` 一致）。

**仍未解决**：没有一个已验证的 `fastrpc.c` 补丁内容。`INIT_CREATE → AEE_EBADASID` 是 DSP 侧创建 user PD 失败，内核无法直接替 DSP 修 ASID；已排除 RMID 选择、节点、PD 类型、attach 顺序、listener heap、`memory-region`、固件混拼。继续盲目刷内核只会换来一个"同样失败但可换模块"的状态。

**因此本轮停在决策点**：要么 (a) 先做一个能验证「root-PD 不完整导致 INIT_CREATE 失败」的最小实验（例如让 `cdsprpcd` 完全不发 nr=10 后重测，成本极低、零刷机），确定补丁目标后再刷官方内核；要么 (b) 直接刷官方内核取得模块可替换能力，同时接受补丁仍需继续研究；要么 (c) 接受 D8 受阻，转其它目标。

### 13.8 本轮新增资产

| 路径 | 用途 |
|---|---|
| `tmp/boot_probe/pr319.diff` | PR #319 原始 diff（69 行） |
| `tmp/boot_probe/fastrpc-pr319/` | 已打 v1 补丁的干净源码树（本机） |
| `tmp/boot_probe/fastrpc-pr319.tar.gz` | 传设备用的打包 |
| `tmp/boot_probe/deploy_pr319.py` | `build` / `install` / `restore` / `test` 四态部署脚本，含 CRLF 归一化 |
| `tmp/boot_probe/kernel-7.0.0-raphael.config{,.gz}` | 设备内核 config 基线 |
| `tmp/boot_probe/fastrpc-v7.0.c` | 内核 v7.0 `fastrpc.c`（补丁点分析） |
| `tmp/kernel/linux-image-xiaomi-raphael-v7.0.deb` 等 3 个 .deb | 官方内核 / headers / 固件 |
| `tmp/kernel/official-v7.0.config` | 官方 config |
| `tmp/kernel/linux-v7.0/` | `torvalds/linux@v7.0` shallow clone（参考） |
| 设备 `/opt/fastrpc-pr319/`、`/opt/fastrpc-backup-20261106/` | 补丁构建树与原始库备份 |

### 13.9 计划打标记（更新）

- [x] **K1** 定位设备内核源码来源 — ✅ 见 §13.2
- [x] **K2** 取得可复现内核/模块基线 — ✅ 见 §13.3
- [x] **K3** 设备编译能力盘点 + config 落档 — ✅ 见 §13.4
- [x] **K4** 用户态降级实验（PR319）与回滚 — ✅ 见 §13.5
- [ ] **K5** 确定 `fastrpc.c` 的具体补丁内容 — ⏳ **当前唯一硬阻塞**（§13.7 决策点）
- [ ] **K6** 刷官方内核（保留 stage2 DTB + rEFInd 回滚项）— ⏸ 待 K5，属高风险动作
- [ ] **K7** 用 `linux-headers` 单独重编 `fastrpc.ko` 并验证 D8 — ⏸ 待 K6
- [ ] **清理项** `chmod 644 /etc/systemd/system/usb-ncm.service.d/timeout.conf`；`/data2`(loop0) ext4 需离线 `e2fsck -D`；`src/hexagon690/Makefile` 旧 SDK 路径 `4.1.0/8.4.06` → `4.3.0.0`；`hvx_add_imp.c` 标量循环 → HVX 向量化

---

## §14 零刷机 root-PD 实验（2026-11-06 第二轮，链路受阻 / 待设备复位后执行）

### 14.1 用户决策

上一轮（§13.7）三个方向中用户选 **1（推荐）**：设备重启后先做**零刷机实验**，验证「root-PD 初始化不完整导致 `INIT_CREATE` 失败」，确定补丁目标之后再刷官方内核。本轮不含任何刷机 / DTB 修改 / 内核替换动作。

### 14.2 设备链路诊断：sshd 全局阻塞，物理重启是唯一解（本轮新增证据）

上一轮末尾：23MB SFTP 被取消后，设备 ping / 22 端口 / SSH 认证全部正常，但 `open_session()` 连续超时。本轮逐项排查：

| 尝试 | 结果 | 推论 |
|---|---|---|
| 端口扫描（22/80/443/5555/5037/8080/…/8888） | **只有 22 开放** | 无备用控制通道 |
| `adb devices -l` / `fastboot devices` | **均无设备**（Ubuntu 正常启动时无 adbd） | 不能靠 adb 救 |
| `paramiko open_session(timeout=45)` | 仍超时 | 不是客户端超时太短 |
| `no-more-sessions@openssh.com` 全局请求后再开 session | 仍超时 | 与 session 数上限无关 |
| Windows `iphlpapi!SetTcpEntry(MIB_TCP_STATE_DELETE_TCB)` 拆除残留 `172.16.42.2:14417 → 172.16.42.1:22 ESTABLISHED` | **`rc=0`，主机侧连接全部清空**，设备侧仍超时 | 主机侧残留 TCP 不是唯一原因 |
| **`direct-tcpip` 通道**（127.0.0.1:22 / 5555 / 19531 / 4713） | **全部同样 `Timeout opening channel`** | 与 PAM 卡点**一致**而非排除它：`server_loop2()` 未启动前，所有 CHANNEL_OPEN（含转发通道）的统一入口 `server_input_channel_open()` 根本没注册 |
| `Get-PnpDevice` / `Win32_SerialPort` 查 USB ACM 串口 | 只有蓝牙 **COM6 / COM7**，无 `/dev/ttyGS0` 类串口 | 无串口登录通道 |

**根因（源码级，第二个子代理取证，修正了本轮早期"sshd 主进程阻塞、不是 PAM"的推论）**：OpenSSH 9.6p1 在发出 `SSH2_MSG_USERAUTH_SUCCESS` 之后、`server_loop2()` 之前，**同步**执行 `do_pam_session()`：

- `sshd.c:2300–2303` `do_pam_setcred(1); do_pam_session(ssh)`；`privsep_postauth()`(2311) / `do_authenticated()`(2328) / `server_loop2()` 都在其后；
- `auth-pam.c:1208–1229` 的 `pam_open_session()` 是**无超时的同步调用**；Ubuntu 24.04 `/etc/pam.d/sshd` → `common-session` → `pam_systemd.so` → logind D-Bus `CreateSession`；systemd v255 `pam_systemd.c:51` 定义 `LOGIN_SLOW_BUS_CALL_TIMEOUT_USEC = 2*USEC_PER_MINUTE`（**120 秒**）；
- `serverloop.c:911–930` 的 `server_init_dispatch()` 才注册 `SSH2_MSG_CHANNEL_OPEN → server_input_channel_open`；卡在 PAM 时 monitor **不在读 socket**，客户端发的 CHANNEL_OPEN 进内核缓冲后无人处理 → 无 CONFIRMATION、无 FAILURE、无 disconnect；
- `do_exec` / fork / utmp / sshrc / MaxSessions 全部发生在 CONFIRMATION **之后**，逐一排除。`PerSourcePenalties` 是 9.8 才引入，9.6p1 不存在。

由此每个新连接都产生一个新的、最多 120 秒的阻塞窗口（解释了"反复重连都不行"）。**即使等满 120 秒**：`pam_open_session()` 失败 → `auth_restrict_session()` → `do_child()` 的 `!is_pam_session_open()` 检查（`session.c:1559–1563`）直接 `exit(254)`，**exec 仍不可用**，所以"等超时自愈"不成立。

真正的服务级修复是 Ubuntu 仍在运行时在任意 shell 执行**单条** `sudo systemctl restart systemd-logind`（Red Hat 提醒：会强制中断当前所有桌面/用户会话）。**不要附带 `ssh`**：卡点本就在 PAM/logind，restart ssh 既不杀已 fork 的 monitor，也不是修复手段；该结论与 ssh 走常驻 service 还是 socket activation **无关**。（11-05 干净 boot 的 journal 显示 ssh 由 `ssh.socket` 按需拉起、Ubuntu 24.04 默认 `Accept=no`，但 **11-06 事故 boot 是否同一状态未验证【推测】**，不写成事实；`systemctl reload/restart ssh.socket` 只动监听 socket，清不掉卡在 `sd_bus_call()` 的 monitor。）

> ⚠️ **这是理论修复、当前不可执行**：设备 adb 无设备、无 USB ACM 串口、只开 22 端口，拿不到任何 shell；进 TWRP 本身已让 Ubuntu 停机，同样无法"只重启服务"。**实际解只有物理重启**（长按电源键，或进 TWRP 后 `adb reboot` 回 system），不要把它当作可下发的操作步骤。

**结论不变：必须一次物理重启**（长按电源键，或进 TWRP 再 `adb reboot` 回 system）。所有 SSH 协议层 trick 已穷尽，不要在这一点上再花时间。重启后主机侧执行 `scripts/host/usb-ncm-up.ps1`（如路由未自动恢复），再 `python3 tmp/boot_probe/deploy_pdscan.py check` 即可继续。

> 主机侧注意：Windows `netstat` 里到设备 22 的 `ESTABLISHED` 残留可用 `SetTcpEntry` 清掉，但它**不能**替代设备侧重启。

### 14.2b 触发链推测（未确证，需设备侧只读观测）

- 项目文档 §13.4 记有「23MB SFTP 曾卡住并导致 sshd 会话耗尽」，与本轮被强杀的 23MB 上传完全吻合（**二手记录，无运行时证据**）。
- **推测链**：强杀上传 → 遗留未清理的 sshd/logind session（monitor 卡在 `sd_bus_call()` 时不读 socket，TCP RST 感知不到，`pam_close_session()` / `ReleaseSession` 不会执行）→ logind 每 session 一个 fd（unit 注释 "we keep one fd open per session"，`FileDescriptorStoreMax=768`）、D-Bus 连接 / scope job 队列饱和 → 此后所有新连接的 `CreateSession` 都挂到 120 秒超时 → 认证成功但 `open_session` 超时，且重连 / 重置网卡都无效。
- **必须区分**：systemd v255 `logind-dbus.c:871–874` 命中 `SessionsMax=8192` 是**立即返回错误**，不是阻塞。所以"会话耗尽"若成立，只能理解为 logind **整体无响应**（fd / D-Bus / scope job 饱和），**不是**命中计数上限，两种机制不能混为一谈。
- 这进一步压低了「等 2 分钟自愈」的可能性：遗留 session 不会自动清理，每次重连反而再留一个最多阻塞 120 秒的 monitor（**正反馈**）。
- **据此调整**：后台等待脚本改为 **banner-only TCP 探测**（只连 22 端口读 SSH banner、不认证，因此不会产生卡在 PAM 的 monitor），每 30 秒检测「端口/ ping 短暂消失」的重启信号；完整 SSH 认证只在**观察到重启**时执行一次（另给 3 次 30 秒快速重试）或每 5 分钟兜底一次。等待窗口 90 分钟。首个 30 分钟窗口已于 `11:04:50` 超时（设备未重启、零改动），复测仍是 ping 通 / 认证通 / `open_session` 超时。
- 证据等级：**推测**。确证需设备恢复后做只读观测：`ps -o wchan,pid,stat,cmd`、`cat /proc/<pid>/stack`、`dmesg`（hung task / D-state）、`journalctl -u systemd-logind -u ssh`、`ls /proc/<logind-pid>/fd | wc -l`（`loginctl list-sessions` 在 logind 卡住时本身也会卡）。**已实现**：`deploy_pdscan.py forensics`（也会被 `check` 自动调用），采集 `--list-boots`、上一 boot 与 11-06 时间窗的 logind/ssh journal、pam/session 关键字、`wchan` / fd 数 / STAT、hung task；每条都包了 `timeout`，输出存 `logs/pdscan/forensics.txt`。设备一重启就会随 P0 流程自动取证。
- 净影响：核心结论（PAM/logind 全局卡死、必须物理重启）**不变**；`cdsprpcd` / 内核态作为根因进一步弱化（V41）。

**证据边界与防误读（主机侧只读取证）**：

- `tmp/boot_probe/{system,latest,prev1,prev2}.journal`、`boot.log`、`tail.txt`、`logs/{dmesg.log,logcat.txt,recovery.log}` **全部是 2026-11-05 的**；`latest.journal` 末条是 `2026-11-05 22:15:43` 的 `MESSAGE=System is powering down.`。11-06 事故时间窗内**没有任何设备日志**（`find -newermt 2026-11-06` 只命中两个 `auto-summary.txt` 等待日志）。→ §14.2b 的触发链**无法用本地日志证实或证伪**，V42 维持【推测】。
- **别把 journal 的 `CODE_FILE=src/login/logind-dbus.c` / `logind-seat.c` / `logind-session.c` / `logind-wall.c` 当成 coredump**：那是正常关机日志的源码位置（`bus_manager_log_shutdown` → "System is powering down."、`warn_wall` → "The system will power off now!"）；全文件无 COREDUMP / Stack trace / SIGSEGV / SIGABRT / `#0 ` 帧。
- 另一条 decoy：`Failed to StopUnit service: GDBus.Error...Process org.freedesktop.systemd1 exited with status 1` 的 `_COMM=gsd-sharing` / `GLIB_DOMAIN=sharing-plugin`，是 gdm(uid=121) session bus 上 GNOME 共享插件的激活失败，**不是 PID1 / 系统 logind 故障**。
- 11-05 干净 boot 只有 2 个 session（`New session 5 of user user`、`New session c1 of user gdm`，都有 `Removed session`），无 `Maximum number of sessions`、无 D-Bus 超时、无 `pam_systemd` 行、ssh 走 `ssh.socket` socket activation。方向上与 SessionsMax 的区分一致，但**属于错误时间窗，不能用来推断 11-06 事故 boot**。

### 14.3 实验设计纠偏：**原 E0–E3 方案已废弃，从未执行**

并行子代理的源码取证直接推翻了「让 cdsprpcd 完全不发 nr=10 后重测」这个前提：

| 证据 | 结论 |
|---|---|
| 内核 `fastrpc_init_create_process():1413–1520` 全程**不调用** `fastrpc_req_mem_map()` | `INIT_CREATE` 与 `MEM_MAP` 是两条独立路径 |
| `cdsprpcd` 只在 ROOT_PD session 上发 `INIT_ATTACH` + `nr=10`（反向 RPC 的 listener heap 映射），**从不发 `INIT_CREATE`** | daemon 与客户端是不同进程 / 不同 fd / 不同 session |
| `fastrpc_mmap_helper()`（用户态 `fastrpc_mem.c:448+`）在 nr=10 成功后把 `vaddrout` 插入 static_map；DSP 用该地址做转换 | **短路并伪造成功会灌入 `vaddrout=0` 的假映射**，与 PR#319 v2 的 glink 挂死同类风险 |
| 全树 grep：只有 `AEE_EUNSUPPORTED → remote_mmap64_internal()` 一个降级点（PR#319 引入），**没有任何环境变量 / 编译开关**能禁用 MEM_MAP | 不存在干净的"跳过 nr=10"旋钮 |
| `adsp_default_listener.c:267` 用 `setenv("ADSP_LISTENER_MEM_CACHE_SIZE","1048576",0)` | 外部设 `=0` 会被覆盖（解释了 V19 的实验现象） |
| 上游 LKML / `docs/` 记录：CDSP 不存在静态 PD，`INIT_CREATE_STATIC` 主要服务 ADSP；`qcom_scm_assign_mem()` 对 CDSP 不做 | 静态 PD 假设限定在 ADSP |

→ `fastrpc_nomemmap.c` / `deploy_rootpd.py` **已标记 DEPRECATED / DO NOT RUN**，设备上从未编译、从未安装 drop-in。这避免了又一次无效实验和一次可能的 cDSP 挂死。

### 14.3b 替代实验（P0–P2）：停掉 daemon，用原始 UAPI 探针扫描 PD 创建协议

驱动 `tmp/boot_probe/deploy_pdscan.py`，探针 `tmp/boot_probe/fastrpc_pdscan.c`（**不链接 `libcdsprpc`、不用 LD_PRELOAD、不改任何已安装文件**）。每个探针进程只发**一个** PD 创建 ioctl，避免同 fd 上连续 create 产生 `AEE_EALREADY` 混淆。

| 阶段 | 动作 | 判别意义 |
|---|---|---|
| **P0** | daemon 运行（干净基线），两个节点 × attach/noattach × attrs `0x8`(RMID7)/`0x0`(RMID6) 共 5 组 | 记录基线错误码矩阵 |
| **P1** | `systemctl stop cdsprpcd`（**完全移除用户态 root-PD 影响**），重跑同一矩阵 | 若 `INIT_CREATE` **仍 `0x80000453`** → 排除 H_A「root-PD 不完整」，指向 H_B「固件代际 / ASID」；若错误码变化 → H_A 成立，补丁目标在 root-PD 初始化 |
| **P2** | daemon 仍停，补 3 组 attrs/attach 组合 | 确认 RMID6/7 两种形态都失败，排除 attrs/RMID 选择 |
| **restore** | `systemctl start cdsprpcd` + 复跑 `host_main` / `fastrpc_test` | 确认回到 `0x80000453` 干净基线 |
| **p2static**（可选、不进自动流程） | 发 `INIT_CREATE_STATIC` (nr=9 / RMID8) | 验证"固件只认静态 PD"假设。这是**固件从未见过的新 RMID，有挂死风险**，必须看完 P0/P1 结果再单独决定 |

全程零刷机、零 DTB 修改、零库替换、零新 RMID（除可选的 p2static）；输出存 `logs/pdscan/`。后台脚本 `run_rootpd_experiment.py` 会等设备物理重启后自动跑 `check → build → p0 → p1 → p2 → restore`，并在 ping 不通时自动重跑 `usb-ncm-up.ps1`。

### 14.4 本轮新增内核侧取证（K5 补丁候选线索，尚未验证）

阅读 `tmp/boot_probe/fastrpc-v7.0.c` 后的**事实**：

| 位置 | 事实 |
|---|---|
| `fastrpc_init_create_process():1413–1520` | `inbuf.client_id = fl->client_id`；`fl->pd = USER_PD`；`is_session_rejected()` **只**检查 secure 节点与 unsigned 支持；`sc = RMID_INIT_CREATE(6)` 或 `RMID_INIT_CREATE_ATTR(7)`；错误全部来自 `fastrpc_internal_invoke()` 返回的 **DSP 响应**，内核自身不产生 `AEE_EBADASID` |
| `fastrpc_init_attach():1707–1718` | `fl->pd = ROOT_PD`，向 DSP 发 `RMID_INIT_ATTACH(0)`，参数只有 `client_id` |
| `fastrpc_session_alloc():1530–1550` | `fl->client_id = i + 1`，`i` 是 `cctx->session[]` 第一个 `!used && valid` 的下标 |
| `fastrpc_cb_probe():2193–2245` | 每个 `qcom,fastrpc-compute-cb` 注册 1 个 session，`sess->sid` 取 DT 的 `reg`；若节点有 `qcom,nsessions = <N>` 则复制出 N 个共享 sid 的虚拟 session；上限 `FASTRPC_MAX_SESSIONS = 14` |

**新发现的 DT 事实**（主机侧离线解析 `tmp/boot_probe/raphael-stage2.dtb`，用 `fdt_inspect.py`）：cdsp 下 **12 个 `compute-cb@3…@14` 的属性集合只有 `compatible` / `iommus` / `reg` / `dma-coherent`，没有 `qcom,nsessions`**；原始 `raphael-current.dtb` 同样没有。而上游 v7.0 的 `lemans.dtsi:7517`、`sc7180.dtsi:4019`、`sm6350.dtsi:1445`、`talos.dtsi:4695` 都写了 `qcom,nsessions = <5>`（sm8150.dtsi 本身没有）。

→ **推测（未验证）**：`AEE_EBADASID` 字面就是 "Bad ASID"，而内核的 ASID 语义完全由 `client_id`（session 下标）承载；若 2020-12 固件期望的 session/ASID 布局与「12 个 cb × 1 session」不一致，`INIT_CREATE` 就会失败。这给出一条**比刷内核便宜得多**的候选路线：改 DTB 的 `qcom,nsessions`（或 `client_id` 分配）后重测。但**必须先排除更简单的解释**，且改 DTB 需要重启与 rEFInd 回滚项，不计入本轮零刷机实验。列为 K5 候选 C3，证据等级：**推测**。

### 14.5 新增验证项与计划标记

| ID | 项 | 状态 |
|---|---|---|
| V29 | 设备存在 SSH 之外的备用控制通道 | ❌ 只有 22；adb/fastboot 无设备 |
| V30 | 拆除主机侧残留 TCP 能恢复 sshd | ❌ `SetTcpEntry rc=0` 后仍开不了 channel |
| V31 | `direct-tcpip` 通道可绕过 session 阻塞 | ❌ 同样超时；源码证明这是 PAM 卡在 `server_loop2()` **之前**的必然结果（§14.2），**不是**排除 PAM |
| V39 | 等满 `pam_systemd` 的 120s 超时后能自动恢复 exec | ❌ `pam_open_session()` 失败 → `do_child()` 的 `!is_pam_session_open()` 检查 `exit(254)` |
| V40 | 有 USB ACM 串口 / adb 等备用 shell 可只重启服务 | ❌ Windows 只有蓝牙 COM6/COM7，adb/fastboot 无设备 |
| V41 | cDSP / 内核 D 状态导致 sshd 挂起 | ❌ 两条调查线独立：PR319 期间挂的是 cDSP glink/RPC（APPS ioctl 以 `errno=110` 返回，已 reboot 复位）；`cdsprpcd.service` 无 logind/dbus 依赖边，无运行时证据支持关联 |
| V42 | 23MB SFTP 强杀 → logind 资源饱和 → 全局卡死 | ⏳ **推测**（§14.2b）：二手记录 + systemd 源码机制吻合，缺设备侧 `/proc/<pid>/stack` / `wchan` / logind fd 计数等只读观测 |
| V32 | 「短路 daemon 的 nr=10」能改变 `INIT_CREATE` | ❌ **实验设计被源码证伪，从未执行**（INIT_CREATE 不经 MEM_MAP） |
| V33 | DT `qcom,nsessions` / session 布局与 EBADASID 相关 | ⏸ 待 P 系列结果 + 上游取证 |
| V34 | `INIT_CREATE` 与 `MEM_MAP` 是独立内核路径 | ✅ `fastrpc_init_create_process():1413–1520` |
| V35 | `cdsprpcd` 从不发 `INIT_CREATE` | ✅ daemon 只在 ROOT_PD 上发 nr=4 / nr=10 |
| V36 | 存在环境变量/编译开关禁用 MEM_MAP | ❌ 全树 grep 无；`ADSP_LISTENER_MEM_CACHE_SIZE=0` 会被 `setenv` 覆盖 |
| V37 | 停掉 cdsprpcd 后 `INIT_CREATE` 错误码变化 | ⏸ **P1 的核心判别项**，待设备物理重启 |
| V38 | RMID6 / RMID7 两种 PD 创建形态都失败 | ⏸ 待 P0/P2 |

- [ ] **K5** 确定 `fastrpc.c` 的具体补丁内容 — ⏳ 仍是唯一硬阻塞；本轮新增候选：
  - C1 `INIT_CREATE` 前由内核自动 `INIT_ATTACH`（需解释用户态补发 attach 得到 `AEE_EALREADY` 的含义）；
  - C2 让 `INIT_CREATE` 复用 root-PD 的 `client_id` / 调整 `fl->pd` 时序；
  - C3 **DT 层**：补 `qcom,nsessions` / 调整 session 布局（零刷内核，但需重启 + 保留 stage2 DTB 回滚）。
- [ ] **K5-pre** P0–P2 零刷机 PD 协议实验 — ⏸ 设备 sshd 阻塞，需用户物理重启一次；后台脚本已挂好自动执行
- [ ] **K6** 刷官方内核（保留 stage2 DTB + rEFInd 回滚项）— ⏸ 待 K5
- [ ] **K7** 单独重编 `fastrpc.ko` 并验证 D8 — ⏸ 待 K6

### 14.6 本轮新增资产

| 路径 | 用途 |
|---|---|
| `tmp/boot_probe/fastrpc_nomemmap.c` | **DEPRECATED / 从未执行**：原 nr=10 短路 shim，保留作反例 |
| `tmp/boot_probe/deploy_rootpd.py` | **DEPRECATED / 从未执行**：原 E0–E3 驱动，保留作反例 |
| `tmp/boot_probe/fastrpc_pdscan.c` | **现行探针**：纯内核 UAPI，单进程单 create ioctl，支持 RMID6/7/8 与 attach/节点矩阵 |
| `tmp/boot_probe/deploy_pdscan.py` | **现行驱动**：`check/build/p0/p1/p2/p2static/restore/reboot`，小文件走 base64 + `exec_command`（**不用 SFTP**，避免重演 23MB 卡死） |
| `tmp/boot_probe/run_rootpd_experiment.py` | 后台等待设备物理重启后自动跑 P0–P2 + restore；ping 不通时自动重跑 `usb-ncm-up.ps1` |
| `logs/pdscan/` | 实验输出目录（设备恢复后生成） |

---

## §15 P0–P2 实验结果（2026-11-06 18:49 自动执行完毕）

### 15.1 执行与设备恢复时间线

常驻守护 `run_rootpd_experiment.py 0` 在 `16:48:52` 首次检测到链路消失并自动重跑 `usb-ncm-up.ps1`（NCM 恢复但 sshd 仍卡），`18:48:20` 第二次链路消失，`18:49:12` **完整 SSH 登录成功**，随即自动执行 `check → build → p0 → p1 → p2 → restore`，**六个阶段全部 rc=0**，`FINISHED OK`。设备原生编译 `fastrpc_pdscan` 成功（aarch64 ELF，仅一条 kernel-UAPI 头警告）。

### 15.2 结果矩阵（原始探针，单进程单 create ioctl，`GET_DSP_INFO` 全部 rc=0）

| 条件 | P0：daemon 运行 | P1：daemon 停止 | P2：daemon 停止 |
|---|---|---|---|
| `cdsp` noattach attrs=0x8 (RMID7) | `0x80000453` EBADASID | **`0x80000580` AEE_DEFAULT_PROCESS** | — |
| `cdsp` noattach attrs=0x0 (RMID6) | `0x80000453` | **`0x80000580`** | — |
| `cdsp` attach attrs=0x8 | `INIT_ATTACH rc=0` → `0x8000041a` EALREADY | `INIT_ATTACH rc=0` → `0x8000041a` | — |
| `cdsp` attach attrs=0x0 | — | — | `0x8000041a` |
| `cdsp-secure` noattach 0x8 / 0x0 | `0x80000453` | **`0x80000580`** | `0x80000580`（0x0） |
| `cdsp-secure` attach 0x8 / 0x0 | `0x8000041a` | `0x8000041a` | `0x8000041a` |

`0x80000580` = `AEE_EOFFSET(0x80000400)+0x180` = **`AEE_DEFAULT_PROCESS` — "Default process in Guest OS is not present"**（`tmp/boot_probe/fastrpc-pr319/inc/AEEStdErr.h:290`）。

**同时再次证伪**：secure ↔ 非 secure 节点无差异；attrs `0x0`(RMID6) 与 `0x8`(RMID7) 无差异；`GET_DSP_INFO` / `INIT_ATTACH` 始终 rc=0。

### 15.3 判别结论

1. **§14.3 里"抑制 nr=10 与 INIT_CREATE 无因果链"这个强断言需要修正**：停掉整个 `cdsprpcd` 后错误码确实变了 → daemon（root-PD / Guest OS default process 的宿主）状态**确实影响** `INIT_CREATE` 的返回。但注意变化的是「移除整个 daemon」，不是「只去掉 nr=10」；原先那条"只抑制 nr=10 无区分力"的判断仍然成立。
2. **变化方向决定结论**：`AEE_DEFAULT_PROCESS`（Guest OS 默认进程不存在）是比 `AEE_EBADASID`（ASID 分配失败）**更早的前置条件失败**。daemon 在时该前置条件已满足、错误推进到 ASID 阶段；daemon 不在时退回更早阶段。
   → **H_A「root-PD 不完整导致 `INIT_CREATE` 失败」被证伪**；**H_B「2020-12 固件侧无法创建 user PD / 分配 ASID」得到支持**。
3. 带 `INIT_ATTACH` 时恒为 `AEE_EALREADY`（与 daemon 状态、节点、attrs 都无关）：DSP 认为该 session 已 attach / PD 已存在，再 create 被拒 —— 与"PD 创建能力缺失"的画面一致，而不是"root-PD 没准备好"。
4. daemon 日志里 `adsp_default_listener` handle **打开成功**、`fastrpc_shell_unsigned_3` / `fastrpc_shell_3` 打开成功，同时 `mod_table` / `adspmsgd` / `remotectl1` 等新 RPC 失败 → root-PD 的**基本监听能力在**，缺的是固件侧新 PD 创建路径。
5. **对 K5 的直接含义**：内核既不能替 DSP 创建 default process，也不能替它分配 ASID。`fastrpc.c` 没有可修的补丁目标；刷官方内核（K6）只会得到"同样失败、但 fastrpc 变成 `.ko`"的状态。**K6/K7 的性价比大幅下降**。（语义复核已派子代理，结论以复核后为准。）

### 15.4 基线与回滚（restore 后完全干净）

| 项 | 值 |
|---|---|
| `host_main` | `rc=-2147482541` = `0x80000453`（与 P0 前一致） |
| `fastrpc_test -d 3 -U 1` | `Passed: 0 / Failed: 3`，全部 `0x80000453` |
| `cdsprpcd` | `active`（P1 时 `inactive`） |
| remoteproc0 | `running`；`/dev/fastrpc-cdsp[-secure]` 在位 |
| 库 sha256 | `89d89378…` / `9e05b2e2…`（原始版，未替换） |
| drop-in | 只有原有 `10-searchpath.conf`，**无任何实验残留** |

### 15.5 logind 取证（V42 仍为未确证）

`forensics.txt`：`--list-boots` 显示 boot `-1` = `11-06 08:48:30 → 09:11:23`，boot `0` = `11-06 18:48:30`。上一 boot 的 logind/ssh 日志只有正常启动、`08:48:50` 一个连接关闭、**`09:11:22` 最后一次 root 密码登录成功**（`pam_unix(sshd:session): session opened` + `New session 3 of user root`），随后 journal 静默；**没有** `pam_systemd` / `Failed to create session` / `Maximum number of sessions` / D-Bus 超时 / hung task。当前 logind：`PID=567`、`WCHAN=do_epoll_wait`（正常事件循环）、`FD_COUNT=38`、`STATE=Ss`、2 个 session、无 hung task。

→ V42「23MB SFTP → logind 资源饱和」**既未证实也未证伪**：没有饱和的直接错误日志、fd 数正常；但「最后一次成功登录后 journal 静默 9.5 小时」与"全局卡死"方向一致。物理重启后完全恢复，与 §14.2 的 PAM/logind 定性一致。（`--since/--until` 的 11-06 窗口查询返回 `-- No entries --`，与 `-b -1` 有条目矛盾，属时区/过滤问题，不据此推断。）

### 15.6 验证项与计划标记更新

| ID | 项 | 状态 |
|---|---|---|
| V37 | 停掉 cdsprpcd 后 `INIT_CREATE` 错误码变化 | ✅ **变化**（`0x80000453 → 0x80000580`），但方向为退回更早前置条件 |
| V38 | RMID6 / RMID7 两种 PD 创建形态都失败 | ✅ 在 P0/P1/P2 的三个矩阵中完全一致 |
| V43 | H_A「root-PD 不完整导致失败」 | ❌ **证伪**（daemon 在时前置条件已满足） |
| V44 | H_B「固件侧 user PD / ASID 创建能力缺失」 | ✅ **得到支持**（待子代理语义复核） |
| V45 | secure / 非 secure 节点影响结果 | ❌ 无差异（再次证伪） |
| V46 | `cdsprpcd` 可干净停止/恢复且基线可复现 | ✅ restore 后所有指标回到 P0 前 |
| V42 | logind 资源饱和触发链 | ⏳ 仍未确证（见 §15.5） |

- [x] **K5-pre** P0–P2 零刷机 PD 协议实验 — ✅ 已完成，判别见 §15.3
- [ ] **K5** 确定 `fastrpc.c` 的具体补丁内容 — ❌ **结论：无可修的内核补丁目标**；C1/C2/C3 候选均不再具备性价比
- [ ] **K6** 刷官方内核 — ⏸ **建议暂缓**（无补丁可验证，且属高风险动作）
- [ ] **K7** 单独重编 `fastrpc.ko` 验证 D8 — ⏸ 随 K6 暂缓
- [x] **K8** 换整套 2021-07-30 配套固件 — ✅ **2026-11-06 完成**，PAS 验签通过、D8 达成，见 §17.6
- [🔄] **K9** 上游报告 — 已由「负结果反馈」改写为**正结果 + 版本配套 A/B 实证**；主报告 `tmp/firmware/upstream-report.txt`，投递目标清单 `tmp/firmware/upstream-targets.md`。**尚未发送**，对外提交需用户确认
- [x] **新候选 P3** `INIT_CREATE_STATIC`（nr=9 / RMID8）— ✅ **取消**：K8 成功后已无必要，且该 RMID 有 cDSP 挂死风险，不要执行
- [ ] **清理项**（`/data2` ext4、Makefile 旧 SDK 路径、hvx_add_imp.c 向量化）可随时推进

### 15.7 结果文件

`logs/pdscan/` 下：`matrix-p0-daemon-on.txt`、`matrix-p1-daemon-off.txt`、`matrix-p2-extra.txt`、`host-main-{p0,restored}.txt`、`fastrpc-test-{p0,restored}.txt`、`state-{check,p0,p1,p2,restored}.txt`、`logs-{p0,p1,p2,restored}.txt`、`forensics.txt`、`unit.txt`、`auto-*.log`、`auto-summary.txt`。

---

## §16 换固件路线复活（2026-11-06 溯源取证，改写入手点排序）

> 本节**修正 §12 路线 3/4、§13.1 结论 4**，并把上一轮「D8 在当前固件下接近物理天花板」的判断改写为「仍有唯一未排除的变量可试」。

### 16.1 决定性新发现：存在更新的、同机型、完整配套的 SM8150 CDSP 固件

来源 `XiaomiFirmwareUpdater/firmware_xiaomi_raphael`（资产仓 `XiaomiFirmwareUpdaterReleases/firmware_xiaomi_raphael`）。对两个 MIUI 包做**内存解包 + 字节级核验**：

| 来源 | CDSP build id | `fastrpc_shell_3` | `fastrpc_shell_unsigned_3` |
|---|---|---|---|
| 设备 / `firmware-xiaomi-raphael 1.3`（§13.3） | `...357350.2_20201211_224311` | 938172 B | **933772 B** |
| `weekly-26.11.2021`（China Beta 21.11.24） | `...357350.2_20201211_224311` | 938172 B | 933772 B |
| `stable-09.11.2021`（**China Stable** V12.5.6.0.RFKCNXM） | **`...357350.2.419065.1_20210730_070147`** | **939664 B** | **935256 B** |

取证方式：`firmware-update/` 内 `NON-HLOS.bin`(200,929,280 B，含 CDSP PIL 固件) 与 `dspso.bin`(67,108,864 B，**ext4 镜像 magic 0xef53**，含整棵 `/usr/lib/dsp/cdsp/`)，shell 大小由 ext4 inode 51/52 的 `i_size_lo` 读出；新 shell 内嵌 `.../fastrpc_shell_unsigned_img/qdsp6/855.cdsp.prod/...` 与 `CDSP.HT.2.0.1-419065-SM8150-1_LIB*_SKEL`。

**推论**：`weekly` 与设备逐字节同版 → 设备固件来自 **China Beta 分支**；**China Stable 分支拿到了晚 7 个月的新 build**。两个分支的 CDSP 并不相同。

### 16.2 风险评估改写（原 §12:366 按「刷分区」估高了）

mainline `qcom_q6v5_pas` 从 `/lib/firmware/qcom/...` 加载 `cdsp.mbn`、shell 从 `/usr/lib/dsp/cdsp/` 加载（§11.1、§13.3）。因此「换固件」是**替换 Linux 根文件系统里的文件 + `systemctl reboot`**，不是 fastboot 刷 `NON-HLOS.bin`/`dspso.bin` 分区：不触碰 PBL/XBL/分区表，Secure Boot 已禁，保留 rEFInd 旧启动项与 `.bak` 即可回滚。签名走 TZ/SCM 验签，用的是同机型 raphael 小米官方签名固件（Ubuntu Purwa 案例中跨机型 EVK 固件被 PAS 拒 `-22` 是反例）。**变砖风险远低于原评级**，但 China Stable ↔ Beta 分支的签名链兼容性仍需设备侧验证。

### 16.3 老用户态栈（路线 4）前提被证伪 —— 且换它也没用

【事实】AOSP `platform/external/fastrpc` commit `3704a6f17fb3`（2019-11-15，BSD-3-Clause）的 `inc/fastrpc_internal.h`：ioctl 只有 nr 1–7，编号与 v7.0 UAPI 一一对应，**无 8/9/10/11/13（无 MEM_MAP、无 GET_DSP_INFO）**；`struct fastrpc_init_create` 与 v7.0 逐字段相同；`src/fastrpc_apps_user.c` 实际节点宏是 `/dev/fastrpc-cdsp`（同 mainline），`src/rpcmem_android.c` 用 `ALLOC_DMA_BUFF` 而非 ION。**唯一语义漂移**：`struct fastrpc_invoke_args` 第 4 字段 AOSP 为 `reserved`、v7.0 为 `attr`（尺寸相同，影响 INVOKE 不影响 INIT_CREATE）。→ §12:367「面向 `/dev/adsprpc-smd` + ION、不兼容」需按此修正：那只描述下游 BSP 变体。

【决定性反证】发给 DSP 的 `RMID_INIT_CREATE(6)` / `RMID_INIT_CREATE_ATTR(7)` 消息由**内核** `fastrpc_init_create_process()` 构造（§14.4、§15.3），用户态只提供 `struct fastrpc_init_create`。**换任何用户态库，DSP 看到的 PD 创建请求都不变。**老栈唯一收益是天然不发 nr=10，而该路径已证与 INIT_CREATE 无因果链（§15.3）。→ 路线 4 明确降级，只可留作「用户态代际无关」的低成本副线实证。

### 16.4 公开成功案例的一致指向

| 案例 | 关键动作 | 结果 |
|---|---|---|
| Ubuntu Concept 26.10 / Purwa (x1e80100) | 从**同机型** Windows 驱动包取 `qccdsp8380.mbn` + 对应 shell，目标机编译 `libcdsprpc v1.0.8` | `fastrpc_test` 通过；原文：**"ASIC mismatch is the classic trap: Hamoa EVK shells on Purwa firmware → crash 0x8000054F (BADASID)"** |
| Radxa Dragon Q6A (QCS6490) | 官方镜像 `cdsp.mbn` 无配套 shell → `0x80000600`；换 linux-msm 严格配套的 QCM6490 固件 + shell | `fastrpc_test` 通过 |
| Radxa 31391 | 帖中结论：「**all three version strings — firmware, shell, and skel libs — need to be identical**」 | 与本项目 §15.3 H_B 同向 |

Debian WNPP #1101838 引 Dmitry Baryshkov：「the libraries / shell must match exactly the DSP firmware that they have been built with / for」；`qualcomm/fastrpc#325` 里 maintainer 首要追问 shell/固件来源与库版本。**所有公开成功案例都靠换配套固件/shell，无一例靠降级用户态**；未找到「老用户态 + 新 mainline 内核」或「降级用户态修好新用户态+老固件」的案例。

### 16.5 改写入手点排序（⚠️ 历史快照，已由 §17.6 收敛）

> 本节写于 K8 执行前，**仅保留作决策追溯**。最终结论：① 已执行成功（D8 达成），
> ③–⑥ 全部取消，② 已由「负结果反馈」改写为正结果报告。另外本节的
> 「`cdsp.mbn` 单文件」表述**已被设备实测证伪**：设备是 split 形态
> `cdsp.mdt`+`cdsp.b00..b10`，见 §17.2。当前有效动作见 §18。

| 序 | 入手点 | 判断 |
|---|---|---|
| **①** | **换整套 2021-07-30 配套固件**（split PIL + 两个 shell + skel/mod_table 全同 build） | ✅ **已执行并成功**，见 §17.6。当时判断「首选、唯一针对固件能力/配套变量、文件级可回滚」被证实；「成功概率中等偏低」的估计偏保守 |
| **②** | 上游反馈（原计划 `qualcomm/fastrpc#325`、LKML linux-arm-msm、`linux-msm/dsp-binaries` 请求 SM8150 配套集） | ✅ 目标已重新核实：#325 主题不符，主投递点改为 **`qualcomm/fastrpc#400`**；报告改为**正结果 + 版本配套 A/B 实证**，见 §18 |
| ③ | `INIT_CREATE_STATIC`（nr=9 / RMID8）最小探针 | 仅剩的未试协议分支、成本极低；但固件从未见过该 RMID，有 glink 挂死风险，需用户确认，价值主要在把结论钉死 |
| ④ | 老用户态栈整体对齐（路线 4） | **降级**：ABI 兼容但改不了内核构造的 INIT_CREATE；仅作副线实证 |
| ⑤ | 刷官方内核取 `fastrpc.ko`（K6/K7） | **不建议**：§15.3 已判 `fastrpc.c` 无可修补丁目标 |
| ⑥ | 接受 D8 受阻转其它目标 | ① 失败后的兜底 |

**前置检查（决定 ① 能否走）**：~~能否从 `NON-HLOS.bin` 按设备现有 `cdsp.mbn` 3.4MB / `cdsp.mdt`+`cdsp.bXX` 形态可靠提取 PIL 镜像~~ → ✅ **已通过**（§16.8：`CDSP.MDT` + `B00..B10` 原样提取，按 MDT 自身 `p_offset` 重建为 3,405,460 B 单文件；前 436 B 与 12 个 phdr 与基准逐字节一致）。**剩余判定点只剩设备侧 PAS 验签**：若 `qcom_scm_pas_auth_and_reset` 返回 `-22`，此路即止并走 rEFInd 回滚。

### 16.6 新增验证项与计划标记

| ID | 项 | 状态 |
|---|---|---|
| V47 | 存在晚于 2020-12 的同机型 SM8150 CDSP 固件 | ✅ **确证**（2021-07-30 build，字节级核验） |
| V48 | 设备固件来自 China Beta 分支 | ✅ 强支持（`weekly-26.11.2021` 与设备逐字节同版） |
| V49 | AOSP 2019 用户态与 v7.0 UAPI 的 ABI 兼容性 | ✅ **兼容**（nr1–7、`/dev/fastrpc-cdsp`、`ALLOC_DMA_BUFF`；仅 INVOKE args 语义漂移） |
| V50 | 整套 2021-07-30 固件可离线提取且形态与设备匹配 | ✅ **通过**（21 个 DSP 文件 + 12 个 PIL 文件，`cdsp.mbn` 重建结构与基准 100% 对齐） |
| V51 | 新版固件能改变 `INIT_CREATE` 的 `AEE_EBADASID` | ⏸ 待设备侧实测（需用户确认） |
| V52 | 设备侧 DSP 库真实加载路径 | ✅ **`/usr/share/qcom/dsp/cdsp/`**（`logs/pdscan/unit.txt:23-24` 的 `ADSP_LIBRARY_PATH` + `logs-p0.txt:45` 打开 shell 成功），部署只写这一处 |
| V53 | 新套 firmware / shell / skel 版本串一致 | ✅ 三者内嵌均为 `...419065.1_20210730_070147`；旧套三者均为 `...357350.2_20201211_224311` |
| V54 | 新旧 `cdsp.mbn` 是否同一文件 | ❌ 不是：同 3,405,460 B、85.936% 字节相同、478,936 B 不同，属同一代码基线的增量新构建 |

- [x] **K8** 主机侧离线提取 + 基准比对 + 部署预案 — ✅ 完成（§16.8）
- [ ] **K8b** 设备侧整套替换 + `systemctl reboot` + 回滚验证 — ⏸ **需用户确认**；设备零改动
- [x] **K9** 上游负结果反馈草稿 — ✅ `tmp/firmware/upstream-report.txt`（**未发送**，外部动作需用户确认）

### 16.7 证据 URL

- https://github.com/XiaomiFirmwareUpdater/firmware_xiaomi_raphael 、 https://github.com/XiaomiFirmwareUpdater/mi-firmware-updater
- https://github.com/qualcomm/fastrpc/issues/325 、 https://lists.debian.org/debian-wnpp/2025/04/msg00024.html
- https://discourse.ubuntu.com/t/ubuntu-concept-26-10-snapdragon-edition/88518/77
- https://forum.radxa.com/t/non-functional-npu-support-on-dragon-q6a-qcs6490-under-ubuntu-24-04-noble/30699
- https://forum.radxa.com/t/cdsp-fastrpc-session-still-fails-0x80000600-remotectl1-domains-not-supported-after-fixing-the-missing-memory-region-r2-ubuntu-24-04-kernel-7-0-11-5/31391
- https://android.googlesource.com/platform/external/fastrpc/+/3704a6f17fb363358c6973a7082b683ca8c0eb63/
- https://raw.githubusercontent.com/torvalds/linux/v7.0/include/uapi/misc/fastrpc.h
- https://raw.githubusercontent.com/linux-msm/dsp-binaries/master/config.txt

### 16.8 K8 离线提取结果（2026-11-06 20:1x，主机侧完成，设备零改动）

【产出】`tmp/firmware/`

| 目录 | 内容 |
|---|---|
| `_download/` | 原 zip 104,349,078 B、`NON-HLOS.bin` 200,929,280 B（**FAT16**）、`dspso.bin` 67,108,864 B（**ext4**） |
| `baseline-v1.3/` | 官方 deb 流式解包（906 条目），含旧 `cdsp.mbn` 3,405,460 B、两个旧 shell、`cdspr.jsn` |
| `raphael-20210730/dsp/cdsp/` | **21 个文件**：两个新 shell、全部 `lib*_skel.so`、`libc++.so.1`、`libc++abi.so.1`、`libvpp_*.so`、`ubwcdma_dynlib.so`、映射表 |
| `raphael-20210730/pil/` | `CDSP.MDT` + `CDSP.B00..B10`（9 段，B07/B09/B11 的 `filesz=0` 故缺属正常）+ `CDSPR.JSN` + **重建 `cdsp.mbn`** |
| `raphael-20210730/manifest.json` | 35 个产出，逐项路径 / 大小 / sha256 / 镜像内来源，独立重算 0 不符 |
| `baseline-compare.txt` / `deploy-plan.txt` | 新旧对照 / 部署回滚预案 |
| `_scripts/` | 6 个自写纯 Python 解析器（ar+zstd、ELF/phdr、FAT16、ext4 extent tree、PIL 重建、交付物生成） |

**`cdsp.mbn` 重建（关键前置检查已通过）**：`NON-HLOS.bin` 里没有现成单文件 mbn，CDSP 以 Qualcomm split 形态 `CDSP.MDT` + `B00..B10` 存在。按 MDT 自身 ELF32 / Hexagon(`e_machine=0xa4`) / 12 个 program header 的 `p_offset` 把各段**原样**写入、段间补 0，得到 3,405,460 B 单文件。校验：`MDT` 前 436 B 与基准**逐字节相同**、12 个 phdr 的 `type/p_offset/p_filesz/flags` 逐段一致、各 `Bxx` 长度 == `phdr.filesz`、基准段间 padding 抽样全 0。新旧 **85.936% 字节相同 / 478,936 B 不同** → 同一代码基线的增量新构建，非拼凑。原始分段也完整保留，不信任重建可改走 split 形态。

**版本串一致性（Radxa / Ubuntu 的硬要求，已实测满足）**：新套 `cdsp.mbn` / `fastrpc_shell_3` / `fastrpc_shell_unsigned_3` 内嵌均为 `QC_IMAGE_VERSION_STRING=CDSP.HT.2.0.1-00171-SM8150-1.357350.2.419065.1`、`..._20210730_070147`、`QCOM time Fri_Jul_30_07:09:27_PST_2021`；旧套三者均为 `...357350.2_20201211_224311`。21 项对照 **18 项更新、3 项完全相同**（`libc++.so.1`、`libc++abi.so.1`、`map_SHARED_LIBS_855.cdsp.prodQ.txt`）；`cdspr.jsn` 新旧逐字节相同。

**路径分歧已解决（V52）**：提取任务原把「设备 DSP 库真实路径」列为唯一待确认项。本机 `logs/pdscan/unit.txt:23-24`（`systemctl cat cdsprpcd.service` 输出）明确：

```text
Environment="ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx"
Environment="DSP_LIBRARY_PATH=/usr/lib/rfsa/adsp;/usr/share/qcom/dsp/cdsp;/data/local/tmp/hvx"
```

`logs/pdscan/logs-p0.txt:26` 的 `file_watcher_thread` 报出同一搜索路径、`:45` 的 `apps_std_imp.c:1076: Successfully opened file fastrpc_shell_unsigned_3` 印证 shell 命中；基准 deb 也把 shell 装在 `usr/share/qcom/dsp/cdsp/`。→ **部署只写 `/usr/share/qcom/dsp/cdsp/`**，绝不写 `/usr/lib/dsp/cdsp/`。已回写 `deploy-plan.txt`【1】B 段。Ubuntu usrmerge 下 `/lib` 是 `/usr/lib` 符号链接，A 段路径同样自洽。

**剩余风险（部署前须知）**：① TZ/SCM 可能对 PIL 有 anti-rollback 或签名绑定，官方原样字节也可能被 PAS 拒 `-22`；判定点 `dmesg | grep -iE 'cdsp|pas|mdt|remoteproc|firmware|auth|scm'`、`/sys/class/remoteproc/*/state`、`/dev/fastrpc-cdsp`。② 若 cdsp 正常起来但 `INIT_CREATE` 仍 `AEE_EBADASID`，则「固件版本过旧」不是唯一原因，应回到其它假设，**不要继续盲目换固件**。③ 部署前先只读确认设备上 shell 的 sha256 == `1d03f6ca…`（旧版基准），不等则先查清副本来源。

~~**部署动作尚未执行**~~ → 该状态已于 2026-11-06 21:4x 被 §17 改写：设备侧只读核查与整套替换均已执行。

---

## §17 设备侧只读核查与 2021-07-30 固件整套替换（2026-11-06 21:2x–21:4x）

> 用户选择「先做只读核查，通过后自动部署」。本节记录核查结果、对 §16 预案的修正、
> 以及部署执行情况。**所有结论均为设备实测，非推断。**
> 证据：`logs/firmware/readonly-audit.txt`、`readonly-audit2.txt`、`readonly-boot.txt`、
> `readonly-esp.txt`；脚本 `tmp/boot_probe/verify_firmware_readonly*.py`、
> `verify_boot_entries.py`、`verify_esp_readonly.py`、`pack_firmware.py`、`deploy_firmware.py`。

### 17.1 三处预案错误被实测证伪（v2 预案已回写 `deploy-plan.txt`）

| # | v1 预案假设 | 设备实测 | 修正 |
|---|---|---|---|
| 1 | PIL 是单个 `cdsp.mbn` 3.4 MB | **split 形态**：`cdsp.mdt` 7580 B + `cdsp.b00/01/02/03/04/05/06/08/10` + `cdspr.jsn`；目录里**没有 mbn**。内核 `Booting fw image .../cdsp.mdt, size 7580`；DT `firmware-name=qcom/sm8150/Xiaomi/raphael/cdsp.mdt` | 按小写 split 名替换 10 个文件，**不放 cdsp.mbn** |
| 2 | 基准 deb = 设备当前同版 | 仅**用户态**成立：`/usr/share/qcom/dsp/cdsp/` 21 个文件 sha256 与基准 deb 逐字节一致；**PIL 不是同一套**（见 17.2） | 基准比对结论限定在 shell/skel；PIL 需单独取证 |
| 3 | 替换前在 rEFInd 保留/新增回滚启动项 | ESP=`/dev/sda30`（LABEL=`efi`，1G vfat，**未挂载**）只有 `BOOTAA64.EFI` + 默认样例 `refind.conf`(36,644 B，menuentry 全是注释) + 驱动/vars；**没有任何 vmlinuz / initrd / dtb / 第二内核**。`efibootmgr -v` 只有 6 个 `scsi N` auto 项 | 改**文件级回滚**：备份 + tar.gz + `SHA256SUMS` + `/root/cdsp-rollback.sh`；cdsp PAS 失败不阻止 multi-user.target，SSH 回滚路径始终可达 |

其它实测：SecureBoot efivar = `0`（关闭）、SetupMode=`1`；`/lib -> usr/lib`；`/usr/lib/dsp/cdsp/` 不存在；
`/usr/lib/rfsa/adsp/` 下 21 项全是符号链接指向 `/usr/share/qcom/dsp/cdsp/`（**只写后者即可**）；
`/usr/share/qcom/dsp/cdsp/libhvx_add_skel.so`（自编 7160 B）不在替换清单内，必须保留；
`cdsprpcd` active、`remoteproc0=cdsp running`、`/dev/fastrpc-cdsp[-secure]` 在位；`/` 剩余 436 G。

### 17.2 决定性新发现：设备当前 PIL 与 shell **本就不配套**

下载设备 `cdsp.mdt` / `cdsp.b00` 并解析 ELF32(Hexagon) 的 12 个 program header：

| 项 | 设备当前（内存里正跑的） | 基准 deb `cdsp.mbn` | 2021-07-30 `CDSP.MDT` / 重建 mbn |
|---|---|---|---|
| 前 436 B sha256 | `b33f71db…` | `e569f87d…` | `e569f87d…` |
| `phdr[2] filesz` (b02) | 227,348 | 228,148 | 228,148 |
| `phdr[5] filesz` (b05) | 2,710,852 | 2,735,588 | 2,735,588 |
| 末段 `p_offset` | 0x33a000 | 0x340000 | 0x340000 |
| `QC_IMAGE_VERSION_STRING` | `CDSP.HT.2.0.1-**00131**-SM8150-1` | `…**00171**-SM8150-1.357350.2` | `…**00171**-SM8150-1.357350.2.419065.1` |
| 用户态 shell build id | `357350.2_20201211_224311` | 同左 | `419065.1_20210730_070147` |

设备 9 个非零 `phdr.filesz` 与 9 个 `cdsp.bXX` 实际大小逐项相等（split 自洽）。
→ **设备是「较老的 00131 分支 PIL + 2020-12 的 00171 分支 shell/skel」的不配套组合。**
这正好落在 §16.4 引用的 Radxa / Dmitry Baryshkov「libraries / shell must match exactly the DSP firmware」
所指的失败模式上。换 2021-07-30 整套（PIL 00171 + shell/skel `419065.1` 同 build）
同时消掉「不配套」与「固件过老」两个变量，**换固件路线的理由比 §16 原始判断更强**。

### 17.3 部署执行记录（分阶段，每阶段可独立刹车）

| 阶段 | 结果 | 设备改动 |
|---|---|---|
| 主机侧重打包 | `deploy-bundle.tar.gz` 6,062,495 B，sha256 `a3f1d879…`；32 文件（pil 11 + dsp 21）；新 MDT 的 9 个 `filesz` 与 9 个 Bxx 长度逐项断言通过 | 无 |
| `upload` | 6×1 MB 分片、每片独立校验；合并后整体 sha256 一致；解包后 `sha256sum -c want.sha` **32/32 OK** | 仅新增 `/root/cdsp-20210730-staging/` |
| `backup` | `/root/cdsp-firmware-backup-20201211-pre-20210730/`（pil 11 + dsp 21 + `SHA256SUMS` + README）、同名 `.tar.gz` 6,063,953 B、`/root/cdsp-rollback.sh` | 仅新增备份 |
| `precheck` | cmdline 仍是 stage2 DTB、`remoteproc running`、daemon active、SecureBoot=0、备份齐全 | 无 |
| `replace` | 32 个文件一次到位，`libhvx_add_skel.so` sha256 未变、rfsa 符号链接未动 | **已替换根文件系统中的固件文件** |
| `verify` | 32/32 sha256 与 `deploy-manifest.txt` 一致 | 无 |
| `reboot` / 验收 | 见 §17.4 | — |

⚠️ 环境坑复现与规避：USB-NCM 上 23 MB 单文件 SFTP 曾耗尽 sshd 会话（§13），
本次用 **6×1 MB 分片 + 逐片 sha256** 规避；设备 locale 为中文，
`sha256sum -c` 输出「成功」而非「OK」，校验脚本必须加 `LC_ALL=C`。

### 17.4 中间状态记录（21:40–22:31，SSH 会话层不可用）

> ⚠️ **本节是过程记录，不是最终结论**。设备于 22:31 物理重启后已全部验收通过，
> 最终结果与 D8 达成见 **§17.6**。以下诊断保留供追溯（尤其「SSH 会话层卡住」
> 与 PAS 验签无关的判别方法）。

**当时判定：验收尚未完成，V51 未决。** 现状与判定：

| 探测 | 结果 | 含义 |
|---|---|---|
| `ping 172.16.42.1` | 通，TTL=64，1–4 ms | 链路层/内核网络栈活着 |
| ARP | `d6-02-83-44-b6-45` 动态 | 设备真实应答，非缓存假象 |
| TCP 22 | SYN-ACK，但**读不到 SSH banner** | sshd socket 在监听，会话处理卡住 |
| TCP 80 / 12345 / 5355 | `ConnectionRefused`(RST) | 设备本身回 RST → **排除 MihomoTun 代理吞流量** |
| `route print` / `usb-ncm-up.ps1` | `172.16.42.0/24 -> 172.16.42.2 IF 82 metric 26`，NAT 直连正确 | Windows 侧无问题 |
| `adb devices` | 空 | USB 上未暴露 adbd |
| 后台守护 `wait_and_verify.py` | 120 次探测 / 约 36 min 全部 banner 超时，21:42→22:18 以 `TIMEOUT` 正常退出 | 非「启动慢」可解释 |

守护退出后另起了 `tmp/boot_probe/watch_postboot.py`（低噪音、约 2 h 上限、追加写同一日志），
一旦 SSH 回来会自动跑完整验收，并先用 sha256 判定当前是「2021-07 新固件在位」还是
「已回滚到 2020 基线」，避免把回滚后的状态误判成实验结果。日志：
`logs/firmware/postboot-verify.txt`（首轮 TIMEOUT 记录保留）。

【事实】设备没有进入「内核完全挂死」状态（否则不会回 ICMP/RST/TCP SYN-ACK），
也没有停在 rEFInd 菜单（Linux 已起）。【推测】最可能是历史上出现过的
`sshd → do_pam_session() → pam_systemd.so → logind D-Bus CreateSession` 卡死
再次发生；也可能与新 cDSP 固件加载后某个启动期依赖间接相关。
**在能读到 `dmesg` 之前，不能把此现象判定为 PAS 验签失败，也不能判定为固件成功。**

⚠️ 这与 v2 预案【6】预估的「PAS 失败只返回 -22、Ubuntu 照常进 multi-user」不一致：
实测出现的是**会话层不可用**，说明"文件级回滚路径始终可达"这一前提需要打个折扣，
必须保留 TWRP / rEFInd 黑名单项作为兜底（见 17.5）。

### 17.5 应急回滚（三条路径，按成本从低到高）

1. **物理重启一次**（长按电源键 10–15 s → 再次开机）。历史上 logind 卡死正是靠物理重启恢复的。
   若 SSH 恢复但尚未确定固件效果，先跑 `python3 tmp/boot_probe/deploy_firmware.py early`
   读 dmesg / remoteproc / build id，再决定是否回滚。
2. **rEFInd 菜单选带 `modprobe.blacklist=qcom_q6v5_pas,...` 的项**。
   ⚠️ 三项里只有 **`Boot stage1 (usb-net only)`**（`tmp/boot_probe/refind_linux.conf.converged:38`）
   同时满足「带六项黑名单」+「**没有** `systemd.mask=usb-ncm.service`」→ 可绕开 cdsp PAS 且保留 SSH。
   `Boot DIAG (no net, pre-converge)`（`:40`）虽带黑名单但 mask 了 usb-ncm（无网络）；
   `Boot ORIGINAL (pre-diag)`（`:39`）**根本没有黑名单**，不能当回滚项。
   注意 `EFI/BOOT/refind.conf` 是 `timeout -1`，默认立即启动第一项，需在开机瞬间按键才能看到菜单；
   若来不及，用路径 3 的 `twrp_add_rollback_entry.sh` 把黑名单项**改成第一项**（会备份原 conf）。
   进系统后：`bash /root/cdsp-rollback.sh && systemctl reboot`（绝不 kexec）。
3. **进 TWRP 的两个脚本（按需要选）**：
   · `tmp/boot_probe/twrp_add_rollback_entry.sh` — 把带黑名单的
     `"Boot ROLLBACK (no DSP / restore files)"` 置为 refind_linux.conf 第一项，
     备份为 `refind_linux.conf.pre-fw-rollback`；用于「开机根本看不到菜单/进不了系统」。
   · `tmp/boot_probe/twrp_rollback.sh` — 直接做文件级恢复：挂载 `/dev/block/sda31`
     → 解 `/root/cdsp-firmware-backup-20201211-pre-20210730.tar.gz`
     → 覆盖 `usr/lib/firmware/.../cdsp.mdt+bXX` 与 `usr/share/qcom/dsp/cdsp/` 21 个文件
     → `sync` → 卸载 → 重启。该脚本保留自编 `libhvx_add_skel.so`。
   两脚本均需 TWRP 下 adb 可用；分区编号须现场核对（运行系统 `boot -> sde49`，
   旧 TWRP 脚本用 `sde53`，ESP 是 `sda30`）。

**回滚后基线**（sha256，可核对）：`cdsp.mdt=c87b5fa0…`、
`cdsp.b02=a0aaa879…`、`cdsp.b05=85086ea8…`、
`fastrpc_shell_unsigned_3=1d03f6ca…`（2020-12 build）。

---

## §17.6 最终验收结果与 D8 达成（2026-11-06 22:31–22:34）

> 22:31 设备物理重启后恢复，`tmp/boot_probe/watch_postboot.py` 自动跑完完整验收，
> 日志 `logs/firmware/postboot-verify.txt`。**§17.5 的回滚预案保留为资料，当前不需要执行。**

### ① PAS 验签通过、新固件生效（V51 ✅ 确证）

- 内核日志：`Booting fw image qcom/sm8150/Xiaomi/raphael/cdsp.mdt, size 7580`
  → `remote processor cdsp is now up`；**无** `-22` / `authentication` / `rollback` /
  `failed to load`。China Stable 2021-07 固件在这台 China Beta 设备上验签通过，
  anti-rollback 未触发。§16 的剩余风险项至此排除。
- 守望判定 `NEW 2021-07-30 FIRMWARE IN PLACE`：`cdsp.mdt=4b82459c…`、
  `cdsp.b02=a14316ec…`、`cdsp.b05=85e67884…`、
  `fastrpc_shell_unsigned_3=f94a2062…`；build id `419065.1_20210730_070147`，
  PIL `CDSP.HT.2.0.1-00171-SM8150-1.357350.2.419065.1`。
- `remoteproc0=running`、`/dev/fastrpc-cdsp[-secure]` 在位、`cdsprpcd` active。

### ② Unsigned PD / FastRPC 调用链打通

- `fastrpc_test -d 3 -U 1`：**3/3 PASS**（`libmultithreading_skel.so`、
  `libhap_example_skel.so`、`libcalculator_skel.so`）；`calculator_sum` 在 domain 3
  真的算出 `Sum = 499500`、`Max = 999`。
- 日志明确 `Created user PD on domain 3 ... Unsigned:Y`，旧固件下的
  `0x80000453 AEE_EBADASID` **不再出现** → H_B「固件侧无法创建 user PD / 分配 ASID」
  随整套换固件解决，无需动内核或 `fastrpc.ko`。
- 无害噪声仍在：`remotectl1 domains not supported`（`0x4e`）、
  `fastrpc_mmap APIs are not supported on this target`、`mem mmap error` /
  `0x80000414 AEE_EUNSUPPORTED`、`.farf` 文件缺失 —— 均不影响调用。

### ③ 最后一环：自编 skel 的 URI 格式

- 首次 `host_main` 仍失败 `rc=-2147482618 = 0x80000406`，但**性质已完全改变**。
  journal 给出明确原因：

  ```text
  Error 0x80000406: remote_handle_open_domain: dynamic loading failed for
  file:///data/local/tmp/hvx/libhvx_add_skel.so?hvx_add_skel_handle_invoke&_modver=1.0&_dom=cdsp
  (dlerror: Absolute path or ./obj_name required for shared object data/local/t...)
  ```

  即新固件的 DSP 侧 dlopen 把 `file:///` 后的绝对路径剥掉首个 `/` 变成相对路径并拒绝。
  ⚠️ 与 V19 里旧固件下 PD 未建起来导致的 `0x80000406` 是**不同根因**，勿混淆。
- 成功的 `fastrpc_test` 用的是**裸文件名** `file:///libcalculator_skel.so?...`，由
  `ADSP_LIBRARY_PATH` / `DSP_LIBRARY_PATH` 搜索；`libhvx_add_skel.so` 已在
  `/usr/lib/rfsa/adsp`、`/usr/share/qcom/dsp/cdsp`、`/data/local/tmp/hvx` 三处。
- 修复：`src/hexagon690/gen/hvx_add.h` 的 `hvx_add_URI` 改为
  `"file:///libhvx_add_skel.so?hvx_add_skel_handle_invoke&_modver=1.0"`；
  设备上先备份 `hvx_add.h.pre-uri-fix-20261106` / `host_main.pre-uri-fix-20261106`，
  再改 URI 并重编（`gcc host_main.c hvx_add_stub.c -I. -Iincs -Iincs/stddef
  -o host_main -L/usr/local/lib -lcdsprpc -lpthread -ldl`）。
  脚本 `tmp/boot_probe/fix_hostmain_uri.py`，日志 `logs/firmware/hostmain-uri-fix.txt`。
- **结果**：

  ```text
  host: unsigned PD enabled for cDSP (domain=3)
  host: opened cDSP session, handle=187650505697232
  host: hvx_add_addVec done (N=1000)
  host: PASS - all 1000 elements verified correct.
  ```

  journal 同步确认 `Successfully opened file libhvx_add_skel.so`、
  `Successfully opened handle ... for file:///libhvx_add_skel.so?...`、
  `closed module libhvx_add_skel.so`。

### ④ 状态标记统一更新（以本节为准）

| 标记 | 旧状态 | 新状态 |
|---|---|---|
| V18 | ❌ INIT_CREATE 失败 | ✅ user PD 创建成功 |
| V51 | ⏸ 待设备实测 | ✅ **确证**：换整套固件消除 `AEE_EBADASID` |
| D8 | 🔄 阻塞中 | ✅ **达成** `host: PASS` |
| K8 / K8b | 进行中 / 待确认 | ✅ 全部完成并验收 |
| K5 / K6 / K7（刷内核、重编 `fastrpc.ko`） | 待定 | ❌ **不再需要**，取消 |
| P3 `INIT_CREATE_STATIC`（nr=9 / RMID8） | 待确认 | ❌ **不要执行**（有 glink 挂死风险，且问题已解决） |
| K9 上游报告 | 负结果草稿、未发送 | ✅ **已整篇改写为正结果报告**（`tmp/firmware/upstream-report.txt`），投递清单 `tmp/firmware/upstream-targets.md`；仍未发送，见 §18 |

§11 的「D8 阻塞源于固件协议代际不兼容、修复需动内核」与 §12/§13 的路线排序，
均已被 §16 → §17.6 的实机结果取代：**换整套配套固件即可，无需改内核**。

### ⑤ 保留与回滚

- 备份 `/root/cdsp-firmware-backup-20201211-pre-20210730{,.tar.gz}`、
  `/root/cdsp-rollback.sh`、`twrp_rollback.sh`、`twrp_add_rollback_entry.sh` 全部保留；
  若日后需回 2020-12 基线，按 §17.5 执行。
- **当前不要回滚**：新固件是 D8 达成的必要条件。
- 与 DSP 无关的已知残留：`data2.mount`、`rmtfs.service` 启动失败。

---

## §18 成果对外提交目标（K9，2026-11-06 联网核实）

> 回答「应该向哪几个源代码仓库提交报告」。所有 URL 于 2026-11-06 核实。
> **完整清单 + 可直接复制的 Issue 正文**：`tmp/firmware/upstream-targets.md`
> **英文主报告（已按 README 的 Bug Reporting Guidelines 组织）**：`tmp/firmware/upstream-report.txt`
> **均未发送**；对外提交需用户确认与 GitHub/GitLab 账号。

| 序 | 仓库 / URL | 形式 | 理由 |
|---|---|---|---|
| ① | `qualcomm/fastrpc#400`<br>https://github.com/qualcomm/fastrpc/issues/400 | 在 #400 下评论 | 同类「CDSP 固件拒绝创建 user PD / `*BADASID`」开放 issue；maintainer 已给出「shell 与 firmware 必须同 build、`adsp_process_group_create_mpd_attrs` 有 hash matching」，我们的 A/B 实证正好验证该判断；issue 已被标 stale |
| ② | `GengWei1997/kernel-deb`<br>https://github.com/GengWei1997/kernel-deb/issues/new | 新建 Issue（中文） | `firmware-xiaomi-raphael.deb` 的发布源，包里是 2020-12 旧固件；所有用它的 raphael mainline 用户都会踩 `0x80000453`。仓库活跃、无 README、Issues 为空 → 只适合开 Issue |
| ③ | `linux-msm/hexagon-dsp-binaries`<br>https://github.com/linux-msm/hexagon-dsp-binaries/issues | 先开 Issue 征询，**不要直接提二进制 PR** | 上游集中分发 shell/skel 的仓库，README 明言「binaries tied to SoC + firmware revision」，`config.txt` 却无 sm8150/raphael 条目；新增需动 `WHENCE`/`config.txt`/`make check`，且厂商二进制再分发许可必须先问 |
| ④ | `GengWei1997/linux-xiaomi-raphael-uefi`<br>https://github.com/GengWei1997/linux-xiaomi-raphael-uefi | README / Wiki 补充 PR | 同源发行链、中文、已有「常见问题 / 硬件适配表 / USB-NCM `172.16.42.1`」章节，可承接固件配套表与 DTB stage2 经验 |
| ⑤ | `qualcomm/fastrpc` 的 `Docs/`<br>https://github.com/qualcomm/fastrpc/tree/development/Docs | 文档 PR（先开 issue 定 scope） | `Docs/` 只有 adspmsgd / apps_mem / conf_guideline / daemons，**没有固件-shell 兼容性或 troubleshooting 文档**；这是唯一能沉淀成「上游可维护文档」的位置 |

> 最小组合：①（评论）+ ②（Issue）即可把成果留在公开可检索处；⑤ 是长期可维护性的最佳加项。

**核实中纠正的旧假设**：

- `qualcomm/fastrpc#325` 主题是「用 fastrpc 跑独立程序」，**不是** `remote_init failed`，且已于 2026-06-30 被 stale bot 关闭 → 旧草稿的投递建议作废（只作背景引用）。仓库本身是 `quic/fastrpc` 的组织迁移名（`has_discussions:false`，只能 issue/PR），默认分支 `development`，`CONTRIBUTING.md` 要求先开 issue 讨论、PR 回 `development`、commit 带 `git commit -s`。
- **LKML 从「不建议」修正为「可选第三动作」**：结论确是「`fastrpc.c` 无需补丁」，故**不能**发 `[PATCH]`、也不宜改内核 `Documentation/`；但 `submitting-patches.html` 只规范补丁、并未禁止不带 `[PATCH]` 的 FYI 邮件。发一封自包含纯文本 FYI 到 `linux-arm-msm@vger.kernel.org`（cc Srinivas Kandagatla / Amol Maheshwari）可进 `lore.kernel.org` 永久归档，价值在「提醒别再往内核打补丁」。`MAINTAINERS` 条目另含 `dri-devel@lists.freedesktop.org`、`include/uapi/misc/fastrpc.h`。
- **首创性口径精确化**：`inc/AEEStdErr.h` 公开定义 `AEE_EOFFSET=0x80000400`（DSP 侧）、`AEE_EBADASID=+0x053` → 正是 `0x80000453`，错误码本身不是新发现；但该仓库全仓 issue/PR 搜 `AEE_EBADASID`/`EBADASID` **零命中**、`0x80000453` 仅 #269 一处未归因，#400 只有抽象配套原则无成功案例 → 报告 §5.5 的准确措辞是「**该错误码这一具体根因与解法首次被公开实证**」，而非「错误码首次公开」。相关可引用：#401（closed, `0x80000416`）、#188（closed, `0x8000054f`）、#405（open, glink `-110`）、PR#319（closed **未合并**）。
- `renegade-project` 是空组织，Renegade 的正确 GitHub 组织是 `edk2-porting`；`sm8150-mainline/linux` GitHub 停更于 2022-07、gitlab.com 版本已 Archived，主线迁至 postmarketOS GitLab。
- Mesa/Turnip 的 `SET_IOVA` 修复属**另一项成果**（§「2026-11-03 日志」），若提交应单独开 issue，不要与本报告混合。
- `dipa-studio/ios-sweet`、`oosexgang/hackios-xnu-kernel` 是项目主线（跑 iOS）上游，与 cDSP 研究无交集。
- 其它归档位（门槛高、不作首选）：CodeLinaro 的 Linaro *Testing FastRPC* wiki
  https://git.codelinaro.org/linaro/qcomlt/fastrpc/-/wikis/Testing-FastRPC
  （2024-07 后未更新、需账号）；`linux-firmware` 只收 blob 不收经验文档；
  `linux-msm/hexagon-dsp-binaries` 默认分支 `trunk`、`has_wiki:false`、MIT、2026-11-05 仍活跃。

**兜底 · 已落地（2026-11-06）**：成果已自存档到本人 GitHub 公开仓库
**https://github.com/doeasier/raphael-cdsp-fastrpc**（默认分支 `main`，固定 tag
`archive-2026-11-06`）。这样即使上游 issue 被关闭/标 stale，完整证据链仍有永久可引用链接。

| 项 | 内容 |
|---|---|
| 可见性 | **public**（可被上游 issue / 邮件列表直接引用；如需改私有可在仓库 Settings 一键切换） |
| 内容 | `README.md`（中英 TL;DR + 结果矩阵 + 三个坑 + 复现路径）、`docs/`（本文件全文 + 英文报告 + 投递清单 + 部署预案 + 固件哈希/对比）、`evidence/`（冷启动验收、URI 修复、四次只读审计、P0–P2 矩阵 + `KEY-EXCERPTS.md`）、`tools/`（打包/部署/回滚/只读取证/UAPI 探针/TWRP 脚本）、`example/`（自写 HVX 工程源码）、`NOTICE.md` |
| 脱敏 | 设备 SSH 口令 → `<REDACTED>`、Wi-Fi 内网地址 → `192.168.x.x`、本机工作区路径 → `<WORKSPACE>`；自动化泄漏扫描 0 命中 |
| **不含** | **任何厂商固件二进制**（`cdsp.mdt`/`bXX`/`mbn`、`fastrpc_shell_*`、skel、`NON-HLOS.bin`、`.deb`、`.so`）；GPL 的 `drivers/misc/fastrpc.c` 副本也已排除，避免再分发义务。`.gitignore` 做了硬性拦截 |
| 构建脚本 | `tmp/build_github_archive.py`（从工作区复制 + 脱敏生成 `tmp/github-archive/`）；推送走 SSH `git@github.com:doeasier/...` |

各上游 issue / PR / FYI 邮件正文里应链到该仓库（英文报告 §6 已改为公开资产清单）。





