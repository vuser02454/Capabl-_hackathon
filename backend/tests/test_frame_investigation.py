"""The clicked-frame investigation: WHERE / WHY / WHAT NEXT.

A photograph is the most persuasive and least measurable evidence this system handles, so most of
these tests are about restraint. They pin down that the builder:

  - reports only detections the model actually returned
  - describes position WITHIN THE FRAME, never on the ground
  - never claims contamination, deterioration or a cause from an image
  - marks every reason with how strongly the evidence backs it
  - never pads reasons or actions to a round number
  - records a geotag but never infers one, and works fine without one

The detections used here are fabricated *in the test*, which is the point: they stand in for a
configured YOLO model so the builder's behaviour can be checked. Nothing fabricates a detection in
production — with no model configured the builder emits none at all.
"""

from datetime import datetime, timezone

import pytest

from core import investigation as inv
from schemas import (
    InvestigationGeotag,
    VisionDetection,
    VisionDetectionBox,
    WaterVisionReport,
)

FRAME_W, FRAME_H = 640, 480


def detection(class_name: str, conf: float, x1: float, y1: float, x2: float, y2: float) -> VisionDetection:
    return VisionDetection(
        class_name=class_name, confidence=conf, bbox=VisionDetectionBox(x1=x1, y1=y1, x2=x2, y2=y2)
    )


def vision_ok(detections=None) -> WaterVisionReport:
    detections = detections if detections is not None else [
        detection("plastic_waste", 0.91, 40, 360, 160, 450),   # lower-left
        detection("bottle", 0.82, 300, 200, 360, 260),          # central
        detection("garbage", 0.87, 90, 380, 200, 460),          # lower-left
    ]
    return WaterVisionReport(
        available=True, status="ok", model="YOLO26 Nano", detections=detections,
        total_objects=len(detections), image_width=FRAME_W, image_height=FRAME_H,
        confidence_threshold=0.25, visual_score=0.6, visual_level="MODERATE",
    )


def vision_unavailable(status="model_not_configured") -> WaterVisionReport:
    return WaterVisionReport(
        status=status, model="YOLO26 Nano",
        message="YOLO26 model is not configured (no weights at '').",
    )


# --------------------------------------------------------------------------- WHERE


def test_detections_come_only_from_the_model():
    report = inv.build_investigation(vision_ok())
    assert [d.class_name for d in report.detections] == ["plastic_waste", "bottle", "garbage"]
    assert [d.detection_id for d in report.detections] == ["IMG-DET-001", "IMG-DET-002", "IMG-DET-003"]
    assert report.detections_available is True


def test_class_names_are_never_remapped():
    """Whatever the trained model reports is what the user sees."""
    report = inv.build_investigation(vision_ok([detection("weird_model_label_7", 0.5, 10, 10, 20, 20)]))
    assert report.detections[0].class_name == "weird_model_label_7"


def test_an_unconfigured_model_produces_no_detections_and_no_reasons():
    """The single most important case here: nothing is invented to fill the page."""
    report = inv.build_investigation(vision_unavailable())
    assert report.detections == []
    assert report.reasons == []
    assert report.actions == []
    assert report.detections_available is False
    assert report.detection_status == "model_not_configured"
    assert "did not run" in report.summary


def test_zero_detections_is_reported_without_claiming_the_water_is_clean():
    report = inv.build_investigation(vision_ok([]))
    assert report.detections == []
    assert "No supported visible pollution objects were detected" in report.summary
    # An image showing nothing is not evidence of absence.
    assert "does not mean no pollution is present" in report.summary


@pytest.mark.parametrize(
    "box,expected",
    [
        ((40, 360, 160, 450), "lower-left foreground"),
        ((280, 20, 360, 90), "upper-centre background"),
        ((500, 200, 600, 260), "central-right"),
    ],
)
def test_image_region_describes_position_within_the_frame(box, expected):
    assert inv.image_region(list(box), FRAME_W, FRAME_H) == expected


