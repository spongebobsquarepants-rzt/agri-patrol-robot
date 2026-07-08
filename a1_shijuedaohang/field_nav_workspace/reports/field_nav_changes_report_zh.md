# 田间导航线检测项目改动报告

## 1. 改动范围

本次检查和修复主要覆盖两个新增区域：

- `field_nav_workspace`：PC 侧数据转换、训练、评估和模型导出工作区。
- `data/A1_SDK_SC132GS/smartsens_sdk/field_nav_external`：A1 SDK 的 Buildroot external、板端 `field_nav_demo` 应用、启动脚本和打包配置。

没有修改原始 LabelMe 数据集文件。原始 SDK 中已有的大量文件也没有主动改动，改动集中在新增的外部包和训练工作区。

## 2. 板端应用修复

### 2.1 修复 OSD API 命名空间问题

改动文件：

- `field_nav_external/src/field_nav_demo/src/osd_overlay.cpp`

改动内容：

- 将 `osd_open_device`、`osd_close_device`、`osd_delete_buffer`、`osd_clean_layer` 等调用统一改为 `fdevice::osd_*`。

预防的问题：

- 防止交叉编译时报错：`osd_close_device was not declared in this scope`。
- 防止 Buildroot 重新编译时继续卡在 OSD 头文件命名空间不匹配问题上。

### 2.2 增强 OSD 初始化失败处理

改动文件：

- `field_nav_external/src/field_nav_demo/src/osd_overlay.cpp`
- `field_nav_external/src/field_nav_demo/include/field_nav.hpp`

改动内容：

- 增加 `layer_created_` 状态标记。
- 检查 `osd_alloc_buffer`、`osd_get_buffer_fd`、`osd_create_layer`、`osd_set_layer_buffer` 的返回值。
- 如果中途失败，会释放已经分配的 DMA buffer、销毁已创建 layer、关闭 OSD handle。

预防的问题：

- 防止 OSD 初始化失败后资源泄漏。
- 防止只初始化一半的 OSD 状态影响下一次启动。
- 防止 DMA buffer 或 layer 没有创建成功时继续运行导致异常。

### 2.3 增强 NPU/SSNE 模型加载和 tensor 检查

改动文件：

- `field_nav_external/src/field_nav_demo/src/navline_detector.cpp`
- `field_nav_external/src/field_nav_demo/include/field_nav.hpp`

改动内容：

- 检查 `ssne_loadmodel` 是否失败。
- 检查 `create_tensor` 后的数据指针是否为空。
- 检查 `ssne_getoutput` 后输出 tensor 是否为空。
- 增加 `input_created_`、`output_ready_` 状态标记。
- `Release()` 时释放 input/output tensor。

预防的问题：

- 防止模型文件损坏、模型格式不对、NPU 初始化失败时继续推理。
- 防止空 tensor 被后处理读取导致崩溃。
- 防止长时间运行或反复启动时 tensor 资源未释放。

## 3. Buildroot 打包和启动脚本修复

### 3.1 每次构建前清理旧包缓存

改动文件：

- `field_nav_external/scripts/build_field_nav.sh`

改动内容：

- 增加：

```bash
make BR2_EXTERNAL=./smart_software:./field_nav_external field_nav_demo-dirclean
```

预防的问题：

- 防止 Buildroot 继续使用 `output/build/field_nav_demo` 下的旧源码。
- 防止你已经修改了 `field_nav_external/src/...`，但编译仍然报旧错误。

### 3.2 修正模型路径配置

改动文件：

- `field_nav_external/package/field_nav_demo/Config.in`
- `field_nav_external/configs/field_nav_m1pro_defconfig`
- `field_nav_external/package/field_nav_demo/field_nav_demo.mk`
- `field_nav_external/src/field_nav_demo/scripts/run.sh`

改动内容：

- 将默认模型相对路径改为：

```text
app_assets/models/navroad_640x480.m1model
```

- 安装阶段用 `$(SED)` 将 `run.sh` 里的 `@FIELD_NAV_MODEL_PATH@` 替换为 Buildroot 配置值。
- `run.sh` 保留默认兜底路径，避免未替换时直接跑出错误路径。

预防的问题：

