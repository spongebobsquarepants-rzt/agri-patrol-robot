# D:\1.1.1.1.1 项目功能和优势总结报告

生成时间：2026-05-05  
方式：6 个只读子代理并行扫描，主控合并；未修改原始数据集，未修改 `.h/.hpp`，未还原已有改动。

## 一、总体结论

`D:\1.1.1.1.1` 当前不是单一脚本项目，而是一个完整的田间导航本地工程，包含：

- PC 侧训练与评估工作区：`field_nav_workspace`
- 原始 LabelMe 分割数据集：`智慧农业田垄采摘机器人道路识别农作物过道区域识别分割数据集labelme格式211张2类别`
- A1 SDK / Buildroot 工程：`data\A1_SDK_SC132GS\smartsens_sdk`
- 新增板端导航 external：`smartsens_sdk\field_nav_external`
- A1 板端 demo：`field_nav_external\src\field_nav_demo`
- RDK X5 串口桥接脚本：`field_nav_external\scripts\rdk_x5_nav_bridge.py`
- Aurora 烧录和观察工具：`Aurora-2.0.0-ciciec.14`

项目主链路已经具备：LabelMe polygon 数据转换为 road mask，训练轻量分割模型，导出 ONNX 和板端 `.m1model`，A1 板端读取摄像头并推理，后处理提取导航线，通过 UART 发给 RDK X5，RDK 再输出下位机控制帧。

当前仍不能直接声称“完全上板达标”：扫描没有找到 Aurora 中的 `field_nav`、`metrics tag=`、`uart_sent`、`FPS_app` 等板端 60 秒实跑日志。现阶段更准确的表述是“工程主链路和打包产物已具备，缺少板端现场运行证据闭环”。

## 二、项目结构和入口

根目录包含 4 个目录和 3 个文件：

- `Aurora-2.0.0-ciciec.14`
- `data`
- `field_nav_workspace`
- 原始 LabelMe 数据集目录
- `a1-sdk-builder-latest.tar`
- `AGENTS.md`
- `docker_create_sdk_builder.bat`

关键入口：

- 训练入口：`field_nav_workspace\tools\train_navroad_v2.py`
- 数据准备入口：`field_nav_workspace\tools\prepare_labelme_dataset_v2.py`
- 评估入口：`field_nav_workspace\tools\evaluate_navroad_v2.py`
- 主机证明入口：`field_nav_workspace\tools\prove_navroad_host.py`
- SDK 构建入口：`data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\scripts\build_field_nav.sh`
- 板端运行入口：`field_nav_external\src\field_nav_demo\scripts\run.sh`
- 板端自启动入口：`field_nav_external\board\m1pro\rootfs_overlay\usr\smartsoc\smartsoc_start.sh`
- RDK 桥接入口：`field_nav_external\scripts\rdk_x5_nav_bridge.py`

优势：

- 新增导航功能集中放在 `field_nav_external`，没有覆盖原 SDK 主树的人脸 demo。
- Buildroot external 结构清晰，`board`、`configs`、`package`、`scripts`、`src` 分层明确。
- `AGENTS.md` 已存在，记录了本项目约束、关键路径、构建、UART/RDK、OSD 和验证规则。

风险：

- 根目录不是 git 仓库；本轮 `git status --short` 在根目录返回 `fatal: not a git repository`。
- `smartsens_sdk\output\build\field_nav_demo` 是 Buildroot 缓存，只能作为参考，判断源码必须看 `field_nav_external\src\field_nav_demo`。

## 三、数据集能力

扫描路径：

- `D:\1.1.1.1.1\智慧农业田垄采摘机器人道路识别农作物过道区域识别分割数据集labelme格式211张2类别`
- `...\labelme_data`

数量和格式：

- `labelme_data` 总文件数：422
- `.jpg`：211
- `.json`：211
- 同名配对：211 对
- 缺图或缺 JSON：0
- 其他文件：0
- 根目录另有 `版权声明.txt`
- 标注格式：LabelMe JSON，`version=5.5.0`
- shape 类型：全部为 `polygon`
- polygon 总数：1033
- `sand_road`：836 个 polygon，出现在 186 个 JSON
- `grassy_road`：197 个 polygon，出现在 52 个 JSON
- 同时含两个标签的 JSON：27
- 仅 `sand_road`：159
- 仅 `grassy_road`：25

功能判断：

这个数据集适合作为田间道路/过道语义分割训练源数据，但不能直接喂给常规分割模型训练。当前只有 LabelMe polygon JSON，没有现成 mask、COCO 或 YOLO-seg 格式。正确流程是：

`LabelMe polygon -> 二值 road mask -> 分割模型训练 -> 模型输出 road mask -> 后处理提取中心线/偏移/角度`

