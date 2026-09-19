"""Stage 1.5: is this box a valid waste-object localisation at all?

Between detection and classification, and deliberately before the crop is taken. A classifier
prediction is only meaningful once a valid localisation exists — asking "what material is this"
about a region containing a person produces an answer, because the network has eight waste classes
and a softmax that must sum to one across them. Measured on a real frame, the classifier called a
person crop `paper_waste` at 62%, above the 60% assertion threshold. Confidence cannot catch this,
so the check has to happen before the question is asked.

This exists because the gate that was supposed to do it cannot. `is_never_waste`
(`core/investigation.py`) matches the DETECTOR's class name against COCO names — person, dog, car.
The production detector is `models/waste_detector.pt`, which emits only its own six waste class
names, so the intersection is empty and the gate never fires. It was written for a COCO detector
and became inert when the waste detector was configured, silently.

Two independent checks, because they catch different things:

  1. DEGENERATE GEOMETRY — a box spanning almost the whole frame in both dimensions is a region,
     not an object. Measured against 1814 TACO ground-truth boxes, exactly one (0.06%) is that
     large, so this costs essentially nothing real. It is deliberately NOT a size-plausibility
     ceiling: 1.9% of real annotated litter covers more than 40% of its frame, and a bottle held
     up to the camera legitimately fills it. Rejecting large boxes as such would throw away the
     close-up shots this feature exists for.

  2. NON-WASTE SECOND OPINION — a general-purpose COCO detector is run over the same frame and any
     waste box sitting on a person, animal, vehicle or fixed furniture is refused. This restores
     what `is_never_waste` was for, using the one model that HAS a name for those things. The
     waste detector cannot report "this is a person"; yolov8n can.

A refused box is still reported. The detection is real — the detector did produce it — and hiding
it would make the response disagree with the model. What is withheld is the segregation claim.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.investigation import is_never_waste

logger = logging.getLogger("ecosentinel.waste.localisation")

#: A box covering at least this fraction of BOTH the frame's width and its height is treated as a
#: region rather than an object localisation. From the TACO label distribution (1814 boxes):
#: p99.5 width 0.904, p99.5 height 0.837, and 1 box (0.06%) clears 0.92 on both axes.
DEGENERATE_SPAN = 0.92

#: A COCO detection below this confidence is not a strong enough second opinion to veto a
#: detection the waste model made. Separate from, and deliberately higher than, the 0.25 the
#: detectors run at: a veto overrides another model, so it carries a higher bar than a report.
VETO_CONFIDENCE = 0.40

#: Overlap at which a waste box is treated as sitting ON a non-waste object. Either measure alone
#: is insufficient: IoU misses a small waste box drawn inside a large person (IoU 0.09 while the
#: box is entirely within them), and containment alone would veto a bottle that merely touches a
#: hand. Both are checked, in both directions.
VETO_IOU = 0.40
VETO_CONTAINMENT = 0.70


def _iou(a: Sequence[float], b: Sequence[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if overlap <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - overlap
    return overlap / union if union > 0 else 0.0


def _containment(inner: Sequence[float], outer: Sequence[float]) -> float:
    """Fraction of `inner`'s area that falls inside `outer`."""
    x1, y1 = max(inner[0], outer[0]), max(inner[1], outer[1])
    x2, y2 = min(inner[2], outer[2]), min(inner[3], outer[3])
    overlap = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(0.0, inner[2] - inner[0]) * max(0.0, inner[3] - inner[1])
    return overlap / area if area > 0 else 0.0


def non_waste_regions(content: bytes, filename: str) -> List[Tuple[str, float, List[float]]]:
    """Where the COCO detector sees something that cannot be litter.

    Returns `(class_name, confidence, [x1, y1, x2, y2])`. Never raises and never blocks an
    analysis: if the second opinion is unavailable, an empty list means "no veto evidence", and
    the geometry check still applies. A waste analysis must not fail because a secondary model
    could not load.

    One extra yolov8n pass, measured at ~20 ms on the benchmark in
    `runs/waste_detection/AB_TEST_REPORT.md` §9. It runs once per upload, not once per box.
    """
    try:
        from services.water_vision_service import build_report, get_water_vision_detector

        detector = get_water_vision_detector()
        if detector is None:
            return []
        report = build_report(detector, content, filename)
        if report.status != "ok":
            logger.info("non_waste_probe_unavailable status=%s", report.status)
            return []
    except Exception:  # noqa: BLE001 - the veto is advisory; its failure must not end the analysis
        logger.warning("non_waste_probe_failed", exc_info=True)
        return []

    return [
        (d.class_name, d.confidence, [d.bbox.x1, d.bbox.y1, d.bbox.x2, d.bbox.y2])
        for d in report.detections
        if is_never_waste(d.class_name) and d.confidence >= VETO_CONFIDENCE
    ]


def verify_localisation(
    bbox: Sequence[float],
    image_width: Optional[int],
    image_height: Optional[int],
    non_waste: Sequence[Tuple[str, float, List[float]]] = (),
) -> Optional[Dict[str, Any]]:
    """`None` when the box is a usable waste localisation, otherwise why it is not.

    The returned dict carries `reason` (a stable machine-readable code) and `detail` (the sentence
    shown to a reviewer, naming the measurement that refused it — a rejection that cannot be
    checked is not much better than a wrong label).
    """
    if image_width and image_height:
        span_x = (bbox[2] - bbox[0]) / image_width
        span_y = (bbox[3] - bbox[1]) / image_height
        if span_x >= DEGENERATE_SPAN and span_y >= DEGENERATE_SPAN:
            return {
                "reason": "degenerate_box",
                "detail": (
                    f"This box spans {span_x:.0%} of the frame's width and {span_y:.0%} of its "
                    "height, which is a region rather than an object, so no material is asserted."
                ),
            }

    for class_name, confidence, box in non_waste:
        if confidence < VETO_CONFIDENCE:
            # Re-checked here and not only in `non_waste_regions`, because this is where the
            # decision is made. A caller assembling the list some other way — a test, a future
            # second opinion — must not be able to lower the bar for overruling another model.
            continue
        overlap = _iou(bbox, box)
        waste_in_object = _containment(bbox, box)
        object_in_waste = _containment(box, bbox)
        if overlap >= VETO_IOU or waste_in_object >= VETO_CONTAINMENT or object_in_waste >= VETO_CONTAINMENT:
            return {
                "reason": "non_waste_object",
                "detail": (
                    f"This region is a '{class_name}' ({confidence:.0%} confidence from the "
                    f"general-purpose detector, IoU {overlap:.2f}), which cannot be waste, so no "
                    "material is asserted."
                ),
            }

    return None
