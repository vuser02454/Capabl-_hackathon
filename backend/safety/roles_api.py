"""Worker and Safety Admin endpoints.

The split is a privacy boundary, not a convenience. Worker routes return published announcements
only — never a raw report, a reporter, an unreviewed candidate, or an internal note. Admin routes
return the evidence. Keeping them in separate routers with separate shaping functions makes it
hard to leak the wrong one by editing a shared serialiser.

No authentication: the brief says role selection is sufficient for the demo and explicitly says
not to build production auth. The role is a client-side choice, so these routes are NOT a security
control — they are a data-shaping boundary. Real deployment would need auth in front of `/admin`.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from services.geocoding_service import get_geocoder

from safety import authority as authority_lookup
from safety import (caution, chat, domains, geo, graph, history, people, routing,
                    routes_history, store)
from safety.api import DISCLAIMER, SYNTHETIC_NOTICE, _camel, _shape_analysis

logger = logging.getLogger(__name__)

worker_router = APIRouter(prefix="/api/worker", tags=["worker"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])

LOCATION_SOURCES = {"browser_gps", "manual_map", "text_search", "text_location", "unknown"}


class WorkerReportRequest(BaseModel):
    report_text: str = Field(min_length=1, max_length=8000)
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    gps_accuracy: Optional[float] = Field(default=None, ge=0)
    location_source: str = "unknown"
    location_text: Optional[str] = None
    #: When the fix was taken, per the worker's device. Recorded so a stale fix is visible as one.
    location_captured_at: Optional[str] = None
    #: Who is filing. Optional — an unattributed report is still a valid report, and refusing one
    #: because nobody was identified would lose exactly the hazard reports that matter most.
    employee_id: Optional[str] = None


class HotspotAction(BaseModel):
    notes: Optional[str] = None


class FlagRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    reason: str = Field(min_length=1, max_length=2000)
    severity: str = "MEDIUM"
    radius_meters: int = Field(default=geo.HOTSPOT_RADIUS_METERS, ge=50, le=20000)
    location_text: Optional[str] = None


class AnnouncementRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    severity: str = "HIGH"
    hotspot_id: Optional[int] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_meters: int = Field(default=geo.HOTSPOT_RADIUS_METERS, ge=50, le=20000)
    location_text: Optional[str] = None
    expires_at: Optional[str] = None
    #: Closes the area to safety-aware routing entirely. A deliberate admin act, not a severity.
    restricted: bool = False


# --- worker -------------------------------------------------------------------------------------

@worker_router.post("/reports")
async def submit_worker_report(request: WorkerReportRequest) -> Dict[str, Any]:
    """Submit a report, optionally with a device fix.

    Location is optional at every level. No coordinates, a denied permission, or a failed geocode
    must never block a safety report — the text is the thing that matters, and a report that
    cannot be filed is worse than one without a pin.
    """
    text = request.report_text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Report text cannot be empty.")
    source = request.location_source if request.location_source in LOCATION_SOURCES else "unknown"
    if (request.latitude is None) != (request.longitude is None):
        raise HTTPException(status_code=422, detail="Provide both latitude and longitude, or neither.")

    fix = {"latitude": request.latitude, "longitude": request.longitude,
           "gps_accuracy": request.gps_accuracy, "location_source": source,
           "location_text": request.location_text,
           "location_captured_at": request.location_captured_at}
    try:
        result = await run_in_threadpool(graph.analyze_report, text, "worker", True, fix)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("worker_report_failed")
        raise HTTPException(status_code=500, detail=f"Analysis failed: {type(exc).__name__}") from exc

    report_id = result.get("report_id")

    # Attribute the report and, if it carried a confirmed fix, record that one location event.
    # This is the second and last place a worker_location row is ever written.
    worker = store.find_user(request.employee_id) if request.employee_id else None
    if worker is not None and worker["role"] == "WORKER" and report_id:
        await run_in_threadpool(store.attach_report_worker, report_id, worker["id"])
        if request.latitude is not None and request.longitude is not None:
            await run_in_threadpool(store.record_location, {
                "worker_id": worker["id"], "latitude": request.latitude,
                "longitude": request.longitude, "gps_accuracy": request.gps_accuracy,
                "location_source": source, "report_id": report_id,
                "captured_at": request.location_captured_at,
            })

    # Tell the safety admin a report has arrived. Failure here must not lose the report, so it
    # is caught: an unnotified report is recoverable from the reports list, a rejected one is not.
    try:
        facts = result.get("facts") or {}
        analysis = result.get("analysis") or {}
        await run_in_threadpool(store.create_notification, {
            "recipient_role": "SAFETY_ADMIN",
            "notification_type": "REPORT_SUBMITTED",
            "sender_employee_id": request.employee_id,
            "title": f"New {analysis.get('risk_level', 'safety')} report"
                     + (f" from {request.employee_id}" if request.employee_id else ""),
            "message": facts.get("summary") or text[:180],
            "report_id": report_id,
            "latitude": request.latitude, "longitude": request.longitude,
            "gps_accuracy": request.gps_accuracy, "location_source": source,
            "severity": analysis.get("risk_level"),
            "metadata": {
                "riskFactors": facts.get("risk_factors", [])[:6],
                "hazards": facts.get("hazards", [])[:6],
                "domain": (result.get("domain") or {}).get("label"),
                "locationText": request.location_text,
                # Whether a photo exists is filled in by the photo upload; at submission time
                # none is attached yet, so this says what is true now rather than guessing.
                "hasPhoto": False,
            },
        })
    except Exception:  # noqa: BLE001
        logger.exception("report_notification_not_created report_id=%s", report_id)

    shaped = _shape_analysis(result)
    shaped["report"]["reportText"] = text
    shaped["location"] = {
        "latitude": request.latitude, "longitude": request.longitude,
        "gpsAccuracy": request.gps_accuracy, "locationSource": source,
        "locationText": request.location_text,
    }
    shaped["hotspotRule"] = _camel(geo.rule_description())
    shaped["reportId"] = report_id
    # The worker sees only that their report was classified, never the area's history or the
    # authority lookup — those are admin-side evidence.
    shaped["domain"] = _camel({k: v for k, v in (result.get("domain") or {}).items()
                               if k in ("domain", "label")})
    # A worker never sees candidate hotspots; only the count, so the UI can say "logged".
    shaped["candidateHotspotCount"] = len(result.get("hotspots") or [])
    shaped["worker"] = _public_user(worker) if worker is not None else None
    return shaped


def _public_alert(row: Dict[str, Any]) -> Dict[str, Any]:
    """The ONLY shape a worker ever receives. No report ids, no reporter, no internal notes."""
    return {
        "id": row["id"],
        "title": row["title"],
        "message": row["message"],
        "severity": row["severity"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "radiusMeters": row["radius_meters"],
        "locationText": row["location_text"],
        "publishedAt": row["created_at"],
        "issuedBy": "Safety Team",
    }


@worker_router.get("/alerts")
async def worker_alerts() -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_announcements, True)
    return {"alerts": [_public_alert(r) for r in rows], "count": len(rows),
            "disclaimer": DISCLAIMER}


@worker_router.get("/map")
async def worker_map() -> Dict[str, Any]:
    """Published alerts only. Raw reports and unreviewed candidates never appear here."""
    rows = await run_in_threadpool(store.list_announcements, True)
    return {
        "alerts": [_public_alert(r) for r in rows],
        "hotspotRule": _camel(geo.rule_description()),
        "note": "Workers see published safety alerts only. Individual reports stay private.",
    }


# --- admin --------------------------------------------------------------------------------------

def _admin_hotspot(row: Dict[str, Any]) -> Dict[str, Any]:
    shaped = _camel(row)
    shaped["isAiDetected"] = row.get("flag_source") == "ai_detected"
    return shaped


@admin_router.get("/hotspots")
async def admin_hotspots(status: Optional[str] = Query(None)) -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_hotspots, status)
    return {"hotspots": [_admin_hotspot(r) for r in rows], "count": len(rows),
            "rule": _camel(geo.rule_description())}


@admin_router.get("/hotspots/{hotspot_id}")
async def admin_hotspot_detail(hotspot_id: int) -> Dict[str, Any]:
    row = await run_in_threadpool(store.get_hotspot, hotspot_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Hotspot {hotspot_id} was not found.")
    supporting = []
    for report_id in row.get("report_ids") or []:
        record = await run_in_threadpool(store.get_report, int(report_id))
        if record:
            supporting.append({
                "id": record["report"]["id"],
                "reportText": record["report"]["report_text"],
                "location": record["report"]["location"],
                "createdAt": record["report"]["created_at"],
                "riskLevel": (record["analysis"] or {}).get("risk_level"),
                "hazards": (record["analysis"] or {}).get("hazards", []),
                "reasoning": (record["analysis"] or {}).get("reasoning", []),
            })
    intel = await run_in_threadpool(_hotspot_intelligence, row)
    actions = await run_in_threadpool(store.list_admin_actions, hotspot_id, None)
    feedback = await run_in_threadpool(store.list_feedback, hotspot_id)
    return {"hotspot": _admin_hotspot(row), "supportingReports": supporting,
            "rule": _camel(geo.rule_description()),
            **intel,
            "adminActions": [_camel(a) for a in actions],
            "feedback": [_camel(f) for f in feedback]}


def _hotspot_intelligence(row: Dict[str, Any]) -> Dict[str, Any]:
    """Incident history, the explainable assessment and any relevant authority for one hotspot.

    Built entirely from stored reports plus one OpenStreetMap lookup. The authority lookup is
    allowed to fail — it returns its failure as data and this block still renders.
    """
    corpus = store.all_analyses()
    member_ids = [int(i) for i in (row.get("report_ids") or [])]
    members = [r for r in corpus if r["id"] in set(member_ids)]

    # The domain of the cluster is the domain its member reports agree on most often.
    domain_counts: Dict[str, int] = {}
    for member in members:
        found = domains.classify(member.get("report_text", ""))["domain"]
        domain_counts[found] = domain_counts.get(found, 0) + 1
    domain = max(domain_counts, key=lambda k: domain_counts[k]) if domain_counts else "OTHER"

    hazards = sorted({h for m in members for h in (m.get("hazards") or [])})
    block = history.summarise(corpus, row["latitude"], row["longitude"],
                              int(row.get("radius_meters") or geo.HOTSPOT_RADIUS_METERS),
                              exclude_ids=member_ids)
    explanation = history.assessment(block, {"domain": domain, "hazards": hazards})

    authority_type = domains.DOMAIN_AUTHORITY.get(domain)
    found = authority_lookup.lookup(row["latitude"], row["longitude"], authority_type)
    nearest = (found.get("results") or [None])[0]

    specialised = None
    if domain in domains.EMERGENCY_DOMAINS:
        specialised = {
            "domain": domain,
            "label": domains.DOMAIN_LABEL[domain],
            "authority": found,
            "nearest": nearest,
            "evidenceReportIds": member_ids,
            "recommendation": (
                f"Safety Admin should assess the situation and consider contacting the "
                f"appropriate {(found.get('label') or 'emergency').lower()} authority."),
            "disclaimer": ("This is a screening recommendation for a human safety officer. "
                           "The system does not contact any authority and does not declare an "
                           "emergency."),
        }

    return {
        "incidentHistory": _camel(block),
        "explanation": _camel(explanation),
        "domain": {"domain": domain, "label": domains.DOMAIN_LABEL.get(domain, domain)},
        "authority": _camel(found),
        "specializedResponse": _camel(specialised) if specialised else None,
    }


_ACTIONS = {
    "acknowledge": "ACKNOWLEDGED",
    "investigate": "INVESTIGATING",
    "publish": "PUBLISHED",
    "resolve": "RESOLVED",
    "dismiss": "DISMISSED",
}


@admin_router.post("/hotspots/{hotspot_id}/{action}")
async def admin_hotspot_action(hotspot_id: int, action: str,
                               body: Optional[HotspotAction] = None) -> Dict[str, Any]:
    """Advance a hotspot through review. Only a human reaches this endpoint."""
    status = _ACTIONS.get(action)
    if status is None:
        raise HTTPException(status_code=404,
                            detail=f"Unknown action {action!r}. Expected one of {sorted(_ACTIONS)}.")
    row = await run_in_threadpool(store.set_hotspot_status, hotspot_id, status,
                                  body.notes if body else None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Hotspot {hotspot_id} was not found.")
    return {"hotspot": _admin_hotspot(row), "action": action, "status": status}


@admin_router.post("/hotspots/flag")
async def admin_flag_location(request: FlagRequest) -> Dict[str, Any]:
    """An admin's own judgement about a place. Distinct from an AI candidate and never conflated.

    No supporting reports are fabricated: `report_count` is 0 and `report_ids` is empty, because
    the admin flagged this from observation rather than from a cluster.
    """
    hotspot_id = await run_in_threadpool(store.upsert_hotspot, {
        "latitude": request.latitude, "longitude": request.longitude,
        "radius_meters": request.radius_meters, "report_count": 0,
        "primary_hazard": request.reason[:120], "related_hazards": [],
        "risk_level": request.severity if request.severity in ("LOW", "MEDIUM", "HIGH") else "MEDIUM",
        "first_report_at": None, "latest_report_at": None, "report_ids": [],
        "locations": [request.location_text] if request.location_text else [],
        "explanation": "Flagged manually by a safety admin — not derived from report clustering.",
        "flag_source": "admin_flagged", "status": "ACKNOWLEDGED",
        "severity": request.severity, "reason": request.reason,
    })
    row = await run_in_threadpool(store.get_hotspot, hotspot_id)
    return {"hotspot": _admin_hotspot(row) if row else None, "flagSource": "admin_flagged"}


@admin_router.get("/map")
async def admin_map() -> Dict[str, Any]:
    """Everything an admin may see: geolocated reports, candidates, and published alerts."""
    corpus = await run_in_threadpool(store.all_analyses)
    located = [
        {"id": r["id"], "latitude": r["latitude"], "longitude": r["longitude"],
         "riskLevel": r.get("risk_level"), "hazards": r.get("hazards", []),
         "location": r.get("location"), "createdAt": r.get("created_at"),
         "locationSource": r.get("location_source")}
        for r in corpus if r.get("latitude") is not None and r.get("longitude") is not None
    ]
    hotspots = await run_in_threadpool(store.list_hotspots, None)
    alerts = await run_in_threadpool(store.list_announcements, True)
    return {
        "reports": located,
        "hotspots": [_admin_hotspot(h) for h in hotspots],
        "alerts": [_public_alert(a) for a in alerts],
        "rule": _camel(geo.rule_description()),
        "syntheticNotice": SYNTHETIC_NOTICE,
    }


@admin_router.post("/announcements")
async def create_announcement(request: AnnouncementRequest) -> Dict[str, Any]:
    """Publish an alert. This is the only path by which anything becomes visible to workers."""
    payload = request.model_dump()
    announcement_id = await run_in_threadpool(store.create_announcement, payload)
    if request.hotspot_id:
        await run_in_threadpool(store.set_hotspot_status, request.hotspot_id, "PUBLISHED",
                                f"Published as announcement #{announcement_id}")
    rows = await run_in_threadpool(store.list_announcements, False)
    created = next((r for r in rows if r["id"] == announcement_id), None)
    return {"announcement": _camel(created) if created else None, "id": announcement_id}


@admin_router.get("/announcements")
async def list_announcements() -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_announcements, False)
    return {"announcements": [_camel(r) for r in rows], "count": len(rows)}


@admin_router.get("/reports")
async def admin_reports(limit: int = Query(200, ge=1, le=500)) -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_reports, limit)
    return {"reports": [_camel(r) for r in rows], "count": len(rows),
            "syntheticNotice": SYNTHETIC_NOTICE}


# --- photo evidence -------------------------------------------------------------------------

#: A phone photo at full resolution is a few MB; this caps a single upload well above that while
#: keeping a hostile upload from filling the disk.
MAX_PHOTO_BYTES = 8 * 1024 * 1024


@worker_router.post("/reports/{report_id}/photo")
async def attach_report_photo(
    report_id: int,
    file: UploadFile = File(...),
    photo_source: str = Form("live_camera"),
    captured_at: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Attach a photo to a report that has already been filed.

    Deliberately a second request rather than part of the report submission: the report text is
    the thing that matters, and a camera that fails or an upload that times out must not take the
    report down with it. A worker who denies camera permission simply never calls this.
    """
    record = await run_in_threadpool(store.get_report, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} was not found.")
    if photo_source not in store.PHOTO_SOURCES:
        raise HTTPException(status_code=422,
                            detail=f"photo_source must be one of {sorted(store.PHOTO_SOURCES)}.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="The uploaded photo was empty.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"Photo exceeds {MAX_PHOTO_BYTES // (1024 * 1024)} MB.")
    mime = (file.content_type or "").split(";")[0].strip()
    if mime not in store.PHOTO_MIME_TYPES:
        raise HTTPException(status_code=415,
                            detail=f"Unsupported image type {mime!r}. "
                                   f"Expected one of {sorted(store.PHOTO_MIME_TYPES)}.")

    try:
        path = await run_in_threadpool(store.save_photo, data, mime, report_id)
        await run_in_threadpool(store.attach_photo, report_id, path, mime, photo_source, captured_at)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {"reportId": report_id, "photoSource": photo_source, "bytes": len(data),
            "photoUrl": f"/api/admin/reports/{report_id}/photo",
            # Said plainly because the whole geotag design depends on it.
            "note": "The report's geotag comes from the confirmed device fix, not from photo EXIF."}


