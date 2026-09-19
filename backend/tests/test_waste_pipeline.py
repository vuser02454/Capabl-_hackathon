"""The two-stage waste pipeline: detect, crop, classify, segregate.

The contract worth protecting is what the pipeline refuses to do. A detector class is never
promoted into a waste class, a low-confidence classification is never presented as a decision, and
a missing model is never reported as "nothing found" — those last two look identical in a summary
that only counts objects, and they mean opposite things.

Nothing here loads real weights: the detector and classifier are stubbed so the test stays fast and
independent of a model file.
"""

import json
from pathlib import Path

import pytest

from core.investigation import is_pollution_class  # noqa: F401 - shared taxonomy sanity
from services.waste import waste_pipeline
from services.waste.waste_classifier import WasteClassifier, load_categories
from schemas import VisionDetection, VisionDetectionBox, WaterVisionReport

REPO_ROOT = Path(__file__).resolve().parents[2]


def detection(class_name: str, conf: float, x1=40.0, y1=40.0, x2=200.0, y2=220.0) -> VisionDetection:
    return VisionDetection(
        class_name=class_name, confidence=conf, bbox=VisionDetectionBox(x1=x1, y1=y1, x2=x2, y2=y2)
    )


def vision(detections=None, status="ok") -> WaterVisionReport:
    detections = detections if detections is not None else [detection("bottle", 0.9)]
    return WaterVisionReport(
        available=status == "ok", status=status, model="YOLOv8n", detections=detections,
        total_objects=len(detections), image_width=640, image_height=480,
    )


def png_bytes(width=640, height=480) -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (90, 120, 110)).save(buffer, format="PNG")
    return buffer.getvalue()


class StubClassifier:
    """Stands in for trained weights, so the pipeline's own behaviour is what is under test."""

    def __init__(self, result=None, configured=True):
        self._result = result or {
            "classification": "plastic_bottles", "classification_confidence": 0.96,
            "segregation": "non_biodegradable", "handling": "recyclable",
            "display": "Plastic bottles", "status": "confirmed",
        }
        self._configured = configured
        self.config = load_categories()

    def is_configured(self):
        return self._configured

    def classify(self, image):
        return dict(self._result)

    def segregation_for(self, class_name):
        entry = (self.config.get("classes") or {}).get(class_name, {})
        return {"category": entry.get("category"), "handling": entry.get("handling"),
                "display": entry.get("display", class_name)}


class StubDetector:
    name = "stub"
    model = "YOLOv8n"

    def __init__(self, report):
        self._report = report

    def detect(self, content, filename):  # pragma: no cover - build_report is patched instead
        raise NotImplementedError


def patch_vision(monkeypatch, report):
    from services import water_vision_service

    monkeypatch.setattr(water_vision_service, "build_report", lambda d, c, f: report)


# --------------------------------------------------------------------------- configuration


def test_the_segregation_mapping_lives_in_configuration():
    """Not hard-coded, because what counts as recyclable varies by municipality."""
    config = load_categories()
    classes = config["classes"]
    assert set(classes) == {
        "food_waste", "leaf_waste", "paper_waste", "wood_waste",
        "plastic_bottles", "plastic_bags", "metal_cans", "ewaste",
    }
    biodegradable = {n for n, c in classes.items() if c["category"] == "biodegradable"}
    assert biodegradable == {"food_waste", "leaf_waste", "paper_waste", "wood_waste"}


def test_thresholds_are_configurable():
    thresholds = load_categories()["thresholds"]
    assert 0 < thresholds["classification_confidence"] <= 1
    assert 0 < thresholds["detection_confidence"] <= 1


def test_the_environmental_handling_note_is_separate_from_the_ml_class():
    """The model predicts a class; how a council handles it is application policy."""
    config = load_categories()
    assert config["classes"]["plastic_bags"]["handling"] == "persistent"
    assert config["classes"]["ewaste"]["handling"] == "hazardous"
    # Every handling value has an explanatory note, so the UI never shows a bare keyword.
    for entry in config["classes"].values():
        assert entry["handling"] in config["handling_notes"]


# --------------------------------------------------------------------------- two-stage behaviour


