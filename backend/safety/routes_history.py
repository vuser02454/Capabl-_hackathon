"""Persisting worker routing decisions, and classifying them.

A route event is created by exactly one thing: a worker explicitly calling POST /api/worker/route.
The calculation IS the event. There is no scheduler, no `watchPosition`, no background writer —
this is a record of a decision the worker asked for, not a trail of where they went.

WHAT IS STORED, AND WHY THE GEOMETRY MATTERS
--------------------------------------------
The full ordered coordinate list of both the original shortest route and the route actually
selected. Recomputing a route later from start + destination would produce today's answer over
today's map with today's alerts — which is exactly what historical evidence must not do. If an
admin later asks "did EMP007's route pass through this area", the answer has to come from the
geometry that was served at the time.

CLASSIFICATION IS DETERMINISTIC
-------------------------------
Four categories, decided by the routing result and the published alert's own severity. No model
is involved, and none can be: `classify()` takes a dict and returns a string.

    NORMAL_ROUTE             no published alert came within the route safety radius
    MODERATE_HAZARD_PASSED   the selected route runs through a published alert's safety area,
                             but no detour was needed or taken
    HIGH_HAZARD_DETOUR       the shortest route was rejected over a HIGH-severity alert and an
                             alternative was selected
    NO_SAFE_ALTERNATIVE      the route was affected and nothing clear could be found

Severity reuses the existing LOW / MEDIUM / HIGH values already carried by `safety_announcement`;
no new severity scale is introduced.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from safety import store

logger = logging.getLogger(__name__)

NORMAL_ROUTE = "NORMAL_ROUTE"
MODERATE_HAZARD_PASSED = "MODERATE_HAZARD_PASSED"
HIGH_HAZARD_DETOUR = "HIGH_HAZARD_DETOUR"
NO_SAFE_ALTERNATIVE = "NO_SAFE_ALTERNATIVE"

CLASSIFICATIONS = (NORMAL_ROUTE, MODERATE_HAZARD_PASSED, HIGH_HAZARD_DETOUR, NO_SAFE_ALTERNATIVE)

CLASSIFICATION_LABEL = {
    NORMAL_ROUTE: "Normal route",
    MODERATE_HAZARD_PASSED: "Passed a published hazard",
    HIGH_HAZARD_DETOUR: "Rerouted around a high-severity hazard",
    NO_SAFE_ALTERNATIVE: "No clear alternative available",
}

#: Which severities count as high for classification. Reuses the existing announcement values.
HIGH_SEVERITIES = frozenset({"HIGH", "CRITICAL"})


def _worst_alert(alerts: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The alert that best explains the decision: highest severity, then nearest."""
    if not alerts:
        return None
    order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    return sorted(
        alerts,
        key=lambda a: (order.get((a.get("severity") or "").upper(), 9),
                       a.get("closest_approach_meters", 10 ** 9)),
    )[0]


def classify(result: Dict[str, Any]) -> str:
    """Categorise one routing result. Pure, deterministic, no model.

    Reads only fields `safety.routing` already computes, so the classification cannot disagree
    with the route it describes.
    """
    blocking = result.get("blocking_alerts") or []
    near = result.get("alerts_near_route") or []
    selected = result.get("selected")

    if selected == "none_clear":
        return NO_SAFE_ALTERNATIVE

    if result.get("adjusted_for_safety"):
        worst = _worst_alert(blocking)
        severity = (worst or {}).get("severity", "")
        # A detour taken around a lower-severity alert is still a detour, but it is not the
        # "high hazard" case an admin is looking for, so it is not labelled as one.
        return (HIGH_HAZARD_DETOUR if (severity or "").upper() in HIGH_SEVERITIES
                else MODERATE_HAZARD_PASSED)

    # Not adjusted. Either nothing was near, or the route runs past something published.
    return MODERATE_HAZARD_PASSED if near else NORMAL_ROUTE


