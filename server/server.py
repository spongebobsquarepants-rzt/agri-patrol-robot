# server.py —— 农业巡检病虫害检测后端
# 运行: pip install fastapi uvicorn python-multipart
#       python server.py
# 访问: http://你的IP:8888

import json
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ============================================================
# 配置
# ============================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
RECORDS_FILE = DATA_DIR / "records.json"

for d in [DATA_DIR, IMAGE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="农业巡检 APP 后端")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.mount("/static", StaticFiles(directory=str(DATA_DIR)), name="static")


# ============================================================
# 数据存取
# ============================================================
def load_records() -> list[dict]:
    if RECORDS_FILE.exists():
        return json.loads(RECORDS_FILE.read_text(encoding="utf-8"))
    return []


def save_records(records: list[dict]):
    RECORDS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================
# API 1: 上传检测结果（病虫害图片 + GPS）
# ============================================================
@app.post("/api/detections")
async def upload_detection(
    class_name: str = Form(..., description="病虫害名称"),
    confidence: float = Form(..., description="置信度 0.0~1.0"),
    x: int = Form(0, description="边界框 x"),
    y: int = Form(0, description="边界框 y"),
    w: int = Form(0, description="边界框宽"),
    h: int = Form(0, description="边界框高"),
    gps_lat: float = Form(0.0, description="GPS 纬度"),
    gps_lon: float = Form(0.0, description="GPS 经度"),
    image: UploadFile = File(..., description="病虫害截图"),
):
    det_id = uuid.uuid4().hex[:12]
    ext = (image.filename or "det.jpg").split(".")[-1]
    img_name = f"{det_id}.{ext}"
    img_path = IMAGE_DIR / img_name

    # 保存图片
    content = await image.read()
    img_path.write_bytes(content)

    # 构造记录
    record = {
        "id": det_id,
        "class_name": class_name,
        "confidence": round(confidence, 4),
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "gps": {"lat": round(gps_lat, 6), "lon": round(gps_lon, 6)},
        "image_url": f"/static/images/{img_name}",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ts_iso": datetime.now().isoformat(),
    }

    records = load_records()
    records.insert(0, record)
    records = records[:500]  # 最多保留 500 条
    save_records(records)

    return {"ok": True, "id": det_id, "record": record}


# ============================================================
# API 2: 查询检测列表
# ============================================================
@app.get("/api/detections")
def list_detections(skip: int = 0, limit: int = 50):
    records = load_records()
    return {
        "total": len(records),
        "items": records[skip: skip + limit],
    }


# ============================================================
# API 3: 查询单条详情
# ============================================================
@app.get("/api/detections/{det_id}")
def get_detection(det_id: str):
    records = load_records()
    for r in records:
        if r["id"] == det_id:
            return r
    return {"error": "not found"}


# ============================================================
# API 4: 统计概览（APP 仪表盘用）
# ============================================================
@app.get("/api/stats")
def get_stats():
    records = load_records()
    class_counts = {}
    for r in records:
        name = r["class_name"]
        class_counts[name] = class_counts.get(name, 0) + 1
    return {
        "total_detections": len(records),
        "last_detection": records[0]["timestamp"] if records else None,
        "by_class": class_counts,
    }


# ============================================================
# 首页（后面放 APP）
# ============================================================
@app.get("/")
def serve_app():
    app_html = BASE_DIR.parent / "app" / "index.html"
    if app_html.exists():
        return FileResponse(app_html)
    return {"msg": "农业巡检后端已启动", "api_doc": "/docs"}


# ============================================================
# 启动
# ============================================================
if __name__ == "__main__":
    print("=" * 50)
    print("  农业巡检病虫害检测后端")
    print("  API 文档: http://0.0.0.0:8888/docs")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8888)
