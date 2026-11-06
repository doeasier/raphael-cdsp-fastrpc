# Makefile — 最小可运行 FastRPC + HVX(hexagon690/v66) 示例
#
# ============================================================================
# 工具链路径变量（占位）
# 具体取值待「工具链研究子 AGENT」用真实 SDK 确认后回填。下面给出常见布局示例。
# 可在命令行覆盖，例如：
#   make idl QAIC=/opt/qcom/Hexagon_SDK/4.1.0/tools/qaic/Linux/qaic
#   make skel HEXAGON_CLANG=/opt/qcom/.../Hexagon_Tools/8.4.06/bin/hexagon-clang
# ============================================================================
#
# HEXAGON_SDK   : Hexagon SDK 根目录（本例目标 4.1.0）
#                 TODO(工具链): 确认实际安装路径（常见 /opt/qcom/Hexagon_SDK/4.1.0）
# HEXAGON_TOOLS : Hexagon Tools（含 hexagon-clang）根目录
#                 TODO(工具链): 确认版本号（4.1.0 SDK 多配 8.x Hexagon Tools）
# QAIC          : QAIC IDL 编译器可执行文件（由 Hexagon SDK 提供）
# HEXAGON_CLANG : 面向 Hexagon 的 clang 交叉编译器
# FASTRPC_ROOT  : qualcomm/fastrpc 仓库根（提供 rpcmem.h / libfastrpc 等）
# FASTRPC_INC   : host 侧 fastrpc 用户态头文件目录
# FASTRPC_LIB   : host 侧 fastrpc 用户态库目录
# DEVICE        : 设备 ssh 目标。当前以 WiFi 地址 192.168.x.x（root/<REDACTED>）为准，
#                 该地址由用户明确提供且实测 22 端口可达（Phase-0 验证即连此地址）。
#                 备用：USB 网络地址 172.16.42.1（见 connect-k20pro.ps1），若改用 USB 线连接则改此值。
# DEVICE_DIR    : 设备上端侧 skel .so 的部署目录（cDSP 默认扫描路径）
# ============================================================================

HEXAGON_SDK   ?= /opt/qcom/Hexagon_SDK/4.1.0
# HEXAGON_TOOLS 版本号已与工具链研究结论对齐：4.1.0 SDK 配 8.4.06 Hexagon Tools。
HEXAGON_TOOLS ?= $(HEXAGON_SDK)/tools/HEXAGON_Tools/8.4.06
QAIC          ?= $(HEXAGON_SDK)/tools/qaic/Linux/qaic

HEXAGON_CLANG ?= $(HEXAGON_TOOLS)/bin/hexagon-clang
HEXAGON_CLANGXX ?= $(HEXAGON_TOOLS)/bin/hexagon-clang++

# QuRT (cDSP PD 运行时) 头文件路径（computev66 对应 V66 / Hexagon 690）。
# 若 SDK 布局不同，按实际路径覆盖 QURT_INC / QURT_POSIX_INC。
QURT_INC        ?= $(HEXAGON_SDK)/libs/common/qurt/computev66/include
QURT_POSIX_INC  ?= $(QURT_INC)/posix

# fastrpc 用户态：host 侧链接 libfastrpc（旧栈为 libadsprpc / libcdprpc）。
# TODO(工具链): 确认 qualcomm/fastrpc 的 inc/lib 布局（下列为常见假设）。
FASTRPC_ROOT  ?= $(HEXAGON_SDK)/libs/fastrpc
FASTRPC_INC   ?= $(FASTRPC_ROOT)/inc
FASTRPC_LIB   ?= $(FASTRPC_ROOT)/lib

# 设备部署相关
DEVICE        ?= root@192.168.x.x
DEVICE_DIR    ?= /usr/lib/rfsa/cdsp

# 本例目标名（与 .idl 基名一致）
IDL      := hvx_add.idl
STUB_C   := hvx_add_stub.c
SKEL_C   := hvx_add_skel.c        # QAIC 生成的 skel 分派框架
IMPL_C   := hvx_add_skel.c        # 用户实现（同名：构建时先生成到 gen/ 再与本文件区分）
HDR      := hvx_add.h
GEN_DIR  := gen

# 生成的 skel 分派框架放到 gen/hvx_add_skel.c，避免覆盖仓库根的用户实现
# 文件 hvx_add_skel.c；两者一起编进 .so。
GEN_STUB := $(GEN_DIR)/$(STUB_C)
GEN_SKEL := $(GEN_DIR)/$(SKEL_C)
GEN_HDR  := $(GEN_DIR)/$(HDR)

SKEL_SO  := libhvx_add_skel.so
HOST_BIN := host_main

.PHONY: all idl skel host deploy run clean

all: idl skel host

