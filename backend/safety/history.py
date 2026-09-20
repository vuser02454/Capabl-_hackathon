"""Geographic incident history — what has already happened near a location.

This is the evidence layer under the explainable assessment. Everything it returns is derived from
stored reports: counts are counted, hazards are the hazards those reports recorded, and every
claim carries the report ids it came from so an admin can open them. Nothing is generated.

The radius is the same 1 km the hotspot rule uses, so "previous incidents in this area" means the
same thing everywhere in the product.

The serious-incident section exists because a grave past event changes how a mild present report
should be read: three animal sightings near a place where someone was once killed by an animal is
a different situation from three animal sightings anywhere else. The module surfaces that link and
stops there — it states what is on record and what the current reports contain, and leaves the
inference to the safety officer.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from safety import domains
from safety.geo import HOTSPOT_RADIUS_METERS, haversine_meters

#: How many distinct reports must share a hazard before it is called recurring.
RECURRING_MIN = 2


def _coords(report: Dict[str, Any]) -> Optional[tuple]:
    lat, lon = report.get("latitude"), report.get("longitude")
    if lat is None or lon is None:
        return None
    return float(lat), float(lon)


def incidents_within(
    reports: List[Dict[str, Any]],
    latitude: float,
    longitude: float,
    radius_meters: int = HOTSPOT_RADIUS_METERS,
    exclude_ids: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """Stored reports within `radius_meters`, nearest first.

    `exclude_ids` drops the reports that make up the current incident, so "previous" really means
    previous rather than including the thing being looked at.
    """
    skip = set(exclude_ids or [])
    out: List[Dict[str, Any]] = []
    for report in reports:
        if report.get("id") in skip:
            continue
        position = _coords(report)
        if position is None:
            continue
        distance = haversine_meters(latitude, longitude, position[0], position[1])
        if distance <= radius_meters:
            out.append({**report, "distance_meters": round(distance)})
    out.sort(key=lambda item: item["distance_meters"])
    return out


def serious_incidents(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reports whose own text records something grave, with the phrase that identified it."""
    out: List[Dict[str, Any]] = []
    for report in reports:
        markers = domains.serious_incident_markers(report.get("report_text", ""))
        if markers:
            out.append({
                "report_id": report.get("id"),
                "markers": [marker["label"] for marker in markers],
                "evidence": markers[0]["evidence"],
                "risk_level": report.get("risk_level"),
                "reported_at": report.get("created_at"),
                "location": report.get("location") or report.get("location_text"),
                "distance_meters": report.get("distance_meters"),
            })
    return out