- 防止 `BR2_FIELD_NAV_MODEL_PATH` 配置了但运行时不生效。
- 防止目标板上实际查找路径变成 `/field_nav/models/...`，而模型实际被打包在 `/field_nav/app_assets/models/...`。
- 防止后续改模型文件名或路径时需要同时手改多个地方。

### 3.3 确保运行脚本安装权限

改动文件：

- `field_nav_external/package/field_nav_demo/field_nav_demo.mk`

改动内容：

- 用 `$(INSTALL) -D -m 0755` 安装 `run.sh`。

预防的问题：

- 防止 rootfs 中 `/field_nav/scripts/run.sh` 没有执行权限。
- 防止板端启动时脚本无法执行。

## 4. PC 侧数据和训练脚本修复

### 4.1 增加参数防呆

改动文件：

- `field_nav_workspace/tools/prepare_labelme_dataset.py`
- `field_nav_workspace/tools/train_navroad.py`
- `field_nav_workspace/tools/evaluate_navroad.py`
- `field_nav_workspace/tools/audit_labelme_dataset_v2.py`
- `field_nav_workspace/tools/prepare_labelme_dataset_v2.py`
- `field_nav_workspace/tools/train_navroad_v2.py`
- `field_nav_workspace/tools/evaluate_navroad_v2.py`
- `field_nav_workspace/tools/compare_onnx_navroad_v2.py`

改动内容：

- 检查输入宽高必须为正数。
- 检查 train/val/test 划分比例是否合法。
- 检查 `epochs`、`batch-size`、`patience`、`width-mult` 等训练参数是否合法。
- 检查 split 是否为空。
- 检查评估阈值必须在 0 到 1 之间。
- 检查 ONNX 对比样本数必须大于 0。

预防的问题：

- 防止用户传入错误参数后训练到最后才崩溃。
- 防止空训练集、空验证集导致无意义训练或除零问题。
- 防止阈值错误导致评估结果不可信。

### 4.2 优化审核脚本读图逻辑

改动文件：

- `field_nav_workspace/tools/audit_labelme_dataset_v2.py`

改动内容：

- 生成 overlay 预览时复用已经打开的图片尺寸逻辑，避免重复打开图片并可能出现尺寸读取不一致。

预防的问题：

- 降低审核脚本处理大量图片时的无效 IO。
- 减少预览图生成阶段因重复读图引入的边缘错误。

### 4.3 修正文档路径示例

改动文件：

- `field_nav_workspace/README.md`

改动内容：

- 使用 `$DATASET_ROOT` 保存中文数据集路径。

预防的问题：

- 防止中文路径在终端或拷贝命令中乱码。
- 减少 PowerShell 命令中路径写错的概率。

## 5. 已执行验证

已完成的本地验证：

- 所有 Python 工具通过 `python -m py_compile`。
- v2 测试集评估可以正常运行。
- v1 测试集评估可以正常运行。
- 检查 shell 脚本换行格式，均为 LF，不是 CRLF。
- 模拟检查 `run.sh` 中模型路径替换后的结果。
- 确认 `field_nav_external` 内 OSD API 调用都已带 `fdevice::` 命名空间。

当前 v2 测试结果：

```text
mean_iou = 0.5022
mean_center_error_px = 45.61
invalid_centerline_samples = 0/32
```

## 6. 当前仍需注意的问题

### 6.1 尚未在 Docker 里完成交叉编译验证

当前 Windows 环境没有完整交叉编译环境，因此 C++ 最终编译仍需要在 A1 SDK Docker 容器里验证：

```bash
cd /home/smartsens_flying_chip_a1_sdk/A1_SDK_SC132GS/smartsens_sdk
bash ./field_nav_external/scripts/build_field_nav.sh
```

### 6.2 ONNX 到 `.m1model` 转换仍需外部工具

当前 SDK 目录中没有发现可直接使用的 ONNX 转 `.m1model` 工具。板端最终运行需要把：

```text
field_nav_workspace/runs/navroad_v2/navroad_640x480.onnx
```

转换为：

```text
field_nav_external/src/field_nav_demo/app_assets/models/navroad_640x480.m1model
```

### 6.3 模型质量还没有达到目标

v2 比 v1 有提升，但还没有达到计划中的：

```text
test mean_iou >= 0.60
mean_center_error_px < 35
```

