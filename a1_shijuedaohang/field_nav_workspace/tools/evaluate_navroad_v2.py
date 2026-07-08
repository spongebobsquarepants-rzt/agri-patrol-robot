#!/usr/bin/env python3
"""Evaluate a v2 NavRoad checkpoint and generate failure previews."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_navroad_v2 import RoadDataset, SkipFusionNavRoadNet, centerline_errors, row_centers  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析 v2 评估参数。

    输出数据目录、checkpoint、split、阈值、失败样本预览目录和失败判定阈值。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--threshold", default=0.5, type=float)
    parser.add_argument(
        "--failure-dir",
        default=Path("field_nav_workspace/runs/navroad_v2/failures"),
        type=Path,
    )
    parser.add_argument("--failure-iou", default=0.55, type=float)
    parser.add_argument("--failure-center-error", default=45.0, type=float)
    parser.add_argument("--max-failures", default=80, type=int)
    parser.add_argument("--metrics-out", default=None, type=Path)
    return parser.parse_args()


def load_model(checkpoint_path: Path, device: torch.device) -> SkipFusionNavRoadNet:
    """加载 v2 checkpoint 并恢复模型结构。

    输入 checkpoint 路径和设备；输出 eval 模式的 SkipFusionNavRoadNet。
    """

    checkpoint = torch.load(checkpoint_path, map_location=device)
    config = checkpoint.get("config", {})
    model = SkipFusionNavRoadNet(width_mult=float(config.get("width_mult", 1.0))).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model


def sample_iou(pred: np.ndarray, target: np.ndarray) -> float:
    """计算单样本二值 mask IoU；union 为 0 时按 1 防止除零。"""

    inter = np.logical_and(pred, target).sum()
    union = max(1, np.logical_or(pred, target).sum())
    return float(inter / union)


def make_failure_preview(
    image: torch.Tensor,
    pred: np.ndarray,
    target: np.ndarray,
    out_path: Path,
    name: str,
    iou: float,
    center_error: float | None,
    bottom_error: float | None,
) -> None:
    """生成失败样本可视化。

    输入灰度图、预测 mask、目标 mask、指标和输出路径；输出带红/绿叠加和中心点标记的 jpg。
    """

    base = (image.squeeze(0).numpy() * 255.0).clip(0, 255).astype(np.uint8)
    rgb = Image.fromarray(base, mode="L").convert("RGB")
    pred_layer = Image.new("RGB", rgb.size, (255, 40, 40))
    target_layer = Image.new("RGB", rgb.size, (40, 220, 80))
    rgb.paste(target_layer, mask=Image.fromarray((target.astype(np.uint8) * 95), mode="L"))
    rgb.paste(pred_layer, mask=Image.fromarray((pred.astype(np.uint8) * 95), mode="L"))

    draw = ImageDraw.Draw(rgb)
    target_centers = row_centers(target.astype(np.float32))
    pred_centers = row_centers(pred.astype(np.float32))
    # 绿色圆点为目标中心，红色方块为预测中心，便于定位偏移方向。
    for y, x in target_centers.items():
        draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(0, 255, 0))
    for y, x in pred_centers.items():
        draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=(255, 0, 0))
    text = (
        f"{name} iou={iou:.3f} center={center_error if center_error is not None else -1:.1f} "
        f"bottom={bottom_error if bottom_error is not None else -1:.1f}"
    )
    draw.rectangle((0, 0, rgb.size[0], 24), fill=(0, 0, 0))
    draw.text((6, 6), text[:120], fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rgb.save(out_path, quality=92)


def main() -> None:
    """执行 v2 模型评估并导出失败预览。

    流程：推理 split -> 计算 IoU/中心线误差 -> 按阈值保存失败图 -> 写 metrics JSON。
    """

    args = parse_args()
    if args.max_failures < 0:
        raise SystemExit("--max-failures must be >= 0")
    if args.threshold < 0.0 or args.threshold > 1.0:
        raise SystemExit("--threshold must be between 0 and 1")

    device = torch.device(args.device)
    dataset = RoadDataset(args.data_dir, args.split, augment=False, return_name=True)
    if len(dataset) == 0:
        raise SystemExit(f"{args.split} split is empty")

    model = load_model(args.checkpoint, device)
    failure_dir = args.failure_dir / args.split
    failure_count = 0  # 已写出的失败预览数量，受 max_failures 限制。
    ious: list[float] = []  # 所有样本 IoU。
    center_errors: list[float] = []  # 常规中心线平均误差。
    bottom_errors: list[float] = []  # 常规近端底部误差。
    best_segment_center_errors: list[float] = []  # 最大连续段中心线平均误差。
    best_segment_bottom_errors: list[float] = []  # 最大连续段近端底部误差。
    invalid = 0  # 常规中心线无法评估的样本数。
    invalid_best_segment = 0  # 最大连续段中心线无法评估的样本数。

    with torch.no_grad():
        # 逐样本评估，保留 name 以便失败图片能回溯到原始样本。
        for name, image, mask in dataset:
            logits = model(image.unsqueeze(0).to(device))
            prob = torch.sigmoid(logits)
            prob = F.interpolate(prob, size=mask.shape[-2:], mode="bilinear", align_corners=False)
            pred = (prob.squeeze().cpu().numpy() > args.threshold)
            target = (mask.squeeze().numpy() > 0.5)
            iou = sample_iou(pred, target)
            center_error, bottom_error = centerline_errors(pred.astype(np.float32), target.astype(np.float32))
            best_center_error, best_bottom_error = centerline_errors(
                pred.astype(np.float32),
                target.astype(np.float32),
                mode="best_segment",
            )
            ious.append(iou)
            if center_error is None or bottom_error is None:
                invalid += 1
            else:
                center_errors.append(center_error)
                bottom_errors.append(bottom_error)
            if best_center_error is None or best_bottom_error is None:
                invalid_best_segment += 1
            else:
                best_segment_center_errors.append(best_center_error)
                best_segment_bottom_errors.append(best_bottom_error)

            # 失败条件同时考虑 mask IoU 和导航中心线误差，更贴近实际控制需求。
            failed = (
                iou < args.failure_iou
                or center_error is None
                or center_error > args.failure_center_error
            )
            if failed and failure_count < args.max_failures:
                safe_center = "invalid" if center_error is None else f"{center_error:.0f}px"
                out_path = failure_dir / f"{name}_iou{iou:.3f}_center{safe_center}.jpg"
                make_failure_preview(image, pred, target, out_path, name, iou, center_error, bottom_error)
                failure_count += 1

    metrics_out = args.metrics_out or (args.failure_dir / f"{args.split}_metrics.json")
    metrics = {
        "split": args.split,
        "samples": len(dataset),
        "threshold": args.threshold,
        "mean_iou": float(np.mean(ious)) if ious else 0.0,
        "median_iou": float(np.median(ious)) if ious else 0.0,
        "mean_center_error_px": float(np.mean(center_errors)) if center_errors else None,
        "mean_bottom_error_px": float(np.mean(bottom_errors)) if bottom_errors else None,
        "invalid_centerline_samples": invalid,
        "mean_best_segment_center_error_px": float(np.mean(best_segment_center_errors))
        if best_segment_center_errors
        else None,
        "mean_best_segment_bottom_error_px": float(np.mean(best_segment_bottom_errors))
        if best_segment_bottom_errors
        else None,
        "invalid_best_segment_centerline_samples": invalid_best_segment,
        "failure_previews": failure_count,
        "failure_dir": str(failure_dir),
        "metrics_out": str(metrics_out),
    }
    metrics_out.parent.mkdir(parents=True, exist_ok=True)
    metrics_out.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
