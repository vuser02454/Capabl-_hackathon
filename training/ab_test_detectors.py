"""A/B test two detector checkpoints through the COMPLETE production Waste Agent pipeline.

The question is not which detector scores better on detector metrics. It is whether swapping the
weights improves the thing the user actually sees, which is the end of a five-stage pipeline where
a detector gain can be cancelled by a classifier that then refuses the crop.

HOW PRODUCTION IS INVOKED
-------------------------
Nothing here re-implements the pipeline. The call path under test is the one the live app uses:

    POST /api/waste/segregate                       backend/main.py:494
      -> validate_image(...)                        backend/main.py
      -> run_in_threadpool(analyze_waste, ...)      backend/main.py:510
         -> services.waste.waste_pipeline.analyze_waste
            -> water_vision_service.build_report(detector, content, filename)   stage 1 detect
            -> _deduplicate(...)                    class-agnostic NMS at 0.7 IoU
            -> _crop(image, bbox, padding=0.06)     stage 2 crop
            -> WasteClassifier.classify(crop)       stage 3 preprocess + classify
               -> waste_preprocess.eval_transform   letterbox_v2
               -> confidence gate at thresholds.classification_confidence
            -> is_never_waste(detector_class)       stage 4 non-waste gate
            -> classifier.segregation_for(class)    stage 5 taxonomy mapping

`analyze_waste` already accepts `detector=`, which is the single injection point this experiment
uses. Everything downstream — dedup, crop padding, letterbox, the 0.60 confidence gate, the
non-waste gate, the taxonomy lookup — is the production code, unmodified and identical for A and B.

`WasteDebugRecorder` is reused as the observer (it is the existing debug mode) so the per-object
intermediates come from the real run rather than from a second implementation.

WHAT IS DELIBERATELY NOT DONE
-----------------------------
Nothing is retrained. No weights file is written. `backend/.env` is not touched, so the served
detector stays `models/yolov8n.pt`; the B model is constructed explicitly, in-process, and never
becomes the configured one. Both models get the same confidence threshold, read from the same
`settings.yolo_confidence_threshold` the API uses, and the same IoU matching threshold.

    python training/ab_test_detectors.py
"""

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

#: The four classes with enough TACO data to train a detector on. `ewaste` (2 train boxes) and
#: `food_waste` (8, both with 0 validation boxes) are excluded from detector evaluation because
#: there is nothing to measure, not because they were inconvenient.
DETECTOR_CLASSES = ["metal_cans", "paper_waste", "plastic_bags", "plastic_bottles"]
ALL_TACO_CLASSES = ["ewaste", "food_waste", "metal_cans", "paper_waste", "plastic_bags", "plastic_bottles"]

#: Ground-truth match threshold, identical for both models.
IOU_MATCH = 0.30


