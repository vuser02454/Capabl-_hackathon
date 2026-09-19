"""Phase 9: validate a derived YOLO detection dataset before anything is trained on it.

Checks the dataset as a trainer would read it, not as the converter intended to write it.
Exits non-zero if any hard check fails.
"""
import argparse, json, os, sys
from collections import Counter, defaultdict

from PIL import Image
Image.MAX_IMAGE_PIXELS = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="datasets/water/IWHR_AI_Lable_Floater_V1_yolo")
    ap.add_argument("--out", default="runs/water/iwhr_integration/IWHR_YOLO_VALIDATION.json")
    a = ap.parse_args()

    yaml_path = os.path.join(a.dataset, "data.yaml")
    names, nc = {}, None
    for line in open(yaml_path):
        line = line.split("#")[0].rstrip()
        if line.startswith("nc:"):
            nc = int(line.split(":", 1)[1])
        elif line.strip() and line.startswith("  ") and ":" in line:
            k, v = line.strip().split(":", 1)
            if k.isdigit():
                names[int(k)] = v.strip()

    failures, warnings = [], []
    per_split, per_split_boxes = {}, {}
    stems_by_split = {}

    for split in ("train", "val", "test"):
        img_dir = os.path.join(a.dataset, "images", split)
        lbl_dir = os.path.join(a.dataset, "labels", split)
        imgs = sorted(f for f in os.listdir(img_dir) if f.lower().endswith(".jpg"))
        lbls = sorted(f for f in os.listdir(lbl_dir) if f.endswith(".txt"))
        istems = {os.path.splitext(f)[0] for f in imgs}
        lstems = {os.path.splitext(f)[0] for f in lbls}
        stems_by_split[split] = istems

        for s in sorted(istems - lstems): failures.append(f"{split}: image without label: {s}")
        for s in sorted(lstems - istems): failures.append(f"{split}: label without image: {s}")

        boxes = 0
        for stem in sorted(istems & lstems):
            ipath = os.path.join(img_dir, stem + ".jpg")
            if not os.path.exists(os.path.realpath(ipath)):
                failures.append(f"{split}: symlink target missing: {stem}")
                continue
            try:
                with Image.open(ipath) as im: im.verify()
            except Exception as exc:
                failures.append(f"{split}: unreadable image {stem}: {type(exc).__name__}")
                continue
            for n, line in enumerate(open(os.path.join(lbl_dir, stem + ".txt")), 1):
                line = line.strip()
                if not line: continue
                parts = line.split()
                if len(parts) != 5:
                    failures.append(f"{split}/{stem}:{n}: expected 5 fields, got {len(parts)}"); continue
                try:
                    cls = int(parts[0]); cx, cy, bw, bh = (float(v) for v in parts[1:])
                except ValueError:
                    failures.append(f"{split}/{stem}:{n}: non-numeric label"); continue
                boxes += 1
                if cls not in names:
                    failures.append(f"{split}/{stem}:{n}: class id {cls} not in data.yaml")
                if bw <= 0 or bh <= 0:
                    failures.append(f"{split}/{stem}:{n}: non-positive w/h {bw},{bh}")
                for label, v in (("cx", cx), ("cy", cy), ("w", bw), ("h", bh)):
                    if not (0.0 <= v <= 1.0):
                        failures.append(f"{split}/{stem}:{n}: {label}={v} outside [0,1]")
                if cx - bw / 2 < -1e-6 or cx + bw / 2 > 1 + 1e-6 or cy - bh / 2 < -1e-6 or cy + bh / 2 > 1 + 1e-6:
                    failures.append(f"{split}/{stem}:{n}: box extends outside the frame")
        per_split[split] = len(istems)
        per_split_boxes[split] = boxes

    # Leakage: the same underlying source file must not appear in two splits.
    prov_path = os.path.join(a.dataset, "provenance.csv")
    leak = []
    if os.path.exists(prov_path):
        import csv
        by_sha = defaultdict(set)
        for row in csv.DictReader(open(prov_path)):
            by_sha[row["sha256"]].add(row["split"])
        leak = [s for s, sp in by_sha.items() if len(sp) > 1]
        if leak: failures.append(f"{len(leak)} identical images (by sha256) appear in more than one split")

    overlap = [(a_, b_) for a_ in stems_by_split for b_ in stems_by_split
               if a_ < b_ and stems_by_split[a_] & stems_by_split[b_]]
    if overlap: failures.append(f"stem overlap between splits: {overlap}")

    result = {"dataset": os.path.abspath(a.dataset), "classes": names, "nc": nc,
              "images_per_split": per_split, "boxes_per_split": per_split_boxes,
              "images_total": sum(per_split.values()), "boxes_total": sum(per_split_boxes.values()),
              "identical_images_across_splits": len(leak),
              "failures": failures, "warnings": warnings,
              "verdict": "PASS" if not failures else "FAIL"}
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    json.dump(result, open(a.out, "w"), indent=2)
    print(json.dumps({k: result[k] for k in ("classes","nc","images_per_split","boxes_per_split",
          "images_total","boxes_total","identical_images_across_splits","verdict")}, indent=2))
    if failures:
        print("\nFAILURES:"); [print("  -", f) for f in failures[:20]]
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
