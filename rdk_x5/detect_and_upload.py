# detect_and_upload.py
# RDK X5 实时病虫害检测 + 自动上传（ncnn 版本）
# 工作流程: 摄像头取帧 → ncnn YOLO 推理 → GPS 定位 → 上传服务器
# 用法:    python3 detect_and_upload.py [--server http://IP:8888]
#
# 依赖:
#   pip3 install ncnn opencv-python numpy pyserial requests

import sys
import os
import time
import argparse
from pathlib import Path
from collections import defaultdict

import cv2
import numpy as np
import ncnn

sys.path.insert(0, str(Path(__file__).parent))

from config import (
    SERVER_URL, CAMERA_DEVICE,
    STREAM_WIDTH, STREAM_HEIGHT,
    NCNN_PARAM, NCNN_BIN, CLASS_NAMES,
)
from uploader import DetectionUploader
from gps_reader import GPSReader


# ============================================================
# 参数解析
# ============================================================
parser = argparse.ArgumentParser(description="RDK X5 实时病虫害检测 (ncnn)")
parser.add_argument("--server", default=SERVER_URL, help="后端服务器地址")
parser.add_argument("--param", default=NCNN_PARAM, help="ncnn .param 文件路径")
parser.add_argument("--bin", default=NCNN_BIN, help="ncnn .bin 文件路径")
parser.add_argument("--conf", type=float, default=0.5, help="置信度阈值")
parser.add_argument("--nms", type=float, default=0.45, help="NMS IoU 阈值")
parser.add_argument("--interval", type=int, default=5, help="每 N 帧推理一次")
parser.add_argument("--gps-port", default="/dev/ttyUSB2", help="GPS 串口")
parser.add_argument("--debounce", type=float, default=5.0, help="同一目标防抖秒数")
parser.add_argument("--no-gps", action="store_true", help="无 GPS 时运行")
parser.add_argument("--no-upload", action="store_true", help="不上传，仅本地预览")
parser.add_argument("--display", action="store_true", help="显示检测画面（需显示器）")
args = parser.parse_args()


# ============================================================
# YOLOv8 ncnn 检测器
# ============================================================
class NCNNDetector:
    def __init__(self, param_path: str, bin_path: str):
        self.param_path = param_path
        self.bin_path = bin_path
        self.net = None
        self.input_size = 640
        self.num_classes = len(CLASS_NAMES)
        self.reg_max = 16

    def load(self):
        if not Path(self.param_path).exists():
            print(f"[Detector] ❌ .param 不存在: {self.param_path}")
            sys.exit(1)
        if not Path(self.bin_path).exists():
            print(f"[Detector] ❌ .bin 不存在: {self.bin_path}")
            sys.exit(1)

        self.net = ncnn.Net()
        self.net.opt.use_vulkan_compute = False
        self.net.opt.num_threads = 4
        self.net.load_param(self.param_path)
        self.net.load_model(self.bin_path)
        print(f"[Detector] ✅ ncnn 模型加载成功")

    def detect(self, frame: np.ndarray) -> list[dict]:
        """对一帧做推理，返回检测结果列表"""
        h, w = frame.shape[:2]

        # 预处理: BGR→RGB, resize 640x640, /255.0
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (self.input_size, self.input_size))
        img = img.astype(np.float32) / 255.0

        # HWC → CHW, contiguous
        img = np.ascontiguousarray(img.transpose(2, 0, 1))

        # 创建 ncnn Mat
        mat_in = ncnn.Mat.from_pixels(
            img, ncnn.Mat.PixelType.PIXEL_RGB,
            self.input_size, self.input_size
        )
        # 归一化: mean=0, std=1/255
        mean_vals = [0.0, 0.0, 0.0]
        norm_vals = [1 / 255.0, 1 / 255.0, 1 / 255.0]
        mat_in.substract_mean_normalize(mean_vals, norm_vals)

        # 推理
        ex = self.net.create_extractor()
        ex.input("in0", mat_in)
        ret, mat_out = ex.extract("out0")

        if ret != 0:
            return []

        # 解析输出
        out = np.array(mat_out)  # shape: (num_outputs, num_anchors)

        # YOLO ncnn 输出: (7, 8400) for 3 classes
        # [0:4, :] = bbox cx,cy,w,h; [4:, :] = class scores
        # 对于 end2end=false 的 YOLOv8-ncnn，输出可能是 (1, 7, 8400)
        # 需要确保是 2D：(features, anchors)
        if out.ndim == 3:
            out = out[0]  # (1, F, A) → (F, A)

        if out.ndim == 1:
            out = out.reshape(-1, out.shape[0])

        # 转置: (F, A) → (A, F)
        out = out.T

        detections = []
        for row in out:
            # ✅ ncnn YOLO 格式: [cx, cy, w, h, c0, c1, c2]
            bbox = row[:4]
            scores = row[4:]

            class_id = int(np.argmax(scores))
            conf = float(scores[class_id])

            if conf < args.conf:
                continue

            # 归一化坐标 → 像素坐标
            cx, cy, bw, bh = bbox
            x1 = int((cx - bw / 2) / self.input_size * w)
            y1 = int((cy - bh / 2) / self.input_size * h)
            x2 = int((cx + bw / 2) / self.input_size * w)
            y2 = int((cy + bh / 2) / self.input_size * h)

            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)

            if x2 <= x1 or y2 <= y1:
                continue

            detections.append({
                "class_id": class_id,
                "class_name": CLASS_NAMES.get(class_id, f"unknown"),
                "confidence": round(conf, 4),
                "bbox": (x1, y1, x2 - x1, y2 - y1),
            })

        # NMS
        if detections and len(detections) > 1:
            detections = self._nms_filter(detections)

        return detections

    def _nms_filter(self, detections: list[dict]) -> list[dict]:
        boxes = [[d["bbox"][0], d["bbox"][1],
                  d["bbox"][0] + d["bbox"][2],
                  d["bbox"][1] + d["bbox"][3]] for d in detections]
        scores = [d["confidence"] for d in detections]
        indices = cv2.dnn.NMSBoxes(boxes, scores, args.conf, args.nms)
        if len(indices) == 0:
            return []
        return [detections[i] for i in indices.flatten()]


