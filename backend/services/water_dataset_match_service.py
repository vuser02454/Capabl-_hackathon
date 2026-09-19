"""Appearance matching of a water photo against the labelled reference dataset.

Scope
-----
This service answers one question: *which labelled reference frames does this photo look like?*
It compares colour distribution, not chemistry. A confident match to a highly-contaminated class
is CORROBORATING VISUAL EVIDENCE that an area looks contaminated — it is not a measurement of pH,
turbidity, dissolved oxygen or any chemical parameter, and this module never writes one.

Dataset layout (ECOSENTINEL_WATER_DATASET_IMAGES_PATH, default <repo>/datasets)

    datasets/<ClassName>/*.jpg

Folder names are the class labels. The shipped dataset uses the Spanish contamination levels
Alta / Media / Baja, mapped to HIGH / MODERATE / LOW by CLASS_LEVELS below. A folder whose name is
not in that map is still indexed and can still be matched, but it never raises a contamination
flag, because this module has no way to know what an unknown label means.

Method
------
Two tiers, both reported separately so a caller can tell them apart:

  similarity  A spatial HSV colour histogram (2x2 regions x 8H*3S*3V bins) compared by histogram
              intersection, which is bounded to 0..1 and needs no calibration to be readable.
              The k nearest frames vote for a class, weighted by similarity.
  duplicate   A 64-bit difference hash. A small Hamming distance means the photo is essentially
              the SAME frame as one already in the dataset — useful to spot a replayed sample,
              and reported as such rather than dressed up as a new observation.

Below `water_dataset_match_threshold` the answer is "no confident match" and nothing is flagged.
An uncertain match is reported as uncertain; it is never rounded up into a flag.

MEASURED RELIABILITY — read before trusting the flag
----------------------------------------------------
Reproduce with: python scripts/calibrate_dataset_match.py --samples 900 --bands

On the shipped dataset, evaluated leave-one-SEQUENCE-out (a query never sees its own video clip):

    exact class accuracy          ~71%
    contaminated-or-not accuracy  ~84%
    recall on Alta (high)         ~91%
    recall on Baja (clean)        ~15-33%

That last number is the one that matters. Between 50% and 100% of genuinely CLEAN water frames are
matched to a contaminated class, and this does NOT improve at higher similarity — it is roughly as
bad in the 0.99+ band as at 0.7. The cause is in the dataset, not the threshold: only 4 of the 29
source clips are clean water (861 frames from 4 scenes, against 25 contaminated clips), and a colour
histogram keys on scene appearance — lighting, bank, vegetation, framing — far more than on turbidity.
A clean-water photo from an unseen scene therefore lands nearest whichever contaminated clip it
happens to resemble.

Consequences encoded below, deliberately:
  * `contaminated` means "resembles reference frames labelled contaminated", never "this water is
    contaminated". Every ok/no_match result carries `caveat` saying so, and callers must surface it.
  * The near-duplicate tier is the only part of this that is reliable, and is reported separately.
  * Nothing here may raise risk scores or auto-submit a report. A human confirms before anything
    leaves the machine.

Fixing this properly needs more clean-water source clips, or a model trained on turbidity rather
than appearance — not a different threshold.

Dependencies
------------
Pillow and numpy. Both are imported lazily, so a missing package degrades to an "unavailable"
report instead of breaking import of the Water Agent — the same contract as the vision service.
"""

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from config import settings
from schemas import DatasetNeighbour, WaterDatasetMatch

# --- feature geometry -------------------------------------------------------------------
THUMB = 96          # every image is resized to this square before histogramming
GRID = 2            # 2x2 spatial regions, so layout (sky vs water) is not thrown away
H_BINS, S_BINS, V_BINS = 8, 3, 3
REGION_BINS = H_BINS * S_BINS * V_BINS          # 72
FEATURE_BINS = GRID * GRID * REGION_BINS        # 288
REGIONS = GRID * GRID

