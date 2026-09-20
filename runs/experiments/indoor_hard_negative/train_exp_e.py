import json
import random
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import torch
from ultralytics import YOLO, settings as ultralytics_settings

def main():
    repo_root = Path(__file__).resolve().parents[3]
    ultralytics_settings.update({
        "runs_dir": str(repo_root / "runs"),
        "datasets_dir": str(repo_root / "datasets"),
    })

    seed = 1337
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    data_yaml = repo_root / "runs/experiments/indoor_hard_negative/dataset/data.yaml"
    weights = repo_root / "backend/models/yolov8n.pt"
    project_dir = repo_root / "runs/experiments/indoor_hard_negative"
    name = "exp_e_yolov8n"

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"Starting Experiment E Training: device={device}, data={data_yaml}, base={weights}")

    model = YOLO(str(weights))
    results = model.train(
        data=str(data_yaml),
        epochs=40,
        batch=16,
        imgsz=640,
        device=device,
        workers=4,
        seed=seed,
        patience=12,
        project=str(project_dir),
        name=name,
        exist_ok=True,
        pretrained=True,
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
    last = run_dir / "weights" / "last.pt"

    ckpt_dir = project_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    if best.is_file():
        import shutil
        shutil.copy2(best, ckpt_dir / "best_exp_e.pt")
        print(f"Saved best checkpoint to {ckpt_dir / 'best_exp_e.pt'}")
    if last.is_file():
        import shutil
        shutil.copy2(last, ckpt_dir / "last_exp_e.pt")
        print(f"Saved last checkpoint to {ckpt_dir / 'last_exp_e.pt'}")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "purpose": "EXPERIMENT E - Indoor Hard-Negative Detector Experiment",
        "data_yaml": str(data_yaml),
        "pretrained_base": str(weights),
        "device": device,
        "seed": seed,
        "epochs": 40,
        "patience": 12,
        "batch": 16,
        "imgsz": 640,
        "run_dir": str(run_dir),
        "best_checkpoint": str(best),
        "saved_checkpoints": [
            str(ckpt_dir / "best_exp_e.pt"),
            str(ckpt_dir / "last_exp_e.pt")
        ],
        "metrics_summary": {
            "mAP50": float(results.box.map50) if hasattr(results, 'box') else None,
            "mAP50_95": float(results.box.map) if hasattr(results, 'box') else None,
            "precision": float(results.box.p.mean()) if hasattr(results, 'box') and hasattr(results.box, 'p') else None,
            "recall": float(results.box.r.mean()) if hasattr(results, 'box') and hasattr(results.box, 'r') else None,
        }
    }
    with open(project_dir / "training_manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)
    print("Training manifest written successfully!")

if __name__ == "__main__":
    main()
