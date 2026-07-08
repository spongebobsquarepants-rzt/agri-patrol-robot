#!/usr/bin/env python3
"""Audit LabelMe road annotations and create a curated-v2 review set."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw


VALID_LABELS = {"sand_road", "grassy_road"}
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp")


def parse_args() -> argparse.Namespace:
    """解析数据审计参数。

    输出包含审计目录、人工修订副本目录和各类可疑样本阈值。
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument(
        "--audit-dir",
        default=Path("field_nav_workspace/data/audit_v2"),
        type=Path,
    )
    parser.add_argument(
        "--curated-dir",
        default=Path("field_nav_workspace/data/labelme_curated_v2"),
        type=Path,
    )
    parser.add_argument("--preview-width", default=640, type=int)
    parser.add_argument("--preview-height", default=480, type=int)
    parser.add_argument("--fg-low", default=0.05, type=float)
    parser.add_argument("--fg-high", default=0.85, type=float)
    parser.add_argument("--min-short-edge", default=300, type=int)
    parser.add_argument("--extreme-aspect", default=2.0, type=float)
    parser.add_argument("--max-shapes", default=12, type=int)
    parser.add_argument("--max-vertices", default=250, type=int)
    parser.add_argument("--max-components", default=4, type=int)
    parser.add_argument("--no-copy-suspicious", action="store_true")
    return parser.parse_args()


def find_labelme_dir(dataset_root: Path) -> Path:
    """定位 LabelMe 标注目录；兼容传入数据集根目录或 labelme_data。"""

    if (dataset_root / "labelme_data").is_dir():
        return dataset_root / "labelme_data"
    return dataset_root


def resolve_image_path(labelme_dir: Path, json_path: Path, annotation: dict) -> Path | None:
    """根据 imagePath 和同名图片规则查找标注对应图像。

    找到则返回 Path，找不到返回 None，供审计报告记录 missing_image。
    """

    image_name = annotation.get("imagePath")
    candidates: list[Path] = []
    if image_name:
        candidates.append(labelme_dir / image_name)
        candidates.append(json_path.parent / image_name)
    for ext in IMAGE_EXTENSIONS:
        candidates.append(json_path.with_suffix(ext))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def polygon_points(points: Iterable[Iterable[float]]) -> list[tuple[float, float]]:
    """把 LabelMe 点数组转为 float 坐标，并忽略维度不足的坏点。"""

    parsed: list[tuple[float, float]] = []
    for point in points:
        if len(point) >= 2:
            parsed.append((float(point[0]), float(point[1])))
    return parsed


def render_mask(annotation: dict, image_size: tuple[int, int]) -> Image.Image:
    """渲染审计用二值 mask。

    输入 annotation/image_size；输出 road mask。审计阶段跳过未知标签和非 polygon，问题另行计数。
    """

    mask = Image.new("L", image_size, 0)
    draw = ImageDraw.Draw(mask)
    for shape in annotation.get("shapes", []):
        if shape.get("label") not in VALID_LABELS:
            continue
        if shape.get("shape_type", "polygon") != "polygon":
            continue
        pts = polygon_points(shape.get("points", []))
        if len(pts) >= 3:
            draw.polygon(pts, fill=255)
    return mask


