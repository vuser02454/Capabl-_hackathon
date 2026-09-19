"""Clicked-frame investigation: WHERE the visible pollution is, WHY it matters, WHAT to do next.

Built entirely from what a detector actually returned. There is no path through this module that
invents a detection, a reason, a coordinate or a date — which matters more here than anywhere
else in the system, because a photograph is the most persuasive and least measurable evidence
EcoSentinel handles. An image can show floating plastic; it can never establish chemical
contamination, and the wording enforces that difference:

    visible pollution / visible waste accumulation      ✓ an image can support this
    water contamination / the river is deteriorating    ✗ needs measurement or history

Every reason carries a `type` saying how strongly the evidence backs it:

    OBSERVED    the detector located it in this frame
    INFERRED    follows from several observations in this frame
    HYPOTHESIS  suggested by context; not established
    UNKNOWN     a data gap — stated so it cannot be mistaken for a finding

Reasons and actions are capped at five and **never padded** to reach it. Three supported reasons
means three.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional, Sequence

from core.recovery import TIMELINE_BANDS
from schemas import (
    DataAvailability,
    EscalationRisk,
    FrameDetection,
    FrameInvestigation,
    FrameAction,
    InvestigationGeotag,
    InvestigationReason,
    RecoveryTimeline,
    WaterAgentResult,
    WaterVisionReport,
)

MAX_REASONS = 5
MAX_ACTIONS = 5

#: Class names that actually indicate visible pollution. A general-purpose detector (COCO YOLOv8n)
#: reports things like `person`, `car` and `boat`; calling those "visible pollution objects"
#: because they happened to appear in a water photo is exactly the misrepresentation this system
#: exists to avoid. Matching is on substrings, so a waste-trained model's `plastic_bottle`,
#: `floating_trash` or `litter_bag` are all recognised without needing an exhaustive list.
POLLUTION_CLASS_HINTS = (
    "plastic", "bottle", "garbage", "trash", "waste", "litter", "debris", "rubbish",
    "styrofoam", "polythene", "can", "cup", "bag", "wrapper", "foam", "tyre", "tire",
)


def is_pollution_class(class_name: str) -> bool:
    """Does this class name indicate visible pollution, rather than any object at all?"""
    lowered = class_name.replace("_", " ").lower()
    return any(hint in lowered for hint in POLLUTION_CLASS_HINTS)


#: Classes that cannot be litter, whatever a classifier claims about the pixels inside the box.
#:
#: This is an EXCLUSION list, not the inverse of POLLUTION_CLASS_HINTS, and the difference matters.
#: A COCO detector routinely calls a plastic bottle a `vase` or a `teddy bear`; refusing everything
#: outside the hint list would discard those, and the waste classifier labels them correctly. So
#: the rule is narrow: refuse only where the detector's own class rules waste out.
#:
#: The waste classifier has eight waste classes and no way to answer "not waste" — its softmax must
#: distribute 1.0 across bottles, bags and leaves whatever it is shown. Measured on TACO images it
#: called a `dog` wood_waste at 84% and a `car` food_waste at 64%, both above the 60% threshold.
#: Confidence cannot catch this, because the model was never given the option of abstaining.
#:
#: A dumped car or a broken bench is genuinely litter in the ordinary sense, but neither is one of
#: the eight classes, so any confident label on them is wrong regardless. The detection is still
#: reported — only the segregation claim is withheld.
NEVER_WASTE_CLASSES = frozenset({
    # living things
    "person", "dog", "cat", "bird", "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe",
    # vehicles
    "car", "truck", "bus", "train", "motorcycle", "bicycle", "airplane", "boat",
    # fixed street and indoor furniture
    "bench", "traffic light", "fire hydrant", "stop sign", "parking meter", "bed", "toilet",
})


def is_never_waste(class_name: str) -> bool:
    """True when the detector's own class rules out this object being one of the waste classes."""
    return class_name.replace("_", " ").strip().lower() in NEVER_WASTE_CLASSES


def semantic_category_for(class_name: str) -> str:
    """One raw detector class -> this project's semantic interpretation of it.

    Built on the two predicates above so there is exactly ONE taxonomy in the system. There used
    to be effectively two: `POST /api/water/scan-frame` filtered by `is_pollution_class` while the
    Water Agent's risk blend counted every detection, so the same river photo was reported as
    "no visible pollution" by one endpoint and "6 pollution objects, risk +0.08" by the other.

    The raw class is never replaced by this value — they are carried in separate fields, because
    "the detector said bottle" and "we read that as litter" are different claims.
    """
    if is_pollution_class(class_name):
        return "visible_surface_litter"
    if is_never_waste(class_name):
        return "non_pollution_object"
    return "unclassified_object"


