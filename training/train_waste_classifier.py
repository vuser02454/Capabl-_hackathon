"""Train the waste segregation classifier.

Stage 2 of the waste pipeline: given a crop of one object, say which of the eight waste classes it
is, and therefore whether it is biodegradable. Detection (stage 1) is a separate model — this one
never sees a whole scene.

Two properties of this dataset drive most of the decisions here:

**Cross-split duplicates.** 111 images appear in both train and val. Left alone, validation
measures memorisation and reports a number that looks excellent until the model meets real data.
Duplicates are dropped from TRAIN and kept in val, so the held-out set stays exactly as shipped and
the model simply never sees those images during fitting.

**56:1 class imbalance.** food_waste has 10,066 training images, ewaste has 180. Unweighted, the
fastest way to minimise loss is to predict food_waste and accept being wrong about everything rare.
A weighted sampler balances what the model actually sees per epoch, and metrics are reported
per-class and macro-averaged, because overall accuracy on this distribution is close to meaningless.

    python training/train_waste_classifier.py --epochs 8
    python training/train_waste_classifier.py --epochs 20 --batch-size 64 --device cpu
"""

import argparse
import hashlib
import json
import random
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler
from torchvision import transforms
from torchvision.models import MobileNet_V3_Small_Weights, mobilenet_v3_small

import waste_preprocess

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MIN_DIMENSION = 32