def record(
    result: Dict[str, Any],
    start: Dict[str, float],
    destination: Dict[str, float],
    employee_id: Optional[str],
    worker_id: Optional[int],
    path=None,
) -> Optional[int]:
    """Persist one route event. Returns its id, or None when there was nothing to record.

    Never raises into the request: a worker's route must be returned even if the audit write
    fails, so a storage problem costs the record rather than the answer.
    """
    if not result.get("found"):
        return None

    try:
        near = result.get("alerts_near_route") or []
        blocking = result.get("blocking_alerts") or []
        worst = _worst_alert(blocking) or _worst_alert(near)
        classification = classify(result)

        return store.record_route_event({
            "worker_id": worker_id,
            "employee_id": employee_id,
            "start_latitude": start["latitude"],
            "start_longitude": start["longitude"],
            "destination_latitude": destination["latitude"],
            "destination_longitude": destination["longitude"],
            "original_distance_meters": result.get("original_distance_meters"),
            # The shortest route, whether or not it was the one served. NOT defaulted to the
            # selected route: a branch that forgot to supply it would then silently record
            # "original == selected", which reads as evidence that no detour happened.
            "original_route_geometry": result.get("original_route_geometry", []),
            "selected_distance_meters": result.get("selected_distance_meters"),
            "selected_route_geometry": result.get("route") or [],
            "route_adjusted_for_safety": bool(result.get("route_adjusted_for_safety")),
            "safe_alternative_found": result.get("safe_alternative_found"),
            "selected_reason": result.get("selected_reason"),
            "alerts_near_route": near,
            "affecting_alert_id": (worst or {}).get("id"),
            "affecting_alert_title": (worst or {}).get("title"),
            "affecting_alert_severity": (worst or {}).get("severity"),
            "affecting_alert_latitude": (worst or {}).get("latitude"),
            "affecting_alert_longitude": (worst or {}).get("longitude"),
            "affecting_alert_radius_meters": (worst or {}).get("radius_meters"),
            "minimum_distance_to_alert_meters": (worst or {}).get("closest_approach_meters"),
            "detour_distance_meters": result.get("additional_distance_meters", 0),
            "detour_ratio": result.get("detour_ratio", 1.0),
            "classification": classification,
            "safety_radius_meters": result.get("safety_radius_meters"),
        }, path=path)
    except Exception:  # noqa: BLE001
        logger.exception("route_event_not_recorded employee=%s", employee_id)
        return None


def summarise(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Counts for the admin's route-intelligence view. Every number is a count of stored rows."""
    counts = {name: 0 for name in CLASSIFICATIONS}
    for event in events:
        name = event.get("classification")
        if name in counts:
            counts[name] += 1
    return {
        "total": len(events),
        # A LIST, not a dict keyed by the enum: the API's recursive camelCase conversion is for
        # field names, and it mangled "NORMAL_ROUTE" into "NORMALRoute" when it was used as a key.
        "by_classification": [{"classification": name, "label": CLASSIFICATION_LABEL[name],
                               "count": counts[name]} for name in CLASSIFICATIONS],
        "normal": counts[NORMAL_ROUTE],
        "moderate_hazard": counts[MODERATE_HAZARD_PASSED],
        "high_hazard_detour": counts[HIGH_HAZARD_DETOUR],
        "no_safe_alternative": counts[NO_SAFE_ALTERNATIVE],
        "workers_affected": len({e["employee_id"] for e in events
                                 if e.get("employee_id")
                                 and e.get("classification") != NORMAL_ROUTE}),
        "alerts_involved": len({e["affecting_alert_id"] for e in events
                                if e.get("affecting_alert_id") is not None}),
        # Stated plainly wherever this is rendered: route history begins when the feature did.
        "coverage_note": ("Route events are recorded from the moment a worker requests a route. "
                          "No history exists for routes calculated before this was introduced."),
    }
