"""Evaluate the trained waste classifier on the held-out validation split.

Reports per-class precision, recall and F1 alongside the confusion matrix, because a single
accuracy figure on a 56:1 distribution is close to meaningless — a model that answered
"food_waste" for everything would score around 19% accuracy here while being useless, and one that
gets the common classes right can look excellent while never once recognising e-waste.

Writes a JSON report and, when matplotlib is available, training-curve and confusion-matrix plots.

    python training/evaluate_classifier.py --weights runs/classification/best.pt
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from torchvision.models import mobilenet_v3_small

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train_waste_classifier import (  # noqa: E402
    WasteDataset, build_splits, pick_device, transforms_for,
)


def per_class_report(confusion: np.ndarray, classes: List[str]) -> Dict[str, Dict[str, float]]:
    """Precision / recall / F1 / support for every class, computed from the confusion matrix."""
    report: Dict[str, Dict[str, float]] = {}
    for i, name in enumerate(classes):
        tp = int(confusion[i, i])
        fp = int(confusion[:, i].sum() - tp)
        fn = int(confusion[i, :].sum() - tp)
        support = int(confusion[i, :].sum())
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        report[name] = {
            "precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "support": support,
        }
    return report


def plot_confusion(confusion: np.ndarray, classes: List[str], out_path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    # Row-normalised: raw counts on a 56:1 distribution show one bright cell and nothing else.
    normalised = confusion.astype(float) / np.maximum(1, confusion.sum(axis=1, keepdims=True))
    fig, ax = plt.subplots(figsize=(8, 7))
    image = ax.imshow(normalised, cmap="viridis", vmin=0, vmax=1)
    ax.set_xticks(range(len(classes)), classes, rotation=45, ha="right")
    ax.set_yticks(range(len(classes)), classes)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Actual")
    ax.set_title("Waste classifier - confusion matrix (row-normalised)")
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, f"{normalised[i, j]:.2f}", ha="center", va="center",
                    color="white" if normalised[i, j] < 0.6 else "black", fontsize=8)
    fig.colorbar(image, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return True


def plot_history(history: List[Dict], out_path: Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    epochs = [h["epoch"] for h in history]
    fig, (left, right) = plt.subplots(1, 2, figsize=(11, 4))
    left.plot(epochs, [h["train_loss"] for h in history], label="train loss")
    left.plot(epochs, [h["val_loss"] for h in history], label="val loss")
    left.set_xlabel("epoch"); left.set_ylabel("loss"); left.legend(); left.set_title("Loss")
    right.plot(epochs, [h["val_accuracy"] for h in history], label="accuracy")
    right.plot(epochs, [h["macro_f1"] for h in history], label="macro F1")
    right.plot(epochs, [h["macro_recall"] for h in history], label="macro recall")
    right.set_xlabel("epoch"); right.set_ylim(0, 1); right.legend(); right.set_title("Validation")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="garbage_Dataset")
    parser.add_argument("--weights", default="runs/classification/best.pt")
    parser.add_argument("--out", default="runs/evaluation")
    parser.add_argument("--batch-size", type=int, default=48)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    weights_path = Path(args.weights)
    if not weights_path.is_file():
        raise SystemExit(f"No trained weights at {weights_path}. Train first.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    device = pick_device(args.device)

    checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
    classes = checkpoint["classes"]
    image_size = int(checkpoint.get("image_size", 224))

    model = mobilenet_v3_small()
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model = model.to(device).eval()

    _train, val_samples, discovered, stats = build_splits(Path(args.dataset))
    if discovered != classes:
        print(f"WARNING: dataset classes {discovered} differ from checkpoint classes {classes}")
    _train_tf, eval_tf = transforms_for(image_size)
    loader = DataLoader(
        WasteDataset(val_samples, classes, eval_tf),
        batch_size=args.batch_size, shuffle=False, num_workers=args.workers,
    )

    confusion = np.zeros((len(classes), len(classes)), dtype=np.int64)
    confidences: List[float] = []
    with torch.no_grad():
        for images, labels in loader:
            probabilities = torch.softmax(model(images.to(device)), dim=1)
            predictions = probabilities.argmax(1).cpu().numpy()
            confidences.extend(probabilities.max(1).values.cpu().numpy().tolist())
            for actual, predicted in zip(labels.numpy(), predictions):
                confusion[actual, predicted] += 1

    accuracy = float(np.trace(confusion) / max(1, confusion.sum()))
    by_class = per_class_report(confusion, classes)
    macro = {
        "macro_precision": round(float(np.mean([m["precision"] for m in by_class.values()])), 4),
        "macro_recall": round(float(np.mean([m["recall"] for m in by_class.values()])), 4),
        "macro_f1": round(float(np.mean([m["f1"] for m in by_class.values()])), 4),
    }

    manifest_path = weights_path.parent / "training_manifest.json"
    history = json.loads(manifest_path.read_text())["history"] if manifest_path.is_file() else []

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weights": str(weights_path),
        "dataset": str(args.dataset),
        "device": str(device),
        "classes": classes,
        "validation_images": int(confusion.sum()),
        "accuracy": round(accuracy, 4),
        **macro,
        "per_class": by_class,
        "confusion_matrix": confusion.tolist(),
        "mean_confidence": round(float(np.mean(confidences)), 4) if confidences else None,
        "dataset_stats": stats,
        "note": (
            "Accuracy alone is misleading on this distribution. Macro F1 and the per-class recall "
            "below are what show whether the rare classes are recognised at all."
        ),
    }
    (out_dir / "classification_report.json").write_text(json.dumps(report, indent=2))
    np.save(out_dir / "confusion_matrix.npy", confusion)

    plots = []
    if plot_confusion(confusion, classes, out_dir / "confusion_matrix.png"):
        plots.append("confusion_matrix.png")
    if history and plot_history(history, out_dir / "training_curves.png"):
        plots.append("training_curves.png")

    print(f"Validation images : {int(confusion.sum())}")
    print(f"Accuracy          : {accuracy:.4f}")
    print(f"Macro precision   : {macro['macro_precision']:.4f}")
    print(f"Macro recall      : {macro['macro_recall']:.4f}")
    print(f"Macro F1          : {macro['macro_f1']:.4f}")
    print("\nPer class:")
    print(f"  {'class':<18}{'precision':>10}{'recall':>9}{'f1':>8}{'support':>9}")
    for name, metrics in by_class.items():
        print(f"  {name:<18}{metrics['precision']:>10.3f}{metrics['recall']:>9.3f}"
              f"{metrics['f1']:>8.3f}{metrics['support']:>9}")
    print(f"\nReport -> {out_dir}/classification_report.json")
    if plots:
        print(f"Plots  -> {', '.join(plots)}")
    else:
        print("Plots  -> skipped (matplotlib not available)")


if __name__ == "__main__":
    main()
