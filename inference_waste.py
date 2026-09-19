"""Two-stage waste inference over an image, a video, or a webcam.

    python inference_waste.py --source test.jpg
    python inference_waste.py --source pollution_video.mp4 --out runs/inference
    python inference_waste.py --source 0                      # webcam, if one is available

Each detected object is cropped and classified, and the overlay shows both stages separately:

    Plastic Bottle
    Detection: 91%
    Classification: 96%
    Category: Non-Biodegradable

Keeping the two confidences visible matters. A confident detection of an object the classifier is
unsure about is a completely different situation from both being confident, and a single merged
number would hide which stage to distrust. Anything below the configured classification threshold
renders as UNCERTAIN rather than as its best guess.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from services.waste.waste_pipeline import analyze_waste, pipeline_status  # noqa: E402

SEGREGATION_COLOR = {
    "biodegradable": (80, 200, 120),      # green
    "non_biodegradable": (80, 140, 255),  # orange-red in BGR
    "uncertain": (150, 150, 150),         # grey - deliberately unremarkable
}


def annotate(frame, result: Dict[str, Any]):
    """Draw boxes and both confidences. Returns the frame unchanged if OpenCV is missing."""
    try:
        import cv2
    except ImportError:
        return frame

    for detection in result.get("detections", []):
        x1, y1, x2, y2 = (int(v) for v in detection["bbox"])
        segregation = detection.get("segregation", "uncertain")
        color = SEGREGATION_COLOR.get(segregation, SEGREGATION_COLOR["uncertain"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)

        label = detection.get("display") or detection["detected_object"].replace("_", " ").title()
        lines = [label, f"Detection: {detection['detection_confidence']:.0%}"]
        confidence = detection.get("classification_confidence")
        if detection.get("classification"):
            lines.append(f"Classification: {confidence:.0%}")
            lines.append(f"Category: {segregation.replace('_', '-').title()}")
        else:
            # Never show a category the classifier did not commit to.
            lines.append(f"Classification: {'%.0f%%' % (confidence * 100) if confidence else 'n/a'}")
            lines.append("Category: UNCERTAIN")

        y = max(14, y1 - 6 - 14 * (len(lines) - 1))
        for line in lines:
            cv2.putText(frame, line, (x1, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            y += 14
    return frame


def run_image(path: Path, out_dir: Path) -> Dict[str, Any]:
    result = analyze_waste(path.read_bytes(), path.name)
    print(f"\n{path.name}: status={result['status']}  objects={result['summary']['total_objects']}")
    if result.get("message"):
        print(f"  note: {result['message']}")
    for detection in result["detections"]:
        classification = detection.get("classification") or f"uncertain ({detection.get('status')})"
        print(f"  {detection['id']}  {detection['detected_object']:<14} "
              f"det={detection['detection_confidence']:.0%}  -> {classification}"
              f"  [{detection.get('segregation')}]")
    print(f"  summary: {result['summary']}")

    try:
        import cv2
        import numpy as np

        frame = cv2.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            out_dir.mkdir(parents=True, exist_ok=True)
            target = out_dir / f"{path.stem}_annotated.jpg"
            cv2.imwrite(str(target), annotate(frame, result))
            print(f"  annotated -> {target}")
    except ImportError:
        print("  (OpenCV not installed; no annotated image written)")
    return result


def run_video(source: str, out_dir: Path, stride: int, max_frames: int) -> List[Dict[str, Any]]:
    """Sample every `stride`-th frame. Running both stages on every frame is pointless work."""
    try:
        import cv2
    except ImportError:
        raise SystemExit("OpenCV is required for video inference: pip install opencv-python")

    capture = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not capture.isOpened():
        raise SystemExit(f"Could not open video source: {source}")

    out_dir.mkdir(parents=True, exist_ok=True)
    writer = None
    results: List[Dict[str, Any]] = []
    index, processed = 0, 0

    while True:
        ok, frame = capture.read()
        if not ok or (max_frames and processed >= max_frames):
            break
        if index % stride == 0:
            ok_encode, buffer = cv2.imencode(".jpg", frame)
            if ok_encode:
                result = analyze_waste(buffer.tobytes(), f"frame_{index}.jpg")
                result["frame"] = index
                results.append(result)
                frame = annotate(frame, result)
                processed += 1
                print(f"  frame {index:>5}: {result['summary']}")
        if writer is None:
            height, width = frame.shape[:2]
            writer = cv2.VideoWriter(
                str(out_dir / "annotated.mp4"), cv2.VideoWriter_fourcc(*"mp4v"), 15, (width, height)
            )
        writer.write(frame)
        index += 1

    capture.release()
    if writer is not None:
        writer.release()
        print(f"  annotated video -> {out_dir / 'annotated.mp4'}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Image, video, directory, or webcam index")
    parser.add_argument("--out", default="runs/inference")
    parser.add_argument("--stride", type=int, default=15, help="Process every Nth video frame")
    parser.add_argument("--max-frames", type=int, default=40, help="0 = no limit")
    parser.add_argument("--status", action="store_true", help="Print pipeline status and exit")
    args = parser.parse_args()

    if args.status:
        print(json.dumps(pipeline_status(), indent=2))
        return
    if not args.source:
        raise SystemExit("--source is required (or use --status)")

    out_dir = Path(args.out)
    status = pipeline_status()
    print(f"detector  : {status['detector'].get('model')} (available={status['detector'].get('available')})")
    print(f"classifier: {len(status['classifier'].get('classes') or [])} classes "
          f"(available={status['classifier'].get('available')})")
    if not status["classifier"].get("available"):
        # Said once, up front: every result below will be uncertain, and that is a missing model
        # rather than an image with nothing in it.
        print(f"  note: {status['classifier'].get('detail')}")

    source = Path(args.source)
    results: List[Dict[str, Any]] = []

    if args.source.isdigit() or (source.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv"}):
        results = run_video(args.source, out_dir, args.stride, args.max_frames)
    elif source.is_dir():
        for image_path in sorted(p for p in source.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}):
            results.append(run_image(image_path, out_dir))
    elif source.is_file():
        results.append(run_image(source, out_dir))
    else:
        raise SystemExit(f"Source not found: {source}")

    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": args.source,
        "pipeline_status": status,
        "results": results,
    }
    (out_dir / "inference_results.json").write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nResults -> {out_dir / 'inference_results.json'}")


if __name__ == "__main__":
    main()
