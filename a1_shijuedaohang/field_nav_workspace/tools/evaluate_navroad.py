#!/usr/bin/env python3
"""Evaluate a trained TinyNavRoadNet checkpoint on prepared split data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F

from train_navroad import RoadDataset, TinyNavRoadNet


def row_center(mask: np.ndarray, threshold: float = 0.5) -> list[tuple[int, float]]:
    """从 mask 中按行提取道路中心点。

    输入 HxW mask 和阈值；输出 (y, x_center) 列表，仅扫描下方 65% 近端区域。
    """

    points: list[tuple[int, float]] = []
    h, w = mask.shape
    for y in range(h - 1, int(h * 0.35), -max(1, h // 32)):
        xs = np.where(mask[y] > threshold)[0]
        if xs.size > max(2, w // 40):
            points.append((y, float(xs.mean())))
    return points


def center_error(pred: np.ndarray, target: np.ndarray) -> float | None:
    """计算预测/目标中心线平均横向误差。

    输出单位为像素；共同有效扫描行少于 4 行时返回 None，表示无法稳定评估。
    """

    pred_points = dict(row_center(pred))
    target_points = dict(row_center(target))
    common = sorted(set(pred_points) & set(target_points))
    if len(common) < 4:
        return None
    return float(np.mean([abs(pred_points[y] - target_points[y]) for y in common]))


def parse_args() -> argparse.Namespace:
    """解析 v1 checkpoint 评估参数，输出数据目录、权重、split 和设备。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return parser.parse_args()


def main() -> None:
    """执行 v1 模型评估。

    流程：加载 checkpoint -> 对 split 推理 -> 计算 IoU 和中心线误差 -> 打印 JSON 指标。
    """

    args = parse_args()
    device = torch.device(args.device)
    dataset = RoadDataset(args.data_dir, args.split, augment=False)
    if len(dataset) == 0:
        raise SystemExit(f"{args.split} split is empty")

    model = TinyNavRoadNet().to(device)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    model.load_state_dict(checkpoint["model"])
    model.eval()

    ious: list[float] = []  # 每个样本的 mask IoU。
    errors: list[float] = []  # 可提取中心线样本的平均横向误差。
    invalid = 0  # 无法提取有效中心线的样本数。
    with torch.no_grad():
        # 逐样本推理，评估逻辑保持简单，避免 batch 维度掩盖单样本失败。
        for image, mask in dataset:
            image = image.unsqueeze(0).to(device)
            logits = model(image)
            prob = torch.sigmoid(logits)
            prob = F.interpolate(prob, size=mask.shape[-2:], mode="bilinear", align_corners=False)
            pred = (prob.squeeze().cpu().numpy() > 0.5)
            target = (mask.squeeze().numpy() > 0.5)
            inter = np.logical_and(pred, target).sum()
            union = max(1, np.logical_or(pred, target).sum())
            ious.append(float(inter / union))
            err = center_error(pred.astype(np.float32), target.astype(np.float32))
            if err is None:
                invalid += 1
            else:
                errors.append(err)

    metrics = {
        "split": args.split,
        "samples": len(dataset),
        "mean_iou": float(np.mean(ious)) if ious else 0.0,
        "mean_center_error_px": float(np.mean(errors)) if errors else None,
        "invalid_centerline_samples": invalid,
    }
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
