# K20 Pro GPU（Vulkan）编译与排错要点

> 目标：在 K20 Pro（红米 K20 Pro 尊享版，骁龙 855+ / Adreno 640，aarch64 Linux）上编译
> llama.cpp 的 **Vulkan 后端**，用 `-ngl` 把层卸载到 GPU，对比 CPU(NEON) 推理速度。
>
> 源码：llama.cpp **v0.8.0**，位于设备 `/data2/llama.cpp-0.8.0`
> 编译/运行都在**设备本机**完成（本机是 Windows，无 WSL/Linux 宿主机；通过 SSH `root@192.168.x.x` 操作）。
>
> **一句话结论**：编译成功，fp32 补丁生效，但运行时 `vkCreateDevice` 被**内核 IOMMU 拦截**，
> GPU 路线在现有内核下不可行（见第 6 节）。现有 `build-vulkan` 二进制留作日后换内核后直接重试。

---

## 0. 前置依赖（设备端）

- 编译工具：`cmake`、`make`、gcc/g++（aarch64）
- **`ninja-build`（关键）**：解决 Make 目录竞态，见第 3 节。`apt-get install -y ninja-build`
  （apt 源为清华 `ubuntu-ports` 镜像）
- Vulkan 运行时/头文件：`vulkan-tools`（`vulkaninfo`）、Vulkan loader/headers
- OpenMP（编译开了 `-DGGML_OPENMP=ON`）

---

## 1. 源代码修改（必须，在编译之前）

**文件**：`/data2/llama.cpp-0.8.0/ggml/src/ggml-vulkan/ggml-vulkan.cpp`

**问题**：Adreno 640（turnip / freedreno 驱动）**不支持** `storageBuffer16BitAccess`
（16-bit storage，扩展 `VK_KHR_16bit_storage`）。原代码检测到不支持就直接 `throw` 中止，
导致 llama-server 起不来。

**修改**：把 `throw` 改成打印告警，并**强制走 fp32 回退路径**（着色器本就带 fp32 fallback）。

```cpp
// ===== 修改前（old）=====
        if (!vk11_features.storageBuffer16BitAccess) {
            std::cerr << "ggml_vulkan: device " << GGML_VK_NAME << idx << " does not support 16-bit storage." << std::endl;
            throw std::runtime_error("Unsupported device");
        }

        device_extensions.push_back("VK_KHR_16bit_storage");

// ===== 修改后（new）=====
        if (!vk11_features.storageBuffer16BitAccess) {
            std::cerr << "ggml_vulkan: device " << GGML_VK_NAME << idx << " does not support 16-bit storage; forcing fp32 path." << std::endl;
            // throw std::runtime_error("Unsupported device");  // PATCHED for Adreno640/turnip
            device->fp16 = false;
        }

        if (vk11_features.storageBuffer16BitAccess) {
            device_extensions.push_back("VK_KHR_16bit_storage");
        }
```

**要点说明**：
- 原代码无条件 `device_extensions.push_back("VK_KHR_16bit_storage")`；改为**仅在支持时才添加**。
- `device->fp16 = false` 关闭 fp16、强制 fp32 路径，从而绕过 16-bit storage 硬门槛。
- 该补丁已在构建日志中确认生效（日志出现 `forcing fp32 path`）。
- **不要按行号硬改**：原讨论里的行号（约 4664 行）随版本漂移。请用上方代码块文本做**精确字符串匹配**
  （部署脚本用 `assert old in s` 校验），匹配不到就说明上下文已变，需要重新核对。

> 对应脚本：`scripts/gpu_patch.py`（通过 paramiko 在设备端用 `python3 - <<'PY'` 内联打补丁，
> `assert old in s` 失败即中止，成功打印 `PATCH_APPLIED`）。

### 1.1 「16-bit storage」与「fp16 ALU」是两个不同的 Vulkan 特性（参考链接证实）

你给的两篇资料正好把之前容易混的点讲清楚了。关键原句：

> Support for this was added by the `VK_KHR_16bit_storage` extension, which was promoted to core in Vulkan 1.1. You need to check/enable the `VkPhysicalDevice16BitStorageFeaturesKHR::storageBuffer16BitAccess` feature. Then you can use `float16_t`, `f16vec2`, etc. types in your buffer declaration in GLSL.

**对照结论**：

