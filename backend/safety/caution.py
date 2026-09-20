"""Worker-facing caution, and the pattern level a location has reached.

This module draws the line between four things the product must never blur:

    ONE REPORT          an incident. Analysed and explained to the admin. No pattern claimed.
    EMERGING PATTERN    2 related reports nearby. Admin sees it; workers may see a generic
                        caution. NOTHING is published and routing does not change.
    CANDIDATE HOTSPOT   3+ related reports within 1 km. A PENDING_REVIEW row for the admin.
                        Still invisible to workers, still no effect on routing.
    PUBLISHED ALERT     a human pressed Publish. Worker-visible, and the only thing that may
                        influence a route.

The two rules that make this safe are both structural rather than conventional:

1. `worker_cautions()` returns text with no report ids, no reporter, no hazard-by-hazard
   breakdown and no count. A worker learns that *something* was reported nearby, which is what
   lets them be careful, and nothing that identifies who reported it or what they wrote.

2. Nothing in this module is consulted by `safety.routing`. A caution cannot alter a route
   because the routing code never imports it — only PUBLISHED announcements reach the router.
   A regression test asserts exactly that.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from safety.geo import (
    HOTSPOT_MIN_REPORTS,
    HOTSPOT_RADIUS_METERS,
    are_related,
    haversine_meters,
)

#: How close a worker must be to a cluster of reports before a caution is worth showing. Smaller
#: than the hotspot radius: a hotspot is an analytical grouping, a caution is advice to somebody
#: standing somewhere, and 1 km of "be careful" would cover most of a site.
CAUTION_RADIUS_METERS = 500

#: Fewer related reports than a hotspot needs. One report is enough to be worth a word of caution;
#: three is enough to become a candidate hotspot, which is a different mechanism.
CAUTION_MIN_REPORTS = 1

PATTERN_NONE = "no_pattern"
PATTERN_EMERGING = "emerging"
PATTERN_CANDIDATE = "candidate_hotspot"

PATTERN_LABEL = {
    PATTERN_NONE: "No recurring pattern established",
    PATTERN_EMERGING: "Emerging pattern",
    PATTERN_CANDIDATE: "Candidate hotspot",
}


def _located(reports: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in reports
            if r.get("latitude") is not None and r.get("longitude") is not None]


def related_reports(
    reports: Sequence[Dict[str, Any]],
    subject: Dict[str, Any],
    radius_meters: int = HOTSPOT_RADIUS_METERS,
) -> List[Dict[str, Any]]:
    """Stored reports that are both near `subject` and share a hazard family with it.

    The same two-part test the hotspot rule uses — proximity alone groups a broken light with an
    oil spill — applied to one report rather than to the whole corpus.
    """
    if subject.get("latitude") is None or subject.get("longitude") is None:
        return []
    out: List[Dict[str, Any]] = []
    for report in _located(reports):
        if report.get("id") == subject.get("id"):
            continue
        distance = haversine_meters(
            float(subject["latitude"]), float(subject["longitude"]),
            float(report["latitude"]), float(report["longitude"]))
        if distance <= radius_meters and are_related(subject, report):
            out.append({**report, "distance_meters": round(distance)})
    out.sort(key=lambda item: item["distance_meters"])
    return out


def pattern_status(
    reports: Sequence[Dict[str, Any]],
    subject: Dict[str, Any],
    radius_meters: int = HOTSPOT_RADIUS_METERS,
) -> Dict[str, Any]:
    """Which of the three levels this report's surroundings have reached.

    Counts the subject itself, because "2 related reports" means two incidents exist, not two
    others besides this one. Off-by-one here would report an emerging pattern for a lone incident.
    """
    related = related_reports(reports, subject, radius_meters)
    total = len(related) + 1  # the subject counts toward its own pattern

    if total >= HOTSPOT_MIN_REPORTS:
        level = PATTERN_CANDIDATE
        summary = (f"Candidate hotspot — {total} related reports within "
                   f"{radius_meters} m. Awaiting safety-admin review.")
    elif total == 2:
        level = PATTERN_EMERGING
        summary = (f"Emerging pattern — {total} related reports nearby. "
                   f"Below the {HOTSPOT_MIN_REPORTS}-report threshold for a candidate hotspot.")
    else:
        level = PATTERN_NONE
        summary = "No recurring pattern established — this is the only related report on record."

    # Precursor assessment grounded in stored evidence
    near_miss_indicators = False
    all_cluster = [subject] + related
    for rep in all_cluster:
        txt = (rep.get("report_text") or "").lower()
        if any(term in txt for term in ("near miss", "near-miss", "nearly", "almost", "narrowly", "could have", "slip", "trip")):
            near_miss_indicators = True
            break

    precursor: Optional[str] = None
    if total >= 2:
        if near_miss_indicators:
            precursor = (
                "Possible incident precursor — repeated near-miss reports may indicate "
                "an emerging safety precursor in this area."
            )
        else:
            precursor = (
                f"Possible incident precursor — {total} related reports may indicate "
                "an emerging safety precursor in this area."
            )

    return {
        "level": level,
        "label": PATTERN_LABEL[level],
        "related_count": total,
        "summary": summary,
        "precursor": precursor,
        # Admin-side evidence. Never included in a worker payload.
        "related_report_ids": [r["id"] for r in related],
        "radius_meters": radius_meters,
        "creates_hotspot": level == PATTERN_CANDIDATE,
        # Stated explicitly because it is the question this module exists to answer.
        "affects_routing": False,
        "routing_note": ("Only a published safety alert can affect routing. A pattern at any "
                         "level does not."),
    }


def worker_cautions(
    reports: Sequence[Dict[str, Any]],
    latitude: float,
    longitude: float,
    radius_meters: int = CAUTION_RADIUS_METERS,
) -> List[Dict[str, Any]]:
    """Generic cautions for a worker standing at a point.

    Deliberately thin. Each entry carries an area name and a hazard family and nothing else: no
    report ids, no counts, no report text, no reporter, no risk score, no pattern level. A worker
    who can see "3 reports" can infer how many colleagues reported a thing, and a worker who can
    see the hazard list can often infer who reported it. The value to them is the same either way
    — be careful here — so the extra detail is cost without benefit.
    """
    nearby: Dict[str, Dict[str, Any]] = {}
    for report in _located(reports):
        distance = haversine_meters(latitude, longitude,
                                    float(report["latitude"]), float(report["longitude"]))
        if distance > radius_meters:
            continue
        hazards = report.get("hazards") or []
        family = hazards[0] if hazards else "a safety issue"
        area = report.get("location") or report.get("location_text") or "this area"
        key = f"{area}|{family}"
        # One caution per area+hazard, keeping the nearest. Repeating it per report would leak
        # the count through the length of the list.
        if key not in nearby or distance < nearby[key]["_distance"]:
            nearby[key] = {
                "area": area,
                "hazard": family,
                "message": ("A similar safety incident has been reported nearby. "
                            "Exercise caution while passing through this area."),
                "severity": "CAUTION",
                "_distance": distance,
            }

    out = sorted(nearby.values(), key=lambda item: item["_distance"])
    for item in out:
        item.pop("_distance", None)
    return out
