"""Geographic hotspot detection: distance, clustering, and the 1 km rule.

Entirely deterministic. No language model is consulted for any geographic decision — distance,
membership, cluster formation and the report threshold are arithmetic, and the same reports always
produce the same hotspot. The LLM may later describe a hotspot in prose; it never decides that one
exists.

The rule, in one line: THREE OR MORE RELATED reports within ONE KILOMETRE form a candidate hotspot.

Both halves are load-bearing. Proximity alone would merge an oil spill, a broken light and a noise
complaint into a single "hazard" because they happen to share a car park — three unrelated problems
reported as one, which is worse than reporting none. So clustering requires a shared hazard family
as well as shared ground.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# --- the thresholds, defined once ------------------------------------------------------------
#
# Application-level demo thresholds, not a regulatory standard. Every consumer imports these;
# the numbers appear nowhere else in the codebase.

#: A candidate hotspot needs at least this many RELATED reports.
HOTSPOT_MIN_REPORTS = 3

#: ...all within this radius of one another. Exactly one kilometre.
HOTSPOT_RADIUS_METERS = 1000

EARTH_RADIUS_METERS = 6_371_000.0

#: Hazards that describe the same underlying problem. Membership in a family is what makes three
#: reports "related" rather than merely nearby. A hazard absent from every family is related only
#: to itself, which is the safe default — it can still form a hotspot with identical hazards.
HAZARD_FAMILIES: Dict[str, Set[str]] = {
    "slip_hazard": {"Oil spill", "Slip / trip / fall", "Wet surface", "Housekeeping"},
    "vehicle": {"Vehicle / forklift"},
    "electrical": {"Electrical hazard", "Fire / ignition", "Overheating"},
    "chemical": {"Chemical exposure"},
    "ppe": {"Missing PPE"},
    "machine": {"Machine guarding", "Equipment failure"},
    "height": {"Working at height"},
    "egress": {"Blocked egress"},
    "handling": {"Manual handling"},
    "confined": {"Confined space"},
    "noise": {"Noise exposure"},
}

#: Human-readable name per family, used for `primary_hazard` when several hazards share one.
FAMILY_LABEL = {
    "slip_hazard": "Oil spill / slip hazard",
    "vehicle": "Vehicle / forklift hazard",
    "electrical": "Electrical / fire hazard",
    "chemical": "Chemical exposure",
    "ppe": "PPE non-compliance",
    "machine": "Machine / equipment hazard",
    "height": "Work at height",
    "egress": "Blocked emergency egress",
    "handling": "Manual handling",
    "confined": "Confined space",
    "noise": "Noise exposure",
}


def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres.

    Haversine rather than a flat-earth approximation: at the scale of a single site the difference
    is small, but the threshold is an exact 1000 m and a cluster should not gain or lose a member
    because of the projection used to measure it.
    """
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_METERS * math.asin(min(1.0, math.sqrt(a)))


def families_for(hazards: Iterable[str]) -> Set[str]:
    """Which hazard families a report belongs to. An unrecognised hazard forms its own family."""
    found: Set[str] = set()
    for hazard in hazards or []:
        matched = False
        for family, members in HAZARD_FAMILIES.items():
            if hazard in members:
                found.add(family)
                matched = True
        if not matched:
            found.add(f"other:{hazard}")
    return found