INDEX_VERSION = 2
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Folder name (lowercased) -> (human label, risk level). Unmapped folders never raise a flag.
CLASS_LEVELS: Dict[str, Tuple[str, str]] = {
    "alta": ("High contamination", "HIGH"),
    "media": ("Moderate contamination", "MODERATE"),
    "baja": ("Low contamination", "LOW"),
    "high": ("High contamination", "HIGH"),
    "moderate": ("Moderate contamination", "MODERATE"),
    "medium": ("Moderate contamination", "MODERATE"),
    "low": ("Low contamination", "LOW"),
    "clean": ("Low contamination", "LOW"),
}


#: Attached to every ok/no_match result. See the module docstring for where these numbers come from.
RELIABILITY_CAVEAT = (
    "Appearance match only. Measured leave-one-clip-out on this dataset, it recognises visibly "
    "contaminated water well (~91% on the high class) but misreads clean water as contaminated "
    "most of the time, because only 4 of 29 reference clips are clean. Treat a flag as a prompt to "
    "look, never as a verdict, and never as a substitute for the sensor readings."
)


class MatchUnavailable(Exception):
    """Raised inside the matcher when it cannot run. Never escapes to the Water Agent."""

    def __init__(self, message: str, status: str = "unavailable"):
        super().__init__(message)
        self.message = message
        self.status = status


def _imports():
    """Import Pillow and numpy on first use, converting absence into MatchUnavailable."""
    try:
        import numpy as np  # noqa: WPS433
        from PIL import Image  # noqa: WPS433
    except ImportError as exc:  # pragma: no cover - depends on deployment
        raise MatchUnavailable(
            "Dataset matching needs Pillow and numpy. Install them with: pip install pillow numpy",
            status="unavailable",
        ) from exc
    return np, Image


def class_meta(class_name: str) -> Tuple[str, Optional[str]]:
    """(human label, risk level) for a dataset folder name. Level is None when unmapped."""
    label, level = CLASS_LEVELS.get(class_name.strip().lower(), (class_name, None))
    return label, level


@dataclass
class IndexState:
    """What the matcher currently holds. `features` is (n, FEATURE_BINS) float32."""

    features: object = None
    hashes: object = None
    files: List[str] = None
    labels: List[str] = None
    built_at: Optional[datetime] = None
    counts: Dict[str, int] = None


# --------------------------------------------------------------------------- features


def _features_and_hash(image) -> Tuple[object, int]:
    """Spatial HSV histogram (L1-normalised per region) plus a 64-bit difference hash."""
    np, Image = _imports()

    rgb = image.convert("RGB")
    hsv = np.asarray(rgb.convert("HSV").resize((THUMB, THUMB), Image.BILINEAR), dtype=np.int32)
    h = hsv[..., 0] * H_BINS // 256
    s = hsv[..., 1] * S_BINS // 256
    v = hsv[..., 2] * V_BINS // 256
    binned = (h * S_BINS + s) * V_BINS + v

    half = THUMB // GRID
    regions = []
    for row in range(GRID):
        for col in range(GRID):
            block = binned[row * half : (row + 1) * half, col * half : (col + 1) * half].ravel()
            counts = np.bincount(block, minlength=REGION_BINS).astype(np.float32)
            total = counts.sum()
            regions.append(counts / total if total else counts)
    feature = np.concatenate(regions)

    grey = np.asarray(rgb.convert("L").resize((9, 8), Image.BILINEAR), dtype=np.int16)
    bits = (grey[:, 1:] > grey[:, :-1]).ravel()
    digest = 0
    for bit in bits:
        digest = (digest << 1) | int(bit)
    return feature, digest


def _open(content: bytes):
    np, Image = _imports()
    import io

    try:
        image = Image.open(io.BytesIO(content))
        image.load()
    except Exception as exc:  # Pillow raises a wide variety of decode errors
        raise MatchUnavailable(f"The image could not be decoded: {exc}", status="unavailable")
    return image


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# --------------------------------------------------------------------------- the matcher