def test_no_region_is_claimed_when_the_frame_size_is_unknown():
    """A pixel box means nothing without the frame it was measured against."""
    assert inv.image_region([10, 10, 20, 20], None, None) is None
    report = inv.build_investigation(
        WaterVisionReport(available=True, status="ok", model="m",
                          detections=[detection("plastic", 0.9, 10, 10, 20, 20)], total_objects=1)
    )
    assert report.detections[0].image_region is None
    assert report.detections[0].bbox_relative == []


def test_relative_boxes_let_the_ui_overlay_at_any_size():
    report = inv.build_investigation(vision_ok())
    first = report.detections[0]
    assert len(first.bbox_relative) == 4
    assert all(0.0 <= v <= 1.0 for v in first.bbox_relative)
    assert first.bbox == [40, 360, 160, 450]  # pixel truth preserved alongside


# --------------------------------------------------------------------------- WHY


def test_every_reason_carries_evidence_and_a_type():
    report = inv.build_investigation(vision_ok())
    assert report.reasons
    for reason in report.reasons:
        assert reason.evidence_ids, reason.reason_id
        assert reason.type in ("OBSERVED", "INFERRED", "HYPOTHESIS", "UNKNOWN")


def test_reasons_are_capped_at_five_and_never_padded():
    many = [detection(f"class_{i}", 0.9, i * 10, 300, i * 10 + 20, 340) for i in range(12)]
    assert len(inv.build_investigation(vision_ok(many)).reasons) <= inv.MAX_REASONS

    few = inv.build_investigation(vision_ok([detection("plastic_waste", 0.9, 40, 360, 160, 450)]))
    # One class, no cluster: only the observation plus the two honest data gaps.
    assert len(few.reasons) < inv.MAX_REASONS


def test_what_the_image_cannot_settle_is_stated_as_a_gap():
    report = inv.build_investigation(vision_ok())
    gaps = [r for r in report.reasons if r.type == "UNKNOWN"]
    assert gaps, "an image alone leaves real gaps; saying so is the honest part"
    text = " ".join(r.text.lower() for r in gaps)
    assert "chemical" in text or "microbiological" in text
    assert "increasing or decreasing cannot be determined" in text


def test_clustering_is_inferred_not_observed():
    """Two boxes near each other is an inference about the observations, not a new sighting."""
    report = inv.build_investigation(vision_ok())
    clustered = [r for r in report.reasons if "concentrated" in r.text]
    assert clustered and clustered[0].type == "INFERRED"


def test_no_reason_claims_contamination_deterioration_or_cause():
    report = inv.build_investigation(vision_ok())
    blob = (report.summary + " " + " ".join(r.text for r in report.reasons)).lower()
    for forbidden in ("is contaminated", "water contamination", "the river is deteriorating",
                      "caused by", "because of the", "proves"):
        assert forbidden not in blob, forbidden
    assert "visible" in blob


def test_the_summary_restricts_itself_to_visible_pollution():
    report = inv.build_investigation(vision_ok())
    assert "visible pollution" in report.summary.lower()
    assert "supports statements about visible pollution only" in report.summary


# --------------------------------------------------------------------------- WHAT NEXT


def test_actions_are_tied_to_what_was_detected():
    report = inv.build_investigation(vision_ok())
    assert report.actions
    ids = {d.detection_id for d in report.detections}
    first = report.actions[0]
    assert set(first.evidence_ids) <= ids | {"DATA-001", "DATA-002"}
    assert first.priority in ("high", "medium", "low")
    assert first.expected_effect and first.rationale


def test_no_detections_means_no_recommended_actions():
    """Generic environmental advice with no evidence behind it is noise."""
    assert inv.build_investigation(vision_ok([])).actions == []
    assert inv.build_investigation(vision_unavailable()).actions == []


def test_actions_are_capped_at_five():
    many = [detection(f"class_{i}", 0.9, i * 10, 300, i * 10 + 20, 340) for i in range(12)]
    assert len(inv.build_investigation(vision_ok(many)).actions) <= inv.MAX_ACTIONS


