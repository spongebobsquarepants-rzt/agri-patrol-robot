#!/usr/bin/env python3
"""Compare PyTorch and ONNX logits for the v2 NavRoad model."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_navroad_v2 import RoadDataset, SkipFusionNavRoadNet  # noqa: E402


def parse_args() -> argparse.Namespace:
    """解析 PyTorch/ONNX 一致性比较参数。

    输出数据目录、checkpoint、onnx 路径、split、抽样数量和运行设备。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--onnx", required=True, type=Path)
    parser.add_argument("--split", default="test")
    parser.add_argument("--samples", default=16, type=int)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def main() -> None:
    """比较 PyTorch checkpoint 与 ONNX 输出 logits。

    核心用途是在交给 A1 转换前确认 ONNX 导出没有数值漂移；只比较 logits，不包含后处理。
    """

    args = parse_args()
    if args.samples < 1:
        raise SystemExit("--samples must be >= 1")

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise SystemExit("onnxruntime is required for ONNX comparison. Install it on the PC side first.") from exc

    device = torch.device(args.device)
    checkpoint = torch.load(args.checkpoint, map_location=device)
    config = checkpoint.get("config", {})
    model = SkipFusionNavRoadNet(width_mult=float(config.get("width_mult", 1.0))).to(device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    dataset = RoadDataset(args.data_dir, args.split, augment=False)
    if len(dataset) == 0:
        raise SystemExit(f"{args.split} split is empty")

    session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    diffs: list[float] = []  # 每个样本 mean(abs(torch_logits - onnx_logits))。
    max_diffs: list[float] = []  # 每个样本 max(abs(diff))，用于发现局部异常。

    with torch.no_grad():
        # 逐样本比较固定输入，避免 batch size 变化影响 ONNXRuntime 行为判断。
        for index in range(min(args.samples, len(dataset))):
            image, _ = dataset[index]
            torch_logits = model(image.unsqueeze(0).to(device)).cpu().numpy()
            onnx_logits = session.run(None, {input_name: image.unsqueeze(0).numpy()})[0]
            diffs.append(float(np.mean(np.abs(torch_logits - onnx_logits))))
            max_diffs.append(float(np.max(np.abs(torch_logits - onnx_logits))))

    metrics = {
        "split": args.split,
        "samples": len(diffs),
        "mean_abs_diff": float(np.mean(diffs)) if diffs else 0.0,
        "max_abs_diff_mean": float(np.mean(max_diffs)) if max_diffs else 0.0,
        "max_abs_diff_worst": float(np.max(max_diffs)) if max_diffs else 0.0,
    }
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
