# Project Notes for Future Agents

[保留] 元数据：本文件适用于 `D:\1.1.1.1.1` 的田间道路视觉导航项目。后续回答本项目问题或改代码时，先读本文件，再检查实际文件状态；本文件只记录可复用的项目事实、约束、入口、运行命令、数据格式、验证命令和环境坑点。

## [保留] 基本工作规则

- [保留] 回答本地项目问题时，先检查实际文件结构、入口文件、构建脚本和当前文件内容，再给运行命令。
- [保留] 后续在本项目开工前，必须先读取 Obsidian 知识库 `D:\obsidian\30_Projects\田间道路视觉导航` 中的内容，再结合 `AGENTS.md` 和实际文件状态开展回答、检查、计划或改动。
- [保留] 数据集问题要先统计文件数量、标注格式和标签类别，再判断能不能直接训练。
- [保留] 默认使用 PowerShell 命令，除非用户明确在 Linux/SDK 容器或板端 shell 中操作。
- [保留] 不要修改原始数据集文件；转换、清洗、训练产物放到 `field_nav_workspace` 或新建派生目录。
- [保留] 田间导航项目代码优先放在 `data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external`，尽量不改 SDK 原始源码。
- [保留] 用户强调过：不要修改现有头文件，尤其不要改 SDK 原有 `.h/.hpp`；如果必须改头文件，先说明原因并征求确认。
- [保留] 手动编辑文件使用 `apply_patch`，不要用 shell 重定向或脚本直接覆盖源码。
- [保留] 可能存在脏工作区和 Buildroot 生成文件；不要还原用户或构建系统已有改动。

## [保留] 关键路径

- [保留] 工作区根目录：`D:\1.1.1.1.1`
- [保留] SDK 根目录：`D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk`
- [保留] Buildroot external：`D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external`
- [保留] 板端 demo 源码：`field_nav_external\src\field_nav_demo`
- [保留] 板端模型：`field_nav_external\src\field_nav_demo\app_assets\models\navroad_640x480.m1model`
- [保留] 训练工作区：`D:\1.1.1.1.1\field_nav_workspace`
- [保留] 原始 LabelMe 数据集：`D:\1.1.1.1.1\智慧农业田垄采摘机器人道路识别农作物过道区域识别分割数据集labelme格式211张2类别\labelme_data`
- [保留] 最终烧录产物：`data\A1_SDK_SC132GS\smartsens_sdk\output\images\zImage.smartsens-m1-evb`
- [保留] Buildroot 旧缓存目录：`data\A1_SDK_SC132GS\smartsens_sdk\output\build\field_nav_demo`

## [保留] A1 开发板参数

- [保留] 芯片：Flyingchip A1，面向端侧视觉处理。
- [保留] CPU：单核 ARM Cortex-A7，最高约 1.2GHz。
- [保留] NPU：0.8TOPS@INT8。
- [保留] 内存：DDR3L 16bit 1Gb stacked。
- [保留] 存储：256Mb NOR Flash。
- [保留] 外设：SPI、I2C、UART、GPIO 等。
- [保留] 视频接口：2 x 4-lane MIPI CSI RX，1 x 4-lane MIPI CSI TX。
- [保留] ISP：支持双路 3MP 30fps HDR、单路 3MP 60fps HDR、单路 5MP 60fps RGB-IR、单路 8MP 30fps HDR。
- [保留] 电源：5V DC；工作温度：0~65C。
- [保留] 程序运行方式：编译生成 `zImage.smartsens-m1-evb`，烧录到板子运行。

## [保留] 数据集事实

- [保留] 数据集是 LabelMe polygon 分割数据。
- [保留] `labelme_data` 下已确认 `211` 张 `.jpg` 和 `211` 个 `.json`，同名配对完整。
- [保留] 标签类别：`sand_road`、`grassy_road`。
- [保留] 当前导航任务中两个类别都表示可通行区域；训练时通常合并为一个前景类 `road` / `road_area`。
- [保留] 数据集没有现成 mask，需要先把 LabelMe JSON polygon 转成二值 mask。
- [保留] LabelMe JSON 包含图片名、尺寸、标签名、polygon 点坐标等。
- [保留] 不要把 polygon 面标注直接当成导航线；正确流程是：图像 -> 分割模型 -> road mask -> 后处理提取中心线。
- [保留] 数据集版权声明含个人使用限制；公开发布或商业用途前要检查授权。

