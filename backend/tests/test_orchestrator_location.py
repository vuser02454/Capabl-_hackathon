import ast
import dataclasses
from datetime import datetime, timezone
from pathlib import Path

from agents import orchestrator as orchestrator_module
from agents.coordinator_agent import CoordinatorAgent, CoordinatorInput
from agents.orchestrator import AnalysisOrchestrator
from schemas import LocationContext
from services.location_service import resolve_location
from services.openaq_service import AirQualityReading
from services.water_sensor_service import WaterSensorReading


def test_demo_mode_preset_numbers_unchanged():
    result = AnalysisOrchestrator(demo_mode=True).analyze(resolve_location("Bengaluru", None))
    assert (result.air.risk_score, result.water.risk_score, result.waste.risk_score) == (0.82, 0.61, 0.88)
    assert (result.coordinator.overall_score, result.coordinator.confidence) == (0.81, 0.89)
    assert result.location_context.source == "preset"


def test_demo_mode_live_location_flow(bengaluru_gps):
    result = AnalysisOrchestrator(demo_mode=True).analyze(bengaluru_gps)
    assert [run.agent for run in result.runs] == ["air", "water", "waste", "coordinator"]
    assert result.location_context.latitude == 12.9716
    assert result.air.station_distance_km is not None and result.air.is_mock
    assert result.water.sensor_id == "WTR-07" and result.water.source_type == "demo"
    assert result.waste.source_location is not None
    assert result.coordinator.inputs_received == ["air", "water", "waste"]


class RecordingAir:
    name = "Fake OpenAQ"
    network = "OpenAQ"

    def __init__(self):
        self.locations = []

    def get_latest(self, location):
        self.locations.append(location)
        return AirQualityReading(
            station_id="OPENAQ-9", station_name="Fake station", pm25=42.0, pm10=78.0, no2=31.0, o3=None,
            observed_at=datetime.now(timezone.utc), provider=self.name, is_mock=False, distance_km=3.2,
            station_latitude=12.99, station_longitude=77.60, data_age_minutes=4, freshness="live",
        )

    def get_pm25_baseline(self, location):
        return None


class RecordingWater:
    name = "Fake resolver"
    network = "water sensors and monitoring stations"

    def __init__(self):
        self.locations = []

    def get_latest(self, location):
        self.locations.append(location)
        return WaterSensorReading(
            sensor_id="WATER_001", sensor_name="Node 01", status="online", ph=7.1, turbidity=4.0, temperature=25.0,
            observed_at=datetime.now(timezone.utc), provider="EcoSentinel Water Sensor (mqtt)", is_mock=False,
            source_type="live_iot", source_label="EcoSentinel Water Sensor", distance_km=0.07, latitude=12.972, longitude=77.5951,
            data_age_minutes=2,
        )


def test_live_mode_passes_same_location_to_specialists(monkeypatch, bengaluru_gps):
    air, water = RecordingAir(), RecordingWater()
    monkeypatch.setattr(orchestrator_module, "get_air_provider", lambda demo: air)
    monkeypatch.setattr(orchestrator_module, "get_water_provider", lambda demo: water)

    received = {}
    original_run = CoordinatorAgent.run

    def spy(self, payload, trace):
        received["payload"] = payload
        return original_run(self, payload, trace)

    monkeypatch.setattr(CoordinatorAgent, "run", spy)

    result = AnalysisOrchestrator(demo_mode=False).analyze(bengaluru_gps)

    assert result.mode == "live"
    assert air.locations[0] is bengaluru_gps and water.locations[0] is bengaluru_gps
    assert result.air.station_name == "Fake station" and result.air.freshness == "live"
    assert result.water.source_type == "live_iot" and result.water.sensor_distance_km == 0.07
    payload = received["payload"]
    assert payload.location == "Bengaluru"  # a label, never coordinates
    assert payload.air is result.air and payload.water is result.water and payload.waste is result.waste
    assert result.coordinator.inputs_received == ["air", "water", "waste"]


def test_coordinator_consumes_only_specialist_reports():
    assert {f.name for f in dataclasses.fields(CoordinatorInput)} == {"location", "air", "water", "waste"}
    source = Path(__file__).resolve().parents[1] / "agents" / "coordinator_agent.py"
    imported = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
        elif isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
    assert not imported & {"services", "urllib", "data", "http", "requests", "httpx"}


def test_invalid_location_context_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LocationContext(latitude=123.0, longitude=77.0)
