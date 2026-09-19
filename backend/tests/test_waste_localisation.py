"""The localisation gate: is this box a waste object before anything is asked about its material?

These protect the one thing a confidence threshold cannot. The classifier has eight waste classes
and no way to abstain, so shown a person it answers `paper_waste` at 62% — above the 60% assertion
bar. The only defence is refusing to ask, which means the check has to happen before the crop.

`is_never_waste` was that defence and stopped being one: it matches the DETECTOR's class name
against COCO names, and `models/waste_detector.pt` emits waste class names exclusively. The gate
went inert the day that model was configured, without a single test failing — which is why these
exist.

Nothing here loads real weights.
"""

from io import BytesIO

import pytest

from schemas import VisionDetection, VisionDetectionBox, WaterVisionReport
from services.waste import waste_pipeline
from services.waste.waste_classifier import load_categories
from services.waste.waste_localisation import (
    DEGENERATE_SPAN,
    VETO_CONFIDENCE,
    verify_localisation,
)

FRAME = (640, 480)


def box(x1, y1, x2, y2) -> VisionDetection:
    return VisionDetection(
        class_name="plastic_bags", confidence=0.7,
        bbox=VisionDetectionBox(x1=x1, y1=y1, x2=x2, y2=y2),
    )


def png_bytes(width=640, height=480) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (90, 120, 110)).save(buffer, format="PNG")
    return buffer.getvalue()


class RecordingClassifier:
    """Counts how many crops it was shown, so "was it asked at all" is testable."""

    def __init__(self):
        self.calls = 0
        self.config = load_categories()

    def is_configured(self):
        return True

    def classify(self, image):
        self.calls += 1
        return {
            "classification": "paper_waste", "classification_confidence": 0.9,
            "segregation": "biodegradable", "handling": "fibre_recyclable",
            "display": "Paper waste", "status": "confirmed",
        }

    def segregation_for(self, class_name):
        entry = (self.config.get("classes") or {}).get(class_name, {})
        return {"category": entry.get("category"), "handling": entry.get("handling"),
                "display": entry.get("display", class_name)}


def run(monkeypatch, detections, non_waste=()):
    """Run the pipeline with a stubbed detector and a stubbed second opinion."""
    from services import water_vision_service

    report = WaterVisionReport(
        available=True, status="ok", model="waste_detector", detections=list(detections),
        total_objects=len(detections), image_width=FRAME[0], image_height=FRAME[1],
    )
    monkeypatch.setattr(water_vision_service, "build_report", lambda d, c, f: report)
    monkeypatch.setattr(
        waste_pipeline, "non_waste_regions", lambda content, filename: list(non_waste)
    )
    classifier = RecordingClassifier()
    result = waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=classifier
    )
    return result, classifier


# --------------------------------------------------------------------------- geometry


def test_a_box_spanning_the_whole_frame_is_a_region_not_an_object():
    refusal = verify_localisation([0, 0, 640, 480], *FRAME)
    assert refusal is not None
    assert refusal["reason"] == "degenerate_box"
    # The refusal states the measurement, so a reviewer can check it rather than trust it.
    assert "100%" in refusal["detail"]


def test_a_close_up_of_one_object_is_not_refused_for_being_large():
    """The gate is NOT a size ceiling, and must never become one.

    1.9% of TACO's 1814 annotated boxes cover more than 40% of their frame and the largest covers
    94%. A bottle held up to the camera is the shot this feature exists for; refusing large boxes
    as implausible would throw away exactly the photographs people deliberately take.
    """
    assert verify_localisation([30, 20, 600, 450], *FRAME) is None  # 89% x 90%, both under the bar
    assert verify_localisation([0, 0, 639, 200], *FRAME) is None  # full width, but short


def test_the_degenerate_bar_is_above_every_real_annotation_but_one():
    """Documents where the number came from, so moving it is a decision and not a tweak."""
    assert DEGENERATE_SPAN == 0.92  # p99.5 of TACO widths is 0.904, of heights 0.837


def test_geometry_is_skipped_when_the_frame_size_is_unknown():
    """No frame, no fraction. Refusing on a guess would be worse than not refusing."""
    assert verify_localisation([0, 0, 640, 480], None, None) is None


# --------------------------------------------------------------------------- non-waste veto


def test_a_waste_box_sitting_on_a_person_is_refused():
    refusal = verify_localisation(
        [1.7, 0.0, 286.7, 164.6], *FRAME, [("person", 0.705, [0.3, 0.2, 378.8, 154.8])]
    )
    assert refusal is not None
    assert refusal["reason"] == "non_waste_object"
    assert "person" in refusal["detail"]


def test_a_small_box_wholly_inside_a_person_is_refused_despite_low_iou():
    """Containment and IoU catch different failures, so both are checked.

    A 40x40 box drawn on someone's shirt has IoU 0.01 with them and is entirely within them. IoU
    alone would wave it through.
    """
    person = ("person", 0.8, [0.0, 0.0, 600.0, 470.0])
    assert verify_localisation([100, 100, 140, 140], *FRAME, [person]) is not None


