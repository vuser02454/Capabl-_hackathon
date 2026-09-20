"""Tests for Air Quality health thresholds, WHO 2021 AQG vs CPCB NAAQS, health effects, and emission sources."""

import pytest
from data.pollutant_metadata import (
    DISCLAIMER,
    compare_to_reference,
    generate_contextual_sources,
    get_pollutant_info,
)


def test_1_pm25_91_with_24h_who_reference_15():
    result = compare_to_reference(
        measured_value=91.0,
        measured_unit="µg/m³",
        measured_period="24-hour",
        reference_value=15.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
        sub_score=0.91,
    )
    assert result["is_compatible"] is True
    assert result["status"] == "compatible"
    assert result["ratio"] == 6.07
    assert result["difference"] == 76.0
    assert result["percentage_difference"] == 506.7
    assert result["interpretation_label"] == "CRITICAL"
    assert "Within" not in result["interpretation_description"]
    assert "safe" not in result["note"].lower()


def test_2_pm10_165_with_24h_who_reference_45():
    result = compare_to_reference(
        measured_value=165.0,
        measured_unit="µg/m³",
        measured_period="24-hour",
        reference_value=45.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
        sub_score=0.92,
    )
    assert result["is_compatible"] is True
    assert result["ratio"] == 3.67
    assert result["difference"] == 120.0
    assert result["percentage_difference"] == 266.7
    assert result["interpretation_label"] == "CRITICAL"


def test_3_no2_42_with_24h_who_reference_25():
    result = compare_to_reference(
        measured_value=42.0,
        measured_unit="µg/m³",
        measured_period="24-hour",
        reference_value=25.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
        sub_score=0.53,
    )
    assert result["is_compatible"] is True
    assert result["ratio"] == 1.68
    assert result["difference"] == 17.0
    assert result["percentage_difference"] == 68.0
    assert result["interpretation_label"] == "ABOVE GUIDELINE REFERENCE"


def test_4_o3_31_with_8h_who_reference_100():
    result = compare_to_reference(
        measured_value=31.0,
        measured_unit="µg/m³",
        measured_period="8-hour",
        reference_value=100.0,
        reference_unit="µg/m³",
        reference_period="8-hour",
        sub_score=0.31,
    )
    assert result["is_compatible"] is True
    assert result["ratio"] == 0.31
    assert result["difference"] == -69.0
    assert result["percentage_difference"] == -69.0
    assert result["interpretation_label"] == "WITHIN GUIDELINE REFERENCE"
    # Never claim "100% safe"
    assert "100% safe" not in result["interpretation_description"]
    assert "Within the WHO guideline reference" in result["interpretation_description"]


def test_5_unit_mismatch():
    result = compare_to_reference(
        measured_value=4.0,
        measured_unit="mg/m³",
        measured_period="24-hour",
        reference_value=15.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
    )
    assert result["is_compatible"] is False
    assert result["status"] == "mismatch_units"
    assert result["ratio"] is None
    assert "Unit mismatch" in result["note"]


def test_6_averaging_period_mismatch():
    # 1-hour measurement compared to 24-hour WHO reference
    result = compare_to_reference(
        measured_value=91.0,
        measured_unit="µg/m³",
        measured_period="1-hour",
        reference_value=15.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
    )
    assert result["is_compatible"] is False
    assert result["status"] == "mismatch_averaging_period"
    assert result["ratio"] is None
    assert result["note"] == "Comparable WHO reference unavailable for this averaging period."


def test_7_missing_guideline():
    result = compare_to_reference(
        measured_value=50.0,
        measured_unit="µg/m³",
        measured_period="24-hour",
        reference_value=None,
        reference_unit="µg/m³",
        reference_period="24-hour",
    )
    assert result["is_compatible"] is False
    assert result["status"] == "missing_data"
    assert result["ratio"] is None


def test_8_missing_measurement():
    result = compare_to_reference(
        measured_value=None,
        measured_unit="µg/m³",
        measured_period="24-hour",
        reference_value=15.0,
        reference_unit="µg/m³",
        reference_period="24-hour",
    )
    assert result["is_compatible"] is False
    assert result["status"] == "missing_data"
    assert result["ratio"] is None


def test_9_o3_secondary_pollutant_metadata():
    o3_meta = get_pollutant_info("o3")
    assert o3_meta is not None
    assert o3_meta["is_secondary_pollutant"] is True
    assert o3_meta["source_type"] == "secondary"
    assert "NOₓ" in str(o3_meta["precursor_pollutants"])
    assert "VOCs" in str(o3_meta["precursor_pollutants"])
    assert "direct emissions" not in o3_meta["description"].lower() or "not by direct emissions" in o3_meta["description"].lower()


def test_10_source_attribution_must_not_claim_specific_facility():
    class DummyFeature:
        def __init__(self, name, distance_km):
            self.name = name
            self.distance_km = distance_km

    class DummyGeoContext:
        available = True
        roads = [DummyFeature("Outer Ring Road", 0.4)]
        industrial_features = [DummyFeature("Local Industrial Estate", 1.2)]

    sources = generate_contextual_sources("pm25", DummyGeoContext())
    categories = [s["category"] for s in sources]
    descriptions = " ".join([s["description"] for s in sources])

    # Contextual features included
    assert any("Nearby Road" in c for c in categories)
    assert any("Nearby Industrial" in c for c in categories)

    # Must include cautious disclaimer words
    assert "potential source category" in descriptions.lower()
    assert "not measured facility attribution" in descriptions.lower() or "contextual inference only" in descriptions.lower()

    # Must NOT claim that a specific factory caused the pollution
    assert "this factory caused" not in descriptions.lower()
    assert "caused the current" not in descriptions.lower()


def test_health_disclaimer_present():
    assert "not a medical diagnosis" in DISCLAIMER.lower()
    assert "published air-quality guidance" in DISCLAIMER.lower()