def effective_semantic_category(detection) -> str:
    """A detection's category, derived from its class name when the field was never set.

    `semantic_category` defaults to `unclassified_object`, which is also a legitimate value, so a
    detection built directly (a test fixture, a detector predating the field) cannot be told apart
    from one the taxonomy genuinely could not place. Re-deriving in that case is idempotent —
    `semantic_category_for` returns `unclassified_object` for an unplaceable class anyway — and it
    means no score depends on whether an earlier caller remembered to categorise.
    """
    stored = getattr(detection, "semantic_category", None)
    if stored and stored != "unclassified_object":
        return stored
    return semantic_category_for(detection.class_name)


#: Labels for where a box sits in the frame. Position in an IMAGE, never a position on the ground.
VERTICAL = ((0.33, "upper"), (0.66, "central"), (1.01, "lower"))
HORIZONTAL = ((0.33, "left"), (0.66, "centre"), (1.01, "right"))


def image_region(bbox: Sequence[float], width: Optional[int], height: Optional[int]) -> Optional[str]:
    """Describe where a box sits within the frame, e.g. "lower-left foreground".

    Returns None when the frame size is unknown: a pixel box means nothing without the frame it
    was measured against, and guessing a region from an unknown canvas would be fabrication.
    """
    if not width or not height or len(bbox) < 4:
        return None
    cx = ((bbox[0] + bbox[2]) / 2) / width
    cy = ((bbox[1] + bbox[3]) / 2) / height
    if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
        return None

    vertical = next(label for bound, label in VERTICAL if cy < bound)
    horizontal = next(label for bound, label in HORIZONTAL if cx < bound)
    region = vertical if horizontal == "centre" and vertical == "central" else f"{vertical}-{horizontal}"
    # Objects low in the frame are nearer the camera; that is a property of the image, not of the
    # scene, so it is only ever phrased as foreground/background.
    depth = " foreground" if cy >= 0.66 else " background" if cy < 0.33 else ""
    return f"{region}{depth}".replace("central-centre", "central")


def build_detections(vision: WaterVisionReport) -> List[FrameDetection]:
    """Vision output -> identified, positioned detections. Only what the model returned."""
    detections: List[FrameDetection] = []
    for index, detection in enumerate(vision.detections, start=1):
        box = [detection.bbox.x1, detection.bbox.y1, detection.bbox.x2, detection.bbox.y2]
        relative: List[float] = []
        if vision.image_width and vision.image_height:
            relative = [
                max(0.0, min(1.0, box[0] / vision.image_width)),
                max(0.0, min(1.0, box[1] / vision.image_height)),
                max(0.0, min(1.0, box[2] / vision.image_width)),
                max(0.0, min(1.0, box[3] / vision.image_height)),
            ]
        detections.append(
            FrameDetection(
                detection_id=f"IMG-DET-{index:03d}",
                class_name=detection.class_name,
                confidence=detection.confidence,
                bbox=box,
                bbox_relative=relative,
                image_region=image_region(box, vision.image_width, vision.image_height),
            )
        )
    return detections


