"""Tests for the LangGraph orchestration layer (agents/langgraph_orchestrator.py).

Covers: full success, each specialist failing individually, multiple/all specialists
failing, per-agent timeout isolation, that the Coordinator only ever sees typed reports
(never coordinates or provider internals), that risk scoring stays deterministic and
unchanged from the pre-LangGraph orchestrator, and that POST /api/analyze stays
API-compatible. Everything here runs against fake providers — no network access.
"""

import asyncio
import time
from datetime import datetime, timezone

import pytest

from agents import langgraph_orchestrator as lg_module
from agents import orchestrator as orchestrator_module
from agents.coordinator_agent import CoordinatorAgent
from agents.langgraph_orchestrator import LangGraphOrchestrator
from core.errors import SensorDataUnavailableError
from schemas import LocationContext
from services.openaq_service import AirQualityReading
from services.water_sensor_service import WaterSensorReading
from services.waste_detection_service import DetectionOutput


# --------------------------------------------------------------------------- fakes


class FakeAirProvider:
    name = "Fake Air"
    network = "test"

    def __init__(self, delay: float = 0.0, fail: bool = False):
        self.delay = delay
        self.fail = fail

    def get_latest(self, location):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise SensorDataUnavailableError("Air provider unavailable (test).")
        return AirQualityReading(
            station_id="T-AIR", station_name="Test station", pm25=10.0, pm10=10.0, no2=5.0, o3=5.0,
            observed_at=datetime.now(timezone.utc), provider=self.name, is_mock=True,
        )

    def get_pm25_baseline(self, location):
        return None


class FakeWaterProvider:
    name = "Fake Water"
    network = "test"

    def __init__(self, delay: float = 0.0, fail: bool = False):
        self.delay = delay
        self.fail = fail

    def get_latest(self, location):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise SensorDataUnavailableError("Water provider unavailable (test).")
        return WaterSensorReading(
            sensor_id="T-WATER", sensor_name="Test sensor", status="online", ph=7.0, turbidity=2.0,
            temperature=22.0, observed_at=datetime.now(timezone.utc), provider=self.name, is_mock=True,
            source_type="demo",
        )


class FakeWasteDetector:
    name = "Fake Waste"
    model = "test-model"

    def __init__(self, delay: float = 0.0, fail: bool = False):
        self.delay = delay
        self.fail = fail

    def detect_camera_frame(self, location):
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise SensorDataUnavailableError("Waste detector unavailable (test).")
        return DetectionOutput(
            source_id="T-CAM", source_name="Test camera", input_type="camera", model=self.model,
            detections=[], is_mock=True,
        )

    def detect_image(self, content, filename, location):
        raise NotImplementedError


class _PatchedSettings:
    """Wraps the real (frozen) settings object, overriding just a few attributes for a test."""

    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)


def _patch_providers(monkeypatch, air=None, water=None, waste=None):
    monkeypatch.setattr(orchestrator_module, "get_air_provider", lambda demo: air or FakeAirProvider())
    monkeypatch.setattr(orchestrator_module, "get_water_provider", lambda demo: water or FakeWaterProvider())
    monkeypatch.setattr(orchestrator_module, "get_waste_detector", lambda demo: waste or FakeWasteDetector())


# --------------------------------------------------------------------------- scenario A: full success


def test_demo_mode_scores_match_pre_langgraph_orchestrator():
    """Deterministic risk scoring must be identical to the original ThreadPoolExecutor orchestrator."""
    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert (result.air.risk_score, result.water.risk_score, result.waste.risk_score) == (0.82, 0.61, 0.88)
    assert (result.coordinator.overall_score, result.coordinator.confidence) == (0.81, 0.89)
    assert result.coordinator.insufficient_data is False
    assert [run.status for run in result.runs] == ["complete", "complete", "complete", "complete"]


def test_demo_mode_works_without_any_api_keys(monkeypatch):
    """OPENAQ_API_KEY / FIREBASE_DB_URL / etc. are blank in the test environment (conftest.py);
    demo mode must still fully succeed."""
    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert result.mode == "demo"
    assert result.air is not None and result.water is not None and result.waste is not None
    assert result.coordinator.overall_risk_level in ("LOW", "MODERATE", "HIGH")


def test_specialists_run_concurrently_not_sequentially(monkeypatch, bengaluru_gps):
    """Air, water, and waste must run in parallel branches, not one after another."""
    delay = 0.15
    _patch_providers(
        monkeypatch,
        air=FakeAirProvider(delay=delay),
        water=FakeWaterProvider(delay=delay),
        waste=FakeWasteDetector(delay=delay),
    )

    started = time.perf_counter()
    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))
    elapsed = time.perf_counter() - started

    assert result.air is not None and result.water is not None and result.waste is not None
    # Sequential execution would take >= 3 * delay; parallel execution takes roughly 1 * delay.
    assert elapsed < 2 * delay, f"expected concurrent execution, took {elapsed:.3f}s for 3x{delay}s work"


# --------------------------------------------------------------------------- scenario B/C: partial failure


def test_air_agent_failure_does_not_abort_analysis(monkeypatch, bengaluru_gps):
    _patch_providers(monkeypatch, air=FakeAirProvider(fail=True))

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    assert result.air is None
    assert result.water is not None and result.waste is not None
    air_run = next(r for r in result.runs if r.agent == "air")
    assert air_run.status == "failed" and "Air provider unavailable" in air_run.error
    assert result.coordinator.missing_inputs == ["air"]
    assert result.coordinator.inputs_received == ["water", "waste"]
    assert result.coordinator.insufficient_data is False
    assert any("No air assessment is available" in note for note in result.coordinator.data_limitations)


