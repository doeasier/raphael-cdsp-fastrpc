/*
 * hvx_add_skel.c — DSP (cDSP / Hexagon 690, V66) 侧实现。
 *
 * 构建流程（见 Makefile 的 `skel` target）：
 *   1) make idl   -> QAIC 由 hvx_add.idl 生成 hvx_add.h / hvx_add_stub.c / hvx_add_skel.c
 *                   生成的 hvx_add_skel.c 提供分派框架并调用本文件实现的 hvx_add_addVec()。
 *   2) make skel  -> hexagon-clang 把本文件 + QAIC 生成的 hvx_add_skel.c 编成
 *                   libhvx_add_skel.so，部署到设备的 /usr/lib/rfsa/cdsp/。
 *
 * 本文件只需：
 *   - #include "hvx_add.h"（QAIC 生成，含方法原型与 remote_handle64 等类型）
 *   - 用 HVX intrinsic 实现 hvx_add_addVec()
 *
 * 注意：HVX 头文件 / intrinsic 名 / 加锁 API 均随 SDK 版本不同（常见为 SDK 4.x 的
 * 写法，已按最可能的名称写在此处）。若编译报"找不到头/符号"，请按所用 SDK 实际路径
 * 与头文件调整下列 #include 与调用名。
 */

#include <stdint.h>
#include <string.h>

/* QAIC 生成：方法原型 int hvx_add_addVec(remote_handle64, const int32*, const int32*, int32*, int); */
#include "hvx_add.h"

/* HVX 向量内建函数（1024-bit 向量 = 32 个 int32）。头文件名随 SDK 版本可能为
 * Hvx_Vector.h / hvx_inlines.h / q6op.h / hexagon_protos.h；编译报找不到时按 SDK 调整。 */
#include <Hvx_Vector.h>

/* HVX 单元加锁/解锁 API（HAP_hvx.h / qurt_hvx.h）。编译报找不到时按 SDK 调整。 */
#include <HAP_hvx.h>

/* HVX 一次可并行处理的 int32 元素数 = 1024bit / 32bit = 32。 */
#define HVX_INT32_LANES 32

/*
 * addVec 实现：对 32 位整数向量做逐元素相加。
 *   - 主体用 HVX 1024-bit 向量（Q6_V* 系列 intrinsic）做 32 路并行；
 *   - 尾部（len 非 32 倍数）用标量补齐；
 *   - 变长 load/store（vldu/vstu variable）允许 buffer 不按 128 字节对齐。
 *
 * intrinsic 名（Q6_V_vldu_variable_A / Q6_Vw_vadd_VwVw / Q6_void_vstu_variable_AV）
 * 为 Hexagon Tools 常见命名；若所用 SDK 不同，以实际 q6op.h/Hvx_Vector.h 为准。
 */
int hvx_add_addVec(remote_handle64 handle,
                   const int32* a,
                   const int32* b,
                   int32* out,
                   int len)
{
    int i = 0;
    int hvx_rc;

    (void)handle; /* 本例无需使用 handle */

    /* 参数校验 */
    if (a == NULL || b == NULL || out == NULL || len <= 0) {
        return -1; /* 错误码：非法参数 */
    }

    /* 加锁 HVX 单元。cDSP 上 HVX 默认未开启，必须先 lock 才能执行 HVX 指令，
     * 否则触发非法指令异常。HAP_HVX_MODE_128B 表示 1024-bit（128 字节）宽向量。
     * 备选 API：qurt_hvx_lock(..., HAP_HVX_MODE_128B)。 */
    hvx_rc = HAP_hvx_lock(HAP_HVX_MODE_128B, 0);
    if (hvx_rc != 0) {
        return -2; /* 错误码：HVX 加锁失败 */
    }

    /* 向量主体：每次处理 32 个 int32 */
    for (; i + HVX_INT32_LANES <= len; i += HVX_INT32_LANES) {
        HVX_Vector va, vb, vout;

        /* 变长 load：从 host 传入的共享内存读取 32 个 int32（不要求 128B 对齐） */
        va = Q6_V_vldu_variable_A((void*)(a + i));
        vb = Q6_V_vldu_variable_A((void*)(b + i));

        /* 32 路 int32 逐元素相加 */
        vout = Q6_Vw_vadd_VwVw(va, vb);

        /* 变长 store：写回 32 个 int32 到共享内存 */
        Q6_void_vstu_variable_AV((void*)(out + i), vout);
    }

    /* 尾部补齐：剩余不足 32 个的元素用标量处理 */
    for (; i < len; i++) {
        out[i] = a[i] + b[i];
    }

    /* 解锁 HVX 单元，交还资源 */
    HAP_hvx_unlock(0);

    return 0; /* 成功 */
}

/*
 * TODO(工具链): QAIC 生成的 skel 分派入口符号名（如 hvx_add_skel_init /
 * hvx_add_skel_handle_invoke）以 QAIC 实际生成文件为准；本文件只实现方法体，
 * 不重复定义分派入口。若链接报重复定义，检查 gen/hvx_add_skel.c 与本文件的分工。
 */
