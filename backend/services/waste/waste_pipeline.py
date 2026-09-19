"""Two-stage waste analysis: detect objects, then classify each one.

    image -> YOLO detection -> crop each box -> classifier -> segregation category

The two stages are kept separate because they answer different questions and fail differently. The
detector says *where* something is; the classifier says *what* it is.

When the detector itself emits a waste-taxonomy class (the TACO-trained `waste_detector.pt`),
that class is the label. Measured on the held-out TACO test split, detector authority is four
times more often correct than letting the classifier overrule it. The classifier still runs:
its answer is kept as `candidate` when the two disagree, so a reviewer can see the conflict.

A COCO detector (bottle, cup, vase) is unchanged: those names are not waste classes, so the
classifier remains the only source of a segregation label. That is why the second stage exists.

What the pipeline refuses to do:

  - report a detection the detector did not make
  - assert a segregation category below the configured classification threshold
  - claim the classifier is available when no trained weights exist
  - let the environmental interpretation masquerade as a model output

The last point has its own field. `environmental_note` is an application-level heuristic read from
configuration — "plastic bags are persistent" is a policy statement, not something the network
predicted, and the response keeps the two apart.
"""

import io
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.investigation import is_never_waste
from services.waste.waste_classifier import ClassifierUnavailable, get_waste_classifier

logger = logging.getLogger("ecosentinel.waste.pipeline")

#: Boxes smaller than this are not worth cropping: below roughly this size the crop carries too
#: few pixels for the classifier to do anything but guess.
MIN_CROP_PIXELS = 24

#: Two boxes overlapping this much are treated as one object, whatever the detector called them.
#: YOLO applies NMS per class, so a single bottle can survive twice — once as "bottle" and once as
#: "vase" over nearly identical pixels. Left alone that turns one bottle into "2 objects", and the
#: count is the number the report and the language model both build on.
DUPLICATE_IOU = 0.7


def _iou(a: List[float], b: List[float]) -> float:
    """Intersection over union of two [x1, y1, x2, y2] boxes."""
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if overlap <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - overlap
    return overlap / union if union > 0 else 0.0


def _deduplicate(detections: List[Any]) -> List[Tuple[Any, List[float], List[str]]]:
    """Collapse boxes that cover the same object under different class names.

    Returns `(detection, box, also_detected_as)` per surviving object. The highest-confidence
    detection wins and the suppressed class names travel with it rather than being discarded —
    "detected as bottle, also as vase" is a useful admission of the detector's uncertainty, and
    dropping it silently would hide why the count changed.

    The absorbed names are returned rather than stashed on the detection or in module state: this
    runs in FastAPI's threadpool, so two uploads can be in here at once.
    """
    kept: List[Tuple[Any, List[float], List[str]]] = []
    for detection in sorted(detections, key=lambda d: d.confidence, reverse=True):
        box = [detection.bbox.x1, detection.bbox.y1, detection.bbox.x2, detection.bbox.y2]
        for _, existing_box, absorbed in kept:
            if _iou(box, existing_box) >= DUPLICATE_IOU:
                absorbed.append(detection.class_name)
                break
        else:
            kept.append((detection, box, []))
    return kept


def _supports_capture(classifier: Any) -> bool:
    """Does this classifier accept the diagnostic `capture` argument?

    Asked by inspection rather than by catching TypeError, which would also swallow a genuine
    TypeError raised inside `classify` and turn a real fault into a silent fallback.
    """
    import inspect

    try:
        return "capture" in inspect.signature(classifier.classify).parameters
    except (TypeError, ValueError):  # builtins and C callables have no introspectable signature
        return False


