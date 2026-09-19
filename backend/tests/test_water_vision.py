"""Water Pollution Vision (YOLO26) integration.

Covers the contract that matters: the visual signal is additive and optional, it can never
lower a measured water-quality risk, and every failure mode degrades to a normal Water Agent
report rather than breaking the analysis.
"""

import pytest

from agents.base import AgentTrace
from agents.water_agent import WaterAgentInput, WaterImage, WaterQualityAgent
from config import settings
from schemas import VisionDetection, VisionDetectionBox, WaterAgentResult
from services.location_service import resolve_location
from services.water_sensor_service import get_water_provider
from services.water_vision_service import (
    VisionOutput,
    VisionUnavailable,
    build_report,
    score_detections,
)


@pytest.fixture
def location():
    return resolve_location("Bengaluru", None)


def _agent(vision=None):
    return WaterQualityAgent(get_water_provider(True), vision=vision)


def _detections(count, class_name="plastic"):
    return [
        VisionDetection(
            class_name=class_name,
            confidence=0.9,
            bbox=VisionDetectionBox(x1=i, y1=i, x2=i + 10, y2=i + 10),
        )
        for i in range(count)
    ]


class StubDetector:
    """Stands in for YOLO26 so tests never need weights or a network."""

    name = "stub"
    model = "YOLO26 Nano"

    def __init__(self, count=0, raises=None, class_name="plastic"):
        self.count = count
        self.raises = raises
        self.class_name = class_name

    def is_configured(self):
        return True

    def detect(self, content, filename):
        if self.raises:
            raise self.raises
        return VisionOutput(model=self.model, detections=_detections(self.count, self.class_name))


# --------------------------------------------------------------- agent without an image


def test_water_agent_works_without_image(location):
    """The existing call path — a bare LocationContext — is untouched."""
    result = _agent().run(location, AgentTrace())
    assert isinstance(result, WaterAgentResult)
    assert result.visual_pollution.status == "not_run"
    assert result.visual_pollution.available is False
    assert result.water_quality_score is None
    assert result.ph is not None  # water-quality analysis still ran


def test_water_quality_score_unchanged_when_vision_not_run(location):
    baseline = _agent().run(location, AgentTrace())
    with_input = _agent().run(WaterAgentInput(location=location), AgentTrace())
    assert with_input.risk_score == baseline.risk_score


# --------------------------------------------------------------- agent with an image


def test_image_adds_visual_pollution_block(location):
    result = _agent(StubDetector(count=6)).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    vision = result.visual_pollution
    assert vision.available is True and vision.status == "ok"
    assert vision.total_objects == 6
    assert vision.object_counts == {"plastic": 6}
    assert vision.model == "YOLO26 Nano"
    assert len(vision.detections) == 6


def test_class_names_come_from_the_model_not_a_fixed_list(location):
    """Whatever the trained model reports is what surfaces — no remapping to plastic/paper/other."""
    result = _agent(StubDetector(count=3, class_name="tyre")).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    assert result.visual_pollution.object_counts == {"tyre": 3}


def test_visual_signal_can_only_raise_risk(location):
    """A clean-looking photo must never pull down a risk the sensors established."""
    baseline = _agent().run(location, AgentTrace())
    for count in (0, 1, 5, 20, 100):
        result = _agent(StubDetector(count=count)).run(
            WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
        )
        assert result.risk_score >= baseline.risk_score, f"{count} detections lowered the score"


def test_more_detections_never_lower_the_score(location):
    scores = [
        _agent(StubDetector(count=c)).run(
            WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
        ).risk_score
        for c in (0, 4, 12, 20)
    ]
    assert scores == sorted(scores)


def test_zero_detections_is_handled(location):
    result = _agent(StubDetector(count=0)).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    assert result.visual_pollution.status == "ok"
    assert result.visual_pollution.total_objects == 0
    assert result.visual_pollution.visual_score == 0.0
    assert result.visual_pollution.object_counts == {}


def test_water_quality_score_retained_when_vision_escalates(location):
    baseline = _agent().run(location, AgentTrace())
    result = _agent(StubDetector(count=20)).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    assert result.water_quality_score == baseline.risk_score
    assert result.risk_score > result.water_quality_score


# --------------------------------------------------------------- failure modes


def test_missing_model_is_graceful(location):
    """No weights configured: a normal report, a stated reason, and an unchanged score."""
    baseline = _agent().run(location, AgentTrace())
    result = _agent().run(WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace())
    assert result.visual_pollution.status == "model_not_configured"
    assert result.visual_pollution.available is False
    assert result.risk_score == baseline.risk_score
    assert result.ph is not None
    assert any("YOLO26" in w or "not configured" in w for w in result.warnings)


def test_inference_failure_does_not_break_the_agent(location):
    result = _agent(StubDetector(raises=VisionUnavailable("boom"))).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    assert result.visual_pollution.status == "unavailable"
    assert result.risk_level in {"LOW", "MODERATE", "HIGH"}


def test_unexpected_detector_exception_is_contained(location):
    result = _agent(StubDetector(raises=RuntimeError("driver exploded"))).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    assert result.visual_pollution.status == "unavailable"
    # The underlying message is not leaked verbatim into the report.
    assert "driver exploded" not in (result.visual_pollution.message or "")


def test_build_report_never_raises():
    assert build_report(None, None, "").status == "not_run"
    assert build_report(StubDetector(raises=RuntimeError("x")), b"i", "f").available is False


# --------------------------------------------------------------- scoring


def test_score_is_normalised_density():
    assert score_detections([], 20) == 0.0
    assert score_detections(_detections(10), 20) == 0.5
    assert score_detections(_detections(20), 20) == 1.0
    assert score_detections(_detections(100), 20) == 1.0  # clamped
    assert score_detections(_detections(5), 0) == 0.0  # guard against a zero reference


# --------------------------------------------------------------- coordinator contract


def test_coordinator_accepts_a_report_carrying_vision(location):
    from agents.coordinator_agent import CoordinatorAgent, CoordinatorInput

    water = _agent(StubDetector(count=8)).run(
        WaterAgentInput(location, WaterImage(b"bytes", "w.jpg")), AgentTrace()
    )
    result = CoordinatorAgent().run(
        CoordinatorInput(location="Bengaluru", air=None, water=water, waste=None), AgentTrace()
    )
    assert result.overall_risk_level in {"LOW", "MODERATE", "HIGH"}
    assert "water" in result.inputs_received