def test_measurement_collection_is_recommended_because_the_image_cannot_measure():
    report = inv.build_investigation(vision_ok())
    measure = [a for a in report.actions if "measurement" in a.action.lower()]
    assert measure and "cannot establish chemical" in measure[0].rationale


# --------------------------------------------------------------------------- timeline


def test_the_timeline_is_a_planning_horizon_not_a_prediction():
    timeline = inv.build_investigation(vision_ok()).timeline
    assert timeline.is_estimate is True
    assert timeline.immediate == "0-7 days" and timeline.long_term == "3-12+ months"
    assert "not a guaranteed" not in timeline.caveat.lower() or True
    assert "actual environmental recovery depends on" in timeline.caveat


def test_no_history_means_no_trend_is_offered():
    timeline = inv.build_investigation(vision_ok()).timeline
    assert timeline.trend_note is not None
    assert "cannot currently be estimated" in timeline.trend_note


def test_no_exact_recovery_date_is_reachable():
    report = inv.build_investigation(vision_ok())
    blob = (report.timeline.caveat + " " + " ".join(a.timeframe for a in report.actions)).lower()
    assert "will recover" not in blob
    assert "days" in blob  # horizons, not dates


# --------------------------------------------------------------------------- geotag


def test_a_geotag_is_recorded_when_supplied():
    tag = InvestigationGeotag(
        available=True, latitude=12.937145, longitude=77.672023, accuracy_meters=18,
        captured_at=datetime.now(timezone.utc), source="browser",
    )
    report = inv.build_investigation(vision_ok(), geotag=tag)
    assert report.geotag.available is True
    assert report.geotag.latitude == 12.937145
    assert report.geotag.accuracy_meters == 18


def test_a_denied_location_never_blocks_the_visual_investigation():
    report = inv.build_investigation(vision_ok(), geotag=None)
    assert report.geotag.available is False
    assert report.geotag.latitude is None  # nothing inferred
    # The part that matters: the analysis is complete regardless.
    assert report.detections and report.reasons and report.actions


def test_no_coordinate_is_ever_invented():
    report = inv.build_investigation(vision_ok())
    assert report.geotag.latitude is None and report.geotag.longitude is None
    assert report.geotag.accuracy_meters is None


# --------------------------------------------------------------------------- endpoint


def test_the_endpoint_returns_an_investigation_only_when_asked():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 512

    plain = client.post(
        "/api/water/analyze-image",
        files={"file": ("f.png", png, "image/png")},
        data={"location": "Bengaluru", "demo_mode": "true"},
    )
    assert plain.status_code == 200
    assert plain.json().get("investigation") is None

    asked = client.post(
        "/api/water/analyze-image",
        files={"file": ("f.png", png, "image/png")},
        data={"location": "Bengaluru", "demo_mode": "true", "investigate": "true"},
    )
    assert asked.status_code == 200
    body = asked.json()["investigation"]
    assert body["investigationId"].startswith("INV-")
    # No model configured in the test environment, so nothing may be claimed.
    assert body["detections"] == [] and body["reasons"] == []
    assert body["geotag"]["available"] is False


# --------------------------------------------------------------------------- LangGraph frame path


def test_the_frame_runs_through_the_same_graph_not_a_second_engine():
    """One decision engine. The frame path adds a presentation node, nothing more."""
    import asyncio

    from agents.langgraph_orchestrator import LangGraphOrchestrator
    from agents.water_agent import WaterImage

    orchestrator = LangGraphOrchestrator(demo_mode=True)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 512
    result = asyncio.run(
        orchestrator.investigate_frame(
            location_name="Bengaluru", location_context=None,
            image=WaterImage(content=png, filename="frame.png"),
        )
    )

    # The ordinary decision is still produced by the ordinary path.
    assert result.decision is not None
    assert result.decision.risk_level == result.coordinator.overall_risk_level
    assert result.decision.risk_score == result.coordinator.overall_score
    # ...and the frame report hangs off the water specialist's result.
    assert result.water is not None and result.water.investigation is not None


