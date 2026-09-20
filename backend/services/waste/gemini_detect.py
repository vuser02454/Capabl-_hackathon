"""EXPERIMENTAL: Gemini as a second opinion on waste detection, measured against YOLO.

This is a comparison instrument, not part of the production path. `POST /api/waste/segregate`
is untouched and still runs `waste_detector.pt`; nothing here is called from it, and Gemini is
never consulted when YOLO is unsure. That wiring is a decision to be made from the numbers this
endpoint produces, not before them.

Two deliberate refusals:

NO FABRICATED CONFIDENCE. Gemini returns a label and a box, not a calibrated probability. A
number invented here — 0.95 because the answer reads confident — would be compared against
YOLO's real 0.39 and win on a quantity that does not exist. `confidence` is therefore `None`,
always, and the comparison has to be made on what each model actually provides.

NO NEW CLASSES. Gemini is told the six canonical names and anything it returns outside them
becomes `unknown`. The taxonomy in `datasets/taco_yolo/data.yaml` stays authoritative, so a
candidate annotation can be merged into the existing dataset without a translation layer.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The detector's classes, in the detector's own id order. Read from the dataset that trained it
#: rather than restated here, so a future class change cannot leave this file silently stale.
DATA_YAML = REPO_ROOT / "datasets" / "taco_yolo" / "data.yaml"

#: Fallback used only when data.yaml is absent (it is gitignored, so a fresh clone has no copy).
#: Same names, same order as the committed `runs/experiments/.../dataset/data.yaml`.
_FALLBACK_CLASSES = [
    "ewaste",
    "food_waste",
    "metal_cans",
    "paper_waste",
    "plastic_bags",
    "plastic_bottles",
]

#: Returned when Gemini names something outside the taxonomy. Never a class id, never trainable.
UNKNOWN = "unknown"

PROMPT = """Analyze this image for physical waste objects.

Detect ALL clearly visible waste items that belong to the allowed waste taxonomy.

Allowed categories:
plastic_bottles
plastic_bags
paper_waste
metal_cans
food_waste
ewaste

Ignore normal household/background objects such as furniture, walls, doors, curtains, shelves, \
tables, appliances, clothing, and decorations unless they themselves are clearly waste.

For every waste object, return one bounding box and one canonical category.

Do not merge separate waste objects into one box.

Do not invent objects that are not visibly present.

If an object cannot confidently be assigned to one of the allowed categories, use unknown.

Bounding boxes must use [ymin, xmin, ymax, xmax] normalized from 0 to 1000.

Return ONLY a JSON object of the form:
{"detections": [{"class": "plastic_bottles", "label": "plastic bottle", \
"box_2d": [ymin, xmin, ymax, xmax]}]}

