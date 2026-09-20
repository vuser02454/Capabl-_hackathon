"""Air Quality Agent.

Input:      LocationContext (latitude/longitude from browser GPS or a preset)
Tools:      AirQualityProvider (OpenAQ v3 nearby-station search, or the demo dataset)
Processing: data normalisation -> risk calculation -> anomaly detection
Output:     AirAgentResult ("Air Pollution Risk")
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple

from agents.base import Agent, AgentTrace
from core.errors import SensorDataUnavailableError
from core.risk import clamp, format_number, risk_level_for, round_half_up
from data.pollutant_metadata import (
    compare_to_reference,
    generate_contextual_sources,
    get_pollutant_info,
)
from schemas import AirAgentResult, Finding, GeoPoint, LocationContext, Measurement
from services.location_service import location_label
from services.openaq_service import AirQualityProvider


@dataclass(frozen=True)
class Pollutant:
    key: str
    label: str
    weight: float  # share of the air risk score
    reference: float  # concentration treated as maximum risk (µg/m³)
    guideline: float  # WHO 2021 24-hour guideline (O3: 8-hour)
    finding: str
    averaging_period: str = "24-hour"
    cpcb_standard: Optional[float] = None
    cpcb_averaging_period: Optional[str] = None


POLLUTANTS: Tuple[Pollutant, ...] = (
    Pollutant("pm25", "PM2.5", 0.55, 100.0, 15.0, "Elevated PM2.5", "24-hour", 60.0, "24-hour"),
    Pollutant("pm10", "PM10", 0.25, 180.0, 45.0, "Elevated PM10", "24-hour", 100.0, "24-hour"),
    Pollutant("no2", "NO₂", 0.12, 80.0, 25.0, "Elevated NO₂", "24-hour", 80.0, "24-hour"),
    Pollutant("o3", "O₃", 0.08, 100.0, 100.0, "Elevated ozone", "8-hour", 100.0, "8-hour"),
)

# India National AQI breakpoints: (conc_lo, conc_hi, index_lo, index_hi).
# Applied to single readings this is an ESTIMATE, not an official 24-hour AQI.
NAQI_BREAKPOINTS = {
    "pm25": [(0, 30, 0, 50), (31, 60, 51, 100), (61, 90, 101, 200), (91, 120, 201, 300), (121, 250, 301, 400), (251, 500, 401, 500)],
    "pm10": [(0, 50, 0, 50), (51, 100, 51, 100), (101, 250, 101, 200), (251, 350, 201, 300), (351, 430, 301, 400), (431, 1000, 401, 500)],
}
AQI_CATEGORIES = [(50, "Good"), (100, "Satisfactory"), (200, "Moderate"), (300, "Poor"), (400, "Very Poor"), (500, "Severe")]

ANOMALY_RATIO = 1.15
BASE_CONFIDENCE = 0.95  # reference-grade regulatory station
LOW_COST_CONFIDENCE = 0.80  # low-cost sensor network
MISSING_PENALTY = 0.15
DELAYED_PENALTY = 0.05  # per pollutant using an older "latest available" reading


def naqi_sub_index(key: str, concentration: float) -> float:
    for c_lo, c_hi, i_lo, i_hi in NAQI_BREAKPOINTS[key]:
        if concentration <= c_hi:
            c = max(concentration, c_lo)
            return i_lo + (i_hi - i_lo) * (c - c_lo) / (c_hi - c_lo)
    return 500.0


def aqi_category(aqi: float) -> str:
    for upper, name in AQI_CATEGORIES:
        if aqi <= upper:
            return name
    return "Severe"


class AirQualityAgent(Agent[LocationContext, AirAgentResult]):
    agent_id = "air"
    name = "Air Quality Agent"

    def __init__(self, provider: AirQualityProvider):
        self.provider = provider

    def run(self, location: LocationContext, trace: AgentTrace) -> AirAgentResult:
        trace.log(f"Searching nearby {self.provider.network} stations")
        reading = self.provider.get_latest(location)
        kind = "demo station" if reading.is_mock else "reference monitor" if reading.reference_grade else "low-cost sensor"
        distance = f" · {reading.distance_km:.1f} km away" if reading.distance_km is not None else ""
        trace.log(f"Station selected · {reading.station_name}{distance} ({kind})")
        trace.log("Retrieved latest PM2.5 / PM10 / NO₂ / O₃ readings")
        other_stations = {name for _, name in reading.sources if not name.startswith(reading.station_name)}
        if other_stations:
            plural = "s" if len(other_stations) > 1 else ""
            trace.log(f"Filled missing pollutants from {len(other_stations)} other nearby station{plural}")

        measurements: List[Measurement] = []
        findings: List[Finding] = []
        warnings: List[str] = list(reading.notes)
        missing = 0
        weighted = 0.0
        weight_total = 0.0

        for p in POLLUTANTS:
            info = get_pollutant_info(p.key)
            health_effects = info.get("health_effects") if info else None
            is_secondary = info.get("is_secondary_pollutant") if info else False
            precursors = info.get("precursor_pollutants") if info else None
            geo_ctx = getattr(location, "geographic_context", None)
            major_sources = generate_contextual_sources(p.key, geo_ctx)

            value: Optional[float] = getattr(reading, p.key)
            if value is None or value < 0:
                missing += 1
                source = reading.station_name if reading.is_mock else "nearby OpenAQ stations"
                warnings.append(f"{p.label} reading unavailable from {source}")
                measurements.append(
                    Measurement(
                        key=p.key,
                        label=p.label,
                        value=None,
                        unit="µg/m³",
                        threshold=p.guideline,
                        threshold_label="WHO guideline",
                        status="missing",
                        averaging_period=p.averaging_period,
                        who_reference=p.guideline,
                        who_averaging_period=p.averaging_period,
                        cpcb_standard=p.cpcb_standard,
                        cpcb_averaging_period=p.cpcb_averaging_period,
                        comparison_status="missing_data",
                        comparison_note="Measurement unavailable.",
                        health_effects=health_effects,
                        major_sources=major_sources,
                        is_secondary_pollutant=is_secondary,
                        precursor_pollutants=precursors,
                    )
                )
                continue

            sub_score = clamp(value / p.reference)
            weighted += p.weight * sub_score
            weight_total += p.weight
            exceeds = value > p.guideline
            status = "critical" if sub_score >= 0.7 else "elevated" if exceeds else "normal"

            comparison = compare_to_reference(
                measured_value=value,
                measured_unit="µg/m³",
                measured_period=p.averaging_period,
                reference_value=p.guideline,
                reference_unit="µg/m³",
                reference_period=p.averaging_period,
                sub_score=sub_score,
            )

            measurements.append(
                Measurement(
                    key=p.key,
                    label=p.label,
                    value=value,
                    unit="µg/m³",
                    threshold=p.guideline,
                    threshold_label="WHO guideline",
                    sub_score=round_half_up(sub_score),
                    status=status,
                    averaging_period=p.averaging_period,
                    who_reference=p.guideline,
                    who_averaging_period=p.averaging_period,
                    cpcb_standard=p.cpcb_standard,
                    cpcb_averaging_period=p.cpcb_averaging_period,
                    ratio_to_reference=comparison.get("ratio"),
                    difference_to_reference=comparison.get("difference"),
                    percentage_difference=comparison.get("percentage_difference"),
                    interpretation_label=comparison.get("interpretation_label"),
                    comparison_status=comparison.get("status"),
                    comparison_note=comparison.get("note"),
                    health_effects=health_effects,
                    major_sources=major_sources,
                    is_secondary_pollutant=is_secondary,
                    precursor_pollutants=precursors,
                )
            )
            if exceeds:
                findings.append(
                    Finding(
                        code=f"air.{p.key}",
                        label=p.finding,
                        detail=f"{format_number(value)} µg/m³ · {value / p.guideline:.1f}× WHO guideline",
                        impact=round_half_up(p.weight * sub_score, 3),
                    )
                )

        if weight_total == 0:
            raise SensorDataUnavailableError(f"{reading.station_name} returned no valid pollutant readings.")
        trace.log(f"Normalized {len(POLLUTANTS) - missing} pollutants against WHO guidelines")

        aqi, category, dominant = self._aqi(reading.pm25, reading.pm10)

        anomalies: List[str] = []
        baseline = self.provider.get_pm25_baseline(location) if reading.pm25 is not None else None
        if baseline:
            ratio = reading.pm25 / baseline
            if ratio >= ANOMALY_RATIO:
                anomalies.append(f"PM2.5 is {ratio:.1f}× its 24-hour baseline")
            trace.log(f"Anomaly scan vs 24-h baseline · {len(anomalies)} flagged")
        else:
            trace.log("Anomaly scan skipped · no 24-h PM2.5 baseline available")

        score = round_half_up(weighted / weight_total)
        level = risk_level_for(score)
        trace.log(f"Air pollution risk assessed · {level}")

        base_confidence = BASE_CONFIDENCE if reading.reference_grade else LOW_COST_CONFIDENCE
        source_location = (
            GeoPoint(latitude=reading.station_latitude, longitude=reading.station_longitude)
            if reading.station_latitude is not None and reading.station_longitude is not None
            else None
        )
        return AirAgentResult(
            location=location_label(location),
            risk_level=level,
            risk_score=score,
            confidence=round_half_up(
                clamp(base_confidence - MISSING_PENALTY * missing - DELAYED_PENALTY * len(reading.delayed))
            ),
            timestamp=reading.observed_at,
            data_source=reading.provider,
            is_mock=reading.is_mock,
            measurements=measurements,
            findings=sorted(findings, key=lambda f: f.impact, reverse=True),
            warnings=warnings,
            station_id=reading.station_id,
            station_name=reading.station_name,
            pm25=reading.pm25,
            pm10=reading.pm10,
            no2=reading.no2,
            o3=reading.o3,
            aqi=aqi,
            aqi_category=category,
            dominant_pollutant=dominant,
            anomalies=anomalies,
            station_distance_km=reading.distance_km,
            reference_grade=reading.reference_grade,
            source_url=reading.source_url,
            pollutant_sources=dict(reading.sources),
            source_location=source_location,
            data_age_minutes=reading.data_age_minutes,
            freshness=reading.freshness,  # type: ignore[arg-type]
        )

    @staticmethod
    def _aqi(pm25: Optional[float], pm10: Optional[float]) -> Tuple[Optional[int], Optional[str], Optional[str]]:
        indices = []
        if pm25 is not None:
            indices.append((naqi_sub_index("pm25", pm25), "PM2.5"))
        if pm10 is not None:
            indices.append((naqi_sub_index("pm10", pm10), "PM10"))
        if not indices:
            return None, None, None
        value, dominant = max(indices, key=lambda item: item[0])
        aqi = int(round_half_up(value, 0))
        return aqi, aqi_category(aqi), dominant