def build_reasons(
    detections: Sequence[FrameDetection],
    vision: WaterVisionReport,
    water: Optional[WaterAgentResult],
    observed_at: Optional[datetime],
) -> List[InvestigationReason]:
    """Why this frame is a concern. Capped at five, never padded to reach it."""
    source = f"Selected frame ({vision.model})" if vision.model else "Selected frame"
    seen: List[tuple] = []      # OBSERVED — what the detector located
    inferred: List[tuple] = []  # INFERRED — what follows from those observations
    gaps: List[tuple] = []      # UNKNOWN  — what this frame cannot settle

    def add(text: str, kind: str, evidence: List[str], confidence: Optional[float] = None) -> None:
        # Kept in three buckets so the cap drops the least informative reason rather than whichever
        # happened to be added last. Gaps always survive: a frame with several detected classes
        # would otherwise fill all five slots with confident observations and push
        # "an image cannot show chemical contamination" off the page — leaving only the
        # certain-sounding reasons visible, which is the opposite of the intent.
        bucket = gaps if kind == "UNKNOWN" else inferred if kind == "INFERRED" else seen
        bucket.append((text, kind, evidence, confidence))

    if detections:
        by_class: dict = {}
        for detection in detections:
            by_class.setdefault(detection.class_name, []).append(detection)

        # 1. What was actually seen, per class. Directly observed.
        for class_name, group in sorted(by_class.items(), key=lambda item: -len(item[1])):
            label = class_name.replace("_", " ")
            count = len(group)
            where = ", ".join(filter(None, (d.image_region for d in group[:3])))
            placement = f" ({where})" if where else ""
            pollution = is_pollution_class(class_name)
            add(
                (
                    f"Visible {label} detected in the selected frame: {count} object"
                    f"{'s' if count != 1 else ''}{placement}."
                )
                if pollution
                else (
                    f"The detector reported {count} {label} object{'s' if count != 1 else ''}"
                    f"{placement}. This class does not indicate pollution and is listed for "
                    "completeness."
                ),
                "OBSERVED",
                [d.detection_id for d in group],
                max(d.confidence for d in group),
            )

        # 2. Several objects clustered low in the frame reads as accumulation — an inference from
        #    the observations above, not a separate sighting.
        clustered = [d for d in detections if d.image_region and "lower" in d.image_region]
        if len(clustered) >= 2:
            add(
                "Multiple waste objects are concentrated in the same part of the frame, consistent "
                "with visible accumulation rather than isolated litter.",
                "INFERRED",
                [d.detection_id for d in clustered],
            )

    # 3. What the image cannot settle. Stated as a gap so it cannot read as a finding.
    if water is not None and not water.is_mock and water.measurements:
        missing = [m.label for m in water.measurements if m.value is None]
        if missing:
            add(
                f"No {', '.join(missing[:3])} measurement accompanies this frame, so chemical or "
                "microbiological contamination cannot be assessed from the image alone.",
                "UNKNOWN",
                ["DATA-001"],
            )
    else:
        add(
            "This frame has no accompanying water measurements, so it supports statements about "
            "visible pollution only - not about chemical or microbiological contamination.",
            "UNKNOWN",
            ["DATA-001"],
        )

    # 4. No historical comparison exists for a single frame.
    add(
        "No earlier frames of this location are available for comparison, so whether the visible "
        "pollution is increasing or decreasing cannot be determined.",
        "UNKNOWN",
        ["DATA-002"],
    )

    # Order: the strongest observation, then what it implies, then the rest of what was seen,
    # then the gaps. Observations lead because they are what the user can verify in the image;
    # the inference sits high because a synthesis of several detections says more than the third
    # per-class line; the gaps always close and are never the ones dropped.
    room = max(0, MAX_REASONS - len(gaps))
    ordered = (seen[:1] + inferred + seen[1:])[:room] + gaps
    return [
        InvestigationReason(
            reason_id=f"WHY-{index:03d}",
            text=text,
            type=kind,  # type: ignore[arg-type]
            evidence_ids=evidence,
            source=source if evidence and evidence[0].startswith("IMG-DET") else "EcoSentinel analysis",
            confidence=confidence,
            observed_at=observed_at,
        )
        for index, (text, kind, evidence, confidence) in enumerate(ordered[:MAX_REASONS], start=1)
    ]


