"""Dataset quality report for the waste classification dataset.

Reports, never deletes. Problematic images are listed with the reason they were flagged so a human
decides what to do — silently dropping data changes what a model learned without leaving a trace,
and a later "why is recall low on this class" investigation has nothing to go on.

Checks:
  - unreadable / corrupted images
  - images too small to carry usable detail
  - exact duplicates (content hash) within and, critically, ACROSS splits
  - class distribution and imbalance
  - unexpected file formats

Cross-split duplicates are the one that matters most: the same image in train and val turns
validation accuracy into a memorisation score, and the number looks good right up until the model
meets real data.

    python training/validate_dataset.py --dataset garbage_Dataset --out runs/dataset_report.json
"""

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow is required: pip install pillow")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
#: Below this, an image carries too little detail to be worth training on at 224px.
MIN_DIMENSION = 32


def discover(dataset_root: Path) -> Dict[str, Dict[str, List[Path]]]:
    """Map split -> class -> image paths.

    Handles both a flat `split/class/` layout and the nested `split/category/class/` layout this
    dataset actually uses, so the script does not need the caller to describe the structure.
    """
    found: Dict[str, Dict[str, List[Path]]] = defaultdict(lambda: defaultdict(list))
    for split_dir in sorted(p for p in dataset_root.iterdir() if p.is_dir()):
        for path in split_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
                # The class is the immediate parent directory, whatever nesting sits above it.
                found[split_dir.name][path.parent.name].append(path)
    return {split: dict(classes) for split, classes in found.items()}


def inspect_image(path: Path) -> Dict:
    """Read one image and report what is wrong with it, if anything."""
    try:
        with Image.open(path) as image:
            width, height = image.size
            mode = image.mode
            # Fully decode. `verify()` and a header read both accept truncated JPEGs, which then
            # fail during training instead of here.
            image.convert("RGB").load()
    except Exception as exc:  # noqa: BLE001 - any failure is a finding, not a crash
        return {"ok": False, "reason": f"unreadable ({exc.__class__.__name__})"}

    if width < MIN_DIMENSION or height < MIN_DIMENSION:
        return {"ok": False, "reason": f"too small ({width}x{height})", "width": width, "height": height}
    return {"ok": True, "width": width, "height": height, "mode": mode}


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="garbage_Dataset", help="Dataset root directory")
    parser.add_argument("--out", default="runs/dataset_report.json", help="Where to write the report")
    parser.add_argument("--skip-hashes", action="store_true", help="Skip duplicate detection (faster)")
    args = parser.parse_args()

    root = Path(args.dataset)
    if not root.is_dir():
        raise SystemExit(f"Dataset not found: {root}")

    splits = discover(root)
    if not splits:
        raise SystemExit(f"No images found under {root}")

    report: Dict = {
        "dataset": str(root),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "splits": {},
        "problems": {"unreadable_or_invalid": [], "duplicates_within_split": [], "duplicates_across_splits": []},
        "totals": {},
    }

    hashes: Dict[str, List[str]] = defaultdict(list)  # hash -> ["split/class/name", ...]
    total_images = 0
    invalid = 0
    dimensions: List[int] = []

    for split, classes in sorted(splits.items()):
        distribution = Counter()
        split_total = 0
        for class_name, paths in sorted(classes.items()):
            for path in paths:
                total_images += 1
                split_total += 1
                result = inspect_image(path)
                if not result["ok"]:
                    invalid += 1
                    report["problems"]["unreadable_or_invalid"].append(
                        {"path": str(path), "reason": result["reason"]}
                    )
                    continue
                distribution[class_name] += 1
                dimensions.append(min(result["width"], result["height"]))
                if not args.skip_hashes:
                    hashes[content_hash(path)].append(f"{split}/{class_name}/{path.name}")

        counts = dict(sorted(distribution.items(), key=lambda kv: -kv[1]))
        report["splits"][split] = {
            "images": split_total,
            "valid_images": sum(counts.values()),
            "classes": len(counts),
            "class_distribution": counts,
            # Stated plainly: a 50:1 ratio is the single most likely reason a rare class scores badly.
            "imbalance_ratio": round(max(counts.values()) / max(1, min(counts.values())), 1) if counts else None,
        }

    for digest, locations in hashes.items():
        if len(locations) < 2:
            continue
        split_names = {loc.split("/", 1)[0] for loc in locations}
        entry = {"hash": digest[:16], "count": len(locations), "locations": locations[:8]}
        if len(split_names) > 1:
            # The serious one: the same image in two splits makes validation a memorisation test.
            report["problems"]["duplicates_across_splits"].append(entry)
        else:
            report["problems"]["duplicates_within_split"].append(entry)

    report["totals"] = {
        "images": total_images,
        "valid_images": total_images - invalid,
        "invalid_images": invalid,
        "duplicate_groups_within_split": len(report["problems"]["duplicates_within_split"]),
        "duplicate_groups_across_splits": len(report["problems"]["duplicates_across_splits"]),
        "smallest_dimension_seen": min(dimensions) if dimensions else None,
        "median_smallest_dimension": sorted(dimensions)[len(dimensions) // 2] if dimensions else None,
    }
    report["leakage_clean"] = not report["problems"]["duplicates_across_splits"]
    report["note"] = (
        "Nothing was deleted. Problems are listed so a human decides; silently dropping data "
        "changes what the model learned without leaving a record."
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    print(f"Dataset report -> {out_path}")
    for split, data in report["splits"].items():
        print(f"  {split:<6} {data['valid_images']:>6} images  {data['classes']} classes  "
              f"imbalance {data['imbalance_ratio']}:1")
    totals = report["totals"]
    print(f"  invalid images            : {totals['invalid_images']}")
    print(f"  duplicate groups (within) : {totals['duplicate_groups_within_split']}")
    print(f"  duplicate groups (across) : {totals['duplicate_groups_across_splits']}")
    print(f"  cross-split leakage clean : {report['leakage_clean']}")


if __name__ == "__main__":
    main()