## [保留] 训练工作区和数据产物

- [保留] `field_nav_workspace` 只读原始数据集，写入派生数据、清洗副本、模型、报告。
- [保留] v1 脚本：`tools\prepare_labelme_dataset.py`、`tools\train_navroad.py`、`tools\evaluate_navroad.py`。
- [保留] v2 脚本：`tools\audit_labelme_dataset_v2.py`、`tools\prepare_labelme_dataset_v2.py`、`tools\train_navroad_v2.py`、`tools\evaluate_navroad_v2.py`、`tools\compare_onnx_navroad_v2.py`、`tools\prove_navroad_host.py`。
- [保留] v2 产物目录：`audit_v2`、`labelme_curated_v2`、`processed_v2_640x480`、`runs\navroad_v2`。
- [保留] 只允许人工修改 `field_nav_workspace\data\labelme_curated_v2` 里的副本，不要改原始 LabelMe 数据。
- [保留] `processed_v2_640x480` 已有 211 个 images、211 个 masks、211 个 previews；split 为 `train=147`、`val=32`、`test=32`。
- [保留] `processed_v2_640x480\class_map.json`：`background=0`、`road=1`。
- [保留] `runs\navroad_v2` 已有 `best.pt`、`last.pt`、`navroad_640x480.onnx`、`history.json`、`summary.json`、`host_proof`。
- [保留] `summary.json` 关键指标：`best_epoch=64`，`best_val.iou≈0.4438`，`mean_center_error_px≈54.11`，`mean_bottom_error_px≈59.96`。
- [保留] `host_proof\proof_metrics.json` 关键指标：test 样本 32，`mean_iou≈0.4992`，`valid_navline_samples=32`，`mean_line_error_px_original720≈86.92`，`mean_crop_bottom_error_px_original720≈100.03`。
- [保留] `data\audit_v2\audit_summary.json` 显示 211 个样本中 170 个 suspicious，主要包括 `low_resolution=89`、`fragmented_mask=94`、`many_vertices=46`。
- [保留] 当前模型质量可运行、可证明主机端链路，但不能视为最终高质量模型；后续优先清理可疑样本、增强数据、复查 crop 策略。

## [保留] 模型和转换

- [保留] 模型输入约定：灰度 `1x480x640`。
- [保留] 推荐输出：低分辨率 road 概率图，常见为 `1x120x160`。
- [保留] `120x160` 概率图不是原图；每个点表示对应区域属于可通行过道的概率，再用阈值转为二值 mask。
- [保留] 当前板端模型文件名约定为 `navroad_640x480.m1model`；真正要求是运行脚本和打包路径一致。
- [保留] 当前板端默认模型路径：`/field_nav/app_assets/models/navroad_640x480.m1model`。
- [保留] 用户板上确认过模型大小约 `616750` 字节；本地模型文件也位于 `field_nav_external\src\field_nav_demo\app_assets\models\navroad_640x480.m1model`。
- [保留] 训练导出 ONNX 后，需要使用 A1 工具链转换为 `.m1model`。
- [保留] A1 AI Tool 支持的 ONNX 算子有限；复杂后处理放 CPU 更稳。
- [保留] 推荐网络结构保持简单：Conv、Pool、BatchNorm、Add、Mul、Concat、Relu、LeakyRelu、nearest resize/upsample 等。
- [保留] 避免在 ONNX 中依赖 Softmax、Sub、Div、NMS、复杂 Transpose 等不确定支持的后处理。

## [保留] 板端应用 field_nav_demo

- [保留] 不覆盖原有人脸 demo；新增/维护 `field_nav_demo`。
- [保留] Buildroot external package：`field_nav_external\package\field_nav_demo`。
- [保留] `field_nav.hpp` 是当前板端 demo 头文件，用户要求不要随意修改。
- [保留] `navline_detector.cpp`：模型加载、推理输出解析、road mask 后处理、导航线拟合。
- [保留] `image_processor.cpp`：摄像头图像链路。
- [保留] `osd_overlay.cpp`：OSD 显示。
- [保留] `main.cpp`：参数、主循环、OSD、UART 输出、metrics、退出释放。
- [保留] `scripts\run.sh`：传入默认模型、LUT、UART 参数。
- [保留] `CMakeLists.txt` 复用人脸 demo 的 `osd-device.cpp`；该依赖缺失会导致 CMake 失败。

## [保留] 图像和坐标约定