def _crop(image, bbox: List[float], padding: float = 0.06):
    """Crop a detection with a little context around it.

    A box drawn tight to an object loses the edges the classifier uses to tell a bag from a bottle,
    so a small margin is added and then clamped to the frame.
    """
    width, height = image.size
    x1, y1, x2, y2 = bbox
    pad_x, pad_y = (x2 - x1) * padding, (y2 - y1) * padding
    box = (
        max(0, int(x1 - pad_x)),
        max(0, int(y1 - pad_y)),
        min(width, int(x2 + pad_x)),
        min(height, int(y2 + pad_y)),
    )
    if box[2] - box[0] < MIN_CROP_PIXELS or box[3] - box[1] < MIN_CROP_PIXELS:
        return None
    return image.crop(box)


def analyze_waste(
    content: bytes,
    filename: str = "image.jpg",
    detector: Any = None,
    classifier: Any = None,
    observer: Any = None,
    explain: bool = False,
) -> Dict[str, Any]:
    """Run both stages over one image. Never raises.

    Returns detections with their classification and segregation, plus a summary that counts
    `uncertain` separately — collapsing uncertain results into one bucket or the other would hide
    exactly the cases a reviewer needs to see.

    `observer`, when given, is called with the real intermediate values of this exact run — the
    source image, each raw detection, each crop, the tensor the classifier consumed and the record
    that came back. It exists so debugging watches the production path instead of a parallel
    re-implementation of it, which would be capable of disagreeing with the thing under diagnosis.

    `explain` adds a Grad-CAM attribution per classified crop. Off by default: it costs a backward
    pass per object and explains a decision that has already been made, so it must not sit on the
    critical path of every upload.
    """
    from services.water_vision_service import build_report, get_waste_pipeline_detector

    try:
        from PIL import Image
    except ImportError:
        return _empty("Pillow is required for waste analysis.", "unavailable")

    detector = detector or get_waste_pipeline_detector()
    vision = build_report(detector, content, filename)

    if vision.status != "ok":
        # The detector did not run. Nothing can be said about objects in this image, and saying
        # "no waste found" here would be a claim the system has not earned.
        return _empty(vision.message or "Visual detection did not run.", vision.status, model=vision.model)

    try:
        image = Image.open(io.BytesIO(content)).convert("RGB")
    except Exception as exc:  # noqa: BLE001
        return _empty(f"The image could not be decoded ({exc.__class__.__name__}).", "unavailable")

    classifier = classifier or get_waste_classifier()
    classifier_ready = classifier.is_configured()

    unique = _deduplicate(vision.detections)
    suppressed = len(vision.detections) - len(unique)

    if observer is not None:
        observer.on_image(image, vision)

    detections: List[Dict[str, Any]] = []
    for index, (detection, bbox, also_as) in enumerate(unique, start=1):
        record: Dict[str, Any] = {
            "id": f"WASTE-DET-{index:03d}",
            "bbox": [round(v, 1) for v in bbox],
            # Exactly what the detector reported. Never remapped to a waste label.
            "detected_object": detection.class_name,
            "detection_confidence": round(detection.confidence, 4),
            "also_detected_as": sorted(set(also_as)) or None,
        }

        crop = _crop(image, bbox)
        capture: Dict[str, Any] = {}
        if crop is None:
            record.update(
                classification=None, classification_confidence=None,
                segregation="uncertain", status="needs_review",
                message="The detected region is too small to classify reliably.",
            )
        elif not classifier_ready:
            record.update(
                classification=None, classification_confidence=None,
                segregation="uncertain", status="unavailable",
                message="No trained waste classifier is available, so no segregation is asserted.",
            )
        elif observer is not None and _supports_capture(classifier):
            record.update(classifier.classify(crop, capture=capture))
        else:
            # `capture` is an OPTIONAL extension of the classifier interface, passed only when
            # something is observing and the implementation accepts it. A classifier that predates
            # it — a stub, a different backend — keeps working, and debugging one degrades to
            # having no tensor rather than to a TypeError mid-analysis.
            record.update(classifier.classify(crop))

        if record.get("classification") and is_never_waste(detection.class_name):
            # The classifier cannot answer "not waste" — it has eight waste classes and a softmax
            # that must sum to one across them. So a confident label on a dog or a car is an
            # artefact of forced choice, not a finding. The guess is kept visible as a candidate;
            # the segregation claim is withheld.
            record.update(
                candidate=record["classification"],
                classification=None,
                segregation="uncertain",
                status="needs_review",
                handling=None,
                display=None,
                label_source=None,
                message=(
                    f"The detector identified this as '{detection.class_name}', which is not one "
                    "of the waste classes, so no segregation is asserted."
                ),
            )
        else:
            _apply_detector_authority(record, detection.class_name, classifier)

        if record.get("classification"):
            mapping = classifier.segregation_for(record["classification"])
            # Kept in its own field: this is a configured policy statement, not a prediction.
            record["environmental_note"] = _handling_note(classifier, mapping.get("handling"))

        # Attribution runs on the crop the classifier actually saw, and only where there is a
        # classifier answer to explain. An unavailable attribution is reported as unavailable —
        # there is deliberately no fallback image.
        if explain and crop is not None and classifier_ready:
            from services.waste.waste_xai import safe_explain

            record["xai"] = safe_explain(classifier, crop)

        if observer is not None:
            observer.on_detection(record, detection, bbox, crop, capture, classifier)
        detections.append(record)

    summary = {
        "total_objects": len(detections),
        # How many boxes were folded into another. Reported rather than hidden: the difference
        # between "8 detected" and "8 objects" is the whole question when counting litter.
        "duplicate_boxes_merged": suppressed,
        "biodegradable": sum(1 for d in detections if d.get("segregation") == "biodegradable"),
        "non_biodegradable": sum(1 for d in detections if d.get("segregation") == "non_biodegradable"),
        # Counted separately and never folded into either category.
        "uncertain": sum(1 for d in detections if d.get("segregation") == "uncertain"),
        # Objects the detector identified as something that cannot be waste at all.
        "non_waste_objects": sum(1 for d in detections if is_never_waste(d["detected_object"])),
    }

    return {
        "status": "ok",
        "model": vision.model,
        "classifier_available": classifier_ready,
        "image_width": vision.image_width,
        "image_height": vision.image_height,
        "detections": detections,
        "summary": summary,
        "message": None if classifier_ready else (
            "No trained classifier is available. Objects the detector named with a waste class "
            "are segregated from that class; everything else is reported as uncertain."
        ),
    }


