"""Water Quality Agent.

Input:      LocationContext, or WaterAgentInput (location + an optional water image)
Tools:      WaterSensorProvider — nearest IoT sensor -> monitoring station -> dataset -> demo
            WaterVisionDetector — optional YOLO26 visual pollution detection (services/water_vision_service.py)
Processing: source selection -> validation -> threshold analysis -> risk calculation
            (+ visual-pollution blending when an image was supplied and the model ran)
Output:     WaterAgentResult (always reports its data source type)

The two signals stay strictly separate in the report:

    measurements / ph / turbidity / temperature / tds   <- sensors and datasets
    visual_pollution                                     <- what YOLO26 could SEE in an image
    dataset_match                                        <- which labelled reference frames the
                                                            image LOOKS LIKE

A vision model cannot measure pH, turbidity, dissolved oxygen or chemistry, and this agent
never lets it populate those fields.
"""

from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from agents.base import Agent, AgentTrace
from config import settings
from core.errors import SensorDataUnavailableError
from core.risk import clamp, format_number, risk_level_for, round_half_up
from schemas import (
    Finding,
    GeoPoint,
    LocationContext,
    Measurement,
    WaterAgentResult,
    WaterDatasetMatch,
    WaterVisionReport,
)
from services.location_service import location_label
from services.water_dataset_match_service import build_match_report
from services.water_sensor_service import WaterSensorProvider
from services.water_vision_service import WaterVisionDetector, build_report, get_water_vision_detector


@dataclass(frozen=True)
class WaterImage:
    content: bytes
    filename: str


@dataclass(frozen=True)
class WaterAgentInput:
    """Optional richer input. Plain LocationContext still works, so existing callers and both
    orchestrators are unaffected."""

    location: LocationContext
    image: Optional[WaterImage] = None


@dataclass(frozen=True)
class WaterParameter:
    key: str
    label: str
    unit: str
    weight: float
    valid_range: Tuple[float, float]
    threshold: float
    threshold_label: str
    sub_score: Callable[[float], float]
    exceeds: Callable[[float], bool]
    optional: bool = False  # only scored when the source reports it


PARAMETERS: Tuple[WaterParameter, ...] = (
    WaterParameter("ph", "pH", "", 0.2, (0, 14), 6.5, "BIS 6.5–8.5",
                   lambda v: clamp(abs(v - 7.0) / 1.5), lambda v: v < 6.5 or v > 8.5),
    WaterParameter("turbidity", "Turbidity", "NTU", 0.55, (0, 4000), 5.0, "BIS permissible",
                   lambda v: clamp(v / 21.0), lambda v: v > 5.0),
    WaterParameter("temperature", "Temperature", "°C", 0.25, (-5, 60), 26.0, "Thermal stress",
                   lambda v: clamp((v - 18.0) / 14.0), lambda v: v > 26.0),
    WaterParameter("tds", "TDS", "mg/L", 0.15, (0, 5000), 500.0, "BIS acceptable",
                   lambda v: clamp(v / 1000.0), lambda v: v > 500.0, optional=True),
)

SOURCE_TRACE_LABELS = {
    "live_iot": "LIVE IOT · EcoSentinel water sensor",
    "monitoring_station": "MONITORING STATION · configured water monitoring station",
    "historical": "HISTORICAL · water-quality dataset",
    "demo": "DEMO · EcoSentinel demo data",
}
BASE_CONFIDENCE = {"live_iot": 0.85, "monitoring_station": 0.9, "historical": 0.6, "demo": 0.85}
MISSING_PENALTY = 0.2


def _finding(key: str, value: float) -> Tuple[str, str]:
    if key == "ph":
        label = "Acidic water pH" if value < 6.5 else "Alkaline water pH"
        return label, f"pH {format_number(value)} · outside BIS range 6.5–8.5"
    if key == "turbidity":
        return "Increased water turbidity", f"{format_number(value)} NTU · {value / 5:.1f}× BIS permissible limit"
    if key == "tds":
        return "High dissolved solids", f"{format_number(value)} mg/L · above BIS acceptable limit (500 mg/L)"
    return "Elevated water temperature", f"{format_number(value)} °C · reduces dissolved oxygen"


