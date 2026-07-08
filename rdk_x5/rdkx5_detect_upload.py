"""
rdkx5_detect_upload.py
RDK X5 ROS2 实时病虫害检测 + 自动上传
用法:
  终端1: source /opt/tros/humble/setup.bash && ros2 launch mipi_cam mipi_cam_dual_channel_websocket.launch.py
  终端2: cd ~/agri_app/rdk_x5 && source /opt/tros/humble/setup.bash && python3 rdkx5_detect_upload.py
"""

import os
import sys
import time
import argparse

import cv2
import numpy as np
from ultralytics import YOLO
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from uploader import DetectionUploader
from gps_reader import GPSReader

parser = argparse.ArgumentParser(description="RDK X5 检测+上传")
parser.add_argument("--server", default="http://localhost:8888", help="后端地址")
parser.add_argument("--model", default="/home/sunrise/ultralytics/robust_ncnn_model", help="ncnn模型目录")
parser.add_argument("--conf", type=float, default=0.25, help="置信度阈值")
parser.add_argument("--iou", type=float, default=0.45, help="NMS IoU")
parser.add_argument("--imgsz", type=int, default=640)
parser.add_argument("--gps-port", default="/dev/ttyUSB2")
parser.add_argument("--debounce", type=float, default=3.0)
parser.add_argument("--no-gps", action="store_true")
parser.add_argument("--no-upload", action="store_true")
parser.add_argument("--no-display", action="store_true")
args = parser.parse_args()

# 显示用英文(OpenCV支持), 上传用中文
EN_CLASS = {0: "Bacteria_Leaf_Blight", 1: "Brown_Spot", 2: "Leaf_smut"}
CN_CLASS = {0: "细菌性叶枯病", 1: "褐斑病", 2: "叶黑粉病"}
COLORS   = {0: (0, 255, 0), 1: (0, 165, 255), 2: (255, 0, 255)}


class DedupTracker:
    def __init__(self, debounce=3.0):
        self.debounce = debounce
        self.last = {}
    def should_upload(self, name):
        now = time.time()
        if name in self.last and now - self.last[name] < self.debounce:
            return False
        self.last[name] = now
        return True


class PestDetectorUpload(Node):
    def __init__(self):
        super().__init__("pest_detector_upload")
        print("=" * 50)
        print("  RDK X5 病虫害检测 + 自动上传")
        print(f"  服务器: {args.server}  阈值: {args.conf}")
        print("=" * 50)

        print("\n[1/4] 加载模型...")
        t0 = time.time()
        self.model = YOLO(args.model, task="detect")
        print(f"      ✅ 完成 ({time.time()-t0:.1f}s)")

        self.uploader = None if args.no_upload else DetectionUploader(args.server)
        self.tracker = DedupTracker(args.debounce)

        self.gps = None
        if not args.no_gps:
            self.gps = GPSReader(args.gps_port)
            if not self.gps.open():
                print("[GPS] ⚠️ 不可用")
                self.gps = None

        print("[2/4] 订阅 /image_combine_jpeg ...")
        self.sub = self.create_subscription(
            CompressedImage, "/image_combine_jpeg", self.callback, 10
        )
        self.frame = None
        self.frame_count = 0
        self.upload_count = 0
        self.fps_timer = time.time()
        self.fps_counter = 0
        self.fps = 0.0
        self.last_stats = time.time()

        if not args.no_display:
            cv2.namedWindow("RDK X5 - Pest Detection", cv2.WINDOW_NORMAL)
        self.create_timer(1/30.0, self.update_frame)
        print("[3/4] 运行中 (Q=退出)\n")

    def callback(self, msg):
        try:
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            self.frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except:
            pass

    def update_frame(self):
        if self.frame is None:
            return
        frame = self.frame.copy()
        self.frame_count += 1

        t0 = time.time()
        results = self.model(frame, imgsz=args.imgsz, conf=args.conf, iou=args.iou, verbose=False)

        self.fps_counter += 1
        if time.time() - self.fps_timer >= 1.0:
            self.fps = self.fps_counter / (time.time() - self.fps_timer)
            self.fps_counter = 0
            self.fps_timer = time.time()

        if results[0].boxes is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            confs = results[0].boxes.conf.cpu().numpy()
            clss  = results[0].boxes.cls.cpu().numpy().astype(int)

            for box, conf, cls in zip(boxes, confs, clss):
                en_name = EN_CLASS.get(cls, "unknown")
                cn_name = CN_CLASS.get(cls, "unknown")
                x1, y1, x2, y2 = map(int, box)
                color = COLORS.get(cls, (255,255,255))

                # 显示英文(OpenCV渲染)
                label = f"{en_name} {conf:.2f}"
                cv2.rectangle(frame, (x1,y1), (x2,y2), color, 2)
                (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                cv2.rectangle(frame, (x1, y1-th-6), (x1+tw+4, y1), color, -1)
                cv2.putText(frame, label, (x1+2, y1-4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)

                # 上传用中文
                if self.uploader and self.tracker.should_upload(cn_name):
                    w, h = x2-x1, y2-y1
                    crop = frame[y1:y2, x1:x2]
                    if crop.size == 0:
                        continue
                    tmp = f"/tmp/pest_{self.frame_count}.jpg"
                    cv2.imwrite(tmp, crop)

                    gps_lat, gps_lon = 0.0, 0.0
                    if self.gps:
                        glat, glon = self.gps.get_location()
                        if glat and glon:
                            gps_lat, gps_lon = glat, glon

                    det_id = self.uploader.upload(cn_name, float(conf), x1, y1, w, h, tmp, gps_lat, gps_lon)
                    if det_id:
                        self.upload_count += 1
                        print(f"  📤 {cn_name} {conf:.0%} -> {det_id}")
                    try: os.remove(tmp)
                    except: pass

        if time.time() - self.last_stats >= 10:
            print(f"  📊 FPS={self.fps:.1f}  总帧={self.frame_count}  上传={self.upload_count}")
            self.last_stats = time.time()

        if not args.no_display:
            cv2.putText(frame, f"FPS:{self.fps:.1f} | Upl:{self.upload_count}", (10,25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2)
            cv2.imshow("RDK X5 - Pest Detection", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                rclpy.shutdown()


def main():
    rclpy.init()
    node = PestDetectorUpload()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\n⏹ 停止")
    finally:
        cv2.destroyAllWindows()
        if node.gps: node.gps.close()
        print(f"  帧={node.frame_count}  上传={node.upload_count}")
        rclpy.shutdown()

if __name__ == "__main__":
    main()
