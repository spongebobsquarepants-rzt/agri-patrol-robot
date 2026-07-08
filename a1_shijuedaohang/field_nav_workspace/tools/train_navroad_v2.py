#!/usr/bin/env python3
"""Train a v2 lightweight grayscale road model with skip fusion."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    from torch.utils.data import DataLoader, Dataset
except ImportError as exc:  # pragma: no cover - runtime dependency guard
    raise SystemExit("PyTorch is required for training this model.") from exc


def set_seed(seed: int) -> None:
    """设置 Python/Numpy/PyTorch 随机种子。

    输入 seed；输出为空。作用是让数据增强、初始化和训练 split 复现实验结果。
    """

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class RoadDataset(Dataset):
    """v2 道路分割数据集。

    输入 data_dir/split/augment/return_name；输出灰度图张量、mask 张量，可选返回样本名。
    """

    def __init__(self, data_dir: Path, split: str, augment: bool = False, return_name: bool = False) -> None:
        self.data_dir = data_dir
        self.names = [
            line.strip()
            for line in (data_dir / "splits" / f"{split}.txt").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.augment = augment
        self.return_name = return_name

    def __len__(self) -> int:
        """返回当前 split 样本数量。"""

        return len(self.names)

    def _augment(self, image: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """执行轻量图像增强。

        输入 0~1 灰度 image 和二值 mask；输出增强后的 image/mask。
        注意：增强只改变图像外观或水平翻转，不破坏 mask 与图像对应关系。
        """

        if random.random() < 0.5:
            image = np.ascontiguousarray(image[:, ::-1])
            mask = np.ascontiguousarray(mask[:, ::-1])

        if random.random() < 0.9:
            mean = float(image.mean())
            contrast = random.uniform(0.75, 1.30)
            gain = random.uniform(0.82, 1.18)
            bias = random.uniform(-0.10, 0.10)
            image = (image - mean) * contrast + mean
            image = image * gain + bias

        if random.random() < 0.45:
            gamma = random.uniform(0.70, 1.45)
            image = np.power(np.clip(image, 0.0, 1.0), gamma)

        if random.random() < 0.35:
            # 模拟侧向阴影/开窗强光造成的横向亮度变化，提高现场鲁棒性。
            h, w = image.shape
            xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
            center = random.uniform(0.0, 1.0)
            width = random.uniform(0.18, 0.45)
            strength = random.uniform(0.18, 0.45)
            profile = np.clip(1.0 - np.abs(xs - center) / width, 0.0, 1.0)
            if random.random() < 0.5:
                profile = profile[::-1]
            image = image * (1.0 - strength * profile[None, :])

        if random.random() < 0.18:
            radius = random.uniform(0.35, 1.10)
            pil = Image.fromarray(np.clip(image * 255.0, 0, 255).astype(np.uint8))
            image = np.asarray(pil.filter(ImageFilter.GaussianBlur(radius=radius)), dtype=np.float32) / 255.0

        image = np.clip(image, 0.0, 1.0)
        return image, mask

    def __getitem__(self, index: int):
        """读取单个样本并转为 NCHW 前的 1xHxW 张量。

        返回值根据 return_name 决定是否带样本名，供评估和失败预览定位文件。
        """

        name = self.names[index]
        image = np.asarray(Image.open(self.data_dir / "images" / f"{name}.png").convert("L"), dtype=np.float32) / 255.0
        mask = np.asarray(Image.open(self.data_dir / "masks" / f"{name}.png").convert("L"), dtype=np.float32)
        mask = (mask > 127).astype(np.float32)
        if self.augment:
            image, mask = self._augment(image, mask)
        image_tensor = torch.from_numpy(np.ascontiguousarray(image[None, ...]))
        mask_tensor = torch.from_numpy(np.ascontiguousarray(mask[None, ...]))
        if self.return_name:
            return name, image_tensor, mask_tensor
        return image_tensor, mask_tensor


class ConvBNAct(nn.Module):
    """Conv2d + BatchNorm + ReLU 基础块，保持算子简单以兼容 A1 ONNX 转换。"""

    def __init__(self, in_channels: int, out_channels: int, stride: int = 1, dilation: int = 1) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(
                in_channels,
                out_channels,
                3,
                stride=stride,
                padding=dilation,
                dilation=dilation,
                bias=False,
            ),
            nn.BatchNorm2d(out_channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """输入 NCHW 特征，输出卷积归一化激活后的特征。"""

        return self.block(x)


class DepthwiseSeparable(nn.Module):
    """深度可分离卷积块。

    输入通道数 channels；输出通道数不变，用较低计算量扩大感受野。
    """

    def __init__(self, channels: int, dilation: int = 1) -> None:
        super().__init__()
        self.block = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=dilation, dilation=dilation, groups=channels, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
            nn.Conv2d(channels, channels, 1, bias=False),
            nn.BatchNorm2d(channels),
            nn.ReLU(inplace=True),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """前向传播；输入输出 shape 保持一致。"""

        return self.block(x)


def scaled_channels(base: int, width_mult: float) -> int:
    """按 width_mult 缩放通道数，并保证最少 4 通道。"""

    return max(4, int(round(base * width_mult)))


class SkipFusionNavRoadNet(nn.Module):
    """带浅层跳连融合的 stride-4 灰度道路分割网络。"""

    def __init__(self, width_mult: float = 1.0) -> None:
        super().__init__()
        c1 = scaled_channels(12, width_mult)
        c2 = scaled_channels(24, width_mult)
        c3 = scaled_channels(40, width_mult)
        cf = scaled_channels(32, width_mult)
        self.width_mult = float(width_mult)
        self.stem = nn.Sequential(ConvBNAct(1, c1), ConvBNAct(c1, c1))
        self.down1 = nn.Sequential(ConvBNAct(c1, c2, stride=2), DepthwiseSeparable(c2))
        self.down2 = nn.Sequential(ConvBNAct(c2, c3, stride=2), DepthwiseSeparable(c3))
        self.context = nn.Sequential(DepthwiseSeparable(c3, dilation=2), DepthwiseSeparable(c3, dilation=3))
        self.fuse = nn.Sequential(ConvBNAct(c1 + c2 + c3, cf), DepthwiseSeparable(cf))
        self.head = nn.Conv2d(cf, 1, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """输出低分辨率 road logits。

        输入为 N,1,480,640；输出为 N,1,120,160。浅层/中层/上下文特征在 stride-4 尺度融合。
        """

        stem = self.stem(x)
        down1 = self.down1(stem)
        down2 = self.down2(down1)
        context = self.context(down2)
        stem_skip = F.avg_pool2d(stem, kernel_size=4, stride=4)
        down1_skip = F.avg_pool2d(down1, kernel_size=2, stride=2)
        fused = torch.cat([context, down1_skip, stem_skip], dim=1)
        return self.head(self.fuse(fused))


def dice_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """计算 Dice loss；输入 logits 和同尺寸 target，输出 batch 平均损失。"""

    prob = torch.sigmoid(logits)
    inter = (prob * target).sum(dim=(1, 2, 3))
    denom = prob.sum(dim=(1, 2, 3)) + target.sum(dim=(1, 2, 3))
    return 1.0 - ((2.0 * inter + 1.0) / (denom + 1.0)).mean()


def focal_bce_loss(logits: torch.Tensor, target: torch.Tensor, gamma: float = 2.0) -> torch.Tensor:
    """计算带类别权重的 focal BCE。

    输入 logits/target/gamma；输出平均损失，用于强调难分像素。
    """

    bce = F.binary_cross_entropy_with_logits(logits, target, reduction="none")
    prob = torch.sigmoid(logits)
    pt = prob * target + (1.0 - prob) * (1.0 - target)
    alpha = target * 0.60 + (1.0 - target) * 0.40
    return (alpha * (1.0 - pt).pow(gamma) * bce).mean()


def segmentation_loss(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """组合分割损失。

    输入模型低分辨率 logits 和原始 mask；输出 0.70*BCE + Dice + 0.40*FocalBCE。
    """

    target = F.interpolate(mask, size=logits.shape[-2:], mode="nearest")
    bce = F.binary_cross_entropy_with_logits(logits, target)
    return 0.70 * bce + dice_loss(logits, target) + 0.40 * focal_bce_loss(logits, target)


def row_centers(mask: np.ndarray, threshold: float = 0.5) -> dict[int, float]:
    """按行扫描 mask 并取整行前景平均中心。

    输入 HxW mask；输出 y -> x_center，用于训练期估算导航中心线误差。
    """

    h, w = mask.shape
    step = max(1, h // 32)
    min_span = max(2, w // 40)
    points: dict[int, float] = {}
    for y in range(h - 1, int(h * 0.35), -step):
        xs = np.where(mask[y] > threshold)[0]
        if xs.size >= min_span:
            points[y] = float(xs.mean())
    return points


def row_centers_best_segment(mask: np.ndarray, threshold: float = 0.5) -> dict[int, float]:
    """按行选择最大连续前景段中心。

    输入 HxW mask；输出 y -> segment_center，更接近板端后处理对主道路段的选择方式。
    """

    h, w = mask.shape
    step = max(1, h // 32)
    min_span = max(2, w // 40)
    points: dict[int, float] = {}
    for y in range(h - 1, int(h * 0.35), -step):
        row = mask[y]
        best_start = -1
        best_end = -1
        best_sum = 0.0
        start = -1
        running_sum = 0.0
        # 单行内寻找概率和最大的连续前景段，忽略小碎片。
        for x, value in enumerate(row):
            if value > threshold:
                if start < 0:
                    start = x
                    running_sum = 0.0
                running_sum += float(value)
            ended = value <= threshold or x == w - 1
            if start >= 0 and ended:
                end = x - 1 if value <= threshold else x
                span = end - start + 1
                if span >= min_span and running_sum > best_sum:
                    best_start = start
                    best_end = end
                    best_sum = running_sum
                start = -1
        if best_start >= 0:
            points[y] = float((best_start + best_end) * 0.5)
    return points


def centerline_errors(pred: np.ndarray, target: np.ndarray, mode: str = "all") -> tuple[float | None, float | None]:
    """计算预测 mask 和目标 mask 的中心线误差。

    输出 mean_center_error 和 bottom_error；共同扫描行少于 4 行时返回 None，避免无意义指标。
    """

    if mode == "best_segment":
        pred_points = row_centers_best_segment(pred)
        target_points = row_centers_best_segment(target)
    else:
        pred_points = row_centers(pred)
        target_points = row_centers(target)
    common = sorted(set(pred_points) & set(target_points))
    if len(common) < 4:
        return None, None
    errors = [abs(pred_points[y] - target_points[y]) for y in common]
    bottom_y = max(common)
    return float(np.mean(errors)), float(abs(pred_points[bottom_y] - target_points[bottom_y]))


def batch_metrics(logits: torch.Tensor, mask: torch.Tensor, threshold: float = 0.5) -> dict[str, float]:
    """计算一个 batch 的 IoU 和中心线误差累积项。

    输出为 sum/count 形式，便于 run_epoch 按样本数聚合。
    """

    prob = torch.sigmoid(logits)
    prob_full = F.interpolate(prob, size=mask.shape[-2:], mode="bilinear", align_corners=False)
    pred = prob_full > threshold
    target = mask > 0.5
    inter = (pred & target).sum(dim=(1, 2, 3)).float()
    union = (pred | target).sum(dim=(1, 2, 3)).float().clamp_min(1.0)
    ious = (inter / union).detach().cpu().numpy().tolist()
    center_errors: list[float] = []
    bottom_errors: list[float] = []
    invalid = 0
    pred_np = pred.squeeze(1).detach().cpu().numpy().astype(np.float32)
    target_np = target.squeeze(1).detach().cpu().numpy().astype(np.float32)
    # 中心线误差在 CPU/Numpy 上计算，避免把评估后处理放进训练图。
    for pred_item, target_item in zip(pred_np, target_np):
        center_error, bottom_error = centerline_errors(pred_item, target_item)
        if center_error is None or bottom_error is None:
            invalid += 1
        else:
            center_errors.append(center_error)
            bottom_errors.append(bottom_error)
    return {
        "iou_sum": float(np.sum(ious)),
        "center_error_sum": float(np.sum(center_errors)),
        "bottom_error_sum": float(np.sum(bottom_errors)),
        "center_count": float(len(center_errors)),
        "invalid": float(invalid),
    }


def run_epoch(model, loader, optimizer, device: torch.device) -> dict[str, float | None]:
    """运行一个训练或验证 epoch。

    optimizer 为 None 时不反向传播；返回 loss、IoU、中心线误差和 invalid 样本数。
    """

    training = optimizer is not None
    model.train(training)
    total_loss = 0.0
    total_iou = 0.0
    total_center_error = 0.0
    total_bottom_error = 0.0
    center_count = 0.0
    invalid = 0.0
    count = 0
    for image, mask in loader:
        image = image.to(device)
        mask = mask.to(device)
        with torch.set_grad_enabled(training):
            logits = model(image)
            loss = segmentation_loss(logits, mask)
            if training:
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                optimizer.step()
        batch = image.size(0)
        metrics = batch_metrics(logits.detach(), mask)
        total_loss += float(loss.detach().cpu()) * batch
        total_iou += metrics["iou_sum"]
        total_center_error += metrics["center_error_sum"]
        total_bottom_error += metrics["bottom_error_sum"]
        center_count += metrics["center_count"]
        invalid += metrics["invalid"]
        count += batch
    return {
        "loss": total_loss / max(count, 1),
        "iou": total_iou / max(count, 1),
        "mean_center_error_px": total_center_error / center_count if center_count else None,
        "mean_bottom_error_px": total_bottom_error / center_count if center_count else None,
        "invalid_centerline_samples": int(invalid),
    }


def parse_args() -> argparse.Namespace:
    """解析 v2 训练参数，包括早停、通道宽度倍率和优化器配置。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--run-dir", default=Path("field_nav_workspace/runs/navroad_v2"), type=Path)
    parser.add_argument("--epochs", default=120, type=int)
    parser.add_argument("--batch-size", default=8, type=int)
    parser.add_argument("--lr", default=8e-4, type=float)
    parser.add_argument("--weight-decay", default=1e-4, type=float)
    parser.add_argument("--patience", default=15, type=int)
    parser.add_argument("--min-delta", default=1e-4, type=float)
    parser.add_argument("--width-mult", default=1.0, type=float)
    parser.add_argument("--seed", default=20260427, type=int)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--num-workers", default=0, type=int)
    return parser.parse_args()