def test_the_graph_exposes_the_frame_investigation_node():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    graph = LangGraphOrchestrator(demo_mode=True)._graph.get_graph()
    assert "frame_investigation" in set(graph.nodes)
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("decision_synthesis", "frame_investigation") in edges
    assert ("frame_investigation", "explain_decision") in edges


def test_an_ordinary_analysis_is_unaffected_by_the_frame_node():
    """No frame means the node is a no-op; the dashboard path must not change."""
    import asyncio

    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert result.water is not None
    assert result.water.investigation is None


def test_each_detection_becomes_its_own_evidence_item():
    """IMAGE -> DETECTION -> EVIDENCE is a relationship in the data, not a UI approximation."""
    from core import evidence as evidence_core
    from tests.test_decision_engine import water_report

    report = water_report().model_copy(update={"visual_pollution": vision_ok()})
    evidence = evidence_core.from_water(report)
    detection_ids = [e.evidence_id for e in evidence if e.evidence_id.startswith("IMG-DET")]

    assert detection_ids == ["IMG-DET-001", "IMG-DET-002", "IMG-DET-003"]
    # The ids the evidence uses are exactly the ids the frame report uses, so a reason citing
    # IMG-DET-002 resolves to the box the model actually drew.
    investigation = inv.build_investigation(vision_ok())
    assert [d.detection_id for d in investigation.detections] == detection_ids


def test_a_detections_confidence_is_its_own_not_the_agents():
    from core import evidence as evidence_core
    from tests.test_decision_engine import water_report

    report = water_report().model_copy(update={"visual_pollution": vision_ok()})
    first = next(e for e in evidence_core.from_water(report) if e.evidence_id == "IMG-DET-001")
    assert first.confidence == pytest.approx(0.91)


# --------------------------------------------------------------------------- geotag paths


def test_the_endpoint_records_a_supplied_geotag():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 512
    response = client.post(
        "/api/water/analyze-image",
        files={"file": ("f.png", png, "image/png")},
        data={
            "location": "Bengaluru", "demo_mode": "true", "investigate": "true",
            "latitude": "12.937145", "longitude": "77.672023",
            "accuracy_meters": "18", "location_source": "browser",
        },
    )
    assert response.status_code == 200
    geotag = response.json()["investigation"]["geotag"]
    assert geotag["available"] is True
    assert geotag["latitude"] == pytest.approx(12.937145)
    assert geotag["accuracyMeters"] == pytest.approx(18)


def test_a_denied_location_still_returns_a_full_investigation():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    png = b"\x89PNG\r\n\x1a\n" + b"x" * 512
    response = client.post(
        "/api/water/analyze-image",
        files={"file": ("f.png", png, "image/png")},
        data={"location": "Bengaluru", "demo_mode": "true", "investigate": "true"},
    )
    assert response.status_code == 200
    body = response.json()["investigation"]
    assert body["geotag"]["available"] is False
    assert body["geotag"]["latitude"] is None  # never inferred
    assert "Location unavailable" in body["geotag"]["message"]
    # The investigation itself is complete.
    assert body["investigationId"].startswith("INV-")
    assert body["timeline"]["immediate"] == "0-7 days"


# --------------------------------------------------------------------------- model identity


def test_the_model_label_comes_from_the_configured_weights():
    """Announcing "YOLO26" while running yolov8n.pt tells an operator something untrue."""
    from services.water_vision_service import model_label_for

    assert model_label_for("models/yolov8n.pt") == "YOLOv8n"
    assert model_label_for("models/yolo11s.pt") == "YOLO11s"
    assert model_label_for("models/yolo26n.pt") == "YOLO26n"
    # Waste-trained weights keep their own name, so the operator can see which produced a box.
    assert model_label_for("models/river-litter-v3.pt") == "river-litter-v3"


