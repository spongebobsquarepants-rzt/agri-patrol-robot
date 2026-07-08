#!/usr/bin/env python3
"""Prepare board-like grayscale road segmentation data with stratified splits."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


VALID_LABELS = {"sand_road", "grassy_road"}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")


def parse_args() -> argparse.Namespace:
    """解析 v2 数据准备参数。

    输入来自 CLI；输出包含原始数据、人工修订副本、输出目录、图像尺寸和分层 split 配置。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument(
        "--curated-dir",
        default=Path("field_nav_workspace/data/labelme_curated_v2"),
        type=Path,
        help="Optional LabelMe review copy. Matching JSON files override the original annotation.",
    )
    parser.add_argument(
        "--out-dir",
        default=Path("field_nav_workspace/data/processed_v2_640x480"),
        type=Path,
    )
    parser.add_argument("--width", default=640, type=int)
    parser.add_argument("--height", default=480, type=int)
    parser.add_argument("--seed", default=20260427, type=int)
    parser.add_argument("--val-ratio", default=0.15, type=float)
    parser.add_argument("--test-ratio", default=0.15, type=float)
    parser.add_argument("--preview-count", default=48, type=int)
    parser.add_argument("--preview-all", action="store_true")
    return parser.parse_args()


def find_labelme_dir(dataset_root: Path) -> Path:
    """定位真实 LabelMe 目录；兼容传入数据集根目录或 labelme_data 子目录。"""

    if (dataset_root / "labelme_data").is_dir():
        return dataset_root / "labelme_data"
    return dataset_root


def resolve_image_path(labelme_dir: Path, json_path: Path, annotation: dict, fallback_dir: Path | None = None) -> Path:
    """为一个 JSON 标注查找对应图片。

    输入 labelme_dir/json_path/annotation；fallback_dir 用于 curated JSON 仍引用原始图片时回退。
    输出存在的图片路径；找不到时抛 FileNotFoundError。
    """

    image_name = annotation.get("imagePath")
    candidates: list[Path] = []
    if image_name:
        candidates.extend([json_path.parent / image_name, labelme_dir / image_name])
        if fallback_dir is not None:
            candidates.append(fallback_dir / image_name)
    for ext in IMAGE_EXTENSIONS:
        candidates.append(json_path.with_suffix(ext))
        if fallback_dir is not None:
            candidates.append(fallback_dir / f"{json_path.stem}{ext}")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"missing image for {json_path}")


