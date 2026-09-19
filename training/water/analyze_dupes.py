"""Duplicate / near-duplicate analysis for a YOLO dataset audited by audit_yolo.py.

Same methodology as the IWHR forensic audit: SHA-256 for exact duplicates, 64-bit dHash for
near-duplicates, and the results reported as PAIRS, UNIQUE IMAGES and GROUPS (connected
components) separately — conflating them overstates duplication several-fold.
"""
import argparse, csv, json, re
from collections import Counter, defaultdict


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


def popcount(x): return bin(x).count("1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--records", required=True)
    ap.add_argument("--out-csv", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--session-regex", default=r"^(exp\d+)_",
                    help="capture group 1 = source session; used only for reporting, never to split")
    ap.add_argument("--thresholds", type=int, nargs="+", default=[0, 2, 5, 8])
    a = ap.parse_args()

    recs = [r for r in json.load(open(a.records))["records"] if "dhash" in r]
    sess = lambda s: (re.match(a.session_regex, s).group(1) if re.match(a.session_regex, s) else "_unmatched")

    by_sha = defaultdict(list)
    for r in recs: by_sha[r["sha256"]].append(r)
    exact = {k: v for k, v in by_sha.items() if len(v) > 1}

    H = [(r["dhash"], r) for r in recs]
    near = defaultdict(list)
    for i in range(len(H)):
        hi, ri = H[i]
        for j in range(i + 1, len(H)):
            hj, rj = H[j]
            d = popcount(hi ^ hj)
            if d <= max(a.thresholds):
                for t in a.thresholds:
                    if d <= t: near[t].append((ri, rj, d))

    summary = {"images_total": len(recs),
               "exact_duplicates": {"groups": len(exact),
                                    "extra_images": sum(len(v) - 1 for v in exact.values()),
                                    "images_involved": sum(len(v) for v in exact.values())},
               "near_duplicates": {}}
    for t in a.thresholds:
        uf = UnionFind(); imgs = set()
        same = cross = 0
        for ri, rj, d in near[t]:
            uf.union(ri["image"], rj["image"]); imgs |= {ri["image"], rj["image"]}
            if sess(ri["stem"]) == sess(rj["stem"]): same += 1
            else: cross += 1
        comp = defaultdict(set)
        for i in imgs: comp[uf.find(i)].add(i)
        sizes = sorted((len(v) for v in comp.values()), reverse=True)
        summary["near_duplicates"][str(t)] = {
            "pairs": len(near[t]), "unique_images": len(imgs),
            "percent_of_dataset": round(100 * len(imgs) / len(recs), 2),
            "groups": len(comp), "largest_group": sizes[0] if sizes else 0,
            "pairs_within_same_session": same, "pairs_crossing_sessions": cross}

    with open(a.out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["type", "hamming_distance", "image_a", "image_b", "stem_a", "stem_b",
                    "session_a", "session_b", "same_session"])
        for g in exact.values():
            for o in g[1:]:
                w.writerow(["exact_duplicate_sha256", 0, g[0]["image"], o["image"], g[0]["stem"], o["stem"],
                            sess(g[0]["stem"]), sess(o["stem"]), sess(g[0]["stem"]) == sess(o["stem"])])
        seen = set()
        for t in a.thresholds:
            for ri, rj, d in near[t]:
                k = (ri["image"], rj["image"])
                if k in seen or ri["sha256"] == rj["sha256"]: continue
                seen.add(k)
                w.writerow(["near_duplicate_dhash", d, ri["image"], rj["image"], ri["stem"], rj["stem"],
                            sess(ri["stem"]), sess(rj["stem"]), sess(ri["stem"]) == sess(rj["stem"])])
    summary["csv_rows"] = sum(len(v) - 1 for v in exact.values()) + len(seen)
    json.dump(summary, open(a.out_json, "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
