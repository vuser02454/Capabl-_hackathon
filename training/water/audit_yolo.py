"""Generic YOLO-detection dataset auditor.

Supersedes `audit_flow.py` by making the two things that differed between datasets into
arguments: where images and labels live, and where class names come from. It reproduces
`audit_flow.py`'s Flow-Img numbers exactly (verified), so there is one auditor, not one per
dataset.

Two layouts are handled:

  roboflow  <root>/{train,valid,val,test}/{images,labels}   + data.yaml for names
  flat      <root>/<images-dir> and <root>/<labels-dir>     + classes.txt for names

Reports; repairs nothing, deletes nothing. Every defect is recorded with the value that produced
it, in the same CSV shape the IWHR and FloW audits used.
"""
import argparse, csv, hashlib, json, os
from collections import Counter, defaultdict
from datetime import datetime, timezone

from PIL import Image
Image.MAX_IMAGE_PIXELS = None

DHASH_SIDE = 8
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")


def dhash(path):
    """64-bit difference hash plus real pixel size. `draft` downscales during JPEG decode."""
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
    out, section = {}, None
    for line in open(path):
        raw = line.rstrip("\n")
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        if not raw.startswith(" ") and ":" in raw:
            k, v = raw.split(":", 1); section = k.strip(); out[section] = v.strip()
        elif raw.startswith(" ") and ":" in raw:
            k, v = raw.strip().split(":", 1); out[f"{section}.{k.strip()}"] = v.strip()
    return out


def load_classes(root, classes_file, data_yaml):
    """Class names, from classes.txt or data.yaml. Never guessed, never defaulted to a name."""
    if classes_file:
        p = os.path.join(root, classes_file)
        # A trailing newline is optional; a blank line is not a class.
        names = [ln.strip() for ln in open(p).read().splitlines() if ln.strip()]
        return names, {"source": p, "raw_bytes": os.path.getsize(p)}
    p = os.path.join(root, data_yaml)
    cfg = parse_yaml(p)
    names = [n.strip().strip("'\"") for n in cfg.get("names", "[]").strip("[]").split(",") if n.strip()]
    return names, {"source": p, "nc_declared": cfg.get("nc"), "cfg": cfg}


def discover(root, layout, images_dir, labels_dir):
    """-> [(split_label, image_dir, label_dir)]. `split_label` is 'flat' when there is no split."""
    if layout == "flat":
        return [("flat", os.path.join(root, images_dir), os.path.join(root, labels_dir))]
    found = []
    for s in ("train", "valid", "val", "test"):
        idir = os.path.join(root, s, "images")
        if os.path.isdir(idir):
            found.append((s, idir, os.path.join(root, s, "labels")))
    return found


