"""Semantic separation between what a detector SAW and what the system CLAIMS it means.

The production water detector is a COCO model. In a river photo it reports people, kites and
boats alongside any litter, and every one of those was once counted as "visible pollution":
two people and four kites scored 0.30 visual pollution and escalated the water risk by 0.08 on
a frame containing no litter at all. These tests hold that line.

The parallel waste rule is here too: a label is only ASSERTED when a model cleared the bar for
that label. A prediction no model is confident about is a candidate, not a segregation category.
"""

import pytest

from core import evidence as evidence_core
from core.investigation import effective_semantic_category, semantic_category_for
from schemas import VisionDetection, VisionDetectionBox, WaterVisionReport
from services.water_vision_service import pollution_detections, score_detections


def detection(class_name, confidence=0.9, category=None):
    kwargs = {}
    if category is not None:
        kwargs["semantic_category"] = category
    return VisionDetection(
        class_name=class_name,
        confidence=confidence,
        bbox=VisionDetectionBox(x1=0, y1=0, x2=10, y2=10),
        **kwargs,
    )


# --------------------------------------------------------------------------- taxonomy


@pytest.mark.parametrize(
    "class_name, expected",
    [
        ("bottle", "visible_surface_litter"),
        ("plastic_waste", "visible_surface_litter"),
        ("garbage", "visible_surface_litter"),
        ("styrofoam", "visible_surface_litter"),
        ("person", "non_pollution_object"),
        ("boat", "non_pollution_object"),
        ("car", "non_pollution_object"),
        # Neither confirmed litter nor ruled out. The system makes NO claim, which is not the
        # same as claiming it is clean — it must simply not be counted as pollution.
        ("kite", "unclassified_object"),
        ("umbrella", "unclassified_object"),
    ],
)
def test_raw_class_maps_to_one_semantic_category(class_name, expected):
    assert semantic_category_for(class_name) == expected


def test_the_raw_detector_class_is_never_overwritten():
    """Interpretation lives beside the raw class, never on top of it."""
    report = WaterVisionReport(
        status="ok", detections=[detection("person"), detection("bottle")], total_objects=2
    )
    assert [d.class_name for d in report.detections] == ["person", "bottle"]


def test_category_is_derived_when_it_was_never_set():
    """A detection built directly must not be scored as 'not litter' by accident."""
    assert effective_semantic_category(detection("bottle")) == "visible_surface_litter"
    # An explicitly-set category is respected rather than re-derived.
    assert effective_semantic_category(detection("bottle", category="non_pollution_object")) == (
        "non_pollution_object"
    )


# --------------------------------------------------------------------------- scoring


def test_non_pollution_objects_do_not_score_as_pollution():
    """The exact frame that exposed the defect: 2 people + 4 kites, no litter."""
    frame = [detection("person"), detection("person")] + [detection("kite") for _ in range(4)]
    assert pollution_detections(frame) == []
    assert score_detections(frame, 20) == 0.0


def test_litter_still_scores():
    assert score_detections([detection("bottle") for _ in range(10)], 20) == 0.5


def test_mixed_frame_scores_only_the_litter():
    frame = [detection("bottle"), detection("person"), detection("garbage"), detection("boat")]
    assert len(pollution_detections(frame)) == 2
    assert score_detections(frame, 20) == 0.1


# --------------------------------------------------------------------------- evidence


def _water_report(detections):
    from tests.test_decision_engine import water_report

    vision = WaterVisionReport(
        available=True,
        status="ok",
        model="YOLOv8n",
        detections=detections,
        total_objects=len(detections),
        pollution_objects=len(pollution_detections(detections)),
        confidence_threshold=0.25,
        visual_score=score_detections(detections, 20),
    )
    return water_report().model_copy(update={"visual_pollution": vision})


def test_a_frame_of_people_produces_no_pollution_evidence():
    evidence = evidence_core.from_water(_water_report([detection("person"), detection("kite")]))
    assert [e for e in evidence if e.kind == "detection"] == []


def test_litter_produces_evidence_that_claims_only_what_was_seen():
    evidence = evidence_core.from_water(_water_report([detection("bottle")]))
    detections = [e for e in evidence if e.kind == "detection"]
    assert detections, "visible litter must still become evidence"
    for item in detections:
        text = f"{item.label} {item.detail}".lower()
        # An image establishes a surface condition, never a chemistry. Denying a chemical claim
        # is the point, so the test looks for the AFFIRMATIVE forms only — "no chemical
        # contamination is established" must pass where "chemical contamination detected" fails.
        for forbidden in (
            "contamination detected",
            "chemically contaminated",
            "unsafe to drink",
            "not potable",
            "dissolved oxygen",
            "toxic",
        ):
            assert forbidden not in text, f"vision evidence must not claim {forbidden!r}: {text}"
        # And it must say what kind of claim it is making.
        assert "surface" in text


def test_evidence_ids_still_index_the_real_boxes():
    """IMG-DET-00N must point at the Nth box the model drew, litter or not."""
    evidence = evidence_core.from_water(
        _water_report([detection("person"), detection("bottle"), detection("person")])
    )
    ids = [e.evidence_id for e in evidence if e.evidence_id.startswith("IMG-DET")]
    assert ids == ["IMG-DET-002"]
