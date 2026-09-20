"""Authoritative pollutant health thresholds, emission sources, and dynamic comparison engine.

Sources:
  - Primary health reference: WHO Global Air Quality Guidelines (2021)
  - Indian regulatory standard: CPCB National Ambient Air Quality Standards (NAAQS 2009)
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_METADATA_PATH = Path(__file__).resolve().parent.parent.parent / "shared" / "pollutant_metadata.json"

with open(_METADATA_PATH, "r", encoding="utf-8") as f:
    POLLUTANT_REGISTRY = json.load(f)

DISCLAIMER: str = POLLUTANT_REGISTRY.get("disclaimer", "")
POLLUTANTS: Dict[str, Dict[str, Any]] = POLLUTANT_REGISTRY.get("pollutants", {})


def normalize_unit(unit: str) -> str:
    """Normalize unit string for strict equality checks."""
    return (
        unit.strip()
        .lower()
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("³", "3")
        .replace(" ", "")
    )


def normalize_period(period: Optional[str]) -> str:
    """Normalize averaging period string for comparison."""
    if not period:
        return ""
    p = period.strip().lower().replace("_", "-").replace(" ", "-")
    if p in {"24h", "24hr", "24-hr", "24-hour", "daily", "day"}:
        return "24-hour"
    if p in {"8h", "8hr", "8-hr", "8-hour"}:
        return "8-hour"
    if p in {"1h", "1hr", "1-hr", "1-hour", "hourly"}:
        return "1-hour"
    if p in {"annual", "year", "1y", "1-year"}:
        return "annual"
    if p in {"instantaneous", "spot", "real-time", "instant"}:
        return "instantaneous"
    return p


def get_pollutant_info(key: str) -> Optional[Dict[str, Any]]:
    """Retrieve structured metadata for a given pollutant key (e.g. 'pm25', 'no2')."""
    return POLLUTANTS.get(key.lower())


def compare_to_reference(
    measured_value: Optional[float],
    measured_unit: str,
    measured_period: Optional[str],
    reference_value: Optional[float],
    reference_unit: str,
    reference_period: str,
    sub_score: Optional[float] = None,
) -> Dict[str, Any]:
    """Dynamically evaluate a measurement against an authoritative reference value.

    Guards:
      1. Units must match exactly.
      2. Averaging periods must be compatible.
      3. Measurement and reference must be present.
    """
    if measured_value is None or reference_value is None or reference_value <= 0:
        return {
            "status": "missing_data",
            "ratio": None,
            "difference": None,
            "percentage_difference": None,
            "interpretation_label": None,
            "note": "Measurement or reference guideline unavailable.",
            "is_compatible": False,
        }

    # Guard 1: Unit compatibility
    if normalize_unit(measured_unit) != normalize_unit(reference_unit):
        return {
            "status": "mismatch_units",
            "ratio": None,
            "difference": None,
            "percentage_difference": None,
            "interpretation_label": None,
            "note": f"Unit mismatch: measured in {measured_unit} while reference is in {reference_unit}.",
            "is_compatible": False,
        }

    # Guard 2: Averaging period compatibility
    norm_meas_period = normalize_period(measured_period)
    norm_ref_period = normalize_period(reference_period)

    if not norm_meas_period or norm_meas_period != norm_ref_period:
        return {
            "status": "mismatch_averaging_period",
            "ratio": None,
            "difference": None,
            "percentage_difference": None,
            "interpretation_label": None,
            "note": "Comparable WHO reference unavailable for this averaging period.",
            "is_compatible": False,
        }

    # Calculation
    ratio = round(measured_value / reference_value, 2)
    difference = round(measured_value - reference_value, 2)
    percentage_difference = round(((measured_value - reference_value) / reference_value) * 100.0, 1)

    # Classification label
    # Retain existing system's critical classification if sub_score >= 0.7 or ratio is severe
    if (sub_score is not None and sub_score >= 0.7) or ratio >= 3.0:
        label = "CRITICAL"
        desc = "Significantly above reference (Critical)"
    elif ratio >= 2.0:
        label = "SIGNIFICANTLY ABOVE REFERENCE"
        desc = "Significantly above reference"
    elif ratio > 1.0:
        label = "ABOVE GUIDELINE REFERENCE"
        desc = "Above the WHO guideline reference"
    else:
        label = "WITHIN GUIDELINE REFERENCE"
        desc = "Within the WHO guideline reference"

    return {
        "status": "compatible",
        "ratio": ratio,
        "difference": difference,
        "percentage_difference": percentage_difference,
        "interpretation_label": label,
        "interpretation_description": desc,
        "note": f"{ratio}× the reference ({'+' if difference >= 0 else ''}{difference} {measured_unit}, {'+' if percentage_difference >= 0 else ''}{percentage_difference}%)",
        "is_compatible": True,
    }


def generate_contextual_sources(
    pollutant_key: str,
    geographic_context: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """Build contextual emissions source statements without falsely claiming facility causation."""
    meta = get_pollutant_info(pollutant_key)
    if not meta:
        return []

    sources = list(meta.get("primary_sources", []))

    # If geographic context exists, add guarded contextual inferences
    if geographic_context and getattr(geographic_context, "available", False):
        roads = getattr(geographic_context, "roads", [])
        industries = getattr(geographic_context, "industrial_features", [])

        if roads and pollutant_key in {"pm25", "pm10", "no2", "co"}:
            closest_road = min((r.distance_km for r in roads), default=None)
            dist_str = f" (~{closest_road:.1f} km away)" if closest_road is not None else ""
            sources.append({
                "category": "Nearby Road Infrastructure (Contextual)",
                "description": f"Nearby road traffic{dist_str} is a potential source category for NO₂ and particulate matter. Contextual inference only — not measured facility attribution.",
                "icon": "Navigation",
                "is_contextual": True,
            })

        if industries and pollutant_key in {"pm25", "pm10", "so2", "no2"}:
            closest_ind = min((i.distance_km for i in industries), default=None)
            dist_str = f" (~{closest_ind:.1f} km away)" if closest_ind is not None else ""
            sources.append({
                "category": "Nearby Industrial Area (Contextual)",
                "description": f"Nearby industrial zones{dist_str} represent potential source categories for combustion and process emissions. Contextual inference only — not measured facility attribution.",
                "icon": "Factory",
                "is_contextual": True,
            })

    return sources