def audit(root, layout, images_dir, labels_dir, classes_file, data_yaml, out):
    os.makedirs(out, exist_ok=True)
    names, class_meta = load_classes(root, classes_file, data_yaml)
    nc = len(names)

    records, problems = [], []
    by_sha, by_dh = defaultdict(list), defaultdict(list)
    cls_obj, cls_img = Counter(), defaultdict(set)
    splits = discover(root, layout, images_dir, labels_dir)

    for split, idir, ldir in splits:
        imgs = sorted(f for f in os.listdir(idir) if f.lower().endswith(IMG_EXT)) if os.path.isdir(idir) else []
        non_img = sorted(f for f in os.listdir(idir) if not f.lower().endswith(IMG_EXT)) if os.path.isdir(idir) else []
        lbls = sorted(f for f in os.listdir(ldir) if f.endswith(".txt")) if os.path.isdir(ldir) else []
        non_lbl = sorted(f for f in os.listdir(ldir) if not f.endswith(".txt")) if os.path.isdir(ldir) else []
        for f in non_img:
            problems.append([os.path.join(idir, f), "", "non_image_file_in_images_dir", f, "recorded, ignored"])
        for f in non_lbl:
            problems.append(["", os.path.join(ldir, f), "non_txt_file_in_labels_dir", f, "recorded, ignored"])

        istems = {os.path.splitext(f)[0] for f in imgs}
        lstems = {os.path.splitext(f)[0] for f in lbls}
        for s in sorted(lstems - istems):
            problems.append(["", os.path.join(ldir, s + ".txt"), "orphan_label_no_image", s, "recorded"])
        for s in sorted(istems - lstems):
            problems.append([os.path.join(idir, s), "", "missing_label", s, "recorded"])

        # Duplicate stems differing only by extension (e.g. a.jpg and a.png).
        stem_counts = Counter(os.path.splitext(f)[0] for f in imgs)
        for s, n in stem_counts.items():
            if n > 1:
                problems.append([os.path.join(idir, s), "", "duplicate_filename_stem", f"{n} images share stem", "recorded"])

        for f in imgs:
            stem = os.path.splitext(f)[0]
            ipath, lpath = os.path.join(idir, f), os.path.join(ldir, stem + ".txt")
            rec = {"split": split, "stem": stem, "image": ipath, "label": lpath, "objects": []}

            if os.path.getsize(ipath) == 0:
                problems.append([ipath, lpath, "zero_byte_image", "0 bytes", "image rejected"])
                continue
            try:
                bits, w, h, fmt, mode = dhash(ipath)
                with Image.open(ipath) as im:
                    im.verify()               # catches truncation/corruption the decode above may tolerate
            except Exception as exc:
                problems.append([ipath, lpath, "unreadable_or_corrupt_image", f"{type(exc).__name__}: {exc}", "image rejected"])
                continue
            rec.update(width=w, height=h, format=fmt, mode=mode, dhash=bits, sha256=sha256(ipath))
            by_sha[rec["sha256"]].append(rec); by_dh[bits].append(rec)

            if not os.path.isfile(lpath):
                records.append(rec); continue
            if os.path.getsize(lpath) == 0:
                problems.append([ipath, lpath, "zero_byte_label", "0 bytes", "image kept as background/negative"])
                records.append(rec); continue

            lines = [ln for ln in open(lpath).read().splitlines() if ln.strip()]
            if not lines:
                problems.append([ipath, lpath, "empty_label", "0 annotation lines", "image kept as background/negative"])
            seen = set()
            for n, ln in enumerate(lines, 1):
                parts = ln.split()
                if len(parts) != 5:
                    problems.append([ipath, lpath, "malformed_line", f"line {n}: {len(parts)} fields: {ln}", "object rejected"]); continue
                try:
                    cid = int(parts[0]); cx, cy, bw, bh = (float(v) for v in parts[1:])
                except ValueError:
                    problems.append([ipath, lpath, "non_numeric_label", f"line {n}: {ln}", "object rejected"]); continue
                orig = f"{cid} {cx:g} {cy:g} {bw:g} {bh:g}"
                if cid < 0 or cid >= nc:
                    problems.append([ipath, lpath, "class_id_not_in_classes_file", orig, "object rejected"]); continue
                if bw <= 0 or bh <= 0:
                    problems.append([ipath, lpath, "zero_or_negative_wh", orig, "object rejected"]); continue
                if not (0 <= cx <= 1 and 0 <= cy <= 1 and 0 < bw <= 1 and 0 < bh <= 1):
                    problems.append([ipath, lpath, "coordinate_outside_0_1", orig, "object rejected"]); continue
                x1, y1, x2, y2 = cx - bw/2, cy - bh/2, cx + bw/2, cy + bh/2
                if x1 < -1e-9 or y1 < -1e-9 or x2 > 1+1e-9 or y2 > 1+1e-9:
                    problems.append([ipath, lpath, "box_extends_past_frame",
                                     f"{orig} -> x1={x1:.6f} y1={y1:.6f} x2={x2:.6f} y2={y2:.6f}",
                                     "recorded, box kept"])
                key = (cid, round(cx, 6), round(cy, 6), round(bw, 6), round(bh, 6))
                if key in seen:
                    problems.append([ipath, lpath, "duplicate_annotation", orig, "duplicate dropped"]); continue
                seen.add(key)
                rec["objects"].append({"cls": cid, "cxcywh": [cx, cy, bw, bh]})
                label = names[cid]
                cls_obj[label] += 1; cls_img[label].add(ipath)
            records.append(rec)

    with open(os.path.join(out, "invalid_annotations.csv"), "w", newline="") as fh:
        w = csv.writer(fh); w.writerow(["image", "label", "problem", "original_value", "action"]); w.writerows(problems)
    json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
               "root": root, "classes": names, "class_meta": class_meta, "records": records},
              open(os.path.join(out, "_records.json"), "w"))

    return {"records": records, "problems": problems, "names": names,
            "cls_obj": cls_obj, "cls_img": {k: len(v) for k, v in cls_img.items()},
            "by_sha": by_sha, "by_dh": by_dh, "splits": [s for s, _, _ in splits]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--layout", choices=("flat", "roboflow"), default="flat")
    ap.add_argument("--images-dir", default="images")
    ap.add_argument("--labels-dir", default="labels_txt")
    ap.add_argument("--classes-file", default=None, help="e.g. classes.txt; omit to read data.yaml")
    ap.add_argument("--data-yaml", default="data.yaml")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    r = audit(a.root, a.layout, a.images_dir, a.labels_dir, a.classes_file, a.data_yaml, a.out)
    print(f"splits={r['splits']} records={len(r['records'])} problems={len(r['problems'])}")
    print(f"classes={r['names']}")
    print(f"objects per class={dict(r['cls_obj'])}")
    print(f"images per class={r['cls_img']}")
    print(f"exact-dup groups={sum(1 for v in r['by_sha'].values() if len(v)>1)} "
          f"identical-dhash groups={sum(1 for v in r['by_dh'].values() if len(v)>1)}")
