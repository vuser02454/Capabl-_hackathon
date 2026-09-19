"""Grad-CAM attribution is the model's own gradients, or it is nothing.

The failure mode these tests exist to prevent is a confident-looking heatmap with no
relationship to the model — a generated image, or a decorative gradient. Every check here ties
the explanation back to the same network that produced the prediction.
"""

import pytest

from services.waste.waste_classifier import get_waste_classifier
from services.waste.waste_xai import XaiUnavailable, explain, safe_explain

pytestmark = pytest.mark.skipif(
    not get_waste_classifier().is_configured(),
    reason="no trained waste classifier weights available",
)


@pytest.fixture
def crop():
    from pathlib import Path

    from PIL import Image

    root = Path(__file__).resolve().parents[2]
    return Image.open(root / "runs" / "debug_waste" / "classifier_crops" / "metal_can_WASTE-DET-001_crop.png")


def test_attribution_explains_the_prediction_that_was_actually_made(crop):
    """The explained class and confidence must equal what `classify` reports.

    If these ever diverge, the heatmap is explaining a different computation from the one the
    user is being shown — which is the whole risk with post-hoc attribution.
    """
    classifier = get_waste_classifier()
    predicted = classifier.classify(crop)
    attribution = explain(classifier, crop)

    assert attribution["available"] is True
    assert attribution["target_class"] == predicted["classification"]
    assert attribution["target_confidence"] == pytest.approx(
        predicted["classification_confidence"], abs=1e-3
    )


def test_attribution_is_class_conditional(crop):
    """A different target class must produce a different explanation.

    A saliency map that does not change with the class is not Grad-CAM — it is an edge detector,
    and it would explain every answer equally well, which is to say not at all.
    """
    classifier = get_waste_classifier()
    classes = classifier.classes
    first = explain(classifier, crop, target_index=classes.index("metal_cans"))
    second = explain(classifier, crop, target_index=classes.index("leaf_waste"))

    assert first["overlay_image"] != second["overlay_image"]
    assert first["target_confidence"] != second["target_confidence"]


def test_the_attribution_grid_is_reported(crop):
    """A 7x7 map upsampled for display must never be read as pixel-level precision."""
    attribution = explain(get_waste_classifier(), crop)
    assert attribution["attribution_grid"] == "7x7"
    assert attribution["layer"] == "features[-1]"
    assert attribution["method"] == "grad-cam"


def test_the_overlay_is_a_png_data_uri(crop):
    import base64

    attribution = explain(get_waste_classifier(), crop)
    uri = attribution["overlay_image"]
    assert uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert raw.startswith(b"\x89PNG"), "the overlay must be a real PNG"


def test_an_unavailable_classifier_yields_no_image_rather_than_a_fake_one(crop):
    """The point of the whole module: absence is reported, never substituted."""

    class Broken:
        def loaded_model(self):
            raise RuntimeError("weights missing")

    result = safe_explain(Broken(), crop)
    assert result["available"] is False
    assert result.get("overlay_image") is None
    assert result["message"]


def test_a_model_without_features_is_refused(crop):
    class NoFeatures:
        def loaded_model(self):
            class Bare:
                training = False

            return Bare(), [], lambda image: image

    result = safe_explain(NoFeatures(), crop)
    assert result["available"] is False
    assert result.get("overlay_image") is None