def export_onnx(model: nn.Module, path: Path, device: torch.device) -> None:
    """导出固定输入尺寸 ONNX。

    输入模型/路径/设备；输出 navroad_640x480.onnx，后续交给 A1 AI Tool 转 .m1model。
    """

    model.eval()
    dummy = torch.zeros(1, 1, 480, 640, device=device)
    torch.onnx.export(
        model,
        dummy,
        path,
        input_names=["image"],
        output_names=["road_logits"],
        opset_version=11,
        do_constant_folding=True,
        dynamo=False,
    )


def is_better(row: dict, best_score: float, args: argparse.Namespace) -> tuple[bool, float]:
    """判断当前 epoch 是否优于历史最佳。

    输入一行训练日志和 best_score；输出是否提升及当前 score。
    评分兼顾 val IoU 和中心线误差，避免只优化面积重叠而导航线偏差过大。
    """

    val = row["val"]
    center_error = val["mean_center_error_px"] if val["mean_center_error_px"] is not None else 640.0
    score = float(val["iou"]) - 0.05 * (float(center_error) / 640.0)
    return score > best_score + args.min_delta, score


def main() -> None:
    """执行 v2 训练主流程。

    流程：固定随机种子 -> 加载 split -> 训练 SkipFusionNavRoadNet -> 早停 -> 保存 best/last/ONNX/summary。
    """

    args = parse_args()
    if args.epochs < 1:
        raise SystemExit("--epochs must be >= 1")
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.patience < 1:
        raise SystemExit("--patience must be >= 1")
    if args.width_mult <= 0.0:
        raise SystemExit("--width-mult must be > 0")

    set_seed(args.seed)
    args.run_dir.mkdir(parents=True, exist_ok=True)
    device = torch.device(args.device)
    train_set = RoadDataset(args.data_dir, "train", augment=True)
    val_set = RoadDataset(args.data_dir, "val", augment=False)
    if len(train_set) == 0:
        raise SystemExit("train split is empty")
    if len(val_set) == 0:
        raise SystemExit("val split is empty")

    train_loader = DataLoader(
        train_set,
        batch_size=args.batch_size,
        shuffle=True,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )
    val_loader = DataLoader(
        val_set,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
        pin_memory=device.type == "cuda",
    )

    model = SkipFusionNavRoadNet(width_mult=args.width_mult).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=max(args.epochs, 1))
    best_score = -math.inf  # 复合选模分数，越高越好。
    bad_epochs = 0  # 连续未提升 epoch 数，达到 patience 后早停。
    history: list[dict] = []  # 每个 epoch 的完整指标，写入 history.json。
    config = {
        "width_mult": args.width_mult,
        "input_shape": [1, 480, 640],
        "output_stride": 4,
        "loss": "0.70*bce + dice + 0.40*focal_bce",
    }

    # 训练循环：每轮训练、验证、调学习率，并按复合分数保存 best.pt。
    for epoch in range(1, args.epochs + 1):
        train_metrics = run_epoch(model, train_loader, optimizer, device)
        val_metrics = run_epoch(model, val_loader, None, device)
        scheduler.step()
        row = {
            "epoch": epoch,
            "lr": optimizer.param_groups[0]["lr"],
            "train": train_metrics,
            "val": val_metrics,
        }
        history.append(row)
        print(json.dumps(row, ensure_ascii=False))
        better, score = is_better(row, best_score, args)
        if better:
            best_score = score
            bad_epochs = 0
            torch.save(
                {
                    "model": model.state_dict(),
                    "epoch": epoch,
                    "val": val_metrics,
                    "score": best_score,
                    "config": config,
                },
                args.run_dir / "best.pt",
            )
        else:
            bad_epochs += 1
            if bad_epochs >= args.patience:
                print(f"early stopping at epoch {epoch}, best score {best_score:.5f}")
                break

    torch.save({"model": model.state_dict(), "epoch": history[-1]["epoch"], "config": config}, args.run_dir / "last.pt")
    (args.run_dir / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")

    best = torch.load(args.run_dir / "best.pt", map_location=device)
    model.load_state_dict(best["model"])
    export_onnx(model, args.run_dir / "navroad_640x480.onnx", device)
    summary = {
        "best_epoch": best["epoch"],
        "best_val": best["val"],
        "best_score": best["score"],
        "onnx": str(args.run_dir / "navroad_640x480.onnx"),
        "config": config,
    }
    (args.run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