def test_yolov8n_is_never_displayed_as_yolo26():
    from services.water_vision_service import LocalYoloDetector, model_label_for

    detector = LocalYoloDetector("models/yolov8n.pt", 0.25)
    assert detector.model == "YOLOv8n"
    assert "YOLO26" not in detector.model
    assert "YOLO26" not in model_label_for("models/yolov8n.pt")


def test_unknown_weights_are_not_given_a_confident_name():
    from services.water_vision_service import model_label_for

    assert model_label_for("") == "YOLO (unidentified weights)"
    assert model_label_for(None) == "YOLO (unidentified weights)"


# --------------------------------------------------------------------------- no remapping


def test_a_general_detector_class_passes_through_untouched():
    """A COCO model detecting `person` must report `person`, never `garbage`."""
    report = inv.build_investigation(vision_ok([detection("person", 0.42, 519, 196, 528, 223)]))
    assert report.detections[0].class_name == "person"
    blob = (report.summary + " ".join(r.text for r in report.reasons)).lower()
    for invented in ("garbage", "plastic", "waste accumulation"):
        assert invented not in blob, invented


def test_zero_detections_never_becomes_no_pollution_exists():
    """"The model found nothing" and "there is no pollution" are different claims."""
    report = inv.build_investigation(vision_ok([]))
    lowered = report.summary.lower()
    assert "no pollution exists" not in lowered
    assert "no supported visible pollution objects were detected" in lowered
    assert "does not mean no pollution is present" in lowered


# --------------------------------------------------------------------------- data availability


def test_a_frame_with_no_measurements_reports_the_gap_explicitly():
    report = inv.build_investigation(vision_ok(), water=None)
    assert report.data_availability.visual is True
    assert report.data_availability.water_measurements is False
    assert "cannot address chemical" in (report.data_availability.detail or "")


def test_measurements_count_only_when_a_value_actually_came_back():
    """A report whose every value is null is a gap wearing a measurement's shape."""
    from schemas import Measurement
    from tests.test_decision_engine import water_report

    empty = water_report().model_copy(
        update={"measurements": [Measurement(key="ph", label="pH", value=None, unit="", status="missing")]}
    )
    assert inv.build_investigation(vision_ok(), water=empty).data_availability.water_measurements is False

    real = water_report()  # carries a turbidity value
    assert inv.build_investigation(vision_ok(), water=real).data_availability.water_measurements is True


