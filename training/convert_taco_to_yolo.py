"""Convert TACO (COCO format) into a YOLO detection dataset, under the EcoSentinel taxonomy.

The source dataset is never modified. Images are copied into `datasets/taco_yolo/`, leaving
`TACO-master/` exactly as downloaded.

Only categories the taxonomy mapping marks `mapped` or `partially_mapped` are converted. The other
2,970 annotations — cigarettes, unlabeled litter, glass, foam, caps, straws — are **excluded and
counted**, not folded into the nearest class. Forcing 667 cigarette annotations into any of the
eight EcoSentinel classes would teach the detector that class means "small litter".

Every converted box is re-validated after the coordinate transform, not just before it. Clipping a
box to the image edge can produce a zero-width box from a valid input, and a silently emitted
degenerate label is the kind of thing that surfaces much later as unexplained training instability.

Splits are made **by image**, never by annotation, so no image can appear in two splits.

    python training/convert_taco_to_yolo.py --taco TACO-master --out datasets/taco_yolo
"""

import argparse
import hashlib
import json
import random
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

MIN_NORMALISED_SIDE = 0.002  # ~1px on a 512px image; below this a box is not trainable


def load_mapping(path: Path) -> Tuple[Dict[str, str], Dict]:
    """TACO category name -> EcoSentinel class, for usable statuses only."""
    document = json.loads(path.read_text())
    usable = {
        name: entry["ecosentinel_class"]
        for name, entry in document["categories"].items()
        if entry["status"] in ("mapped", "partially_mapped") and entry["ecosentinel_class"]
    }
    return usable, document


