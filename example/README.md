# 最小可运行示例：FastRPC + 自定义 HVX（骁龙 855 / SM8150 / Hexagon 690 / V66）

本目录给出一个**最小、流程完整、可读优先**的示例：host 端把两个整数向量发给
cDSP（Hexagon 690），DSP 用 HVX 1024-bit 向量 intrinsic 做逐元素相加，结果返回
host 校验。目标只求「流程跑通」，不追求性能。

> 工具链研究子 AGENT 已确认大部分编译/链接关键事实（QAIC 生成约定、`-mv66 -mhvx` 标志、
> Unsigned PD 启用方式、fastrpc 库名、Hexagon Tools 8.4.06），并已回填代码与 §7 清单。
> 编译能否通过最终取决于 SDK 是否就位与个别 SDK 版本差异（见 §7 仍待确认项）。

---

## 1. 目录结构

```
hexagon690/
├── hvx_add.idl        # FastRPC IDL：声明接口与 addVec 方法
├── hvx_add_skel.c     # DSP 侧实现：用 HVX intrinsic 实现 addVec
├── host_main.c        # host 侧：开会话、派发、校验、打印
├── Makefile           # idl / skel / host / deploy / run 等 target
├── README.md          # 本文件
├── scripts/
│   └── hexagon690/
│       └── build.sh   # 一键构建 + 部署 + 运行的封装（调用 Makefile）
└── gen/               # make idl 由 QAIC 生成的 stub/skel/header（gitignore 友好）
```

---

## 2. 构建前置

需要三件套：

1. **Hexagon SDK 4.1.0**（提供 QAIC、Hexagon Tools 集成、fastrpc 头文件）
   - 下载：Qualcomm 开发者网络（Hexagon SDK）
   - TODO(工具链): 确认 4.1.0 的官方下载地址与安装路径（默认多为
     `/opt/qcom/Hexagon_SDK/4.1.0`）。
2. **Hexagon Tools**（提供 `hexagon-clang` 交叉编译器，对应 V66 / Hexagon 690）
   - 通常随 SDK 捆绑，或独立安装。
   - 版本号已确认：**8.4.06**（与 SDK 4.1.0 匹配；Makefile `HEXAGON_TOOLS` 默认值已改）。
3. **qualcomm/fastrpc**（`git clone https://github.com/quic/fastrpc`）
   - 提供 host 侧用户态库（libfastrpc / libadsprpc）、`rpcmem.h` 等。
   - TODO(工具链): 确认仓库版本与所需头/库目录布局。

环境建议：**WSL2 (x86_64 Ubuntu)** 下构建。QAIC 与 `hexagon-clang` 均为 Linux
二进制；Windows 原生不支持，请在 WSL 中执行 `make`。

> 部署目标设备：Redmi K20 Pro（骁龙 855）。当前以 **WiFi 地址 `192.168.x.x`**
> （root/<REDACTED>）为准——该地址由用户明确提供、且 Phase-0 设备验证实测 22 端口可达，
> Makefile 的 `DEVICE` 变量默认即此值。备用：**USB 网络地址 `172.16.42.1`**
> （见 `connect-k20pro.ps1`），若改用 USB 线连接则改 `DEVICE` 变量。

---

## 3. 在 WSL(x86_64 Linux) 中构建

```bash
# 1) 进入目录
cd src/hexagon690

# 2) 生成 stub/skel/header（需先就位 QAIC）
make idl QAIC=/opt/qcom/Hexagon_SDK/4.1.0/tools/qaic/Linux/qaic

# 3) 编译 DSP 侧 .so（需 hexagon-clang / v66）
make skel HEXAGON_CLANG=/opt/qcom/.../Hexagon_Tools/8.4.06/bin/hexagon-clang

# 4) 编译 host 侧可执行文件（需 gcc + fastrpc 用户态库）
make host FASTRPC_INC=.../fastrpc/inc FASTRPC_LIB=.../fastrpc/lib
```

