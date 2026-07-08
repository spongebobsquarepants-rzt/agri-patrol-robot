# RDK X5 导航帧到下位机控制

## 已确认设备信息

- 本机通过 `以太网 2` 连接 RDK X5。
- Windows 侧 IP：`192.168.127.100`。
- RDK X5 `eth0` IP：`192.168.127.10/24`。
- 板卡型号：`D-Robotics RDK X5 V1.0`。
- 系统：`Ubuntu 22.04.5 LTS`。
- 内核：`Linux 6.1.83 aarch64`。
- Python：`3.10.12`。
- SSH 用户：`sunrise`。密码不要写入项目文件、笔记或提交记录。

## 串口情况

- RDK X5 上存在 `/dev/ttyS0` 到 `/dev/ttyS7`。
- `/dev/ttyS0` 被 `serial-getty@ttyS0.service` 占用，像系统调试串口，不建议用于导航控制。
- `/dev/ttyS1` 到 `/dev/ttyS7` 当前未发现进程占用，权限为 `root:dialout` 可读写。
- `sunrise` 用户属于 `dialout`、`sudo`、`gpio` 等组，有访问常规串口的基础权限。
- 联调起点建议：`/dev/ttyS1`、`115200 8N1`。

## 控制链路

```text
A1 摄像头
-> field_nav_demo 模型推理和后处理
-> NavLine 导航结果
-> A1 UART 16 字节导航帧 A5 5A
-> RDK X5 rdk_x5_nav_bridge.py
-> RDK 控制帧 B5 5B
-> 下位机/单片机
```

A1 发出的不是原始图片，也不是数据集文件，而是导航结果。RDK X5 不直接运行视觉模型，只解析导航帧、做安全判断、生成下位机控制命令。

## A1 导航帧

A1 导航帧为 16 字节：

```text
A5 5A | version | valid | seq | deviation_px*10 | angle_deg*100 | confidence | point_count | bottom_x | status | checksum
```

关键字段：

- `valid`：当前导航线是否有效。
- `deviation_px`：车底部中心相对道路中心线的横向偏差，单位 px。
- `angle_deg`：导航线角度，单位度。
- `confidence`：置信度，范围 0-100。
- `status`：A1 状态，`0` 表示正常。
- `checksum`：前 15 字节累加后的低 8 位。

## RDK 控制逻辑

RDK 必须先判断导航帧是否能用于控制：

```python
valid_nav = nav.valid and nav.status == 0 and nav.confidence_pct >= min_confidence and age <= timeout
```

默认安全条件：

- `valid=1`
- `status=0`
- `confidence >= 30`
- 导航帧年龄不超过 `0.3s`

任一条件不满足时，RDK 应向下位机输出停车/禁用控制帧。

当前脚本使用简单 P 控制：

```python
angular = kp_dev * deviation_px + kp_ang * angle_deg
linear = linear_speed
```

默认参数：

- `linear = 150 mm/s`
- `kp_dev = -2.0 mrad/s per px`
- `kp_ang = -20.0 mrad/s per deg`
- `max_angular = 800 mrad/s`
- `min_confidence = 30`
- `timeout = 0.3s`

注意：这里的 `linear_v_mm_s` 和 `angular_w_mrad_s` 是 RDK 计算出来的目标线速度和目标角速度，不是摄像头测得的真实速度。

## RDK 发给下位机的控制帧

RDK 控制帧为 16 字节：

```text
B5 5B | version | flags | seq | linear_v_mm_s | angular_w_mrad_s | deviation_px*10 | mode | reserved | checksum
```

字段含义：

- `flags bit0 = enable`
- `flags bit1 = valid_nav`
- `linear_v_mm_s`：目标线速度，单位 mm/s。
- `angular_w_mrad_s`：目标角速度，单位 mrad/s。
- `mode=1`：正常循迹。
- `mode=2`：停车或无效导航。

下位机只需要执行 RDK 给出的控制帧，不需要解析原始图像或模型输出。

## 摄像头、编码器和控制精度

只用普通单目摄像头，不能直接准确知道机器人真实线速度和真实角速度。摄像头负责识别道路方向和偏差：

- 道路中心线在哪里。
- 机器人相对道路中心偏了多少。
- 导航线角度是多少。
- 当前识别是否可靠。

有编码电机、没有陀螺仪也可以做闭环控制。差速底盘可用编码器估算：

```text
v = (v_left + v_right) / 2
w = (v_right - v_left) / wheel_base
```

其中：

- `v_left`：左轮实际线速度。
- `v_right`：右轮实际线速度。
- `wheel_base`：左右轮中心距。

若下位机接收左右轮目标速度，RDK 或下位机可做差速运动学转换：

```text
v_left_target  = v_target - w_target * wheel_base / 2
v_right_target = v_target + w_target * wheel_base / 2
```

没有陀螺仪的主要影响：

- 轮子打滑时，编码器会高估实际运动。
- 松软地面、草地、泥地上角速度估计会漂。
- 急转弯或单侧轮悬空时误差会变大。

田间道路循迹在低速、连续视觉修正条件下可以接受。推荐分工：

```text
A1 摄像头：负责往哪走
RDK X5：根据 deviation_px/angle_deg 生成目标 v/w
单片机：用编码器 PID 闭环执行左右轮速度
```

## 调参起点

建议低速起步：

```bash
python3 rdk_x5_nav_bridge.py \
  --port /dev/ttyS1 \
  --baud 115200 \
  --rate 10 \
  --linear 120 \
  --kp-dev -1.5 \
  --kp-ang -15 \
  --max-angular 600 \
  --min-confidence 30 \
  --timeout 0.3
```

调参规则：

- 车偏了但转得不够：增大 `kp-dev` 绝对值。
- 车头方向纠正慢：增大 `kp-ang` 绝对值。
- 左右来回摆动：减小 `kp-dev/kp-ang` 绝对值，或降低 `linear`。
- 速度太快导致冲出道路：降低 `linear`。
- 转向太猛：降低 `max-angular`。
- 导航偶尔失效还继续走：降低 `timeout`。
- 误识别太多：提高 `min-confidence`。

## 下位机安全要求

单片机端建议：

- 只接受 `B5 5B` 帧头。
- 检查 checksum。
- `enable=1` 且 `valid_nav=1` 才运动。
- `mode=2` 或 `enable=0` 时停车。
- 超过约 `500ms` 没收到有效控制帧时停车。
- 限制最大电机 PWM、最大线速度、最大角速度和最大加速度。

## 继续实现前需要补充的参数

- 底盘类型：差速两轮、四轮差速、阿克曼或其他。
- 左右轮中心距 `wheel_base`，单位 mm。
- 轮子直径，单位 mm。
- 编码器 PPR/CPR。
- 减速比。
- 下位机当前接收指令类型：左右 PWM、左右目标速度，还是 `v/w`。
- 下位机串口协议格式。
- 最大安全线速度，单位 mm/s。
- 最大安全角速度，单位 mrad/s。
