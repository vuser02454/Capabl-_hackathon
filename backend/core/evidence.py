"""Evidence normalization: specialist reports -> one common representation.

Every downstream decision stage reads `EnvironmentalEvidence` and nothing else. That is the
point: problem detection should not need to know that air measures µg/m³ against a WHO guideline
while waste counts objects in a frame. Normalising first is what makes cross-domain reasoning
possible without special-casing every pair.

Severity is NOT recomputed here. It is taken from the scores the specialists already produced
(`Measurement.sub_score`, `Finding.impact`), so the deterministic scale established in
`core/risk.py` stays the single source of truth for "how bad is this".

Direction (improving / deteriorating) is only ever set where a REAL baseline exists. Today that
is the air agent's 24-hour PM2.5 comparison and nothing else: the water and waste providers
return a single point in time with no history to compare against. Where there is no baseline the
direction stays `"unknown"` — never `"stable"`, which would be a claim about a trend nobody
measured.
"""

from typing import List, Optional, Sequence

from core import investigation
from schemas import (
    AirAgentResult,
    EnvironmentalEvidence,
    GeographicContext,
    WasteAgentResult,
    WaterAgentResult,
)

#: Status -> the floor severity a threshold exceedance carries even when sub_score is small.
#: An exceeded guideline is meaningful on its own, however modest the normalised score.
STATUS_FLOOR = {"critical": 0.7, "elevated": 0.4, "normal": 0.0, "missing": 0.0}

#: Evidence at or above this severity counts as "elevated" for problem detection.
ELEVATED_SEVERITY = 0.4


def _measurement_evidence(
    domain: str, report, source: str, is_mock: bool, observed_at
) -> List[EnvironmentalEvidence]:
    """One evidence item per reported measurement, carrying its own threshold and status."""
    evidence: List[EnvironmentalEvidence] = []
    for measurement in report.measurements:
        if measurement.value is None and measurement.status == "missing":
            # A missing measurement is still evidence — of a data gap, handled by the planner.
            evidence.append(
                EnvironmentalEvidence(
                    evidence_id=f"{domain}.{measurement.key}",
                    domain=domain,  # type: ignore[arg-type]
                    kind="measurement",
                    label=measurement.label,
                    detail=f"{measurement.label} was not reported by {source}.",
                    unit=measurement.unit or None,
                    threshold=measurement.threshold,
                    status="missing",
                    severity=0.0,
                    confidence=0.0,
                    source=source,
                    observed_at=observed_at,
                    is_mock=is_mock,
                )
            )
            continue

        severity = max(measurement.sub_score or 0.0, STATUS_FLOOR.get(measurement.status, 0.0))
        detail = f"{measurement.label} {measurement.value}{(' ' + measurement.unit) if measurement.unit else ''}"
        if measurement.threshold is not None:
            detail += f" against {measurement.threshold_label or 'threshold'} {measurement.threshold}"
        evidence.append(
            EnvironmentalEvidence(
                evidence_id=f"{domain}.{measurement.key}",
                domain=domain,  # type: ignore[arg-type]
                kind="measurement",
                label=measurement.label,
                detail=detail,
                value=measurement.value,
                unit=measurement.unit or None,
                threshold=measurement.threshold,
                status=measurement.status,
                severity=min(1.0, severity),
                confidence=report.confidence,
                source=source,
                observed_at=observed_at,
                is_mock=is_mock,
            )
        )
    return evidence


def from_air(report: Optional[AirAgentResult]) -> List[EnvironmentalEvidence]:
    """Air measurements, plus the one genuine trend signal in the system."""
    if report is None:
        return []
    evidence = _measurement_evidence("air", report, report.data_source, report.is_mock, report.timestamp)

    # The air agent is the only provider with a real historical comparison: a 24-hour PM2.5
    # baseline. Its anomaly strings are therefore the only honest source of "deteriorating".
    for index, anomaly in enumerate(report.anomalies):
        evidence.append(
            EnvironmentalEvidence(
                evidence_id=f"air.anomaly.{index}",
                domain="air",
                kind="derived",
                label="Deviation from 24-hour baseline",
                detail=anomaly,
                status="elevated",
                severity=ELEVATED_SEVERITY,
                confidence=report.confidence,
                direction="deteriorating",
                source=report.data_source,
                observed_at=report.timestamp,
                is_mock=report.is_mock,
            )
        )
    return evidence