def test_detector_class_and_classifier_class_are_reported_separately(monkeypatch):
    """A COCO 'cup' classified as 'metal_cans' is informative, not a contradiction to hide."""
    patch_vision(monkeypatch, vision([detection("cup", 0.67)]))
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    item = result["detections"][0]
    assert item["detected_object"] == "cup"            # exactly what the detector said
    assert item["classification"] == "plastic_bottles"  # what the classifier said
    assert item["segregation"] == "non_biodegradable"
    assert item["status"] == "confirmed"


def test_a_detector_class_is_never_promoted_into_a_waste_class(monkeypatch):
    patch_vision(monkeypatch, vision([detection("person", 0.42)]))
    low = StubClassifier({
        "classification": None, "classification_confidence": 0.38,
        "segregation": "uncertain", "status": "needs_review", "candidate": "food_waste",
    })
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=low)

    item = result["detections"][0]
    assert item["detected_object"] == "person"
    assert item["classification"] is None
    assert item["segregation"] == "uncertain"


def test_low_confidence_returns_uncertain_not_a_best_guess(monkeypatch):
    patch_vision(monkeypatch, vision())
    low = StubClassifier({
        "classification": None, "classification_confidence": 0.38,
        "segregation": "uncertain", "status": "needs_review", "candidate": "plastic_bottles",
    })
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=low)

    item = result["detections"][0]
    assert item["segregation"] == "uncertain"
    assert item["status"] == "needs_review"
    # The guess is visible for review, but it is not the answer.
    assert item["candidate"] == "plastic_bottles"
    assert result["summary"]["uncertain"] == 1
    assert result["summary"]["non_biodegradable"] == 0


def test_a_missing_classifier_is_not_reported_as_nothing_found(monkeypatch):
    """"No model" and "no waste" look identical in a count. They mean opposite things."""
    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))
    result = waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=StubClassifier(configured=False)
    )

    assert result["summary"]["total_objects"] == 1      # the object was still found
    assert result["summary"]["uncertain"] == 1
    assert result["detections"][0]["status"] == "unavailable"
    assert "no trained classifier is available" in result["message"].lower()


def test_an_unavailable_detector_makes_no_claim_about_the_image(monkeypatch):
    patch_vision(monkeypatch, vision(status="model_not_configured"))
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    assert result["status"] == "model_not_configured"
    assert result["detections"] == []
    assert result["summary"]["total_objects"] == 0


def test_tiny_detections_are_not_classified(monkeypatch):
    """A 10px crop carries too few pixels for the classifier to do anything but guess."""
    patch_vision(monkeypatch, vision([detection("bottle", 0.9, 10, 10, 18, 18)]))
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    item = result["detections"][0]
    assert item["segregation"] == "uncertain"
    assert "too small" in item["message"].lower()


def test_the_summary_counts_uncertain_separately(monkeypatch):
    # Distinct boxes: two objects in different places, not one object detected twice. Overlapping
    # boxes are deliberately merged, which is what test_one_object_detected_twice_counts_once covers.
    patch_vision(monkeypatch, vision([
        detection("bottle", 0.9),
        detection("cup", 0.8, x1=300.0, y1=40.0, x2=420.0, y2=200.0),
    ]))
    mixed = [
        {"classification": "plastic_bottles", "classification_confidence": 0.96,
         "segregation": "non_biodegradable", "status": "confirmed"},
        {"classification": None, "classification_confidence": 0.3,
         "segregation": "uncertain", "status": "needs_review"},
    ]

    class Alternating(StubClassifier):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def classify(self, image):
            result = dict(mixed[self.calls])
            self.calls += 1
            return result

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=Alternating())
    assert result["summary"] == {
        "total_objects": 2, "biodegradable": 0, "non_biodegradable": 1, "uncertain": 1,
        "duplicate_boxes_merged": 0, "non_waste_objects": 0, "localisations_rejected": 0,
    }


def test_the_waste_pipeline_uses_taco_weights_when_configured(tmp_path, monkeypatch):
    """Waste and water must not share a detector: the Water Agent stays on COCO."""
    from dataclasses import replace

    from config import settings
    from services import water_vision_service

    weights = tmp_path / "waste_detector.pt"
    weights.write_bytes(b"placeholder")
    monkeypatch.setattr(
        water_vision_service,
        "settings",
        replace(settings, waste_detector_model_path=str(weights), yolo26_model_path=""),
    )

    detector = water_vision_service.get_waste_pipeline_detector()
    water = water_vision_service.get_water_vision_detector()

    assert detector is not None
    assert detector.weights_path == str(weights)
    assert water is not None
    assert water.weights_path != str(weights)


