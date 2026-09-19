"""Audit the Roboflow Flow-Img v2 YOLOv8 export. Reports; repairs nothing, deletes nothing.

Same discipline as the IWHR audit: every figure comes from reading the files, the label file is
read as a trainer would read it, and defects are recorded with the value that produced them
rather than silently fixed.
"""
import argparse, csv, hashlib, json, os, statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

DHASH_SIDE = 8
TINY_FRAC = 0.01


def dhash(path):
    with Image.open(path) as im:
        w, h = im.size
        fmt, mode = im.format, im.mode
        im.draft("L", (DHASH_SIDE * 4, DHASH_SIDE * 4))
        small = im.convert("L").resize((DHASH_SIDE + 1, DHASH_SIDE), Image.BILINEAR)
        px = list(small.getdata())
    bits = 0
    for r in range(DHASH_SIDE):
        b = r * (DHASH_SIDE + 1)
        for c in range(DHASH_SIDE):
            bits = (bits << 1) | int(px[b + c] > px[b + c + 1])
    return bits, w, h, fmt, mode


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def parse_yaml(path):
    """Minimal reader for the handful of keys a Roboflow data.yaml carries."""
    out, section = {}, None
    for line in open(path):
        raw = line.rstrip("\n")
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if not raw.startswith(" ") and ":" in raw:
            k, v = raw.split(":", 1)
            section = k.strip()
            out[section] = v.strip()
        elif raw.startswith(" ") and ":" in raw:
            k, v = raw.strip().split(":", 1)
            out[f"{section}.{k.strip()}"] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="water_datasets/Flow-Img.v2i.yolov8")
    ap.add_argument("--out", default="runs/water/flow_integration")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    cfg = parse_yaml(os.path.join(a.root, "data.yaml"))
    names = [n.strip().strip("'\"") for n in cfg.get("names", "[]").strip("[]").split(",") if n.strip()]
    nc = int(cfg.get("nc", 0))

    # Which split directories actually exist, versus what data.yaml claims.
    declared = {k: cfg.get(k) for k in ("train", "val", "test")}
    present = {s: os.path.isdir(os.path.join(a.root, s, "images")) for s in ("train", "valid", "val", "test")}

    records, problems = [], []
    by_sha, by_dh = defaultdict(list), defaultdict(list)
    cls_objects, cls_images = Counter(), defaultdict(set)

    for split in ("train", "valid", "val", "test"):
        idir = os.path.join(a.root, split, "images")
        ldir = os.path.join(a.root, split, "labels")
        if not os.path.isdir(idir):
            continue
        imgs = sorted(f for f in os.listdir(idir) if f.lower().endswith((".jpg", ".jpeg", ".png")))
        lbls = sorted(f for f in os.listdir(ldir)) if os.path.isdir(ldir) else []
        istems = {os.path.splitext(f)[0] for f in imgs}
        lstems = {os.path.splitext(f)[0] for f in lbls if f.endswith(".txt")}

        for s in sorted(lstems - istems):
            problems.append([f"{split}/{s}", "", "missing_image", "label has no image", "recorded"])
        for s in sorted(istems - lstems):
            problems.append([f"{split}/{s}", "", "missing_label", "image has no label file", "recorded"])

        for f in imgs:
            stem = os.path.splitext(f)[0]
            ipath = os.path.join(idir, f)
            lpath = os.path.join(ldir, stem + ".txt")
            rec = {"split": split, "stem": stem, "image": ipath, "label": lpath, "objects": []}
            try:
                bits, w, h, fmt, mode = dhash(ipath)
            except Exception as exc:
                problems.append([f"{split}/{stem}", lpath, "unreadable_image", f"{type(exc).__name__}", "image rejected"])
                continue
            rec.update(width=w, height=h, format=fmt, mode=mode, dhash=bits, sha256=sha256(ipath))
            by_sha[rec["sha256"]].append(rec)
            by_dh[bits].append(rec)

            if not os.path.isfile(lpath):
                records.append(rec)
                continue
            lines = [ln for ln in open(lpath).read().splitlines() if ln.strip()]
            if not lines:
                problems.append([f"{split}/{stem}", lpath, "empty_label", "0 lines", "image kept as background/negative"])
            seen = set()
            for n, ln in enumerate(lines, 1):
                parts = ln.split()
                if len(parts) != 5:
                    problems.append([f"{split}/{stem}", lpath, "malformed_line", f"line {n}: {len(parts)} fields", "object rejected"])
                    continue
                try:
                    cid = int(parts[0]); cx, cy, bw, bh = (float(v) for v in parts[1:])
                except ValueError:
                    problems.append([f"{split}/{stem}", lpath, "non_numeric_label", f"line {n}: {ln}", "object rejected"])
                    continue
                orig = f"{cid} {cx:g} {cy:g} {bw:g} {bh:g}"
                if cid < 0 or cid >= nc:
                    problems.append([f"{split}/{stem}", lpath, "unknown_class_id", orig, "object rejected"])
                    continue
                if bw <= 0 or bh <= 0:
                    problems.append([f"{split}/{stem}", lpath, "zero_or_negative_wh", orig, "object rejected"])
                    continue
                if any(v < 0 or v > 1 for v in (cx, cy, bw, bh)):
                    problems.append([f"{split}/{stem}", lpath, "coordinate_outside_0_1", orig, "object rejected"])
                    continue
                if cx - bw/2 < -1e-6 or cx + bw/2 > 1+1e-6 or cy - bh/2 < -1e-6 or cy + bh/2 > 1+1e-6:
                    problems.append([f"{split}/{stem}", lpath, "box_extends_past_frame", orig, "recorded, box kept"])
                key = (cid, round(cx, 6), round(cy, 6), round(bw, 6), round(bh, 6))
                if key in seen:
                    problems.append([f"{split}/{stem}", lpath, "duplicate_annotation", orig, "duplicate dropped"])
                    continue
                seen.add(key)
                rec["objects"].append({"cls": cid, "cxcywh": [cx, cy, bw, bh]})
                cls_objects[names[cid] if cid < len(names) else str(cid)] += 1
                cls_images[names[cid] if cid < len(names) else str(cid)].add(ipath)
            records.append(rec)

    with open(os.path.join(a.out, "invalid_labels.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["image", "label", "problem", "original_value", "action"]); w.writerows(problems)

    json.dump({"generated_at": datetime.now(timezone.utc).isoformat(), "records": records},
              open(os.path.join(a.out, "_records.json"), "w"))

    print(f"records={len(records)} problems={len(problems)} classes={dict(cls_objects)}")
    print(f"data.yaml: nc={nc} names={names}")
    print(f"declared splits={declared}")
    print(f"split dirs present={present}")
    print(f"exact-dup groups={sum(1 for v in by_sha.values() if len(v)>1)} identical-dhash groups={sum(1 for v in by_dh.values() if len(v)>1)}")


if __name__ == "__main__":
    main()
