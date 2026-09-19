"""Waste Detection Agent.

Input:      image / camera frame + LocationContext
Processing: object detection -> waste classification -> density estimation
Output:     WasteAgentResult
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from agents.base import Agent, AgentTrace
from core.risk import clamp, risk_level_for, round_half_up
from schemas import Finding, GeoPoint, LocationContext, Measurement, WasteAgentResult, WasteCounts
from services.location_service import location_label
from services.waste_detection_service import WasteDetector

COUNT_REFERENCE = 24.0  # objects per standard frame treated as maximum density
PLASTIC_SHARE_REFERENCE = 0.65
COUNT_WEIGHT = 0.7
PLASTIC_WEIGHT = 0.3


@dataclass(frozen=True)
class UploadedImage:
    content: bytes
    filename: str


@dataclass(frozen=True)
class WasteAgentInput:
    location: LocationContext
    image: Optional[UploadedImage] = None


class WasteDetectionAgent(Agent[WasteAgentInput, WasteAgentResult]):
    agent_id = "waste"
    name = "Waste Detection Agent"

    def __init__(self, detector: WasteDetector):
        self.detector = detector

    def run(self, payload: WasteAgentInput, trace: AgentTrace) -> WasteAgentResult:
        location = payload.location
        if payload.image:
            trace.log(f"Received uploaded image · {payload.image.filename}")
            output = self.detector.detect_image(payload.image.content, payload.image.filename, location)
        else:
            output = self.detector.detect_camera_frame(location)
            distance = f" · {output.distance_km:.1f} km away" if output.distance_km is not None else ""
            trace.log(f"Analyzed environmental image · {output.source_name} ({output.source_id}){distance}")

        detections = output.detections
        counts = WasteCounts(
            plastic=sum(1 for d in detections if d.category == "plastic"),
            paper=sum(1 for d in detections if d.category == "paper"),
            other=sum(1 for d in detections if d.category == "other"),
        )
        total = len(detections)
        trace.log(f"{total} objects detected · {output.model}")
        trace.log(f"Classified waste · plastic {counts.plastic} · paper {counts.paper} · other {counts.other}")

        count_score = clamp(total / COUNT_REFERENCE)
        plastic_share = counts.plastic / total if total else 0.0
        plastic_score = clamp(plastic_share / PLASTIC_SHARE_REFERENCE)
        density_index = round_half_up(total / COUNT_REFERENCE)
        trace.log(f"Estimated litter density index · {density_index:.2f}")

        findings: List[Finding] = []
        if total >= 15:
            findings.append(Finding(code="waste.density", label="High litter concentration",
                                    detail=f"{total} objects in frame · density index {density_index:.2f}",
                                    impact=round_half_up(COUNT_WEIGHT * count_score, 3)))
        elif total >= 8:
            findings.append(Finding(code="waste.density", label="Moderate litter accumulation",
                                    detail=f"{total} objects in frame · density index {density_index:.2f}",
                                    impact=round_half_up(COUNT_WEIGHT * count_score, 3)))
        if total and plastic_share >= 0.5 and counts.plastic >= 3:
            findings.append(Finding(code="waste.plastic", label="Plastic-dominant waste",
                                    detail=f"{counts.plastic} of {total} objects ({plastic_share * 100:.0f}%) are plastic",
                                    impact=round_half_up(PLASTIC_WEIGHT * plastic_score, 3)))

        score = round_half_up(COUNT_WEIGHT * count_score + PLASTIC_WEIGHT * plastic_score)
        level = risk_level_for(score)
        trace.log(f"Image analysis completed · waste risk {level}")

        confidence = (
            round_half_up(sum(d.confidence for d in detections) / total) if total else 0.9
        )
        measurements = [
            Measurement(key="total", label="Detected objects", value=total, unit="", threshold=15,
                        threshold_label="High density", sub_score=round_half_up(count_score),
                        status="critical" if total >= 15 else "elevated" if total >= 8 else "normal"),
            Measurement(key="plastic", label="Plastic", value=counts.plastic, unit=""),
            Measurement(key="paper", label="Paper", value=counts.paper, unit=""),
            Measurement(key="other", label="Other", value=counts.other, unit=""),
            Measurement(key="density", label="Density index", value=density_index, unit="",
                        threshold=0.62, threshold_label="High density"),
        ]

        return WasteAgentResult(
            location=location_label(location),
            risk_level=level,
            risk_score=score,
            confidence=confidence,
            timestamp=datetime.now(timezone.utc),
            data_source=self.detector.name,
            is_mock=output.is_mock,
            measurements=measurements,
            findings=sorted(findings, key=lambda f: f.impact, reverse=True),
            warnings=[] if total else ["No waste objects detected in the image."],
            source_id=output.source_id,
            source_name=output.source_name,
            input_type=output.input_type,  # type: ignore[arg-type]
            model=output.model,
            total_objects=total,
            counts=counts,
            density_index=density_index,
            detections=detections,
            source_distance_km=output.distance_km,
            source_location=(
                GeoPoint(latitude=output.latitude, longitude=output.longitude)
                if output.latitude is not None and output.longitude is not None
                else None
            ),
        )
