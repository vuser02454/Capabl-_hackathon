"""Convert IWHR Pascal VOC -> YOLO detection format, split so no near-duplicate crosses a split.

Derived dataset only. `raw/` is never written to; images are symlinked, not copied, so the
derived tree costs kilobytes and every file's provenance is a readable path back to the original.

The split unit is NOT the image. It is a connected component of:

    (frames sharing a source session)  UNION  (frames within HAMMING of each other)

because this dataset is video frames. Adjacent frames of one water surface are near-identical;
splitting them randomly would put a near-copy of a training frame in validation and score
memorisation as generalisation. Components are assigned whole.
"""

import argparse, csv, json, os, shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone

HAMMING = 2   # dHash distance treated as "near-duplicate" for split isolation


class UnionFind:
    def __init__(self, items): self.parent = {i: i for i in items}
    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.parent[rb] = ra


def build_components(records, dup_rows, hamming):
    uf = UnionFind([r["image"] for r in records])
    first = {}
    for r in records:
        g = r["source_group"]
        if g in first: uf.union(first[g], r["image"])
        else: first[g] = r["image"]
    for row in dup_rows:
        if int(row["hamming_distance"]) <= hamming:
            uf.union(row["image_a"], row["image_b"])
    comps = defaultdict(list)
    for r in records:
        comps[uf.find(r["image"])].append(r)
    return comps