def component_count(mask: Image.Image, max_dim: int = 320) -> int:
    """估算 mask 连通域数量。

    输入 mask；输出 4 邻域前景连通域个数。大图会先缩小到 max_dim 内，降低审计耗时。
    """

    width, height = mask.size
    scale = min(1.0, max_dim / max(width, height))
    if scale < 1.0:
        mask = mask.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.NEAREST)
    arr = np.asarray(mask, dtype=np.uint8) > 0
    visited = np.zeros(arr.shape, dtype=bool)
    h, w = arr.shape
    count = 0
    # 用栈式 DFS 避免递归深度问题；只需数量，不保留每个连通域的像素。
    for y in range(h):
        for x in range(w):
            if not arr[y, x] or visited[y, x]:
                continue
            count += 1
            stack = [(y, x)]
            visited[y, x] = True
            while stack:
                cy, cx = stack.pop()
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < h and 0 <= nx < w and arr[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
    return count


def overlay_preview(image: Image.Image, mask: Image.Image, record: dict, size: tuple[int, int]) -> Image.Image:
    """生成带审计原因文字的叠加预览图。

    输入原图/mask/审计记录/输出尺寸；输出 RGB 预览，用于人工快速复核 suspicious 样本。
    """

    rgb = image.convert("RGB").resize(size, Image.BILINEAR)
    mask_small = mask.resize(size, Image.NEAREST)
    green = Image.new("RGB", size, (0, 255, 80))
    alpha = mask_small.point(lambda value: 96 if value > 0 else 0)
    rgb.paste(green, mask=alpha)
    draw = ImageDraw.Draw(rgb)
    reasons = record["reasons"].replace("|", ", ")
    text = f'{record["name"]} fg={float(record["fg_ratio"]):.3f} {reasons}'
    draw.rectangle((0, 0, size[0], 24), fill=(0, 0, 0))
    draw.text((6, 6), text[:120], fill=(255, 255, 255))
    return rgb


def classify_reasons(record: dict, args: argparse.Namespace) -> list[str]:
    """根据审计记录和阈值生成可疑原因列表。

    输出原因字符串列表；空列表表示该样本未触发当前规则。
    """

    reasons: list[str] = []
    if record["missing_image"]:
        reasons.append("missing_image")
    if record["invalid_labels"]:
        reasons.append("invalid_label")
    if record["non_polygon_shapes"]:
        reasons.append("non_polygon")
    if record["empty_polygons"]:
        reasons.append("empty_polygon")
    fg_ratio = float(record["fg_ratio"])
    if fg_ratio < args.fg_low:
        reasons.append("fg_lt_5pct")
    if fg_ratio > args.fg_high:
        reasons.append("fg_gt_85pct")
    if min(record["source_width"], record["source_height"]) < args.min_short_edge:
        reasons.append("low_resolution")
    if float(record["aspect_ratio"]) > args.extreme_aspect:
        reasons.append("extreme_aspect")
    if record["shape_count"] > args.max_shapes:
        reasons.append("many_polygons")
    if record["total_vertices"] > args.max_vertices:
        reasons.append("many_vertices")
    if record["component_count"] > args.max_components:
        reasons.append("fragmented_mask")
    if record["shape_count"] == 0:
        reasons.append("no_shapes")
    return reasons


def main() -> None:
    """执行 LabelMe v2 数据审计。

    核心流程：逐 JSON 统计标签/尺寸/mask 质量 -> 生成 overlay -> 可选复制可疑样本到 curated_dir。
    """

    args = parse_args()
    if args.preview_width < 1 or args.preview_height < 1:
        raise SystemExit("--preview-width and --preview-height must be positive")

    labelme_dir = find_labelme_dir(args.dataset_root)
    overlay_dir = args.audit_dir / "overlays"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    args.curated_dir.mkdir(parents=True, exist_ok=True)

    json_files = sorted(labelme_dir.glob("*.json"))
    if not json_files:
        raise SystemExit(f"no LabelMe json files found in {labelme_dir}")

    rows: list[dict] = []  # audit.csv 的逐样本记录。
    copied: list[dict] = []  # 已复制到 curated_v2 的可疑样本清单。
    # 逐个 JSON 做静态审计，不修改原始数据；可疑样本只复制副本供人工修订。
    for json_path in json_files:
        annotation = json.loads(json_path.read_text(encoding="utf-8"))
        image_path = resolve_image_path(labelme_dir, json_path, annotation)
        labels = Counter()
        invalid_labels: list[str] = []
        non_polygon_shapes = 0
        empty_polygons = 0
        total_vertices = 0
        for shape in annotation.get("shapes", []):
            label = shape.get("label")
            labels[label] += 1
            if label not in VALID_LABELS:
                invalid_labels.append(str(label))
            if shape.get("shape_type", "polygon") != "polygon":
                non_polygon_shapes += 1
            points = polygon_points(shape.get("points", []))
            total_vertices += len(points)
            if len(points) < 3:
                empty_polygons += 1

        if image_path is None:
            record = {
                "name": json_path.stem,
                "source_json": str(json_path),
                "source_image": "",
                "source_width": 0,
                "source_height": 0,
                "orientation": "missing",
                "aspect_ratio": 0.0,
                "fg_ratio": 0.0,
                "shape_count": len(annotation.get("shapes", [])),
                "total_vertices": total_vertices,
                "component_count": 0,
                "sand_road_shapes": labels.get("sand_road", 0),
                "grassy_road_shapes": labels.get("grassy_road", 0),
                "labels": "|".join(sorted(str(label) for label in labels)),
                "missing_image": 1,
                "invalid_labels": "|".join(sorted(set(invalid_labels))),
                "non_polygon_shapes": non_polygon_shapes,
                "empty_polygons": empty_polygons,
            }
        else:
            image = Image.open(image_path).convert("RGB")
            width, height = image.size
            mask = render_mask(annotation, image.size)
            fg_ratio = float((np.asarray(mask, dtype=np.uint8) > 0).mean())
            record = {
                "name": json_path.stem,
                "source_json": str(json_path),
                "source_image": str(image_path),
                "source_width": width,
                "source_height": height,
                "orientation": "portrait" if height > width else "landscape",
                "aspect_ratio": max(width / max(height, 1), height / max(width, 1)),
                "fg_ratio": fg_ratio,
                "shape_count": len(annotation.get("shapes", [])),
                "total_vertices": total_vertices,
                "component_count": component_count(mask),
                "sand_road_shapes": labels.get("sand_road", 0),
                "grassy_road_shapes": labels.get("grassy_road", 0),
                "labels": "|".join(sorted(str(label) for label in labels)),
                "missing_image": 0,
                "invalid_labels": "|".join(sorted(set(invalid_labels))),
                "non_polygon_shapes": non_polygon_shapes,
                "empty_polygons": empty_polygons,
            }
        reasons = classify_reasons(record, args)
        record["suspicious"] = 1 if reasons else 0
        record["reasons"] = "|".join(reasons)
        rows.append(record)

        if image_path is not None:
            image = Image.open(image_path).convert("RGB")
            preview = overlay_preview(
                image,
                render_mask(annotation, image.size),
                record,
                (args.preview_width, args.preview_height),
            )
            preview.save(overlay_dir / f"{json_path.stem}.jpg", quality=90)

        if reasons and image_path is not None and not args.no_copy_suspicious:
            dst_json = args.curated_dir / json_path.name
            dst_image = args.curated_dir / image_path.name
            shutil.copy2(json_path, dst_json)
            shutil.copy2(image_path, dst_image)
            copied.append(
                {
                    "name": json_path.stem,
                    "json": str(dst_json),
                    "image": str(dst_image),
                    "reasons": reasons,
                }
            )

    fieldnames = [
        "name",
        "source_json",
        "source_image",
        "source_width",
        "source_height",
        "orientation",
        "aspect_ratio",
        "fg_ratio",
        "shape_count",
        "total_vertices",
        "component_count",
        "sand_road_shapes",
        "grassy_road_shapes",
        "labels",
        "missing_image",
        "invalid_labels",
        "non_polygon_shapes",
        "empty_polygons",
        "suspicious",
        "reasons",
    ]
    with (args.audit_dir / "audit.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    fg_values = [float(row["fg_ratio"]) for row in rows if not row["missing_image"]]
    summary = {
        "labelme_dir": str(labelme_dir),
        "samples": len(rows),
        "suspicious_samples": sum(int(row["suspicious"]) for row in rows),
        "copied_to_curated_v2": len(copied),
        "foreground_ratio": {
            "mean": float(np.mean(fg_values)) if fg_values else 0.0,
            "min": float(np.min(fg_values)) if fg_values else 0.0,
            "max": float(np.max(fg_values)) if fg_values else 0.0,
        },
        "reason_counts": Counter(
            reason for row in rows for reason in str(row["reasons"]).split("|") if reason
        ),
        "copied": copied,
    }
    summary["reason_counts"] = dict(summary["reason_counts"])
    (args.audit_dir / "audit_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.audit_dir / "suspicious.txt").write_text(
        "\n".join(row["name"] for row in rows if row["suspicious"]) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({k: summary[k] for k in ("samples", "suspicious_samples", "copied_to_curated_v2")}, indent=2))
    print(f"audit table: {args.audit_dir / 'audit.csv'}")
    print(f"overlay previews: {overlay_dir}")
    print(f"curated review copy: {args.curated_dir}")


if __name__ == "__main__":
    main()