def are_related(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Do these two reports describe the same kind of problem?"""
    return bool(families_for(a.get("hazards") or []) & families_for(b.get("hazards") or []))


def _centroid(points: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    """Mean latitude/longitude. Adequate at sub-kilometre scale and trivially explainable."""
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def _geolocated(reports: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for report in reports:
        lat, lon = report.get("latitude"), report.get("longitude")
        if lat is None or lon is None:
            continue
        try:
            report = {**report, "latitude": float(lat), "longitude": float(lon)}
        except (TypeError, ValueError):
            continue
        out.append(report)
    return out


def find_clusters(reports: Iterable[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group reports that are BOTH within `HOTSPOT_RADIUS_METERS` AND share a hazard family.

    Single-link agglomeration over the related-and-near graph: two reports join the same cluster
    when they are directly related-and-near, or connected through a chain of such pairs. This is
    deterministic — reports are processed in id order and the result does not depend on which
    report happened to be seen first, unlike comparing everything against report #1.

    A cluster is returned whatever its size; the caller applies `HOTSPOT_MIN_REPORTS`.
    """
    items = sorted(_geolocated(reports), key=lambda r: r.get("id") or 0)
    n = len(items)
    if n == 0:
        return []

    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for i in range(n):
        for j in range(i + 1, n):
            near = haversine_meters(
                items[i]["latitude"], items[i]["longitude"],
                items[j]["latitude"], items[j]["longitude"],
            ) <= HOTSPOT_RADIUS_METERS
            if near and are_related(items[i], items[j]):
                union(i, j)

    grouped: Dict[int, List[Dict[str, Any]]] = {}
    for index, item in enumerate(items):
        grouped.setdefault(find(index), []).append(item)
    # Ordered by size then by earliest member, so the output is stable across runs.
    return sorted(grouped.values(), key=lambda c: (-len(c), c[0].get("id") or 0))


_RISK_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


def summarise_cluster(cluster: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Turn a cluster into the hotspot record, with the evidence that justifies it."""
    points = [(r["latitude"], r["longitude"]) for r in cluster]
    lat, lon = _centroid(points)

    hazard_counts: Counter = Counter()
    for report in cluster:
        for hazard in report.get("hazards") or []:
            hazard_counts[hazard] += 1

    family_counts: Counter = Counter()
    for report in cluster:
        for family in families_for(report.get("hazards") or []):
            family_counts[family] += 1
    top_family = family_counts.most_common(1)[0][0] if family_counts else None
    primary = FAMILY_LABEL.get(top_family or "", None)
    if not primary:
        primary = hazard_counts.most_common(1)[0][0] if hazard_counts else "Unclassified hazard"

    levels = [r.get("risk_level") for r in cluster if r.get("risk_level")]
    risk_level = max(levels, key=lambda lv: _RISK_ORDER.get(lv, 0)) if levels else "LOW"

    times = sorted(t for t in (r.get("created_at") for r in cluster) if t)
    # The furthest any member sits from the centroid — the actual spread, not the rule's radius.
    spread = max(haversine_meters(lat, lon, p[0], p[1]) for p in points) if points else 0.0

    return {
        "latitude": round(lat, 6),
        "longitude": round(lon, 6),
        "radius_meters": HOTSPOT_RADIUS_METERS,
        "report_count": len(cluster),
        "primary_hazard": primary,
        "related_hazards": [h for h, _ in hazard_counts.most_common(6)],
        "risk_level": risk_level,
        "first_report_at": times[0] if times else None,
        "latest_report_at": times[-1] if times else None,
        "report_ids": [r.get("id") for r in cluster],
        "locations": sorted({r["location"] for r in cluster if r.get("location")}),
        "max_spread_meters": round(spread, 1),
        "explanation": (
            f"{len(cluster)} related reports within {HOTSPOT_RADIUS_METERS} m "
            f"(furthest member {round(spread)} m from centre). "
            f"Shared hazard family: {primary}."
        ),
    }


def detect_hotspots(reports: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Candidate hotspots: clusters meeting BOTH the count and the radius rule."""
    return [
        summarise_cluster(cluster)
        for cluster in find_clusters(reports)
        if len(cluster) >= HOTSPOT_MIN_REPORTS
    ]


def rule_description() -> Dict[str, Any]:
    """The threshold, for the UI to state rather than hardcode."""
    return {
        "min_reports": HOTSPOT_MIN_REPORTS,
        "radius_meters": HOTSPOT_RADIUS_METERS,
        "summary": (
            f"Candidate hotspot: {HOTSPOT_MIN_REPORTS}+ related reports within a "
            f"{HOTSPOT_RADIUS_METERS // 1000} km radius."
        ),
        "disclaimer": "Application/demo threshold, not a regulatory standard.",
    }