If there is no waste of any allowed category, return {"detections": []}."""


def canonical_classes() -> List[str]:
    """The six detector classes, ordered by class id, read from the dataset that defines them."""
    try:
        names: Dict[int, str] = {}
        in_names = False
        for line in DATA_YAML.read_text().splitlines():
            if line.startswith("names:"):
                in_names = True
                continue
            if in_names:
                match = re.match(r"\s+(\d+):\s*(\S+)", line)
                if not match:
                    break
                names[int(match.group(1))] = match.group(2)
        if names:
            return [names[i] for i in sorted(names)]
    except OSError:
        pass
    return list(_FALLBACK_CLASSES)


def class_id_of(class_name: str) -> Optional[int]:
    """The YOLO class id, so an approved candidate needs no second mapping to be trainable."""
    classes = canonical_classes()
    return classes.index(class_name) if class_name in classes else None


def _strip_code_fence(text: str) -> str:
    """Gemini wraps JSON in ```json fences often enough that parsing must expect it."""
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    return (fenced.group(1) if fenced else text).strip()


def parse_response(text: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """`(raw_detections, error)` — never raises, so a bad generation cannot 500 the endpoint."""
    if not text or not text.strip():
        return None, "Gemini returned an empty response."
    try:
        payload = json.loads(_strip_code_fence(text))
    except json.JSONDecodeError as exc:
        return None, f"Gemini response was not valid JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "Gemini response was not a JSON object."
    detections = payload.get("detections")
    if detections is None:
        return None, "Gemini response had no 'detections' key."
    if not isinstance(detections, list):
        return None, "Gemini 'detections' was not a list."
    return detections, None


def convert_box(
    box_2d: Any, width: int, height: int
) -> Tuple[Optional[List[float]], Optional[str]]:
    """`[ymin, xmin, ymax, xmax]` over 0..1000 -> `[x1, y1, x2, y2]` in pixels.

    Pixel xyxy is what `WasteSegregationDetection.bbox` already carries and what the photo
    overlay divides by `imageWidth`/`imageHeight`, so a Gemini box renders through the existing
    path with no frontend change. A box that fails validation is rejected and reported; it is
    never clamped into looking plausible.
    """
    if not isinstance(box_2d, (list, tuple)) or len(box_2d) != 4:
        return None, "box_2d must be a list of four numbers"
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box_2d)
    except (TypeError, ValueError):
        return None, "box_2d contained a non-numeric value"
    if not all(0 <= v <= 1000 for v in (ymin, xmin, ymax, xmax)):
        return None, "box_2d values outside the documented 0-1000 range"

    x1 = xmin / 1000.0 * width
    y1 = ymin / 1000.0 * height
    x2 = xmax / 1000.0 * width
    y2 = ymax / 1000.0 * height

    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        return None, "converted box is degenerate or outside the frame"
    return [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)], None


def normalise_detections(
    raw: List[Dict[str, Any]], width: int, height: int
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """`(accepted, rejected)`. A rejected entry keeps its reason: silence would hide parse drift."""
    classes = set(canonical_classes())
    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            rejected.append({"index": index, "reason": "detection was not an object", "raw": str(item)[:200]})
            continue
        name = str(item.get("class") or item.get("canonical_class") or "").strip()
        canonical = name if name in classes else UNKNOWN
        bbox, error = convert_box(item.get("box_2d"), width, height)
        if error:
            rejected.append({"index": index, "reason": error, "class": canonical, "raw": str(item.get("box_2d"))[:100]})
            continue
        accepted.append(
            {
                "canonical_class": canonical,
                "class_id": class_id_of(canonical),
                "label": str(item.get("label") or name or "")[:120] or None,
                "box_2d": [float(v) for v in item["box_2d"]],
                "bbox": bbox,
                # Gemini gives no calibrated score. Inventing one would make this column
                # comparable to YOLO's, which is exactly the mistake to avoid.
                "confidence": None,
            }
        )
    return accepted, rejected


def detect(content: bytes, filename: str, timeout: float = 90.0) -> Dict[str, Any]:
    """Run Gemini over one image and return the experimental contract. Never raises."""
    started = time.perf_counter()
    result: Dict[str, Any] = {
        "provider": "gemini",
        "model": None,
        "image_width": None,
        "image_height": None,
        "detections": [],
        "rejected": [],
        "latency_ms": None,
        "error": None,
    }

    try:
        from PIL import Image
        import io

        with Image.open(io.BytesIO(content)) as image:
            width, height = image.size
    except Exception as exc:  # noqa: BLE001 - a bad upload is a client error, not a crash
        result["error"] = f"Could not read the uploaded image: {type(exc).__name__}"
        result["latency_ms"] = round(1000 * (time.perf_counter() - started), 1)
        return result

    result["image_width"], result["image_height"] = width, height

    try:
        from config import settings

        result["model"] = settings.gemini_model
        if not settings.gemini_api_key:
            result["error"] = "GEMINI_API_KEY is not configured."
            result["latency_ms"] = round(1000 * (time.perf_counter() - started), 1)
            return result

        from langchain_core.messages import HumanMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            timeout=timeout,
        )
        encoded = base64.b64encode(content).decode()
        message = HumanMessage(
            content=[
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": f"data:image/jpeg;base64,{encoded}"},
            ]
        )
        response = llm.invoke([message])
        text = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:  # noqa: BLE001 - provider faults are reported, never raised
        logger.warning("gemini_detect_failed error=%s", type(exc).__name__)
        result["error"] = f"Gemini call failed: {type(exc).__name__}"
        result["latency_ms"] = round(1000 * (time.perf_counter() - started), 1)
        return result

    raw, error = parse_response(text)
    if error:
        result["error"] = error
        result["latency_ms"] = round(1000 * (time.perf_counter() - started), 1)
        return result

    accepted, rejected = normalise_detections(raw, width, height)
    result["detections"] = accepted
    result["rejected"] = rejected
    result["latency_ms"] = round(1000 * (time.perf_counter() - started), 1)
    return result


# --- training-candidate staging -------------------------------------------------------------
#
# Staged OUTSIDE the production dataset on purpose. A Gemini label is a proposal; merging it into
# `datasets/taco_yolo` before a human has seen it would put unverified boxes in the set the next
# model is measured against, and the damage would be invisible until the metrics moved.

CANDIDATE_ROOT = REPO_ROOT / "datasets" / "waste_user_candidates"


def save_candidate(content: bytes, filename: str, detection: Dict[str, Any]) -> Dict[str, Any]:
    """Stage one image + its Gemini annotations for human review. Returns a status dict."""
    digest = hashlib.sha256(content).hexdigest()

    for state in ("pending", "approved", "rejected"):
        for existing in sorted((CANDIDATE_ROOT / state).glob("*/metadata.json")):
            try:
                if json.loads(existing.read_text()).get("image_sha256") == digest:
                    return {
                        "saved": False,
                        "duplicate_of": existing.parent.name,
                        "status": state,
                        "reason": "an identical image is already staged",
                    }
            except (OSError, json.JSONDecodeError):
                continue

    pending = CANDIDATE_ROOT / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    capture_id = f"capture_{1 + len(list(pending.glob('capture_*'))):06d}"
    folder = pending / capture_id
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "image.jpg").write_bytes(content)
    # xywh here, per the candidate contract; the API response keeps xyxy to match production.
    (folder / "annotations.json").write_text(
        json.dumps(
            {
                "annotations": [
                    {
                        "class": d["canonical_class"],
                        "class_id": d["class_id"],
                        "bbox": [
                            d["bbox"][0],
                            d["bbox"][1],
                            round(d["bbox"][2] - d["bbox"][0], 1),
                            round(d["bbox"][3] - d["bbox"][1], 1),
                        ],
                    }
                    for d in detection.get("detections", [])
                    if d.get("canonical_class") != UNKNOWN
                ],
                "bbox_format": "xywh_pixels",
            },
            indent=2,
        )
    )
    (folder / "metadata.json").write_text(
        json.dumps(
            {
                "capture_id": capture_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_filename": filename,
                "image_sha256": digest,
                "image_width": detection.get("image_width"),
                "image_height": detection.get("image_height"),
                "annotation_provider": "gemini",
                "annotation_model": detection.get("model"),
                "review_status": "pending",
                "unknown_detections_excluded": sum(
                    1 for d in detection.get("detections", []) if d.get("canonical_class") == UNKNOWN
                ),
                "note": "Gemini pseudo-labels. NOT training data until a human approves them.",
            },
            indent=2,
        )
    )
    try:
        path = str(folder.relative_to(REPO_ROOT))
    except ValueError:  # staged outside the repo (a test tmpdir, a configured absolute root)
        path = str(folder)
    return {"saved": True, "capture_id": capture_id, "status": "pending", "path": path}
