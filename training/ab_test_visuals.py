"""Save annotated examples for the detector A/B test, from the recorded per-object results.

Every image is a real evaluation image and every number drawn on it comes from `ab_test_report.json`,
which was produced by the production pipeline. Nothing is re-inferred here, so a picture cannot
disagree with the table it illustrates.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

OUT = REPO_ROOT / "runs/waste_detection/ab_test"
GT_COLOR = (250, 204, 21)      # ground truth
DET_COLOR = (45, 212, 191)     # detector
MISS_COLOR = (248, 113, 113)   # nothing found
PER_BUCKET = 6


def font(size=16):
    from PIL import ImageFont
    for path in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def find_image(name: str):
    for split in ("test", "val", "train"):
        candidate = REPO_ROOT / f"datasets/taco_yolo/images/{split}/{name}"
        if candidate.is_file():
            return candidate
    return None


def annotate(entry, gt_box, destination: Path):
    from PIL import Image, ImageDraw

    source = find_image(entry["image"])
    if source is None:
        return False
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    small = font(max(14, image.size[0] // 55))

    if gt_box:
        draw.rectangle(gt_box, outline=GT_COLOR, width=3)
        draw.text((gt_box[0] + 3, max(0, gt_box[1] - 20)), f"GT: {entry['ground_truth']}",
                  fill=GT_COLOR, font=small)

    if entry["detector_bbox"]:
        box = entry["detector_bbox"]
        draw.rectangle(box, outline=DET_COLOR, width=3)
        draw.text((box[0] + 3, min(image.size[1] - 18, box[3] + 3)),
                  f"det: {entry['detector_class']} {entry['detector_confidence']:.2f} "
                  f"IoU {entry['iou']:.2f}", fill=DET_COLOR, font=small)

    lines = [
        f"model: {entry['detector_model']}",
        f"ground truth : {entry['ground_truth']}",
        f"detector     : {entry['detector_class']} "
        + (f"{entry['detector_confidence']:.2f}" if entry['detector_confidence'] else "(none)"),
        f"IoU          : {entry['iou']:.2f}",
        f"classifier   : {entry['classifier_class']} "
        + (f"{entry['classifier_confidence']:.2f}" if entry['classifier_confidence'] else ""),
        f"final        : {entry['final_class']} [{entry['final_status']}]",
        f"outcome      : {entry['outcome']}",
    ]
    pad = 6
    height = len(lines) * (small.size + 3) + pad * 2
    draw.rectangle([0, 0, max(300, image.size[0] // 2), height], fill=(8, 12, 16))
    for index, line in enumerate(lines):
        draw.text((pad, pad + index * (small.size + 3)), line, fill=(235, 235, 235), font=small)

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination)
    return True


def main():
    report = json.loads((REPO_ROOT / "runs/waste_detection/ab_test_report.json").read_text())
    dataset = "taco_test_heldout"      # the held-out split, used for the visual record
    truth_boxes = {}

    # Ground-truth boxes, re-read from the untouched label files purely for drawing.
    from PIL import Image
    for image_path in (REPO_ROOT / "datasets/taco_yolo/images/test").glob("*.jpg"):
        label = Path(str(image_path).replace("/images/", "/labels/")).with_suffix(".txt")
        if not label.is_file():
            continue
        W, H = Image.open(image_path).size
        rows = []
        for line in label.read_text().strip().splitlines():
            if not line.strip():
                continue
            p = line.split()
            cx, cy, bw, bh = (float(v) for v in p[1:5])
            rows.append([(cx - bw / 2) * W, (cy - bh / 2) * H, (cx + bw / 2) * W, (cy + bh / 2) * H])
        truth_boxes[image_path.name] = rows

    written = {}
    for model_key, folder in (("coco_yolov8n", "coco"), ("taco_waste_detector", "taco")):
        objects = report["results"][dataset][model_key]["objects"]
        buckets = {
            f"{folder}/correct": [o for o in objects if o["outcome"] == "E_correct"],
            f"{folder}/missed": [o for o in objects if o["outcome"] == "A_detector_missed"],
            f"pipeline/classifier_wrong": [o for o in objects if o["outcome"] == "C_classifier_wrong"],
            f"pipeline/uncertain": [o for o in objects if o["outcome"] == "D_classifier_uncertain"],
        }
        for bucket, entries in buckets.items():
            count = 0
            for entry in entries[:PER_BUCKET]:
                gt = None
                candidates = truth_boxes.get(entry["image"], [])
                if entry["detector_bbox"]:
                    gt = max(candidates, key=lambda b: _iou(b, entry["detector_bbox"]), default=None)
                elif candidates:
                    gt = candidates[0]
                name = f"{model_key}_{entry['image'].replace('.jpg','')}_{count}.png"
                if annotate(entry, gt, OUT / bucket / name):
                    count += 1
            written[f"{model_key}:{bucket}"] = count

    # The false-positive folders: detections that matched no annotated object.
    for model_key, folder in (("coco_yolov8n", "coco"), ("taco_waste_detector", "taco")):
        target = OUT / folder / "false_positive"
        target.mkdir(parents=True, exist_ok=True)
        (target / "README.txt").write_text(
            "Unmatched-detection counts are in ab_test_report.json under "
            "'detections_matching_no_annotation'. Region-level probes over ordinary objects are in "
            "ab_false_positive_probe.json. No annotated non-waste image set exists in this project, "
            "so no false-positive rate against human labels is claimed beyond those unmatched counts.\n"
        )
    print(json.dumps(written, indent=2))
    print("wrote", OUT)


def _iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    ov = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if ov <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ov
    return ov / ua if ua > 0 else 0.0


if __name__ == "__main__":
    main()
