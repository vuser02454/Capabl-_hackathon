"""Design a deterministic session-level train/val/test split for TUD-GV.

Writes a MANIFEST ONLY. No image is copied, moved, symlinked or modified; no dataset is created.

The split unit is a connected component of:

    (frames sharing an `exp` session)  UNION  (frames within dHash distance 2)

Session alone would leave the 55 cross-session near-duplicate pairs at distance <= 2 spanning
splits. Merging those sessions into components removes that residue by construction, at the cost
of coarser split granularity. Components are assigned whole, largest first, to whichever split is
furthest below its target — deterministic, no RNG.
"""
import argparse, csv, json, re
from collections import Counter, defaultdict
from datetime import datetime, timezone


class UnionFind:
    def __init__(self): self.p = {}
    def add(self, x): self.p.setdefault(x, x)
    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b):
        self.add(a); self.add(b)
        ra, rb = self.find(a), self.find(b)
        if ra != rb: self.p[rb] = ra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", default="runs/water/tudgv_integration/_records.json")
    ap.add_argument("--duplicates", default="runs/water/tudgv_integration/TUDGV_DUPLICATES.csv")
    ap.add_argument("--out", default="runs/water/dataset_comparison/TUDGV_SPLIT_MANIFEST.json")
    ap.add_argument("--hamming", type=int, default=2)
    ap.add_argument("--ratios", type=float, nargs=3, default=[0.70, 0.20, 0.10])
    a = ap.parse_args()

    doc = json.load(open(a.records))
    recs = [r for r in doc["records"] if "dhash" in r]
    sess = lambda s: re.match(r"^(exp\d+)_", s).group(1)

    # sessions -> components, merged by cross-session near-duplicates at <= hamming
    uf = UnionFind()
    for r in recs: uf.add(sess(r["stem"]))
    dup_rows = list(csv.DictReader(open(a.duplicates)))
    merged_by_dupes = []
    for row in dup_rows:
        if int(row["hamming_distance"]) <= a.hamming and row["session_a"] != row["session_b"]:
            if uf.find(row["session_a"]) != uf.find(row["session_b"]):
                merged_by_dupes.append((row["session_a"], row["session_b"], int(row["hamming_distance"])))
            uf.union(row["session_a"], row["session_b"])

    comp_of_sess = {s: uf.find(s) for s in {sess(r["stem"]) for r in recs}}
    comps = defaultdict(list)
    for r in recs: comps[comp_of_sess[sess(r["stem"])]].append(r)

    targets = dict(zip(("train", "val", "test"), (x * len(recs) for x in a.ratios)))
    counts = {k: 0 for k in targets}
    assign = {}
    for root, members in sorted(comps.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        split = max(counts, key=lambda k: targets[k] - counts[k])
        assign[root] = split
        counts[split] += len(members)

    split_of_img, per = {}, defaultdict(lambda: {"images": 0, "boxes": 0, "sessions": set(), "components": set()})
    for root, members in comps.items():
        sp = assign[root]
        for r in members:
            split_of_img[r["image"]] = sp
            per[sp]["images"] += 1
            per[sp]["boxes"] += len(r["objects"])
            per[sp]["sessions"].add(sess(r["stem"]))
            per[sp]["components"].add(root)

    # residual leakage: any near-duplicate pair still spanning two splits
    residual = defaultdict(list)
    for row in dup_rows:
        sa, sb = split_of_img.get(row["image_a"]), split_of_img.get(row["image_b"])
        if sa and sb and sa != sb:
            residual[int(row["hamming_distance"])].append(
                {"hamming": int(row["hamming_distance"]), "a": row["stem_a"], "b": row["stem_b"],
                 "split_a": sa, "split_b": sb})

    total_imgs = sum(v["images"] for v in per.values())
    total_boxes = sum(v["boxes"] for v in per.values())
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "TUD-GV",
        "source": "water_datasets/TUD-GV (READ ONLY - not modified, not copied)",
        "status": "MANIFEST ONLY - no training dataset was created",
        "classes": doc["classes"],
        "method": {
            "split_unit": f"connected component of (exp session) UNION (dHash distance <= {a.hamming})",
            "determinism": "components ordered by (size desc, root id); assigned to the split furthest below target; no RNG, no seed",
            "target_ratios": dict(zip(("train", "val", "test"), a.ratios)),
            "rationale": "Frames are subsampled video; 34.78% of images have a near-duplicate at <=2 "
                         "and 98.3% of those pairs are intra-session. Session grouping removes almost "
                         "all of it; merging the cross-session pairs removes the rest.",
        },
        "sessions_total": len({sess(r["stem"]) for r in recs}),
        "components_total": len(comps),
        "sessions_merged_by_cross_session_duplicates": [
            {"session_a": x, "session_b": y, "hamming": d} for x, y, d in merged_by_dupes],
        "splits": {
            sp: {
                "sessions": sorted(v["sessions"], key=lambda s: int(s[3:])),
                "session_count": len(v["sessions"]),
                "component_count": len(v["components"]),
                "images": v["images"],
                "boxes": v["boxes"],
                "image_ratio": round(v["images"] / total_imgs, 4),
                "box_ratio": round(v["boxes"] / total_boxes, 4),
                "boxes_per_image": round(v["boxes"] / v["images"], 2),
                "class_distribution": {doc["classes"][0]: v["boxes"]},
            } for sp, v in sorted(per.items())
        },
        "totals": {"images": total_imgs, "boxes": total_boxes,
                   "images_expected": 1501, "boxes_expected": 8181,
                   "images_match": total_imgs == 1501, "boxes_match": total_boxes == 8181},
        "near_duplicate_isolation": {
            "isolation_threshold": a.hamming,
            "cross_split_pairs_at_or_below_threshold": sum(len(v) for k, v in residual.items() if k <= a.hamming),
            "cross_split_pairs_by_distance": {str(k): len(v) for k, v in sorted(residual.items())},
            "cross_split_pairs_total": sum(len(v) for v in residual.values()),
            "examples_above_threshold": [x for k in sorted(residual) for x in residual[k]][:10],
        },
        "image_assignment": {r["stem"]: split_of_img[r["image"]] for r in sorted(recs, key=lambda r: r["stem"])},
    }
    json.dump(manifest, open(a.out, "w"), indent=2)
    show = {k: manifest[k] for k in ("sessions_total", "components_total",
                                     "sessions_merged_by_cross_session_duplicates", "totals",
                                     "near_duplicate_isolation")}
    show["near_duplicate_isolation"].pop("examples_above_threshold", None)
    print(json.dumps(show, indent=2))
    for sp, v in manifest["splits"].items():
        print(f'{sp:6s} sessions={v["session_count"]:3d} images={v["images"]:5d} ({v["image_ratio"]*100:.1f}%) '
              f'boxes={v["boxes"]:5d} ({v["box_ratio"]*100:.1f}%) box/img={v["boxes_per_image"]}')
        print(f'       {v["sessions"]}')


if __name__ == "__main__":
    main()