优势：

- 图片和 JSON 完整配对。
- 标签名干净，只有 `sand_road` 和 `grassy_road`。
- 全部是 polygon 面标注，适合转换为语义分割 mask。
- 覆盖多种分辨率和视角，有一定泛化价值。

风险：

- 数据量只有 211 张，偏小。
- 类别不均衡明显，`sand_road` polygon 数量约为 `grassy_road` 的 4.2 倍。
- 图片分辨率和宽高比不统一，训练前必须有统一 resize/crop 策略。
- polygon 是道路区域，不是导航线，不能把 polygon 直接当中心线。
- `版权声明.txt` 含个人使用限制，公开发布或商业用途需另行确认授权。

## 四、训练和模型

训练工作区：`D:\1.1.1.1.1\field_nav_workspace`

实际训练脚本：9 个

- `audit_labelme_dataset_v2.py`
- `compare_onnx_navroad_v2.py`
- `evaluate_navroad.py`
- `evaluate_navroad_v2.py`
- `prepare_labelme_dataset.py`
- `prepare_labelme_dataset_v2.py`
- `prove_navroad_host.py`
- `train_navroad.py`
- `train_navroad_v2.py`

v2 数据产物：

- `processed_v2_640x480\images`：211 个 `.png`
- `processed_v2_640x480\masks`：211 个 `.png`
- `processed_v2_640x480\previews`：211 个 `.jpg`
- split：`train=147`、`val=32`、`test=32`
- `class_map.json`：`background=0`，`road=1`

模型产物：

- `runs\navroad_v2\best.pt`
- `runs\navroad_v2\last.pt`
- `runs\navroad_v2\navroad_640x480.onnx`
- `field_nav_external\src\field_nav_demo\app_assets\models\navroad_640x480.m1model`
- 板端 `.m1model` 大小：616750 字节

训练指标：

- `best_epoch=64`
- `best_val.iou=0.4438094389`
- `best_val.mean_center_error_px=54.1087`
- `best_val.mean_bottom_error_px=59.9630`
- `best_val.invalid_centerline_samples=0`
- host proof `test mean_iou=0.4992480655`
- host proof `valid_navline_samples=32`，`invalid_navline_samples=0`
- host proof `mean_line_error_px_original720=86.9214`
- host proof `mean_crop_bottom_error_px_original720=100.0255`

功能判断：

训练链路已经贯通，不是只有脚本没有结果。v2 流程已经完成数据转换、训练、ONNX 导出、主机端证明和板端模型放置。

优势：

- 数据、训练、评估、ONNX、host proof、板端模型都有实际产物。
- 两个道路标签合并成单一 `road` 前景，贴合当前导航任务。
- 模型输入约定为灰度 `1x480x640`，输出低分辨率 road logits/probability，适合 A1 端轻量部署。
- ONNX 导出使用保守结构，倾向 Conv/BN/ReLU/Pool/Concat 等 A1 更可能支持的算子。

风险：

- 当前精度只能算“可运行、可验证”，不能算最终高质量模型。
- `val IoU` 约 0.444，host proof `mean_iou` 约 0.499，分割质量一般。
- 导航线误差偏大，原 720 坐标下平均线误差约 86.9 px。
- `audit_v2` 显示 211 个样本中 170 个被标记为 suspicious，常见原因包括 `low_resolution=89`、`fragmented_mask=94`、`many_vertices=46`。
- `train_stdout.log` 和 `train_stderr.log` 为 0 字节，训练过程日志留痕不足。
- `compare_onnx_navroad_v2.py` 是否实际跑通过，本轮未完成确认。

## 五、A1 板端 demo 功能

扫描路径：`data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\src\field_nav_demo`

数量：

- `.cpp`：4 个
- `.hpp`：1 个，只读未改
- `scripts\run.sh`：1 个
- `CMakeLists.txt`：1 个
- `cmake_config\Paths.cmake`：1 个
- `app_assets\models\navroad_640x480.m1model`：1 个

功能链路：

`摄像头在线 pipeline -> crop/resize/灰度输入 -> SSNE/NPU 推理 -> 输出 tensor 动态解析 -> TDM-LS 后处理提导航线 -> OSD 绘制 -> UART_TX0 发布导航帧`

关键实现：

- `image_processor.cpp`：配置 `OnlineSetCrop`、`OnlineSetOutputImage`、`OpenOnlinePipeline`
- `navline_detector.cpp`：模型加载、推理、输出解析、阈值、形态学修补、连通域、行带中心点、最小二乘拟合和 fallback
- `osd_overlay.cpp`：复用人脸 demo 的 `OsdDevice` 链路
- `main.cpp`：参数解析、主循环、metrics、OSD、UART 发布
- `run.sh`：读取 `FIELD_NAV_*` 环境变量并传入板端程序