def test_a_bottle_merely_overlapping_a_hand_is_not_refused():
    """The veto must not fire on the ordinary case of litter being held or picked up."""
    person = ("person", 0.9, [0.0, 300.0, 200.0, 480.0])
    assert verify_localisation([180, 100, 260, 350], *FRAME, [person]) is None


def test_a_low_confidence_non_waste_detection_does_not_veto():
    """A veto overrides another model, so it carries a higher bar than a report does."""
    weak = ("person", VETO_CONFIDENCE - 0.01, [0.0, 0.0, 640.0, 480.0])
    assert verify_localisation([100, 100, 300, 300], *FRAME, [weak]) is None


# --------------------------------------------------------------------------- pipeline wiring


def test_the_classifier_is_never_asked_about_a_refused_region(monkeypatch):
    """The whole point. A prediction about a person is not evidence, it is an artefact."""
    result, classifier = run(
        monkeypatch,
        [box(1.7, 0.0, 286.7, 164.6)],
        non_waste=[("person", 0.705, [0.3, 0.2, 378.8, 154.8])],
    )

    assert classifier.calls == 0
    record = result["detections"][0]
    assert record["classification"] is None
    assert record["segregation"] == "uncertain"
    assert record["status"] == "needs_review"
    assert record["localisation_rejected"] == "non_waste_object"


def test_a_refused_detection_is_still_reported(monkeypatch):
    """The detector did produce this box. Hiding it would make the response disagree with the model."""
    result, _ = run(
        monkeypatch,
        [box(1.7, 0.0, 286.7, 164.6)],
        non_waste=[("person", 0.705, [0.3, 0.2, 378.8, 154.8])],
    )

    record = result["detections"][0]
    assert record["detected_object"] == "plastic_bags"
    assert record["detection_confidence"] == pytest.approx(0.7)
    assert record["bbox"] == [1.7, 0.0, 286.7, 164.6]
    # The detector's class is a waste class, so it survives as a candidate for a human to judge.
    assert record["candidate"] == "plastic_bags"


def test_refusals_are_counted_in_the_summary(monkeypatch):
    """"Found nothing" and "found three things and refused all three" are different states."""
    result, _ = run(
        monkeypatch,
        [box(1.7, 0.0, 286.7, 164.6), box(300.0, 300.0, 380.0, 400.0)],
        non_waste=[("person", 0.705, [0.3, 0.2, 378.8, 154.8])],
    )

    assert result["summary"]["total_objects"] == 2
    assert result["summary"]["localisations_rejected"] == 1
    assert result["summary"]["non_waste_objects"] == 1
    assert result["summary"]["uncertain"] == 1


def test_a_valid_localisation_still_reaches_the_classifier(monkeypatch):
    """The gate must not be a blanket refusal — that would be safe and useless."""
    result, classifier = run(monkeypatch, [box(300.0, 300.0, 380.0, 400.0)], non_waste=[])

    record = result["detections"][0]
    assert classifier.calls == 1
    assert record.get("localisation_rejected") is None
    # `plastic_bags` at 0.7 clears the assertion bar, so detector authority applies as before —
    # the gate changes which boxes are asked about, not how an answer is resolved.
    assert record["classification"] == "plastic_bags"
    assert record["segregation"] == "non_biodegradable"


def test_the_veto_failing_does_not_fail_the_analysis(monkeypatch):
    """A secondary model is advisory. Its absence means no veto evidence, not no analysis."""
    from services import water_vision_service

    monkeypatch.setattr(
        water_vision_service, "get_water_vision_detector",
        lambda: (_ for _ in ()).throw(RuntimeError("weights gone")),
    )
    from services.waste.waste_localisation import non_waste_regions

    assert non_waste_regions(png_bytes(), "f.png") == []


# --------------------------------------------------------------------------- EXIF orientation


def test_a_portrait_phone_photo_is_measured_as_portrait():
    """The frame the API reports must be the frame the browser renders.

    A phone stores a portrait photo as a landscape buffer with `Orientation=6`. Pillow ignores the
    tag; an `<img>` applies it. The API returns `image_width`/`image_height` from the decoded
    array and the UI positions every box as a percentage of those, so when the two disagree every
    box lands in the wrong place — and one at `x2 = width` becomes a full-width overlay.
    """
    from PIL import Image

    from services.water_vision_service import _decode_image

    stored = Image.new("RGB", (640, 480), (10, 20, 30))
    exif = stored.getexif()
    exif[274] = 6  # rotate 90 CW on display
    buffer = BytesIO()
    stored.save(buffer, "JPEG", exif=exif.tobytes())

    height, width = _decode_image(buffer.getvalue()).shape[:2]
    assert (width, height) == (480, 640)


def test_an_image_without_an_orientation_tag_is_untouched():
    from services.water_vision_service import _decode_image

    height, width = _decode_image(png_bytes(640, 480)).shape[:2]
    assert (width, height) == (640, 480)


def test_a_malformed_exif_block_does_not_fail_the_decode():
    """A broken tag is a reason to skip the rotation, not to refuse the image."""
    from PIL import Image

    from services.water_vision_service import exif_upright

    class Exploding:
        @staticmethod
        def exif_transpose(image):
            raise ValueError("corrupt EXIF")

    original = Image.new("RGB", (8, 8))
    assert exif_upright(original, Exploding) is original