- [保留] 传感器/原始尺寸常见为 `720x1280`。
- [保留] 当前板端处理思路：`720x1280 -> crop 720x540 offset_y=370 -> resize 640x480`。
- [保留] 模型输入：`640x480` 灰度图。
- [保留] 模型输出通常为 `120x160` 概率图，但代码应读取 runtime tensor 宽高，不要硬编码输出尺寸。
- [保留] 导航点最终映射回原画面坐标，用于 OSD 和 UART 输出。

## [保留] 导航线后处理算法

- [保留] 后处理入口：`NavLineDetector::DecodeOutputToLine(...)`。
- [保留] 流程：模型输出概率图 -> 阈值 `0.45` 二值 road mask -> 下方约 `65%` ROI -> 纵向形态学修补 -> 4 邻域 DFS 连通域 -> 小区域过滤 -> 主贯通域选择 -> 行带概率加权中心点 -> 最小二乘拟合 -> `NavLine`。
- [保留] 旧算法使用固定阈值、逐行找最高连续前景段、概率加权中心点和最小二乘直线；没有形态学修补、连通域过滤、贯通域匹配、行带中心点、历史帧兜底。
- [保留] 当前 TDM-LS 思路只改 `.cpp`，不改头文件。
- [保留] 纵向形态学核：`kMorphVerticalRadius=3`、`kMorphHorizontalRadius=0`；闭运算后保留原始前景，避免细道路被腐蚀误删。
- [保留] 小连通域过滤阈值：`kMinComponentArea=30`。
- [保留] 行带高度：`kBandHeight=4` 个 mask 像素。
- [保留] 直线拟合最少点数：`kMinValidPoints=6`。
- [保留] 拟合输出：`bottom_x`、`deviation_px`、`angle_deg`、`confidence`、`valid`。
- [保留] 成功日志 reason：`ok_tdm_ls`。
- [保留] 短暂失败时最多 2 帧使用上一帧导航线低置信度兜底，日志 reason：`fallback_last_valid`；连续失败后输出 `valid=0`。
- [保留] 当前实现未采用 DBSCAN、Hough、骨架化、完整 Otsu/YCrCb 颜色分割或 OpenCV 重型轮廓算法作为主流程。

## [保留] NPU 和 CPU 分工

- [保留] 板端模型前向推理明确走 A1 NPU：`NavLineDetector::Predict()` 中调用 `ssne_inference(model_id_, 1, &input_)`。
- [保留] `ssne_loadmodel()`、`ssne_initial()`、`ssne_getoutput()`、`ssne_release()` 属于 SSNE 运行时/模型管理接口；真正网络计算发生在 `ssne_inference()`。
- [保留] `RunAiPreprocessPipe(preprocess_, *img, input_)` 是 A1 SDK AI 预处理管线，是否硬件加速取决于 SDK 实现。
- [保留] 摄像头在线管线由 `ImageProcessor` 通过 `OnlineSetCrop()`、`OpenOnlinePipeline()`、`GetImageData()` 获取裁剪后的灰度图；这是 ISP/SDK 图像输入链路，不是 NPU 神经网络推理。
- [保留] 模型输出后的概率读取、阈值分割、形态学、连通域、主区域选择、中心点、最小二乘拟合和历史帧兜底走 CPU。
- [保留] `main.cpp` 的状态判定、UART 帧打包发送、OSD、60 秒 metrics、退出释放逻辑属于 CPU 侧业务控制或外设调用。
- [保留] RDK X5 端 `rdk_x5_nav_bridge.py` 是 CPU 脚本：解析 A1 导航帧、校验 checksum、计算线速度/角速度，并向下位机写控制帧。

## [保留] OSD 和 Aurora 调试