优势：

- 板端应用不是空壳，摄像头、模型、后处理、OSD、UART 和 metrics 都已接入。
- `ssne_loadmodel()` 后通过 `ssne_get_model_input_num()` 判断模型是否可用，没有把 `model_id == 0` 误判为失败。
- 后处理运行在低分辨率输出 mask 上，符合 Cortex-A7 轻量 CPU 的约束。
- `output tensor width/height/dtype`、`prob`、`components`、`main_area`、`band_points`、`reason=ok_tdm_ls` 等日志有助于板端定位问题。
- `main.cpp` 有 60 秒窗口 metrics，可记录 `FPS_app`、`image_ms`、`predict_ms`、`uart_ms`、`osd_ms`、`uart_sent`、`uart_fail`、`max_invalid_ms`。

风险：

- `field_nav_demo\app_assets` 本身只看到模型，没有 LUT；最终 LUT 依赖 Buildroot package 从人脸 demo assets 复制。
- `CMakeLists.txt` 依赖 `FIELD_NAV_FACE_DEMO_ROOT`，如果人脸 demo 的 `osd-device.cpp` 不存在会构建失败。
- `--sensor-fps` 只进入日志目标值，没有扫描到单独重配传感器帧率的逻辑。
- `ImageProcessor::Initialize()` 主要检查 `OpenOnlinePipeline()`，对前面 crop/output 设置返回值显性检查不足。
- OSD 初始化有约 3 秒固定测试框等待，对调试有用，但会增加启动时间。

## 六、Buildroot 和打包

扫描路径：

- `field_nav_external\package`
- `field_nav_external\configs`
- `field_nav_external\board`
- `field_nav_external\scripts`
- `output\images`
- `output\target\field_nav`
- `output\build\field_nav_demo`

数量和产物：

- Buildroot `.mk`：2 个
- `Config.in`：2 个
- defconfig：1 个
- rootfs overlay 自启动脚本：1 个
- external scripts：2 个
- runtime `run.sh`：1 个
- `output\images`：3 个文件，共 16547964 字节
- `zImage.smartsens-m1-evb`：5920184 字节，时间 2026-05-05 03:15:02
- `rootfs.cpio`：7467520 字节
- `rootfs.cpio.gz`：3160260 字节
- `output\target\field_nav\field_nav_demo`：58768 字节
- `output\target\field_nav\app_assets\models\navroad_640x480.m1model`：616750 字节
- `output\target\field_nav\app_assets\shared_colorLUT.sscl`：98 字节
- `output\target\field_nav\app_assets\colorLUT.sscl`：71 字节
- `output\target\field_nav\scripts\run.sh`：1345 字节

功能判断：

Buildroot external 已完整接入。`field_nav_m1pro_defconfig` 启用 `BR2_PACKAGE_FIELD_NAV_DEMO=y`，叠加 field_nav rootfs overlay；`field_nav_demo.mk` 安装 demo、run.sh、模型和 LUT；`build_field_nav.sh` 执行 defconfig、`field_nav_demo-dirclean` 和完整 `make`。

优势：

- package、defconfig、overlay、脚本闭环清楚。
- 构建脚本显式执行 `field_nav_demo-dirclean`，能降低旧缓存误用风险。
- target rootfs 已实际包含 demo、模型、LUT 和启动脚本。
- `run.sh` 会检查模型和 LUT，缺失时给出明确错误。

风险：

- 本轮没有运行 Linux SDK 容器构建，不能声称“本轮编译通过”。
- `build_field_nav.sh` 在模型缺失时只 warning，镜像仍可能生成，但板端 `run.sh` 会退出。
- overlay 自启动脚本容错有限，关键资源缺失会导致启动链路中断。

## 七、UART / RDK / 上板验证

核心文件：

- A1 端：`field_nav_demo\src\main.cpp`
- RDK 端：`field_nav_external\scripts\rdk_x5_nav_bridge.py`
- 板端启动：`field_nav_demo\scripts\run.sh`
- 自启动：`board\m1pro\rootfs_overlay\usr\smartsoc\smartsoc_start.sh`
- 文档：`field_nav_external\README.md`

A1 导航帧：

- 帧长：16 字节
- 帧头：`A5 5A`
- 版本：`0x01`
- 字段：valid、seq、`deviation_px * 10`、`angle_deg * 100`、confidence、point_count、bottom_x、status、checksum
- 发送口：`GPIO_PIN_0=UART_TX0`
- 默认：115200 baud，10 Hz

RDK 控制帧：