或直接 `make all`（会依次 idl → skel → host）。

产物：
- `libhvx_add_skel.so` —— 部署到设备 cDSP 目录。
- `host_main` —— 在设备上运行的 host 程序。

> 注：上述 `QAIC / HEXAGON_CLANG / FASTRPC_*` 路径为占位，需在工具链确认后填实，
> 也可写入本目录一个 `.env` 或在命令行覆盖。

---

## 4. 部署到 K20 Pro 并运行

cDSP 默认从 `/usr/lib/rfsa/cdsp/` 加载 skel 库；host 程序放到设备可写/可执行目录
（如 `/data/local/tmp`）。

```bash
# 部署 skel .so 到设备 cDSP 目录（make deploy 内部执行）:
make deploy DEVICE=root@192.168.x.x

# 把 host_main 也推到设备（示例脚本 build.sh 会一并处理）:
scp host_main root@192.168.x.x:/data/local/tmp/

# 在设备上运行（make run 内部执行）:
make run DEVICE=root@192.168.x.x
```

> TODO(工具链): 确认 host 程序是否还需要随附 `libfastrpc.so` 等用户态库到设备
> `/vendor/lib64` 或 `/system/lib64`；以及是否需要 `chmod +x` 与 SELinux 权限
> （Unsigned PD / 关闭 verity 等，参见工具链研究的 TVM launcher 结论）。

---

## 5. 预期输出

设备上执行 `./host_main` 应看到类似：

```
host: opened cDSP session, handle=1
host: hvx_add_addVec done (N=1000)
host: first 16 results (a + b = out):
  [   0]   -500 +     1 =   -499
  [   1]   -498 +     2 =   -496
  [   2]   -496 +     3 =   -493
  ...
  [  15]   -470 +    16 =   -454
host: PASS — all 1000 elements verified correct.
```

若 `out[i] != a[i] + b[i]`，会打印 `host: FAIL — N/1000 mismatches.`，
常见原因：HVX 未加锁（DSP 端非法指令）、共享内存未正确映射、或 `len` 尾部处理错误。

---

## 6. 设计要点 / 注意事项

- **Unsigned PD（无签名模块）必须先启用**：现代 fastrpc 栈默认只允许加载**已签名**
  的 DSP 模块。本示例的 `hvx_add_skel.so` 是**无签名**的，因此 host 侧在**任何一次
  FastRPC 调用之前**必须先下发 `remote_session_control(DSPRPC_CONTROL_UNSIGNED_MODULE,
  &data, sizeof(data))`（其中 `data.enable = 1; data.domain = CDSP_DOMAIN_ID;`，
  cDSP 的 `CDSP_DOMAIN_ID` 一般为 3）。代码见 `host_main.c` 的 `enable_unsigned_pd()`；
  该调用通过 `#pragma weak remote_session_control` 声明为弱符号，SDK 不支持时安全跳过
  （若随后 `hvx_add_open` 失败则需改用支持该控制的 fastrpc 栈）。**漏掉这一步会直接导致
  加载无签名 skel 失败**，这是首次跑通最常见的一个坑。
- **HVX 加锁**：cDSP 上 HVX 单元默认未开启，`hvx_add_skel.c` 中在向量运算前调用
  `HAP_hvx_lock(HAP_HVX_MODE_128B, 0)`（或 `qurt_hvx_lock`），结束后 `HAP_hvx_unlock`。
  这是 V66 上跑 HVX 的必要条件。
- **32 路并行**：1024-bit HVX 向量 = 32 个 int32；主循环每次处理 32 个元素，
  用变长 load/store（vldu/vstu variable）以支持非对齐 buffer；尾部标量补齐。
- **内存模型**：IDL 指针参数由 QAIC 生成的 stub 通过 `rpcmem` 自动在 host↔DSP
  间做共享内存拷贝，host 侧用普通 `malloc` 即可；大 buffer 可改用 `rpcmem_alloc`
  减少一次拷贝。

