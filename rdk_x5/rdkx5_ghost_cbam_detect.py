"""
rdkx5_ghost_cbam_detect.py - RDK X5 + SC230AI + YOLO26 Ghost-CBAM NCNN
"""

import cv2
import numpy as np
from ultralytics import YOLO
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
import time

MODEL_PATH = "/home/sunrise/ultralytics/robust_ncnn_model"
CONFIDENCE = 0.25
IOU = 0.45
IMGSZ = 640

CLASS_NAMES = {
    0: "Bacteria_Leaf_Blight",
    1: "Brown_Spot",
    2: "Leaf_smut",
}


def draw_boxes(img, results, class_names):
    if results[0].boxes is None:
        return img
    boxes = results[0].boxes.xyxy.cpu().numpy()
    confs = results[0].boxes.conf.cpu().numpy()
    clss = results[0].boxes.cls.cpu().numpy().astype(int)
    colors = {
        0: (0, 255, 0),
        1: (0, 165, 255),
        2: (255, 0, 255),
    }
    for box, conf, cls in zip(boxes, confs, clss):
        x1, y1, x2, y2 = map(int, box)
        color = colors.get(cls, (255, 255, 255))
        label = f"{class_names.get(cls, str(cls))} {conf:.2f}"
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(img, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, label, (x1 + 2, y1 - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    return img


class PestDetector(Node):
    def __init__(self):
        super().__init__("pest_detector")
        print("=" * 50)
        print("RDK X5 Pest Detection")
        print("Model: YOLO26 + GhostNet + CBAM (NCNN)")
        print(f"Model path: {MODEL_PATH}")
        print("=" * 50)
        print("\n[1/3] Loading model...")
        t0 = time.time()
        self.model = YOLO(MODEL_PATH, task="detect")
        print(f"      Model loaded ({time.time() - t0:.1f}s)")
        print("[2/3] Subscribing /image_combine_jpeg ...")
        self.sub = self.create_subscription(
            CompressedImage, "/image_combine_jpeg", self.callback, 10
        )
        self.frame = None
        self.fps_counter = 0
        self.fps_timer = time.time()
        cv2.namedWindow("RDK X5 - Pest Detection (Ghost-CBAM)", cv2.WINDOW_NORMAL)
        self.create_timer(1/30.0, self.update_frame)
        print("[3/3] Running (Q to quit)...\n")

    def callback(self, msg):
        try:
            buf = np.frombuffer(msg.data, dtype=np.uint8)
            self.frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception as e:
            self.get_logger().error(f"Decode error: {e}")

    def update_frame(self):
        if self.frame is None:
            return
        frame = self.frame.copy()
        t_infer = time.time()
        results = self.model(frame, imgsz=IMGSZ, conf=CONFIDENCE, iou=IOU, verbose=False)
        infer_ms = (time.time() - t_infer) * 1000
        annotated = draw_boxes(frame, results, CLASS_NAMES)
        self.fps_counter += 1
        if time.time() - self.fps_timer >= 1.0:
            fps = self.fps_counter / (time.time() - self.fps_timer)
            self.fps_counter = 0
            self.fps_timer = time.time()
        cv2.putText(annotated, f"GhostNet+CBAM | Pest Detection",
                    (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        cv2.imshow("RDK X5 - Pest Detection (Ghost-CBAM)", annotated)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            rclpy.shutdown()


def main(args=None):
    rclpy.init(args=args)
    node = PestDetector()
    rclpy.spin(node)
    cv2.destroyAllWindows()
    rclpy.shutdown()


if __name__ == "__main__":
    main()