def polygon_points(points: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    """过滤并转换 LabelMe polygon 点坐标，返回 PIL 可绘制的 (x, y) 列表。"""

    parsed: list[tuple[float, float]] = []
    for point in points:
        if len(point) >= 2:
            parsed.append((float(point[0]), float(point[1])))
    return parsed


def render_mask(annotation: dict, image_size: tuple[int, int]) -> Image.Image:
    """把 sand_road/grassy_road polygon 合并渲染成单通道 road mask。

    输入 annotation 和原图尺寸；输出 L 模式 mask。遇到未知标签或非 polygon 会直接报错。
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


def label_profile(annotation: dict) -> str:
    """概括样本标签组成，用于后续分层 split。

    输出 sand_only/grassy_only/mixed，避免某类道路只集中在某个数据划分。
    """

    labels = {shape.get("label") for shape in annotation.get("shapes", [])}
    if labels == {"sand_road"}:
        return "sand_only"
    if labels == {"grassy_road"}:
        return "grassy_only"
    return "mixed"


def crop_foreground_ratio(mask: Image.Image, box: tuple[int, int, int, int]) -> float:
    """计算指定裁剪框内的 road 前景占比；用于判断裁剪是否保留道路区域。"""

    crop = mask.crop(box)
    return float((np.asarray(crop, dtype=np.uint8) > 0).mean())


def board_like_crop_box(width: int, height: int, mask: Image.Image | None = None) -> tuple[int, int, int, int, str]:
    """选择接近板端视角的裁剪框。

    输入原图尺寸和可选 mask；输出 x0/y0/x1/y1/mode。
    原理：竖图按 4:3 裁剪，优先中心裁剪；中心道路太少时选择 foreground 更多的位置。
    """

    if height > width:
        crop_width = width
        crop_height = min(height, max(1, int(round(crop_width * 3.0 / 4.0))))
        max_y = max(0, height - crop_height)
        center_y = max_y // 2
        center_box = (0, center_y, crop_width, center_y + crop_height)
        if mask is None or max_y == 0:
            return (*center_box, "portrait_center_crop_4x3")

        center_fg = crop_foreground_ratio(mask, center_box)
        best_box = center_box
        best_fg = center_fg
        # 在纵向 9 个候选位置中寻找道路占比更高的裁剪框，减少低质量边缘裁剪。
        for idx in range(9):
            y0 = int(round(max_y * idx / 8.0))
            box = (0, y0, crop_width, y0 + crop_height)
            fg = crop_foreground_ratio(mask, box)
            if fg > best_fg:
                best_fg = fg
                best_box = box
        if center_fg >= 0.02 or center_fg >= best_fg * 0.70:
            return (*center_box, "portrait_center_crop_4x3")
        return (*best_box, "portrait_road_aware_crop_4x3")
    return 0, 0, width, height, "landscape_full_resize"


def transform_pair(image: Image.Image, mask: Image.Image, out_size: tuple[int, int]) -> tuple[Image.Image, Image.Image, dict]:
    """把原图/mask 转为训练样本。

    输入 RGB 原图、二值 mask 和输出尺寸；输出灰度图、缩放 mask 和裁剪元数据。
    """

    width, height = image.size
    x0, y0, x1, y1, mode = board_like_crop_box(width, height, mask)
    image_crop = image.crop((x0, y0, x1, y1))
    mask_crop = mask.crop((x0, y0, x1, y1))
    gray = image_crop.convert("L").resize(out_size, Image.BILINEAR)
    mask_small = mask_crop.resize(out_size, Image.NEAREST)
    meta = {"mode": mode, "crop_box": [x0, y0, x1, y1]}
    return gray, mask_small, meta


def make_preview(gray: Image.Image, mask: Image.Image) -> Image.Image:
    """生成绿色 mask 叠加预览图，便于人工检查裁剪和标签质量。"""

    rgb = gray.convert("RGB")
    overlay = Image.new("RGB", rgb.size, (0, 255, 80))
    alpha = mask.point(lambda p: 96 if p > 0 else 0)
    rgb.paste(overlay, mask=alpha)
    return rgb


def fg_bucket(fg_ratio: float) -> str:
    """把前景占比分桶，供 stratified split 使用。"""

    if fg_ratio < 0.10:
        return "fg_00_10"
    if fg_ratio < 0.25:
        return "fg_10_25"
    if fg_ratio < 0.45:
        return "fg_25_45"
    if fg_ratio < 0.65:
        return "fg_45_65"
    return "fg_65_100"


def size_bucket(width: int, height: int) -> str:
    """把原图尺寸分桶，避免低分辨率样本只集中在某个 split。"""

    short = min(width, height)
    long = max(width, height)
    if short < 300:
        return "low_short_edge"
    if long >= 2500:
        return "large_source"
    return "standard_source"


def split_key(record: dict) -> str:
    """生成分层划分键。

    输入样本 record；输出由方向、尺寸桶、前景占比桶和标签组成的字符串 key。
    """

    orientation = "portrait" if record["source_height"] > record["source_width"] else "landscape"
    return "|".join(
        [
            orientation,
            size_bucket(record["source_width"], record["source_height"]),
            fg_bucket(record["fg_ratio"]),
            record["label_profile"],
        ]
    )


def assign_stratified_splits(records: list[dict], seed: int, val_ratio: float, test_ratio: float) -> dict[str, list[str]]:
    """按样本属性做近似分层 train/val/test 划分。

    输入 records/seed/比例；输出 split 到样本名列表的映射。
    使用注意：小数据集无法严格满足每个桶比例，因此按目标容量贪心分配。
    """

    rng = random.Random(seed)
    total = len(records)
    target = {
        "test": int(round(total * test_ratio)),
        "val": int(round(total * val_ratio)),
    }
    target["train"] = total - target["test"] - target["val"]
    splits: dict[str, list[str]] = {"train": [], "val": [], "test": []}
    by_key: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_key[split_key(record)].append(record)

    # 每个分层桶内部先打乱，再优先填充尚未达到目标容量的 split。
    for key in sorted(by_key):
        group = by_key[key]
        rng.shuffle(group)
        for record in group:
            candidates = [name for name in ("test", "val", "train") if len(splits[name]) < target[name]]
            if not candidates:
                candidates = ["train"]
            chosen = min(
                candidates,
                key=lambda name: (
                    len(splits[name]) / max(target[name], 1),
                    len(splits[name]),
                    {"test": 0, "val": 1, "train": 2}[name],
                ),
            )
            splits[chosen].append(record["name"])

    for names in splits.values():
        names.sort()
    return splits


def write_split(path: Path, names: list[str]) -> None:
    """写入 split 列表；一行一个样本名，末尾保留换行。"""

    path.write_text("\n".join(names) + "\n", encoding="utf-8")


def split_stats(records: list[dict], splits: dict[str, list[str]]) -> dict:
    """统计各 split 的前景占比、标签组成和裁剪模式。

    输出 JSON 友好 dict，用于判断划分是否明显偏斜。
    """

    by_name = {record["name"]: record for record in records}
    stats: dict[str, dict] = {}
    for split, names in splits.items():
        split_records = [by_name[name] for name in names]
        fg_values = [float(record["fg_ratio"]) for record in split_records]
        stats[split] = {
            "count": len(names),
            "fg_ratio_mean": float(np.mean(fg_values)) if fg_values else 0.0,
            "fg_ratio_min": float(np.min(fg_values)) if fg_values else 0.0,
            "fg_ratio_max": float(np.max(fg_values)) if fg_values else 0.0,
            "label_profile": dict(Counter(record["label_profile"] for record in split_records)),
            "transform_mode": dict(Counter(record["transform"]["mode"] for record in split_records)),
            "source_size_bucket": dict(
                Counter(size_bucket(record["source_width"], record["source_height"]) for record in split_records)
            ),
        }
    return stats


def main() -> None:
    """执行 v2 数据准备流程。

    核心流程：优先读取 curated 标注 -> 渲染 mask -> 板端风格裁剪 -> 灰度缩放 -> 分层 split -> 写 metadata。
    """

    args = parse_args()
    if args.width < 1 or args.height < 1:
        raise SystemExit("--width and --height must be positive")
    if args.val_ratio < 0.0 or args.test_ratio < 0.0 or args.val_ratio + args.test_ratio >= 1.0:
        raise SystemExit("--val-ratio and --test-ratio must be non-negative and sum to less than 1")

    labelme_dir = find_labelme_dir(args.dataset_root)
    image_dir = args.out_dir / "images"
    mask_dir = args.out_dir / "masks"
    preview_dir = args.out_dir / "previews"
    split_dir = args.out_dir / "splits"
    for directory in (image_dir, mask_dir, preview_dir, split_dir):
        directory.mkdir(parents=True, exist_ok=True)

    json_files = sorted(labelme_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"no LabelMe json files found in {labelme_dir}")

    records: list[dict] = []  # 训练样本记录，包含来源、输出路径、裁剪和标签信息。
    labels_seen: Counter[str] = Counter()  # 全数据集标签计数，用于检查未知类别。
    curated_used = 0  # 实际采用人工修订 JSON 的样本数量。
    # 原始 JSON 是主索引；如果 curated_dir 中存在同名 JSON，则用修订标注覆盖。
    for index, original_json in enumerate(json_files):
        curated_json = args.curated_dir / original_json.name
        active_json = curated_json if curated_json.exists() else original_json
        annotation = json.loads(active_json.read_text(encoding="utf-8"))
        fallback_dir = original_json.parent if active_json == curated_json else None
        image_path = resolve_image_path(active_json.parent, active_json, annotation, fallback_dir=fallback_dir)
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        for shape in annotation.get("shapes", []):
            labels_seen[shape.get("label")] += 1
        mask = render_mask(annotation, image.size)
        gray, mask_small, transform = transform_pair(image, mask, (args.width, args.height))
        sample_name = original_json.stem
        gray.save(image_dir / f"{sample_name}.png")
        mask_small.save(mask_dir / f"{sample_name}.png")
        if args.preview_all or index < args.preview_count:
            make_preview(gray, mask_small).save(preview_dir / f"{sample_name}.jpg", quality=92)
        fg_ratio = float((np.asarray(mask_small, dtype=np.uint8) > 0).mean())
        record = {
            "name": sample_name,
            "source_json": str(original_json),
            "active_json": str(active_json),
            "source_image": str(image_path),
            "image": str(image_dir / f"{sample_name}.png"),
            "mask": str(mask_dir / f"{sample_name}.png"),
            "source_width": width,
            "source_height": height,
            "fg_ratio": fg_ratio,
            "label_profile": label_profile(annotation),
            "curated_annotation": active_json == curated_json,
            "transform": transform,
        }
        curated_used += int(record["curated_annotation"])
        records.append(record)

    unexpected = set(labels_seen) - VALID_LABELS
    if unexpected:
        raise SystemExit(f"unexpected labels found: {sorted(unexpected)}")

    splits = assign_stratified_splits(records, args.seed, args.val_ratio, args.test_ratio)
    for split, names in splits.items():
        write_split(split_dir / f"{split}.txt", names)

    metadata = {
        "image_width": args.width,
        "image_height": args.height,
        "labels_merged_to_foreground": sorted(VALID_LABELS),
        "records": records,
        "labels_seen": dict(labels_seen),
        "curated_annotations_used": curated_used,
        "splits": {split: len(names) for split, names in splits.items()},
        "split_stats": split_stats(records, splits),
    }
    (args.out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out_dir / "split_stats.json").write_text(
        json.dumps(metadata["split_stats"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out_dir / "class_map.json").write_text(
        json.dumps({"background": 0, "road": 1}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(metadata["splits"], indent=2))
    print(json.dumps(metadata["split_stats"], indent=2))
    print(f"curated annotations used: {curated_used}")
    print(f"prepared {len(records)} v2 samples in {args.out_dir}")


if __name__ == "__main__":
    main()
