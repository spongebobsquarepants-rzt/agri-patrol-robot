#!/usr/bin/env python3
"""Generate host-side proof that NavRoad produces a navigation line.

The script runs the PyTorch checkpoint on processed 640x480 grayscale samples,
then applies a board-like row-scan postprocess to the low-resolution mask output.
It writes visual overlays plus JSON/CSV metrics that can be inspected without
booting the A1 board.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_navroad_v2 import RoadDataset, SkipFusionNavRoadNet  # noqa: E402


# 以下常量镜像板端 field_nav.hpp 坐标约定，用于把 host 端结果映射到 720x1280 原始画面。
K_ORIGINAL_WIDTH = 720
K_ORIGINAL_HEIGHT = 1280
K_CROP_WIDTH = 720
K_CROP_HEIGHT = 540
K_CROP_OFFSET_Y = 370
K_MODEL_WIDTH = 640
K_MODEL_HEIGHT = 480


@dataclass
class NavPoint:
    """导航线中心点。

    x/y 为原始画面坐标，confidence 为该行/段的平均置信度。
    """

    x: float
    y: float
    confidence: float


@dataclass
class NavLine:
    """host 端导航线结果。

    字段含义与板端 NavLine 对齐，并额外保存 crop_bottom_x/crop_deviation_px 便于证明图统计。
    """

    valid: bool = False
    slope: float = 0.0
    intercept: float = 0.0
    bottom_x: float = 0.0
    deviation_px: float = 0.0
    crop_bottom_x: float = 0.0
    crop_deviation_px: float = 0.0
    angle_deg: float = 0.0
    confidence: float = 0.0
    points: list[NavPoint] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    """解析主机端证明参数。

    输出数据目录、checkpoint、split、阈值、样本数量和可视化输出目录。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threshold", default=0.45, type=float)
    parser.add_argument("--max-samples", default=0, type=int, help="0 means all samples in the split")
    parser.add_argument(
        "--output-dir",
        default=Path("field_nav_workspace/runs/navroad_v2/host_proof"),
        type=Path,
    )
    parser.add_argument("--contact-sheet-count", default=16, type=int)
    return parser.parse_args()


def load_model(checkpoint_path: Path, device: torch.device) -> SkipFusionNavRoadNet:
    """加载 v2 checkpoint。

    输入 checkpoint 路径和 torch 设备；输出 eval 模式模型。兼容新旧 torch.load 参数。
    """

    try:
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
    except TypeError:
        checkpoint = torch.load(checkpoint_path, map_location=device)
    config = checkpoint.get("config", {})
    model = SkipFusionNavRoadNet(width_mult=float(config.get("width_mult", 1.0))).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model