def summarise(
    reports: List[Dict[str, Any]],
    latitude: float,
    longitude: float,
    radius_meters: int = HOTSPOT_RADIUS_METERS,
    exclude_ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """The full history block for one location: counts, hazards, serious events, dates.

    Returns a well-formed empty block when there is no history, rather than omitting the section —
    "no previous reports within 1 km" is itself a useful answer.
    """
    nearby = incidents_within(reports, latitude, longitude, radius_meters, exclude_ids)

    levels = Counter(report.get("risk_level") for report in nearby if report.get("risk_level"))
    hazard_counts = Counter(
        hazard for report in nearby for hazard in (report.get("hazards") or [])
    )
    incident_types = Counter(
        report["incident_type"] for report in nearby if report.get("incident_type")
    )
    dates = sorted(report["created_at"] for report in nearby if report.get("created_at"))
    grave = serious_incidents(nearby)

    return {
        "radius_meters": radius_meters,
        "report_count": len(nearby),
        "risk_breakdown": {level: levels.get(level, 0) for level in ("HIGH", "MEDIUM", "LOW")},
        "recurring_hazards": [
            {"hazard": hazard, "count": count}
            for hazard, count in hazard_counts.most_common()
            if count >= RECURRING_MIN
        ],
        "all_hazards": [{"hazard": h, "count": c} for h, c in hazard_counts.most_common(10)],
        "incident_types": [{"type": t, "count": c} for t, c in incident_types.most_common()],
        "serious_incidents": grave,
        "serious_incident_count": len(grave),
        "first_report_at": dates[0] if dates else None,
        "latest_report_at": dates[-1] if dates else None,
        "report_ids": [report["id"] for report in nearby if report.get("id") is not None],
        "previous_recommendations": _previous_actions(nearby),
    }


def _previous_actions(reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Recommendations already recorded against nearby reports, newest first.

    Shown so an admin can see what was advised last time before advising it again.
    """
    out: List[Dict[str, Any]] = []
    for report in reports:
        recommendations = report.get("recommendations") or {}
        actions = recommendations.get("immediate_actions") or [] if isinstance(recommendations, dict) else []
        if actions:
            out.append({"report_id": report.get("id"), "actions": actions[:3],
                        "reported_at": report.get("created_at")})
    out.sort(key=lambda item: item.get("reported_at") or "", reverse=True)
    return out[:5]


def assessment(history: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """An explainable statement about the area, built only from `history` and `current`.

    Every sentence this produces is traceable to a count or a hazard name that came out of the
    database. Where the history and the current report point the same way it says so and stops;
    it does not conclude that the hazard is present, because a pattern in reports is evidence
    about reporting, not a measurement of the world.
    """
    count = history["report_count"]
    radius_km = history["radius_meters"] / 1000
    domain = current.get("domain")
    current_hazards = set(current.get("hazards") or [])

    if count == 0:
        return {
            "statement": f"No previous safety reports are on record within {radius_km:.0f} km of this location.",
            "findings": [],
            "serious_history": [],
            "evidence_report_ids": [],
            "basis": "stored reports",
        }

    breakdown = history["risk_breakdown"]
    findings: List[str] = [
        f"{count} previous safety report{'s' if count != 1 else ''} within {radius_km:.0f} km "
        f"({breakdown['HIGH']} HIGH, {breakdown['MEDIUM']} MEDIUM, {breakdown['LOW']} LOW)."
    ]

    recurring = history["recurring_hazards"]
    if recurring:
        top = ", ".join(f"{item['hazard']} ({item['count']})" for item in recurring[:4])
        findings.append(f"Recurring hazards on record: {top}.")

    # An overlap between what is being reported now and what has been reported before is the
    # single most useful thing to say, so it is called out explicitly.
    overlap = [item["hazard"] for item in history["all_hazards"] if item["hazard"] in current_hazards]
    if overlap:
        findings.append(
            f"The current report's hazard{'s' if len(overlap) != 1 else ''} "
            f"({', '.join(overlap)}) already appear{'s' if len(overlap) == 1 else ''} in this area's history."
        )

    serious = history["serious_incidents"]
    if serious:
        labels = sorted({label for item in serious for label in item["markers"]})
        ids = ", ".join(f"SR-{item['report_id']}" for item in serious[:5])
        findings.append(
            f"{len(serious)} previous report{'s' if len(serious) != 1 else ''} in this area "
            f"record a serious incident ({', '.join(labels)}): {ids}."
        )

    statement = " ".join(findings)

    # The domain-specific link, phrased as a relationship between records — never as a claim that
    # the hazard is currently present.
    relation = _relation(domain, serious, current_hazards)
    if relation:
        statement = f"{statement} {relation}"

    return {
        "statement": statement,
        "findings": findings,
        "serious_history": serious,
        "evidence_report_ids": history["report_ids"],
        "basis": "stored reports",
    }


#: How a grave past event of the same kind should be related to a current report. Worded as
#: "a previous X exists here, and the current report contains Y indicators" — a statement about
#: two records, not an assertion that the hazard is present right now.
_RELATION_TEMPLATES = {
    "WILDLIFE": ("Animal attack",
                 "A previous serious wildlife-related incident is on record in this geographic area, "
                 "and the current report contains wildlife indicators."),
    "FIRE": ("Fire",
             "A previous fire incident is on record in this geographic area, and the current report "
             "contains fire indicators."),
    "ELECTRICAL": ("Electrical incident",
                   "A previous electrical incident is on record in this geographic area, and the "
                   "current report contains electrical indicators."),
    "VIOLENCE_SECURITY": ("Security incident",
                          "A previous security incident is on record in this geographic area, and the "
                          "current report contains security indicators."),
    "CHEMICAL": ("Chemical exposure",
                 "A previous chemical exposure incident is on record in this geographic area, and the "
                 "current report contains chemical indicators."),
}


def _relation(domain: Optional[str], serious: List[Dict[str, Any]], hazards: set) -> Optional[str]:
    template = _RELATION_TEMPLATES.get(domain or "")
    if not template:
        return None
    marker, sentence = template
    present = any(marker in item["markers"] for item in serious)
    # A fatality near a wildlife report is the case this exists for, so it counts too.
    if domain == "WILDLIFE":
        present = present or any("Fatality" in item["markers"] for item in serious)
    return sentence if present else None