def to_yolo(bbox: List[float], width: float, height: float) -> Tuple[float, float, float, float]:
    """COCO [x, y, w, h] absolute -> YOLO [cx, cy, w, h] normalised, clipped to the image."""
    x, y, box_width, box_height = bbox
    x1, y1 = max(0.0, x), max(0.0, y)
    x2, y2 = min(width, x + box_width), min(height, y + box_height)
    cx = ((x1 + x2) / 2) / width
    cy = ((y1 + y2) / 2) / height
    return cx, cy, (x2 - x1) / width, (y2 - y1) / height


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taco", default="TACO-master")
    parser.add_argument("--annotations", default="data/annotations.json")
    parser.add_argument("--mapping", default="training/config/taco_taxonomy_mapping.json")
    parser.add_argument("--out", default="datasets/taco_yolo")
    parser.add_argument("--report", default="runs/waste_detection_dataset_report.json")
    parser.add_argument("--val-fraction", type=float, default=0.15)
    parser.add_argument("--test-fraction", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--copy-images", action="store_true", default=True)
    args = parser.parse_args()

    taco_root = Path(args.taco)
    data = json.loads((taco_root / args.annotations).read_text())
    usable, mapping_doc = load_mapping(Path(args.mapping))

    images = {image["id"]: image for image in data["images"]}
    categories = {category["id"]: category["name"] for category in data["categories"]}

    # Stable class ordering so a label file means the same thing across runs.
    eco_classes = sorted(set(usable.values()))
    class_index = {name: i for i, name in enumerate(eco_classes)}

    # --- group usable annotations by image ---
    per_image: Dict[int, List[Tuple[int, List[float]]]] = defaultdict(list)
    excluded_by_category: Counter = Counter()
    rejected: List[Dict] = []
    rejection_reasons: Counter = Counter()

    for annotation in data["annotations"]:
        category_name = categories.get(annotation["category_id"], "?")
        eco_class = usable.get(category_name)
        if eco_class is None:
            excluded_by_category[category_name] += 1
            continue

        image = images.get(annotation["image_id"])
        if image is None:
            rejected.append({"annotation_id": annotation["id"], "reason": "orphan_image_id"})
            rejection_reasons["orphan_image_id"] += 1
            continue

        width, height = float(image["width"]), float(image["height"])
        bbox = annotation.get("bbox") or []
        if len(bbox) != 4 or width <= 0 or height <= 0:
            rejected.append({"annotation_id": annotation["id"], "reason": "malformed_input"})
            rejection_reasons["malformed_input"] += 1
            continue

        cx, cy, bw, bh = to_yolo([float(v) for v in bbox], width, height)

        # Re-validate AFTER the transform: clipping a valid box to the edge can leave it empty.
        problems = []
        if bw <= MIN_NORMALISED_SIDE or bh <= MIN_NORMALISED_SIDE:
            problems.append("degenerate_after_clipping")
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            problems.append("centre_outside_image")
        if cx - bw / 2 < -1e-6 or cy - bh / 2 < -1e-6 or cx + bw / 2 > 1 + 1e-6 or cy + bh / 2 > 1 + 1e-6:
            problems.append("box_exceeds_bounds")
        if problems:
            rejected.append({
                "annotation_id": annotation["id"], "image": image["file_name"],
                "category": category_name, "bbox": bbox, "reasons": problems,
            })
            for reason in problems:
                rejection_reasons[reason] += 1
            continue

        per_image[annotation["image_id"]].append((class_index[eco_class], [cx, cy, bw, bh]))

    # --- split BY IMAGE so the same image cannot land in two splits ---
    image_ids = sorted(per_image)
    random.Random(args.seed).shuffle(image_ids)
    total = len(image_ids)
    val_count = int(total * args.val_fraction)
    test_count = int(total * args.test_fraction)
    split_of = {}
    for position, image_id in enumerate(image_ids):
        if position < val_count:
            split_of[image_id] = "val"
        elif position < val_count + test_count:
            split_of[image_id] = "test"
        else:
            split_of[image_id] = "train"

    out_root = Path(args.out)
    for split in ("train", "val", "test"):
        (out_root / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_root / "labels" / split).mkdir(parents=True, exist_ok=True)

    written: Counter = Counter()
    per_split_classes: Dict[str, Counter] = defaultdict(Counter)
    missing_images: List[str] = []
    hashes: Dict[str, List[str]] = defaultdict(list)

    for image_id, boxes in per_image.items():
        image = images[image_id]
        split = split_of[image_id]
        source = taco_root / "data" / image["file_name"]
        if not source.is_file():
            missing_images.append(image["file_name"])
            continue

        # Flatten batch_N/000006.jpg -> batch_N_000006.jpg so names stay unique in one directory.
        stem = image["file_name"].replace("/", "_")
        target_image = out_root / "images" / split / stem
        target_label = out_root / "labels" / split / f"{Path(stem).stem}.txt"

        if args.copy_images and not target_image.exists():
            shutil.copy2(source, target_image)
        hashes[hashlib.sha256(source.read_bytes()).hexdigest()].append(f"{split}/{stem}")

        target_label.write_text(
            "\n".join(f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}" for cls, (cx, cy, bw, bh) in boxes) + "\n"
        )
        written[split] += 1
        for cls, _ in boxes:
            per_split_classes[split][eco_classes[cls]] += 1

    # --- leakage: identical pixels landing in two splits ---
    cross_split = []
    for digest, locations in hashes.items():
        if len({loc.split("/")[0] for loc in locations}) > 1:
            cross_split.append({"hash": digest[:16], "locations": locations})

    yaml_path = out_root / "data.yaml"
    yaml_path.write_text(
        "# Generated by training/convert_taco_to_yolo.py - do not edit by hand.\n"
        f"path: {out_root.resolve()}\n"
        "train: images/train\nval: images/val\ntest: images/test\n\n"
        "names:\n" + "".join(f"  {i}: {name}\n" for i, name in enumerate(eco_classes))
    )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(taco_root / args.annotations),
        "output": str(out_root),
        "taxonomy": {
            "ecosentinel_classes_in_dataset": eco_classes,
            "classes_with_no_taco_data": mapping_doc["summary"]["ecosentinel_classes_with_no_taco_data"],
            "mapping_file": str(args.mapping),
        },
        "images": {
            "with_usable_annotations": len(per_image),
            "written": dict(written),
            "missing_on_disk": len(missing_images),
            "missing_examples": missing_images[:10],
        },
        "annotations": {
            "converted": sum(sum(c.values()) for c in per_split_classes.values()),
            "rejected": len(rejected),
            "rejection_reasons": dict(rejection_reasons),
            "rejected_examples": rejected[:20],
            "excluded_unmapped_categories": dict(excluded_by_category.most_common()),
            "excluded_unmapped_total": sum(excluded_by_category.values()),
        },
        "class_distribution": {split: dict(counts) for split, counts in per_split_classes.items()},
        "leakage": {
            "cross_split_duplicate_groups": len(cross_split),
            "examples": cross_split[:5],
            "split_strategy": "by image id, so one image's annotations never span two splits",
        },
        "note": (
            "Unmapped categories are excluded and counted, never merged into the nearest class. "
            "The source dataset is untouched."
        ),
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))

    print(f"Converted -> {out_root}")
    print(f"  classes            : {eco_classes}")
    print(f"  images written     : {dict(written)}  (missing on disk: {len(missing_images)})")
    print(f"  annotations written: {report['annotations']['converted']}")
    print(f"  rejected           : {len(rejected)}  {dict(rejection_reasons) or ''}")
    print(f"  excluded (unmapped): {report['annotations']['excluded_unmapped_total']}")
    print(f"  cross-split dupes  : {len(cross_split)}")
    print(f"  report             -> {report_path}")
    print(f"  data.yaml          -> {yaml_path}")


if __name__ == "__main__":
    main()