- 帧长：16 字节
- 帧头：`B5 5B`
- 字段：enable/valid、seq、线速度 mm/s、角速度 mrad/s、`deviation_px * 10`、mode、checksum
- 脚本使用 Linux `termios`，无第三方依赖

硬件约束：

- A1 UART 电平是 1.8V
- RDK X5 40Pin UART 是 3.3V
- A1 到 RDK 必须加 1.8V 到 3.3V 电平转换
- A1、RDK X5、下位机必须共地
- 示例 RDK 设备 `/dev/ttyS1` 需要现场确认

验证状态：

- 代码链路判断为“主链路已具备”。
- 本地有 host proof，能证明主机端模型/后处理可输出导航线。
- 未找到 Aurora 板端 `field_nav` metrics 日志，不能证明 UART 实际发出、RDK 实际收到、下位机实际收控，也不能证明 90fps 达标。

优势：

- 协议固定 16 字节，便于下位机解析、串口抓包和示波验证。
- RDK 脚本部署成本低，无第三方依赖。
- 板端 metrics 字段完整，适合参赛证据采集。

风险：

- `FIELD_NAV_SENSOR_FPS=90` 只是记录目标值，不等于实际配置传感器到 90fps。
- 90fps 判断必须看板端 60 秒 `FPS_app` 和真实传感器模式。
- host proof 不是 `.m1model` 上板证明，也不是 UART/RDK 实物联调证明。

## 八、主要优势总结

- 工程闭环完整：数据、训练、模型、板端 demo、打包、UART/RDK 桥接都有实际文件和产物。
- 新增功能隔离好：`field_nav_external` 不覆盖原 SDK 主源码，降低回归风险。
- 训练链路可复现：v2 脚本覆盖审计、转换、训练、评估、ONNX 对比和主机证明。
- 板端实现贴合硬件：轻量模型、低分辨率 mask 后处理、C++11、无 OpenCV 重依赖。
- 诊断信息强：模型输出、后处理状态、帧率、分阶段耗时、UART 成败都有日志字段。
- 打包证据强：target rootfs 已看到 demo、模型、LUT、run.sh，最终 `zImage.smartsens-m1-evb` 已存在。
- RDK 联动简单：UART 固定帧，RDK 脚本无三方依赖，控制帧协议清楚。

## 九、当前最重要的风险和下一步验证

1. 上板证据不足  
   需要在 Aurora 串口日志中保存至少 60 秒 `metrics tag=heartbeat/final`、`output tensor`、`valid`、`nav UART frame sent`、`uart_sent`。

2. 90fps 不能凭环境变量证明  
   `FIELD_NAV_SENSOR_FPS=90` 只写入日志目标值。必须看 `FPS_app / target_sensor_fps`，以及 `image_ms` 是否说明传感器/ISP 仍停在约 30fps。

3. 模型质量仍需提升  
   当前 `val IoU` 和 host proof 指标偏一般，导航线平均误差偏大。优先清理 suspicious 样本、增强数据、复查 crop 策略和弱分割场景。

4. Buildroot 构建仍需在 Linux SDK 容器复核  
   本轮只读扫描看到已有镜像和 target rootfs，但没有重新编译。后续验证应回到 Linux SDK 容器执行：

```bash
cd /home/smartsens_flying_chip_a1_sdk/A1_SDK_SC132GS/smartsens_sdk
bash ./field_nav_external/scripts/build_field_nav.sh
```

5. UART 硬件必须按电平约束接线  
   A1 1.8V TX 不能直连 RDK 3.3V RX，必须加电平转换并共地。

## 十、证据文件清单

- `D:\1.1.1.1.1\AGENTS.md`
- `D:\1.1.1.1.1\field_nav_workspace\README.md`
- `D:\1.1.1.1.1\field_nav_workspace\docs\model_contract.md`
- `D:\1.1.1.1.1\field_nav_workspace\data\processed_v2_640x480\class_map.json`
- `D:\1.1.1.1.1\field_nav_workspace\data\processed_v2_640x480\split_stats.json`
- `D:\1.1.1.1.1\field_nav_workspace\data\audit_v2\audit_summary.json`
- `D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\summary.json`
- `D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\proof_metrics.json`
- `D:\1.1.1.1.1\field_nav_workspace\runs\navroad_v2\host_proof\host_proof_report_zh.md`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\README.md`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\scripts\build_field_nav.sh`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\scripts\rdk_x5_nav_bridge.py`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\src\field_nav_demo\src\main.cpp`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\src\field_nav_demo\src\navline_detector.cpp`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\package\field_nav_demo\field_nav_demo.mk`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\field_nav_external\configs\field_nav_m1pro_defconfig`
- `D:\1.1.1.1.1\data\A1_SDK_SC132GS\smartsens_sdk\output\images\zImage.smartsens-m1-evb`