# --------------------------------------------------------------------------- classifier guards


def test_an_untrained_classifier_reports_itself_unavailable(tmp_path):
    classifier = WasteClassifier(weights_path=tmp_path / "missing.pt")
    assert classifier.is_configured() is False
    status = classifier.status()
    assert status["available"] is False and status["classes"] == []
    assert "train" in status["detail"].lower()


def test_classification_never_raises_when_weights_are_missing(tmp_path):
    from PIL import Image

    classifier = WasteClassifier(weights_path=tmp_path / "missing.pt")
    outcome = classifier.classify(Image.new("RGB", (100, 100)))
    assert outcome["segregation"] == "uncertain"
    assert outcome["status"] == "unavailable"


# --------------------------------------------------------------------------- API


def test_the_status_endpoint_reports_each_stage_separately():
    from fastapi.testclient import TestClient

    import main

    body = TestClient(main.app).get("/api/waste/pipeline-status").json()
    assert "detector" in body
    assert "classifierAvailable" in body
    # Either stage can be missing on its own, so they are never collapsed into one flag.
    assert isinstance(body["classifierClasses"], list)


def test_the_segregate_endpoint_returns_a_structured_result(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from services import water_vision_service

    monkeypatch.setattr(water_vision_service, "build_report", lambda d, c, f: vision([detection("bottle", 0.9)]))
    response = TestClient(main.app).post(
        "/api/waste/segregate", files={"file": ("f.png", png_bytes(), "image/png")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["detections"][0]["detectedObject"] == "bottle"
    assert "summary" in body and body["summary"]["totalObjects"] == 1


def test_one_object_detected_twice_counts_once(monkeypatch):
    """A single bottle must not be reported as two objects.

    YOLO runs NMS per class, so one bottle can survive as both "bottle" and "vase" over nearly
    identical pixels — which is exactly what a real photo of one bottle produced. The count is what
    a report and a language model then build their claims on, so the inflation cannot be tolerated.
    """
    patch_vision(monkeypatch, vision([
        detection("bottle", 0.66),
        detection("vase", 0.39, x1=41.0, y1=38.0, x2=199.0, y2=221.0),
    ]))

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    assert result["summary"]["total_objects"] == 1
    assert result["summary"]["duplicate_boxes_merged"] == 1
    # The more confident detection survives, and the absorbed name stays visible rather than
    # being quietly discarded — it is the detector's own uncertainty about the object.
    assert result["detections"][0]["detected_object"] == "bottle"
    assert result["detections"][0]["also_detected_as"] == ["vase"]


def test_separate_objects_are_never_merged(monkeypatch):
    """Two bottles side by side are two bottles. Dedup must not swallow real objects."""
    patch_vision(monkeypatch, vision([
        detection("bottle", 0.9),
        detection("bottle", 0.85, x1=300.0, y1=40.0, x2=460.0, y2=220.0),
    ]))

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    assert result["summary"]["total_objects"] == 2
    assert result["summary"]["duplicate_boxes_merged"] == 0
    assert all(d["also_detected_as"] is None for d in result["detections"])


def test_partial_overlap_below_the_threshold_is_kept(monkeypatch):
    """Touching objects — a can resting against a bottle — stay distinct."""
    patch_vision(monkeypatch, vision([
        detection("bottle", 0.9, x1=40.0, y1=40.0, x2=200.0, y2=220.0),
        detection("cup", 0.8, x1=150.0, y1=40.0, x2=310.0, y2=220.0),  # ~0.16 IoU
    ]))

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    assert result["summary"]["total_objects"] == 2


def test_dedup_does_not_leak_between_calls(monkeypatch):
    """Two analyses in a row must not share absorbed labels.

    The pipeline runs in FastAPI's threadpool, so anything held between calls would let one
    upload's suppressed classes appear on another's detections.
    """
    patch_vision(monkeypatch, vision([
        detection("bottle", 0.66),
        detection("vase", 0.39, x1=41.0, y1=38.0, x2=199.0, y2=221.0),
    ]))
    first = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))
    second = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())

    assert first["detections"][0]["also_detected_as"] == ["vase"]
    assert second["detections"][0]["also_detected_as"] is None