class WaterQualityAgent(Agent[LocationContext, WaterAgentResult]):
    agent_id = "water"
    name = "Water Quality Agent"

    def __init__(self, provider: WaterSensorProvider, vision: Optional[WaterVisionDetector] = None):
        self.provider = provider
        # Resolved once per agent instance so the model is not re-selected per request.
        self.vision = vision if vision is not None else get_water_vision_detector()

    def run(self, payload, trace: AgentTrace) -> WaterAgentResult:
        # Accept either the historical LocationContext or the newer WaterAgentInput.
        if isinstance(payload, WaterAgentInput):
            location, image = payload.location, payload.image
        else:
            location, image = payload, None
        trace.log(f"Searching nearby {self.provider.network}")
        reading = self.provider.get_latest(location)
        distance = f" · {reading.distance_km:.2f} km away" if reading.distance_km is not None else ""
        trace.log(f"Sensor selected · {reading.sensor_name} ({reading.sensor_id}){distance}")
        trace.log(f"Data source · {SOURCE_TRACE_LABELS.get(reading.source_type, reading.source_type)}")

        measurements: List[Measurement] = []
        findings: List[Finding] = []
        warnings: List[str] = list(reading.notes)
        missing = 0
        checked = 0
        weighted = 0.0
        weight_total = 0.0

        for p in PARAMETERS:
            value: Optional[float] = getattr(reading, p.key)
            if p.optional and value is None:
                continue
            checked += 1
            low, high = p.valid_range
            if value is not None and not (low <= value <= high):
                warnings.append(f"Rejected out-of-range {p.label} reading ({format_number(value)})")
                value = None
            elif value is None:
                warnings.append(f"{p.label} reading missing from sensor {reading.sensor_id}")

            if value is None:
                missing += 1
                measurements.append(
                    Measurement(key=p.key, label=p.label, value=None, unit=p.unit, threshold=p.threshold,
                                threshold_label=p.threshold_label, status="missing")
                )
                continue

            sub_score = p.sub_score(value)
            weighted += p.weight * sub_score
            weight_total += p.weight
            exceeds = p.exceeds(value)
            status = "critical" if sub_score >= 0.7 else "elevated" if exceeds else "normal"
            measurements.append(
                Measurement(key=p.key, label=p.label, value=value, unit=p.unit, threshold=p.threshold,
                            threshold_label=p.threshold_label, sub_score=round_half_up(sub_score), status=status)
            )
            if exceeds:
                label, detail = _finding(p.key, value)
                findings.append(Finding(code=f"water.{p.key}", label=label, detail=detail,
                                        impact=round_half_up(p.weight * sub_score, 3)))

        valid = checked - missing
        if valid == 0:
            raise SensorDataUnavailableError(f"Sensor {reading.sensor_id} returned no usable readings.")
        trace.log(f"Validated {valid}/{checked} readings" + (f" · {missing} missing" if missing else ""))
        trace.log("Threshold analysis against BIS 10500 limits")

        quality_score = round_half_up(weighted / weight_total)

        # --- Visual pollution (optional, escalation-only) -------------------------------
        # Runs only when an image was supplied.
        #
        # The visual signal can only ever RAISE the assessed risk:
        #
        #     combined = clamp(quality_score + water_visual_weight * visual_score)
        #
        # It is deliberately not a weighted average. Averaging would let a clean-looking photo
        # pull down a risk that measured chemistry had already established — a river can be
        # visually clear and still fail on pH or turbidity, and a photograph is not evidence
        # against a sensor reading. Visible pollution is corroborating evidence of harm;
        # its absence is not evidence of safety. water_visual_weight therefore acts as the
        # maximum escalation (default 0.25) applied at maximum visual density, and when vision
        # does not run the combined score IS the water-quality score.
        vision_report: Optional[WaterVisionReport] = None
        score = quality_score
        blended = False
        if image is not None:
            trace.log(f"Received water image · {image.filename}")
            vision_report = build_report(self.vision, image.content, image.filename)
            if vision_report.status == "ok" and vision_report.visual_score is not None:
                # Two numbers, deliberately both logged: what the model saw, and what of that
                # counts as litter. A COCO detector in a river scene reports people and boats,
                # and only the litter subset may touch the risk score.
                trace.log(
                    f"{vision_report.total_objects} object(s) detected · "
                    f"{vision_report.pollution_objects} classified as visible litter · "
                    f"{vision_report.model}"
                )
                if vision_report.non_pollution_objects:
                    trace.log(
                        f"{vision_report.non_pollution_objects} non-pollution object(s) excluded "
                        "from the visual pollution signal"
                    )
                weight = clamp(settings.water_visual_weight)
                score = round_half_up(clamp(quality_score + weight * vision_report.visual_score))
                blended = score != quality_score
                if blended:
                    trace.log(
                        f"Water risk escalated {quality_score} -> {score} "
                        f"by visual pollution (max +{weight:g})"
                    )
                if vision_report.pollution_objects:
                    findings.append(
                        Finding(
                            code="water.visual_pollution",
                            label="Visible litter on the water surface",
                            detail=(
                                f"{vision_report.pollution_objects} litter object(s) detected by "
                                f"{vision_report.model} at "
                                f"≥{int((vision_report.confidence_threshold or 0) * 100)}% confidence. "
                                "Observed surface condition only — this is not a chemical measurement."
                            ),
                            impact=round_half_up(
                                clamp(settings.water_visual_weight) * vision_report.visual_score, 3
                            ),
                        )
                    )
            else:
                trace.log(f"Visual detection unavailable · {vision_report.message or vision_report.status}")
                warnings.append(
                    vision_report.message or "Visual water-pollution detection was unavailable."
                )
        else:
            vision_report = build_report(self.vision, None, "")

        # --- Reference-dataset appearance match (optional, reporting-only) ---------------
        # Deliberately does NOT touch `score`. Measured leave-one-clip-out, this matcher misreads
        # clean water as contaminated most of the time (see water_dataset_match_service), so letting
        # it move a risk number would corrupt an otherwise sensor-backed figure. It is carried as
        # separate, clearly-caveated evidence for a human to act on.
        dataset_match: Optional[WaterDatasetMatch] = None
        if image is not None:
            dataset_match = build_match_report(image.content)
            if dataset_match.status == "ok":
                trace.log(
                    f"Reference match · {dataset_match.matched_label} "
                    f"(similarity {dataset_match.similarity:.2f}) · does not affect the risk score"
                )
            elif dataset_match.status not in {"not_run"}:
                trace.log(f"Reference match unavailable · {dataset_match.message or dataset_match.status}")

        level = risk_level_for(score)
        trace.log(f"Water risk assessed · {level}")

        base = BASE_CONFIDENCE.get(reading.source_type, 0.85)
        return WaterAgentResult(
            location=location_label(location),
            risk_level=level,
            risk_score=score,
            confidence=round_half_up(clamp(base - MISSING_PENALTY * missing)),
            timestamp=reading.observed_at,
            data_source=reading.provider,
            is_mock=reading.is_mock,
            measurements=measurements,
            findings=sorted(findings, key=lambda f: f.impact, reverse=True),
            warnings=warnings,
            sensor_id=reading.sensor_id,
            sensor_name=reading.sensor_name,
            sensor_status="degraded" if missing else reading.status,  # type: ignore[arg-type]
            ph=reading.ph,
            turbidity=reading.turbidity,
            temperature=reading.temperature,
            tds=reading.tds,
            source_type=reading.source_type,  # type: ignore[arg-type]
            source_name=reading.source_label,
            sensor_distance_km=reading.distance_km,
            source_location=(
                GeoPoint(latitude=reading.latitude, longitude=reading.longitude)
                if reading.latitude is not None and reading.longitude is not None
                else None
            ),
            data_age_minutes=reading.data_age_minutes,
            visual_pollution=vision_report,
            dataset_match=dataset_match,
            # Surfaced only when the visual signal actually moved the number, so the blend is auditable.
            water_quality_score=quality_score if blended else None,
        )
