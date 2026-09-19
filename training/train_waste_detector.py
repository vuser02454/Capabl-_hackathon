"""Fine-tune the waste object detector on the converted TACO dataset.

Stage 1 of the waste pipeline: find waste objects and draw boxes. Uses the Ultralytics YOLO
already configured in EcoSentinel (`yolov8n.pt`) as the starting point rather than introducing a
different architecture — the inference path, the model-label derivation and the detector
abstraction all already work with it.

Writes to `runs/waste_detection/` and saves the best weights to `backend/models/waste_detector.pt`. The
existing `backend/models/yolov8n.pt` is never overwritten, so the current EcoSentinel behaviour is
recoverable by pointing `YOLO26_MODEL_PATH` back at it.

**Two of the six classes cannot be learned from this data.** `ewaste` has 2 training boxes and
`food_waste` has 8, and neither appears in validation at all — so their metrics will be zero or
undefined, and that is a fact about the dataset rather than a training failure. The evaluation
report states it rather than hiding it behind a macro average.

    python training/train_waste_detector.py --epochs 40
    python training/train_waste_detector.py --epochs 60 --batch 8 --device cpu
"""

import argparse
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def pick_device(requested: str) -> str:
    """Ultralytics device string. CUDA, then Apple MPS, then CPU."""
    if requested != "auto":
        return requested
    try:
        import torch

        if torch.cuda.is_available():
            return "0"
        if torch.backends.mps.is_available():
            return "mps"
    except ImportError:
        pass
    return "cpu"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="datasets/taco_yolo/data.yaml")
    parser.add_argument("--weights", default="backend/models/yolov8n.pt", help="Pretrained starting point")
    parser.add_argument("--project", default="runs/waste_detection")
    parser.add_argument("--name", default="taco_yolov8n")
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--patience", type=int, default=12, help="Early-stopping patience")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--export", default="backend/models/waste_detector.pt")
    args = parser.parse_args()

    try:
        from ultralytics import YOLO
    except ImportError:
        raise SystemExit("ultralytics is required: pip install ultralytics")

    random.seed(args.seed)
    np.random.seed(args.seed)

    data_path = Path(args.data)
    if not data_path.is_file():
        raise SystemExit(f"Dataset config not found: {data_path}. Run convert_taco_to_yolo.py first.")

    weights = Path(args.weights)
    if not weights.is_file():
        raise SystemExit(f"Pretrained weights not found: {weights}")

    device = pick_device(args.device)

    # Ultralytics keeps a GLOBAL runs_dir in its own settings file, which can point at an
    # unrelated project from an earlier install. Left alone it silently writes this project's
    # weights and plots somewhere else entirely, so pin both paths here.
    from ultralytics import settings as ultralytics_settings

    repo_root = Path(__file__).resolve().parents[1]
    ultralytics_settings.update({
        "runs_dir": str(repo_root / "runs"),
        "datasets_dir": str(repo_root / "datasets"),
    })

    project_dir = Path(args.project)
    if not project_dir.is_absolute():
        project_dir = repo_root / project_dir

    print(f"device={device}  data={data_path}  weights={weights}  epochs={args.epochs}")
    print(f"output -> {project_dir / args.name}")

    model = YOLO(str(weights))
    results = model.train(
        data=str(data_path.resolve()),
        epochs=args.epochs,
        batch=args.batch,
        imgsz=args.imgsz,
        device=device,
        workers=args.workers,
        seed=args.seed,
        patience=args.patience,
        project=str(project_dir),
        name=args.name,
        exist_ok=True,
        pretrained=True,
        # Augmentation kept realistic for litter photography: flips and mild geometry, no vertical
        # flip and no aggressive hue shift — a upside-down bottle is not a scene this model meets.
        fliplr=0.5,
        flipud=0.0,
        degrees=8.0,
        translate=0.1,
        scale=0.4,
        hsv_h=0.015,
        hsv_s=0.5,
        hsv_v=0.3,
        mosaic=1.0,
        plots=True,
    )

    run_dir = Path(results.save_dir)
    best = run_dir / "weights" / "best.pt"
    if best.is_file():
        export = Path(args.export)
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_bytes(best.read_bytes())
        print(f"best weights -> {export}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data": str(data_path),
        "pretrained_from": str(weights),
        "device": device,
        "args": vars(args),
        "run_dir": str(run_dir),
        "exported_to": args.export,
        "note": (
            "ewaste (2 train boxes) and food_waste (8, both with 0 validation boxes) cannot be "
            "learned from this dataset. Their metrics are not evidence of a training problem."
        ),
    }
    (run_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"manifest -> {run_dir / 'training_manifest.json'}")


if __name__ == "__main__":
    main()