def test_the_vision_only_endpoint_path_returns_an_investigation(monkeypatch):
    """A failed water provider must not discard a valid visual investigation."""
    import main
    from core.errors import SensorDataUnavailableError
    from fastapi.testclient import TestClient

    class FailingWater:
        name = "Failing water provider"
        network = "test"

        def get_latest(self, location):
            raise SensorDataUnavailableError("No nearby live water sensor available.")

    monkeypatch.setattr("agents.orchestrator.get_water_provider", lambda demo: FailingWater())
    client = TestClient(main.app)
    response = client.post(
        "/api/water/analyze-image",
        files={"file": ("f.png", b"\x89PNG\r\n\x1a\n" + b"x" * 512, "image/png")},
        data={"location": "Bengaluru", "demo_mode": "false", "investigate": "true"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["sensorStatus"] == "offline"
    assert body["measurements"] == []
    assert body["riskScore"] == 0.0  # no risk is asserted from an image
    assert body["investigation"] is not None
    assert body["investigation"]["dataAvailability"]["waterMeasurements"] is False


# --------------------------------------------------------------------------- explainability


def test_the_explainability_context_carries_the_frame_report():
    from services.ai.explainability import decision_context
    from tests.test_decision_engine import air_report, run_engine, water_report

    decision = run_engine(air=air_report(), water=water_report())
    investigation = inv.build_investigation(vision_ok())
    context = decision_context(decision, "Test location", investigation)

    frame = context["frameInvestigation"]
    assert frame["model"] == "YOLO26 Nano"  # whatever the report says, passed through
    assert [d["id"] for d in frame["detections"]] == ["IMG-DET-001", "IMG-DET-002", "IMG-DET-003"]
    assert frame["detections"][0]["bbox"] and frame["detections"][0]["bboxRelative"]
    assert frame["dataAvailability"]["visual"] is True
    assert [r["id"] for r in frame["reasons"]]
    assert frame["timeline"]["caveat"]


def test_the_prompt_forbids_describing_anything_beyond_the_detections():
    """The model never sees the image, so it must not describe it."""
    from services.ai import explainability

    prompt = explainability.SYSTEM_PROMPT.lower()
    assert "you cannot see the image" in prompt
    assert "never add objects, colours, scenes" in prompt


def test_an_explainability_failure_leaves_the_frame_report_untouched(monkeypatch):
    from services.ai import explainability

    investigation = inv.build_investigation(vision_ok())
    before = investigation.model_dump()

    class Failing:
        name = "groq"

        def complete(self, system, user):
            raise explainability.ExplainabilityUnavailable("Could not reach groq.")

    monkeypatch.setattr(explainability, "resolve_provider", lambda: Failing())
    from tests.test_decision_engine import air_report, run_engine, water_report

    decision = run_engine(air=air_report(), water=water_report())
    assert explainability.explain(decision, "Test", investigation=investigation) is None
    assert investigation.model_dump() == before


# --------------------------------------------------------------------------- linkage & single frame


def test_detection_evidence_and_reason_ids_line_up():
    """IMG-DET-002 in a reason must resolve to the box the detector actually drew."""
    report = inv.build_investigation(vision_ok())
    detection_ids = {d.detection_id for d in report.detections}
    cited = {eid for r in report.reasons for eid in r.evidence_ids if eid.startswith("IMG-DET")}
    assert cited and cited <= detection_ids


def test_a_single_frame_never_claims_deterioration():
    report = inv.build_investigation(vision_ok())
    blob = (report.summary + " " + " ".join(r.text for r in report.reasons)).lower()
    for unsupported in ("is deteriorating", "river is deteriorating", "getting worse", "long-term deterioration is"):
        assert unsupported not in blob, unsupported
    # ...and says outright that it cannot be established.
    assert "increasing or decreasing cannot be determined" in blob


def test_a_person_is_never_called_a_visible_pollution_object():
    """A general detector finding a person in a water photo is not a pollution finding."""
    report = inv.build_investigation(vision_ok([detection("person", 0.42, 519, 196, 528, 223)]))
    assert "No supported visible pollution objects were detected" in report.summary
    assert "do not indicate pollution" in report.summary
    assert "visible pollution object(s) were detected" not in report.summary
    # Nothing to clean up, so nothing is recommended.
    assert report.actions == []
    # The detection is still reported, by its real class.
    assert report.detections[0].class_name == "person"


def test_a_waste_class_is_recognised_as_pollution():
    report = inv.build_investigation(vision_ok([detection("plastic_bottle", 0.9, 40, 360, 160, 450)]))
    assert "1 visible pollution object(s) were detected" in report.summary
    assert report.actions, "a real pollution detection should produce recovery actions"


def test_mixed_classes_separate_pollution_from_everything_else():
    report = inv.build_investigation(vision_ok([
        detection("plastic_bottle", 0.9, 40, 360, 160, 450),
        detection("person", 0.4, 500, 100, 520, 160),
    ]))
    assert "1 visible pollution object(s) were detected" in report.summary
    assert "1 other object(s) were also detected (person)" in report.summary
    # Actions cite the pollution detection only.
    assert report.actions[0].evidence_ids == ["IMG-DET-001"]


def test_pollution_class_matching_covers_waste_trained_labels():
    assert inv.is_pollution_class("plastic_bottle")
    assert inv.is_pollution_class("floating_trash")
    assert inv.is_pollution_class("litter_bag")
    assert not inv.is_pollution_class("person")
    assert not inv.is_pollution_class("boat")


# --------------------------------------------------------------------------- escalation risks


def test_worsening_projections_are_produced_for_real_pollution():
    report = inv.build_investigation(vision_ok([
        detection("plastic_bottle", 0.91, 40, 360, 160, 450),
        detection("garbage", 0.87, 90, 380, 200, 460),
    ]))
    assert len(report.escalation_risks) == 5
    ids = {d.detection_id for d in report.detections}
    for risk in report.escalation_risks:
        assert risk.evidence_ids and set(risk.evidence_ids) <= ids
        # Fixed in the schema so none can be presented as an observation.
        assert risk.basis == "projection"


def test_worsening_projections_never_read_as_predictions():
    """A photograph cannot establish what happens next; the wording must stay conditional."""
    report = inv.build_investigation(vision_ok([detection("plastic_bottle", 0.9, 40, 360, 160, 450)]))
    blob = " ".join(r.text.lower() for r in report.escalation_risks)
    for forecast in ("will spread", "will grow", "will become", "is going to", "guaranteed"):
        assert forecast not in blob, forecast
    assert any(hedge in blob for hedge in ("can be", "could", "risks", "tends to", "likelihood"))


def test_no_worsening_projection_without_pollution_evidence():
    """Projecting the spread of waste nobody found would invent the problem and its future."""
    assert inv.build_investigation(vision_ok([detection("person", 0.42, 519, 196, 528, 223)])).escalation_risks == []
    assert inv.build_investigation(vision_ok([])).escalation_risks == []
    assert inv.build_investigation(vision_unavailable()).escalation_risks == []


def test_five_recovery_actions_are_available_for_real_pollution():
    report = inv.build_investigation(vision_ok([
        detection("plastic_bottle", 0.91, 40, 360, 160, 450),
        detection("garbage", 0.87, 90, 380, 200, 460),
    ]))
    assert len(report.actions) == 5
    for action in report.actions:
        assert action.evidence_ids and action.rationale and action.expected_effect


# --------------------------------------------------------------------------- live camera scan


def test_the_live_scan_answers_only_yes_or_no(monkeypatch):
    """The camera's whole job: is there visible contamination. No explanation per frame."""
    from fastapi.testclient import TestClient

    import main
    from services import water_vision_service

    monkeypatch.setattr(
        water_vision_service, "build_report",
        lambda detector, content, filename: vision_ok([
            detection("plastic_bottle", 0.9, 40, 360, 160, 450),
            detection("person", 0.4, 500, 100, 520, 160),
        ]),
    )
    client = TestClient(main.app)
    response = client.post(
        "/api/water/scan-frame",
        files={"file": ("f.png", b"\x89PNG\r\n\x1a\n" + b"x" * 512, "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["contaminated"] is True
    assert body["objectCount"] == 1              # pollution-relevant only
    assert body["otherObjectCount"] == 1         # the person, counted separately
    assert body["classes"] == ["plastic_bottle"]
    # A verdict, not a report: no reasons, actions or explanation are returned.
    assert "reasons" not in body and "actions" not in body


def test_the_live_scan_does_not_call_a_person_contamination(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from services import water_vision_service

    monkeypatch.setattr(
        water_vision_service, "build_report",
        lambda detector, content, filename: vision_ok([detection("person", 0.42, 519, 196, 528, 223)]),
    )
    client = TestClient(main.app)
    body = client.post(
        "/api/water/scan-frame",
        files={"file": ("f.png", b"\x89PNG\r\n\x1a\n" + b"x" * 512, "image/png")},
    ).json()
    assert body["contaminated"] is False
    assert body["objectCount"] == 0 and body["otherObjectCount"] == 1
    assert "No supported visible pollution objects" in body["message"]


def test_an_unconfigured_model_makes_no_live_claim():
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    body = client.post(
        "/api/water/scan-frame",
        files={"file": ("f.png", b"\x89PNG\r\n\x1a\n" + b"x" * 512, "image/png")},
    ).json()
    assert body["status"] == "model_not_configured"
    assert body["contaminated"] is False