- [保留] OSD 应复用人脸 demo 已验证的 `OsdDevice` 链路，不要手写未验证的 OSD 初始化。
- [保留] 默认 LUT：`/field_nav/app_assets/shared_colorLUT.sscl`；备用 LUT：`/field_nav/app_assets/colorLUT.sscl`。
- [保留] 用户板上确认过 `shared_colorLUT.sscl` 约 98 字节，`colorLUT.sscl` 约 71 字节。
- [保留] 程序启动后应先画 3 秒固定测试框；固定框显示在 Aurora 中间摄像头画面，不在左侧串口文本区。
- [保留] Aurora 左侧 UART 窗口显示 Linux 启动日志和程序 printf 日志；中间 camera/device 画面显示摄像头图像和 OSD。
- [保留] 如果固定框可见但导航线不可见，优先看 `valid`、`components`、`points`、`reason` 日志。
- [保留] Aurora 的 A1 图像工具可用于导出板端保存的 tensor 图像；当前 `field_nav_demo` 已接入 `q/Q` 回车退出时保存 crop tensor。
- [保留] dump 默认路径：`/field_nav/field_nav_dbg_crop.bin`，调用 SDK `save_tensor(image, "/field_nav/field_nav_dbg_crop.bin")`。
- [保留] 只有前台运行且 stdin 是 TTY 时，Aurora 串口输入 `q/Q` 才能作用到当前进程；自启动后台运行时日志会提示 `stdin is not interactive`。

## [保留] 模型加载和释放

- [保留] `ssne_loadmodel()` 返回的 `model_id` 可能是 `0`，不能把 `model_id_ == 0` 当成失败。
- [保留] 正确做法：加载后调用 `ssne_get_model_input_num(model_id_)` 等 API 查询，返回值异常才算失败。
- [保留] 项目没有单独的 `ssne_unloadmodel(model_id)` 调用；退出或初始化失败时调用 `ssne_release()` 释放 SSNE 运行时资源。
- [保留] `NavLineDetector::Release()` 只释放导航模型相关输入/输出 tensor 和 AI 预处理管线：`release_tensor(output_)`、`release_tensor(input_)`、`ReleaseAIPreprocessPipe(preprocess_)`。
- [保留] 正常退出顺序：`overlay.Release()`、`nav_uart.Release()`、`detector.Release()`、`processor.Release()`，最后调用 `ssne_release()`。

## [保留] Buildroot 和构建

- [保留] 正式构建在 Linux SDK 容器中执行；Windows PowerShell 不能证明完整 Buildroot 编译通过。
- [保留] 构建命令：

```bash
cd /home/smartsens_flying_chip_a1_sdk/A1_SDK_SC132GS/smartsens_sdk
bash ./field_nav_external/scripts/build_field_nav.sh
```

- [保留] 构建脚本会执行：`build_dl.sh`、检查/解压 toolchain、检查/解压 package、检查/解压 kernel src、`make BR2_EXTERNAL=./smart_software:./field_nav_external field_nav_m1pro_defconfig`、`make ... field_nav_demo-dirclean`、`make -j$(nproc)`。
- [保留] `field_nav_demo-dirclean` 用于避免 Buildroot 使用 `output\build\field_nav_demo` 旧缓存。
- [保留] Windows 当前环境可能出现 WSL `E_ACCESSDENIED`、`/bin/bash` 不存在或 Docker daemon 未运行；此时不要判断源码编译失败，应回到 Linux/SDK 容器构建。
- [保留] `field_nav_demo.mk` 会安装 `/field_nav/field_nav_demo`、`/field_nav/scripts/run.sh`、`/field_nav/app_assets`，并复制 `shared_colorLUT.sscl` 和 `colorLUT.sscl`。
- [保留] `output\target\field_nav` 已实际包含 `field_nav_demo`、模型、`run.sh`、两个 LUT。
- [保留] `output\images` 已有 `rootfs.cpio`、`rootfs.cpio.gz`、`zImage.smartsens-m1-evb`；但未重新运行 Linux SDK 容器时不能声称本轮编译通过。

## [保留] 板端启动参数

- [保留] `run.sh` 是板端程序默认启动参数来源。
- [保留] `--model` 默认 `/field_nav/app_assets/models/navroad_640x480.m1model`。
- [保留] `--lut` 指定 OSD 颜色 LUT 文件路径。
- [保留] `--nav-uart` 控制 A1 侧导航 UART 输出开关/编号。
- [保留] `--nav-baud` 默认 `115200`。
- [保留] `--nav-rate` 默认 `10Hz`。
- [保留] `--sensor-fps` 只作为日志目标值，不单独重配传感器。
- [保留] `--osd-rate` 默认 `15Hz`；设置为 `0` 可关闭运行中 OSD 绘制，用于排查 OSD 是否拖慢 `FPS_app`。
- [保留] `--test-seconds` 固定运行时长，`>0` 时达到秒数后打印 final metrics 并退出。
- [保留] 参赛证据采集命令：

