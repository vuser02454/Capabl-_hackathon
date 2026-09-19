"""Stage 2: classify one cropped waste object and map it to a segregation category.

Given a crop the detector produced, answer "what is this" and therefore "biodegradable or not".
It never sees a whole scene — localisation is the detector's job, and asking a classifier to do it
would mean inventing boxes.

Two refusals are built in:

  - Below the configured confidence the result is `uncertain`, not the best guess. A 38%-confident
    "plastic_bottles" is not a classification; presenting it as one puts a number on a coin flip.
  - With no trained weights the classifier reports that plainly rather than falling back to
    anything. There is no heuristic here that pretends to be a model.

The segregation mapping lives in `training/config/waste_categories.json`, not in this file, because
what counts as recyclable varies by municipality and a hard-coded mapping quietly exports one
region's rules everywhere.
"""

import json
import logging
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ecosentinel.waste.classifier")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WEIGHTS = REPO_ROOT / "runs" / "classification" / "best.pt"
DEFAULT_CATEGORIES = REPO_ROOT / "training" / "config" / "waste_categories.json"

#: Preprocessing is imported from the training package rather than restated here. It was restated
#: once: training validated on square dataset photos with Resize+CenterCrop and scored macro-F1
#: 0.911, while serving applied the same transform to tall detector crops, where CenterCrop keeps
#: a patch of the middle and discards the object's shape. On 145 real bottle crops that cost
#: 36% vs 87% correct, and no metric in the project moved. One definition, one place.
_TRAINING_DIR = REPO_ROOT / "training"


def _training_package():
    """The training package, which owns the preprocessing definition."""
    import sys

    if str(_TRAINING_DIR) not in sys.path:
        sys.path.insert(0, str(_TRAINING_DIR))
    import waste_preprocess  # noqa: PLC0415

    return waste_preprocess


def _eval_transform(image_size: int):
    return _training_package().eval_transform(image_size)


def _preprocess_version() -> str:
    return _training_package().PREPROCESS_VERSION


