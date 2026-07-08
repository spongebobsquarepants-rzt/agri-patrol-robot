# 田间巡检机器人 — 病虫害检测与自主导航系统

## 项目简介

本项目面向现代农业精准植保场景，设计了一套**田间自主巡检机器人系统**，实现作物病虫害的实时检测、定位与云端展示。系统由飞凌微 A1 视觉导航、STM32F407 运动控制、RDK X5 AI 检测、4G 云端通信及手机 APP 五大模块协同工作，完成"自主行走—实时检测—云端上传—APP 展示"的完整任务闭环。

## 系统架构

```
┌─────────────────┐    串口    ┌──────────────────┐
│  飞凌微 A1      │ ────────→  │  STM32F407       │
│  视觉导航        │           │  运动控制         │
│  (路径规划)      │           │  (模糊 PID)       │
└─────────────────┘           └────────┬─────────┘
                                       │ 串口
┌─────────────────┐                    │
│  RDK X5         │ ←─────────────────┘
│  YOLO 检测       │
│  ROS2 摄像头     │
│  ncnn 推理       │
└────────┬────────┘
         │ USB
┌────────┴────────┐
│  EC200A 4G 模块  │
│  GPS + 数据上传  │
└────────┬────────┘
         │ 4G 网络
┌────────┴────────┐
│  云端服务器       │
│  FastAPI         │
└────────┬────────┘
         │ HTTP
┌────────┴────────┐
│  手机 APP (Web)  │
│  检测列表 + 地图  │
└─────────────────┘
```

## 硬件清单

| 模块 | 硬件 | 数量 | 说明 |
|------|------|------|------|
| AI 主控 | RDK X5 开发者套件 | 1 | 10 TOPS 算力，搭载旭日 5 芯片 |
| 导航板 | 飞凌微 A1 | 1 | 视觉导航线提取与路径规划 |
| 运动控制 | STM32F407 | 1 | 双路电机驱动，自适应模糊 PID |
| 4G 通信 | 移远 EC200A-CN | 1 | LTE Cat.1，GPS 定位 |
| 摄像头 | MIPI 摄像头 (RDK X5) | 1 | 通过 ROS2 话题发布图像 |
| 摄像头 | 飞凌微 A1 自带 | 1 | 导航线识别 |
| GPS 天线 | SMA 接口有源天线 | 1 | GPS+BD 双模 |
| 4G 天线 | FPC 主天线 | 1 | 4G 通信 |

## 软件架构

```
agri-patrol-robot/
├── a1_shijuedaohang/       # 飞凌微 A1 视觉导航
│   ├── field_nav_external/  # Buildroot 扩展包
│   ├── field_nav_workspace/ # 导航算法工作区
│   └── project_root/        # 项目根配置
├── adaptive-fuzzy-pid/     # STM32F407 模糊 PID 控制
│   ├── Drivers/             # HAL 驱动库
│   ├── User/                # 主程序 (main.c)
│   └── Projects/            # Keil MDK 工程
├── rdk_x5/                 # RDK X5 AI 检测
│   ├── rdkx5_detect_upload.py  # ROS2 检测主程序
│   ├── rdkx5_ghost_cbam_detect.py  # ncnn 推理模块
│   ├── detect_and_upload.py  # 摄像头检测 + 上传
│   ├── gps_reader.py         # GPS 串口读取
│   ├── uploader.py           # HTTP 上传模块
│   └── config.py             # 配置文件
├── server/                  # 云端/边缘服务器
│   ├── server.py             # FastAPI 主程序
│   └── requirements.txt      # Python 依赖
├── app/                     # 手机 APP (移动 Web)
│   └── index.html            # 单页应用
├── README.md
└── README_cn.md
```

## 检测能力

基于 YOLO + GhostNet + CBAM 轻量化模型，ncnn 推理框架，支持 3 类水稻病害：

| 序号 | 病害名称 | 英文名 |
|------|----------|--------|
| 0 | 细菌性叶枯病 | Bacterial Leaf Blight |
| 1 | 褐斑病 | Brown Spot |
| 2 | 叶黑粉病 | Leaf Smut |

## 开发环境

### RDK X5 环境要求

```bash
# 系统版本
Ubuntu 22.04 (RDK OS)

# Python 依赖
pip install ncnn opencv-python pyserial requests

# ROS2 环境
source /opt/tros/humble/setup.bash
```

### 服务器环境

```bash
cd server
pip install -r requirements.txt
# fastapi + uvicorn + python-multipart
```

## 运行方式

### 1. 启动后端服务器

```bash
cd server
python3 server.py
# 服务启动在 http://0.0.0.0:8888
# API 文档: http://<IP>:8888/docs
```

### 2. 启动 RDK X5 检测

```bash
# 终端一：启动 ROS2 摄像头节点
source /opt/tros/humble/setup.bash
ros2 launch mipi_cam mipi_cam_dual_channel_websocket.launch.py

# 终端二：启动检测程序
source /opt/tros/humble/setup.bash
cd rdk_x5
python3 rdkx5_detect_upload.py
```

### 3. 启用 GPS (需先插入 SIM 卡并开启 GPS)

```bash
python3 -c "
import serial
s = serial.Serial('/dev/ttyUSB2', 115200, timeout=2)
s.write(b'AT+QGPS=1\r\n')  # 开启 GPS
s.close()
"
```

### 4. 访问 APP

手机浏览器打开：`http://<服务器IP>:8888`

### 5. 飞凌微 A1 视觉导航

将 `a1_shijuedaohang/field_nav_external/` 放入 Buildroot 的 external 目录编译。

### 6. STM32 运动控制

使用 Keil MDK 打开 `adaptive-fuzzy-pid/Projects/MDK-ARM/Project.uvprojx` 编译下载。

## 技术要点

- **视觉感知（必选）**：RDK X5 搭载 YOLO 病虫害检测，飞凌微 A1 田间导航线提取
- **自主运动**：STM32 自适应模糊 PID 速度闭环 + 串口指令控制
- **完整任务闭环**：自动巡检 → 实时检测 → 云端上传 → APP 展示
- **算力利用**：ncnn 推理框架充分利用 RDK X5 BPU 加速
- **远程通信**：4G 模块实现田间环境下的数据实时回传

## 创新点

- 飞凌微 A1 + RDK X5 双板异构协同，视觉导航与 AI 检测解耦
- GhostNet + CBAM 轻量化模型，适配端侧低算力场景
- 自适应模糊 PID 算法在线整定电机参数，适应不同地形
- 4G + GPS 实现无 WiFi 环境下的远程数据回传与定位

## 竞赛信息

- 赛事：全国大学生嵌入式芯片与系统设计竞赛 2026
- 赛题：地瓜机器人 — 自主选题（现代农业方向）
- 主控平台：RDK X5 开发者套件
- NodeHub 地址：https://developer.d-robotics.cc/nodehub
- GitHub 仓库：https://github.com/spongebobsquarepants-rzt/agri-patrol-robot
