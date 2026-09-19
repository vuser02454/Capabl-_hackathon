"""Waste / litter detection source consumed by the Waste Detection Agent.

Today:  MockWasteDetector produces deterministic, realistic detections so the demo
        is reproducible (same image -> same result, identical to the browser demo).
Later:  YoloWasteDetector runs an Ultralytics YOLO model fine-tuned on litter
        classes (e.g. TACO dataset) and maps model classes -> plastic/paper/other.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from config import settings
from core.errors import InvalidImageError, ProviderNotConfiguredError
from core.geo import haversine_km
from core.risk import round_half_up
from core.rng import seeded
from data.locations import nearest_profile
from schemas import Detection, LocationContext
from services.location_service import demo_site

LABELS: Dict[str, List[str]] = {
    "plastic": ["PET bottle", "Plastic bag", "Food wrapper", "Plastic cup", "Styrofoam"],
    "paper": ["Cardboard", "Paper cup", "Newspaper"],
    "other": ["Metal can", "Glass bottle", "Textile", "Rubber"],
}

IMAGE_SIGNATURES = (b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"RIFF", b"BM")


@dataclass(frozen=True)
class DetectionOutput:
    source_id: str
    source_name: str
    input_type: str  # camera | upload
    model: str
    detections: List[Detection]
    is_mock: bool
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None


class WasteDetector(Protocol):
    name: str
    model: str

    def detect_camera_frame(self, location: LocationContext) -> DetectionOutput: ...

    def detect_image(self, content: bytes, filename: str, location: LocationContext) -> DetectionOutput: ...


def validate_image(content: Optional[bytes], content_type: Optional[str], max_bytes: int) -> bytes:
    if not content:
        raise InvalidImageError("The uploaded image is empty. Please choose another file.")
    if len(content) > max_bytes:
        raise InvalidImageError(f"Image exceeds the {max_bytes // (1024 * 1024)} MB upload limit.")
    if content_type and not content_type.startswith("image/"):
        raise InvalidImageError("Unsupported file type. Upload a JPG, PNG or WebP image.")
    if not content.startswith(IMAGE_SIGNATURES):
        raise InvalidImageError("The file does not look like a valid image.")
    return content


def generate_detections(seed_key: str, plastic: int, paper: int, other: int) -> List[Detection]:
    rng = seeded(seed_key)
    categories = ["plastic"] * plastic + ["paper"] * paper + ["other"] * other
    detections: List[Detection] = []
    for index, category in enumerate(categories):
        options = LABELS[category]
        label = options[int(rng() * len(options))]
        width = 0.05 + rng() * 0.09
        height = 0.05 + rng() * 0.1
        x = 0.03 + rng() * (0.94 - width)
        y = 0.28 + rng() * (0.68 - height)
        confidence = round_half_up(0.76 + rng() * 0.22, 2)
        detections.append(
            Detection(
                id=f"det-{index + 1:02d}",
                label=label,
                category=category,  # type: ignore[arg-type]
                confidence=confidence,
                bbox=[round_half_up(v, 4) for v in (x, y, width, height)],
            )
        )
    return detections


def simulated_upload_counts(seed_key: str) -> Dict[str, int]:
    rng = seeded(seed_key)
    total = 6 + int(rng() * 20)
    plastic = int(round_half_up(total * (0.4 + rng() * 0.25), 0))
    paper = int((total - plastic) * (0.3 + rng() * 0.4))
    return {"plastic": plastic, "paper": paper, "other": total - plastic - paper}


class MockWasteDetector:
    name = "Simulated detector"
    model = "YOLOv8n-waste (simulated)"

    def detect_camera_frame(self, location: LocationContext) -> DetectionOutput:
        profile, _ = nearest_profile(location.latitude, location.longitude)
        waste = profile["waste"]
        lat, lon, simulated = demo_site(location, waste.get("latitude"), waste.get("longitude"), 0.6, -1.3)
        return DetectionOutput(
            source_id="DEMO-CAM" if simulated else waste["cameraId"],
            source_name="Simulated observation point (demo)" if simulated else waste["cameraName"],
            input_type="camera",
            model=self.model,
            detections=generate_detections(
                f"camera:{profile['id']}", waste["plastic"], waste["paper"], waste["other"]
            ),
            is_mock=True,
            latitude=lat,
            longitude=lon,
            distance_km=round_half_up(haversine_km(location.latitude, location.longitude, lat, lon), 1),
        )

    def detect_image(self, content: bytes, filename: str, location: LocationContext) -> DetectionOutput:
        seed_key = f"upload:{filename}:{len(content)}"
        counts = simulated_upload_counts(seed_key)
        return DetectionOutput(
            source_id="UPLOAD",
            source_name=filename,
            input_type="upload",
            model=self.model,
            detections=generate_detections(
                f"{seed_key}:boxes", counts["plastic"], counts["paper"], counts["other"]
            ),
            is_mock=True,
        )


class YoloWasteDetector:
    """Ultralytics YOLO integration (not yet enabled).

    Sketch:
        from ultralytics import YOLO
        model = YOLO(weights_path)
        result = model.predict(image, conf=0.35)[0]
        for box in result.boxes: map result.names[int(box.cls)] -> plastic/paper/other
    """

    name = "YOLO"
    model = "YOLOv8n-waste"

    def __init__(self, weights_path: str):
        self.weights_path = weights_path

    def detect_camera_frame(self, location: LocationContext) -> DetectionOutput:
        raise ProviderNotConfiguredError("Camera stream ingestion is not configured.")

    def detect_image(self, content: bytes, filename: str, location: LocationContext) -> DetectionOutput:
        raise ProviderNotConfiguredError(
            f"YOLO weights not loaded ({self.weights_path}). Switch to Demo Mode."
        )


def get_waste_detector(demo_mode: bool) -> WasteDetector:
    if demo_mode or settings.waste_provider == "mock":
        return MockWasteDetector()
    if settings.waste_provider == "yolo":
        return YoloWasteDetector(settings.yolo_weights_path)
    raise ProviderNotConfiguredError(f"Unknown waste provider '{settings.waste_provider}'.")