class ClassifierUnavailable(Exception):
    """The classifier cannot answer. Callers report `uncertain`, never a guess."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def load_categories(path: Optional[Path] = None) -> Dict[str, Any]:
    """Segregation mapping and thresholds. Missing file is a configuration error, not a default."""
    source = Path(path or DEFAULT_CATEGORIES)
    if not source.is_file():
        raise ClassifierUnavailable(f"Waste category configuration not found at {source}.")
    return json.loads(source.read_text())


class WasteClassifier:
    """MobileNetV3 classifier over the eight waste classes, loaded once per process."""

    _lock = threading.Lock()
    _cache: Dict[str, Any] = {}

    def __init__(self, weights_path: Optional[Path] = None, categories_path: Optional[Path] = None):
        self.weights_path = Path(weights_path or DEFAULT_WEIGHTS)
        self.config = load_categories(categories_path)
        self.threshold = float(self.config["thresholds"]["classification_confidence"])
        self._model = None
        self._classes: List[str] = []
        self._image_size = 224
        self._transform = None
        self._preprocess_mismatch: Optional[str] = None

    def is_configured(self) -> bool:
        return self.weights_path.is_file()

    def _load(self):
        """Load weights once and reuse. Torch is imported lazily: it is heavy and optional."""
        key = str(self.weights_path)
        with WasteClassifier._lock:
            cached = WasteClassifier._cache.get(key)
            if cached is not None:
                self._model, self._classes, self._image_size, self._transform = cached
                return

            if not self.is_configured():
                raise ClassifierUnavailable(
                    f"No trained waste classifier at {self.weights_path}. "
                    "Train one with training/train_waste_classifier.py."
                )
            try:
                import torch
                import torch.nn as nn
                from torchvision.models import mobilenet_v3_small
            except ImportError as exc:
                raise ClassifierUnavailable(
                    "torch and torchvision are required for waste classification."
                ) from exc

            checkpoint = torch.load(self.weights_path, map_location="cpu", weights_only=False)
            classes = checkpoint["classes"]
            image_size = int(checkpoint.get("image_size", 224))

            model = mobilenet_v3_small()
            model.classifier[3] = nn.Linear(model.classifier[3].in_features, len(classes))
            model.load_state_dict(checkpoint["state_dict"])
            model.eval()

            transform = _eval_transform(image_size)

            # A checkpoint trained under different preprocessing still loads — the weights are
            # valid — but the mismatch is recorded and surfaced in `status()` rather than left to
            # be discovered as unexplained misclassification.
            trained_with = checkpoint.get("preprocess")
            if trained_with is None:
                # Not "no problem" — "no claim". These weights predate preprocessing versioning,
                # so the match cannot be verified either way. Saying nothing here would present an
                # unverifiable state as a verified one.
                self._preprocess_mismatch = (
                    "These weights do not record the preprocessing they were trained with, so the "
                    f"match with the served transform ('{_preprocess_version()}') is unverified. "
                    "It was chosen by measurement on real detector crops, not by matching."
                )
            elif trained_with != _preprocess_version():
                self._preprocess_mismatch = (
                    f"Weights were trained with preprocessing '{trained_with}', "
                    f"but '{_preprocess_version()}' is being applied."
                )
            else:
                self._preprocess_mismatch = None
            if self._preprocess_mismatch:
                logger.warning("waste_classifier_preprocess_mismatch %s", self._preprocess_mismatch)

            WasteClassifier._cache[key] = (model, classes, image_size, transform)
            self._model, self._classes, self._image_size, self._transform = (
                model, classes, image_size, transform
            )
            logger.info("waste_classifier_loaded classes=%s weights=%s", len(classes), self.weights_path)

    @property
    def classes(self) -> List[str]:
        if not self._classes and self.is_configured():
            self._load()
        return list(self._classes)

    def loaded_model(self):
        """The live model, its class list and the served transform — for attribution only.

        Exposed so `waste_xai.py` can run gradients through the SAME network instance that
        produced the prediction. An explanation computed against a separately-loaded copy, or
        against a re-derived transform, would be an explanation of a different computation — which
        is the one thing an attribution method must not be. Raises `ClassifierUnavailable` exactly
        as `classify` does, so callers degrade the same way.
        """
        self._load()
        return self._model, list(self._classes), self._transform

    def segregation_for(self, class_name: str) -> Dict[str, Optional[str]]:
        """Class -> segregation category and handling heuristic, from configuration."""
        entry = (self.config.get("classes") or {}).get(class_name, {})
        return {
            "category": entry.get("category"),
            "handling": entry.get("handling"),
            "display": entry.get("display", class_name.replace("_", " ").title()),
        }

    def classify(self, image, capture: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """One PIL crop -> class, confidence and segregation. Never raises.

        Below the configured threshold the answer is `uncertain` with `needs_review`, carrying the
        top guess only as `candidate` — visible for a human, never presented as a decision.

        `capture`, when given, is filled with the exact tensor this call fed the network and the
        full probability vector. Diagnosis needs the real input, not a reconstruction of it: a
        separately-built "equivalent" crop would hide precisely the preprocessing faults it is
        meant to find. Nothing about the prediction changes when it is passed.
        """
        try:
            self._load()
            import torch

            tensor = self._transform(image.convert("RGB")).unsqueeze(0)
            with torch.no_grad():
                probabilities = torch.softmax(self._model(tensor), dim=1)[0]
            confidence, index = float(probabilities.max()), int(probabilities.argmax())
            if capture is not None:
                capture["tensor"] = tensor
                capture["classes"] = list(self._classes)
                capture["probabilities"] = [float(p) for p in probabilities]
                capture["image_size"] = self._image_size
        except ClassifierUnavailable as exc:
            return {
                "classification": None, "classification_confidence": None,
                "segregation": "uncertain", "status": "unavailable", "message": exc.message,
            }
        except Exception as exc:  # noqa: BLE001 - a classifier fault must not break an analysis
            logger.warning("waste_classification_failed", exc_info=True)
            return {
                "classification": None, "classification_confidence": None,
                "segregation": "uncertain", "status": "unavailable",
                "message": f"Classification failed ({exc.__class__.__name__}).",
            }

        class_name = self._classes[index]
        if confidence < self.threshold:
            return {
                "classification": None,
                "classification_confidence": round(confidence, 4),
                "segregation": "uncertain",
                "status": "needs_review",
                # The guess is shown, but it is not the answer.
                "candidate": class_name,
                "message": (
                    f"Top class '{class_name}' at {confidence:.0%} is below the "
                    f"{self.threshold:.0%} threshold, so no segregation is asserted."
                ),
            }

        mapping = self.segregation_for(class_name)
        return {
            "classification": class_name,
            "classification_confidence": round(confidence, 4),
            "segregation": mapping["category"] or "uncertain",
            "handling": mapping["handling"],
            "display": mapping["display"],
            "status": "confirmed",
        }

    def status(self) -> Dict[str, Any]:
        """Health for the API. Never reports a model it does not have."""
        if not self.is_configured():
            return {
                "configured": False, "available": False, "weights": str(self.weights_path),
                "classes": [], "threshold": self.threshold,
                "detail": "No trained classifier. Run training/train_waste_classifier.py.",
            }
        try:
            self._load()
        except ClassifierUnavailable as exc:
            return {"configured": True, "available": False, "weights": str(self.weights_path),
                    "classes": [], "threshold": self.threshold, "detail": exc.message}
        return {
            "configured": True, "available": True, "weights": str(self.weights_path),
            "classes": list(self._classes), "threshold": self.threshold,
            "detail": self._preprocess_mismatch,
        }


_singleton_lock = threading.Lock()
_singleton: Optional[WasteClassifier] = None


def get_waste_classifier() -> WasteClassifier:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = WasteClassifier()
        return _singleton