```sh
FIELD_NAV_UART=1 FIELD_NAV_BAUD=115200 FIELD_NAV_RATE=90 FIELD_NAV_SENSOR_FPS=90 FIELD_NAV_OSD_RATE=15 FIELD_NAV_TEST_SECONDS=60 /field_nav/scripts/run.sh
```

- [保留] `FIELD_NAV_SENSOR_FPS=90` 只把目标帧率写进日志，不能单独证明传感器已配置到 90fps。
- [保留] `FIELD_NAV_OSD_RATE=15` 只限制 OSD 刷新频率，不影响 NPU 每帧推理和 UART 90Hz 导航输出；若 `osd_ms` 高，可用 `FIELD_NAV_OSD_RATE=0` 复测。

## [保留] UART / GPIO / RDK X5 链路

- [保留] 当前项目与地瓜派 RDK X5 联动是 UART 串口链路，不是网络、ROS 或文件共享链路。
- [保留] A1 端由 `field_nav_demo` 读取摄像头、执行模型推理、提取 `NavLine`，再从 `GPIO_PIN_0` 复用的 `UART_TX0` 发出 16 字节导航帧。
- [保留] GPIO 可用性按赛题区分；GPIO0 默认可复用为 UART TX0，GPIO1 默认可复用为 UART RX0 但已占用，不能随意改。
- [保留] A1 侧推荐只用 UART TX 输出导航结果，不直接控制车轮。
- [保留] A1 UART 电平是 1.8V，RDK X5 40Pin UART 是 3.3V；A1 -> RDK 必须加 1.8V 到 3.3V 电平转换。
- [保留] 推荐硬件链路：A1 P4-15 / A1_D0_UART0TX -> 电平转换 -> RDK X5 40Pin Pin10 / UART_RXD；RDK X5 40Pin Pin8 / UART_TXD -> 下位机 UART_RX；A1、RDK X5、下位机必须共地。
- [保留] 不要用 RDK X5 Micro-USB 调试串口做导航数据通道。
- [保留] RDK X5 侧脚本：`field_nav_external\scripts\rdk_x5_nav_bridge.py`，无第三方依赖，使用 Linux `termios`。
- [保留] RDK X5 串口检查：

```bash
ls -l /dev/ttyS* /dev/ttyUSB* /dev/ttyACM*
dmesg | grep -i tty
```

- [保留] RDK X5 运行示例：

```bash
python3 rdk_x5_nav_bridge.py --port /dev/ttyS1 --baud 115200
```

## [保留] 导航帧和控制帧协议

- [保留] A1 导航帧：16 字节，帧头 `A5 5A`，版本字节 `0x01`，valid 标志，seq，`deviation_px * 10`，`angle_deg * 100`，confidence 百分比，导航点数量，bottom_x，status，前 15 字节累加校验。
- [保留] RDK 控制帧：16 字节，帧头 `B5 5B`，版本字节 `0x01`，enable/valid 标志，seq，线速度 mm/s，角速度 mrad/s，`deviation_px * 10`，mode，前 15 字节累加校验。
- [保留] A1 每约 100ms 发送一帧导航数据；字段包括 `valid`、`deviation_px`、`angle_deg`、`confidence`、`bottom_x` 等。
- [保留] RDK X5 接收后计算线速度和角速度，再发给下位机。
- [保留] 下位机只执行 RDK 控制指令，不直接解析原始图像或模型输出。
- [保留] 下位机超过 500ms 未收到有效控制帧时应停车。
- [保留] 若以后需要下位机回传编码器、电池、电机状态，升级为双串口或 USB 转串口链路。

## [保留] 直接相关文件清单

