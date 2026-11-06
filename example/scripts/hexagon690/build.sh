#!/usr/bin/env bash
#
# scripts/hexagon690/build.sh
# 一键构建 + 部署（可选运行）封装，调用本目录 Makefile 的 target。
#
# 用法:
#   ./build.sh            # 仅构建（idl + skel + host）
#   ./build.sh deploy     # 构建并 scp 推送 skel .so 到设备
#   ./build.sh run        # 构建 + 部署 + 在设备上执行 host_main
#
# 工具链路径可通过环境变量或同目录 .env 覆盖，例如:
#   QAIC=/opt/.../qaic HEXAGON_CLANG=/opt/.../hexagon-clang ./build.sh run
#
set -euo pipefail

# 定位到本脚本所在仓库的 hexagon690 目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"   # .../src/hexagon690
cd "$PROJ_DIR"

# 可选：载入本地 .env（若用户创建）
if [[ -f "$PROJ_DIR/.env" ]]; then
    # shellcheck disable=SC1091
    source "$PROJ_DIR/.env"
fi

TARGET="${1:-build}"

# 组装 make 变量覆盖（仅在变量非空时传入）
MAKE_VARS=()
for v in HEXAGON_SDK HEXAGON_TOOLS QAIC HEXAGON_CLANG FASTRPC_ROOT FASTRPC_INC \
         FASTRPC_LIB DEVICE DEVICE_DIR; do
    if [[ -n "${!v:-}" ]]; then
        MAKE_VARS+=("$v=${!v}")
    fi
done

echo "==> project dir: $PROJ_DIR"
echo "==> make vars: ${MAKE_VARS[*]:-(defaults)}"

case "$TARGET" in
    build)
        make "${MAKE_VARS[@]}" idl
        make "${MAKE_VARS[@]}" skel
        make "${MAKE_VARS[@]}" host
        echo "==> build complete: libhvx_add_skel.so + host_main"
        ;;
    deploy)
        make "${MAKE_VARS[@]}" deploy
        echo "==> deployed libhvx_add_skel.so to device"
        ;;
    run)
        make "${MAKE_VARS[@]}" run
        ;;
    *)
        echo "usage: $0 [build|deploy|run]" >&2
        exit 1
        ;;
esac
