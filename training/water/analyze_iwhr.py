"""Phases 5-7: duplicates and leakage, taxonomy, visual statistics. Reads _records.json."""
import json, csv, os, statistics
from collections import Counter, defaultdict

OUT = "runs/water/iwhr_integration"
TINY_FRAC = 0.01

recs = json.load(open(f"{OUT}/_records.json"))["records"]
valid = [r for r in recs if r.get("valid")]

# ---------------------------------------------------------------- duplicates and leakage
by_sha, by_dh = defaultdict(list), defaultdict(list)
for r in valid:
    by_sha[r["sha256"]].append(r)
    by_dh[r["dhash"]].append(r)

exact = {k: v for k, v in by_sha.items() if len(v) > 1}
dh_ident = {k: v for k, v in by_dh.items() if len(v) > 1}

def popcount(x): return bin(x).count("1")

# Near-duplicates: compare within source group AND across groups. O(n^2) on 3k hashes is fine.
hashes = [(r["dhash"], r) for r in valid]
near = defaultdict(list)   # threshold -> pairs
THRESHOLDS = [0, 2, 5, 8]
for i in range(len(hashes)):
    hi, ri = hashes[i]
    for j in range(i + 1, len(hashes)):
        hj, rj = hashes[j]
        d = popcount(hi ^ hj)
        if d <= max(THRESHOLDS):
            for t in THRESHOLDS:
                if d <= t:
                    near[t].append((ri, rj, d))

cross_pkg_exact = [v for v in exact.values() if len({r["package"] for r in v}) > 1]

with open(f"{OUT}/IWHR_DUPLICATES.csv", "w", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["type", "hamming_distance", "image_a", "image_b", "package_a", "package_b",
                "source_group_a", "source_group_b", "same_group", "cross_package"])
    for group in exact.values():
        base = group[0]
        for other in group[1:]:
            w.writerow(["exact_duplicate_sha256", 0, base["image"], other["image"],
                        base["package"], other["package"], base["source_group"], other["source_group"],
                        base["source_group"] == other["source_group"],
                        base["package"] != other["package"]])
    seen = set()
    for t in THRESHOLDS:
        for a, b, d in near[t]:
            key = (a["image"], b["image"])
            if key in seen or a["sha256"] == b["sha256"]:
                continue
            seen.add(key)
            w.writerow(["near_duplicate_dhash", d, a["image"], b["image"], a["package"], b["package"],
                        a["source_group"], b["source_group"], a["source_group"] == b["source_group"],
                        a["package"] != b["package"]])

# ---------------------------------------------------------------- taxonomy
classes = Counter()
class_imgs = defaultdict(set)
for r in valid:
    for c, n in (r.get("classes") or {}).items():
        classes[c] += n
        class_imgs[c].add(r["image"])

# ---------------------------------------------------------------- source groups
groups = Counter(r["source_group"] for r in valid)
group_pkgs = defaultdict(set)
for r in valid:
    group_pkgs[r["source_group"]].add(r["package"])

# ---------------------------------------------------------------- visual statistics
dims = Counter((r["width"], r["height"]) for r in valid)
ars = Counter(round(r["width"] / r["height"], 3) for r in valid)
per_image = [len(r["objects"]) for r in valid]
areas, rel_areas, widths, heights = [], [], [], []
trunc = diff = 0
for r in valid:
    ia = r["width"] * r["height"]
    for o in r["objects"]:
        x1, y1, x2, y2 = o["box"]
        bw, bh = x2 - x1, y2 - y1
        widths.append(bw); heights.append(bh)
        areas.append(bw * bh); rel_areas.append((bw * bh) / ia)
        trunc += o["truncated"] not in ("0", "")
        diff += o["difficult"] not in ("0", "")

def pct(vals, p): return statistics.quantiles(vals, n=100)[p - 1] if len(vals) > 2 else None
tiny = sum(1 for a in rel_areas if a < TINY_FRAC)
empty = [r for r in valid if not r["objects"]]

stats = {
  "dataset": "IWHR_AI_Lable_Floater_V1",
  "images_total": len(valid), "annotations_total": len(valid),
  "objects_total": sum(classes.values()),
  "classes": {c: {"objects": n, "images": len(class_imgs[c])} for c, n in classes.items()},
  "images_with_no_objects": len(empty),
  "objects_per_image": {"min": min(per_image), "max": max(per_image),
                        "mean": round(statistics.mean(per_image), 2),
                        "median": statistics.median(per_image),
                        "p90": round(pct(per_image, 90), 1), "p99": round(pct(per_image, 99), 1)},
  "image_dimensions": {f"{w}x{h}": n for (w, h), n in dims.most_common()},
  "aspect_ratios": {str(k): v for k, v in ars.most_common()},
  "bbox_pixels": {
      "width":  {"min": round(min(widths), 1), "median": round(statistics.median(widths), 1), "max": round(max(widths), 1)},
      "height": {"min": round(min(heights), 1), "median": round(statistics.median(heights), 1), "max": round(max(heights), 1)},
      "area_median": round(statistics.median(areas), 1)},
  "bbox_relative_area": {
      "p1": round(pct(rel_areas, 1), 6), "p10": round(pct(rel_areas, 10), 6),
      "median": round(statistics.median(rel_areas), 6),
      "p90": round(pct(rel_areas, 90), 6), "max": round(max(rel_areas), 6)},
  "tiny_objects": {"threshold_fraction_of_image_area": TINY_FRAC,
                   "count": tiny, "percent": round(100 * tiny / len(rel_areas), 2)},
  "flags": {"truncated_objects": trunc, "difficult_objects": diff},
  "source_groups": {g: {"images": n, "packages": sorted(group_pkgs[g])} for g, n in groups.most_common()},
  "duplicates": {
      "exact_duplicate_sha256_groups": len(exact),
      "exact_duplicate_extra_images": sum(len(v) - 1 for v in exact.values()),
      "exact_duplicates_cross_package": len(cross_pkg_exact),
      "identical_dhash_groups": len(dh_ident),
      "near_duplicate_pairs_by_hamming": {str(t): len({(a["image"], b["image"]) for a, b, d in near[t]})
                                          for t in THRESHOLDS}},
}
json.dump(stats, open(f"{OUT}/IWHR_DATASET_STATS.json", "w"), indent=2)

print(json.dumps({k: stats[k] for k in ("images_total","objects_total","classes","images_with_no_objects",
      "objects_per_image","image_dimensions","tiny_objects","duplicates","flags")}, indent=2))
print("\nsource groups:")
for g, n in groups.most_common():
    print(f"  {g:28s} {n:5d} images   packages={sorted(group_pkgs[g])}")
print("\nbbox relative area:", stats["bbox_relative_area"])