def _taxonomy_classes(classifier: Any) -> Dict[str, Any]:
    return (getattr(classifier, "config", None) or {}).get("classes") or {}


def _assertion_threshold(classifier: Any) -> float:
    """The confidence any model must clear before its label is ASSERTED rather than suggested.

    Deliberately the same number for both stages (`classification_confidence`, 0.60). It is not a
    property of the classifier — it is the project's bar for turning a prediction into a claim, and
    a detector's label is no less of a claim than a classifier's. Two different bars would mean the
    same object could be `confirmed` or `needs_review` depending only on which model happened to
    speak, which is not a distinction a reviewer can act on.
    """
    try:
        return float((classifier.config.get("thresholds") or {})["classification_confidence"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return 0.60


def _apply_detector_authority(record: Dict[str, Any], detector_class: str, classifier: Any) -> None:
    """Use the detector's class when it is already a waste-taxonomy label.

    COCO names never match, so this is a no-op for a general-purpose detector. For the TACO
    waste detector it is the measured win: on the held-out split the detector was right 22 times
    in 42 disagreements, the classifier 6.

    That win is real, but it is a statement about which model to BELIEVE when both have spoken
    confidently — not a licence to assert a category the detector itself is unsure of. This path
    used to set `status="confirmed"` from the existence of a category mapping alone, never reading
    the detector's own confidence. A person in a frame, detected as `paper_waste` at 0.395 with the
    classifier below its threshold at 0.567, was returned as a *confirmed* `biodegradable` object
    whose own message read "the classifier did not confirm a label". Both models were unsure and
    the response said neither.

    So the detector's class is still preferred, and it is only ASSERTED when the detector clears
    the assertion bar. Below it the label is still shown — as a candidate, with the segregation
    claim withheld.
    """
    mapping = _taxonomy_classes(classifier).get(detector_class)
    if not mapping:
        if record.get("classification"):
            record["label_source"] = "classifier"
        return

    classifier_class = record.get("classification")
    if classifier_class == detector_class:
        record["label_source"] = "classifier"
        return

    detection_confidence = float(record.get("detection_confidence") or 0.0)
    threshold = _assertion_threshold(classifier)

    if detection_confidence < threshold:
        # The detector's class is still the better guess — that is what the held-out measurement
        # says, and a disagreeing classifier does not become right by being loud. But no model has
        # cleared the assertion bar FOR THIS LABEL, so it is offered as a candidate and the
        # segregation claim is withheld.
        #
        # Handing the label to the classifier instead was tried and is worse: on `paper.jpg` the
        # classifier says `ewaste` at 85% against the detector's `paper_waste` at 53%, and
        # asserting `ewaste` would route paper to hazardous handling with a confident-looking
        # number on it. Confidence is not accuracy, and these are exactly the disagreements the
        # classifier loses 6-22.
        detail = (
            f"and the classifier disagreed with '{classifier_class}' "
            f"({float(record.get('classification_confidence') or 0.0):.0%})"
            if classifier_class
            else "and the classifier did not confirm a label"
        )
        record.update(
            candidate=detector_class,
            classification=None,
            segregation="uncertain",
            status="needs_review",
            handling=None,
            display=None,
            label_source=None,
            environmental_note=None,
            message=(
                f"The detector labelled this '{detector_class}' at {detection_confidence:.0%}, "
                f"below the {threshold:.0%} threshold, {detail}. The detector's class is the "
                "better guess but no segregation is asserted."
            ),
        )
        return

    if classifier_class:
        record["candidate"] = classifier_class
        record["message"] = (
            f"The detector labelled this '{detector_class}' at {detection_confidence:.0%} and the "
            f"classifier labelled it '{classifier_class}'; the detector's class is used."
        )
    elif record.get("status") == "unavailable":
        record["message"] = (
            f"No trained classifier is available; segregation follows the detector class "
            f"'{detector_class}' ({detection_confidence:.0%})."
        )
    else:
        record["message"] = (
            f"Segregation follows the detector class '{detector_class}' ({detection_confidence:.0%}) "
            "because the classifier did not confirm a label."
        )

    record.update(
        classification=detector_class,
        segregation=mapping.get("category") or "uncertain",
        handling=mapping.get("handling"),
        display=mapping.get("display", detector_class),
        status="confirmed" if mapping.get("category") else "needs_review",
        label_source="detector",
        environmental_note=_handling_note(classifier, mapping.get("handling")),
    )


def _handling_note(classifier: Any, handling: Optional[str]) -> Optional[str]:
    if not handling:
        return None
    return (classifier.config.get("handling_notes") or {}).get(handling)


def _empty(message: str, status: str, model: Optional[str] = None) -> Dict[str, Any]:
    return {
        "status": status,
        "model": model,
        "classifier_available": False,
        "image_width": None,
        "image_height": None,
        "detections": [],
        "summary": {
            "total_objects": 0, "biodegradable": 0, "non_biodegradable": 0,
            "uncertain": 0, "duplicate_boxes_merged": 0, "non_waste_objects": 0,
        },
        "message": message,
    }


def pipeline_status() -> Dict[str, Any]:
    """Health of both stages, reported separately — either can be missing on its own."""
    from services.water_vision_service import waste_detector_status as detector_status

    try:
        classifier = get_waste_classifier().status()
    except ClassifierUnavailable as exc:
        classifier = {"configured": False, "available": False, "detail": exc.message, "classes": []}
    return {"detector": detector_status(), "classifier": classifier}