- [保留] `field_nav_external\src\field_nav_demo\src\main.cpp`：定义 `NavUartPublisher`，初始化 GPIO/UART，配置 `GPIO_PIN_0=UART_TX0`，按 `--nav-baud`、`--nav-rate` 发送导航帧；主循环调用 `nav_uart.Publish(status, line)`。
- [保留] `field_nav_external\scripts\rdk_x5_nav_bridge.py`：RDK X5 桥接程序；解析 A1 导航帧，校验帧头和 checksum，计算控制量，并向同一 UART 写出下位机控制帧。
- [保留] `field_nav_external\src\field_nav_demo\include\field_nav.hpp`：定义 `NavLine`、`NavPoint`、坐标和裁剪常量；不要随意修改。
- [保留] `field_nav_external\src\field_nav_demo\src\navline_detector.cpp`：模型推理后处理，生成 `NavLine`。
- [保留] `field_nav_external\src\field_nav_demo\scripts\run.sh`：读取 `FIELD_NAV_UART`、`FIELD_NAV_BAUD`、`FIELD_NAV_RATE`、`FIELD_NAV_SENSOR_FPS`、`FIELD_NAV_OSD_RATE`、`FIELD_NAV_TEST_SECONDS`。
- [保留] `field_nav_external\board\m1pro\rootfs_overlay\usr\smartsoc\smartsoc_start.sh`：板端自启动脚本，加载 `gpio_kmod.ko`、`uart_kmod.ko` 等模块后执行 `/field_nav/scripts/run.sh`。
- [保留] `field_nav_external\src\field_nav_demo\CMakeLists.txt`：编译 `field_nav_demo` 并链接 GPIO/UART/SSNE/OSD 等 M1 SDK 库。
- [保留] `field_nav_external\src\field_nav_demo\cmake_config\Paths.cmake`：声明 `libgpio.so` 和 `libuart.so` 路径。
- [保留] `field_nav_external\package\field_nav_demo\field_nav_demo.mk`：安装 demo、run.sh、模型和 LUT 到目标根文件系统 `/field_nav`。
- [保留] `field_nav_external\configs\field_nav_m1pro_defconfig`：启用 `BR2_PACKAGE_FIELD_NAV_DEMO=y`，叠加 `field_nav_external` rootfs overlay。
- [保留] `field_nav_external\package\field_nav_demo\Config.in`：定义 `field_nav_demo` 包和 `/field_nav` 内模型相对路径选项。
- [保留] `field_nav_external\scripts\build_field_nav.sh`：Linux SDK 容器构建脚本，生成包含导航 demo、UART 模块加载和资源的 `zImage.smartsens-m1-evb`。
- [保留] `field_nav_external\README.md`：项目说明文档，记录构建入口、板端环境变量、UART 接线、RDK 桥接和证据采集命令。

## [保留] 日志字段和诊断口径

- [保留] `output tensor width=... height=... dtype=...`：模型输出尺寸和类型。
- [保留] `output stats raw=[min,max,mean] prob=[min,max,mean]`：模型输出原始值范围和 road 概率范围；`threshold=0.45` 是二值化阈值。
- [保留] `components=0 failure=no_components`：没有找到满足面积阈值的道路连通域。
- [保留] `main_area` 很小：主连通域面积不足，可能是画面不对、模型输出弱或阈值过高。
- [保留] `band_points < 6`：行带中心点不足，直线拟合不会生效。
- [保留] `reason=ok_tdm_ls`：TDM-LS 后处理成功。
- [保留] `reason=fallback_last_valid`：当前帧失败，短时间沿用上一帧导航线。
- [保留] `valid=0`：当前没有可靠导航线，下游应停车或保持安全状态。
- [保留] `nav UART frame sent: valid=... status=...`：UART 帧发送成功；`valid=0` 表示该帧无有效导航线。
- [保留] `metrics tag=heartbeat window=60s`：60 秒滑动窗口统计。
- [保留] `FPS_app`、`fps_ratio`、`P95_frame_ms`、`max_frame_ms`：判断应用帧率和性能。
- [保留] `image_ms`：取图/ISP pipeline 耗时；P95 接近 33ms 时说明实际链路可能接近 30fps。
- [保留] `predict_ms`：AI 预处理、NPU 推理、取输出和后处理整体耗时；异常时继续看 `preprocess_ms`、`inference_ms`、`getoutput_ms`、`postprocess_ms`。
- [保留] `uart_ms`、`osd_ms`：输出侧耗时。
- [保留] `valid_nav`、`no_line`、`predict_fail`、`image_fail`：有效导航、无导航线、推理失败、取图失败计数。
- [保留] `uart_sent`、`uart_fail`：导航 UART 成功发送和失败计数。
- [保留] `max_invalid_ms`：当前窗口最长连续无效导航时间；鲁棒性测试中超过 `1000ms` 要如实记录并优化。

## [保留] 常见诊断命令

- [保留] 板端检查模型和 LUT：

```sh
ls -l /field_nav/app_assets/models/
wc -c /field_nav/app_assets/models/navroad_640x480.m1model
ls -l /field_nav/app_assets/shared_colorLUT.sscl
ls -l /field_nav/app_assets/colorLUT.sscl
```

- [保留] 查看导航资源：

