# RDK X5 配置文件 —— 所有车载脚本共享

# 后端服务器地址（改成实际 IP）
SERVER_URL = "http://localhost:8888"

# 摄像头设备
CAMERA_DEVICE = 0  # /dev/video0

# 视频推流参数
STREAM_FPS = 15
STREAM_WIDTH = 640
STREAM_HEIGHT = 480
STREAM_QUALITY = 70  # JPEG 质量 1-100

# ncnn 模型路径
NCNN_PARAM = "/home/sunrise/ultralytics/robust_ncnn_model/model.ncnn.param"
NCNN_BIN = "/home/sunrise/ultralytics/robust_ncnn_model/model.ncnn.bin"

# 病虫害类别（与模型训练时一致）
CLASS_NAMES = {
    0: "细菌性叶枯病",
    1: "褐斑病",
    2: "叶黑粉病",
}