下一步应优先检查：

```text
field_nav_workspace/data/audit_v2/overlays
field_nav_workspace/runs/navroad_v2/failures
```

修正 `labelme_curated_v2` 中明显错标、漏标、边界粗糙的样本，再重新训练。

## 7. 总结

本次改动主要不是为了增加功能，而是为了降低编译失败、路径错误、启动失败、资源泄漏和错误参数导致训练结果不可信的风险。板端路径、Buildroot 缓存、OSD 命名空间、NPU tensor 检查、训练参数防呆这些问题都已经处理。下一步关键验证是在 Docker SDK 容器里重新编译，并在转换好 `.m1model` 后上板测试。

## 8. 参赛合规补齐：60 秒运行与性能证据

### 8.1 当前定位

本项目保留“田间机器人道路/作物过道导航”方向，按参赛评分口径整理为 5 个可验证功能：

- 图像采集：A1 从 SC132GS 图像链路取图，进入 `field_nav_demo`。
- A1/NPU AI：`navroad_640x480.m1model` 通过 SSNE 推理输出道路概率图。
- 导航结果：CPU 后处理输出 `valid`、`deviation_px`、`angle_deg`、`confidence`、`bottom_x`。
- 图像验证：OSD 启动测试框和导航线叠加在 Aurora 中间画面。
- 串口验证：A1 UART0 TX 发送导航帧，RDK X5 桥接脚本可转换为下位机控制帧；失效时发送无效/停车状态。

### 8.2 本次新增的板端日志证据

`field_nav_demo` 主循环新增 60 秒滚动窗口统计，每秒打印一行：

```text
[field_nav] metrics tag=heartbeat window=60s total_frames=... samples=... FPS_app=... target_sensor_fps=... fps_ratio=... P95_frame_ms=... max_frame_ms=... valid_nav=... no_line=... predict_fail=... image_fail=... uart_sent=... uart_fail=... status_ok=... status_no_line=... status_predict_fail=... status_camera_fail=... max_invalid_ms=... max_invalid_frames=...
```

字段含义：

- `FPS_app`：应用主循环实测帧率，用于判断是否接近传感器输出帧率。
- `P95_frame_ms` / `max_frame_ms`：端到端处理耗时的 P95 和最大值。
- `valid_nav` / `no_line` / `predict_fail` / `image_fail`：有效导航、无有效线、AI/预处理失败、摄像头取帧失败计数。
- `uart_sent` / `uart_fail`：串口发送成功和失败计数。
- `max_invalid_ms`：60 秒窗口内最长连续无效导航时间，用于鲁棒性扣分判断。

### 8.3 板端 60 秒验证命令

保守默认运行：

```sh
FIELD_NAV_UART=1 FIELD_NAV_BAUD=115200 FIELD_NAV_RATE=10 /field_nav/scripts/run.sh
```

参赛性能证据采集：

```sh
FIELD_NAV_UART=1 FIELD_NAV_BAUD=115200 FIELD_NAV_RATE=90 FIELD_NAV_SENSOR_FPS=90 FIELD_NAV_TEST_SECONDS=60 /field_nav/scripts/run.sh
```

说明：`FIELD_NAV_SENSOR_FPS=90` 当前只作为日志目标帧率记录，程序不会单独重配传感器模式。是否满足“接近 90fps”必须以板端实际 `FPS_app`、传感器模式和 Aurora/串口日志为准。

### 8.4 诚实满足情况

当前项目已经具备参赛主链路和可验证输出，但仍不能仅凭本地文件声称“完全满足”。必须补齐以下现场证据后才能确认：

- A1 板端连续运行 60 秒不崩溃。
- 串口日志持续打印 `metrics`、`output tensor` 和导航状态。
- Aurora 中间画面能看到 OSD 测试框和 `valid=1` 时的导航线。
- UART/RDK 侧能收到导航帧。
- 普通光照、强光/开窗、暗光/关灯三种场景各运行 60 秒，`max_invalid_ms` 不应超过 1000ms；若超过，应如实记录并继续优化模型或后处理。
- 若 `FPS_app / 90` 不接近 1，应明确写“不满足接近 90fps 的高分性能项”，不能把 10Hz UART 输出或模型理论帧率当成 90fps 实测。
