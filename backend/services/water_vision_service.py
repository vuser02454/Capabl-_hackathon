"""Visual water-pollution detection consumed by the Water Quality Agent.

Scope
-----
This service answers exactly one question: *what pollution objects are visible in this
image of water?* It is a VISUAL signal. It cannot measure pH, turbidity, dissolved oxygen,
temperature or chemical contamination — those come from the sensor/dataset readings handled by
services/water_sensor_service.py. Nothing here ever writes a water-quality parameter.

Backends (selected by ECOSENTINEL_WATER_VISION_PROVIDER)
-------------------------------------------------------
local     Ultralytics-compatible weights at YOLO26_MODEL_PATH, loaded once and cached.
roboflow  Roboflow hosted inference (ROBOFLOW_API_KEY + ROBOFLOW_MODEL_ID) over httpx.
auto      local when the weights file exists, else roboflow when configured, else unavailable.
off       never run.

Both backends import their dependency lazily, so a missing package degrades to an
"unavailable" report instead of breaking import of the Water Agent. Class names always come
from the model or the API response — this module never invents or remaps a class.
"""

import base64
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from config import settings
from core.risk import clamp, risk_level_for, round_half_up
from schemas import VisionDetection, VisionDetectionBox, WaterVisionReport

#: Fallback only, for when nothing better can be derived. The displayed identity must come from
#: the weights that are actually loaded — announcing "YOLO26" while running yolov8n.pt tells an
#: operator the system is doing something it is not.
MODEL_LABEL = "YOLO (unidentified weights)"

#: yolov8n -> "YOLOv8n", yolo11s -> "YOLO11s", yolo26n -> "YOLO26n".
_YOLO_NAME = re.compile(r"^yolo(v?)(\d+)([nsmlx])?$", re.IGNORECASE)
_SIZE_WORD = {"n": "Nano", "s": "Small", "m": "Medium", "l": "Large", "x": "Extra-large"}


def model_label_for(weights_path: Optional[str]) -> str:
    """A display name derived from the configured weights file.

    Anything unrecognised falls through to the filename stem rather than a guess, so a
    waste-trained `river-litter-v3.pt` shows as `river-litter-v3` and the operator can see exactly
    which weights produced a detection.
    """
    if not weights_path:
        return MODEL_LABEL
    stem = Path(weights_path).stem
    match = _YOLO_NAME.match(stem)
    if not match:
        return stem
    _v, version, size = match.groups()
    label = f"YOLOv{version}" if _v else f"YOLO{version}"
    if size:
        label += size.lower()
    return label


@dataclass
class VisionOutput:
    """Raw detector output, before it is scored or shaped into the API contract."""

    model: str
    detections: List[VisionDetection] = field(default_factory=list)
    annotated_image: Optional[str] = None
    #: Frame size in pixels. Needed to say WHERE in the frame a box sits ("lower-left foreground")
    #: — a bbox alone is meaningless without the frame it was measured against.
    image_width: Optional[int] = None
    image_height: Optional[int] = None


class WaterVisionDetector(Protocol):
    name: str
    model: str

    def is_configured(self) -> bool: ...

    def detect(self, content: bytes, filename: str) -> VisionOutput: ...


class VisionUnavailable(Exception):
    """Raised inside a detector when it cannot run. Never escapes to the Water Agent."""

    def __init__(self, message: str, status: str = "unavailable"):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------- local weights