class DatasetMatcher:
    """Builds (once) and queries the reference index. Safe to share across requests."""

    def __init__(self, images_path: Path, index_path: Path):
        self.images_path = images_path
        self.index_path = index_path
        self._state: Optional[IndexState] = None
        self._lock = threading.Lock()
        self._build_thread: Optional[threading.Thread] = None
        self._progress: Tuple[int, int] = (0, 0)
        self._error: Optional[str] = None

    # -- lifecycle ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return settings.water_dataset_matching_enabled

    def _load_cached(self) -> bool:
        np, _ = _imports()
        if not self.index_path.exists():
            return False
        try:
            with np.load(self.index_path, allow_pickle=False) as data:
                meta = json.loads(str(data["meta"]))
                if int(meta.get("version", 0)) != INDEX_VERSION:
                    return False
                features = data["features"].astype(np.float32)
                hashes = [int(x) for x in data["hashes"]]
                files = [str(x) for x in data["files"]]
                labels = [str(x) for x in data["labels"]]
        except Exception:
            return False  # a corrupt or half-written cache is rebuilt, not trusted
        if features.shape[0] != len(files) or features.shape[1] != FEATURE_BINS:
            return False
        self._state = IndexState(
            features=features,
            hashes=hashes,
            files=files,
            labels=labels,
            built_at=datetime.fromisoformat(meta["builtAt"]),
            counts=meta.get("counts", {}),
        )
        return True

    def _image_paths(self) -> List[Tuple[str, str, Path]]:
        """[(relative path, class name, absolute path)] for every indexable image."""
        found: List[Tuple[str, str, Path]] = []
        if not self.images_path.is_dir():
            return found
        for class_dir in sorted(p for p in self.images_path.iterdir() if p.is_dir()):
            for image in sorted(class_dir.iterdir()):
                if image.suffix.lower() in IMAGE_SUFFIXES:
                    found.append((f"{class_dir.name}/{image.name}", class_dir.name, image))
        return found

    def build(self) -> None:
        """Index every dataset image. Slow (thousands of JPEG decodes) — run off the request path."""
        np, Image = _imports()
        entries = self._image_paths()
        if not entries:
            raise MatchUnavailable(
                f"No reference images found under {self.images_path}. Set "
                "ECOSENTINEL_WATER_DATASET_IMAGES_PATH to a folder of <class>/<image> directories.",
                status="index_missing",
            )

        total = len(entries)
        self._progress = (0, total)
        features = np.zeros((total, FEATURE_BINS), dtype=np.float32)
        hashes: List[int] = []
        files: List[str] = []
        labels: List[str] = []
        counts: Dict[str, int] = {}
        kept = 0

        for done, (relative, class_name, path) in enumerate(entries, start=1):
            try:
                with Image.open(path) as image:
                    feature, digest = _features_and_hash(image)
            except Exception:
                continue  # one unreadable frame must not abort a 6000-image build
            features[kept] = feature
            hashes.append(digest)
            files.append(relative)
            labels.append(class_name)
            counts[class_name] = counts.get(class_name, 0) + 1
            kept += 1
            if done % 100 == 0 or done == total:
                self._progress = (done, total)

        if kept == 0:
            raise MatchUnavailable("No reference image could be decoded.", status="index_missing")

        features = features[:kept]
        built_at = datetime.now(timezone.utc)
        meta = {
            "version": INDEX_VERSION,
            "builtAt": built_at.isoformat(),
            "root": str(self.images_path),
            "counts": counts,
        }
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.index_path.with_suffix(".tmp.npz")
        np.savez_compressed(
            temporary,
            features=features.astype(np.float16),
            hashes=np.array(hashes, dtype=np.uint64),
            files=np.array(files),
            labels=np.array(labels),
            meta=np.array(json.dumps(meta)),
        )
        temporary.replace(self.index_path)
        self._state = IndexState(
            features=features, hashes=hashes, files=files, labels=labels, built_at=built_at, counts=counts
        )
        self._progress = (kept, kept)

    def ensure_ready(self) -> Optional[str]:
        """Load or start building the index. Returns a status string when not ready yet."""
        if not self.enabled:
            return "disabled"
        if self._state is not None:
            return None
        with self._lock:
            if self._state is not None:
                return None
            if self._build_thread and self._build_thread.is_alive():
                return "indexing"
            try:
                if self._load_cached():
                    return None
            except MatchUnavailable:
                raise

            def worker() -> None:
                try:
                    self.build()
                    self._error = None
                except MatchUnavailable as exc:
                    self._error = exc.message
                except Exception as exc:  # pragma: no cover - defensive
                    self._error = f"Building the reference index failed: {exc}"

            self._error = None
            self._progress = (0, 0)
            self._build_thread = threading.Thread(target=worker, name="water-dataset-index", daemon=True)
            self._build_thread.start()
            return "indexing"

    # -- query -------------------------------------------------------------------

    def status_report(self) -> WaterDatasetMatch:
        """A non-ok WaterDatasetMatch describing why no match is available, or None when ready."""
        try:
            pending = self.ensure_ready()
        except MatchUnavailable as exc:
            return WaterDatasetMatch(status=exc.status, message=exc.message)
        if pending == "disabled":
            return WaterDatasetMatch(
                status="not_run", message="Reference-dataset matching is switched off on this backend."
            )
        if pending == "indexing":
            done, total = self._progress
            return WaterDatasetMatch(
                status="indexing",
                progress=round(done / total, 3) if total else 0.0,
                message=(
                    f"Indexing the reference dataset ({done}/{total} images). "
                    "Matching becomes available when this finishes."
                ),
            )
        if self._error:
            return WaterDatasetMatch(status="unavailable", message=self._error)
        return None

    def match(self, content: bytes) -> WaterDatasetMatch:
        not_ready = self.status_report()
        if not_ready is not None:
            return not_ready

        np, _ = _imports()
        state = self._state
        assert state is not None

        image = _open(content)
        query, digest = _features_and_hash(image)

        # Histogram intersection: each of the REGIONS regions sums to 1, so the total is bounded
        # by REGIONS and the mean over regions lands in 0..1 with no further calibration.
        similarities = np.minimum(state.features, query).sum(axis=1) / REGIONS

        top_k = max(1, min(settings.water_dataset_top_k, similarities.shape[0]))
        order = np.argpartition(-similarities, top_k - 1)[:top_k]
        order = order[np.argsort(-similarities[order])]

        neighbours: List[DatasetNeighbour] = []
        votes: Dict[str, float] = {}
        for position in order:
            index = int(position)
            class_name = state.labels[index]
            similarity = float(similarities[index])
            label, _level = class_meta(class_name)
            neighbours.append(
                DatasetNeighbour(
                    file=state.files[index],
                    class_name=class_name,
                    label=label,
                    similarity=round(similarity, 4),
                )
            )
            votes[class_name] = votes.get(class_name, 0.0) + similarity

        best_similarity = float(similarities[int(order[0])])
        winner = max(votes.items(), key=lambda item: item[1])
        # An image sharing no colour at all with the dataset scores 0 against every frame, which
        # would make the vote share 0/0. That case is a non-match, not a tie.
        vote_total = sum(votes.values())
        vote_share = winner[1] / vote_total if vote_total > 0 else 0.0
        matched_class = winner[0]
        matched_label, level = class_meta(matched_class)

        threshold = settings.water_dataset_match_threshold

        # Near-duplicate tier: is this essentially a frame the dataset already contains?
        #
        # A small hash distance is claimed only when that SAME frame is also a strong colour match.
        # A difference hash of a low-detail image (flat water, fog, an overexposed frame) carries
        # almost no signal and collides readily, so on its own it is not evidence of anything.
        duplicate_of: Optional[str] = None
        best_distance = 64
        for index, stored in enumerate(state.hashes):
            distance = _hamming(digest, stored)
            if distance < best_distance and float(similarities[index]) >= threshold:
                best_distance = distance
                if distance <= settings.water_dataset_duplicate_max_distance:
                    duplicate_of = state.files[index]
                    if distance == 0:
                        break

        dataset_size = len(state.files)
        common = dict(
            caveat=RELIABILITY_CAVEAT,
            dataset_size=dataset_size,
            match_threshold=round(threshold, 3),
            indexed_at=state.built_at,
            neighbours=neighbours,
            similarity=round(best_similarity, 4),
        )

        if best_similarity < threshold and duplicate_of is None:
            return WaterDatasetMatch(
                status="no_match",
                contaminated=False,
                message=(
                    f"No confident match. The closest reference frame scored "
                    f"{best_similarity:.2f}, below the {threshold:.2f} threshold, so this photo is "
                    "not being treated as evidence either way."
                ),
                **common,
            )

        flag_levels = settings.water_dataset_flag_levels
        contaminated = level in flag_levels
        if level is None:
            message = (
                f"Closest match is the \"{matched_class}\" reference class, which this deployment has "
                "not mapped to a contamination level, so no flag was raised."
            )
        elif contaminated:
            message = (
                f"Resembles reference frames labelled \"{matched_label}\" "
                f"({vote_share:.0%} of the {top_k} nearest frames, best similarity {best_similarity:.2f})."
            )
        else:
            message = (
                f"Closest match is the \"{matched_label}\" reference class "
                f"(best similarity {best_similarity:.2f}) — below the level that raises a flag."
            )
        if duplicate_of is not None:
            message += (
                f" This photo is a near-duplicate of reference frame {duplicate_of} "
                f"(hash distance {best_distance}), so treat it as a replayed sample, not a new observation."
            )

        return WaterDatasetMatch(
            status="ok",
            contaminated=bool(contaminated),
            matched_class=matched_class,
            matched_label=matched_label,
            contamination_level=level,  # type: ignore[arg-type]
            vote_share=round(float(vote_share), 3),
            near_duplicate=duplicate_of is not None,
            duplicate_of=duplicate_of,
            message=message,
            **common,
        )

    def describe(self) -> dict:
        """Index health, for /api/water/dataset-status."""
        state = self._state
        done, total = self._progress
        return {
            "enabled": self.enabled,
            "imagesPath": str(self.images_path),
            "indexPath": str(self.index_path),
            "ready": state is not None,
            "datasetSize": len(state.files) if state else 0,
            "classes": state.counts if state else {},
            "builtAt": state.built_at.isoformat() if state and state.built_at else None,
            "building": bool(self._build_thread and self._build_thread.is_alive()),
            "progress": round(done / total, 3) if total else None,
            "error": self._error,
            "matchThreshold": settings.water_dataset_match_threshold,
            "duplicateMaxDistance": settings.water_dataset_duplicate_max_distance,
            "flagLevels": sorted(settings.water_dataset_flag_levels),
        }


_matcher: Optional[DatasetMatcher] = None
_matcher_lock = threading.Lock()


def get_dataset_matcher() -> DatasetMatcher:
    global _matcher
    if _matcher is None:
        with _matcher_lock:
            if _matcher is None:
                _matcher = DatasetMatcher(
                    Path(settings.water_dataset_images_path).expanduser(),
                    Path(settings.water_dataset_index_path).expanduser(),
                )
    return _matcher


def build_match_report(content: Optional[bytes]) -> WaterDatasetMatch:
    """Entry point used by the Water Agent. Never raises."""
    if content is None:
        return WaterDatasetMatch(status="not_run", message="No image supplied for reference matching.")
    try:
        return get_dataset_matcher().match(content)
    except MatchUnavailable as exc:
        return WaterDatasetMatch(status=exc.status, message=exc.message)
    except Exception as exc:  # pragma: no cover - defensive
        return WaterDatasetMatch(status="unavailable", message=f"Reference matching failed: {exc}")