def test_a_non_waste_class_never_gets_a_segregation(monkeypatch):
    """A dog is not wood waste, however confident the classifier is.

    The classifier has eight waste classes and no way to abstain: its softmax must distribute 1.0
    across them whatever it is shown. On real TACO images it called a dog wood_waste at 84% and a
    car food_waste at 64% — both above the 60% threshold, so confidence cannot catch this. The
    detector's own class is what rules it out.
    """
    patch_vision(monkeypatch, vision([detection("dog", 0.41)]))
    confident = StubClassifier({
        "classification": "wood_waste", "classification_confidence": 0.8417,
        "segregation": "biodegradable", "handling": "organic",
        "display": "Wood waste", "status": "confirmed",
    })

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=confident)
    record = result["detections"][0]

    assert record["classification"] is None
    assert record["segregation"] == "uncertain"
    assert record["status"] == "needs_review"
    # The guess stays visible for a human, but it is not the answer.
    assert record["candidate"] == "wood_waste"
    assert "not one of the waste classes" in record["message"]
    assert result["summary"]["non_waste_objects"] == 1
    assert result["summary"]["biodegradable"] == 0


def test_an_odd_detector_label_on_real_waste_is_still_classified(monkeypatch):
    """COCO calls plastic bottles `vase` and `teddy bear`. Those must survive.

    The exclusion list is deliberately narrow for this reason: requiring membership in a list of
    waste-sounding names would discard ten of the twenty-one correct bottle detections measured on
    this dataset, because `vase` does not sound like litter and is one.
    """
    patch_vision(monkeypatch, vision([detection("vase", 0.92)]))

    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=StubClassifier())
    record = result["detections"][0]

    assert record["classification"] == "plastic_bottles"
    assert record["segregation"] == "non_biodegradable"
    assert record["status"] == "confirmed"
    assert record["label_source"] == "classifier"
    assert result["summary"]["non_waste_objects"] == 0


def test_a_taco_detector_class_is_used_when_the_classifier_is_uncertain(monkeypatch):
    """The held-out A/B test: most TACO detections were discarded by the classifier gate."""
    patch_vision(monkeypatch, vision([detection("plastic_bags", 0.72)]))
    low = StubClassifier({
        "classification": None, "classification_confidence": 0.41,
        "segregation": "uncertain", "status": "needs_review", "candidate": "paper_waste",
    })
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=low)
    record = result["detections"][0]

    assert record["classification"] == "plastic_bags"
    assert record["segregation"] == "non_biodegradable"
    assert record["status"] == "confirmed"
    assert record["label_source"] == "detector"
    assert record["candidate"] == "paper_waste"
    assert result["summary"]["non_biodegradable"] == 1
    assert result["summary"]["uncertain"] == 0


def test_a_taco_detector_class_wins_when_the_classifier_disagrees(monkeypatch):
    patch_vision(monkeypatch, vision([detection("metal_cans", 0.81)]))
    wrong = StubClassifier({
        "classification": "ewaste", "classification_confidence": 0.88,
        "segregation": "non_biodegradable", "handling": "hazardous",
        "display": "E-waste", "status": "confirmed",
    })
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=wrong)
    record = result["detections"][0]

    assert record["classification"] == "metal_cans"
    assert record["display"] == "Metal cans"
    assert record["label_source"] == "detector"
    assert record["candidate"] == "ewaste"
    assert "detector" in (record["message"] or "").lower()


def test_coco_detector_names_are_not_promoted_into_waste_classes(monkeypatch):
    """`bottle` is not in the taxonomy, so a COCO detector still needs the classifier."""
    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))
    low = StubClassifier({
        "classification": None, "classification_confidence": 0.38,
        "segregation": "uncertain", "status": "needs_review", "candidate": "plastic_bottles",
    })
    result = waste_pipeline.analyze_waste(png_bytes(), "f.png", detector=object(), classifier=low)
    record = result["detections"][0]

    assert record["classification"] is None
    assert record["segregation"] == "uncertain"
    assert record.get("label_source") is None


def test_a_missing_classifier_still_segregates_a_taco_class(monkeypatch):
    patch_vision(monkeypatch, vision([detection("paper_waste", 0.64)]))
    result = waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=StubClassifier(configured=False)
    )
    record = result["detections"][0]

    assert record["classification"] == "paper_waste"
    assert record["segregation"] == "biodegradable"
    assert record["label_source"] == "detector"
    assert result["summary"]["biodegradable"] == 1
    assert result["summary"]["uncertain"] == 0
