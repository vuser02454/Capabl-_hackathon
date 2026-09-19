"""Audit the IWHR_AI_Lable_Floater_V1 dataset. Reports; repairs nothing, deletes nothing.

One pass over every XML and every image produces the evidence for phases 3-7:
structure, annotation validity, duplicates/leakage, taxonomy and visual statistics.

Nothing here writes to raw/. Every finding is recorded with the value that produced it, so a
reader can disagree with a judgement without re-running the audit.
"""

import argparse, csv, hashlib, json, os, sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

#: dHash side; 8 -> 64-bit hash. Near-duplicate threshold is a Hamming distance, reported at
#: several cut-offs rather than one, because "near-duplicate" is a judgement, not a constant.
DHASH_SIDE = 8
TINY_FRAC = 0.01   # object smaller than this fraction of image area counts as tiny (COCO-ish "small")


def source_group(internal_filename: str) -> str:
    """The capture session a frame came from, read from the ORIGINAL filename the annotation
    carries, not from the renumbered file on disk.

    Sequential frames of one session must not be split across train and val: adjacent frames of
    the same water surface are near-identical, and a random split would score memorisation.

    Rules are derived from the filename shapes actually present in this dataset, not guessed:

        rubbish-1208.jpg          -> rubbish            (one session, frame index 1208)
        fishing-1,0023.jpg        -> fishing-1          (session number before the comma)
        image-0042.jpg            -> image
        2022-07-20-093412.jpg     -> 2022-07-20         (one capture date)
        5-11_mix_data_4317.jpg    -> 5-11_mix_data
        01703.jpg                 -> _bare_numeric      (provenance unknown)

    `_bare_numeric` groups all 163 unattributable frames together deliberately. Their source is
    unknown, so they cannot be shown to be independent; keeping them in one split is the
    conservative reading, because the cost of being wrong is leakage.
    """
    stem = os.path.splitext(os.path.basename(internal_filename.replace("\\", "/")))[0]
    if not stem:
        return "_no_filename_field"
    if "," in stem:                                    # fishing-1,0023
        return stem.split(",", 1)[0]
    if "_mix_data_" in stem:                           # 5-11_mix_data_4317
        return stem.split("_mix_data_", 1)[0] + "_mix_data"
    parts = stem.split("-")
    if len(parts) >= 4 and all(p.isdigit() for p in parts):   # 2022-07-20-093412
        return "-".join(parts[:3])
    if len(parts) == 2 and not parts[0].isdigit():     # rubbish-1208, image-0042
        return parts[0]
    if stem.isdigit():
        return "_bare_numeric"
    return stem