| Vulkan 特性 | 含义 | Adreno 640 是否支持 | 依据 |
|---|---|---|---|
| `storageBuffer16BitAccess`（来自 `VK_KHR_16bit_storage`，Vulkan 1.1 核心） | 允许在 **buffer/uniform 里存放 16-bit（fp16）数据** | ❌ **不支持** | `vulkaninfo` 无此项；llama.cpp 因此 `throw` |
| `shaderFloat16` / `shaderInt16`（来自 `VK_KHR_shader_float16_int8`） | 着色器里能做 **fp16 算术运算** | ✅ **支持** | 即你早先查到的「Adreno 640 支持 fp16」 |

要点：
1. 这两个是**独立的特性位**。Adreno 640 缺的是**前者（16-bit 存储）**，不是后者（fp16 计算）——它确实能算 fp16，但**不能在 buffer 里存 fp16**。
2. 资料里的 `float16_t`/`f16vec2` GLSL 类型，**前提是设备先报告 `storageBuffer16BitAccess = true`**。这是个**硬件能力位、不是软件开关**：Adreno 640 报告 false，就**无法 enable**，只能走 fp32。这正好证明第 1 节的 fp32 补丁是正确且必要的。
3. llama.cpp 的 Vulkan 后端要用 16-bit storage 把 fp16 权重量化后**放进 buffer**，所以缺这个特性就 `throw`；即便设备有 fp16 ALU 也救不了，因为它的代码路径依赖的是 **storage** 而非 ALU。
4. **更致命的是**：补丁把 fp32 走通后，`vkCreateDevice` 仍被内核 IOMMU 卡死（第 5 节），**任何着色器都还没机会运行**。所以「16-bit storage vs fp16 ALU」之争在运行时根本到不了——真墙在内核层。

因此这两篇资料**不改变 GPU 结论**，只是从 Vulkan 规范层面确认了：① 我们打 fp32 补丁的判断是对的；② Adreno 640 的 fp16 能力（ALU）和 llama.cpp 需要的 fp16 能力（storage）不是一回事。

参考链接：
- https://cloud.tencent.com/developer/ask/sof/115010261
- https://stackoverflow.com/questions/49689632/vulkan-compute-shader-with-16-bit-floating-point-operation-on-android-device

---

## 2. 编译参数与命令（正确做法：Ninja）

先确保已装 `ninja-build`，删掉旧构建目录，用 **Ninja 生成器**重新配置并编译：

```bash
# 设备端执行
which ninja >/dev/null 2>&1 || DEBIAN_FRONTEND=noninteractive apt-get install -y ninja-build

cd /data2/llama.cpp-0.8.0
rm -rf build-vulkan && mkdir build-vulkan && cd build-vulkan

cmake -G Ninja \
      -DGGML_VULKAN=ON \
      -DCMAKE_BUILD_TYPE=Release \
      -DLLAMA_CURL=ON \
      -DGGML_OPENMP=ON \
      ..

ninja
```

**关键参数说明**：
- `-G Ninja`：**必须用 Ninja 生成器**。最初用默认 Make + `make -j$(nproc)` 会因为
  `CMakeFiles/<target>.dir` 目录尚未建好就去写 `.d` 依赖文件而报错（日志里 `BUILD_EXIT_2`），
  Ninja 会自动预建目录，规避目录竞态。
- `-DGGML_VULKAN=ON`：开启 Vulkan 后端，这是 GPU 路线的核心开关。
- `-DGGML_OPENMP=ON` / `-DLLAMA_CURL=ON`：多线程 + 服务器 curl 支持（聊天/接口需要）。
- 构建产物：`/data2/llama.cpp-0.8.0/build-vulkan/bin/llama-server`（及 `llama-cli` 等）。

> 构建日志：`/data2/build-vulkan.log`，成功时末尾应有 `BUILD_EXIT_0`。
>
> （历史命令，已弃用）`scripts/gpu_build_launch.py` 用的是 `cmake ...`（默认 Make）+ `make -j$(nproc)`，
> 因目录竞态失败，被上面的 Ninja 方案取代。

---

## 3. 运行 / 启动命令（GPU server）

```bash
# 设备端执行（构建完成后）
cd /data2/llama.cpp-0.8.0/build-vulkan
./bin/llama-server \
    -m /data2/models/Qwen3.5-4B-Q4_K_M.gguf \
    -c 8192 \
    --host 0.0.0.0 --port 8082 \
    -ngl 999
```