def from_water(report: Optional[WaterAgentResult]) -> List[EnvironmentalEvidence]:
    """Water measurements, and the visual signal when a photo was analysed.

    No direction is derived. The water providers return one reading with no history, so any
    "improving"/"deteriorating" claim here would be invented.
    """
    if report is None:
        return []
    source = report.source_name or report.data_source
    evidence = _measurement_evidence("water", report, source, report.is_mock, report.timestamp)

    vision = report.visual_pollution
    # Gated on the LITTER count, not the raw object count. A frame containing only people and
    # boats produced six "visible pollution" evidence items before this: the detector was right
    # about the objects and the system was wrong about what they meant.
    #
    # The count is recomputed from the detections rather than read from `vision.pollution_objects`.
    # Evidence is built from the boxes themselves, so deriving the gate from anything else allows a
    # report whose summary field and whose detection list disagree — and the summary would win.
    litter_count = 0
    if vision is not None:
        litter_count = sum(
            1
            for d in vision.detections
            if investigation.effective_semantic_category(d) == "visible_surface_litter"
        )
    if vision is not None and getattr(vision, "status", None) == "ok" and litter_count:
        model = getattr(vision, "model", None) or "water vision model"
        # ONE EVIDENCE ITEM PER DETECTION, with the same id the frame investigation uses
        # (IMG-DET-001...). That is what makes IMAGE -> DETECTION -> EVIDENCE -> REASON a real
        # relationship in the data rather than something the UI merely draws: a reason citing
        # IMG-DET-002 resolves to the box the model actually drew, and the decision engine weighs
        # each detection as its own signal.
        #
        # The enumeration runs over ALL detections so an evidence id still matches the box index
        # the investigation and the annotated image use — renumbering only the litter would make
        # IMG-DET-002 point at a different object in two places. Non-litter detections are simply
        # skipped: they are visible in the vision report, they are not evidence of pollution.
        for index, detection in enumerate(vision.detections, start=1):
            if investigation.effective_semantic_category(detection) != "visible_surface_litter":
                continue
            evidence.append(
                EnvironmentalEvidence(
                    evidence_id=f"IMG-DET-{index:03d}",
                    domain="water",
                    kind="detection",
                    label=f"Visible {detection.class_name.replace('_', ' ')}",
                    detail=(
                        f"{detection.class_name.replace('_', ' ')} detected in the submitted frame "
                        f"at {detection.confidence:.0%} confidence. Observed surface litter; "
                        "it establishes nothing about the water's chemistry."
                    ),
                    value=detection.confidence,
                    status="elevated",
                    severity=ELEVATED_SEVERITY,
                    # The detector's own confidence in THIS object, not the agent's overall figure.
                    confidence=detection.confidence,
                    source=model,
                    observed_at=report.timestamp,
                    is_mock=report.is_mock,
                )
            )

        # A roll-up alongside the individual boxes: the count is a signal in its own right, and a
        # reason about accumulation needs something to cite that is not one specific object.
        evidence.append(
            EnvironmentalEvidence(
                evidence_id="water.visual_pollution",
                domain="water",
                kind="detection",
                label="Visible litter on the water surface",
                detail=(
                    f"{litter_count} litter object(s) in the submitted water photo "
                    f"(of {len(vision.detections)} object(s) detected). Surface condition only — "
                    "no chemical contamination is established by an image."
                ),
                value=float(litter_count),
                status="elevated",
                severity=ELEVATED_SEVERITY,
                confidence=report.confidence,
                source=model,
                observed_at=report.timestamp,
                is_mock=report.is_mock,
            )
        )
    return evidence