def set_seeds(seed: int) -> None:
    """Make a run reproducible. Reported in the manifest so a result can be re-derived."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device(requested: str) -> torch.device:
    """CUDA, then Apple MPS, then CPU. An explicit request always wins."""
    if requested != "auto":
        return torch.device(requested)
    if torch.cuda.is_available():
        return torch.device("cuda")
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class WasteDataset(Dataset):
    """Images discovered from a `split/**/class/` tree, with the class as the leaf directory."""

    def __init__(self, samples: List[Tuple[Path, int]], classes: List[str], transform):
        self.samples = samples
        self.classes = classes
        self.transform = transform

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, label = self.samples[index]
        # Convert on load: a stray greyscale or RGBA image would otherwise break the batch.
        image = Image.open(path).convert("RGB")
        return self.transform(image), label


def discover(split_dir: Path) -> Dict[str, List[Path]]:
    by_class: Dict[str, List[Path]] = defaultdict(list)
    for path in split_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            by_class[path.parent.name].append(path)
    return dict(by_class)


def usable(path: Path) -> bool:
    """Skip unreadable files, truncated files, and images too small to carry detail.

    The image is fully decoded, not just opened for its header. Reading dimensions alone lets a
    truncated JPEG through — it reports a valid size and then throws during training, which is how
    a run dies twenty minutes in rather than at startup.
    """
    try:
        with Image.open(path) as image:
            width, height = image.size
            image.convert("RGB").load()
        return width >= MIN_DIMENSION and height >= MIN_DIMENSION
    except Exception:  # noqa: BLE001
        return False


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_splits(root: Path) -> Tuple[List[Tuple[Path, int]], List[Tuple[Path, int]], List[str], Dict]:
    """Train/val sample lists with cross-split duplicates removed from TRAIN only."""
    train_by_class = discover(root / "train")
    val_by_class = discover(root / "val")
    classes = sorted(set(train_by_class) | set(val_by_class))
    index = {name: i for i, name in enumerate(classes)}

    # Validation is left exactly as shipped, so the held-out set is not quietly reshaped by
    # whatever the training code decided to drop.
    val_hashes = set()
    val_samples: List[Tuple[Path, int]] = []
    skipped_val = 0
    for name, paths in val_by_class.items():
        for path in paths:
            if not usable(path):
                skipped_val += 1
                continue
            val_samples.append((path, index[name]))
            val_hashes.add(digest(path))

    train_samples: List[Tuple[Path, int]] = []
    leaked = 0
    skipped_train = 0
    for name, paths in train_by_class.items():
        for path in paths:
            if not usable(path):
                skipped_train += 1
                continue
            if digest(path) in val_hashes:
                leaked += 1  # present in val: exclude from training rather than from validation
                continue
            train_samples.append((path, index[name]))

    stats = {
        "train_samples": len(train_samples),
        "val_samples": len(val_samples),
        "excluded_leaked_from_train": leaked,
        "excluded_unusable_train": skipped_train,
        "excluded_unusable_val": skipped_val,
        "train_distribution": dict(Counter(classes[label] for _, label in train_samples)),
        "val_distribution": dict(Counter(classes[label] for _, label in val_samples)),
    }
    return train_samples, val_samples, classes, stats


def transforms_for(image_size: int) -> Tuple[transforms.Compose, transforms.Compose]:
    """Augmentation chosen to stay realistic for waste photography.

    Horizontal flips, modest rotation, mild scale/translation and gentle colour jitter reflect how
    the same object genuinely varies between photos. Vertical flips and aggressive hue shifts are
    deliberately absent: they produce images that do not occur, and a rotated-90 bottle or a
    blue-shifted leaf teaches the model about a world it will never be deployed in.

    The transforms themselves live in `waste_preprocess`, imported by the backend as well. They
    were duplicated once, drifted, and the served model lost half its accuracy on detector crops
    without a single metric moving — see that module for the measurement.
    """
    return waste_preprocess.transforms_for(image_size)


def macro_metrics(confusion: np.ndarray) -> Dict[str, float]:
    """Macro precision/recall/F1. Macro, because a rare class must count as much as a common one."""
    precisions, recalls, f1s = [], [], []
    for i in range(confusion.shape[0]):
        tp = confusion[i, i]
        fp = confusion[:, i].sum() - tp
        fn = confusion[i, :].sum() - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    return {
        "macro_precision": float(np.mean(precisions)),
        "macro_recall": float(np.mean(recalls)),
        "macro_f1": float(np.mean(f1s)),
    }


@torch.no_grad()
def evaluate(model, loader, device, num_classes: int) -> Tuple[float, np.ndarray, float]:
    model.eval()
    confusion = np.zeros((num_classes, num_classes), dtype=np.int64)
    criterion = nn.CrossEntropyLoss()
    loss_total, seen = 0.0, 0
    for images, labels in loader:
        images, labels = images.to(device), labels.to(device)
        logits = model(images)
        loss_total += criterion(logits, labels).item() * labels.size(0)
        seen += labels.size(0)
        for actual, predicted in zip(labels.cpu().numpy(), logits.argmax(1).cpu().numpy()):
            confusion[actual, predicted] += 1
    accuracy = float(np.trace(confusion) / max(1, confusion.sum()))
    return accuracy, confusion, loss_total / max(1, seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="garbage_Dataset")
    parser.add_argument("--out", default="runs/classification")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--image-size", type=int, default=224)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--device", default="auto", help="auto | cuda | mps | cpu")
    parser.add_argument("--seed", type=int, default=1337)
    parser.add_argument("--patience", type=int, default=3, help="Early stopping patience, in epochs")
    parser.add_argument("--limit-per-class", type=int, default=0,
                        help="Cap training images per class (0 = no cap). Useful for a quick run.")
    args = parser.parse_args()

    set_seeds(args.seed)
    device = pick_device(args.device)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    train_samples, val_samples, classes, stats = build_splits(Path(args.dataset))
    if args.limit_per_class:
        capped: List[Tuple[Path, int]] = []
        per_class: Counter = Counter()
        for sample in train_samples:
            if per_class[sample[1]] < args.limit_per_class:
                capped.append(sample)
                per_class[sample[1]] += 1
        train_samples = capped
        stats["train_samples_after_cap"] = len(train_samples)

    print(f"device={device}  classes={len(classes)}  train={len(train_samples)}  val={len(val_samples)}")
    print(f"excluded from train: {stats['excluded_leaked_from_train']} leaked, "
          f"{stats['excluded_unusable_train']} unusable")

    train_tf, eval_tf = transforms_for(args.image_size)
    train_loader = DataLoader(
        WasteDataset(train_samples, classes, train_tf),
        batch_size=args.batch_size,
        # Balanced sampling: without it the fastest way to cut loss is to always answer food_waste.
        sampler=WeightedRandomSampler(
            weights=[1.0 / Counter(l for _, l in train_samples)[label] for _, label in train_samples],
            num_samples=len(train_samples),
            replacement=True,
        ),
        num_workers=args.workers,
        pin_memory=device.type == "cuda",
    )
    val_loader = DataLoader(
        WasteDataset(val_samples, classes, eval_tf),
        batch_size=args.batch_size, shuffle=False, num_workers=args.workers,
    )

    # MobileNetV3-Small: the pipeline runs per detected crop, so a heavy backbone would multiply
    # cost by the number of objects in frame. Pretrained features matter more than capacity here.
    model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.IMAGENET1K_V1)
    model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(classes))
    model = model.to(device)

    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs)
    criterion = nn.CrossEntropyLoss(label_smoothing=0.05)

    history: List[Dict] = []
    best_f1, best_epoch, stale = -1.0, -1, 0
    started = time.time()

    for epoch in range(1, args.epochs + 1):
        model.train()
        running, seen = 0.0, 0
        for images, labels in train_loader:
            images, labels = images.to(device), labels.to(device)
            optimizer.zero_grad()
            loss = criterion(model(images), labels)
            loss.backward()
            optimizer.step()
            running += loss.item() * labels.size(0)
            seen += labels.size(0)
        scheduler.step()

        train_loss = running / max(1, seen)
        accuracy, confusion, val_loss = evaluate(model, val_loader, device, len(classes))
        metrics = macro_metrics(confusion)
        history.append({
            "epoch": epoch, "train_loss": train_loss, "val_loss": val_loss,
            "val_accuracy": accuracy, **metrics,
        })
        print(f"epoch {epoch:>2}/{args.epochs}  train_loss={train_loss:.4f}  val_loss={val_loss:.4f}  "
              f"acc={accuracy:.4f}  macro_f1={metrics['macro_f1']:.4f}")

        # Selected on macro F1, not accuracy: on a 56:1 distribution accuracy rewards ignoring the
        # rare classes, which is the opposite of what this model is for.
        if metrics["macro_f1"] > best_f1:
            best_f1, best_epoch, stale = metrics["macro_f1"], epoch, 0
            torch.save(
                {"state_dict": model.state_dict(), "classes": classes,
                 "image_size": args.image_size, "arch": "mobilenet_v3_small",
                 # Serving checks this against the transform it is about to apply.
                 "preprocess": waste_preprocess.PREPROCESS_VERSION},
                out_dir / "best.pt",
            )
            np.save(out_dir / "best_confusion.npy", confusion)
        else:
            stale += 1
            if stale >= args.patience:
                print(f"early stopping: no macro-F1 improvement for {args.patience} epochs")
                break

    torch.save(
        {"state_dict": model.state_dict(), "classes": classes,
         "image_size": args.image_size, "arch": "mobilenet_v3_small",
         "preprocess": waste_preprocess.PREPROCESS_VERSION},
        out_dir / "last.pt",
    )

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset),
        # Both recorded: the first is the contract serving must honour, the second describes how
        # this particular run was augmented. They move independently.
        "preprocess": waste_preprocess.PREPROCESS_VERSION,
        "augmentation": waste_preprocess.AUGMENTATION_VERSION,
        "classes": classes,
        "device": str(device),
        "args": vars(args),
        "dataset_stats": stats,
        "history": history,
        "best": {"epoch": best_epoch, "macro_f1": best_f1},
        "duration_seconds": round(time.time() - started, 1),
        "versions": {"torch": torch.__version__, "numpy": np.__version__},
    }
    (out_dir / "training_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nbest macro F1 {best_f1:.4f} at epoch {best_epoch}  ->  {out_dir}/best.pt")


if __name__ == "__main__":
    main()
