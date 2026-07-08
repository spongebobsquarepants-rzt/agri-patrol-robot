# 农业巡检机器人 - 病虫害检测系统

## 系统架构

飞凌微A1 视觉导航 + STM32F407 运动控制 + RDK X5 AI检测 + 4G云端通信

## 功能模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 后端服务器 | `server/` | FastAPI，接收检测数据、提供APP接口 |
| AI检测 | `rdk_x5/` | YOLO+GhostNet+CBAM，ncnn推理，ROS2摄像头 |
| 手机APP | `app/` | 移动端Web，检测列表/地图/统计 |

## 检测类别

- 细菌性叶枯病 (Bacterial Leaf Blight)
- 褐斑病 (Brown Spot)
- 叶黑粉病 (Leaf Smut)

## 运行方式

1. 启动摄像头: `ros2 launch mipi_cam mipi_cam_dual_channel_websocket.launch.py`
2. 启动服务器: `cd server && python3 server.py`
3. 启动检测: `cd rdk_x5 && python3 rdkx5_detect_upload.py`
4. 打开APP: `http://服务器IP:8888`