def assign_splits(comps, ratios):
    """Largest component first, into whichever split is furthest below its target.

    Deterministic: components are ordered by (size desc, root id) so the same input always
    produces the same split, with no RNG to seed or drift.
    """
    total = sum(len(v) for v in comps.values())
    targets = {k: total * v for k, v in ratios.items()}
    counts = {k: 0 for k in ratios}
    assignment = {}
    for root, members in sorted(comps.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        split = max(counts, key=lambda k: targets[k] - counts[k])
        assignment[root] = split
        counts[split] += len(members)
    return assignment, counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="runs/water/iwhr_integration/_records.json")
    ap.add_argument("--duplicates", default="runs/water/iwhr_integration/IWHR_DUPLICATES.csv")
    ap.add_argument("--out", default="datasets/water/IWHR_AI_Lable_Floater_V1_yolo")
    ap.add_argument("--hamming", type=int, default=HAMMING)
    ap.add_argument("--report", default="runs/water/iwhr_integration/IWHR_CONVERSION_REPORT.json")
    a = ap.parse_args()

    records = [r for r in json.load(open(a.records))["records"] if r.get("valid")]
    dup_rows = list(csv.DictReader(open(a.duplicates)))

    comps = build_components(records, dup_rows, a.hamming)
    assignment, counts = assign_splits(comps, {"train": 0.70, "val": 0.20, "test": 0.10})

    if os.path.exists(a.out):
        raise SystemExit(f"{a.out} already exists; refusing to overwrite a derived dataset.")
    for split in ("train", "val", "test"):
        os.makedirs(os.path.join(a.out, "images", split), exist_ok=True)
        os.makedirs(os.path.join(a.out, "labels", split), exist_ok=True)

    # One class, exactly as annotated. No class is invented and none is renamed.
    classes = sorted({c for r in records for c in (r.get("classes") or {})})
    class_index = {c: i for i, c in enumerate(classes)}

    provenance, split_of, written_boxes, clipped = [], {}, 0, 0
    for root, members in comps.items():
        split = assignment[root]
        for r in members:
            split_of[r["image"]] = split
            stem = f'{r["package"]}_{r["stem"]}'      # package-qualified: stems repeat across packages
            src = os.path.abspath(r["image"])
            dst = os.path.join(a.out, "images", split, stem + ".jpg")
            if not os.path.exists(dst):
                os.symlink(src, dst)

            iw, ih = r["width"], r["height"]
            lines = []
            for o in r["objects"]:
                x1, y1, x2, y2 = o["box"]
                # Already clipped to the frame by the audit; re-assert here so a label file can
                # never carry a coordinate outside [0,1] even if the inputs change.
                nx1, ny1 = max(0.0, x1) / iw, max(0.0, y1) / ih
                nx2, ny2 = min(float(iw), x2) / iw, min(float(ih), y2) / ih
                if nx2 <= nx1 or ny2 <= ny1:
                    continue
                cx, cy = (nx1 + nx2) / 2, (ny1 + ny2) / 2
                bw, bh = nx2 - nx1, ny2 - ny1
                lines.append(f"{class_index[o['class']]} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            written_boxes += len(lines)
            with open(os.path.join(a.out, "labels", split, stem + ".txt"), "w") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))

            provenance.append({"yolo_stem": stem, "split": split, "component": str(root),
                               "source_group": r["source_group"], "package": r["package"],
                               "original_image": r["image"],
                               "original_annotation": r["image"].replace("JPEGImages", "Annotations").replace(".jpg", ".xml"),
                               "internal_filename": r.get("internal_filename"),
                               "sha256": r["sha256"], "objects": len(lines),
                               "width": iw, "height": ih})

    with open(os.path.join(a.out, "data.yaml"), "w") as fh:
        fh.write("# IWHR_AI_Lable_Floater_V1 - derived YOLO detection dataset\n")
        fh.write("# Generated by training/water/convert_iwhr_to_yolo.py. Do not edit by hand.\n")
        fh.write("# Class names are exactly those annotated in the source VOC XML.\n")
        fh.write(f"path: {os.path.abspath(a.out)}\n")
        fh.write("train: images/train\nval: images/val\ntest: images/test\n\n")
        fh.write(f"nc: {len(classes)}\nnames:\n")
        for i, c in enumerate(classes):
            fh.write(f"  {i}: {c}\n")

    with open(os.path.join(a.out, "provenance.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(provenance[0].keys()))
        w.writeheader(); w.writerows(provenance)

    # Residual leakage check: any near-duplicate pair that still spans two splits.
    residual = []
    for row in dup_rows:
        sa, sb = split_of.get(row["image_a"]), split_of.get(row["image_b"])
        if sa and sb and sa != sb:
            residual.append({"hamming": int(row["hamming_distance"]), "a": row["image_a"],
                             "b": row["image_b"], "split_a": sa, "split_b": sb})

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "datasets/water/IWHR_AI_Lable_Floater_V1/raw (symlinked, never modified)",
        "output": os.path.abspath(a.out),
        "image_storage": "symlinks to raw/ - the derived tree duplicates no image bytes",
        "classes": classes, "nc": len(classes),
        "split_unit": f"connected component of (source session) U (dHash distance <= {a.hamming})",
        "components": len(comps),
        "component_sizes": sorted((len(v) for v in comps.values()), reverse=True),
        "split_counts": counts,
        "split_percent": {k: round(100 * v / sum(counts.values()), 1) for k, v in counts.items()},
        "images_written": len(provenance), "boxes_written": written_boxes,
        "split_by_source_group": {
            g: dict(Counter(p["split"] for p in provenance if p["source_group"] == g))
            for g in sorted({p["source_group"] for p in provenance})},
        "residual_cross_split_near_duplicates": {
            "threshold_used_for_isolation": a.hamming,
            "count_at_any_recorded_distance": len(residual),
            "by_distance": dict(Counter(r["hamming"] for r in residual)),
            "examples": residual[:10]},
    }
    json.dump(report, open(a.report, "w"), indent=2)
    print(json.dumps({k: report[k] for k in ("classes", "components", "component_sizes",
          "split_counts", "split_percent", "images_written", "boxes_written")}, indent=2))
    print("residual cross-split near-dups:", report["residual_cross_split_near_duplicates"]["by_distance"])
    print("split by source group:", json.dumps(report["split_by_source_group"], indent=2))


if __name__ == "__main__":
    main()
