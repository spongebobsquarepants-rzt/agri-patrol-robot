# 农业巡检机器人 — 田间病虫害检测与导航系统

## 系统架构

```
飞凌微A1 (视觉导航) ──→ STM32F407 (运动控制) ←── 传感器
                              │
RDK X5 (AI病虫害检测) ──→ 4G 模块 ──→ 云端服务器 ──→ 手机 APP
```

| 角色 | 硬件 | 功能 |
|------|------|------|
| 视觉导航 | 飞凌微 A1 | 田间路径提取 / 导航线检测 / 路径规划 |
| 运动控制 | STM32F407 | 自适应模糊 PID 电机控制 / 传感器采集 / 串口通信 |
| AI 检测 | RDK X5 | YOLO 病虫害检测 / ncnn 推理 / GPS 定位 |
| 数据上传 | EC200A 4G 模块 | 检测数据 + GPS 坐标上传云端 |
| 后端服务 | FastAPI (Python) | 接收检测数据 / 提供 API 接口 |
| 手机 APP | 移动端 Web | 病虫害列表 / GPS 地图 / 实时监测 |

---

## 文件结构

| 模块 | 路径 | 说明 |
|------|------|------|
| 视觉导航 | `a1_shijuedaohang/` | 飞凌微 A1 田间导航线提取与路径规划 |
| 运动控制 | `adaptive-fuzzy-pid/` | STM32F407 自适应模糊 PID 直流电机控制 |
| AI 检测 | `rdk_x5/` | YOLO + GhostNet + CBAM，ncnn 推理，ROS2 摄像头 |
| 后端服务 | `server/` | FastAPI 服务器，数据存储与 API |
| 手机 APP | `app/` | 移动端 Web 页面，检测展示与地图 |

---

## 检测类别

- 细菌性叶枯病 (Bacterial Leaf Blight)
- 褐斑病 (Brown Spot)
- 叶黑粉病 (Leaf Smut)

---

## 各模块运行方式

### 1. 飞凌微 A1 — 视觉导航

飞凌微 A1 通过自带摄像头提取田间导航线，进行路径规划，将控制指令通过串口发送给 STM32。

```
# 飞凌微 A1 上运行
cd a1_shijuedaohang
# 根据具体环境编译运行导航程序
```

详见 `a1_shijuedaohang/field_nav_external/README.md`

### 2. STM32F407 — 自适应模糊 PID 控制

基于 STM32F407 的电机控制系统，支持：
- 双路直流电机 PWM 控制
- 增量式 PID 速度闭环
- 自适应模糊 PID 参数在线整定
- 编码器速度反馈
- 串口指令接收

```
# 使用 Keil MDK 打开工程
Projects/MDK-ARM/Project.uvprojx
```

详见 `adaptive-fuzzy-pid/User/main.c`

### 3. RDK X5 — AI 病虫害检测

YOLO 模型使用 ncnn 推理框架加速，通过 ROS2 话题订阅 MIPI 摄像头画面，检测结果通过 4G 模块上传。

```
# 终端一：启动摄像头 ROS 节点
source /opt/tros/humble/setup.bash
ros2 launch mipi_cam mipi_cam_dual_channel_websocket.launch.py

# 终端二：启动检测
cd rdk_x5
python3 rdkx5_detect_upload.py --no-upload --no-gps --display
```

### 4. 后端服务器

```
cd server
pip install -r requirements.txt
python3 server.py
# 访问 API 文档: http://服务器IP:8888/docs
```

### 5. 手机 APP

服务器启动后，手机浏览器访问：`http://服务器IP:8888`

---

## 数据流向

```
摄像头画面 → RDK X5 YOLO检测 → 病虫害名称 + GPS + 图片
                                        │
                                        ▼
                                 4G 模块上传
                                        │
                                        ▼
                              FastAPI 服务器存储
                                        │
                                        ▼
                                 手机 APP 展示
```
