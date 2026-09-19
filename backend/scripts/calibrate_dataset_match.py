"""Measure how well reference-dataset matching actually generalises, and pick a threshold.

    python scripts/calibrate_dataset_match.py [--samples 400] [--negatives path ...]

Why leave-one-SEQUENCE-out: the dataset is video frames, so neighbouring frames of the same clip
are nearly identical. Scoring a frame against its own clip measures nothing useful — it only shows
that a video frame resembles the next video frame. Every query here therefore excludes ALL frames
from its own source sequence (the "S15-4" prefix), which is the honest stand-in for "a photo of
water this model has never seen".

The numbers it prints are the basis for ECOSENTINEL_WATER_DATASET_MATCH_THRESHOLD.
"""

import argparse
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from config import settings  # noqa: E402
from services.water_dataset_match_service import (  # noqa: E402
    REGIONS,
    _features_and_hash,
    get_dataset_matcher,
)

SEQUENCE = re.compile(r"^([^/]+)/([^_]+)_frame_")
CONTAMINATED = {"Alta", "Media"}


def sequence_of(relative: str) -> str:
    match = SEQUENCE.match(relative)
    return f"{match.group(1)}/{match.group(2)}" if match else relative


def percentiles(values, points=(1, 5, 25, 50, 75, 95, 99)):
    array = np.asarray(values, dtype=np.float64)
    return {point: float(np.percentile(array, point)) for point in points}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=400, help="query frames to evaluate")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--negatives", nargs="*", default=[], help="non-dataset images that must NOT match")
    parser.add_argument("--bands", action="store_true", help="break accuracy down by similarity band")
    args = parser.parse_args()

    matcher = get_dataset_matcher()
    if matcher.ensure_ready() == "indexing":
        print("Index is still building — run scripts/build_dataset_index.py first.", file=sys.stderr)
        return 1
    state = matcher._state
    if state is None:
        print("No index available.", file=sys.stderr)
        return 1

    features = state.features
    files = state.files
    labels = state.labels
    sequences = np.array([sequence_of(f) for f in files])
    top_k = settings.water_dataset_top_k

    print(f"Index: {len(files)} frames, {len(set(sequences))} source sequences")
    print("Classes (frames / independent source clips):")
    for class_name in sorted(set(labels)):
        frames = sum(1 for lab in labels if lab == class_name)
        clips = len({sequences[i] for i, lab in enumerate(labels) if lab == class_name})
        print(f"  {class_name:<8} {frames:>5} frames   {clips:>3} clips")
    print(f"k = {top_k}, similarity = mean per-region histogram intersection\n")

    random.seed(args.seed)
    sample_indices = random.sample(range(len(files)), min(args.samples, len(files)))

    correct = 0
    banded = []  # (best similarity, actual class, predicted class)
    flag_correct = 0  # HIGH/MODERATE vs LOW, the decision that actually raises a flag
    best_similarities = []
    per_class = defaultdict(lambda: [0, 0])
    confusion = Counter()

    for index in sample_indices:
        query = features[index]
        mask = sequences != sequences[index]  # leave-one-sequence-out
        candidates = np.flatnonzero(mask)
        similarities = np.minimum(features[candidates], query).sum(axis=1) / REGIONS
        order = candidates[np.argsort(-similarities)[:top_k]]

        votes = defaultdict(float)
        for position in order:
            votes[labels[position]] += float(
                np.minimum(features[position], query).sum() / REGIONS
            )
        predicted = max(votes.items(), key=lambda item: item[1])[0]
        actual = labels[index]
        best = float(similarities.max())
        best_similarities.append(best)

        per_class[actual][1] += 1
        if predicted == actual:
            correct += 1
            per_class[actual][0] += 1
        confusion[(actual, predicted)] += 1
        banded.append((best, actual, predicted))
        contaminated_actual = actual in {"Alta", "Media"}
        contaminated_predicted = predicted in {"Alta", "Media"}
        if contaminated_actual == contaminated_predicted:
            flag_correct += 1

    total = len(sample_indices)
    print(f"Leave-one-sequence-out over {total} query frames")
    print(f"  exact class accuracy      : {correct / total:.1%}")
    print(f"  contaminated-or-not accuracy: {flag_correct / total:.1%}")
    for class_name, (hits, count) in sorted(per_class.items()):
        print(f"    {class_name:<8} {hits}/{count} = {hits / count:.1%}")
    print("\n  confusion (actual -> predicted):")
    for (actual, predicted), count in sorted(confusion.items(), key=lambda kv: -kv[1]):
        print(f"    {actual:<8} -> {predicted:<8} {count}")

    print("\nBest-match similarity for genuine unseen-sequence water frames:")
    for point, value in percentiles(best_similarities).items():
        print(f"  p{point:<3} {value:.3f}")

    if args.negatives:
        print("\nNon-dataset images (these should sit clearly lower):")
        negative_best = []
        for path in args.negatives:
            try:
                with Image.open(path) as image:
                    feature, _ = _features_and_hash(image)
            except Exception as exc:
                print(f"  {Path(path).name:<40} unreadable: {exc}")
                continue
            similarities = np.minimum(features, feature).sum(axis=1) / REGIONS
            best = float(similarities.max())
            negative_best.append(best)
            winner = labels[int(np.argmax(similarities))]
            print(f"  {Path(path).name:<40} best {best:.3f} ({winner})")
        if negative_best:
            print(f"  max over negatives: {max(negative_best):.3f}")

    if args.bands:
        # The decisive table: does a HIGHER similarity buy a more trustworthy flag? On the shipped
        # dataset it does not, which is why the flag is worded as a resemblance, not a verdict.
        print("\nAccuracy by best-similarity band:")
        print(f"  {'band':<14}{'n':>6}{'exact':>8}{'flag ok':>9}{'clean called dirty':>21}{'clean n':>9}")
        edges = [(0.0, 0.62), (0.62, 0.90), (0.90, 0.96), (0.96, 0.98), (0.98, 0.99), (0.99, 1.01)]
        for low, high in edges:
            rows = [r for r in banded if low <= r[0] < high]
            if not rows:
                continue
            exact = sum(1 for r in rows if r[1] == r[2]) / len(rows)
            flag_ok = sum(
                1 for r in rows if (r[1] in CONTAMINATED) == (r[2] in CONTAMINATED)
            ) / len(rows)
            clean = [r for r in rows if r[1] not in CONTAMINATED]
            false_positive = (
                sum(1 for r in clean if r[2] in CONTAMINATED) / len(clean) if clean else float("nan")
            )
            print(
                f"  {low:.2f}-{high:<9.2f}{len(rows):>6}{exact:>8.0%}{flag_ok:>9.0%}"
                f"{false_positive:>21.0%}{len(clean):>9}"
            )

    print(f"\nConfigured threshold: {settings.water_dataset_match_threshold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
