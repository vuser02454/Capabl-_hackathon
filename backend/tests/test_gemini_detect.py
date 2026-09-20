"""The experimental Gemini detector's contract with the existing taxonomy.

Nothing here calls Gemini: the parsing, validation and staging are pure functions over a
generation, and the tests that matter are about what happens to a *bad* one. The two properties
under guard are the two that would quietly corrupt the dataset — an invented confidence number
that gets compared against YOLO's real one, and a new class name that forks the taxonomy.
"""

import json

import pytest

from services.waste import gemini_detect as g


# --- taxonomy -------------------------------------------------------------------------------

def test_canonical_classes_are_the_detector_s_own_six():
    classes = g.canonical_classes()
    assert classes == ["ewaste", "food_waste", "metal_cans", "paper_waste", "plastic_bags", "plastic_bottles"]


def test_class_ids_match_the_dataset_order():
    # An approved candidate must be trainable without a second mapping, so the id here has to be
    # the id in data.yaml — not an index into some Gemini-specific list.
    assert g.class_id_of("ewaste") == 0
    assert g.class_id_of("plastic_bottles") == 5
    assert g.class_id_of(g.UNKNOWN) is None


# --- response parsing -----------------------------------------------------------------------

def test_parses_a_bare_json_object():
    raw, error = g.parse_response('{"detections": []}')
    assert error is None and raw == []


def test_parses_json_inside_a_code_fence():
    # Gemini wraps output in ```json often enough that not handling it would look like an outage.
    raw, error = g.parse_response('```json\n{"detections": [{"class": "metal_cans"}]}\n```')
    assert error is None and len(raw) == 1


@pytest.mark.parametrize(
    "text",
    ["", "   ", "not json at all", "[1,2,3]", '{"objects": []}'],
)
def test_malformed_generations_become_errors_not_detections(text):
    raw, error = g.parse_response(text)
    assert raw is None and error


# --- bounding boxes -------------------------------------------------------------------------

def test_converts_gemini_yxyx_over_1000_into_pixel_xyxy():
    # [ymin, xmin, ymax, xmax] over 0..1000 -> [x1, y1, x2, y2] in pixels, which is what
    # WasteSegregationDetection.bbox already carries and the photo overlay expects.
    bbox, error = g.convert_box([250, 100, 750, 500], width=1000, height=2000)
    assert error is None
    assert bbox == [100.0, 500.0, 500.0, 1500.0]


@pytest.mark.parametrize(
    "box,reason",
    [
        ([0, 0, 0, 0], "degenerate"),          # zero area
        ([900, 100, 100, 500], "degenerate"),  # ymax < ymin
        ([0, 500, 100, 100], "degenerate"),    # xmax < xmin
        ([0, 0, 1200, 500], "range"),          # outside 0-1000
        ([0, 0, 100], "four"),                 # wrong arity
        ("nope", "four"),                      # wrong type
        ([0, 0, "x", 5], "numeric"),           # non-numeric
    ],
)
def test_invalid_boxes_are_rejected_never_clamped(box, reason):
    bbox, error = g.convert_box(box, width=640, height=480)
    assert bbox is None
    assert reason in error


# --- normalisation: the properties that protect the dataset ---------------------------------

def test_never_fabricates_a_confidence():
    accepted, _ = g.normalise_detections(
        [{"class": "plastic_bottles", "box_2d": [0, 0, 500, 500]}], 100, 100
    )
    assert accepted[0]["confidence"] is None


def test_unrecognised_class_becomes_unknown_not_a_new_class():
    accepted, _ = g.normalise_detections(
        [{"class": "gemini_bottle_group_1", "box_2d": [0, 0, 500, 500]}], 100, 100
    )
    assert accepted[0]["canonical_class"] == g.UNKNOWN
    assert accepted[0]["class_id"] is None


def test_one_image_yields_object_level_annotations_across_several_existing_classes():
    """3 bottles + 2 bags + 1 can -> six objects, three existing classes, no groups."""
    raw = (
        [{"class": "plastic_bottles", "box_2d": [i * 100, 0, i * 100 + 50, 50]} for i in range(3)]
        + [{"class": "plastic_bags", "box_2d": [i * 100 + 400, 0, i * 100 + 450, 50]} for i in range(2)]
        + [{"class": "metal_cans", "box_2d": [700, 0, 750, 50]}]
    )
    accepted, rejected = g.normalise_detections(raw, 1000, 1000)

    assert len(accepted) == 6 and not rejected
    names = [d["canonical_class"] for d in accepted]
    assert names.count("plastic_bottles") == 3
    assert names.count("plastic_bags") == 2
    assert names.count("metal_cans") == 1
    # The failure this guards: a "group" concept leaking in as a class.
    assert all(n in set(g.canonical_classes()) for n in names)
    assert not any("group" in n for n in names)
    assert {d["class_id"] for d in accepted} == {5, 4, 2}


def test_a_bad_box_is_reported_rather_than_silently_dropped():
    accepted, rejected = g.normalise_detections(
        [
            {"class": "plastic_bottles", "box_2d": [0, 0, 500, 500]},
            {"class": "plastic_bags", "box_2d": [0, 0, 0, 0]},
        ],
        100,
        100,
    )
    assert len(accepted) == 1 and len(rejected) == 1
    assert rejected[0]["reason"]


# --- candidate staging ----------------------------------------------------------------------

def _detection_payload():
    return {
        "model": "gemini-2.5-flash",
        "image_width": 100,
        "image_height": 100,
        "detections": [
            {"canonical_class": "plastic_bottles", "class_id": 5, "bbox": [10.0, 20.0, 40.0, 80.0], "confidence": None},
            {"canonical_class": g.UNKNOWN, "class_id": None, "bbox": [0.0, 0.0, 5.0, 5.0], "confidence": None},
        ],
    }


def test_candidate_is_staged_pending_with_existing_class_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "CANDIDATE_ROOT", tmp_path / "waste_user_candidates")
    out = g.save_candidate(b"fake-image-bytes", "capture.jpg", _detection_payload())

    assert out["saved"] and out["status"] == "pending"
    folder = g.CANDIDATE_ROOT / "pending" / out["capture_id"]
    annotations = json.loads((folder / "annotations.json").read_text())["annotations"]

    # `unknown` is staged out of the annotations: it has no class id and cannot be trained on.
    assert len(annotations) == 1
    assert annotations[0]["class"] == "plastic_bottles" and annotations[0]["class_id"] == 5
    # xywh, per the candidate contract.
    assert annotations[0]["bbox"] == [10.0, 20.0, 30.0, 60.0]

    metadata = json.loads((folder / "metadata.json").read_text())
    assert metadata["review_status"] == "pending"
    assert metadata["annotation_provider"] == "gemini"
    assert metadata["image_sha256"]


def test_an_identical_image_is_not_staged_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(g, "CANDIDATE_ROOT", tmp_path / "waste_user_candidates")
    first = g.save_candidate(b"same-bytes", "a.jpg", _detection_payload())
    second = g.save_candidate(b"same-bytes", "b.jpg", _detection_payload())

    assert first["saved"] is True
    assert second["saved"] is False
    assert second["duplicate_of"] == first["capture_id"]


# --- production must be unaffected ----------------------------------------------------------

def test_production_segregate_is_still_backed_by_yolo():
    """The experiment must not have rewired the production route onto Gemini."""
    import inspect

    import main

    source = inspect.getsource(main.segregate_waste)
    assert "waste_pipeline" in source
    assert "gemini" not in source.lower()
