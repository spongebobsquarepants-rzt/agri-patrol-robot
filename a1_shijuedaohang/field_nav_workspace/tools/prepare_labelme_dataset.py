#!/usr/bin/env python3
"""Prepare a grayscale road segmentation dataset from LabelMe annotations."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


VALID_LABELS = {"sand_road", "grassy_road"}


def parse_args() -> argparse.Namespace:
    """解析数据准备命令行参数。

    输入来自 CLI；输出 argparse.Namespace，包含原始数据集目录、输出尺寸、随机种子和 split 比例。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument(
        "--out-dir",
        default=Path("field_nav_workspace/data/processed_640x480"),
        type=Path,
    )
    parser.add_argument("--width", default=640, type=int)
    parser.add_argument("--height", default=480, type=int)
    parser.add_argument("--seed", default=20260427, type=int)
    parser.add_argument("--val-ratio", default=0.15, type=float)
    parser.add_argument("--test-ratio", default=0.15, type=float)
    parser.add_argument("--preview-count", default=24, type=int)
    return parser.parse_args()


def find_labelme_dir(dataset_root: Path) -> Path:
    """定位 LabelMe JSON 所在目录。

    输入 dataset_root 可以是数据集根目录或 labelme_data 本身；输出实际读取 JSON/JPG 的目录。
    """

    if (dataset_root / "labelme_data").is_dir():
        return dataset_root / "labelme_data"
    return dataset_root


def polygon_points(points: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    """把 LabelMe 点坐标转成 PIL polygon 可用的 float 二元组列表。"""

    return [(float(x), float(y)) for x, y in points]


def render_mask(annotation: dict, image_size: tuple[int, int]) -> Image.Image:
    """将 LabelMe polygon 标注渲染为二值道路 mask。

    输入 annotation 和原图尺寸；输出 L 模式 mask，前景 255 表示可通行 road。
    使用注意：sand_road/grassy_road 在此阶段合并为同一个前景类。
    """

    mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(mask)
    for shape in annotation.get("shapes", []):
        label = shape.get("label")
        if label not in VALID_LABELS:
            raise ValueError(f"unexpected label {label!r}")
        if shape.get("shape_type", "polygon") != "polygon":
            raise ValueError(f"unexpected shape type {shape.get('shape_type')!r}")
        pts = polygon_points(shape.get("points", []))
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
    return mask


def make_preview(gray: Image.Image, mask: Image.Image) -> Image.Image:
    """生成绿色半透明预览图。

    输入灰度图和 mask；输出 RGB 图，便于人工快速检查 polygon 转 mask 是否正确。
    """

    rgb = gray.convert("RGB")
    overlay = Image.new("RGB", rgb.size, (0, 255, 0))
    alpha = mask.point(lambda p: 96 if p > 0 else 0)
    rgb.paste(overlay, mask=alpha)
    return rgb


def write_split(path: Path, names: list[str]) -> None:
    """写入 split txt 文件。

    输入 path 和样本名列表；输出为一行一个样本名，末尾保留换行，兼容训练脚本读取。
    """

    path.write_text("\n".join(names) + "\n", encoding="utf-8")


def main() -> None:
    """执行 v1 数据准备流程。

    核心流程：读取 LabelMe JSON -> 渲染 mask -> 转灰度并缩放到模型尺寸 -> 随机划分 train/val/test。
    """

    args = parse_args()
    if args.width < 1 or args.height < 1:
        raise SystemExit("--width and --height must be positive")
    if args.val_ratio < 0.0 or args.test_ratio < 0.0 or args.val_ratio + args.test_ratio >= 1.0:
        raise SystemExit("--val-ratio and --test-ratio must be non-negative and sum to less than 1")

    labelme_dir = find_labelme_dir(args.dataset_root)
    out_dir = args.out_dir
    image_dir = out_dir / "images"
    mask_dir = out_dir / "masks"
    preview_dir = out_dir / "previews"
    split_dir = out_dir / "splits"
    for directory in (image_dir, mask_dir, preview_dir, split_dir):
        directory.mkdir(parents=True, exist_ok=True)

    json_files = sorted(labelme_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"no LabelMe json files found in {labelme_dir}")

    records: list[dict] = []  # 每个样本的来源、输出路径和原始尺寸记录。
    labels_seen: dict[str, int] = {}  # 统计标签出现次数，用于发现非预期类别。
    size_seen: dict[str, int] = {}  # 统计原始图片尺寸分布，便于判断数据集一致性。
    missing_images: list[str] = []  # 找不到同名图片的 JSON 名称。

    # 逐个样本读取标注、查找图片、生成灰度输入和二值 mask。
    for index, json_path in enumerate(json_files):
        annotation = json.loads(json_path.read_text(encoding="utf-8"))
        image_path = labelme_dir / annotation.get("imagePath", f"{json_path.stem}.jpg")
        if not image_path.exists():
            image_path = json_path.with_suffix(".jpg")
        if not image_path.exists():
            missing_images.append(json_path.name)
            continue

        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        size_seen[f"{width}x{height}"] = size_seen.get(f"{width}x{height}", 0) + 1
        for shape in annotation.get("shapes", []):
            label = shape.get("label")
            labels_seen[label] = labels_seen.get(label, 0) + 1

        mask = render_mask(annotation, image.size)
        gray = image.convert("L").resize((args.width, args.height), Image.BILINEAR)
        mask_small = mask.resize((args.width, args.height), Image.NEAREST)

        sample_name = json_path.stem
        gray.save(image_dir / f"{sample_name}.png")
        mask_small.save(mask_dir / f"{sample_name}.png")
        if index < args.preview_count:
            make_preview(gray, mask_small).save(preview_dir / f"{sample_name}.jpg", quality=92)

        records.append(
            {
                "name": sample_name,
                "source_json": str(json_path),
                "source_image": str(image_path),
                "image": str(image_dir / f"{sample_name}.png"),
                "mask": str(mask_dir / f"{sample_name}.png"),
                "source_width": width,
                "source_height": height,
            }
        )

    if missing_images:
        raise SystemExit(f"missing images for: {missing_images[:8]}")
    unexpected = set(labels_seen) - VALID_LABELS
    if unexpected:
        raise SystemExit(f"unexpected labels found: {sorted(unexpected)}")

    # 固定随机种子保证 split 可复现；排序后写文件便于 diff 和人工检查。
    rng = random.Random(args.seed)
    names = [record["name"] for record in records]
    rng.shuffle(names)
    test_count = int(round(len(names) * args.test_ratio))
    val_count = int(round(len(names) * args.val_ratio))
    test_names = sorted(names[:test_count])
    val_names = sorted(names[test_count : test_count + val_count])
    train_names = sorted(names[test_count + val_count :])
    write_split(split_dir / "train.txt", train_names)
    write_split(split_dir / "val.txt", val_names)
    write_split(split_dir / "test.txt", test_names)

    metadata = {
        "image_width": args.width,
        "image_height": args.height,
        "labels_merged_to_foreground": sorted(VALID_LABELS),
        "records": records,
        "labels_seen": labels_seen,
        "source_sizes": size_seen,
        "splits": {
            "train": len(train_names),
            "val": len(val_names),
            "test": len(test_names),
        },
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "class_map.json").write_text(
        json.dumps({"background": 0, "road": 1}, indent=2), encoding="utf-8"
    )
    print(json.dumps(metadata["splits"], indent=2))
    print(f"prepared {len(records)} samples in {out_dir}")


if __name__ == "__main__":
    main()