def resize_nearest(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """用最近邻把二值 mask 缩放到指定宽高。

    输入 mask 和 (width,height)；输出 0/1 float32 mask，保持类别边界不被插值污染。
    """

    width, height = size
    pil = Image.fromarray((mask.astype(np.float32) * 255.0).clip(0, 255).astype(np.uint8), mode="L")
    return (np.asarray(pil.resize((width, height), resample=Image.Resampling.NEAREST)) > 127).astype(np.float32)


def original_to_display(x: float, y: float) -> tuple[float, float]:
    """原始 720x1280 坐标转证明图 640x480 显示坐标。"""

    display_x = x * K_MODEL_WIDTH / K_CROP_WIDTH
    display_y = (y - K_CROP_OFFSET_Y) * K_MODEL_HEIGHT / K_CROP_HEIGHT
    return display_x, display_y


def display_to_original_y(display_y: float) -> float:
    """证明图 y 坐标转回原始画面 y，用于按板端坐标系绘制拟合线。"""

    return K_CROP_OFFSET_Y + display_y * K_CROP_HEIGHT / K_MODEL_HEIGHT


def extract_navline(prob: np.ndarray, threshold: float) -> NavLine:
    """从低分辨率概率图提取导航线。

    输入 prob 为模型低分辨率 road 概率图，threshold 为二值化阈值；输出 NavLine。
    实现镜像板端早期行扫描逻辑：逐行找连续前景段 -> 概率加权中心 -> 最小二乘拟合。
    """

    line = NavLine()
    height, width = prob.shape
    if width <= 0 or height <= 0:
        return line

    row_step = max(1, height // 30)
    min_span = max(2, width // 40)
    y_stop = int(height * 0.35)

    # 自底向上扫描近端区域；近端对车体控制最关键，远端噪声不参与拟合。
    for y in range(height - 1, y_stop - 1, -row_step):
        best_start = -1
        best_end = -1
        best_sum = 0.0
        start = -1
        running_sum = 0.0

        # 单行内寻找概率和最高且宽度足够的连续前景段。
        for x in range(width):
            value = float(prob[y, x])
            if value >= threshold:
                if start < 0:
                    start = x
                    running_sum = 0.0
                running_sum += value

            ended = value < threshold or x == width - 1
            if start >= 0 and ended:
                end = x - 1 if value < threshold else x
                span = end - start + 1
                if span >= min_span and running_sum > best_sum:
                    best_start = start
                    best_end = end
                    best_sum = running_sum
                start = -1

        if best_start >= 0:
            # 对最佳段内像素按概率加权，得到更平滑的中心点。
            weighted_x = 0.0
            weight = 0.0
            for x in range(best_start, best_end + 1):
                value = float(prob[y, x])
                weighted_x += value * x
                weight += value
            cx = weighted_x / max(weight, 1e-5)
            original_x = cx * K_CROP_WIDTH / max(1, width - 1)
            original_y = K_CROP_OFFSET_Y + y * K_CROP_HEIGHT / max(1, height - 1)
            confidence = best_sum / max(1, best_end - best_start + 1)
            line.points.append(NavPoint(original_x, original_y, confidence))

    if len(line.points) < 6:
        return line

    # 用 x = slope*y + intercept 做最小二乘拟合，和板端 UART/OSD 坐标定义保持一致。
    sum_y = sum(point.y for point in line.points)
    sum_x = sum(point.x for point in line.points)
    sum_yy = sum(point.y * point.y for point in line.points)
    sum_yx = sum(point.y * point.x for point in line.points)
    sum_conf = sum(point.confidence for point in line.points)
    n = float(len(line.points))
    denom = n * sum_yy - sum_y * sum_y
    if abs(denom) < 1e-4:
        return line

    line.slope = (n * sum_yx - sum_y * sum_x) / denom
    line.intercept = (sum_x - line.slope * sum_y) / n
    line.bottom_x = line.slope * (K_ORIGINAL_HEIGHT - 1) + line.intercept
    line.deviation_px = line.bottom_x - (K_ORIGINAL_WIDTH / 2.0)
    crop_bottom_y = K_CROP_OFFSET_Y + K_CROP_HEIGHT - 1
    line.crop_bottom_x = line.slope * crop_bottom_y + line.intercept
    line.crop_deviation_px = line.crop_bottom_x - (K_CROP_WIDTH / 2.0)
    line.angle_deg = math.atan(line.slope) * 180.0 / math.pi
    line.confidence = sum_conf / n
    line.valid = True
    return line


def line_errors(pred: NavLine, target: NavLine) -> tuple[float | None, float | None]:
    """计算预测线与目标线误差。

    输出 20 个近端采样点平均误差和 crop 底部误差；任一线无效则返回 None。
    """

    if not pred.valid or not target.valid:
        return None, None
    y0 = K_CROP_OFFSET_Y + int(K_CROP_HEIGHT * 0.35)
    y1 = K_CROP_OFFSET_Y + K_CROP_HEIGHT - 1
    ys = np.linspace(y0, y1, 20, dtype=np.float32)
    errors = [
        abs((pred.slope * float(y) + pred.intercept) - (target.slope * float(y) + target.intercept))
        for y in ys
    ]
    bottom_error = abs(pred.crop_bottom_x - target.crop_bottom_x)
    return float(np.mean(errors)), float(bottom_error)


def sample_iou(pred: np.ndarray, target: np.ndarray) -> float:
    """计算单样本二值 mask IoU；目标和预测都为空时返回 1.0。"""

    inter = np.logical_and(pred, target).sum()
    union = np.logical_or(pred, target).sum()
    if union == 0:
        return 1.0
    return float(inter / union)


def draw_line(draw: ImageDraw.ImageDraw, line: NavLine, color: tuple[int, int, int], width: int) -> None:
    """在证明图上绘制导航线和中心点。

    输入 PIL draw、NavLine、颜色和线宽；无效线直接跳过。
    """

    if not line.valid:
        return
    points: list[tuple[float, float]] = []
    for display_y in np.linspace(0, K_MODEL_HEIGHT - 1, 24, dtype=np.float32):
        original_y = display_to_original_y(float(display_y))
        original_x = line.slope * original_y + line.intercept
        display_x, mapped_y = original_to_display(original_x, original_y)
        if -50 <= display_x <= K_MODEL_WIDTH + 50:
            points.append((display_x, mapped_y))
    if len(points) >= 2:
        draw.line(points, fill=color, width=width)
    for point in line.points:
        x, y = original_to_display(point.x, point.y)
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)


def make_overlay(
    image: torch.Tensor,
    pred_mask: np.ndarray,
    target_mask: np.ndarray,
    pred_line: NavLine,
    target_line: NavLine,
    name: str,
    iou: float,
    line_error: float | None,
    out_path: Path,
) -> None:
    """生成单样本证明图。

    输入图像、预测/目标 mask、预测/目标线和指标；输出叠加 jpg。
    黄色为预测导航线，绿色为目标 mask 提取的参考线。
    """

    base = (image.squeeze(0).numpy() * 255.0).clip(0, 255).astype(np.uint8)
    rgb = Image.fromarray(base, mode="L").convert("RGB")
    target_layer = Image.new("RGB", rgb.size, (20, 190, 60))
    pred_layer = Image.new("RGB", rgb.size, (230, 80, 35))
    rgb.paste(target_layer, mask=Image.fromarray((target_mask.astype(np.uint8) * 70), mode="L"))
    rgb.paste(pred_layer, mask=Image.fromarray((pred_mask.astype(np.uint8) * 95), mode="L"))

    draw = ImageDraw.Draw(rgb)
    draw_line(draw, target_line, (40, 255, 80), 3)
    draw_line(draw, pred_line, (255, 230, 30), 4)

    status = "valid" if pred_line.valid else "invalid"
    error_text = "na" if line_error is None else f"{line_error:.1f}px"
    text = (
        f"{name} | {status} | IoU {iou:.3f} | line_err {error_text} | "
        f"crop_dev {pred_line.crop_deviation_px:.1f}px | angle {pred_line.angle_deg:.1f}deg"
    )
    draw.rectangle((0, 0, K_MODEL_WIDTH, 28), fill=(0, 0, 0))
    draw.text((6, 8), text[:130], fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(out_path, quality=92)


def build_contact_sheet(image_paths: list[Path], output_path: Path, columns: int = 4, thumb_width: int = 320) -> None:
    """把若干 overlay 合成联系表。

    输入图片路径列表和输出路径；输出 contact_sheet.jpg，便于一次性查看多样本效果。
    """

    if not image_paths:
        return
    thumbs: list[Image.Image] = []
    for path in image_paths:
        img = Image.open(path).convert("RGB")
        ratio = thumb_width / img.width
        thumb_height = int(round(img.height * ratio))
        thumbs.append(img.resize((thumb_width, thumb_height), Image.Resampling.BILINEAR))

    rows = int(math.ceil(len(thumbs) / columns))
    thumb_height = thumbs[0].height
    sheet = Image.new("RGB", (columns * thumb_width, rows * thumb_height), (20, 20, 20))
    for index, img in enumerate(thumbs):
        x = (index % columns) * thumb_width
        y = (index // columns) * thumb_height
        sheet.paste(img, (x, y))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path, quality=92)


def main() -> None:
    """执行主机端导航线证明流程。

    流程：加载模型 -> 对 split 推理 -> 提取预测/目标导航线 -> 保存 overlay、mask、CSV 和汇总指标。
    """

    args = parse_args()
    if args.threshold < 0.0 or args.threshold > 1.0:
        raise SystemExit("--threshold must be between 0 and 1")
    if args.max_samples < 0:
        raise SystemExit("--max-samples must be >= 0")
    if args.contact_sheet_count < 0:
        raise SystemExit("--contact-sheet-count must be >= 0")

    device = torch.device(args.device)
    dataset = RoadDataset(args.data_dir, args.split, augment=False, return_name=True)
    if len(dataset) == 0:
        raise SystemExit(f"{args.split} split is empty")

    model = load_model(args.checkpoint, device)
    sample_count = len(dataset) if args.max_samples == 0 else min(args.max_samples, len(dataset))

    overlays_dir = args.output_dir / "overlays"
    masks_dir = args.output_dir / "pred_masks"
    rows: list[dict[str, object]] = []  # proof_samples.csv 的逐样本记录。
    overlay_paths: list[Path] = []  # 已生成 overlay 路径，用于 contact sheet。
    ious: list[float] = []  # 每个样本的全尺寸 mask IoU。
    line_error_values: list[float] = []  # 有效线样本的平均线误差。
    crop_bottom_error_values: list[float] = []  # 有效线样本的 crop 底部误差。
    valid_count = 0  # 预测线 valid 的样本数。
    target_valid_count = 0  # 目标 mask 参考线 valid 的样本数。

    with torch.no_grad():
        # 逐样本生成证明材料，保留每张图的 overlay 和 mask，便于赛前人工复核。
        for index in range(sample_count):
            name, image, mask = dataset[index]
            logits = model(image.unsqueeze(0).to(device))
            prob_low = torch.sigmoid(logits).squeeze().detach().cpu().numpy().astype(np.float32)
            prob_full = F.interpolate(
                torch.from_numpy(prob_low[None, None, ...]),
                size=mask.shape[-2:],
                mode="bilinear",
                align_corners=False,
            ).squeeze().numpy()

            pred_mask = prob_full >= args.threshold
            target_mask = mask.squeeze().numpy() > 0.5
            target_low = resize_nearest(target_mask.astype(np.float32), (prob_low.shape[1], prob_low.shape[0]))

            pred_line = extract_navline(prob_low, args.threshold)
            target_line = extract_navline(target_low, 0.5)
            line_error, bottom_error = line_errors(pred_line, target_line)
            iou = sample_iou(pred_mask, target_mask)

            if pred_line.valid:
                valid_count += 1
            if target_line.valid:
                target_valid_count += 1
            if line_error is not None:
                line_error_values.append(line_error)
            if bottom_error is not None:
                crop_bottom_error_values.append(bottom_error)
            ious.append(iou)

            overlay_path = overlays_dir / f"{index:03d}_{name}.jpg"
            make_overlay(image, pred_mask, target_mask, pred_line, target_line, name, iou, line_error, overlay_path)
            overlay_paths.append(overlay_path)

            mask_path = masks_dir / f"{index:03d}_{name}.png"
            masks_dir.mkdir(parents=True, exist_ok=True)
            Image.fromarray((pred_mask.astype(np.uint8) * 255), mode="L").save(mask_path)

            rows.append(
                {
                    "index": index,
                    "name": name,
                    "iou": iou,
                    "pred_valid": int(pred_line.valid),
                    "target_valid": int(target_line.valid),
                    "pred_points": len(pred_line.points),
                    "pred_confidence": pred_line.confidence,
                    "deviation_px_original720": pred_line.deviation_px,
                    "crop_deviation_px_original720": pred_line.crop_deviation_px,
                    "angle_deg": pred_line.angle_deg,
                    "line_error_px_original720": line_error,
                    "crop_bottom_error_px_original720": bottom_error,
                    "overlay": str(overlay_path),
                    "pred_mask": str(mask_path),
                }
            )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.output_dir / "proof_samples.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    contact_sheet_path = args.output_dir / "contact_sheet.jpg"
    build_contact_sheet(overlay_paths[: args.contact_sheet_count], contact_sheet_path)

    metrics = {
        "split": args.split,
        "samples": sample_count,
        "threshold": args.threshold,
        "mean_iou": float(np.mean(ious)) if ious else 0.0,
        "median_iou": float(np.median(ious)) if ious else 0.0,
        "valid_navline_samples": valid_count,
        "invalid_navline_samples": sample_count - valid_count,
        "target_valid_navline_samples": target_valid_count,
        "mean_line_error_px_original720": float(np.mean(line_error_values)) if line_error_values else None,
        "mean_crop_bottom_error_px_original720": float(np.mean(crop_bottom_error_values))
        if crop_bottom_error_values
        else None,
        "overlays_dir": str(overlays_dir),
        "pred_masks_dir": str(masks_dir),
        "samples_csv": str(csv_path),
        "contact_sheet": str(contact_sheet_path),
        "note": "Yellow line is predicted navigation line; green line is target-mask reference line.",
    }
    metrics_path = args.output_dir / "proof_metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
