"""The only database access the safety chatbot has.

The model never writes SQL and never touches the store directly. It picks a tool from this
module by name; the tool runs a fixed query and returns a structured result; the model is then
given that result and asked to phrase it. Anything it cannot get from a tool, it cannot say.

Two boundaries are enforced here rather than in the prompt, because a prompt is a request and
this is a rule:

READ ONLY. Every function selects. None writes, publishes, dismisses, resolves, changes a
severity or contacts anybody. The chatbot is explanatory; the Safety Admin decides.

ROLE SCOPING. `WORKER_TOOLS` is a strict subset of `ADMIN_TOOLS`, and every worker-facing tool
takes the caller's own employee_id from the session rather than from the question. A worker
asking about EMP002 gets their own records or nothing — the model is never handed another
worker's data to be discreet about.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from safety import caution, geo, history, routes_history, store

logger = logging.getLogger(__name__)

MAX_ROWS = 25


def _trim(rows: List[Dict[str, Any]], keys: tuple) -> List[Dict[str, Any]]:
    """Keep the evidence small enough to fit in a prompt without losing what identifies a row."""
    return [{k: row.get(k) for k in keys} for row in rows[:MAX_ROWS]]


# --- shared -----------------------------------------------------------------------------------

def get_published_alerts(**_: Any) -> Dict[str, Any]:
    """Every alert currently visible to workers and able to influence routing."""
    rows = store.list_announcements(True)
    return {"alerts": _trim(rows, ("id", "title", "severity", "location_text",
                                   "latitude", "longitude", "radius_meters", "restricted",
                                   "created_at")),
            "count": len(rows)}


def get_nearby_incidents(latitude: float, longitude: float,
                         radius_meters: int = geo.HOTSPOT_RADIUS_METERS, **_: Any) -> Dict[str, Any]:
    """Stored reports within a radius, with the risk breakdown and any serious markers."""
    corpus = store.all_analyses()
    block = history.summarise(corpus, float(latitude), float(longitude), int(radius_meters))
    return {"radius_meters": block["radius_meters"], "report_count": block["report_count"],
            "risk_breakdown": block["risk_breakdown"],
            "recurring_hazards": block["recurring_hazards"][:6],
            "serious_incidents": block["serious_incidents"][:5],
            "report_ids": block["report_ids"][:MAX_ROWS]}


# --- admin ------------------------------------------------------------------------------------

def get_worker_reports(employee_id: str, **_: Any) -> Dict[str, Any]:
    user = store.find_user(employee_id)
    if user is None:
        return {"error": f"No worker with employee id {employee_id!r}."}
    rows = store.reports_for_worker(user["id"], 200)
    return {"employee_id": employee_id, "name": user["name"],
            "department": user["department"], "count": len(rows),
            "reports": _trim(rows, ("id", "report_text", "created_at", "risk_level",
                                    "hazards", "location", "latitude", "longitude"))}


def get_route_history(employee_id: str, **_: Any) -> Dict[str, Any]:
    rows = store.list_route_events(employee_id, None, None, None, None, 100)
    return {"employee_id": employee_id, "count": len(rows),
            "routes": _trim(rows, ("id", "created_at", "classification",
                                   "original_distance_meters", "selected_distance_meters",
                                   "detour_distance_meters", "detour_ratio",
                                   "route_adjusted_for_safety", "affecting_alert_id",
                                   "affecting_alert_title", "affecting_alert_severity",
                                   "minimum_distance_to_alert_meters", "selected_reason")),
            "coverage_note": routes_history.summarise(rows)["coverage_note"]}


def get_route_event(route_event_id: int, **_: Any) -> Dict[str, Any]:
    row = store.get_route_event(int(route_event_id), None)
    if row is None:
        return {"error": f"No route event {route_event_id}."}
    # Geometry is deliberately omitted: hundreds of coordinates would crowd out the evidence and
    # a model cannot say anything useful about them. The UI draws them from the route endpoint.
    return {k: row.get(k) for k in (
        "id", "employee_id", "worker_name", "created_at", "classification",
        "original_distance_meters", "selected_distance_meters", "detour_distance_meters",
        "detour_ratio", "route_adjusted_for_safety", "safe_alternative_found",
        "selected_reason", "affecting_alert_id", "affecting_alert_title",
        "affecting_alert_severity", "affecting_alert_radius_meters",
        "minimum_distance_to_alert_meters", "safety_radius_meters")}


def get_workers_affected_by_alert(alert_id: int, **_: Any) -> Dict[str, Any]:
    rows = store.list_route_events(None, None, int(alert_id), None, None, 200)
    affected = [r for r in rows if r.get("minimum_distance_to_alert_meters") is not None
                and r["minimum_distance_to_alert_meters"] <= (r.get("safety_radius_meters") or 500)]
    return {"alert_id": alert_id, "count": len(affected),
            "workers": _trim(affected, ("employee_id", "worker_name", "created_at",
                                        "minimum_distance_to_alert_meters", "classification",
                                        "id")),
            "evidence": "stored route geometry recorded when each route was requested",
            "coverage_note": ("Only routes requested after route-event recording began are "
                              "represented.")}


def get_workers_rerouted_by_alert(alert_id: int, **_: Any) -> Dict[str, Any]:
    rows = store.list_route_events(None, None, int(alert_id), None, None, 200)
    rerouted = [r for r in rows if r.get("route_adjusted_for_safety")]
    return {"alert_id": alert_id, "count": len(rerouted),
            "workers": _trim(rerouted, ("employee_id", "worker_name", "created_at",
                                        "original_distance_meters", "selected_distance_meters",
                                        "detour_distance_meters", "detour_ratio", "id"))}


def get_alert_history(alert_id: int, **_: Any) -> Dict[str, Any]:
    rows = [a for a in store.list_announcements(False) if a["id"] == int(alert_id)]
    if not rows:
        return {"error": f"No alert {alert_id}."}
    alert = rows[0]
    events = store.list_route_events(None, None, int(alert_id), None, None, 200)
    return {"alert": {k: alert.get(k) for k in ("id", "title", "message", "severity", "status",
                                                "latitude", "longitude", "radius_meters",
                                                "restricted", "location_text", "created_at")},
            "route_events": len(events),
            "rerouted": sum(1 for e in events if e.get("route_adjusted_for_safety"))}


def get_hotspot_reports(hotspot_id: int, **_: Any) -> Dict[str, Any]:
    hotspot = store.get_hotspot(int(hotspot_id))
    if hotspot is None:
        return {"error": f"No hotspot {hotspot_id}."}
    reports = []
    for report_id in (hotspot.get("report_ids") or [])[:MAX_ROWS]:
        record = store.get_report(int(report_id))
        if record:
            reports.append({"id": record["report"]["id"],
                            "report_text": record["report"]["report_text"],
                            "created_at": record["report"]["created_at"],
                            "risk_level": (record["analysis"] or {}).get("risk_level")})
    return {"hotspot": {k: hotspot.get(k) for k in (
                "id", "status", "primary_hazard", "related_hazards", "risk_level",
                "report_count", "latitude", "longitude", "radius_meters", "explanation",
                "flag_source", "first_report_at", "latest_report_at")},
            "supporting_reports": reports}


def get_department_statistics(**_: Any) -> Dict[str, Any]:
    corpus = store.all_analyses()
    by_department: Dict[str, Dict[str, int]] = {}
    for report in corpus:
        name = report.get("department") or "Unassigned"
        bucket = by_department.setdefault(name, {"reports": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0})
        bucket["reports"] += 1
        level = report.get("risk_level")
        if level in bucket:
            bucket[level] += 1
    return {"departments": [{"department": k, **v} for k, v in
                            sorted(by_department.items(), key=lambda kv: -kv[1]["reports"])]}


def get_recurring_patterns(**_: Any) -> Dict[str, Any]:
    """Recurring hazards and locations, and the candidate hotspots awaiting review."""
    corpus = store.all_analyses()
    hazards: Dict[str, int] = {}
    locations: Dict[str, int] = {}
    for report in corpus:
        for hazard in report.get("hazards") or []:
            hazards[hazard] = hazards.get(hazard, 0) + 1
        place = report.get("location")
        if place:
            locations[place] = locations.get(place, 0) + 1
    hotspots = store.list_hotspots(None)
    return {
        "top_hazards": sorted(hazards.items(), key=lambda kv: -kv[1])[:8],
        "top_locations": sorted(locations.items(), key=lambda kv: -kv[1])[:8],
        "candidate_hotspots": _trim([h for h in hotspots if h["status"] == "PENDING_REVIEW"],
                                    ("id", "primary_hazard", "report_count", "risk_level",
                                     "locations", "status")),
        "hotspot_rule": geo.rule_description(),
    }


def get_report_detail(report_id: int, **_: Any) -> Dict[str, Any]:
    """One report with its deterministic analysis and its pattern level."""
    record = store.get_report(int(report_id))
    if record is None:
        return {"error": f"No report {report_id}."}
    report, analysis = record["report"], record["analysis"] or {}
    corpus = store.all_analyses()
    subject = next((r for r in corpus if r["id"] == int(report_id)), None)
    pattern = caution.pattern_status(corpus, subject) if subject else None
    return {
        "report": {k: report.get(k) for k in ("id", "report_text", "created_at", "location",
                                              "department", "latitude", "longitude",
                                              "location_source", "photo_source")},
        "analysis": {k: analysis.get(k) for k in ("risk_level", "risk_score", "summary",
                                                  "hazards", "risk_factors", "reasoning")},
        "pattern": {k: pattern.get(k) for k in ("level", "label", "related_count", "summary",
                                                "related_report_ids")} if pattern else None,
    }


def get_admin_actions(**_: Any) -> Dict[str, Any]:
    rows = store.list_admin_actions(None, None)
    return {"count": len(rows),
            "actions": _trim(rows, ("id", "label", "hotspot_id", "report_id",
                                    "authority_contacted", "outcome", "action_timestamp"))}


# --- worker-scoped -------------------------------------------------------------------------
#
# Each takes the CALLER's employee_id, injected by the endpoint from the session. The model may
# not pass one, so a worker cannot ask about somebody else by naming them.

def my_reports(_caller: str, **_: Any) -> Dict[str, Any]:
    return get_worker_reports(_caller)


def my_routes(_caller: str, **_: Any) -> Dict[str, Any]:
    return get_route_history(_caller)


def alerts_near_me(_caller: str, latitude: float, longitude: float,
                   radius_meters: int = 2000, **_: Any) -> Dict[str, Any]:
    """Published alerts and generic cautions near a point. No reports, no reporters, no ids."""
    published = store.list_announcements(True)
    near = [a for a in published
            if a.get("latitude") is not None
            and geo.haversine_meters(float(latitude), float(longitude),
                                     float(a["latitude"]), float(a["longitude"]))
            <= max(float(a.get("radius_meters") or 0), radius_meters)]
    cautions = caution.worker_cautions(store.all_analyses(), float(latitude), float(longitude))
    return {"alerts": _trim(near, ("id", "title", "message", "severity", "location_text",
                                   "latitude", "longitude", "radius_meters")),
            "cautions": cautions[:5],
            "note": "Cautions are advisories from nearby reports. They do not change your route."}


ADMIN_TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "get_published_alerts": get_published_alerts,
    "get_nearby_incidents": get_nearby_incidents,
    "get_worker_reports": get_worker_reports,
    "get_route_history": get_route_history,
    "get_route_event": get_route_event,
    "get_workers_affected_by_alert": get_workers_affected_by_alert,
    "get_workers_rerouted_by_alert": get_workers_rerouted_by_alert,
    "get_alert_history": get_alert_history,
    "get_hotspot_reports": get_hotspot_reports,
    "get_department_statistics": get_department_statistics,
    "get_recurring_patterns": get_recurring_patterns,
    "get_report_detail": get_report_detail,
    "get_admin_actions": get_admin_actions,
}

WORKER_TOOLS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "my_reports": my_reports,
    "my_routes": my_routes,
    "alerts_near_me": alerts_near_me,
    "get_published_alerts": get_published_alerts,
}

#: Tools that need the caller's own identity injected rather than taken from the question.
CALLER_SCOPED = frozenset({"my_reports", "my_routes", "alerts_near_me"})


def run(name: str, arguments: Dict[str, Any], *, role: str,
        caller: Optional[str] = None) -> Dict[str, Any]:
    """Execute one tool for one role. Refuses anything not in that role's table."""
    table = ADMIN_TOOLS if role == "admin" else WORKER_TOOLS
    tool = table.get(name)
    if tool is None:
        return {"error": f"'{name}' is not available to this role."}
    try:
        if name in CALLER_SCOPED:
            if not caller:
                return {"error": "This question needs your employee id."}
            return tool(_caller=caller, **arguments)
        return tool(**arguments)
    except TypeError as exc:
        return {"error": f"Bad arguments for '{name}': {exc}"}
    except Exception:  # noqa: BLE001
        logger.exception("chat_tool_failed name=%s", name)
        return {"error": f"'{name}' could not be completed."}