def build_actions(
    detections: Sequence[FrameDetection], reasons: Sequence[InvestigationReason]
) -> List[FrameAction]:
    """What to do next. Derived from what was detected — never generic advice."""
    relevant = [d for d in detections if is_pollution_class(d.class_name)]
    if not relevant:
        # Nothing pollution-related was found, so there is nothing to recommend removing. Offering
        # "remove the accumulated waste" for a detected person would be absurd and misleading.
        return []

    evidence = [d.detection_id for d in relevant]
    detections = relevant
    actions = [
        FrameAction(
            action_id="ACTION-001",
            action="Remove the visible accumulated waste from the affected area.",
            rationale=f"{len(detections)} waste object(s) were located in the selected frame.",
            priority="high",
            expected_effect="Reduces visible solid-waste accumulation and prevents further downstream transport.",
            timeframe=TIMELINE_BANDS["immediate"],
            timeline_category="immediate",
            evidence_ids=evidence,
        ),
        FrameAction(
            action_id="ACTION-002",
            action="Identify how waste is entering the water at this point.",
            rationale="Removal alone does not stop the accumulation from returning.",
            priority="high",
            expected_effect="Locates the entry route so the accumulation can be prevented rather than repeatedly cleared.",
            timeframe=TIMELINE_BANDS["short_term"],
            timeline_category="short_term",
            evidence_ids=evidence,
        ),
        FrameAction(
            action_id="ACTION-003",
            action="Collect water-quality measurements at this location.",
            rationale="The image shows visible pollution but cannot establish chemical or microbiological contamination.",
            priority="medium",
            expected_effect="Replaces an unknown with a measurement, allowing a contamination claim to be made or ruled out.",
            timeframe=TIMELINE_BANDS["short_term"],
            timeline_category="short_term",
            evidence_ids=["DATA-001"],
        ),
        FrameAction(
            action_id="ACTION-005",
            action="Record this location so the accumulation can be scheduled for removal and re-checked.",
            rationale="A one-off observation achieves nothing unless it reaches whoever can act on it.",
            priority="medium",
            expected_effect="Turns a single observation into a tracked site with a follow-up check.",
            timeframe=TIMELINE_BANDS["short_term"],
            timeline_category="short_term",
            evidence_ids=evidence,
        ),
        FrameAction(
            action_id="ACTION-004",
            action="Re-photograph this location across several time windows.",
            rationale="A single frame cannot distinguish a persistent problem from a transient one.",
            priority="medium",
            expected_effect="Establishes a baseline so any future change can be described as a trend.",
            timeframe=TIMELINE_BANDS["medium_term"],
            timeline_category="medium_term",
            evidence_ids=["DATA-002"],
        ),
    ]
    return actions[:MAX_ACTIONS]


#: How an untreated visible-waste accumulation can plausibly develop. Each entry is conditional
#: and tied to something the frame actually shows — none of them asserts an outcome, because a
#: photograph cannot establish what happens next. Ordered by how directly the frame supports them.
ESCALATION_TEMPLATES = (
    (
        "If left in place, floating and shoreline waste can be carried downstream by current or "
        "rainfall, spreading the affected area beyond the point observed here.",
        "short_term",
    ),
    (
        "Accumulated waste tends to attract further dumping once a site is visibly used for it, so "
        "the volume at this location could grow rather than stay constant.",
        "short_term",
    ),
    (
        "Plastic left exposed to sunlight and abrasion fragments over time, which makes later "
        "removal substantially harder than clearing intact items now.",
        "medium_term",
    ),
    (
        "Waste accumulating at a constriction or inlet can impede flow, which risks localised "
        "pooling and, during heavy rainfall, backing up.",
        "medium_term",
    ),
    (
        "Prolonged accumulation raises the likelihood of associated water-quality effects that this "
        "image cannot measure, so the uncertainty about contamination grows the longer it remains.",
        "long_term",
    ),
)

MAX_ESCALATION_RISKS = 5


def build_escalation_risks(detections: Sequence[FrameDetection]) -> List[EscalationRisk]:
    """How this could get worse if nothing is done. Projections, never predictions.

    Only produced when pollution-relevant objects were actually detected: projecting the spread of
    waste that nobody found would be inventing both the problem and its future.
    """
    relevant = [d for d in detections if is_pollution_class(d.class_name)]
    if not relevant:
        return []

    evidence = [d.detection_id for d in relevant]
    return [
        EscalationRisk(
            risk_id=f"WORSE-{index:03d}",
            text=text,
            evidence_ids=evidence,
            horizon=horizon,  # type: ignore[arg-type]
        )
        for index, (text, horizon) in enumerate(ESCALATION_TEMPLATES[:MAX_ESCALATION_RISKS], start=1)
    ]


def build_timeline(has_history: bool) -> RecoveryTimeline:
    timeline = RecoveryTimeline()
    if not has_history:
        timeline = timeline.model_copy(
            update={
                "trend_note": (
                    "Reliable ecological recovery trend cannot currently be estimated from the "
                    "available evidence."
                )
            }
        )
    return timeline


def _summary(detections: Sequence[FrameDetection], vision: WaterVisionReport) -> str:
    """One honest sentence. Never claims contamination, and never calls any object pollution."""
    if vision.status != "ok":
        return (
            "Visual detection did not run for this frame, so no statement can be made about "
            "visible pollution. "
            + (vision.message or "")
        ).strip()
    if not detections:
        return (
            "No supported visible pollution objects were detected in the selected frame. This does "
            "not mean no pollution is present - it means the configured model reported nothing, "
            "and an image cannot show contamination in any case."
        )

    pollution = [d for d in detections if is_pollution_class(d.class_name)]
    other = [d for d in detections if d not in pollution]
    other_classes = sorted({d.class_name.replace("_", " ") for d in other})

    if not pollution:
        # The detector found things, none of which indicate pollution. Saying so is the whole point:
        # a general-purpose model finding a person in a water photo is not a pollution finding.
        return (
            "No supported visible pollution objects were detected in the selected frame. The "
            f"configured model reported {len(other)} other object(s) ({', '.join(other_classes)}), "
            "which do not indicate pollution."
        )

    classes = sorted({d.class_name.replace("_", " ") for d in pollution})
    text = (
        f"{len(pollution)} visible pollution object(s) were detected in the selected frame "
        f"({', '.join(classes)}). This frame supports statements about visible pollution only."
    )
    if other:
        text += f" {len(other)} other object(s) were also detected ({', '.join(other_classes)})."
    return text


