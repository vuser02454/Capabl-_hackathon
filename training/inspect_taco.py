"""Inspect the TACO dataset and report what is actually in it.

Runs against the COCO-format annotation file alone, so it works before any image has been
downloaded — which matters here, because TACO ships annotations and a `download.py` that fetches
the pixels separately. Reporting on annotations first means the taxonomy and viability questions
are answered before committing to a multi-gigabyte download.

Every bounding box is validated against the image dimensions recorded in the annotation file:
negative coordinates, zero-area boxes and boxes extending past the image edge are counted and
listed. Nothing is discarded here — this script only reports.

    python training/inspect_taco.py --taco TACO-master --out runs/taco_dataset_report.json
"""

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

#: A box smaller than this in either dimension is too small to train on at typical detector scales.
MIN_BOX_SIDE = 2.0


def validate_box(annotation: Dict, image: Dict) -> List[str]:
    """Return the reasons this annotation's bbox is unusable, or an empty list if it is fine."""
    problems: List[str] = []
    bbox = annotation.get("bbox")
    if not bbox or len(bbox) != 4:
        return ["missing_or_malformed_bbox"]

    x, y, width, height = (float(v) for v in bbox)
    image_width, image_height = float(image["width"]), float(image["height"])

    if width <= 0 or height <= 0:
        problems.append("zero_or_negative_area")
    if x < 0 or y < 0:
        problems.append("negative_origin")
    if width < MIN_BOX_SIDE or height < MIN_BOX_SIDE:
        problems.append("degenerate_size")
    # Allow a pixel of slack: annotation tools routinely round a box to the exact image edge.
    if x + width > image_width + 1 or y + height > image_height + 1:
        problems.append("extends_beyond_image")
    if image_width <= 0 or image_height <= 0:
        problems.append("invalid_image_dimensions")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--taco", default="TACO-master", help="TACO repository root")
    parser.add_argument("--annotations", default="data/annotations.json")
    parser.add_argument("--out", default="runs/taco_dataset_report.json")
    args = parser.parse_args()

    root = Path(args.taco)
    annotation_path = root / args.annotations
    if not annotation_path.is_file():
        raise SystemExit(f"TACO annotations not found at {annotation_path}")

    data = json.loads(annotation_path.read_text())
    images = {image["id"]: image for image in data["images"]}
    categories = {category["id"]: category for category in data["categories"]}
    annotations = data["annotations"]

    # --- are the pixels actually here? ---
    present, missing = [], []
    for image in images.values():
        candidate = root / "data" / image["file_name"]
        (present if candidate.is_file() else missing).append(image["file_name"])

    # --- per-annotation validation ---
    invalid: List[Dict] = []
    problem_counts: Counter = Counter()
    with_segmentation = 0
    areas: List[float] = []
    per_category: Counter = Counter()
    images_per_category: Dict[int, set] = defaultdict(set)

    for annotation in annotations:
        image = images.get(annotation["image_id"])
        if image is None:
            invalid.append({"annotation_id": annotation["id"], "reasons": ["orphan_image_id"]})
            problem_counts["orphan_image_id"] += 1
            continue
        problems = validate_box(annotation, image)
        if problems:
            invalid.append({
                "annotation_id": annotation["id"], "image": image["file_name"],
                "bbox": annotation.get("bbox"), "reasons": problems,
            })
            for reason in problems:
                problem_counts[reason] += 1
            continue
        if annotation.get("segmentation"):
            with_segmentation += 1
        areas.append(float(annotation.get("area") or 0.0))
        per_category[annotation["category_id"]] += 1
        images_per_category[annotation["category_id"]].add(annotation["image_id"])

    # --- duplicate images, by declared file name and by URL when present ---
    by_name: Dict[str, List[int]] = defaultdict(list)
    by_url: Dict[str, List[int]] = defaultdict(list)
    for image in images.values():
        by_name[image["file_name"]].append(image["id"])
        url = image.get("flickr_url") or image.get("coco_url")
        if url:
            by_url[url].append(image["id"])
    duplicate_names = {name: ids for name, ids in by_name.items() if len(ids) > 1}
    duplicate_urls = {url: ids for url, ids in by_url.items() if len(ids) > 1}

    # --- images with no annotations at all ---
    annotated_images = {a["image_id"] for a in annotations}
    unannotated = [i["file_name"] for i in images.values() if i["id"] not in annotated_images]

    supercategories: Counter = Counter()
    for category_id, count in per_category.items():
        supercategories[categories[category_id]["supercategory"]] += count

    sorted_areas = sorted(areas)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(annotation_path),
        "format": {
            "annotation_format": "COCO",
            "bbox_convention": "[x, y, width, height] absolute pixels (COCO)",
            "segmentation_available": with_segmentation > 0,
            "bbox_available": True,
            "declared_splits": "none - TACO ships a single annotation set with no train/val/test split",
        },
        "totals": {
            "images_declared": len(images),
            "annotations_declared": len(annotations),
            "annotations_valid": len(annotations) - len(invalid),
            "annotations_invalid": len(invalid),
            "categories": len(categories),
            "categories_with_annotations": len(per_category),
            "categories_empty": len(categories) - len(per_category),
            "images_without_annotations": len(unannotated),
            "annotations_with_segmentation": with_segmentation,
        },
        "image_files": {
            # The decisive number: annotations are useless for training without pixels.
            "present_on_disk": len(present),
            "missing_on_disk": len(missing),
            "note": (
                "TACO distributes annotations separately from images. Run `python download.py` "
                "inside the TACO repository to fetch them before any conversion or training."
            ),
        },
        "invalid_annotations": {
            "count": len(invalid),
            "reasons": dict(problem_counts),
            "examples": invalid[:20],
        },
        "duplicates": {
            "duplicate_file_names": len(duplicate_names),
            "duplicate_source_urls": len(duplicate_urls),
            "examples": list(duplicate_urls.items())[:5],
        },
        "annotation_statistics": {
            "min_area": sorted_areas[0] if sorted_areas else None,
            "median_area": sorted_areas[len(sorted_areas) // 2] if sorted_areas else None,
            "max_area": sorted_areas[-1] if sorted_areas else None,
            "mean_annotations_per_image": round(len(annotations) / max(1, len(images)), 2),
        },
        "supercategory_distribution": dict(supercategories.most_common()),
        "category_distribution": {
            categories[cid]["name"]: {
                "supercategory": categories[cid]["supercategory"],
                "annotations": count,
                "images": len(images_per_category[cid]),
            }
            for cid, count in per_category.most_common()
        },
        "empty_categories": [c["name"] for cid, c in categories.items() if cid not in per_category],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    totals = report["totals"]
    print(f"TACO report -> {out_path}")
    print(f"  images declared           : {totals['images_declared']}")
    print(f"  image files on disk       : {report['image_files']['present_on_disk']}")
    print(f"  annotations               : {totals['annotations_declared']} "
          f"({totals['annotations_valid']} valid, {totals['annotations_invalid']} invalid)")
    print(f"  categories                : {totals['categories']} "
          f"({totals['categories_empty']} with no annotations)")
    print(f"  with segmentation         : {totals['annotations_with_segmentation']}")
    print(f"  images without annotations: {totals['images_without_annotations']}")
    print(f"  duplicate source URLs     : {report['duplicates']['duplicate_source_urls']}")
    if problem_counts:
        print(f"  invalid reasons           : {dict(problem_counts)}")


if __name__ == "__main__":
    main()
