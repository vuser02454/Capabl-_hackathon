"""A waste label is asserted only when a model cleared the bar FOR THAT LABEL.

The detector-authority path used to set `status="confirmed"` from the existence of a category
mapping alone, never reading the detector's own confidence. A person in a frame, detected as
`paper_waste` at 39% with the classifier below its threshold at 57%, came back as a *confirmed*
`biodegradable` object carrying a message that read "the classifier did not confirm a label".
"""

from services.waste.waste_pipeline import _apply_detector_authority, _assertion_threshold


class StubClassifier:
    """Just the configuration surface `_apply_detector_authority` reads."""

    config = {
        "classes": {
            "paper_waste": {"category": "biodegradable", "handling": "fibre_recyclable", "display": "Paper waste"},
            "metal_cans": {"category": "non_biodegradable", "handling": "recyclable", "display": "Metal cans"},
        },
        "handling_notes": {
            "fibre_recyclable": "Degrades naturally, and recoverable as fibre while it is still dry and clean.",
            "recyclable": "Non-degrading but widely recoverable through recycling streams.",
        },
        "thresholds": {"classification_confidence": 0.60},
    }

    def segregation_for(self, class_name):
        entry = self.config["classes"].get(class_name, {})
        return {"category": entry.get("category"), "handling": entry.get("handling"), "display": entry.get("display")}


def record(detection_confidence, classification=None, classification_confidence=None, status="confirmed"):
    return {
        "id": "WASTE-DET-001",
        "detected_object": "paper_waste",
        "detection_confidence": detection_confidence,
        "classification": classification,
        "classification_confidence": classification_confidence,
        "status": status,
    }


def test_the_assertion_bar_is_the_configured_threshold():
    assert _assertion_threshold(StubClassifier()) == 0.60


def test_a_weak_detection_is_not_confirmed():
    """The exact case that was wrong: both models unsure, answer asserted anyway."""
    r = record(0.395, classification=None, classification_confidence=0.5673, status="needs_review")
    _apply_detector_authority(r, "paper_waste", StubClassifier())

    assert r["status"] == "needs_review"
    assert r["segregation"] == "uncertain"
    assert r["classification"] is None
    # The guess stays visible for a reviewer — withheld, not discarded.
    assert r["candidate"] == "paper_waste"
    # No policy note may ride along on a claim that was not made.
    assert r["environmental_note"] is None


def test_a_weak_detection_does_not_hand_the_label_to_a_loud_classifier():
    """On `paper.jpg` the classifier says ewaste at 85% against the detector's paper_waste at 53%.

    Asserting `ewaste` would route paper to hazardous handling with a confident-looking number
    on it. These are the disagreements the classifier loses 6-22 on the held-out split.
    """
    r = record(0.529, classification="ewaste", classification_confidence=0.8503)
    _apply_detector_authority(r, "paper_waste", StubClassifier())

    assert r["classification"] != "ewaste"
    assert r["status"] == "needs_review"
    assert r["segregation"] == "uncertain"
    assert "ewaste" in r["message"]


def test_a_confident_detection_is_still_confirmed():
    """The fix must not cost the measured detector-authority win."""
    r = record(0.937, classification=None, status="needs_review")
    _apply_detector_authority(r, "metal_cans", StubClassifier())

    assert r["status"] == "confirmed"
    assert r["classification"] == "metal_cans"
    assert r["segregation"] == "non_biodegradable"
    assert r["label_source"] == "detector"


def test_agreement_leaves_the_classifier_as_the_source():
    r = record(0.8, classification="metal_cans", classification_confidence=0.9)
    _apply_detector_authority(r, "metal_cans", StubClassifier())

    assert r["label_source"] == "classifier"
    assert r["status"] == "confirmed"


def test_paper_is_not_described_as_non_degrading():
    """`handling_notes` is keyed by handling, so paper once read 'biodegradable' and
    'non-degrading' on the same card."""
    classifier = StubClassifier()
    mapping = classifier.segregation_for("paper_waste")
    note = classifier.config["handling_notes"][mapping["handling"]]

    assert mapping["category"] == "biodegradable"
    assert "non-degrading" not in note.lower()
