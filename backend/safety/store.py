"""SQLite persistence for safety reports and their analyses.

Standard-library `sqlite3` rather than an ORM: three tables, no migrations, no new dependency, and
the whole schema is visible in one screen. The project had no database before this, so there was
nothing to adapt and nothing to break.

JSON-shaped fields (hazards, reasoning, contributions) are stored as TEXT holding JSON. A safety
report's structure is read whole and never queried field-by-field, so normalising those into their
own tables would add joins and migrations for no query we actually make.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

#: Overridable so a hosted deployment can point these at a mounted persistent disk. Render's
#: ordinary filesystem is ephemeral — without a disk mounted at these paths the database and the
#: uploaded photos are lost on every deploy and restart. Module-level on purpose: the tests
#: monkeypatch these attributes, which a function would not allow.
DB_PATH = Path(os.getenv("ECOSENTINEL_DB_PATH")
               or Path(__file__).resolve().parents[1] / "data" / "safety.db")

#: sqlite3 connections are not safe to share across threads, and FastAPI runs handlers in a
#: threadpool. One lock around short writes is simpler than a pool and fast enough at this size.
_LOCK = threading.Lock()

SCHEMA = """
-- The project had no user model before this. One is added here rather than bolted onto the
-- report rows, so a worker exists independently of whether they have reported anything.
--
-- These are SYNTHETIC demo identities. `employee_id` is the stable natural key: seeding matches
-- on it, which is what makes re-seeding idempotent without needing to wipe anything.
CREATE TABLE IF NOT EXISTS safety_user (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT    NOT NULL UNIQUE,
    name        TEXT    NOT NULL,
    email       TEXT,
    role        TEXT    NOT NULL DEFAULT 'WORKER',
    department  TEXT,
    status      TEXT    NOT NULL DEFAULT 'ACTIVE',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

-- Discrete location EVENTS, never a movement trail. A row appears only when a worker explicitly
-- asks for their location or files a report carrying one; nothing writes here on a timer, and
-- there is no code path that records a position the worker did not deliberately produce.
CREATE TABLE IF NOT EXISTS worker_location (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id       INTEGER NOT NULL REFERENCES safety_user(id) ON DELETE CASCADE,
    latitude        REAL    NOT NULL,
    longitude       REAL    NOT NULL,
    gps_accuracy    REAL,
    location_source TEXT    NOT NULL DEFAULT 'unknown',
    -- Set when the event came from filing a report, so a location can be traced to its cause.
    report_id       INTEGER REFERENCES safety_report(id) ON DELETE SET NULL,
    captured_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_report (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    report_text     TEXT    NOT NULL,
    source          TEXT    NOT NULL DEFAULT 'user',
    created_at      TEXT    NOT NULL,
    reported_at     TEXT,
    location        TEXT,
    department      TEXT,
    equipment       TEXT,
    incident_type   TEXT,
    status          TEXT    NOT NULL DEFAULT 'analyzed',
    -- Raw coordinates kept separate from the human-readable location: a place name can be wrong
    -- or missing without invalidating the fix the device actually reported.
    latitude        REAL,
    longitude       REAL,
    gps_accuracy    REAL,
    location_source TEXT    NOT NULL DEFAULT 'unknown',
    location_text   TEXT,
    location_captured_at TEXT,
    -- Photo evidence. The file lives on disk (data/report_photos/); only its relative path is
    -- stored, so the database stays small and the image is servable as a static file.
    photo_path      TEXT,
    photo_mime      TEXT,
    -- 'live_camera' when captured through the in-app camera, 'upload' when chosen from disk.
    -- The distinction matters: only a live capture is contemporaneous with the GPS fix.
    photo_source    TEXT,
    photo_captured_at TEXT
);

CREATE TABLE IF NOT EXISTS report_analysis (
    report_id            INTEGER PRIMARY KEY REFERENCES safety_report(id) ON DELETE CASCADE,
    risk_level           TEXT    NOT NULL,
    risk_score           INTEGER NOT NULL,
    summary              TEXT,
    hazards              TEXT    NOT NULL DEFAULT '[]',
    risk_factors         TEXT    NOT NULL DEFAULT '[]',
    missing_controls     TEXT    NOT NULL DEFAULT '[]',
    root_cause           TEXT,
    contributing_factors TEXT    NOT NULL DEFAULT '[]',
    severity_indicators  TEXT    NOT NULL DEFAULT '[]',
    injury_present       INTEGER,
    ppe_issue            INTEGER,
    confidence           REAL    NOT NULL DEFAULT 0,
    reasoning            TEXT    NOT NULL DEFAULT '[]',
    contributions        TEXT    NOT NULL DEFAULT '[]',
    recommendations      TEXT    NOT NULL DEFAULT '{}',
    narrative_source     TEXT    NOT NULL DEFAULT 'rules',
    analyzed_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS pattern_analysis (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at      TEXT NOT NULL,
    report_count      INTEGER NOT NULL,
    top_hazards       TEXT NOT NULL DEFAULT '[]',
    top_locations     TEXT NOT NULL DEFAULT '[]',
    top_departments   TEXT NOT NULL DEFAULT '[]',
    recurring_causes  TEXT NOT NULL DEFAULT '[]',
    emerging_patterns TEXT NOT NULL DEFAULT '[]',
    summary           TEXT
);

CREATE TABLE IF NOT EXISTS safety_hotspot (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    latitude            REAL    NOT NULL,
    longitude           REAL    NOT NULL,
    radius_meters       INTEGER NOT NULL DEFAULT 1000,
    report_count        INTEGER NOT NULL,
    primary_hazard      TEXT,
    related_hazards     TEXT    NOT NULL DEFAULT '[]',
    risk_level          TEXT    NOT NULL DEFAULT 'LOW',
    first_report_at     TEXT,
    latest_report_at    TEXT,
    report_ids          TEXT    NOT NULL DEFAULT '[]',
    locations           TEXT    NOT NULL DEFAULT '[]',
    explanation         TEXT,
    -- 'ai_detected' or 'admin_flagged'. The UI must not present the two as the same thing.
    flag_source         TEXT    NOT NULL DEFAULT 'ai_detected',
    status              TEXT    NOT NULL DEFAULT 'PENDING_REVIEW',
    review_notes        TEXT,
    reviewed_by         TEXT,
    severity            TEXT,
    reason              TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS safety_announcement (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id    INTEGER REFERENCES safety_hotspot(id) ON DELETE SET NULL,
    title         TEXT    NOT NULL,
    message       TEXT    NOT NULL,
    severity      TEXT    NOT NULL DEFAULT 'HIGH',
    latitude      REAL,
    longitude     REAL,
    radius_meters INTEGER NOT NULL DEFAULT 1000,
    location_text TEXT,
    -- Only 'PUBLISHED' rows are ever returned to a worker.
    status        TEXT    NOT NULL DEFAULT 'PUBLISHED',
    -- When 1, safety-aware routing treats the area as non-traversable rather than merely
    -- expensive. Set deliberately by an admin closing an area, never inferred from severity.
    restricted    INTEGER NOT NULL DEFAULT 0,
    expires_at    TEXT,
    created_at    TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_action (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id           INTEGER REFERENCES safety_hotspot(id) ON DELETE CASCADE,
    report_id            INTEGER REFERENCES safety_report(id) ON DELETE CASCADE,
    -- What the admin actually did, e.g. 'contacted_police'. Recorded, never performed by us:
    -- the system does not contact anyone.
    action_taken         TEXT    NOT NULL,
    authority_contacted  TEXT,
    admin_notes          TEXT,
    outcome              TEXT,
    follow_up_required   INTEGER NOT NULL DEFAULT 0,
    recorded_by          TEXT    NOT NULL DEFAULT 'safety_admin',
    action_timestamp     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    hotspot_id    INTEGER REFERENCES safety_hotspot(id) ON DELETE CASCADE,
    report_id     INTEGER REFERENCES safety_report(id) ON DELETE CASCADE,
    useful        INTEGER NOT NULL,
    reason        TEXT,
    comment       TEXT,
    submitted_by  TEXT    NOT NULL DEFAULT 'safety_admin',
    created_at    TEXT    NOT NULL
);

-- One row per explicit POST /api/worker/route. NOT a location trail: it records a decision the
-- worker asked the system to make, at the moment they asked for it. Nothing writes here on a
-- timer, and there is no watchPosition anywhere in the project.
--
-- The route GEOMETRY is stored, not just the endpoints. A route recomputed later from start and
-- destination would reflect today's map and today's alerts, which is precisely what historical
-- evidence must not do.
CREATE TABLE IF NOT EXISTS worker_route_event (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id                   INTEGER REFERENCES safety_user(id) ON DELETE SET NULL,
    employee_id                 TEXT,
    created_at                  TEXT    NOT NULL,

    start_latitude              REAL    NOT NULL,
    start_longitude             REAL    NOT NULL,
    destination_latitude        REAL    NOT NULL,
    destination_longitude       REAL    NOT NULL,

    -- The shortest Dijkstra route, always, even when it was the one selected.
    original_distance_meters    INTEGER,
    original_route_geometry     TEXT    NOT NULL DEFAULT '[]',
    -- What the worker was actually given.
    selected_distance_meters    INTEGER,
    selected_route_geometry     TEXT    NOT NULL DEFAULT '[]',

    route_adjusted_for_safety   INTEGER NOT NULL DEFAULT 0,
    -- NULL when no alternative was needed; 1/0 once one was sought.
    safe_alternative_found      INTEGER,
    selected_reason             TEXT,
    alerts_near_route           TEXT    NOT NULL DEFAULT '[]',

    -- The published alert that drove the decision, denormalised so the event stays readable
    -- after the alert is archived or its radius edited.
    affecting_alert_id          INTEGER,
    affecting_alert_title       TEXT,
    affecting_alert_severity    TEXT,
    affecting_alert_latitude    REAL,
    affecting_alert_longitude   REAL,
    affecting_alert_radius_meters INTEGER,
    minimum_distance_to_alert_meters INTEGER,

    detour_distance_meters      INTEGER NOT NULL DEFAULT 0,
    detour_ratio                REAL    NOT NULL DEFAULT 1.0,
    -- Deterministic; see safety/routes_history.py. Never set by a model.
    classification              TEXT    NOT NULL DEFAULT 'NORMAL_ROUTE',
    safety_radius_meters        INTEGER
);

-- Worker -> Admin and Admin -> Worker messages. One table for both directions: a notification
-- is addressed either to a ROLE (every admin, every worker) or to one employee, and keeping the
-- two directions in one place is what makes "who may read this" a single WHERE clause instead of
-- a rule repeated in two serialisers.
CREATE TABLE IF NOT EXISTS safety_notification (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    -- 'SAFETY_ADMIN' or 'WORKER'. With recipient_employee_id NULL this is a broadcast to the role.
    recipient_role       TEXT    NOT NULL,
    -- Set for a targeted message; NULL for a broadcast.
    recipient_employee_id TEXT,
    sender_employee_id   TEXT,
    notification_type    TEXT    NOT NULL,
    title                TEXT    NOT NULL,
    message              TEXT    NOT NULL,
    report_id            INTEGER REFERENCES safety_report(id) ON DELETE SET NULL,
    latitude             REAL,
    longitude            REAL,
    gps_accuracy         REAL,
    location_source      TEXT,
    severity             TEXT,
    radius_meters        INTEGER,
    expires_at           TEXT,
    -- Per-recipient read state. A broadcast is marked read by the reader, so `read_at` on a
    -- broadcast row would be wrong; broadcasts are tracked in notification_read instead.
    read_at              TEXT,
    metadata             TEXT    NOT NULL DEFAULT '{}',
    created_at           TEXT    NOT NULL
);

-- Read receipts for BROADCASTS. A broadcast is one row seen by many people, so "read" cannot
-- live on it — one worker opening an announcement would mark it read for everybody.
CREATE TABLE IF NOT EXISTS notification_read (
    notification_id INTEGER NOT NULL REFERENCES safety_notification(id) ON DELETE CASCADE,
    employee_id     TEXT    NOT NULL,
    read_at         TEXT    NOT NULL,
    PRIMARY KEY (notification_id, employee_id)
);

CREATE INDEX IF NOT EXISTS idx_notif_role      ON safety_notification(recipient_role);
CREATE INDEX IF NOT EXISTS idx_notif_employee  ON safety_notification(recipient_employee_id);
CREATE INDEX IF NOT EXISTS idx_notif_created   ON safety_notification(created_at);
CREATE INDEX IF NOT EXISTS idx_notif_type      ON safety_notification(notification_type);
CREATE INDEX IF NOT EXISTS idx_route_worker      ON worker_route_event(worker_id);
CREATE INDEX IF NOT EXISTS idx_route_employee    ON worker_route_event(employee_id);
CREATE INDEX IF NOT EXISTS idx_route_created     ON worker_route_event(created_at);
CREATE INDEX IF NOT EXISTS idx_route_class       ON worker_route_event(classification);
CREATE INDEX IF NOT EXISTS idx_route_alert       ON worker_route_event(affecting_alert_id);
CREATE INDEX IF NOT EXISTS idx_user_employee     ON safety_user(employee_id);
CREATE INDEX IF NOT EXISTS idx_user_role         ON safety_user(role);
CREATE INDEX IF NOT EXISTS idx_wloc_worker       ON worker_location(worker_id);
CREATE INDEX IF NOT EXISTS idx_wloc_captured     ON worker_location(captured_at);
CREATE INDEX IF NOT EXISTS idx_wloc_coords       ON worker_location(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_report_created    ON safety_report(created_at);
CREATE INDEX IF NOT EXISTS idx_report_status     ON safety_report(status);
CREATE INDEX IF NOT EXISTS idx_report_coords     ON safety_report(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_action_hotspot    ON admin_action(hotspot_id);
CREATE INDEX IF NOT EXISTS idx_feedback_hotspot  ON recommendation_feedback(hotspot_id);
CREATE INDEX IF NOT EXISTS idx_hotspot_status     ON safety_hotspot(status);
CREATE INDEX IF NOT EXISTS idx_announce_status    ON safety_announcement(status);
CREATE INDEX IF NOT EXISTS idx_report_location   ON safety_report(location);
CREATE INDEX IF NOT EXISTS idx_report_department ON safety_report(department);
CREATE INDEX IF NOT EXISTS idx_analysis_level    ON report_analysis(risk_level);
"""

_JSON_FIELDS = {
    "hazards", "risk_factors", "missing_controls", "contributing_factors",
    "severity_indicators", "reasoning", "contributions", "recommendations",
    "top_hazards", "top_locations", "top_departments", "recurring_causes", "emerging_patterns",
    "related_hazards", "report_ids", "locations",
    "original_route_geometry", "selected_route_geometry", "alerts_near_route", "metadata",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    target = Path(path) if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


#: Columns added after the first release. Applied on every init so an existing database picks
#: them up without a migration tool — cheap at this size and avoids a drop/recreate that would
#: throw away the seeded corpus.
_LATER_COLUMNS = [
    ("safety_report", "latitude", "REAL"),
    ("safety_report", "longitude", "REAL"),
    ("safety_report", "gps_accuracy", "REAL"),
    ("safety_report", "location_source", "TEXT NOT NULL DEFAULT 'unknown'"),
    ("safety_report", "location_text", "TEXT"),
    ("safety_report", "location_captured_at", "TEXT"),
    ("safety_report", "photo_path", "TEXT"),
    ("safety_report", "photo_mime", "TEXT"),
    ("safety_report", "photo_source", "TEXT"),
    ("safety_report", "photo_captured_at", "TEXT"),
    ("safety_announcement", "restricted", "INTEGER NOT NULL DEFAULT 0"),
    ("safety_report", "worker_id", "INTEGER REFERENCES safety_user(id)"),
]


#: Indexes over columns that arrive via `_LATER_COLUMNS`. They cannot live in SCHEMA, because on
#: an existing database SCHEMA runs BEFORE the ALTER TABLEs and the column does not exist yet.
_LATER_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_report_worker ON safety_report(worker_id)",
]


def init(path: Optional[Path] = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.executescript(SCHEMA)
        for table, column, decl in _LATER_COLUMNS:
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        for statement in _LATER_INDEXES:
            conn.execute(statement)
        # Ensure exactly ONE demo Safety Admin and clean up unreferenced legacy demo admin rows
        conn.execute(
            """DELETE FROM safety_user
               WHERE role = 'SAFETY_ADMIN' AND employee_id != 'ADMIN001'
                 AND id NOT IN (SELECT DISTINCT worker_id FROM safety_report WHERE worker_id IS NOT NULL)
                 AND id NOT IN (SELECT DISTINCT worker_id FROM worker_location WHERE worker_id IS NOT NULL)"""
        )


def _decode(row: sqlite3.Row) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in row.keys():
        value = row[key]
        if key in _JSON_FIELDS and isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                value = [] if key != "recommendations" else {}
        out[key] = value
    return out


def save_report(report: Dict[str, Any], analysis: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Persist one report with its analysis. Returns the new report id."""
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO safety_report
               (report_text, source, created_at, reported_at, location, department,
                equipment, incident_type, status, latitude, longitude, gps_accuracy,
                location_source, location_text, location_captured_at,
                photo_path, photo_mime, photo_source, photo_captured_at, worker_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report["report_text"], report.get("source", "user"), _now(),
             report.get("reported_at"), report.get("location"), report.get("department"),
             report.get("equipment"), report.get("incident_type"),
             report.get("status", "analyzed"),
             report.get("latitude"), report.get("longitude"), report.get("gps_accuracy"),
             report.get("location_source", "unknown"), report.get("location_text"),
             report.get("location_captured_at"),
             report.get("photo_path"), report.get("photo_mime"),
             report.get("photo_source"), report.get("photo_captured_at"),
             report.get("worker_id")),
        )
        report_id = int(cur.lastrowid)
        conn.execute(
            """INSERT INTO report_analysis
               (report_id, risk_level, risk_score, summary, hazards, risk_factors,
                missing_controls, root_cause, contributing_factors, severity_indicators,
                injury_present, ppe_issue, confidence, reasoning, contributions,
                recommendations, narrative_source, analyzed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (report_id, analysis["risk_level"], int(analysis["risk_score"]),
             analysis.get("summary"),
             json.dumps(analysis.get("hazards", [])),
             json.dumps(analysis.get("risk_factors", [])),
             json.dumps(analysis.get("missing_controls", [])),
             analysis.get("root_cause"),
             json.dumps(analysis.get("contributing_factors", [])),
             json.dumps(analysis.get("severity_indicators", [])),
             None if analysis.get("injury_present") is None else int(bool(analysis["injury_present"])),
             None if analysis.get("ppe_issue") is None else int(bool(analysis["ppe_issue"])),
             float(analysis.get("confidence", 0)),
             json.dumps(analysis.get("reasoning", [])),
             json.dumps(analysis.get("contributions", [])),
             json.dumps(analysis.get("recommendations", {})),
             analysis.get("narrative_source", "rules"), _now()),
        )
        return report_id


def list_reports(limit: int = 200, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT r.*, a.risk_level, a.risk_score, a.summary, a.hazards, a.risk_factors,
                      a.confidence, a.injury_present,
                      u.employee_id, u.name AS worker_name, u.department AS worker_department
               FROM safety_report r
               LEFT JOIN report_analysis a ON a.report_id = r.id
               LEFT JOIN safety_user u ON u.id = r.worker_id
               ORDER BY r.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [_decode(r) for r in rows]


def get_report(report_id: int, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with connect(path) as conn:
        report = conn.execute(
            """SELECT r.*, u.employee_id, u.name AS worker_name, u.department AS worker_department
               FROM safety_report r
               LEFT JOIN safety_user u ON u.id = r.worker_id
               WHERE r.id = ?""",
            (report_id,),
        ).fetchone()
        if report is None:
            return None
        analysis = conn.execute(
            "SELECT * FROM report_analysis WHERE report_id = ?", (report_id,)
        ).fetchone()
        return {"report": _decode(report),
                "analysis": _decode(analysis) if analysis is not None else None}


def all_analyses(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every report joined to its analysis — the input to pattern detection."""
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT r.id, r.report_text, r.source, r.created_at, r.location, r.department,
                      r.equipment, r.incident_type, r.latitude, r.longitude, r.gps_accuracy,
                      r.location_source, r.location_text, r.photo_path, r.photo_source,
                      r.worker_id,
                      a.risk_level, a.risk_score, a.hazards, a.risk_factors,
                      a.missing_controls, a.root_cause, a.severity_indicators, a.confidence,
                      a.injury_present, a.recommendations
               FROM safety_report r JOIN report_analysis a ON a.report_id = r.id
               ORDER BY r.id"""
        ).fetchall()
        return [_decode(r) for r in rows]


def count(path: Optional[Path] = None) -> int:
    with connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM safety_report").fetchone()["n"])


def save_patterns(patterns: Dict[str, Any], report_count: int, path: Optional[Path] = None) -> int:
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO pattern_analysis
               (generated_at, report_count, top_hazards, top_locations, top_departments,
                recurring_causes, emerging_patterns, summary)
               VALUES (?,?,?,?,?,?,?,?)""",
            (_now(), report_count,
             json.dumps(patterns.get("top_hazards", [])),
             json.dumps(patterns.get("high_risk_locations", [])),
             json.dumps(patterns.get("top_departments", [])),
             json.dumps(patterns.get("recurring_causes", [])),
             json.dumps(patterns.get("emerging_patterns", [])),
             patterns.get("trend_summary")),
        )
        return int(cur.lastrowid)


def reset(path: Optional[Path] = None) -> None:
    """Drop and recreate. Used by the seeder and by tests; never called from a request handler."""
    with _LOCK, connect(path) as conn:
        # Children before parents: admin_action and recommendation_feedback carry foreign keys
        # into safety_hotspot and safety_report, and SQLite refuses to drop a referenced table.
        conn.executescript(
            "DROP TABLE IF EXISTS notification_read;"
            "DROP TABLE IF EXISTS safety_notification;"
            "DROP TABLE IF EXISTS worker_route_event;"
            "DROP TABLE IF EXISTS worker_location;"
            "DROP TABLE IF EXISTS admin_action;"
            "DROP TABLE IF EXISTS recommendation_feedback;"
            "DROP TABLE IF EXISTS report_analysis;"
            "DROP TABLE IF EXISTS pattern_analysis;"
            "DROP TABLE IF EXISTS safety_announcement;"
            "DROP TABLE IF EXISTS safety_hotspot;"
            "DROP TABLE IF EXISTS safety_report;"
            "DROP TABLE IF EXISTS safety_user;"
        )
        conn.executescript(SCHEMA)


# --- hotspots and announcements ----------------------------------------------------------------
#
# A hotspot is a REVIEW ARTEFACT, not a fact about the world. It is created as PENDING_REVIEW and
# only a human moves it forward; nothing here publishes anything on its own.

HOTSPOT_STATUSES = (
    "PENDING_REVIEW", "ACKNOWLEDGED", "INVESTIGATING", "PUBLISHED", "RESOLVED", "DISMISSED",
)


def upsert_hotspot(candidate: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Insert a candidate, or refresh an existing one that covers the same reports.

    Matching is on the supporting report-id set: re-running detection after a new report arrives
    must update the existing hotspot rather than stack duplicates beside it. A hotspot a human has
    already acted on keeps its status and its notes — detection never silently reopens a decision.
    """
    key = json.dumps(sorted(i for i in candidate.get("report_ids", []) if i is not None))
    with _LOCK, connect(path) as conn:
        for row in conn.execute("SELECT id, report_ids, status FROM safety_hotspot"):
            try:
                existing = sorted(json.loads(row["report_ids"]))
            except json.JSONDecodeError:
                continue
            # Same cluster, or the new one strictly contains the old — treat as the same place.
            if existing and set(existing) <= set(json.loads(key)):
                conn.execute(
                    """UPDATE safety_hotspot SET latitude=?, longitude=?, report_count=?,
                       primary_hazard=?, related_hazards=?, risk_level=?, first_report_at=?,
                       latest_report_at=?, report_ids=?, locations=?, explanation=?, updated_at=?
                       WHERE id=?""",
                    (candidate["latitude"], candidate["longitude"], candidate["report_count"],
                     candidate["primary_hazard"], json.dumps(candidate["related_hazards"]),
                     candidate["risk_level"], candidate["first_report_at"],
                     candidate["latest_report_at"], key, json.dumps(candidate.get("locations", [])),
                     candidate.get("explanation"), _now(), row["id"]),
                )
                return int(row["id"])
        cur = conn.execute(
            """INSERT INTO safety_hotspot
               (latitude, longitude, radius_meters, report_count, primary_hazard, related_hazards,
                risk_level, first_report_at, latest_report_at, report_ids, locations, explanation,
                flag_source, status, severity, reason, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (candidate["latitude"], candidate["longitude"], candidate["radius_meters"],
             candidate["report_count"], candidate["primary_hazard"],
             json.dumps(candidate["related_hazards"]), candidate["risk_level"],
             candidate["first_report_at"], candidate["latest_report_at"], key,
             json.dumps(candidate.get("locations", [])), candidate.get("explanation"),
             candidate.get("flag_source", "ai_detected"),
             candidate.get("status", "PENDING_REVIEW"),
             candidate.get("severity"), candidate.get("reason"), _now(), _now()),
        )
        return int(cur.lastrowid)


def list_hotspots(status: Optional[str] = None, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    query = "SELECT * FROM safety_hotspot"
    params: tuple = ()
    if status:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY CASE risk_level WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, id DESC"
    with connect(path) as conn:
        return [_decode(r) for r in conn.execute(query, params).fetchall()]


def get_hotspot(hotspot_id: int, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM safety_hotspot WHERE id = ?", (hotspot_id,)).fetchone()
        return _decode(row) if row else None


def set_hotspot_status(hotspot_id: int, status: str, notes: Optional[str] = None,
                       reviewed_by: str = "safety_admin",
                       path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    if status not in HOTSPOT_STATUSES:
        raise ValueError(f"Unknown status {status!r}")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            "UPDATE safety_hotspot SET status=?, review_notes=COALESCE(?, review_notes),"
            " reviewed_by=?, updated_at=? WHERE id=?",
            (status, notes, reviewed_by, _now(), hotspot_id),
        )
        if cur.rowcount == 0:
            return None
    return get_hotspot(hotspot_id, path)


def create_announcement(payload: Dict[str, Any], path: Optional[Path] = None) -> int:
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO safety_announcement
               (hotspot_id, title, message, severity, latitude, longitude, radius_meters,
                location_text, status, restricted, expires_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (payload.get("hotspot_id"), payload["title"], payload["message"],
             payload.get("severity", "HIGH"), payload.get("latitude"), payload.get("longitude"),
             payload.get("radius_meters", 1000), payload.get("location_text"),
             payload.get("status", "PUBLISHED"), int(bool(payload.get("restricted"))),
             payload.get("expires_at"), _now()),
        )
        return int(cur.lastrowid)


def list_announcements(published_only: bool = False, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """`published_only=True` is the worker-facing view. Nothing unpublished may cross that line."""
    query = "SELECT * FROM safety_announcement"
    params: tuple = ()
    if published_only:
        query += " WHERE status = 'PUBLISHED'"
    query += " ORDER BY id DESC"
    with connect(path) as conn:
        return [_decode(r) for r in conn.execute(query, params).fetchall()]


# --- photo evidence -------------------------------------------------------------------------

PHOTO_DIR = Path(os.getenv("ECOSENTINEL_REPORTS_PATH") or DB_PATH.parent / "report_photos")

#: What the worker's camera or file picker may have produced. Anything else is refused rather
#: than stored under a guessed type.
PHOTO_MIME_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}

PHOTO_SOURCES = ("live_camera", "upload")


def save_photo(data: bytes, mime: str, report_id: int) -> str:
    """Write photo bytes to disk and return the path stored on the report row.

    The image is kept as a file rather than a database blob so it can be served statically and so
    the SQLite file stays small enough to copy around during a demo.
    """
    if mime not in PHOTO_MIME_TYPES:
        raise ValueError(f"Unsupported photo type '{mime}'.")
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"report_{report_id}{PHOTO_MIME_TYPES[mime]}"
    (PHOTO_DIR / name).write_bytes(data)
    return f"report_photos/{name}"


def attach_photo(report_id: int, photo_path: str, mime: str, source: str,
                 captured_at: Optional[str] = None, path: Optional[Path] = None) -> None:
    """Record a photo against an already-stored report.

    Separate from `save_report` because the report id has to exist before the file can be named
    after it, and because a failed photo upload must never lose the report text.
    """
    if source not in PHOTO_SOURCES:
        raise ValueError(f"Unsupported photo source '{source}'.")
    with _LOCK, connect(path) as conn:
        conn.execute(
            """UPDATE safety_report
               SET photo_path = ?, photo_mime = ?, photo_source = ?, photo_captured_at = ?
               WHERE id = ?""",
            (photo_path, mime, source, captured_at or _now(), report_id),
        )


# --- admin action tracking ------------------------------------------------------------------

#: Actions an admin can record. Each is something a HUMAN did; the system contacts nobody.
ADMIN_ACTIONS = (
    "contacted_police",
    "contacted_fire_service",
    "contacted_wildlife_authority",
    "contacted_electrical_service",
    "contacted_emergency_medical",
    "internal_team_notified",
    "no_action_required",
)

ADMIN_ACTION_LABEL = {
    "contacted_police": "Contacted Police",
    "contacted_fire_service": "Contacted Fire Service",
    "contacted_wildlife_authority": "Contacted Wildlife Authority",
    "contacted_electrical_service": "Contacted Electrical Service",
    "contacted_emergency_medical": "Contacted Emergency Medical",
    "internal_team_notified": "Internal Team Notified",
    "no_action_required": "No Action Required",
}


def record_admin_action(payload: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Log what the admin did. Returns the new action id."""
    action = payload.get("action_taken")
    if action not in ADMIN_ACTIONS:
        raise ValueError(f"Unknown action '{action}'.")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO admin_action
               (hotspot_id, report_id, action_taken, authority_contacted, admin_notes,
                outcome, follow_up_required, recorded_by, action_timestamp)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (payload.get("hotspot_id"), payload.get("report_id"), action,
             payload.get("authority_contacted"), payload.get("admin_notes"),
             payload.get("outcome"), int(bool(payload.get("follow_up_required"))),
             payload.get("recorded_by", "safety_admin"), _now()),
        )
        return int(cur.lastrowid)


def list_admin_actions(hotspot_id: Optional[int] = None, report_id: Optional[int] = None,
                       path: Optional[Path] = None) -> List[Dict[str, Any]]:
    clauses, params = [], []
    if hotspot_id is not None:
        clauses.append("hotspot_id = ?")
        params.append(hotspot_id)
    if report_id is not None:
        clauses.append("report_id = ?")
        params.append(report_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM admin_action {where} ORDER BY id DESC", tuple(params)
        ).fetchall()
        return [{**_decode(row), "label": ADMIN_ACTION_LABEL.get(row["action_taken"], row["action_taken"])}
                for row in rows]


# --- recommendation feedback ------------------------------------------------------------------

#: Why a recommendation was not useful. Collected for later analysis; one entry never changes
#: the model or the rules on its own.
FEEDBACK_REASONS = (
    "wrong_authority",
    "incorrect_location",
    "incorrect_classification",
    "contact_unavailable",
    "not_applicable",
    "authority_did_not_respond",
    "other",
)


def record_feedback(payload: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Store one admin judgement about a recommendation.

    Deliberately inert: nothing reads this back into the classifier. Retraining from a single
    feedback event would let one mistaken click reshape the rules for everyone.
    """
    reason = payload.get("reason")
    if reason is not None and reason not in FEEDBACK_REASONS:
        raise ValueError(f"Unknown feedback reason '{reason}'.")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO recommendation_feedback
               (hotspot_id, report_id, useful, reason, comment, submitted_by, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (payload.get("hotspot_id"), payload.get("report_id"),
             int(bool(payload.get("useful"))), reason, payload.get("comment"),
             payload.get("submitted_by", "safety_admin"), _now()),
        )
        return int(cur.lastrowid)


def list_feedback(hotspot_id: Optional[int] = None, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    where, params = ("WHERE hotspot_id = ?", (hotspot_id,)) if hotspot_id is not None else ("", ())
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM recommendation_feedback {where} ORDER BY id DESC", params
        ).fetchall()
        return [{**_decode(row), "useful": bool(row["useful"])} for row in rows]


# --- users ------------------------------------------------------------------------------------
#
# Synthetic demo identities. There is NO authentication in this project, so a user row is an
# identity, not a credential: it records who a report belongs to, and nothing about it proves
# who is asking. See `safety/people.py` for what that does and does not guarantee.

USER_ROLES = ("WORKER", "SAFETY_ADMIN")
USER_STATUSES = ("ACTIVE", "INACTIVE")

DEPARTMENTS = (
    "Warehouse", "Manufacturing", "Maintenance", "Electrical",
    "Security", "Logistics", "Operations",
)


def upsert_user(user: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Create or update one user, matched on `employee_id`. Returns the row id.

    Matching on the natural key is what makes seeding idempotent: running it twice updates the
    same rows instead of creating a second set. `created_at` is preserved on update so a re-seed
    does not rewrite history.
    """
    role = user.get("role", "WORKER")
    if role not in USER_ROLES:
        raise ValueError(f"Unknown role {role!r}. Expected one of {list(USER_ROLES)}.")
    employee_id = (user.get("employee_id") or "").strip()
    if not employee_id:
        raise ValueError("employee_id is required.")

    with _LOCK, connect(path) as conn:
        existing = conn.execute(
            "SELECT id FROM safety_user WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        now = _now()
        if existing is not None:
            conn.execute(
                """UPDATE safety_user
                   SET name = ?, email = ?, role = ?, department = ?, status = ?, updated_at = ?
                   WHERE id = ?""",
                (user.get("name"), user.get("email"), role, user.get("department"),
                 user.get("status", "ACTIVE"), now, existing["id"]),
            )
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO safety_user
               (employee_id, name, email, role, department, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (employee_id, user.get("name"), user.get("email"), role, user.get("department"),
             user.get("status", "ACTIVE"), now, now),
        )
        return int(cur.lastrowid)


def get_user(user_id: int, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM safety_user WHERE id = ?", (user_id,)).fetchone()
        return _decode(row) if row is not None else None


def find_user(employee_id: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Look a user up by the id printed on their badge — the handle the API accepts."""
    with connect(path) as conn:
        row = conn.execute(
            "SELECT * FROM safety_user WHERE employee_id = ?", ((employee_id or "").strip(),)
        ).fetchone()
        return _decode(row) if row is not None else None


def list_users(role: Optional[str] = None, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    where, params = ("WHERE role = ?", (role,)) if role else ("", ())
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM safety_user {where} ORDER BY employee_id", params
        ).fetchall()
        return [_decode(row) for row in rows]


def count_users(role: Optional[str] = None, path: Optional[Path] = None) -> int:
    where, params = ("WHERE role = ?", (role,)) if role else ("", ())
    with connect(path) as conn:
        return int(conn.execute(
            f"SELECT COUNT(*) AS n FROM safety_user {where}", params).fetchone()["n"])


# --- worker location events ---------------------------------------------------------------------

def record_location(event: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Store ONE location event the worker deliberately produced.

    Called from exactly two places: an explicit "record my location" request, and a report
    submission that carried a confirmed fix. There is deliberately no scheduler, no batch writer
    and no background hook — continuous tracking is not something this table can be made to do
    by accident, because nothing calls it on a timer.
    """
    if event.get("latitude") is None or event.get("longitude") is None:
        raise ValueError("A location event needs both latitude and longitude.")
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO worker_location
               (worker_id, latitude, longitude, gps_accuracy, location_source, report_id, captured_at)
               VALUES (?,?,?,?,?,?,?)""",
            (event["worker_id"], float(event["latitude"]), float(event["longitude"]),
             event.get("gps_accuracy"), event.get("location_source", "unknown"),
             event.get("report_id"), event.get("captured_at") or _now()),
        )
        return int(cur.lastrowid)


def location_history(worker_id: int, limit: int = 100,
                     path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """One worker's own location events, newest first. Never another worker's."""
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT * FROM worker_location WHERE worker_id = ?
               ORDER BY captured_at DESC, id DESC LIMIT ?""",
            (worker_id, limit),
        ).fetchall()
        return [_decode(row) for row in rows]


def count_locations(path: Optional[Path] = None) -> int:
    with connect(path) as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM worker_location").fetchone()["n"])


# --- a worker's own report history ---------------------------------------------------------------

def reports_for_worker(worker_id: int, limit: int = 200,
                       path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every report this worker filed, newest first.

    The WHERE clause is the privacy boundary: it is applied in SQL rather than by filtering a
    wider result set in Python, so there is no intermediate list holding other workers' rows that
    a later change could accidentally return.
    """
    with connect(path) as conn:
        rows = conn.execute(
            """SELECT r.*, a.risk_level, a.risk_score, a.summary, a.hazards, a.risk_factors
               FROM safety_report r LEFT JOIN report_analysis a ON a.report_id = r.id
               WHERE r.worker_id = ?
               ORDER BY r.id DESC LIMIT ?""",
            (worker_id, limit),
        ).fetchall()
        return [_decode(row) for row in rows]


def report_for_worker(report_id: int, worker_id: int,
                      path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """One report, but only if this worker filed it. Returns None otherwise.

    Deliberately indistinguishable from "no such report": telling a worker that a report exists
    but belongs to someone else is itself a disclosure.
    """
    with connect(path) as conn:
        row = conn.execute(
            """SELECT r.*, a.risk_level, a.risk_score, a.summary, a.hazards, a.risk_factors, a.reasoning
               FROM safety_report r LEFT JOIN report_analysis a ON a.report_id = r.id
               WHERE r.id = ? AND r.worker_id = ?""",
            (report_id, worker_id),
        ).fetchone()
        return _decode(row) if row is not None else None


def attach_report_worker(report_id: int, worker_id: int, path: Optional[Path] = None) -> None:
    with _LOCK, connect(path) as conn:
        conn.execute("UPDATE safety_report SET worker_id = ? WHERE id = ?", (worker_id, report_id))


# --- worker route events --------------------------------------------------------------------
#
# One row per explicit route request. See safety/routes_history.py for what is stored and why the
# geometry is kept rather than recomputed.

_ROUTE_JSON_FIELDS = ("original_route_geometry", "selected_route_geometry", "alerts_near_route")


def record_route_event(event: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Persist one route event. Returns the new id."""
    columns = (
        "worker_id", "employee_id", "created_at",
        "start_latitude", "start_longitude", "destination_latitude", "destination_longitude",
        "original_distance_meters", "original_route_geometry",
        "selected_distance_meters", "selected_route_geometry",
        "route_adjusted_for_safety", "safe_alternative_found", "selected_reason",
        "alerts_near_route",
        "affecting_alert_id", "affecting_alert_title", "affecting_alert_severity",
        "affecting_alert_latitude", "affecting_alert_longitude",
        "affecting_alert_radius_meters", "minimum_distance_to_alert_meters",
        "detour_distance_meters", "detour_ratio", "classification", "safety_radius_meters",
    )
    values = []
    for column in columns:
        if column == "created_at":
            values.append(event.get("created_at") or _now())
        elif column in _ROUTE_JSON_FIELDS:
            values.append(json.dumps(event.get(column) or []))
        elif column == "route_adjusted_for_safety":
            values.append(int(bool(event.get(column))))
        elif column == "safe_alternative_found":
            found = event.get(column)
            values.append(None if found is None else int(bool(found)))
        else:
            values.append(event.get(column))

    placeholders = ",".join("?" * len(columns))
    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            f"INSERT INTO worker_route_event ({','.join(columns)}) VALUES ({placeholders})",
            tuple(values),
        )
        return int(cur.lastrowid)


def _decode_route(row: sqlite3.Row) -> Dict[str, Any]:
    out = _decode(row)
    out["route_adjusted_for_safety"] = bool(out.get("route_adjusted_for_safety"))
    found = out.get("safe_alternative_found")
    out["safe_alternative_found"] = None if found is None else bool(found)
    return out


def list_route_events(
    employee_id: Optional[str] = None,
    classification: Optional[str] = None,
    alert_id: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 200,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Route events, newest first, filtered in SQL.

    `employee_id` is the privacy filter for the worker-facing endpoint; applying it here rather
    than over a wider result set means no intermediate list ever holds another worker's rows.
    """
    clauses, params = [], []
    if employee_id:
        clauses.append("e.employee_id = ?")
        params.append(employee_id)
    if classification:
        clauses.append("e.classification = ?")
        params.append(classification)
    if alert_id is not None:
        clauses.append("e.affecting_alert_id = ?")
        params.append(alert_id)
    if since:
        clauses.append("e.created_at >= ?")
        params.append(since)
    if until:
        clauses.append("e.created_at <= ?")
        params.append(until)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)

    with connect(path) as conn:
        rows = conn.execute(
            f"""SELECT e.*, u.name AS worker_name, u.department AS worker_department
                FROM worker_route_event e
                LEFT JOIN safety_user u ON u.id = e.worker_id
                {where} ORDER BY e.id DESC LIMIT ?""",
            tuple(params),
        ).fetchall()
        return [_decode_route(row) for row in rows]


def get_route_event(event_id: int, employee_id: Optional[str] = None,
                    path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """One route event. With `employee_id`, only if it belongs to that worker.

    A row belonging to someone else returns None, indistinguishable from one that does not
    exist — saying "it exists but is not yours" is itself a disclosure.
    """
    clause, params = "e.id = ?", [event_id]
    if employee_id:
        clause += " AND e.employee_id = ?"
        params.append(employee_id)
    with connect(path) as conn:
        row = conn.execute(
            f"""SELECT e.*, u.name AS worker_name, u.department AS worker_department
                FROM worker_route_event e
                LEFT JOIN safety_user u ON u.id = e.worker_id
                WHERE {clause}""",
            tuple(params),
        ).fetchone()
        return _decode_route(row) if row is not None else None


def count_route_events(path: Optional[Path] = None) -> int:
    with connect(path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) AS n FROM worker_route_event").fetchone()["n"])


# --- notifications -----------------------------------------------------------------------------
#
# Two directions, one table. A notification is addressed to a ROLE (broadcast) or to one
# employee (targeted), and `notifications_for` turns that into a single query — which is what
# keeps "who may read this" from being a rule duplicated across serialisers.

NOTIFICATION_TYPES = (
    "REPORT_SUBMITTED",     # worker -> admin, raised automatically when a report is filed
    "ANNOUNCEMENT",         # admin -> workers, broadcast
    "DIRECT_MESSAGE",       # admin -> one worker
    "SAFETY_ALERT",         # admin -> workers, tied to a published alert
    "WORKER_MESSAGE",       # worker -> the safety admin, or worker -> a named colleague
)

#: Message types whose SENDER is shown to the recipient. A message nobody can attribute is worse
#: than one they can: the reader cannot judge it, reply to it, or report it as misuse. This is
#: deliberately narrow — it covers messages a person chose to send, never the automatic
#: REPORT_SUBMITTED notification, which carries another worker's report evidence.
ATTRIBUTED_TYPES = ("WORKER_MESSAGE", "DIRECT_MESSAGE", "ANNOUNCEMENT")


def create_notification(payload: Dict[str, Any], path: Optional[Path] = None) -> int:
    """Store one notification. Returns its id."""
    kind = payload.get("notification_type")
    if kind not in NOTIFICATION_TYPES:
        raise ValueError(f"Unknown notification_type {kind!r}.")
    role = payload.get("recipient_role")
    if role not in USER_ROLES:
        raise ValueError(f"Unknown recipient_role {role!r}.")

    with _LOCK, connect(path) as conn:
        cur = conn.execute(
            """INSERT INTO safety_notification
               (recipient_role, recipient_employee_id, sender_employee_id, notification_type,
                title, message, report_id, latitude, longitude, gps_accuracy, location_source,
                severity, radius_meters, expires_at, metadata, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (role, payload.get("recipient_employee_id"), payload.get("sender_employee_id"),
             kind, payload["title"], payload["message"], payload.get("report_id"),
             payload.get("latitude"), payload.get("longitude"), payload.get("gps_accuracy"),
             payload.get("location_source"), payload.get("severity"),
             payload.get("radius_meters"), payload.get("expires_at"),
             json.dumps(payload.get("metadata") or {}), _now()),
        )
        return int(cur.lastrowid)


def notifications_for(role: str, employee_id: Optional[str] = None, limit: int = 100,
                      unread_only: bool = False,
                      path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Notifications this recipient may read, newest first.

    The WHERE clause IS the privacy boundary: a row is returned when it is addressed to this
    role as a broadcast, or to this employee by name. A message for another worker cannot appear
    in the result set at all, so no later filtering step can forget to remove it.
    """
    clauses = ["n.recipient_role = ?"]
    params: List[Any] = [role]
    if employee_id:
        clauses.append("(n.recipient_employee_id IS NULL OR n.recipient_employee_id = ?)")
        params.append(employee_id)
    else:
        clauses.append("n.recipient_employee_id IS NULL")

    where = " AND ".join(clauses)
    reader = employee_id or ""
    params = [reader] + params + [limit]

    with connect(path) as conn:
        rows = conn.execute(
            f"""SELECT n.*, r.read_at AS receipt_read_at, u.name AS sender_name
                FROM safety_notification n
                LEFT JOIN notification_read r
                       ON r.notification_id = n.id AND r.employee_id = ?
                LEFT JOIN safety_user u ON u.employee_id = n.sender_employee_id
                WHERE {where}
                ORDER BY n.id DESC LIMIT ?""",
            tuple(params),
        ).fetchall()

    out: List[Dict[str, Any]] = []
    for row in rows:
        item = _decode(row)
        # A targeted message carries its own read_at; a broadcast's is per reader.
        item["read"] = bool(item.get("read_at") or item.get("receipt_read_at"))
        item["read_at"] = item.get("read_at") or item.get("receipt_read_at")
        item.pop("receipt_read_at", None)
        if unread_only and item["read"]:
            continue
        out.append(item)
    return out


def unread_count(role: str, employee_id: Optional[str] = None,
                 path: Optional[Path] = None) -> int:
    return len(notifications_for(role, employee_id, 500, unread_only=True, path=path))


def mark_notification_read(notification_id: int, role: str, employee_id: Optional[str] = None,
                           path: Optional[Path] = None) -> bool:
    """Mark one notification read FOR THIS READER. Returns False when it is not theirs to read."""
    visible = {n["id"] for n in notifications_for(role, employee_id, 500, path=path)}
    if notification_id not in visible:
        return False

    with _LOCK, connect(path) as conn:
        row = conn.execute(
            "SELECT recipient_employee_id FROM safety_notification WHERE id = ?",
            (notification_id,),
        ).fetchone()
        if row is None:
            return False
        if row["recipient_employee_id"]:
            conn.execute("UPDATE safety_notification SET read_at = ? WHERE id = ?",
                         (_now(), notification_id))
        else:
            # A broadcast: record a receipt rather than marking it read for everyone.
            conn.execute(
                """INSERT OR REPLACE INTO notification_read (notification_id, employee_id, read_at)
                   VALUES (?,?,?)""",
                (notification_id, employee_id or role, _now()),
            )
    return True


def mark_all_notifications_read(role: str, employee_id: Optional[str] = None,
                                path: Optional[Path] = None) -> int:
    marked = 0
    for item in notifications_for(role, employee_id, 500, unread_only=True, path=path):
        if mark_notification_read(item["id"], role, employee_id, path=path):
            marked += 1
    return marked


def count_notifications(path: Optional[Path] = None) -> int:
    with connect(path) as conn:
        return int(conn.execute(
            "SELECT COUNT(*) AS n FROM safety_notification").fetchone()["n"])