def build_investigation(
    vision: WaterVisionReport,
    water: Optional[WaterAgentResult] = None,
    geotag: Optional[InvestigationGeotag] = None,
    captured_at: Optional[datetime] = None,
    decision: Optional[object] = None,
) -> FrameInvestigation:
    """Assemble the clicked-frame report. Never raises.

    When `decision` is supplied (the LangGraph path), the deterministic engine has already
    normalised the evidence, detected the problems, ranked them and judged sufficiency — so its
    data-gap findings are folded in here rather than being worked out a second time. Nothing that
    the decision owns is recomputed; this only adds the frame view of it.
    """
    moment = captured_at or datetime.now(timezone.utc)
    detections = build_detections(vision) if vision.status == "ok" else []
    reasons = build_reasons(detections, vision, water, moment) if vision.status == "ok" else []
    actions = build_actions(detections, reasons)
    escalation = build_escalation_risks(detections)

    if decision is not None and reasons:
        reasons = _merge_decision_gaps(reasons, decision, moment)

    # Measurements only count as available when a real reading came back — a report with every
    # value missing is not measurement evidence, it is a gap wearing a measurement's shape.
    has_measurements = bool(
        water is not None and any(m.value is not None for m in (water.measurements or []))
    )
    availability = DataAvailability(
        visual=bool(detections),
        water_measurements=has_measurements,
        detail=(
            None
            if has_measurements
            else "No water measurements accompany this frame; the investigation rests on visual "
            "evidence alone and cannot address chemical or microbiological contamination."
        ),
    )

    return FrameInvestigation(
        investigation_id=f"INV-{uuid.uuid4().hex[:10]}",
        data_availability=availability,
        summary=_summary(detections, vision),
        detections_available=bool(detections),
        detection_status=vision.status,
        detection_message=vision.message,
        model=vision.model,
        image_width=vision.image_width,
        image_height=vision.image_height,
        detections=detections,
        reasons=reasons,
        actions=actions,
        escalation_risks=escalation,
        timeline=build_timeline(has_history=False),
        geotag=geotag or InvestigationGeotag(
            available=False, message="Location was not supplied for this investigation."
        ),
        captured_at=moment,
    )


def _merge_decision_gaps(
    reasons: List[InvestigationReason], decision: object, observed_at: Optional[datetime]
) -> List[InvestigationReason]:
    """Fold the decision engine's own data gaps into the frame's reasons.

    The engine already works out what the analysis could not establish (missing domains, absent
    history, insufficient cross-checking). Re-deriving that here would risk the two disagreeing,
    which is the specific failure the single-source rule exists to prevent — so the engine's gaps
    are adopted, and only the frame-specific ones are added locally.

    Gaps still survive the cap: an observation is dropped before a caveat is.
    """
    gaps = [r for r in reasons if r.type == "UNKNOWN"]
    observations = [r for r in reasons if r.type != "UNKNOWN"]

    known = {r.text for r in gaps}
    for gap in getattr(decision, "data_gaps", []) or []:
        if len(gaps) >= MAX_REASONS or gap in known:
            continue
        # Skip gaps the frame already states in its own words.
        if "historical baseline" in gap and any("earlier frames" in r.text for r in gaps):
            continue
        gaps.append(
            InvestigationReason(
                reason_id="WHY-PENDING",
                text=gap,
                type="UNKNOWN",
                evidence_ids=["DATA-ENGINE"],
                source="EcoSentinel decision engine",
                observed_at=observed_at,
            )
        )
        known.add(gap)

    room = max(0, MAX_REASONS - len(gaps))
    ordered = observations[:room] + gaps
    return [
        reason.model_copy(update={"reason_id": f"WHY-{index:03d}"})
        for index, reason in enumerate(ordered[:MAX_REASONS], start=1)
    ]