def dhash(path: str):
    """64-bit difference hash, plus the real pixel dimensions.

    `draft` lets libjpeg downscale during decode, which is what makes 3,000 full-HD frames
    practical to hash in one pass.
    """
    with Image.open(path) as im:
        width, height = im.size
        fmt, mode = im.format, im.mode
        im.draft("L", (DHASH_SIDE * 4, DHASH_SIDE * 4))
        small = im.convert("L").resize((DHASH_SIDE + 1, DHASH_SIDE), Image.BILINEAR)
        px = list(small.getdata())
    bits = 0
    for row in range(DHASH_SIDE):
        base = row * (DHASH_SIDE + 1)
        for col in range(DHASH_SIDE):
            bits = (bits << 1) | int(px[base + col] > px[base + col + 1])
    return bits, width, height, fmt, mode


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def audit(root: str, packages, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    records, problems = [], []
    classes = Counter()
    class_images = defaultdict(set)
    by_sha = defaultdict(list)
    by_dhash = defaultdict(list)

    for pkg in packages:
        ann_dir = os.path.join(root, pkg, "Annotations")
        img_dir = os.path.join(root, pkg, "JPEGImages")
        for name in sorted(os.listdir(ann_dir)):
            if not name.endswith(".xml"):
                continue
            stem = os.path.splitext(name)[0]
            xml_path = os.path.join(ann_dir, name)
            img_path = os.path.join(img_dir, stem + ".jpg")
            rec = {"package": pkg, "stem": stem, "xml": xml_path, "image": img_path,
                   "objects": [], "classes": Counter()}

            if not os.path.isfile(img_path):
                problems.append([img_path, xml_path, "missing_image", "", "annotation rejected"])
                rec["valid"] = False
                records.append(rec)
                continue

            try:
                tree = ET.parse(xml_path)
            except ET.ParseError as exc:
                problems.append([img_path, xml_path, "malformed_xml", str(exc), "annotation rejected"])
                rec["valid"] = False
                records.append(rec)
                continue
            node = tree.getroot()

            internal = (node.findtext("filename") or "").strip()
            rec["internal_filename"] = internal
            rec["source_group"] = source_group(internal) if internal else "_no_filename_field"

            size = node.find("size")
            dw = int(float(size.findtext("width") or 0)) if size is not None else 0
            dh_ = int(float(size.findtext("height") or 0)) if size is not None else 0

            try:
                bits, iw, ih, fmt, mode = dhash(img_path)
            except Exception as exc:
                problems.append([img_path, xml_path, "unreadable_image", f"{type(exc).__name__}: {exc}", "annotation rejected"])
                rec["valid"] = False
                records.append(rec)
                continue

            rec.update(width=iw, height=ih, format=fmt, mode=mode,
                       declared_width=dw, declared_height=dh_, dhash=bits)
            if dw <= 0 or dh_ <= 0:
                problems.append([img_path, xml_path, "impossible_declared_dimensions", f"{dw}x{dh_}", "declared size ignored; real pixels used"])
            elif (dw, dh_) != (iw, ih):
                problems.append([img_path, xml_path, "declared_size_mismatch", f"declared {dw}x{dh_}, actual {iw}x{ih}", "real pixels used for normalisation"])

            digest = sha256(img_path)
            rec["sha256"] = digest
            by_sha[digest].append(rec)
            by_dhash[bits].append(rec)

            seen_boxes = set()
            for obj in node.findall("object"):
                cname = (obj.findtext("name") or "").strip()
                bb = obj.find("bndbox")
                if not cname or bb is None:
                    problems.append([img_path, xml_path, "object_missing_name_or_bndbox", cname or "<empty>", "object rejected"])
                    continue
                try:
                    x1 = float(bb.findtext("xmin")); y1 = float(bb.findtext("ymin"))
                    x2 = float(bb.findtext("xmax")); y2 = float(bb.findtext("ymax"))
                except (TypeError, ValueError) as exc:
                    problems.append([img_path, xml_path, "non_numeric_bndbox", str(exc), "object rejected"])
                    continue

                original = f"[{x1:g},{y1:g},{x2:g},{y2:g}]"
                if x2 < x1 or y2 < y1:
                    problems.append([img_path, xml_path, "inverted_box", original, "object rejected"])
                    continue
                if x2 == x1 or y2 == y1:
                    problems.append([img_path, xml_path, "zero_area_box", original, "object rejected"])
                    continue

                neg = x1 < 0 or y1 < 0
                over = x2 > iw or y2 > ih
                cx1, cy1 = max(0.0, x1), max(0.0, y1)
                cx2, cy2 = min(float(iw), x2), min(float(ih), y2)
                if neg or over:
                    # VOC boxes are absolute pixels in the frame the annotator saw; a box running a
                    # few pixels past the edge is a truncated object, and clipping to the frame is
                    # the documented VOC semantic. Anything that clips away to nothing is rejected.
                    if cx2 - cx1 <= 0 or cy2 - cy1 <= 0:
                        problems.append([img_path, xml_path, "box_entirely_outside_image", original, "object rejected"])
                        continue
                    problems.append([img_path, xml_path,
                                     "box_outside_image_bounds" if over else "negative_coordinate",
                                     original, f"clipped to frame [{cx1:g},{cy1:g},{cx2:g},{cy2:g}]"])

                key = (cname, round(cx1), round(cy1), round(cx2), round(cy2))
                if key in seen_boxes:
                    problems.append([img_path, xml_path, "duplicate_annotation", original, "duplicate object dropped"])
                    continue
                seen_boxes.add(key)

                rec["objects"].append({"class": cname, "box": [cx1, cy1, cx2, cy2],
                                       "truncated": (obj.findtext("truncated") or "0").strip(),
                                       "difficult": (obj.findtext("difficult") or "0").strip()})
                rec["classes"][cname] += 1
                classes[cname] += 1
                class_images[cname].add(f"{pkg}/{stem}")

            if not rec["objects"]:
                problems.append([img_path, xml_path, "empty_annotation", "0 usable objects", "image kept as background/negative"])
            rec["valid"] = True
            records.append(rec)

    with open(os.path.join(out_dir, "invalid_annotations.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["image", "annotation", "problem", "original_value", "action"])
        w.writerows(problems)

    json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
               "records": [{k: (dict(v) if isinstance(v, Counter) else v)
                            for k, v in r.items() if k != "xml"} for r in records]},
              open(os.path.join(out_dir, "_records.json"), "w"))

    return {"records": records, "problems": problems, "classes": classes,
            "class_images": {k: len(v) for k, v in class_images.items()},
            "by_sha": by_sha, "by_dhash": by_dhash}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="datasets/water/IWHR_AI_Lable_Floater_V1/raw")
    ap.add_argument("--packages", nargs="+", default=["package1", "package2"])
    ap.add_argument("--out", default="runs/water/iwhr_integration")
    a = ap.parse_args()
    res = audit(a.root, a.packages, a.out)
    print(f"records={len(res['records'])} problems={len(res['problems'])} classes={dict(res['classes'])}")