def iou(a: List[float], b: List[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if overlap <= 0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - overlap
    return overlap / union if union > 0 else 0.0


def load_ground_truth(image_paths: List[Path]) -> Dict[str, List[Tuple[str, List[float]]]]:
    """TACO's own human annotations, read from the existing label files. Nothing is created here."""
    from PIL import Image

    truth: Dict[str, List[Tuple[str, List[float]]]] = {}
    for image_path in image_paths:
        label_path = Path(str(image_path).replace("/images/", "/labels/")).with_suffix(".txt")
        if not label_path.is_file():
            continue
        width, height = Image.open(image_path).size
        boxes = []
        for line in label_path.read_text().strip().splitlines():
            if not line.strip():
                continue
            parts = line.split()
            name = ALL_TACO_CLASSES[int(parts[0])]
            cx, cy, bw, bh = (float(v) for v in parts[1:5])
            boxes.append((name, [
                (cx - bw / 2) * width, (cy - bh / 2) * height,
                (cx + bw / 2) * width, (cy + bh / 2) * height,
            ]))
        truth[str(image_path)] = boxes
    return truth


def build_detector(weights: Path):
    """A production `LocalYoloDetector`, with the production confidence threshold.

    Constructed directly rather than through `get_water_vision_detector()`, which reads the
    configured path — the whole point is to vary the weights while changing no configuration.
    """
    from config import settings
    from services.water_vision_service import LocalYoloDetector

    detector = LocalYoloDetector(str(weights), settings.yolo_confidence_threshold)
    if not detector.is_configured():
        raise SystemExit(f"weights not found: {weights}")
    return detector, settings.yolo_confidence_threshold


def run_pipeline(image_path: Path, detector) -> Tuple[List[Dict[str, Any]], int]:
    """One image through the REAL pipeline, observed. Returns per-detection records."""
    from services.waste import waste_pipeline
    from services.waste.waste_debug import WasteDebugRecorder

    recorder = WasteDebugRecorder(image_path.stem, keep_images_in_memory=False)
    content = image_path.read_bytes()
    waste_pipeline.analyze_waste(content, image_path.name, detector=detector, observer=recorder)
    return recorder.records, (len(recorder.vision.detections) if recorder.vision else 0)


def classify_outcome(matched: Optional[Dict[str, Any]], truth_class: str,
                     detector_taxonomy: bool) -> str:
    """Place one ground-truth object into exactly one error bucket.

    The buckets exist so that a detector miss is never reported as a classifier failure. They are
    evaluated in pipeline order, because a later stage cannot be blamed for an object an earlier
    stage never passed on.
    """
    if matched is None:
        return "A_detector_missed"

    final = matched["reported"]["classification"]
    if final == truth_class:
        return "E_correct"
    if final is None:
        # The crop reached the classifier and the pipeline declined to assert an answer. Either
        # the confidence gate or the non-waste gate refused it; both are "uncertain", not "wrong".
        return "D_classifier_uncertain"
    # A detector whose classes ARE waste classes can be wrong about the class while still
    # localising correctly. A COCO detector cannot be scored this way at all — `cup` is neither
    # right nor wrong about `metal_cans`, it is a different vocabulary.
    if detector_taxonomy and matched["detector"]["class"] != truth_class:
        return "B_detector_wrong_class"
    return "C_classifier_wrong"


def evaluate(name: str, weights: Path, truth: Dict[str, List[Tuple[str, List[float]]]],
             detector_taxonomy: bool) -> Dict[str, Any]:
    """Run every image of one dataset through the pipeline with one detector."""
    detector, threshold = build_detector(weights)
    objects: List[Dict[str, Any]] = []
    buckets: Counter = Counter()
    per_class_localised: Counter = Counter()
    per_class_correct: Counter = Counter()
    per_class_total: Counter = Counter()
    unmatched_detections = 0
    total_detections = 0
    raw_detection_count = 0

    for image_path_str, gt_boxes in truth.items():
        image_path = Path(image_path_str)
        records, raw_count = run_pipeline(image_path, detector)
        raw_detection_count += raw_count
        total_detections += len(records)
        used = set()

        for truth_class, truth_box in gt_boxes:
            per_class_total[truth_class] += 1
            best, best_iou = None, 0.0
            for index, record in enumerate(records):
                overlap = iou(truth_box, record["detector"]["bbox"])
                if overlap > best_iou:
                    best, best_iou, best_index = record, overlap, index
            matched = best if best_iou >= IOU_MATCH else None
            if matched is not None:
                used.add(best_index)
                per_class_localised[truth_class] += 1

            outcome = classify_outcome(matched, truth_class, detector_taxonomy)
            buckets[outcome] += 1
            if outcome == "E_correct":
                per_class_correct[truth_class] += 1

            entry = {
                "image": image_path.name,
                "ground_truth": truth_class,
                "detector_model": name,
                "detector_class": matched["detector"]["class"] if matched else None,
                "detector_confidence": matched["detector"]["confidence"] if matched else None,
                "detector_bbox": matched["detector"]["bbox"] if matched else None,
                "iou": round(best_iou, 4) if matched else 0.0,
                "classifier_class": matched["classifier"]["class"] if matched else None,
                "classifier_confidence": matched["classifier"]["confidence"] if matched else None,
                "final_class": matched["reported"]["classification"] if matched else None,
                "final_status": (
                    "no_detection" if matched is None
                    else "accepted" if matched["reported"]["classification"] else "needs_review"
                ),
                "outcome": outcome,
            }
            objects.append(entry)

        # Detections matching no annotated object: the false-positive measure available on data
        # that is actually labelled.
        unmatched_detections += len(records) - len(used)

    total = sum(per_class_total.values())
    localised = sum(per_class_localised.values())

    # --- detector-only class correctness, and the two authority strategies ---
    detector_named = sum(
        1 for o in objects
        if o["detector_class"] is not None and o["detector_class"] == o["ground_truth"]
    )
    strategy_classifier = Counter()
    strategy_detector = Counter()
    agreement = Counter()
    for o in objects:
        if o["detector_class"] is None:
            strategy_classifier["missed"] += 1
            strategy_detector["missed"] += 1
            continue
        # Strategy A: production behaviour — the classifier decides, subject to the gates.
        if o["final_class"] == o["ground_truth"]:
            strategy_classifier["correct"] += 1
        elif o["final_class"] is None:
            strategy_classifier["uncertain"] += 1
        else:
            strategy_classifier["wrong"] += 1
        # Strategy B: the detector's own class is the answer, ungated.
        if detector_taxonomy:
            strategy_detector["correct" if o["detector_class"] == o["ground_truth"] else "wrong"] += 1
        else:
            # A COCO class can never equal a waste class. Counted as not-answerable rather than
            # as wrong, because calling it wrong implies the comparison was meaningful.
            strategy_detector["not_answerable"] += 1

        if detector_taxonomy and o["classifier_class"]:
            if o["detector_class"] == o["classifier_class"]:
                agreement["agree"] += 1
                agreement["agree_correct" if o["detector_class"] == o["ground_truth"] else "agree_wrong"] += 1
            else:
                agreement["disagree"] += 1
                if o["detector_class"] == o["ground_truth"]:
                    agreement["disagree_detector_right"] += 1
                elif o["classifier_class"] == o["ground_truth"]:
                    agreement["disagree_classifier_right"] += 1
                else:
                    agreement["disagree_both_wrong"] += 1

    return {
        "model": name,
        "weights": str(weights.relative_to(REPO_ROOT)),
        "confidence_threshold": threshold,
        "iou_match_threshold": IOU_MATCH,
        "ground_truth_objects": total,
        "localised": localised,
        "localisation_pct": round(100 * localised / total, 1) if total else 0.0,
        "detector_named_correctly": detector_named if detector_taxonomy else None,
        "detector_named_pct": round(100 * detector_named / total, 1) if (total and detector_taxonomy) else None,
        "pipeline_correct": buckets["E_correct"],
        "pipeline_correct_pct": round(100 * buckets["E_correct"] / total, 1) if total else 0.0,
        "error_breakdown": dict(buckets),
        "per_class": {
            c: {
                "ground_truth": per_class_total[c],
                "localised": per_class_localised[c],
                "localised_pct": round(100 * per_class_localised[c] / per_class_total[c], 1) if per_class_total[c] else None,
                "pipeline_correct": per_class_correct[c],
            }
            for c in ALL_TACO_CLASSES if per_class_total[c]
        },
        "raw_detections_before_merge": raw_detection_count,
        "detections_after_merge": total_detections,
        "detections_matching_no_annotation": unmatched_detections,
        "strategy_classifier_authority": dict(strategy_classifier),
        "strategy_detector_authority": dict(strategy_detector),
        "detector_classifier_agreement": dict(agreement) or None,
        "objects": objects,
    }


def benchmark(weights: Path, image_paths: List[Path], warmup: int = 3) -> Dict[str, Any]:
    """Detector latency only. No classifier, no LangGraph, no LLM provider is invoked."""
    from ultralytics import YOLO

    model = YOLO(str(weights))
    sample = [str(p) for p in image_paths[: 30 + warmup]]
    for path in sample[:warmup]:
        model.predict(path, verbose=False)

    speeds = defaultdict(list)
    wall_start = time.perf_counter()
    measured = sample[warmup:]
    for path in measured:
        result = model.predict(path, verbose=False)[0]
        for key, value in result.speed.items():
            speeds[key].append(value)
    wall = time.perf_counter() - wall_start

    mean = {k: round(sum(v) / len(v), 2) for k, v in speeds.items()}
    per_image_ms = sum(mean.values())
    return {
        "weights": str(weights.relative_to(REPO_ROOT)),
        "images_measured": len(measured),
        "warmup_images": warmup,
        "preprocess_ms": mean.get("preprocess"),
        "inference_ms": mean.get("inference"),
        "postprocess_ms": mean.get("postprocess"),
        "total_ms_per_image": round(per_image_ms, 2),
        "approx_fps": round(1000 / per_image_ms, 1) if per_image_ms else None,
        "wall_clock_fps": round(len(measured) / wall, 1) if wall else None,
        "model_size_mb": round(weights.stat().st_size / 1024 / 1024, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coco", default="backend/models/yolov8n.pt")
    parser.add_argument("--taco", default="backend/models/waste_detector.pt")
    parser.add_argument("--out", default="runs/waste_detection")
    parser.add_argument("--realworld-images", type=int, default=80,
                        help="Size of the val subset used as the real-world set, to reproduce the "
                             "existing 80-image / 135-box evaluation exactly.")
    args = parser.parse_args()

    coco_weights = REPO_ROOT / args.coco
    taco_weights = REPO_ROOT / args.taco
    out_dir = REPO_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    test_images = sorted((REPO_ROOT / "datasets/taco_yolo/images/test").glob("*.jpg"))
    val_images = sorted((REPO_ROOT / "datasets/taco_yolo/images/val").glob("*.jpg"))[: args.realworld_images]

    datasets = {
        "taco_test_heldout": load_ground_truth(test_images),
        "taco_val_realworld_80": load_ground_truth(val_images),
    }

    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_call_path": [
            "POST /api/waste/segregate (backend/main.py:494)",
            "services.waste.waste_pipeline.analyze_waste",
            "water_vision_service.build_report -> LocalYoloDetector.detect",
            "_deduplicate (class-agnostic NMS, 0.7 IoU)",
            "_crop (padding 0.06, min 24px)",
            "WasteClassifier.classify -> waste_preprocess.eval_transform (letterbox_v2)",
            "confidence gate (thresholds.classification_confidence)",
            "is_never_waste gate",
            "classifier.segregation_for (taxonomy)",
        ],
        "method_note": (
            "analyze_waste is called with detector= as the only variable. Dedup, crop padding, "
            "preprocessing, the confidence gate, the non-waste gate and the taxonomy mapping are "
            "production code, identical for both models. Nothing was retrained and no weights or "
            "configuration were modified."
        ),
        "datasets": {},
        "results": {},
    }

    for dataset_name, truth in datasets.items():
        counts: Counter = Counter()
        for boxes in truth.values():
            for name, _ in boxes:
                counts[name] += 1
        report["datasets"][dataset_name] = {
            "images": len(truth),
            "ground_truth_objects": sum(counts.values()),
            "objects_per_class": dict(counts),
            "source": "TACO human annotations, read from existing label files; none created here.",
        }

    for dataset_name, truth in datasets.items():
        report["results"][dataset_name] = {}
        for model_name, weights, taxonomy in (
            ("coco_yolov8n", coco_weights, False),
            ("taco_waste_detector", taco_weights, True),
        ):
            print(f"  running {model_name} on {dataset_name} ...", flush=True)
            report["results"][dataset_name][model_name] = evaluate(
                model_name, weights, truth, detector_taxonomy=taxonomy
            )

    print("  benchmarking ...", flush=True)
    report["performance"] = {
        "coco_yolov8n": benchmark(coco_weights, test_images),
        "taco_waste_detector": benchmark(taco_weights, test_images),
        "note": "Detector only. The classifier, LangGraph and every LLM provider are not invoked.",
    }

    path = out_dir / "ab_test_report.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {path}")
    return report


if __name__ == "__main__":
    main()