# ---------------------------------------------------------------------------
# idl: 调用 QAIC 由 .idl 生成 stub/skel/header
#   生成产物放到 gen/ 目录，避免覆盖仓库中的用户实现文件。
# TODO(工具链): 确认 qaic 参数。常见：
#   qaic -mdll -o gen hvx_add.idl   （-m 生成方法体, -dll 生成 skel 库桩）
#   部分版本用 qaic -c hvx_add.idl 或 qaic --perl 等，需据 SDK 调整。
# ---------------------------------------------------------------------------
idl:
	@mkdir -p $(GEN_DIR)
	$(QAIC) -mdll -o $(GEN_DIR) $(IDL)
	@echo "QAIC generated: $(GEN_HDR) $(GEN_STUB) $(GEN_SKEL)"

# ---------------------------------------------------------------------------
# skel: 用 hexagon-clang 针对 v66 (Hexagon 690) 编译 DSP 侧 .so
#   把「用户实现 hvx_add_skel.c」与「QAIC 生成的 gen/hvx_add_skel.c」一起编译。
# 关键标志（已与工具链研究结论对齐）：
#   -mv66 -mhvx : 启用 Hexagon 690 V66 + HVX 1024-bit 向量
#   -G0         : 关闭全局指针优化（PD 动态库常见要求）
#   -fPIC -shared -O3 : 生成位置无关共享库并开优化
#   -I 含 QuRT (computev66) 与 posix 头，链接 -lqurt -lposix -Wl,--no-threads
# ---------------------------------------------------------------------------
skel: idl
	$(HEXAGON_CLANG) \
	  -mv66 -mhvx -G0 -fPIC -shared -O3 \
	  -I$(GEN_DIR) \
	  -I$(HEXAGON_SDK)/inc/std -I$(HEXAGON_SDK)/inc \
	  -I$(QURT_INC) -I$(QURT_POSIX_INC) \
	  -I$(FASTRPC_INC) \
	  -o $(SKEL_SO) \
	  $(IMPL_C) $(GEN_SKEL) \
	  -lqurt -lposix -Wl,--no-threads
	@echo "built DSP skel: $(SKEL_SO)"

# ---------------------------------------------------------------------------
# host: 用 gcc 编译 host 侧，链接 fastrpc 用户态库
# 链接 -lfastrpc（新栈 libfastrpc.so）。旧栈/部分固件改用 -ladsprpc -lcdprpc
# （即注释掉 -lfastrpc 改用下面备选）；如需 rpcmem 显式管理，再加 -lrpcmem。
# ---------------------------------------------------------------------------
host: idl
	gcc -O2 -Wall \
	  -I$(GEN_DIR) -I$(FASTRPC_INC) \
	  -o $(HOST_BIN) \
	  host_main.c $(GEN_STUB) \
	  -L$(FASTRPC_LIB) -lfastrpc -ldl -lpthread
	# 旧栈备选（取消下一行注释并删除上一行的 -lfastrpc 即可）：
	# -L$(FASTRPC_LIB) -ladsprpc -lcdprpc -ldl -lpthread
	@echo "built host binary: $(HOST_BIN)"

# ---------------------------------------------------------------------------
# deploy: 通过 ssh 把 skel .so 推到设备的 cDSP 目录
# ---------------------------------------------------------------------------
deploy: skel
	scp $(SKEL_SO) $(DEVICE):$(DEVICE_DIR)/$(SKEL_SO)
	@echo "deployed $(SKEL_SO) -> $(DEVICE):$(DEVICE_DIR)/"

# ---------------------------------------------------------------------------
# deploy-host: 把 host 可执行文件推到设备可写/可执行目录
# TODO(工具链): 确认 host_main 在设备上的部署路径（DEVICE_BIN_DIR），
#               以及是否需附带 fastrpc 用户态库、是否需 chmod +x。
# ---------------------------------------------------------------------------
DEVICE_BIN_DIR ?= /data/local/tmp
deploy-host: host
	scp $(HOST_BIN) $(DEVICE):$(DEVICE_BIN_DIR)/$(HOST_BIN)
	ssh $(DEVICE) "chmod +x $(DEVICE_BIN_DIR)/$(HOST_BIN)"
	@echo "deployed $(HOST_BIN) -> $(DEVICE):$(DEVICE_BIN_DIR)/"

# ---------------------------------------------------------------------------
# run: 构建 + 部署 skel 与 host，并在设备上执行 host 程序
# ---------------------------------------------------------------------------
run: skel host deploy deploy-host
	ssh $(DEVICE) "cd $(DEVICE_BIN_DIR) && ./$(HOST_BIN)"

# ---------------------------------------------------------------------------
# clean
# ---------------------------------------------------------------------------
clean:
	rm -rf $(GEN_DIR) $(SKEL_SO) $(HOST_BIN)
	@echo "cleaned."