@worker_router.get("/reports/{report_id}/photo")
async def get_worker_report_photo(
    report_id: int, employee_id: str = Query(..., alias="employee_id")
) -> Response:
    """Serve a worker's own photo. Enforced server-side: workers can never view another worker's photo."""
    worker = await run_in_threadpool(_require_worker, employee_id)
    record = await run_in_threadpool(store.report_for_worker, report_id, worker["id"])
    if record is None or not record.get("photo_path"):
        raise HTTPException(status_code=404, detail="No photo found for this report.")
    path = store.DB_PATH.parent / record["photo_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is missing from disk.")
    return Response(content=path.read_bytes(),
                    media_type=record.get("photo_mime") or "application/octet-stream")


@admin_router.get("/reports/{report_id}/photo")
async def get_report_photo(report_id: int) -> Response:
    """Serve one report's photo. Admin-side only — a worker never sees another worker's evidence."""
    record = await run_in_threadpool(store.get_report, report_id)
    if record is None or not record["report"].get("photo_path"):
        raise HTTPException(status_code=404, detail="No photo is attached to this report.")
    path = store.DB_PATH.parent / record["report"]["photo_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="The photo file is missing from disk.")
    return Response(content=path.read_bytes(),
                    media_type=record["report"].get("photo_mime") or "application/octet-stream")


@admin_router.get("/reports/{report_id}")
async def admin_report_detail(report_id: int) -> Dict[str, Any]:
    """One report with its analysis, photo provenance and the incident history around it."""
    record = await run_in_threadpool(store.get_report, report_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} was not found.")
    report, analysis = record["report"], record["analysis"] or {}

    evidence = {
        "hasPhoto": bool(report.get("photo_path")),
        "photoUrl": f"/api/admin/reports/{report_id}/photo" if report.get("photo_path") else None,
        "photoSource": report.get("photo_source"),
        "photoCapturedAt": report.get("photo_captured_at"),
        "latitude": report.get("latitude"),
        "longitude": report.get("longitude"),
        "gpsAccuracy": report.get("gps_accuracy"),
        "locationSource": report.get("location_source"),
        "locationText": report.get("location_text"),
        "locationCapturedAt": report.get("location_captured_at"),
        "geotagNote": "Coordinates come from the fix the worker confirmed in-app, not from photo EXIF.",
    }

    block = explanation = None
    if report.get("latitude") is not None and report.get("longitude") is not None:
        corpus = await run_in_threadpool(store.all_analyses)
        block = history.summarise(corpus, float(report["latitude"]), float(report["longitude"]),
                                  geo.HOTSPOT_RADIUS_METERS, exclude_ids=[report_id])
        explanation = history.assessment(
            block, {"domain": domains.classify(report["report_text"])["domain"],
                    "hazards": analysis.get("hazards") or []})

    corpus_for_pattern = await run_in_threadpool(store.all_analyses)
    subject = next((r for r in corpus_for_pattern if r["id"] == report_id), None)
    pattern = (caution.pattern_status(corpus_for_pattern, subject)
               if subject is not None else None)

    geographic_relationship = []
    if subject is not None and pattern:
        for r_id in pattern.get("related_report_ids") or []:
            rel = next((r for r in corpus_for_pattern if r["id"] == r_id), None)
            if rel:
                dist = geo.haversine_meters(
                    float(report["latitude"]), float(report["longitude"]),
                    float(rel["latitude"]), float(rel["longitude"])
                ) if report.get("latitude") is not None and rel.get("latitude") is not None else None
                geographic_relationship.append({
                    "reportId": rel["id"],
                    "location": rel.get("location") or rel.get("location_text"),
                    "distanceMeters": round(dist) if dist is not None else None,
                    "hazards": rel.get("hazards") or [],
                    "createdAt": rel.get("created_at"),
                })

    actions = await run_in_threadpool(store.list_admin_actions, None, report_id)
    return {
        "pattern": _camel(pattern) if pattern else None,
        "report": _camel(report),
        "analysis": _camel(analysis),
        "evidence": evidence,
        "domain": _camel(domains.classify(report["report_text"])),
        "incidentHistory": _camel(block) if block else None,
        "explanation": _camel(explanation) if explanation else None,
        "adminActions": [_camel(a) for a in actions],
        "geographicRelationship": geographic_relationship,
        "recommendations": analysis.get("recommendations") or {},
    }


# --- admin action tracking and feedback --------------------------------------------------------

class AdminActionRequest(BaseModel):
    action_taken: str
    hotspot_id: Optional[int] = None
    report_id: Optional[int] = None
    authority_contacted: Optional[str] = None
    admin_notes: Optional[str] = None
    outcome: Optional[str] = None
    follow_up_required: bool = False


class FeedbackRequest(BaseModel):
    useful: bool
    hotspot_id: Optional[int] = None
    report_id: Optional[int] = None
    reason: Optional[str] = None
    comment: Optional[str] = None


@admin_router.post("/actions")
async def record_action(request: AdminActionRequest) -> Dict[str, Any]:
    """Record what the admin did. The system performs no action and contacts nobody."""
    try:
        action_id = await run_in_threadpool(store.record_admin_action, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": action_id, "actionTaken": request.action_taken,
            "label": store.ADMIN_ACTION_LABEL.get(request.action_taken, request.action_taken),
            "note": "Recorded for the audit trail. EcoSentinel did not contact this authority."}


@admin_router.get("/actions")
async def list_actions(hotspot_id: Optional[int] = Query(None),
                       report_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_admin_actions, hotspot_id, report_id)
    return {"actions": [_camel(r) for r in rows], "count": len(rows),
            "available": [{"id": a, "label": store.ADMIN_ACTION_LABEL[a]} for a in store.ADMIN_ACTIONS]}


@admin_router.post("/feedback")
async def record_feedback(request: FeedbackRequest) -> Dict[str, Any]:
    """Store one judgement about a recommendation. Nothing retrains from it."""
    try:
        feedback_id = await run_in_threadpool(store.record_feedback, request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": feedback_id, "useful": request.useful,
            "note": "Stored for later analysis. A single feedback event never retrains the model."}


@admin_router.get("/feedback")
async def list_feedback(hotspot_id: Optional[int] = Query(None)) -> Dict[str, Any]:
    rows = await run_in_threadpool(store.list_feedback, hotspot_id)
    return {"feedback": [_camel(r) for r in rows], "count": len(rows),
            "reasons": list(store.FEEDBACK_REASONS)}


# --- admin dashboard ---------------------------------------------------------------------------

@admin_router.get("/dashboard")
async def admin_dashboard() -> Dict[str, Any]:
    """Headline numbers for the admin landing screen, all counted from stored rows."""
    corpus = await run_in_threadpool(store.all_analyses)
    hotspots = await run_in_threadpool(store.list_hotspots, None)
    alerts = await run_in_threadpool(store.list_announcements, True)
    actions = await run_in_threadpool(store.list_admin_actions, None, None)

    by_status: Dict[str, int] = {}
    for hotspot in hotspots:
        by_status[hotspot["status"]] = by_status.get(hotspot["status"], 0) + 1
    by_risk: Dict[str, int] = {"HIGH": 0, "MEDIUM": 0, "LOW": 0}
    for report in corpus:
        level = report.get("risk_level")
        if level in by_risk:
            by_risk[level] += 1

    domain_counts: Dict[str, int] = {}
    for report in corpus:
        found = domains.classify(report.get("report_text", ""))["domain"]
        domain_counts[found] = domain_counts.get(found, 0) + 1

    # Worker safety activity, all counted from stored rows.
    route_events = await run_in_threadpool(
        store.list_route_events, None, None, None, None, None, 500)
    route_summary = routes_history.summarise(route_events)
    reporting_workers = len({r["worker_id"] for r in corpus if r.get("worker_id") is not None})

    return {
        "workerCount": await run_in_threadpool(store.count_users, "WORKER"),
        "workersReportingIncidents": reporting_workers,
        "routeEventCount": route_summary["total"],
        "workersPassingModerateHazards": route_summary["moderate_hazard"],
        "workersReroutedFromHighHazards": route_summary["high_hazard_detour"],
        "noSafeAlternativeEvents": route_summary["no_safe_alternative"],
        "routeSummary": _camel(route_summary),
        "reportCount": len(corpus),
        "geolocatedCount": sum(1 for r in corpus if r.get("latitude") is not None),
        "photoCount": sum(1 for r in corpus if r.get("photo_path")),
        "riskBreakdown": by_risk,
        "hotspotCount": len(hotspots),
        "hotspotsByStatus": by_status,
        "pendingReview": by_status.get("PENDING_REVIEW", 0),
        "publishedAlertCount": len(alerts),
        "recordedActionCount": len(actions),
        "domainBreakdown": [{"domain": d, "label": domains.DOMAIN_LABEL.get(d, d), "count": c}
                            for d, c in sorted(domain_counts.items(), key=lambda kv: -kv[1])],
        "rule": _camel(geo.rule_description()),
        "domains": domains.domain_catalogue(),
        "syntheticNotice": SYNTHETIC_NOTICE,
        "disclaimer": DISCLAIMER,
    }


# --- worker routing ----------------------------------------------------------------------------

class RoutePoint(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteRequest(BaseModel):
    start: RoutePoint
    destination: RoutePoint
    #: Who asked. Optional — an unattributed route is still calculated; it is simply recorded
    #: without an owner, and no worker can then retrieve it as their own.
    employee_id: Optional[str] = None
    #: How close the route may come to a published alert before an alternative is sought.
    #: Exposed so the threshold is configurable, defaulted so callers need not care.
    safety_radius_meters: float = Field(default=routing.ROUTE_SAFETY_RADIUS_METERS, ge=0, le=2000)


def _published_alert_circles() -> List[Dict[str, Any]]:
    """The only safety data allowed to influence a worker's route.

    PUBLISHED announcements exclusively. A candidate hotspot is an unreviewed hypothesis that a
    worker is never shown, and letting one bend a route would leak its existence through the
    shape of the path. The 1 km hotspot-analysis radius plays no part in routing at all.
    """
    return [
        {"id": row["id"], "title": row["title"], "severity": row["severity"],
         "latitude": row["latitude"], "longitude": row["longitude"],
         "radius_meters": row["radius_meters"], "location_text": row["location_text"],
         "restricted": bool(row.get("restricted"))}
        for row in store.list_announcements(True)
        if row.get("latitude") is not None and row.get("longitude") is not None
    ]


@worker_router.post("/route")
async def worker_route(request: RouteRequest) -> Dict[str, Any]:
    """Walking route from start to destination.

    The shortest Dijkstra route is returned unchanged unless it actually enters the safety radius
    of a published alert. Only then are alternatives computed, and the first one that is clear is
    returned. Dijkstra runs in `safety.routing` over a graph this backend builds from OpenStreetMap
    way geometry — no external routing service is consulted.
    """
    start = (request.start.latitude, request.start.longitude)
    destination = (request.destination.latitude, request.destination.longitude)
    alerts = await run_in_threadpool(_published_alert_circles)

    try:
        result = await run_in_threadpool(
            routing.service().route, start, destination, alerts, request.safety_radius_meters)
    except routing.RoutingError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("route_failed")
        raise HTTPException(status_code=500, detail=f"Routing failed: {type(exc).__name__}") from exc

    # Persist the decision the worker just asked for. This is the ONLY route-event writer, and
    # it runs because the worker pressed a button — it is not tracking. A failure here costs the
    # audit record, never the route.
    worker = store.find_user(request.employee_id) if request.employee_id else None
    event_id = await run_in_threadpool(
        routes_history.record, result,
        {"latitude": start[0], "longitude": start[1]},
        {"latitude": destination[0], "longitude": destination[1]},
        request.employee_id,
        worker["id"] if worker and worker["role"] == "WORKER" else None,
    )

    payload = _camel(result)
    payload["routeEventId"] = event_id
    payload["classification"] = routes_history.classify(result)
    payload["note"] = ("Routes consider published safety alerts only. Reports under review are "
                       "never used and are not shown here.")
    return payload


# --- worker identity and history ------------------------------------------------------------
#
# IDENTITY IS NOT AUTHENTICATION. This project has no login, and these endpoints do not add one:
# `employee_id` is a handle, not a credential, and anyone may pass any value. What IS enforced is
# the data boundary — a worker's query is filtered to their own rows in SQL, so no response can
# contain another worker's reports or location history whatever else goes wrong. A real
# deployment needs authentication in front of every route below.

def _require_worker(employee_id: Optional[str]) -> Dict[str, Any]:
    """Resolve an employee id to a worker row, or explain why it cannot be resolved."""
    if not (employee_id or "").strip():
        raise HTTPException(status_code=422, detail="An employee_id is required.")
    user = store.find_user(employee_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No worker with employee id {employee_id!r}.")
    if user["role"] != "WORKER":
        raise HTTPException(status_code=403,
                            detail="This endpoint serves worker records only.")
    return user


def _worker_report_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """One of the worker's OWN reports, as they may see it.

    Carries the report's own facts and its risk classification, and nothing about review: no
    internal notes, no reviewer, no hotspot membership, no AI reasoning about other reports.
    """
    return {
        "id": row["id"],
        "reportText": row["report_text"],
        "createdAt": row["created_at"],
        "location": row.get("location") or row.get("location_text"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "gpsAccuracy": row.get("gps_accuracy"),
        "locationSource": row.get("location_source"),
        "locationCapturedAt": row.get("location_captured_at"),
        "riskLevel": row.get("risk_level"),
        "riskScore": row.get("risk_score"),
        "summary": row.get("summary"),
        "hazards": row.get("hazards") or [],
        "status": row.get("status"),
        "hasPhoto": bool(row.get("photo_path") or row.get("photo_source")),
        "photoSource": row.get("photo_source"),
        "photoCapturedAt": row.get("photo_captured_at"),
        "source": row.get("source"),
    }


def _public_user(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": row["id"], "employeeId": row["employee_id"], "name": row["name"],
            "email": row["email"], "role": row["role"], "department": row["department"],
            "status": row["status"], "createdAt": row["created_at"]}


@worker_router.get("/me")
async def worker_me(employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    """The worker's own profile and a count of what is on file for them."""
    worker = await run_in_threadpool(_require_worker, employee_id)
    reports = await run_in_threadpool(store.reports_for_worker, worker["id"], 500)
    locations = await run_in_threadpool(store.location_history, worker["id"], 500)
    return {
        "worker": _public_user(worker),
        "reportCount": len(reports),
        "locationEventCount": len(locations),
        "note": ("Identity is used to group your own records. It is not authentication — this "
                 "demo has no login."),
    }


@worker_router.get("/reports")
async def worker_reports(employee_id: str = Query(..., alias="employee_id"),
                         limit: int = Query(200, ge=1, le=500)) -> Dict[str, Any]:
    """This worker's own report history, newest first. Never another worker's."""
    worker = await run_in_threadpool(_require_worker, employee_id)
    rows = await run_in_threadpool(store.reports_for_worker, worker["id"], limit)
    return {"worker": _public_user(worker),
            "reports": [_worker_report_row(row) for row in rows],
            "count": len(rows)}


@worker_router.get("/reports/{report_id}")
async def worker_report_detail(report_id: int,
                               employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    """One of the worker's own reports.

    A report belonging to someone else returns 404, identically to one that does not exist:
    distinguishing the two would confirm that another worker's report exists.
    """
    worker = await run_in_threadpool(_require_worker, employee_id)
    row = await run_in_threadpool(store.report_for_worker, report_id, worker["id"])
    if row is None:
        raise HTTPException(status_code=404, detail=f"Report {report_id} was not found.")
    shaped = _worker_report_row(row)
    shaped["reasoning"] = row.get("reasoning") or []
    return {"report": shaped}


@worker_router.get("/location-history")
async def worker_location_history(employee_id: str = Query(..., alias="employee_id"),
                                  limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """This worker's own recorded location events.

    Discrete events, not a trail: each row exists because the worker asked for their location or
    filed a report carrying one. Nothing records position in the background.
    """
    worker = await run_in_threadpool(_require_worker, employee_id)
    rows = await run_in_threadpool(store.location_history, worker["id"], limit)
    return {
        "worker": _public_user(worker),
        "locations": [_camel(row) for row in rows],
        "count": len(rows),
        "note": ("Recorded only when you explicitly request your location or submit a report "
                 "with one. This system does not track workers continuously."),
    }


class LocationEventRequest(BaseModel):
    employee_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    gps_accuracy: Optional[float] = Field(default=None, ge=0)
    location_source: str = "browser_gps"
    captured_at: Optional[str] = None


@worker_router.post("/locations")
async def record_worker_location(request: LocationEventRequest) -> Dict[str, Any]:
    """Record ONE location event the worker explicitly produced.

    The only entry point besides report submission. It is a POST the client makes after the
    worker presses a button — there is no polling endpoint and no background writer.
    """
    worker = await run_in_threadpool(_require_worker, request.employee_id)
    source = request.location_source if request.location_source in LOCATION_SOURCES else "unknown"
    event_id = await run_in_threadpool(store.record_location, {
        "worker_id": worker["id"], "latitude": request.latitude, "longitude": request.longitude,
        "gps_accuracy": request.gps_accuracy, "location_source": source,
        "captured_at": request.captured_at,
    })
    return {"id": event_id, "recorded": True, "locationSource": source,
            "note": "One explicit location event. Your location is not tracked continuously."}


# --- admin views over worker records ---------------------------------------------------------

@admin_router.get("/workers")
async def admin_workers(role: Optional[str] = Query(None)) -> Dict[str, Any]:
    """The roster, with each worker's report count. Operational data, not personal detail."""
    users = await run_in_threadpool(store.list_users, role)
    out = []
    for user in users:
        reports = (await run_in_threadpool(store.reports_for_worker, user["id"], 500)
                   if user["role"] == "WORKER" else [])
        out.append({**_public_user(user), "reportCount": len(reports)})
    return {"workers": out, "count": len(out),
            "departments": list(store.DEPARTMENTS),
            "syntheticNotice": ("Synthetic demo identities. No real person's identity or location "
                                "is represented.")}


@admin_router.get("/workers/{employee_id}/reports")
async def admin_worker_reports(employee_id: str) -> Dict[str, Any]:
    """One worker's reports, for safety operations.

    Admins may see who filed what — that is what makes follow-up possible. Location history is
    deliberately NOT included: knowing where a worker has been is not needed to act on a report,
    and the reports already carry the locations that matter.
    """
    user = await run_in_threadpool(store.find_user, employee_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No worker with employee id {employee_id!r}.")
    rows = await run_in_threadpool(store.reports_for_worker, user["id"], 500)
    return {"worker": _public_user(user),
            "reports": [_worker_report_row(row) for row in rows],
            "count": len(rows)}


@admin_router.post("/seed-demo-data")
async def admin_seed_demo_data() -> Dict[str, Any]:
    """Create the synthetic roster and their report history. Idempotent; deletes nothing."""
    outcome = await run_in_threadpool(people.seed_demo_data)
    return {**outcome, "summary": await run_in_threadpool(people.summary)}


# --- India-only location validation -------------------------------------------------------------
#
# This is an India-only application. A coordinate can arrive from three places — a device GPS fix,
# a map tap, or a search result — and only the search result has already been country-checked by
# Nominatim's `countrycodes` filter. The other two are validated here.
#
# Validation is by REVERSE GEOCODING, not by a latitude/longitude box. A rectangle around India
# also contains parts of Pakistan, Nepal, Bangladesh, Myanmar and a large stretch of ocean, so a
# box would accept locations that are plainly not in India and reject legitimate ones near the
# border. The box is used only as a cheap pre-filter to avoid a network call for a coordinate that
# is obviously elsewhere.

#: Generous bounding box around India, including the island territories. Used ONLY to skip the
#: network call for a clearly-distant point; it never decides that something IS in India.
INDIA_BOX = {"south": 6.0, "north": 37.5, "west": 68.0, "east": 97.5}

INDIA_ONLY_MESSAGE = "This application currently supports locations in India."


class CoordinateCheckRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def _plausibly_india(latitude: float, longitude: float) -> bool:
    return (INDIA_BOX["south"] <= latitude <= INDIA_BOX["north"]
            and INDIA_BOX["west"] <= longitude <= INDIA_BOX["east"])


@worker_router.post("/verify-location")
async def verify_location_in_india(request: CoordinateCheckRequest) -> Dict[str, Any]:
    """Is this coordinate in India? Used for a GPS fix and for a tapped map point.

    Returns a verdict rather than raising, because the caller needs to tell the three cases apart:
    accepted, rejected as outside India, and 'could not be checked'. An unreachable geocoder must
    not silently reject a worker standing in a yard in Pune — the location is accepted with
    `verified: False` so the UI can say the country could not be confirmed.
    """
    latitude, longitude = request.latitude, request.longitude

    if not _plausibly_india(latitude, longitude):
        return {"accepted": False, "verified": True, "countryCode": None,
                "reason": INDIA_ONLY_MESSAGE, "place": None,
                "method": "bounding box — the point is far outside India"}

    try:
        place, _cached = await run_in_threadpool(
            get_geocoder().reverse, latitude, longitude)
    except Exception as exc:  # noqa: BLE001 — any geocoder failure is the same case here
        logger.warning("india_check_unverified lat=%.4f lon=%.4f: %s", latitude, longitude, exc)
        return {"accepted": True, "verified": False, "countryCode": None,
                "reason": "The country could not be confirmed, so the location was accepted as given.",
                "place": None, "method": "unverified — reverse geocoding unavailable"}

    shaped = place.as_dict()
    country = (shaped.get("country_code") or "").lower() or None
    if country and country != "in":
        return {"accepted": False, "verified": True, "countryCode": country,
                "reason": INDIA_ONLY_MESSAGE, "place": shaped.get("display_name"),
                "method": "reverse geocoded country code"}

    return {"accepted": True, "verified": bool(country), "countryCode": country,
            "reason": None, "place": shaped.get("display_name"),
            "method": "reverse geocoded country code" if country else "unverified — no country in the address"}


# --- worker caution ------------------------------------------------------------------------------

@worker_router.get("/cautions")
async def worker_cautions(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_meters: int = Query(caution.CAUTION_RADIUS_METERS, ge=50, le=5000),
) -> Dict[str, Any]:
    """Generic cautions for a worker at a point, plus any published alerts nearby.

    The two are returned separately and ranked, because they are different claims. A published
    alert is a decision a safety officer made and signed; a caution is "somebody reported
    something like this near here". Collapsing them would either inflate a caution into an alert
    or dilute an alert into advice.

    Cautions carry no report ids, no counts, no reporter and no report text — see
    `safety/caution.py` for why. They never affect routing.
    """
    corpus = await run_in_threadpool(store.all_analyses)
    found = await run_in_threadpool(
        caution.worker_cautions, corpus, latitude, longitude, radius_meters)

    published = await run_in_threadpool(store.list_announcements, True)
    alerts = [
        _public_alert(row) for row in published
        if row.get("latitude") is not None and row.get("longitude") is not None
        and geo.haversine_meters(latitude, longitude,
                                 float(row["latitude"]), float(row["longitude"]))
        <= max(float(row.get("radius_meters") or 0), radius_meters)
    ]

    return {
        "alerts": alerts,
        "cautions": found,
        "radiusMeters": radius_meters,
        # Published alerts outrank cautions; the UI renders them first.
        "priority": "published_alerts_first",
        "note": ("Cautions are general advisories based on nearby reports. They are not published "
                 "safety alerts, they do not identify who reported anything, and they do not "
                 "change your route."),
        "disclaimer": DISCLAIMER,
    }


# --- route history -------------------------------------------------------------------------
#
# Worker routes are filtered by employee_id in SQL; admin routes are not filtered at all. The
# difference is the privacy boundary, and it lives in the query rather than in a serialiser that
# a later edit could be shared with.

def _route_event(row: Dict[str, Any], *, for_worker: bool) -> Dict[str, Any]:
    """One route event. `for_worker` drops the fields a worker has no business seeing.

    A worker gets their own route and the published alert that changed it — both things they
    were already shown live. They do not get their own name and department echoed back as a
    record, nor anything about other workers.
    """
    shaped = {
        "id": row["id"],
        "createdAt": row["created_at"],
        "start": {"latitude": row["start_latitude"], "longitude": row["start_longitude"]},
        "destination": {"latitude": row["destination_latitude"],
                        "longitude": row["destination_longitude"]},
        "originalDistanceMeters": row["original_distance_meters"],
        "selectedDistanceMeters": row["selected_distance_meters"],
        "detourDistanceMeters": row["detour_distance_meters"],
        "detourRatio": row["detour_ratio"],
        "routeAdjustedForSafety": row["route_adjusted_for_safety"],
        "safeAlternativeFound": row["safe_alternative_found"],
        "selectedReason": row["selected_reason"],
        "classification": row["classification"],
        "classificationLabel": routes_history.CLASSIFICATION_LABEL.get(
            row["classification"], row["classification"]),
        "safetyRadiusMeters": row["safety_radius_meters"],
        "originalRouteGeometry": row["original_route_geometry"],
        "selectedRouteGeometry": row["selected_route_geometry"],
        "alert": {
            "id": row["affecting_alert_id"],
            "title": row["affecting_alert_title"],
            "severity": row["affecting_alert_severity"],
            "latitude": row["affecting_alert_latitude"],
            "longitude": row["affecting_alert_longitude"],
            "radiusMeters": row["affecting_alert_radius_meters"],
            "minimumDistanceMeters": row["minimum_distance_to_alert_meters"],
        } if row.get("affecting_alert_id") is not None else None,
    }
    if not for_worker:
        shaped["employeeId"] = row.get("employee_id")
        shaped["workerName"] = row.get("worker_name")
        shaped["department"] = row.get("worker_department")
        shaped["alertsNearRoute"] = row.get("alerts_near_route") or []
    return shaped


@worker_router.get("/routes")
async def worker_routes(employee_id: str = Query(..., alias="employee_id"),
                        limit: int = Query(50, ge=1, le=200)) -> Dict[str, Any]:
    """This worker's own recorded routes, newest first."""
    worker = await run_in_threadpool(_require_worker, employee_id)
    rows = await run_in_threadpool(
        store.list_route_events, employee_id, None, None, None, None, limit)
    return {
        "worker": _public_user(worker),
        "routes": [_route_event(row, for_worker=True) for row in rows],
        "count": len(rows),
        "note": ("Recorded only when you request a route. Routes calculated before this feature "
                 "existed were not recorded and cannot be shown."),
    }


@worker_router.get("/routes/{route_event_id}")
async def worker_route_detail(route_event_id: int,
                              employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    worker = await run_in_threadpool(_require_worker, employee_id)
    row = await run_in_threadpool(store.get_route_event, route_event_id, worker["employee_id"])
    if row is None:
        raise HTTPException(status_code=404, detail=f"Route event {route_event_id} was not found.")
    return {"route": _route_event(row, for_worker=True)}


@admin_router.get("/routes")
async def admin_routes(
    employee_id: Optional[str] = Query(None),
    classification: Optional[str] = Query(None),
    alert_id: Optional[int] = Query(None),
    department: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
) -> Dict[str, Any]:
    """Worker Route Intelligence: every recorded route event, with filters and a summary."""
    if classification and classification not in routes_history.CLASSIFICATIONS:
        raise HTTPException(status_code=422,
                            detail=f"classification must be one of {list(routes_history.CLASSIFICATIONS)}.")
    rows = await run_in_threadpool(
        store.list_route_events, employee_id, classification, alert_id, since, until, limit)
    # Department is on the joined user row, so it filters here rather than in SQL.
    if department:
        rows = [r for r in rows if (r.get("worker_department") or "") == department]

    return {
        "routes": [_route_event(row, for_worker=False) for row in rows],
        "count": len(rows),
        "summary": _camel(routes_history.summarise(rows)),
        "classifications": [{"id": name, "label": routes_history.CLASSIFICATION_LABEL[name]}
                            for name in routes_history.CLASSIFICATIONS],
        "departments": list(store.DEPARTMENTS),
    }


@admin_router.get("/routes/{route_event_id}")
async def admin_route_detail(route_event_id: int) -> Dict[str, Any]:
    row = await run_in_threadpool(store.get_route_event, route_event_id, None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Route event {route_event_id} was not found.")
    return {"route": _route_event(row, for_worker=False)}


@admin_router.get("/workers/{employee_id}/routes")
async def admin_worker_routes(employee_id: str,
                              limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    user = await run_in_threadpool(store.find_user, employee_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"No worker with employee id {employee_id!r}.")
    rows = await run_in_threadpool(
        store.list_route_events, employee_id, None, None, None, None, limit)
    return {"worker": _public_user(user),
            "routes": [_route_event(row, for_worker=False) for row in rows],
            "count": len(rows),
            "summary": _camel(routes_history.summarise(rows))}


@admin_router.get("/alerts/{alert_id}/affected-workers")
async def admin_alert_affected_workers(alert_id: int) -> Dict[str, Any]:
    """Workers whose STORED route geometry actually entered this alert's safety area.

    Evidence-based, not inferred. A worker is listed because the route they were served came
    within the safety radius, recorded at the time — never because their destination happened to
    be nearby. Routes calculated before this feature existed are not represented, and the
    response says so rather than implying the list is complete.
    """
    rows = await run_in_threadpool(
        store.list_route_events, None, None, alert_id, None, None, 500)
    affected = [row for row in rows
                if row.get("minimum_distance_to_alert_meters") is not None
                and row.get("affecting_alert_radius_meters") is not None
                and row["minimum_distance_to_alert_meters"]
                <= (row.get("safety_radius_meters") or routing.ROUTE_SAFETY_RADIUS_METERS)]

    return {
        "alertId": alert_id,
        "workers": [{
            "employeeId": row.get("employee_id"),
            "workerName": row.get("worker_name"),
            "department": row.get("worker_department"),
            "routeEventId": row["id"],
            "timestamp": row["created_at"],
            "start": {"latitude": row["start_latitude"], "longitude": row["start_longitude"]},
            "destination": {"latitude": row["destination_latitude"],
                            "longitude": row["destination_longitude"]},
            "routeDistanceMeters": row["selected_distance_meters"],
            "minimumDistanceToAlertMeters": row["minimum_distance_to_alert_meters"],
            "classification": row["classification"],
        } for row in affected],
        "count": len(affected),
        "evidence": "stored route geometry recorded at the time each route was requested",
        "coverageNote": ("Only routes requested after route-event recording was introduced appear "
                         "here. Absence from this list is not evidence that nobody passed through."),
    }


@admin_router.get("/alerts/{alert_id}/rerouted-workers")
async def admin_alert_rerouted_workers(alert_id: int) -> Dict[str, Any]:
    """Workers whose route was actually changed by this alert, with both geometries."""
    rows = await run_in_threadpool(
        store.list_route_events, None, None, alert_id, None, None, 500)
    rerouted = [row for row in rows if row.get("route_adjusted_for_safety")]

    return {
        "alertId": alert_id,
        "workers": [{
            "employeeId": row.get("employee_id"),
            "workerName": row.get("worker_name"),
            "department": row.get("worker_department"),
            "routeEventId": row["id"],
            "timestamp": row["created_at"],
            "originalDistanceMeters": row["original_distance_meters"],
            "selectedDistanceMeters": row["selected_distance_meters"],
            "additionalDistanceMeters": row["detour_distance_meters"],
            "detourRatio": row["detour_ratio"],
            "originalRouteGeometry": row["original_route_geometry"],
            "selectedRouteGeometry": row["selected_route_geometry"],
            "alert": {"id": row["affecting_alert_id"], "title": row["affecting_alert_title"],
                      "severity": row["affecting_alert_severity"],
                      "latitude": row["affecting_alert_latitude"],
                      "longitude": row["affecting_alert_longitude"],
                      "radiusMeters": row["affecting_alert_radius_meters"]},
            "selectedReason": row["selected_reason"],
        } for row in rerouted],
        "count": len(rerouted),
        "coverageNote": ("Only routes requested after route-event recording was introduced appear "
                         "here."),
    }


# --- the safety chatbot ---------------------------------------------------------------------
#
# Mounted at /api/safety/chat rather than extending /api/chat. The existing endpoint answers
# questions about one environmental `analysisId` and is grounded in that analysis; this one is
# grounded in the safety database and is role-scoped. Merging them would mean one endpoint with
# two incompatible grounding rules, and a worker could then reach the environmental path.

chat_router = APIRouter(prefix="/api/safety", tags=["safety-chat"])


class SafetyChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    #: "admin" or "worker". Chooses the tool table; a worker's table is a strict subset.
    role: str = "admin"
    #: The asking worker. Used for worker-scoped tools — NEVER read from the question, so naming
    #: another worker cannot widen what is returned.
    employee_id: Optional[str] = None
    #: What the user is looking at (an alert id, a hotspot id, a map position), so "who passed
    #: through this" resolves without repeating the identifier.
    context: Optional[Dict[str, Any]] = None


@chat_router.post("/chat")
async def safety_chat(request: SafetyChatRequest) -> Dict[str, Any]:
    """Answer a question from the safety database through controlled, read-only tools."""
    role = "worker" if request.role == "worker" else "admin"

    caller = None
    if role == "worker":
        # A worker must identify themselves, and it is that id — not anything in the question —
        # that scopes every worker tool.
        worker = await run_in_threadpool(_require_worker, request.employee_id)
        caller = worker["employee_id"]

    result = await run_in_threadpool(
        chat.ask, request.question, role, caller, request.context or {})

    return {
        **result,
        "role": role,
        "note": ("Answers come from this project's stored records through fixed read-only "
                 "queries. The assistant explains safety decisions; it never makes or changes "
                 "them."),
        "disclaimer": DISCLAIMER,
    }


# --- notifications -------------------------------------------------------------------------
#
# Read access is decided by `store.notifications_for`, whose WHERE clause is the boundary: a
# worker's query cannot return a message addressed to another worker. These handlers add the
# role and identity, and shape the payload — they do not re-filter, because a second filter is
# a second thing to get wrong.

def _notification(row: Dict[str, Any], *, for_worker: bool) -> Dict[str, Any]:
    shaped = {
        "id": row["id"],
        "type": row["notification_type"],
        "title": row["title"],
        "message": row["message"],
        "severity": row.get("severity"),
        "createdAt": row["created_at"],
        "read": row.get("read", False),
        "readAt": row.get("read_at"),
        "latitude": row.get("latitude"),
        "longitude": row.get("longitude"),
        "radiusMeters": row.get("radius_meters"),
        "expiresAt": row.get("expires_at"),
    }
    if for_worker:
        # A worker sees the message, never the evidence behind somebody else's report: no report
        # id, no GPS accuracy, no extracted risk factors.
        #
        # The SENDER is the one exception, and only for a message a person chose to send. An
        # unattributable message is worse than an attributed one — the reader cannot weigh it,
        # answer it, or report misuse. The automatic REPORT_SUBMITTED notification is not in
        # ATTRIBUTED_TYPES, so a worker can never learn who filed a report this way.
        if row.get("notification_type") in store.ATTRIBUTED_TYPES:
            shaped["senderEmployeeId"] = row.get("sender_employee_id")
            shaped["senderName"] = row.get("sender_name")
        return shaped
    return {
        **shaped,
        "senderEmployeeId": row.get("sender_employee_id"),
        "recipientEmployeeId": row.get("recipient_employee_id"),
        "reportId": row.get("report_id"),
        "gpsAccuracy": row.get("gps_accuracy"),
        "locationSource": row.get("location_source"),
        "metadata": row.get("metadata") or {},
    }


@admin_router.get("/notifications")
async def admin_notifications(unread_only: bool = Query(False),
                              limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """The admin notification centre: what workers have reported, newest first."""
    rows = await run_in_threadpool(
        store.notifications_for, "SAFETY_ADMIN", "ADMIN001", limit, unread_only)
    unread = await run_in_threadpool(store.unread_count, "SAFETY_ADMIN", "ADMIN001")
    return {"notifications": [_notification(r, for_worker=False) for r in rows],
            "count": len(rows), "unreadCount": unread}


@admin_router.post("/notifications/{notification_id}/read")
async def admin_mark_read(notification_id: int) -> Dict[str, Any]:
    ok = await run_in_threadpool(
        store.mark_notification_read, notification_id, "SAFETY_ADMIN", "ADMIN001")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} was not found.")
    return {"id": notification_id, "read": True,
            "unreadCount": await run_in_threadpool(store.unread_count, "SAFETY_ADMIN", "ADMIN001")}


@admin_router.post("/notifications/read-all")
async def admin_mark_all_read() -> Dict[str, Any]:
    marked = await run_in_threadpool(store.mark_all_notifications_read, "SAFETY_ADMIN", "ADMIN001")
    return {"marked": marked, "unreadCount": 0}


class BroadcastRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    severity: str = "MEDIUM"
    #: Empty or omitted broadcasts to every worker; otherwise the named workers only.
    employee_ids: Optional[List[str]] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    radius_meters: Optional[int] = Field(default=None, ge=50, le=20000)
    expires_at: Optional[str] = None


@admin_router.post("/notifications/send")
async def admin_send_notification(request: BroadcastRequest) -> Dict[str, Any]:
    """Send an announcement to every worker, or a targeted message to named workers.

    This is a MESSAGE, not a published safety alert: it does not enter routing. Only
    `POST /api/admin/announcements` creates something a route reacts to, and the two are kept
    apart so an admin cannot change worker routing by writing a notice.
    """
    base = {
        "recipient_role": "WORKER",
        "sender_employee_id": "ADMIN001",
        "title": request.title, "message": request.message,
        "severity": request.severity,
        "latitude": request.latitude, "longitude": request.longitude,
        "radius_meters": request.radius_meters, "expires_at": request.expires_at,
    }

    created: List[int] = []
    targets = [e.strip() for e in (request.employee_ids or []) if e.strip()]
    if targets:
        for employee_id in targets:
            worker = await run_in_threadpool(store.find_user, employee_id)
            if worker is None or worker["role"] != "WORKER":
                raise HTTPException(status_code=404,
                                    detail=f"No worker with employee id {employee_id!r}.")
            created.append(await run_in_threadpool(store.create_notification, {
                **base, "notification_type": "DIRECT_MESSAGE",
                "recipient_employee_id": employee_id}))
    else:
        created.append(await run_in_threadpool(store.create_notification, {
            **base, "notification_type": "ANNOUNCEMENT", "recipient_employee_id": None}))

    return {"ids": created, "count": len(created),
            "delivery": "targeted" if targets else "broadcast",
            "note": ("An announcement is a message to workers. It does not affect routing — only "
                     "a published safety alert does.")}


@worker_router.get("/notifications")
async def worker_notifications(employee_id: str = Query(..., alias="employee_id"),
                               unread_only: bool = Query(False),
                               limit: int = Query(100, ge=1, le=500)) -> Dict[str, Any]:
    """This worker's own notifications: broadcasts, and messages addressed to them."""
    worker = await run_in_threadpool(_require_worker, employee_id)
    rows = await run_in_threadpool(
        store.notifications_for, "WORKER", worker["employee_id"], limit, unread_only)
    unread = await run_in_threadpool(store.unread_count, "WORKER", worker["employee_id"])
    return {"notifications": [_notification(r, for_worker=True) for r in rows],
            "count": len(rows), "unreadCount": unread,
            "note": ("Announcements from the safety team. Published safety alerts appear "
                     "separately on your Safety Map.")}


@worker_router.post("/notifications/{notification_id}/read")
async def worker_mark_read(notification_id: int,
                           employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    worker = await run_in_threadpool(_require_worker, employee_id)
    ok = await run_in_threadpool(
        store.mark_notification_read, notification_id, "WORKER", worker["employee_id"])
    if not ok:
        raise HTTPException(status_code=404, detail=f"Notification {notification_id} was not found.")
    return {"id": notification_id, "read": True,
            "unreadCount": await run_in_threadpool(
                store.unread_count, "WORKER", worker["employee_id"])}


@worker_router.post("/notifications/read-all")
async def worker_mark_all_read(employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    worker = await run_in_threadpool(_require_worker, employee_id)
    marked = await run_in_threadpool(
        store.mark_all_notifications_read, "WORKER", worker["employee_id"])
    return {"marked": marked, "unreadCount": 0}


# --- worker-initiated messages ------------------------------------------------------------
#
# The other direction. A worker can message the safety admin, and can message named colleagues.
#
# Worker-to-worker messaging deliberately relaxes the anonymity this system otherwise keeps
# between workers: to address a colleague you must know they exist, and they see who wrote to
# you. That is stated in the API response rather than left implicit, and it is why the directory
# below exposes only an id, a name and a department — never anyone's reports, location or
# history. Reporting stays anonymous: a REPORT_SUBMITTED notification is never attributed to a
# worker in any worker-visible payload.

class WorkerMessageRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    message: str = Field(min_length=1, max_length=4000)
    #: Who is writing. Required — an unattributable message cannot be weighed or answered.
    employee_id: str
    #: "admin" sends to the safety team. Otherwise the named colleagues.
    to_admin: bool = True
    recipient_employee_ids: Optional[List[str]] = None


@worker_router.get("/directory")
async def worker_directory(employee_id: str = Query(..., alias="employee_id")) -> Dict[str, Any]:
    """Who a worker can message: the safety admin, and their colleagues.

    Identity only — an id, a name and a department. No reports, no locations, no history, no
    counts. Enough to address a message to somebody, and nothing more.
    """
    await run_in_threadpool(_require_worker, employee_id)
    workers = await run_in_threadpool(store.list_users, "WORKER")
    return {
        "admin": {"label": "Safety Admin", "employeeId": "ADMIN001"},
        "colleagues": [
            {"employeeId": w["employee_id"], "name": w["name"], "department": w["department"]}
            for w in workers if w["employee_id"] != employee_id
        ],
        "note": ("Messaging a colleague shows them your employee ID. Safety reports stay "
                 "anonymous to other workers — this is separate from reporting."),
    }


@worker_router.post("/notifications/send")
async def worker_send_notification(request: WorkerMessageRequest) -> Dict[str, Any]:
    """Send a message to the safety admin, or to named colleagues."""
    sender = await run_in_threadpool(_require_worker, request.employee_id)
    targets = [e.strip() for e in (request.recipient_employee_ids or []) if e.strip()]

    if not request.to_admin and not targets:
        raise HTTPException(status_code=422,
                            detail="Choose the safety admin or at least one colleague.")

    base = {
        "notification_type": "WORKER_MESSAGE",
        "sender_employee_id": sender["employee_id"],
        "title": request.title,
        "message": request.message,
    }

    created: List[int] = []
    if request.to_admin:
        created.append(await run_in_threadpool(store.create_notification, {
            **base, "recipient_role": "SAFETY_ADMIN", "recipient_employee_id": None}))

    for recipient in targets:
        if recipient == sender["employee_id"]:
            continue                      # messaging yourself is a no-op, not an error
        worker = await run_in_threadpool(store.find_user, recipient)
        if worker is None or worker["role"] != "WORKER":
            raise HTTPException(status_code=404,
                                detail=f"No worker with employee id {recipient!r}.")
        created.append(await run_in_threadpool(store.create_notification, {
            **base, "recipient_role": "WORKER", "recipient_employee_id": recipient}))

    return {
        "ids": created, "count": len(created),
        "sentToAdmin": request.to_admin,
        "sentToColleagues": len([t for t in targets if t != sender["employee_id"]]),
        "note": ("Recipients see your employee ID. This is a message, not a safety report — "
                 "it is not analysed, does not create a hotspot, and does not affect routing."),
    }