class LocalYoloDetector:
    """Ultralytics-compatible local inference.

    NOTE ON COMPATIBILITY: a YOLO26 checkpoint only loads if the installed `ultralytics`
    build actually supports that architecture. Being named "ultralytics" is not sufficient.
    If the load fails we surface the real loader error rather than guessing, so the operator
    can see whether they need a newer package or the hosted route instead.
    """

    name = "Local weights"

    _lock = threading.Lock()
    _cache: Dict[str, object] = {}

    def __init__(self, weights_path: str, confidence: float):
        self.weights_path = weights_path
        self.confidence = confidence
        # Derived from the weights actually configured, never asserted. Claiming "YOLO26" while
        # running yolov8n.pt would tell an operator the system is doing something it is not.
        self.model = model_label_for(weights_path)

    def is_configured(self) -> bool:
        return bool(self.weights_path) and Path(self.weights_path).is_file()

    def _load(self):
        """Load the model once per process and reuse it for every request."""
        with LocalYoloDetector._lock:
            cached = LocalYoloDetector._cache.get(self.weights_path)
            if cached is not None:
                return cached
            try:
                from ultralytics import YOLO  # imported lazily: heavy, and optional
            except ImportError as exc:
                raise VisionUnavailable(
                    "The 'ultralytics' package is not installed, so local YOLO inference "
                    "cannot run. Install it or use Roboflow hosted inference.",
                    status="model_not_configured",
                ) from exc
            try:
                model = YOLO(self.weights_path)
            except Exception as exc:  # noqa: BLE001 - surface the loader's own message
                raise VisionUnavailable(f"Could not load vision weights: {exc}") from exc
            LocalYoloDetector._cache[self.weights_path] = model
            return model

    def detect(self, content: bytes, filename: str) -> VisionOutput:
        if not self.is_configured():
            raise VisionUnavailable(
                f"Vision model is not configured (no weights at '{self.weights_path}').",
                status="model_not_configured",
            )
        model = self._load()
        image = _decode_image(content)
        try:
            prediction = model.predict(image, conf=self.confidence, verbose=False)[0]
        except Exception as exc:  # noqa: BLE001
            raise VisionUnavailable(f"Vision inference failed: {exc}") from exc

        names = getattr(prediction, "names", None) or getattr(model, "names", {}) or {}
        detections: List[VisionDetection] = []
        for box in getattr(prediction, "boxes", []) or []:
            try:
                x1, y1, x2, y2 = (float(v) for v in box.xyxy[0].tolist())
                confidence = float(box.conf[0])
                # Class names come from the trained model, never from a hard-coded list.
                class_name = str(names.get(int(box.cls[0]), int(box.cls[0])))
            except Exception:  # noqa: BLE001 - skip a malformed box, keep the rest
                continue
            detections.append(
                VisionDetection(
                    class_name=class_name,
                    confidence=round_half_up(confidence, 3),
                    bbox=VisionDetectionBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    # The raw class above is untouched; this is the interpretation beside it.
                    semantic_category=categorize(class_name),  # type: ignore[arg-type]
                )
            )
        # `image` is HxWxC from the decoder, so the frame size comes from the array itself rather
        # than from anything the model reports.
        height, width = (int(image.shape[0]), int(image.shape[1])) if getattr(image, "shape", None) else (None, None)
        return VisionOutput(
            model=self.model, detections=detections, image_width=width, image_height=height
        )


# --------------------------------------------------------------------------- Roboflow hosted