**注意**：
- `-ngl 999`：把所有层卸载到 GPU（Vulkan）。这是 GPU 加速的关键参数；CPU 模式不传或传 0。
- **不要加 `--webui 0`**：它是无效参数，llama-server 启动即报 `invalid argument 0` 并退出。
  服务器不带内置 Web UI（本构建的 `tools/server/public` 不存在），聊天页用我们自己的
  `chat.html` + `--path /data2/webui` 静态托管（CPU 服务 `llama-4b.service` 已这样配）。
- 监听 `0.0.0.0:8082`，与 CPU 服务（8081）错开，避免互斥。
- 日志：`/data2/llama-server-gpu.log`。

> 对应脚本：`scripts/gpu_server_test.py`（注：该脚本里仍带 `--webui 0`，实际已确认无效，
> 真正可用命令以上方为准）。

---

## 4. 验证步骤

```bash
# 1) 构建是否成功
cat /data2/build-vulkan.log | tail -5          # 看 BUILD_EXIT_0 与 forcing fp32 path

# 2) 设备 Vulkan 能力（确认无 16-bit storage，这正是第 1 节补丁的原因）
vulkaninfo 2>/dev/null | grep -iE 'deviceName|storageBuffer16BitAccess|16bit|float16|shaderFloat16'

# 3) 启动后看 GPU 初始化日志
cat /data2/llama-server-gpu.log
```

预期：`vulkaninfo` 会显示 `deviceName = Adreno 640 (...)` 且 **没有** `storageBuffer16BitAccess`
（即补丁命中分支，走 fp32）；但 **`shaderFloat16` / `shaderInt16` 会显示 `= true`**——
这正是「Adreno 640 支持 fp16 计算、但缺 16-bit 存储」的证明（见 1.1 节）。

---

## 5. 关键故障（真墙，无法绕过）

启动 GPU server 时，Vulkan 设备初始化失败：

```
MSM_INFO_SET_IOVA failed! -28 ENOSPC
VK_ERROR_OUT_OF_HOST_MEMORY
```

- `vulkaninfo`（纯驱动层、不创建 device）**同样失败** → 说明是**内核/驱动层**问题，
  不是 llama.cpp 或 Vulkan 用法的问题。
- `dmesg` 里有 `arm-smmu` **context fault**。
- **根因**：Adreno 640 走 `msm` DRM 驱动 + `arm-smmu` IOMMU，在当前内核下为 GEM buffer
  建立 IOVA 失败（`-28 ENOSPC`）。
- `msm` 是内核**内置**驱动，不可卸载/重载；**没有用户态解法**。

**结论**：在当前内核下，无论 llama.cpp / MNN / MLC-LLM，只要走 Adreno 的 GPU
（Vulkan 或 OpenCL）都会撞同一道内核关。唯一根治是换带正确 `msm` IOMMU 的 raphael 内核
（高风险大工程，属路线 A 范畴）。

---

## 6. 现状与后续

- GPU 构建**已成功**产出 `build-vulkan/bin/llama-server`，fp32 补丁确认生效；
  但**无法实际用 GPU 推理**（卡在第 5 节的内核墙）。
- 若日后换了合格内核，可直接用现成的 `build-vulkan` 二进制 + `-ngl 999` 重试，**无需重新编译**。
- 本机 K20 Pro 上大模型推理仍走 CPU（llama.cpp NEON，8081 服务）；
  想更快可评估 **MNN-LLM 的 CPU 路径**（855+ 是 ARMv8.2，能吃到 MNN 的 sdot/FP16 加速）。

---

## 附：相关脚本清单（位于 `scripts/`）

| 脚本 | 作用 |
|---|---|
| `gpu_patch.py` | 在设备端内联打 fp32 补丁（第 1 节） |
| `gpu_build_ninja.py` | Ninja 生成器编译（第 2 节，可用方案） |
| `gpu_build_launch.py` | 旧版 Make 编译（已弃用，目录竞态失败） |
| `gpu_server_test.py` | 启动 GPU server（注意含无效 `--webui 0`） |
| `gpu_vkinfo.py` | 取设备 Vulkan 能力（第 4 节验证用） |
| `gpu_rebuild.py` / `gpu_cleanup.py` 等 | 重新构建 / 清理 |
