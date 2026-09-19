"""The diagnostic mode for the waste pipeline.

What is worth protecting here is that the debug output describes the pipeline that actually runs.
A debug path that re-implements the stages can disagree with them, and a diagnosis of code nobody
executes is worse than no diagnosis — it sends the investigation somewhere else entirely.
"""

import json

import pytest

from services.waste import waste_debug, waste_pipeline
from tests.test_waste_pipeline import (  # noqa: F401 - shared stubs and fixtures
    StubClassifier, detection, patch_vision, png_bytes, vision,
)


def test_debug_observes_the_real_pipeline_rather_than_a_copy(monkeypatch, tmp_path):
    """The recorder is driven by `analyze_waste`, so it cannot report a different pipeline."""
    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))
    recorder = waste_debug.WasteDebugRecorder("probe", out_root=tmp_path)

    result = waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=StubClassifier(), observer=recorder
    )

    assert len(recorder.records) == len(result["detections"])
    assert recorder.records[0]["id"] == result["detections"][0]["id"]
    assert recorder.records[0]["detector"]["class"] == "bottle"


def test_the_production_path_is_untouched_when_nothing_observes(monkeypatch):
    """No observer means no `capture` keyword, so classifiers that predate it keep working.

    `classify(image, capture=...)` is an optional extension. A stub or an alternative backend
    implementing only `classify(image)` must not break because a debug feature was added.
    """

    class OldStyleClassifier(StubClassifier):
        def classify(self, image):  # deliberately no `capture` parameter
            return dict(self._result)

    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))

    result = waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=OldStyleClassifier()
    )

    assert result["detections"][0]["classification"] == "plastic_bottles"


def test_the_raw_argmax_is_reported_next_to_the_gated_answer(monkeypatch, tmp_path):
    """A withheld answer must be visible as a gate, not as a model that said nothing.

    The pipeline reports `classification: None` both when the classifier was unsure and when a gate
    refused a confident answer. Those are different faults, so the debug record carries what the
    network said alongside what the API returned.
    """
    patch_vision(monkeypatch, vision([detection("dog", 0.8)]))
    recorder = waste_debug.WasteDebugRecorder("probe", out_root=tmp_path)

    class CapturingStub(StubClassifier):
        def classify(self, image, capture=None):
            if capture is not None:
                capture["classes"] = ["plastic_bottles", "wood_waste"]
                capture["probabilities"] = [0.09, 0.91]
            return {
                "classification": "wood_waste", "classification_confidence": 0.91,
                "segregation": "biodegradable", "status": "confirmed",
                "handling": "organic", "display": "Wood waste",
            }

    waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=CapturingStub(), observer=recorder
    )
    entry = recorder.records[0]

    # The network was confident...
    assert entry["classifier"]["class"] == "wood_waste"
    assert entry["classifier"]["confidence"] == pytest.approx(0.91)
    # ...and the pipeline refused it, because a dog is not waste.
    assert entry["reported"]["classification"] is None
    assert entry["reported"]["status"] == "needs_review"


def test_the_saved_model_input_comes_from_the_captured_tensor(monkeypatch, tmp_path):
    """Case D is only diagnosable if the saved image IS the network's input.

    A separately-built "equivalent" crop would look correct in exactly the situation where
    preprocessing is the fault, so the artefact is rendered by inverting the normalisation on the
    tensor the classifier consumed.
    """
    import torch

    patch_vision(monkeypatch, vision([detection("bottle", 0.9)]))
    recorder = waste_debug.WasteDebugRecorder("probe", out_root=tmp_path)

    marker = torch.zeros(1, 3, 8, 8)
    marker[0, 0, :, :] = 5.0  # a value no ordinary crop produces, so its presence is traceable

    class TensorStub(StubClassifier):
        def classify(self, image, capture=None):
            if capture is not None:
                capture["tensor"] = marker
                capture["classes"] = ["plastic_bottles"]
                capture["probabilities"] = [1.0]
            return dict(self._result)

    waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=TensorStub(), observer=recorder
    )
    manifest = recorder.write(png_bytes(), "f.png")
    entry = manifest["detections"][0]

    saved = tmp_path / "classifier_crops" / "probe_WASTE-DET-001_model_input.png"
    assert saved.is_file()
    assert entry["model_input_path"].endswith("probe_WASTE-DET-001_model_input.png")

    from PIL import Image

    # Red saturated by the marker value, the other channels left at their normalised zero.
    pixel = Image.open(saved).convert("RGB").getpixel((4, 4))
    assert pixel[0] == 255 and pixel[1] < 255


def test_a_detector_with_no_findings_records_no_downstream_stages(monkeypatch, tmp_path):
    """Nothing detected means nothing was cropped, classified or mapped.

    This is the most informative debug result there is, so it must not be reported as an empty
    classification — the stages downstream never ran, and cannot be at fault.
    """
    patch_vision(monkeypatch, vision([]))
    recorder = waste_debug.WasteDebugRecorder("probe", out_root=tmp_path)

    waste_pipeline.analyze_waste(
        png_bytes(), "f.png", detector=object(), classifier=StubClassifier(), observer=recorder
    )
    manifest = recorder.write(png_bytes(), "f.png")

    assert manifest["detections"] == []
    assert manifest["raw_detections"] == 0


def test_results_index_keeps_snake_case_and_drops_inline_images(tmp_path):
    """`results.json` is read by people and scripts, in the field names the diagnosis was specified in."""
    manifest = {
        "stem": "probe", "original_image": "data:image/png;base64,AAA",
        "detections": [{"id": "WASTE-DET-001", "final_label": "metal_cans",
                        "crop_image": "data:image/png;base64,AAA", "crop_path": "x.png"}],
    }
    path = waste_debug.write_results_index([manifest], out_root=tmp_path)
    document = json.loads(path.read_text())

    run = document["runs"][0]
    assert "original_image" not in run
    assert "crop_image" not in run["detections"][0]
    assert run["detections"][0]["final_label"] == "metal_cans"


def test_camelize_converts_keys_and_never_values():
    """The wire format is camelCase, but a class name is data and must survive untouched."""
    out = waste_debug.camelize({
        "final_label": "plastic_bottles",
        "detections": [{"crop_path": "a/b_c.png", "detection_confidence": 0.5}],
    })

    assert out["finalLabel"] == "plastic_bottles"
    assert out["detections"][0]["cropPath"] == "a/b_c.png"
    assert out["detections"][0]["detectionConfidence"] == 0.5