def test_water_agent_failure_does_not_abort_analysis(monkeypatch, bengaluru_gps):
    _patch_providers(monkeypatch, water=FakeWaterProvider(fail=True))

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    assert result.water is None
    assert result.air is not None and result.waste is not None
    water_run = next(r for r in result.runs if r.agent == "water")
    assert water_run.status == "failed"
    assert result.coordinator.missing_inputs == ["water"]


def test_waste_agent_failure_does_not_abort_analysis(monkeypatch, bengaluru_gps):
    _patch_providers(monkeypatch, waste=FakeWasteDetector(fail=True))

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    assert result.waste is None
    assert result.air is not None and result.water is not None
    waste_run = next(r for r in result.runs if r.agent == "waste")
    assert waste_run.status == "failed"
    assert result.coordinator.missing_inputs == ["waste"]


def test_multiple_agents_failing_still_produces_partial_assessment(monkeypatch, bengaluru_gps):
    _patch_providers(monkeypatch, air=FakeAirProvider(fail=True), water=FakeWaterProvider(fail=True))

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    assert result.air is None and result.water is None
    assert result.waste is not None
    assert result.coordinator.missing_inputs == ["air", "water"]
    assert result.coordinator.inputs_received == ["waste"]
    assert result.coordinator.insufficient_data is False
    assert result.coordinator.overall_risk_level in ("LOW", "MODERATE", "HIGH")


def test_all_agents_failing_returns_graceful_insufficient_data(monkeypatch, bengaluru_gps):
    """Scenario D: every specialist fails. The graph must return a normal AnalysisResult with an
    explicit insufficient-data marker, never raise, and never fabricate a measurement."""
    _patch_providers(
        monkeypatch,
        air=FakeAirProvider(fail=True),
        water=FakeWaterProvider(fail=True),
        waste=FakeWasteDetector(fail=True),
    )

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    assert result.air is None and result.water is None and result.waste is None
    assert result.coordinator.insufficient_data is True
    assert result.coordinator.overall_score == 0.0
    assert result.coordinator.confidence == 0.0
    assert result.coordinator.inputs_received == []
    assert result.coordinator.missing_inputs == ["air", "water", "waste"]
    coordinator_run = next(r for r in result.runs if r.agent == "coordinator")
    assert coordinator_run.status == "failed"
    assert all(r.status in ("failed", "timeout") for r in result.runs if r.agent != "coordinator")


# --------------------------------------------------------------------------- timeout isolation


def test_specialist_timeout_is_isolated_and_structured(monkeypatch, bengaluru_gps):
    monkeypatch.setattr(lg_module, "settings", _PatchedSettings(lg_module.settings, agent_timeout_seconds=0.05))
    _patch_providers(monkeypatch, air=FakeAirProvider(delay=0.3))

    result = asyncio.run(LangGraphOrchestrator(demo_mode=False).analyze(None, bengaluru_gps))

    air_run = next(r for r in result.runs if r.agent == "air")
    assert air_run.status == "timeout"
    assert "timed out" in air_run.error
    assert result.air is None
    # The other specialists were not affected by air's timeout.
    assert result.water is not None and result.waste is not None
    assert result.coordinator.insufficient_data is False


# --------------------------------------------------------------------------- Coordinator isolation


def test_coordinator_receives_only_typed_reports_and_a_label(monkeypatch, bengaluru_gps):
    received = {}
    original_run = CoordinatorAgent.run

    def spy(self, payload, trace):
        received["payload"] = payload
        return original_run(self, payload, trace)

    monkeypatch.setattr(CoordinatorAgent, "run", spy)

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze(None, bengaluru_gps))

    payload = received["payload"]
    assert isinstance(payload.location, str) and payload.location == "Bengaluru"
    assert not hasattr(payload, "latitude") and not hasattr(payload, "longitude")
    assert payload.air is result.air and payload.water is result.water and payload.waste is result.waste
    # None of these are raw dicts/provider objects — they are the typed Pydantic results.
    from schemas import AirAgentResult, WasteAgentResult, WaterAgentResult

    assert isinstance(payload.air, AirAgentResult)
    assert isinstance(payload.water, WaterAgentResult)
    assert isinstance(payload.waste, WasteAgentResult)


# --------------------------------------------------------------------------- API compatibility


def test_analyze_endpoint_uses_langgraph_and_matches_response_schema():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    response = client.post("/api/analyze", json={"location": "Bengaluru", "demoMode": True})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert set(body.keys()) >= {"analysisId", "location", "air", "water", "waste", "coordinator", "runs"}
    assert body["coordinator"]["overallScore"] == 0.81
    assert {run["agent"] for run in body["runs"]} == {"air", "water", "waste", "coordinator"}


def test_analyze_endpoint_falls_back_to_original_orchestrator_when_disabled(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setattr(main, "settings", _PatchedSettings(main.settings, langgraph_orchestration_enabled=False))
    client = TestClient(main.app)
    response = client.post("/api/analyze", json={"location": "Bengaluru", "demoMode": True})
    assert response.status_code == 200
    body = response.json()
    # Same deterministic numbers regardless of which orchestrator produced them.
    assert body["coordinator"]["overallScore"] == 0.81


def test_analyze_graph_endpoint_always_uses_langgraph():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    response = client.post("/api/analyze/graph", json={"location": "Bengaluru", "demoMode": True})
    assert response.status_code == 200
    assert response.json()["coordinator"]["overallScore"] == 0.81


# --------------------------------------------------------------------------- LLM narrative is fully optional


def test_no_llm_provider_configured_by_default(monkeypatch):
    """LLM_PROVIDER defaults to 'none' — the coordinator's narrative must never be populated
    and no LLM package is required for the pipeline to run."""
    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert result.coordinator.llm_enhanced is False
    assert result.coordinator.llm_narrative is None