# ============================================================
# 去重跟踪器
# ============================================================
class DedupTracker:
    def __init__(self, debounce_seconds: float = 5.0):
        self.debounce = debounce_seconds
        self.last_upload: dict[str, float] = {}
        self.grid_states: dict[str, set] = defaultdict(set)

    def should_upload(self, class_name: str, bbox: tuple) -> bool:
        now = time.time()
        if class_name in self.last_upload:
            if now - self.last_upload[class_name] < self.debounce:
                return False
        grid_key = self._grid(class_name, bbox)
        if grid_key in self.grid_states[class_name]:
            return False
        self.grid_states[class_name].add(grid_key)
        self.last_upload[class_name] = now
        return True

    def _grid(self, class_name: str, bbox: tuple) -> str:
        x, y, w, h = bbox
        gx = int((x + w / 2) / STREAM_WIDTH * 4)
        gy = int((y + h / 2) / STREAM_HEIGHT * 4)
        return f"{gx}_{gy}"

    def cleanup(self):
        self.grid_states.clear()


# ============================================================
# 主循环
# ============================================================
def main():
    print("=" * 50)
    print("  RDK X5 实时病虫害检测 + 自动上传 (ncnn)")
    print(f"  服务器: {args.server}")
    print(f"  模型:   {args.param}")
    print(f"  阈值:   {args.conf}")
    print(f"  去抖:   {args.debounce}s")
    print("=" * 50)

    # 初始化
    detector = NCNNDetector(args.param, args.bin)
    detector.load()
    tracker = DedupTracker(args.debounce)
    uploader = DetectionUploader(args.server) if not args.no_upload else None

    gps = None
    if not args.no_gps:
        gps = GPSReader(args.gps_port)
        if not gps.open():
            print("[Main] ⚠️ GPS 不可用，继续无定位运行")
            gps = None

    print(f"[Main] 打开摄像头 {CAMERA_DEVICE}...")
    cap = cv2.VideoCapture(CAMERA_DEVICE)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, STREAM_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STREAM_HEIGHT)

    if not cap.isOpened():
        print("[Main] ❌ 摄像头打开失败！")
        if gps: gps.close()
        sys.exit(1)

    print("[Main] ✅ 开始实时检测，按 Ctrl+C 停止...")
    frame_count = 0
    upload_count = 0
    last_cleanup = time.time()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame_count += 1

            if frame_count % args.interval != 0:
                continue

            detections = detector.detect(frame)
            if not detections:
                continue

            for det in detections:
                if not tracker.should_upload(det["class_name"], det["bbox"]):
                    continue

                x, y, w, h = det["bbox"]
                crop = frame[y:y + h, x:x + w]
                if crop.size == 0:
                    continue

                crop_path = f"/tmp/pest_{det['class_name']}_{int(time.time())}.jpg"
                cv2.imwrite(crop_path, crop)

                gps_lat, gps_lon = 0.0, 0.0
                if gps:
                    lat, lon = gps.get_location()
                    if lat and lon:
                        gps_lat, gps_lon = lat, lon

                gps_str = f"({gps_lat:.4f}, {gps_lon:.4f})" if gps_lat else "(无GPS)"
                print(f"[Detect] 🐛 {det['class_name']} {det['confidence']:.0%} {gps_str}")

                if uploader:
                    det_id = uploader.upload(
                        class_name=det["class_name"],
                        confidence=det["confidence"],
                        x=x, y=y, w=w, h=h,
                        image_path=crop_path,
                        gps_lat=gps_lat,
                        gps_lon=gps_lon,
                    )
                    if det_id:
                        upload_count += 1

                try:
                    os.remove(crop_path)
                except OSError:
                    pass

            if time.time() - last_cleanup > 60:
                tracker.cleanup()
                last_cleanup = time.time()

    except KeyboardInterrupt:
        print(f"\n[Main] ⏹ 停止")
    finally:
        cap.release()
        if gps:
            gps.close()
        print(f"[Main] 总计: {frame_count} 帧, {upload_count} 次上传")


if __name__ == "__main__":
    main()
