"""False-positive probe and visual evidence for the detector A/B test.

Kept in the same experiment, using the same production pipeline via `analyze_waste(detector=...)`.

On false positives: the project contains **no annotated non-waste image set**. TACO photographs
are litter photographs and `garbage_Dataset` is waste-only, so there is no clean negative corpus
to quote a false-positive rate against. Two things are measured instead, and neither is presented
as more than it is:

  1. Detections matching no annotated object on the TACO test set. This is the only false-positive
     count available against human labels.
  2. What each detector and the full pipeline say about image regions that COCO identifies, at high
     confidence, as ordinary objects — person, mouse, chair, cup, laptop, book, plant. Their
     non-waste identity rests on the COCO model's own label, not on a human annotation, and that
     is a weaker basis which the report states rather than hides.
"""

import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(REPO_ROOT / "training"))

ORDINARY = ["person", "mouse", "chair", "cup", "laptop", "book", "potted plant", "keyboard",
            "cell phone", "tv", "dining table", "couch"]


def find_ordinary_object_regions(limit_per_class: int = 2):
    """Locate regions COCO calls an ordinary object, to probe as non-waste candidates."""
    from ultralytics import YOLO

    model = YOLO(str(REPO_ROOT / "backend/models/yolov8n.pt"))
    found = {}
    counts: Counter = Counter()
    images = sorted((REPO_ROOT / "datasets/taco_yolo/images").glob("*/*.jpg"))
    for image_path in images:
        if len(counts) >= len(ORDINARY) and all(counts[c] >= limit_per_class for c in ORDINARY):
            break
        for box in model.predict(str(image_path), conf=0.45, verbose=False)[0].boxes:
            name = model.names[int(box.cls[0])]
            if name in ORDINARY and counts[name] < limit_per_class:
                counts[name] += 1
                found.setdefault(str(image_path), []).append(
                    {"coco_class": name, "coco_confidence": round(float(box.conf[0]), 3),
                     "bbox": [round(float(v), 1) for v in box.xyxy[0].tolist()]}
                )
    return found, dict(counts)


def probe(found):
    """Run the full production pipeline over those images with each detector."""
    from config import settings
    from services.water_vision_service import LocalYoloDetector
    from services.waste import waste_pipeline

    out = {}
    for model_name, weights in (("coco_yolov8n", "backend/models/yolov8n.pt"),
                                ("taco_waste_detector", "backend/models/waste_detector.pt")):
        detector = LocalYoloDetector(str(REPO_ROOT / weights), settings.yolo_confidence_threshold)
        rows = []
        asserted = withheld = 0
        for image_path, regions in found.items():
            result = waste_pipeline.analyze_waste(
                Path(image_path).read_bytes(), Path(image_path).name, detector=detector
            )
            for region in regions:
                # Does the pipeline assert a waste class over a region COCO calls an ordinary object?
                overlapping = [
                    d for d in result["detections"]
                    if _overlaps(region["bbox"], d["bbox"])
                ]
                for d in overlapping:
                    accepted = d["classification"] is not None
                    asserted += accepted
                    withheld += not accepted
                    rows.append({
                        "image": Path(image_path).name,
                        "coco_says": region["coco_class"],
                        "coco_confidence": region["coco_confidence"],
                        "detector_class": d["detected_object"],
                        "detector_confidence": d["detection_confidence"],
                        "final_class": d["classification"],
                        "final_status": "accepted" if accepted else "needs_review",
                        "message": d.get("message"),
                    })
        out[model_name] = {
            "regions_probed": sum(len(v) for v in found.values()),
            "waste_class_asserted_over_ordinary_object": asserted,
            "correctly_withheld_as_needs_review": withheld,
            "detail": rows,
        }
    return out


def _overlaps(a, b, threshold=0.3):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    ov = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if ov <= 0:
        return False
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ov
    return (ov / ua if ua > 0 else 0) >= threshold


if __name__ == "__main__":
    found, counts = find_ordinary_object_regions()
    print("ordinary-object regions located (by COCO, >=0.45):", counts)
    result = {
        "basis": (
            "No annotated non-waste image set exists in this project. These regions are labelled "
            "by the COCO detector itself at >=0.45 confidence, not by a human, which is a weaker "
            "basis than the TACO ground truth used elsewhere in this report."
        ),
        "regions_per_coco_class": counts,
        "by_detector": probe(found),
    }
    path = REPO_ROOT / "runs/waste_detection/ab_false_positive_probe.json"
    path.write_text(json.dumps(result, indent=2))
    for name, data in result["by_detector"].items():
        print(f"  {name:22} probed {data['regions_probed']} regions -> "
              f"asserted a waste class {data['waste_class_asserted_over_ordinary_object']}, "
              f"withheld {data['correctly_withheld_as_needs_review']}")
    print("wrote", path)
