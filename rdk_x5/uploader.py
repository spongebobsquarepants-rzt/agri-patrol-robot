# uploader.py
# RDK X5 病虫害检测后调用此模块上传到服务器
# 用法:
#   from uploader import DetectionUploader
#   up = DetectionUploader("http://192.168.124.x:8888")
#   up.upload("蚜虫", 0.95, 120, 80, 200, 180, "/tmp/pest.jpg")

import requests
import os
from datetime import datetime
from typing import Optional


class DetectionUploader:
    def __init__(self, server_url: str):
        self.server_url = server_url.rstrip("/")

    def upload(
        self,
        class_name: str,
        confidence: float,
        x: int, y: int, w: int, h: int,
        image_path: str,
        gps_lat: float = 0.0,
        gps_lon: float = 0.0,
    ) -> Optional[str]:
        """
        上传一条病虫害检测结果。
        返回: 成功 → 检测ID, 失败 → None
        """
        url = f"{self.server_url}/api/detections"

        if not os.path.exists(image_path):
            print(f"[Upload] 图片不存在: {image_path}")
            return None

        try:
            with open(image_path, "rb") as f:
                resp = requests.post(
                    url,
                    data={
                        "class_name": class_name,
                        "confidence": str(confidence),
                        "x": str(x),
                        "y": str(y),
                        "w": str(w),
                        "h": str(h),
                        "gps_lat": str(gps_lat),
                        "gps_lon": str(gps_lon),
                    },
                    files={"image": (os.path.basename(image_path), f, "image/jpeg")},
                    timeout=15,
                )
            if resp.status_code == 200:
                data = resp.json()
                det_id = data.get("id", "")
                print(f"[Upload] ✅ {class_name} ({confidence:.0%}) → {det_id}")
                return det_id
            else:
                print(f"[Upload] ❌ 服务器返回 {resp.status_code}: {resp.text[:100]}")
                return None
        except requests.exceptions.RequestException as e:
            print(f"[Upload] ❌ 网络错误: {e}")
            return None


# ============================================================
# 组合使用示例：检测到病虫害后一站式上传
# ============================================================
def upload_detection_with_gps(
    uploader: DetectionUploader,
    class_name: str,
    confidence: float,
    bbox: tuple,          # (x, y, w, h)
    image_path: str,
    gps_lat: float = 0.0,
    gps_lon: float = 0.0,
):
    """一站式上传：检测结果 + GPS + 图片"""
    return uploader.upload(
        class_name=class_name,
        confidence=confidence,
        x=bbox[0], y=bbox[1], w=bbox[2], h=bbox[3],
        image_path=image_path,
        gps_lat=gps_lat,
        gps_lon=gps_lon,
    )


# ============================================================
# 测试：模拟一次上传
# ============================================================
if __name__ == "__main__":
    import sys
    import tempfile
    from PIL import Image

    if len(sys.argv) < 2:
        print("用法: python3 uploader.py http://服务器IP:8888")
        sys.exit(1)

    SERVER = sys.argv[1]
    up = DetectionUploader(SERVER)

    # 生成一张测试图片
    test_img = tempfile.mktemp(suffix=".jpg")
    Image.new("RGB", (640, 480), (100, 200, 100)).save(test_img)

    det_id = up.upload(
        class_name="蚜虫",
        confidence=0.95,
        x=120, y=80, w=200, h=180,
        image_path=test_img,
        gps_lat=31.2304,
        gps_lon=121.4737,
    )

    os.remove(test_img)
    print(f"\n上传结果: {'成功 ' + det_id if det_id else '失败'}")