def from_waste(report: Optional[WasteAgentResult]) -> List[EnvironmentalEvidence]:
    """Waste detections. A single frame, so again no direction is claimed."""
    if report is None:
        return []
    if report.total_objects == 0:
        return []

    evidence = [
        EnvironmentalEvidence(
            evidence_id="waste.density",
            domain="waste",
            kind="detection",
            label="Litter density",
            detail=f"{report.total_objects} object(s) in frame · density index {report.density_index:.2f}",
            value=float(report.total_objects),
            status="critical" if report.risk_level == "HIGH" else "elevated" if report.risk_level == "MODERATE" else "normal",
            severity=report.risk_score,
            confidence=report.confidence,
            source=f"{report.source_name} ({report.model})",
            observed_at=report.timestamp,
            is_mock=report.is_mock,
        )
    ]
    if report.counts.plastic:
        share = report.counts.plastic / report.total_objects
        evidence.append(
            EnvironmentalEvidence(
                evidence_id="waste.plastic",
                domain="waste",
                kind="detection",
                label="Plastic waste",
                detail=f"{report.counts.plastic} of {report.total_objects} object(s) ({share * 100:.0f}%) classified as plastic",
                value=float(report.counts.plastic),
                status="elevated" if share >= 0.5 else "normal",
                severity=min(1.0, share) if share >= 0.5 else 0.0,
                confidence=report.confidence,
                source=f"{report.source_name} ({report.model})",
                observed_at=report.timestamp,
                is_mock=report.is_mock,
            )
        )
    return evidence


def from_geographic(context: Optional[GeographicContext]) -> List[EnvironmentalEvidence]:
    """Mapped OpenStreetMap features.

    CONTEXT ONLY, and severity is deliberately 0. A mapped factory is a polygon a contributor
    drew: it is not an emission and must never raise a severity or a risk score. It exists here
    so cross-signal reasoning can say "industrial activity is mapped nearby" alongside an actual
    measurement — never as a cause.
    """
    if context is None or not context.available:
        return []

    evidence: List[EnvironmentalEvidence] = []
    groups = (
        ("industrial", context.industrial_features, "Mapped industrial feature"),
        ("waste_facility", context.waste_facilities, "Mapped waste facility"),
        ("waterway", context.waterways, "Mapped waterway"),
        ("road", context.roads, "Mapped major road"),
    )
    for key, features, label in groups:
        if not features:
            continue
        nearest = min(features, key=lambda f: f.distance_km)
        evidence.append(
            EnvironmentalEvidence(
                evidence_id=f"geographic.{key}",
                domain="geographic",
                kind="context",
                label=label,
                detail=(
                    f"{len(features)} {label.lower()}(s) mapped nearby; closest is "
                    f"{nearest.name or 'unnamed'} at {nearest.distance_km:.2f} km."
                ),
                value=float(len(features)),
                status="normal",
                severity=0.0,  # context can never carry severity
                confidence=0.0,  # nor confidence in an environmental claim
                source=context.source,
                is_mock=False,
            )
        )
    return evidence


def normalize(
    air: Optional[AirAgentResult],
    water: Optional[WaterAgentResult],
    waste: Optional[WasteAgentResult],
    geographic: Optional[GeographicContext],
) -> List[EnvironmentalEvidence]:
    """All available reports -> one flat, ordered evidence list."""
    return [
        *from_air(air),
        *from_water(water),
        *from_waste(waste),
        *from_geographic(geographic),
    ]


def elevated(evidence: Sequence[EnvironmentalEvidence], domain: Optional[str] = None) -> List[EnvironmentalEvidence]:
    """Evidence at or above the elevated severity threshold, optionally within one domain."""
    return [
        item
        for item in evidence
        if item.severity >= ELEVATED_SEVERITY and (domain is None or item.domain == domain)
    ]


def missing(evidence: Sequence[EnvironmentalEvidence]) -> List[EnvironmentalEvidence]:
    return [item for item in evidence if item.status == "missing"]