```sh
ls -R /field_nav
cat /field_nav/scripts/run.sh
```

- [保留] RDK X5 串口检查：

```bash
ls -l /dev/ttyS* /dev/ttyUSB* /dev/ttyACM*
dmesg | grep -i tty
```

## [保留] 鲁棒性和参赛证据边界

- [保留] 鲁棒性应从算法容错、运行稳定、通信安全和现场证据四个层面证明。
- [保留] 算法容错依据：`components`、`main_area`、`band_points`、`points`、`fallback`、`valid`、`failure`、`reason`。
- [保留] 运行稳定依据：`valid_nav`、`no_line`、`predict_fail`、`image_fail`、`uart_sent`、`uart_fail`、`max_invalid_ms`、`P95_frame_ms`、`image_ms`、`predict_ms`、`uart_ms`、`osd_ms`。
- [保留] 通信安全依据：A1 发送 `A5 5A` 导航帧，RDK 校验后输出 `B5 5B` 控制帧；`uart_sent` 应持续增长，`uart_fail` 应接近 0。
- [保留] RDK 端应结合 `valid`、`status==0`、置信度阈值和超时判断；无有效导航、低置信度或超时时输出停车/禁用控制帧。
- [保留] 普通光照、强光/开窗、暗光/关灯至少各跑 60 秒，保存 Aurora 串口日志、摄像头画面/OSD 录像、RDK 接收日志和下位机停车超时验证。
- [保留] 无板端 60 秒日志时，只能说项目具备主链路，不能说完全满足要求。
- [保留] 若 `FPS_app / 90` 不接近 `1.0`，不能声称满足接近 90fps 的高分性能项。

## [保留] GitHub 和打包边界

- [保留] 根目录 `D:\1.1.1.1.1` 当前是 Git 仓库；远程仓库曾配置为 `https://github.com/Bikini-Bottom-nuc/Rage.git`。
- [保留] `data\A1_SDK_SC132GS` 本身是嵌套 Git 仓库，远程为 `https://git.smartsenstech.ai/Smartsens/A1_SDK_SC132GS.git`；其中 `smartsens_sdk\field_nav_external` 是自研目录。
- [保留] `.gitignore` 按干净源码上传策略排除 Aurora、压缩包、原始数据集、`field_nav_workspace\data`、`field_nav_workspace\runs`、SDK 主体、SDK cache/dl/output、Python cache、日志、训练 checkpoint 和 ONNX。
- [保留] `.gitignore` 明确保留 `data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external`。
- [保留] `.gitattributes` 用于保持 shell/Python/C++/CMake/Markdown/Buildroot 配置文件为 LF，`.bat` 为 CRLF，图片和模型为 binary。
- [保留] 不建议直接压缩整个 `D:\1.1.1.1.1` 发送；根目录包含 Aurora 工具、完整 SDK、大压缩包、原始数据集、Buildroot 输出和训练产物。
- [保留] 发送代码时优先打包 Git 跟踪文件；推荐内容：根目录 `.gitignore`、`.gitattributes`、`README.md`、`AGENTS.md`、`docker_create_sdk_builder.bat`、`field_nav_external`、`field_nav_workspace\tools`、`field_nav_workspace\docs`、`field_nav_workspace\reports`、板端小模型 `navroad_640x480.m1model`。
- [保留] 不要打包：`.git`、Aurora 程序、完整 SDK 主体、SDK `cache/dl/output`、原始数据集、`field_nav_workspace\data`、`field_nav_workspace\runs`、`__pycache__`、训练 checkpoint、ONNX、大压缩包和临时日志。
- [保留] 如果接收方要完整复现 Buildroot 构建，还需要另行获取 A1 SDK、工具链、A1 AI Tool、原始数据集和 Linux SDK 容器环境。

## [保留] 代码风格和实现偏好

- [保留] 多借鉴原有人脸 demo，尤其是 OSD、模型加载、库链接、run.sh 风格。
- [保留] 新逻辑尽量放在 `.cpp` 内部匿名命名空间，减少头文件和接口变化。
- [保留] 板端 CPU 是 Cortex-A7；后处理要轻量，优先处理低分辨率 mask。
- [保留] 不要引入 OpenCV 等重依赖到板端 demo，除非 SDK 已明确支持且用户同意。
- [保留] C++ 目标是 C++11，避免使用 C++17 特性。
- [保留] 日志要能直接在串口定位问题，但不要每帧打印大量内容；保持间隔诊断。