---

## 7. TODO(工具链) 待确认清单

> 经工具链研究子 AGENT 确认并已回填代码/本 README 的项，标记为 **[已确认]**；
> 以下仅保留**真正未决**项（编译报错时按对应项排查）。

**[已确认] 编译/链接关键事实（已写入 Makefile / 代码注释，SDK 就位后即可尝试首编）：**
- QAIC 由 `hvx_add.idl` 生成 `hvx_add.h` / `hvx_add_skel.c`（分派框架）/ `hvx_add_stub.c`（host 侧）；
  方法命名：`rpc_interface` 中 `method(args)=N` → `hvx_add_<method>(remote_handle64, args...)`，
  并生成 `hvx_add_open` / `hvx_add_close`；指针参数由 QAIC 自动经 rpcmem 共享内存拷贝（host 用 malloc 即可）。
- DSP 侧编译标志：`-mv66 -mhvx -G0 -fPIC -shared -O3`；QuRT include 在
  `$HEXAGON_SDK/libs/common/qurt/computev66/include`（及 `/posix`）；链接 `-lqurt -lposix -Wl,--no-threads`。
- Unsigned PD 启用方式（首次 FastRPC 调用前）：host 侧 `#include <remote.h>`，
  `#pragma weak remote_session_control` + `remote_session_control(DSPRPC_CONTROL_UNSIGNED_MODULE, &data, sizeof(data))`，
  `data.enable=1; data.domain=CDSP_DOMAIN_ID;`（cDSP 一般为 3）。见 `host_main.c::enable_unsigned_pd()`。
- fastrpc 用户态库名：host 链接 `libfastrpc`（旧栈备选 `-ladsprpc -lcdprpc`）；设备节点 `/dev/fastrpc-cdsp`。
- Hexagon Tools 版本号与 4.1.0 SDK 匹配为 **8.4.06**（Makefile `HEXAGON_TOOLS` 默认值已改）。

**仍待确认（SDK 就位后按报错排查）：**
1. **Hexagon SDK 4.1.0** 确切下载文件名与默认安装路径（默认假设 `/opt/qcom/Hexagon_SDK/4.1.0`）。
2. **QAIC 生成参数选择**：本例用 `qaic -mdll -o gen hvx_add.idl`；部分 SDK 版本用
   `qaic -c` 或不同 `-m/-dll` 组合，按实际 QAIC 帮助调整。
3. **HVX 头文件确切名随 SDK 版本**：`<Hvx_Vector.h>` / `hvx_inlines.h` / `q6op.h` / `hexagon_protos.h`
   （编译报找不到头时按 SDK 调整 `hvx_add_skel.c` 的 `#include`）。
4. **HVX intrinsic 名随 SDK 版本**：`Q6_V_vldu_variable_A` / `Q6_Vw_vadd_VwVw` /
   `Q6_void_vstu_variable_AV` 以实际 `q6op.h`/`Hvx_Vector.h` 为准。
5. **HVX 加锁 API 名随 SDK 版本**：`HAP_hvx_lock` / `HAP_hvx_unlock`（或 `qurt_hvx_lock`）
   所在头文件与精确签名。
6. **`hvx_add_open` 的 uri 形式**：`"hvx_add_skel.so"` 还是带路径
   `"file:///usr/lib/rfsa/cdsp/hvx_add_skel.so"`。
7. **设备部署细节**：host 侧是否需随附 `libfastrpc.so` 到设备 `/vendor/lib64` 或
   `/system/lib64`；SELinux / verity 处理（Unsigned PD 前提见 §6）。

> 设备 IP 与部署目标：当前以 **WiFi `192.168.x.x`**（root/<REDACTED>，Phase-0 实测 22 端口可达）
> 为准，USB 备用 **`172.16.42.1`**（见 `connect-k20pro.ps1`）。Makefile `DEVICE` / `DEVICE_DIR`
> 已固定，无需修改。