class RoboflowHostedDetector:
    """Roboflow hosted inference. Credentials come from the environment only."""

    name = "YOLO26 (Roboflow hosted)"
    def __init__(self, api_key: Optional[str], model_id: Optional[str], confidence: float, base_url: str, timeout: float):
        self.api_key = api_key
        self.model_id = model_id
        self.confidence = confidence
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model_id)

    def detect(self, content: bytes, filename: str) -> VisionOutput:
        if not self.is_configured():
            raise VisionUnavailable(
                "Roboflow inference is not configured (set ROBOFLOW_API_KEY and ROBOFLOW_MODEL_ID).",
                status="model_not_configured",
            )
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - httpx ships with the backend
            raise VisionUnavailable("httpx is required for Roboflow inference.", status="model_not_configured") from exc

        try:
            response = httpx.post(
                f"{self.base_url}/{self.model_id}",
                params={"api_key": self.api_key, "confidence": self.confidence},
                content=base64.b64encode(content),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:  # noqa: BLE001
            # Never let the URL or key reach the message.
            raise VisionUnavailable(f"Roboflow inference request failed: {type(exc).__name__}") from exc

        detections: List[VisionDetection] = []
        for item in payload.get("predictions", []) or []:
            try:
                cx, cy = float(item["x"]), float(item["y"])
                w, h = float(item["width"]), float(item["height"])
                class_name = str(item.get("class", "object"))
                detections.append(
                    VisionDetection(
                        class_name=class_name,
                        confidence=round_half_up(float(item.get("confidence", 0.0)), 3),
                        # Roboflow reports centre + size; the contract is corner-to-corner.
                        bbox=VisionDetectionBox(x1=cx - w / 2, y1=cy - h / 2, x2=cx + w / 2, y2=cy + h / 2),
                        semantic_category=categorize(class_name),  # type: ignore[arg-type]
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        image_info = payload.get("image") or {}
        width = image_info.get("width")
        height = image_info.get("height")
        return VisionOutput(
            model=self.model,
            detections=detections,
            image_width=int(width) if isinstance(width, (int, float)) else None,
            image_height=int(height) if isinstance(height, (int, float)) else None,
        )


# --------------------------------------------------------------------------- helpers


def exif_upright(image, image_ops=None):
    """Apply the EXIF orientation tag, returning the image as a viewer would show it.

    Pillow decodes the stored pixel buffer and does NOT honour `Orientation`. A browser does: an
    `<img>` applies it by default. So a phone photo taken in portrait is stored landscape with
    `Orientation=6`, and without this the backend measured the frame as 640x480 while the frontend
    rendered it 480x640. The API returns `image_width`/`image_height` from the decoded array and
    `RealWasteDetection.tsx` positions every box as a percentage of those, so the two disagreeing
    put every box in the wrong place and stretched it — a box at `x2 = 640` became a full-width
    overlay on a portrait photo. The detector was also being run on a sideways scene.

    Shared with the waste pipeline's own decode via this function rather than restated there: the
    crops must come out of the same frame the detector drew boxes on, and two copies of this is
    exactly how they would drift apart.

    A missing, unreadable or absent orientation tag leaves the image untouched.
    """
    if image_ops is None:
        from PIL import ImageOps as image_ops  # noqa: PLC0415, N813

    try:
        return image_ops.exif_transpose(image) or image
    except Exception:  # noqa: BLE001 - a malformed EXIF block must not fail the analysis
        return image


def _decode_image(content: bytes):
    """Bytes -> an array ultralytics accepts, with a clear error if the image is unreadable.

    Returned in **BGR**, not RGB. Ultralytics loads a file path with OpenCV and therefore treats a
    bare ndarray as BGR; handing it RGB swaps the red and blue channels of every frame. It does not
    fail, it just quietly detects less, which is why this survived unnoticed.

    Measured on the 59 held-out TACO test images at the production confidence threshold, the same
    pixels passed as RGB rather than BGR cost the waste detector 62 detections against 114 — 46% of
    them. The COCO model lost 28 against 30, so the damage scales with how much a model relies on
    colour, and the effect was easy to mistake for a weak model.
    """
    try:
        import numpy as np
        from PIL import Image, ImageOps
        import io

        image = Image.open(io.BytesIO(content))
        image.load()
        image = exif_upright(image, ImageOps)
        # Contiguous: the reversed view carries a negative stride, which torch refuses to share.
        return np.ascontiguousarray(np.array(image.convert("RGB"))[:, :, ::-1])
    except ImportError as exc:
        raise VisionUnavailable(
            "Pillow and numpy are required for local YOLO26 inference.", status="model_not_configured"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise VisionUnavailable(f"The image could not be decoded: {type(exc).__name__}") from exc


def _resolve_weights(configured: Optional[str]) -> str:
    """Resolve a relative weights path against the backend directory, not the process cwd.

    `YOLO26_MODEL_PATH=models/yolov8n.pt` otherwise means different files depending on where the
    command was launched from — the API found the model and the CLI at the repo root did not,
    which reads as "no model configured" rather than "wrong working directory".
    """
    if not configured:
        return ""
    path = Path(configured)
    if path.is_absolute():
        return str(path)
    from config import BACKEND_DIR

    relative_to_backend = BACKEND_DIR / path
    if relative_to_backend.is_file():
        return str(relative_to_backend)
    return str(path)  # keep the original so the error message names what was configured


def get_waste_pipeline_detector() -> Optional[WaterVisionDetector]:
    """Detector for the waste pipeline, not the Water Agent.

    Prefers `WASTE_DETECTOR_MODEL_PATH` (TACO-trained `waste_detector.pt`). Falls back to the
    water-vision detector only when those weights are absent, so an unconfigured waste path does
    not silently invent a second model.
    """
    waste_path = _resolve_weights(settings.waste_detector_model_path)
    if waste_path and Path(waste_path).is_file():
        return LocalYoloDetector(waste_path, settings.yolo_confidence_threshold)
    return get_water_vision_detector()


def waste_detector_status() -> dict:
    """Health of the waste pipeline's detector, reported independently of water vision."""
    detector = get_waste_pipeline_detector()
    if detector is None:
        return {
            "provider": "off",
            "configured": False,
            "available": False,
            "model": None,
            "detail": "Waste detection is switched off.",
        }
    configured = bool(getattr(detector, "is_configured", lambda: False)())
    path = getattr(detector, "weights_path", "")
    return {
        "provider": "local",
        "configured": configured,
        "available": configured,
        "model": getattr(detector, "model", None) if configured else None,
        "detail": None if configured else (
            f"No weights at '{path}'. Set WASTE_DETECTOR_MODEL_PATH."
        ),
    }


def get_water_vision_detector() -> Optional[WaterVisionDetector]:
    """Pick a detector from configuration. None means vision is switched off entirely."""
    provider = settings.water_vision_provider
    if provider == "off":
        return None

    local = LocalYoloDetector(_resolve_weights(settings.yolo26_model_path), settings.yolo_confidence_threshold)
    hosted = RoboflowHostedDetector(
        settings.roboflow_api_key,
        settings.roboflow_model_id,
        settings.yolo_confidence_threshold,
        settings.roboflow_base_url,
        settings.roboflow_timeout_seconds,
    )

    if provider == "local":
        return local
    if provider == "roboflow":
        return hosted
    # auto: prefer real local weights, fall back to hosted, else report the local path as missing.
    if local.is_configured():
        return local
    if hosted.is_configured():
        return hosted
    return local


def categorize(class_name: str) -> str:
    """One raw detector class -> its semantic interpretation.

    A thin alias. The taxonomy is NOT defined here: it lives in `core/investigation.py` alongside
    `is_pollution_class` / `is_never_waste`, which the frame investigation and
    `POST /api/water/scan-frame` already use. A second list here is exactly how the same image
    came to get two different answers from two endpoints.
    """
    from core.investigation import semantic_category_for

    return semantic_category_for(class_name)


def effective_category(detection: VisionDetection) -> str:
    """The detection's category, derived from its class name when the field was never set."""
    from core.investigation import effective_semantic_category

    return effective_semantic_category(detection)


def pollution_detections(detections: List[VisionDetection]) -> List[VisionDetection]:
    """The subset that indicates visible litter. `unclassified_object` is NOT included.

    Counting an object the taxonomy makes no claim about would be inferring pollution from
    ignorance. It stays visible in `detections` for a reviewer; it does not reach the score.
    """
    return [d for d in detections if effective_category(d) == "visible_surface_litter"]


def score_detections(detections: List[VisionDetection], count_reference: float) -> float:
    """Normalised 0..1 visible-LITTER density.

    Deliberately simple and auditable: the count of detections whose semantic category is
    `visible_surface_litter`, relative to `count_reference`
    (ECOSENTINEL_WATER_VISUAL_COUNT_REFERENCE) — the object count in one frame treated as maximum
    density. This mirrors the convention the Waste Detection Agent already uses for litter density
    (COUNT_REFERENCE in agents/waste_agent.py) so the two visual signals are scored the same way.

    Only litter-class detections are counted. The production water detector is a COCO model, so an
    unfiltered count scored two people and four kites in a river photo as 0.30 visual pollution and
    escalated the water risk by 0.08 — pollution that nobody observed. Within the litter subset no
    per-class severity weighting is applied, because the class list is model-defined and we do not
    assume any litter class is worse than another.

    `count_reference` remains an unvalidated convention (blocker B2,
    runs/water/dataset_comparison/WATER_TRAINING_READINESS.md). Filtering changes WHAT is counted,
    not the calibration of the denominator; that is documented, not silently fixed here.
    """
    if count_reference <= 0:
        return 0.0
    return round_half_up(clamp(len(pollution_detections(detections)) / count_reference))


def build_report(
    detector: Optional[WaterVisionDetector],
    content: Optional[bytes],
    filename: str,
    count_reference: Optional[float] = None,
) -> WaterVisionReport:
    """Run the detector and shape the outcome into the API contract.

    Never raises: every failure becomes a report with `available=False` and a reason, so a
    vision problem can never take down the Water Agent or the wider analysis.
    """
    threshold = settings.yolo_confidence_threshold
    reference = settings.water_visual_count_reference if count_reference is None else count_reference

    if content is None:
        return WaterVisionReport(status="not_run", message="No image was supplied for visual analysis.")
    if detector is None:
        return WaterVisionReport(status="not_run", message="Visual water-pollution detection is disabled.")

    try:
        output = detector.detect(content, filename)
    except VisionUnavailable as exc:
        return WaterVisionReport(
            status=exc.status,  # type: ignore[arg-type]
            model=getattr(detector, "model", None) or MODEL_LABEL,
            message=exc.message,
            confidence_threshold=threshold,
        )
    except Exception as exc:  # noqa: BLE001 - a detector bug must not escape
        return WaterVisionReport(
            status="unavailable",
            model=getattr(detector, "model", None) or MODEL_LABEL,
            message=f"Visual detection failed unexpectedly: {type(exc).__name__}",
            confidence_threshold=threshold,
        )

    counts: Dict[str, int] = {}
    for detection in output.detections:
        counts[detection.class_name] = counts.get(detection.class_name, 0) + 1

    # A detector that predates `semantic_category` (a stub, an older backend) leaves the field at
    # its default. Settle it here so the value the API returns is the value that was scored.
    for detection in output.detections:
        detection.semantic_category = effective_category(detection)  # type: ignore[assignment]

    litter = pollution_detections(output.detections)
    pollution_counts: Dict[str, int] = {}
    for detection in litter:
        pollution_counts[detection.class_name] = pollution_counts.get(detection.class_name, 0) + 1
    non_pollution = sum(1 for d in output.detections if d.semantic_category == "non_pollution_object")

    score = score_detections(output.detections, reference)
    return WaterVisionReport(
        available=True,
        status="ok",
        model=output.model,
        detections=output.detections,
        object_counts=counts,
        total_objects=len(output.detections),
        pollution_objects=len(litter),
        non_pollution_objects=non_pollution,
        pollution_counts=pollution_counts,
        confidence_threshold=threshold,
        visual_score=score,
        visual_level=risk_level_for(score),  # type: ignore[arg-type]
        annotated_image=output.annotated_image,
        image_width=output.image_width,
        image_height=output.image_height,
    )


def status() -> dict:
    """Vision role health for GET /api/ai/status.

    The model name is whatever the configured weights are, never an architecture this code hopes
    is loaded.
    """
    provider = settings.water_vision_provider
    detector = get_water_vision_detector()
    if detector is None:
        return {"provider": provider or "off", "configured": False, "available": False,
                "model": None, "detail": "Visual pollution detection is switched off."}

    configured = bool(getattr(detector, "is_configured", lambda: False)())
    detail = None
    if not configured:
        detail = (
            f"No weights at '{getattr(detector, 'weights_path', '')}'. Set YOLO26_MODEL_PATH."
            if provider == "local"
            else "The hosted detector is not fully configured."
        )
    return {
        "provider": provider,
        "configured": configured,
        "available": configured,
        "model": getattr(detector, "model", None) if configured else None,
        "detail": detail,
    }