## [保留] 验证要求

- [保留] 完成代码改动后，至少检查是否改了 `.h/.hpp`。
- [保留] 确认实际修改目标是 `field_nav_external` 源文件，而不是 Buildroot 缓存目录。
- [保留] Linux SDK 容器构建要确认执行了 `field_nav_demo-dirclean`。
- [保留] 串口应打印模型路径、LUT 路径、output tensor、导航后处理统计。
- [保留] OSD 固定测试框应先出现；`valid=1` 时导航线应显示。
- [保留] UART/RDK 应收到导航帧。
- [保留] 如果本机无法运行 Buildroot，不要声称编译通过；明确说明需要在 Linux SDK 容器中验证。

## [保留] 本次确认：RDK X5 登录、串口和下位机控制边界

- [保留] 本机 `以太网 2` 连接 RDK X5；Windows 侧 IP 为 `192.168.127.100`，RDK X5 侧 `eth0` 为 `192.168.127.10/24`。
- [保留] RDK X5 已确认可通过 SSH 访问，登录用户为 `sunrise`；不要把密码写入项目文件、笔记或提交记录。
- [保留] RDK X5 板卡型号：`D-Robotics RDK X5 V1.0`；系统：`Ubuntu 22.04.5 LTS`；内核：`Linux 6.1.83 aarch64`；Python：`3.10.12`。
- [保留] `sunrise` 用户属于 `dialout`、`sudo`、`gpio` 等组，具备访问常规串口设备的基础权限。
- [保留] RDK X5 串口设备已确认有 `/dev/ttyS0` 到 `/dev/ttyS7`；`/dev/ttyS0` 被 `serial-getty@ttyS0.service` 占用，像系统调试串口，不建议作为导航控制串口。
- [保留] `/dev/ttyS1` 到 `/dev/ttyS7` 当前未发现进程占用，且权限为 `root:dialout` 可读写；优先用 `/dev/ttyS1`、`115200 8N1` 作为 RDK X5 与 A1/下位机串口联调起点。
- [保留] RDK X5 使用 A1 导航帧时，不是从摄像头直接测真实线速度/角速度；摄像头/模型只提供道路中心线、横向偏差 `deviation_px`、航向角 `angle_deg`、置信度和有效标志。
- [保留] `rdk_x5_nav_bridge.py` 中的 `linear_v_mm_s`、`angular_w_mrad_s` 是 RDK 根据导航误差计算出的目标线速度和目标角速度，不是相机测得的真实速度。
- [保留] 当前 RDK 控制律是简单 P 控制：`angular = kp_dev * deviation_px + kp_ang * angle_deg`，`linear` 为预设巡航速度；默认安全参数包括 `linear=150mm/s`、`kp-dev=-2.0`、`kp-ang=-20.0`、`max-angular=800mrad/s`、`min-confidence=30`、`timeout=0.3s`。
- [保留] 调参建议从低速开始，例如 `--linear 120 --kp-dev -1.5 --kp-ang -15 --max-angular 600`；偏了但转不够则增大 `kp-dev` 绝对值，车头修正慢则增大 `kp-ang` 绝对值，左右摆动则减小增益或降低线速度。
- [保留] 下位机已有编码电机但无陀螺仪也可以闭环控制；差速底盘可由编码器估算 `v=(v_left+v_right)/2`、`w=(v_right-v_left)/wheel_base`，但打滑、松软地面和急转时角速度估计会漂。
- [保留] 精确控制分工应为：A1 摄像头负责“往哪走”，RDK X5 负责根据 `deviation_px/angle_deg` 生成目标 `v/w`，下位机用编码器 PID 闭环执行左右轮速度。
- [保留] 若下位机接收左右轮目标速度，可由差速运动学转换：`v_left_target = v_target - w_target * wheel_base / 2`，`v_right_target = v_target + w_target * wheel_base / 2`。
- [保留] 下位机必须做安全兜底：只接受 `B5 5B` 控制帧、校验 checksum、`enable=1` 且 `valid_nav=1` 才运动，`mode=2` 或超过约 `500ms` 未收到有效控制帧时停车。
- [保留] 继续完善 RDK/下位机控制前，需要用户提供底盘类型、左右轮中心距 `wheel_base`、轮径、编码器 PPR/CPR、减速比、下位机当前串口协议、最大安全线速度和最大安全角速度。
