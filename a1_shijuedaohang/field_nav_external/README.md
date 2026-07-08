# 田间导航 Buildroot 扩展目录

本目录是田间导航项目的 Buildroot 外部扩展目录。它新增 `field_nav_demo`
板端目标程序，并保留 SDK 原有人脸检测 demo 源码树，不覆盖原始示例。

## 目录作用

- `configs/field_nav_m1pro_defconfig`：田间导航镜像的 Buildroot 配置。
- `package/field_nav_demo/`：`field_nav_demo` 的 Buildroot package。
- `src/field_nav_demo/`：A1 板端摄像头、推理、OSD 和 UART 输出源码。
- `scripts/build_field_nav.sh`：Linux SDK 容器内的一键构建脚本。
- `scripts/rdk_x5_nav_bridge.py`：地瓜派 RDK X5 侧 UART 桥接脚本。
- `board/m1pro/rootfs_overlay/`：目标根文件系统叠加内容和自启动脚本。

## 构建方式

正式构建需要在 A1 Linux SDK 构建容器中执行，Windows PowerShell 不能直接完整编译
Buildroot。进入 `smartsens_sdk` 后运行：

```bash
bash ./field_nav_external/scripts/build_field_nav.sh
```

脚本会准备 SDK 依赖、应用 `field_nav_m1pro_defconfig`、清理
`field_nav_demo` 旧构建缓存，并重新生成镜像。最终可烧录文件为：

```text
output/images/zImage.smartsens-m1-evb
```

## 模型放置

构建最终板端镜像前，需要把 A1 工具链转换后的模型放到：

```text
field_nav_external/src/field_nav_demo/app_assets/models/navroad_640x480.m1model
```

如果模型缺失，SDK 镜像仍可能完成构建，但板端 `/field_nav/scripts/run.sh`
启动时会明确提示模型不存在并退出。模型在板端默认运行路径为：

```text
/field_nav/app_assets/models/navroad_640x480.m1model
```

## 板端启动参数

Buildroot 打包后，板端通过 `/field_nav/scripts/run.sh` 启动
`field_nav_demo`。常用环境变量如下：

- `FIELD_NAV_UART`：是否启用导航 UART 输出，默认 `1`。
- `FIELD_NAV_BAUD`：导航串口波特率，默认 `115200`。
- `FIELD_NAV_RATE`：导航帧发送频率，默认 `10` Hz。
- `FIELD_NAV_SENSOR_FPS`：写入日志的目标传感器帧率，默认 `0`。
- `FIELD_NAV_OSD_RATE`：OSD 刷新频率，默认 `15` Hz；设为 `0` 可关闭运行中 OSD 绘制。
- `FIELD_NAV_TEST_SECONDS`：固定运行测试时长，默认 `0` 表示不主动退出。

普通运行示例：

```sh
FIELD_NAV_UART=1 FIELD_NAV_BAUD=115200 FIELD_NAV_RATE=10 /field_nav/scripts/run.sh
```

## A1 到 RDK X5 的 UART 链路

A1 侧程序会把 `GPIO_PIN_0` 配置为 `UART0_TX`，并按设定频率发送 16 字节导航帧。
推荐接线如下：

```text
A1 P4-15 / A1_D0_UART0TX -> 1.8V 转 3.3V 电平转换 -> RDK X5 40Pin Pin10 / UART_RXD
A1 GND -> RDK X5 GND
```

A1 输出的是导航结果，不直接控制车轮。RDK X5 接收导航帧后，再计算线速度和角速度，
并从 `RDK X5 40Pin Pin8 / UART_TXD` 向下位机发送 16 字节控制帧。

## RDK X5 桥接脚本

在 RDK X5 上先确认 40Pin UART 设备名：

```bash
ls -l /dev/ttyS* /dev/ttyUSB* /dev/ttyACM*
dmesg | grep -i tty
```

然后运行本仓库中的桥接脚本，例如：

```bash
python3 field_nav_external/scripts/rdk_x5_nav_bridge.py --port /dev/ttyS1 --baud 115200
```

`rdk_x5_nav_bridge.py` 使用 Python 标准库 `termios` 打开串口，不依赖第三方包。
它解析 A1 导航帧头 `A5 5A`，并向下位机发送控制帧头 `B5 5B`。

### Web 仪表盘

可通过可选参数 `--web HOST:PORT` 启用网页可视化终端：

```bash
python3 field_nav_external/scripts/rdk_x5_nav_bridge.py --port /dev/ttyS1 --web 0.0.0.0:8080
```

启动后浏览器访问 `http://<RDK_IP>:8080` 可查看实时仪表盘。Web 服务仅使用
Python 标准库（`http.server`），零第三方依赖。

仪表盘提供以下信息：

- **最新 A1 导航帧**：seq、valid、deviation_px、angle_deg、confidence_pct、
  point_count、bottom_x_px、status、帧龄（ms）。
- **最新 RDK 控制帧**：seq、enable、valid_nav、线速度（mm/s）、角速度（mrad/s）、
  deviation_px、mode。
- **诊断统计**：checksum 错误帧数、seq 跳号次数、A1 超时次数、安全原因（
  ok / slow_speed / no_frame / timeout / invalid_flag / status_error /
  low_confidence）、控制帧发送频率（Hz）、运行时间、总帧计数。
- **JSON 接口**：`/status` 返回完整状态 JSON，可被外部监控脚本消费。

不指定 `--web` 时，桥接脚本行为完全兼容之前的版本。

## 60 秒证据采集

比赛或上板验证时，建议固定运行 60 秒并保存 Aurora 左侧 UART 日志：

```sh
FIELD_NAV_UART=1 FIELD_NAV_BAUD=115200 FIELD_NAV_RATE=90 FIELD_NAV_SENSOR_FPS=90 FIELD_NAV_OSD_RATE=15 FIELD_NAV_TEST_SECONDS=60 /field_nav/scripts/run.sh
```

程序会每秒打印一行 `metrics`。重点关注：

- `FPS_app`：应用主循环实测帧率。
- `P95_frame_ms`：当前 60 秒窗口内帧耗时 P95。
- `max_frame_ms`：当前窗口内最慢帧耗时。
- `image_ms`、`predict_ms`、`uart_ms`、`osd_ms`：取图、推理、UART、OSD 分阶段耗时，
  格式为 `[avg,p95,max]` 毫秒。
- `valid_nav`、`no_line`、`predict_fail`、`image_fail`：有效导航和失败计数。
- `uart_sent`、`uart_fail`：导航 UART 是否实际发送成功的证据。
- `max_invalid_ms`：当前窗口内最长连续无效导航时间。

`FIELD_NAV_SENSOR_FPS=90` 只是把目标帧率写进日志，不会单独重配传感器模式。
是否满足 90fps 性能项，要结合板端传感器配置、`FPS_app`、`fps_ratio` 和
`image_ms` 等实测指标判断。
