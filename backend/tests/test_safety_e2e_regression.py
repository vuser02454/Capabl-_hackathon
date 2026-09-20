"""
Comprehensive E2E Regression Suite for C3 Safety Intelligence.

Validates:
1. User Model & Idempotency: Exactly 1 Admin (ADMIN001) + 15 Workers (EMP001-EMP015).
2. Worker Identity Verification Endpoint: GET /api/worker/me?employee_id=...
3. Server-side Worker Privacy & Photo Isolation:
   - Worker A cannot see Worker B's reports or photo.
4. Three-Level Intelligence & Precursor Detection:
   - Level 1: Single incident -> no pattern, no route change.
   - Level 2: Two related incidents -> caution, precursor detection, NO route change.
   - Level 3: Three+ related incidents -> Candidate hotspot (PENDING_REVIEW), NO route change.
   - Admin Publish -> PUBLISHED alert -> Activates route safety avoidance.
5. India Location Validation:
   - verify-location endpoint accepts India coords, rejects international coordinates.
6. Routing Avoidance Metrics:
   - Case 1: KR Puram -> Whitefield baseline (clean shortest route ~8335m).
   - Case 2: Corridor midpoint 500 m alert avoidance (geometry differs, detour < 1.6).
"""
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.safety import store, people, caution, routing, roles_api


@pytest.fixture(autouse=True)
def setup_seed():
    store.init()
    people.seed_demo_data()


@pytest.mark.anyio
async def test_user_model_and_idempotent_seeding():
    """Validates exactly 1 Admin (ADMIN001) and 15 Workers (EMP001-EMP015), and seed idempotency."""
    users = store.list_users()
    admins = [u for u in users if u["role"] == "SAFETY_ADMIN"]
    workers = [u for u in users if u["role"] == "WORKER"]

    assert len(admins) == 1, f"Expected exactly 1 admin, found {len(admins)}: {[a['employee_id'] for a in admins]}"
    assert admins[0]["employee_id"] == "ADMIN001"
    assert admins[0]["name"] == "Safety Admin"
    assert admins[0]["email"] == "admin@example.com"

    assert len(workers) == 15, f"Expected 15 workers, found {len(workers)}"
    worker_ids = sorted([w["employee_id"] for w in workers])
    expected_ids = [f"EMP{i:03d}" for i in range(1, 16)]
    assert worker_ids == expected_ids

    # Verify idempotency
    res = people.seed_demo_data()
    assert res["users"]["created"] == 0
    assert res["reports"]["reports_created"] == 0


@pytest.mark.anyio
async def test_worker_identity_endpoint():
    """Validates worker identity lookup via GET /api/worker/me."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Valid worker
        res = await client.get("/api/worker/me?employee_id=EMP001")
        assert res.status_code == 200
        data = res.json()
        assert data["worker"]["employeeId"] == "EMP001"
        assert data["worker"]["role"] == "WORKER"
        assert "Worker 001" in data["worker"]["name"]

        # Invalid worker employee_id
        res_invalid = await client.get("/api/worker/me?employee_id=INVALID999")
        assert res_invalid.status_code == 404

        # Admin employee_id passed to worker endpoint is rejected
        res_admin = await client.get("/api/worker/me?employee_id=ADMIN001")
        assert res_admin.status_code == 403


@pytest.mark.anyio
async def test_worker_privacy_and_photo_isolation():
    """Validates server-side isolation of reports and photos between workers."""
    # Get IDs for EMP001 and EMP002
    u1 = store.find_user("EMP001")
    u2 = store.find_user("EMP002")
    assert u1 is not None and u2 is not None

    # Insert distinct reports for worker 1 and worker 2
    r1_id = store.save_report(
        {"report_text": "Oil leak bay 1", "source": "test", "latitude": 12.9716, "longitude": 77.5946,
         "worker_id": u1["id"], "photo_path": "backend/data/report_photos/test_p1.jpg"},
        {"risk_level": "LOW", "risk_score": 20, "hazards": ["spill"], "summary": "Oil leak"},
    )
    r2_id = store.save_report(
        {"report_text": "Exposed cable line 2", "source": "test", "latitude": 12.9720, "longitude": 77.5950,
         "worker_id": u2["id"]},
        {"risk_level": "MEDIUM", "risk_score": 50, "hazards": ["electrical"], "summary": "Exposed cable"},
    )

    # 1. SQL level isolation via store.reports_for_worker
    w1_reports = store.reports_for_worker(u1["id"])
    w1_ids = [r["id"] for r in w1_reports]
    assert r1_id in w1_ids
    assert r2_id not in w1_ids

    w2_reports = store.reports_for_worker(u2["id"])
    w2_ids = [r["id"] for r in w2_reports]
    assert r2_id in w2_ids
    assert r1_id not in w2_ids

    # 2. HTTP endpoint report isolation
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Worker 2 trying to query Worker 1's report detail
        res = await client.get(f"/api/worker/reports/{r1_id}?employee_id=EMP002")
        assert res.status_code == 404, "Worker 2 must receive 404 when querying Worker 1's report"

        # Worker 1 querying their own report
        res_own = await client.get(f"/api/worker/reports/{r1_id}?employee_id=EMP001")
        assert res_own.status_code == 200
        assert res_own.json()["report"]["reportText"] == "Oil leak bay 1"

        # Photo privacy isolation: Worker 2 attempting to view Worker 1's photo
        res_photo_intruder = await client.get(f"/api/worker/reports/{r1_id}/photo?employee_id=EMP002")
        assert res_photo_intruder.status_code == 404

        # Requesting photo without worker employee_id
        res_no_auth = await client.get(f"/api/worker/reports/{r1_id}/photo")
        assert res_no_auth.status_code == 422


@pytest.mark.anyio
async def test_three_level_intelligence_and_precursor():
    """Validates Level 1, Level 2 (with precursor note), Level 3 hotspot, and publish routing gate."""
    # Level 1: Single incident
    corpus_single = [{"id": 1, "hazards": ["spill"], "latitude": 12.9716, "longitude": 77.5946, "report_text": "Spill"}]
    p1 = caution.pattern_status(corpus_single, corpus_single[0])
    assert p1["level"] == caution.PATTERN_NONE
    assert "No recurring pattern" in p1["summary"]

    # Level 2: Two related incidents with near-miss precursor detection
    near_miss_reports = [
        {"id": 101, "hazards": ["near miss", "forklift"], "latitude": 12.9710, "longitude": 77.5940, "report_text": "Near miss: forklift almost reversed into pedestrian"},
        {"id": 102, "hazards": ["near miss", "pedestrian"], "latitude": 12.9712, "longitude": 77.5942, "report_text": "Near miss: close call with pedestrian walking near bay"},
    ]
    p2 = caution.pattern_status(near_miss_reports, near_miss_reports[1])
    assert p2["level"] == caution.PATTERN_EMERGING
    assert p2["precursor"] is not None
    assert "Possible incident precursor" in p2["precursor"]

    # Candidate hotspot (status PENDING_REVIEW) does NOT affect routing
    # Midpoint of KR Puram -> Whitefield
    midpoint_lat, midpoint_lon = 13.0043943, 77.728249

    # Ensure clean state before testing
    with store.connect() as conn:
        conn.execute("DELETE FROM safety_announcement WHERE latitude = ? AND longitude = ?", (midpoint_lat, midpoint_lon))
        conn.commit()

    hotspot_id = store.upsert_hotspot({
        "latitude": midpoint_lat,
        "longitude": midpoint_lon,
        "radius_meters": 500,
        "primary_hazard": "Oil spill corridor",
        "related_hazards": ["spill", "slip"],
        "risk_level": "HIGH",
        "first_report_at": "2026-09-01T00:00:00Z",
        "latest_report_at": "2026-09-19T00:00:00Z",
        "report_ids": [101, 102, 103],
        "status": "PENDING_REVIEW",
        "severity": "HIGH",
        "explanation": "Test candidate hotspot under review",
        "report_count": 3,
        "locations": ["Corridor Midpoint"],
    })

    kr_puram = {"latitude": 13.007516, "longitude": 77.695935}
    whitefield = {"latitude": 12.9957428, "longitude": 77.7579489}
    route_payload = {"start": kr_puram, "destination": whitefield}

    ann_id = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Route check: Candidate hotspot MUST NOT alter route
            res_pending = (await client.post("/api/worker/route", json=route_payload)).json()
            assert res_pending["found"] is True
            assert res_pending["selected"] == "shortest"
            assert res_pending["adjustedForSafety"] is False
            assert res_pending["blockingAlerts"] == []

            # Admin publishes alert
            ann_id = store.create_announcement({
                "title": "Safety Alert — Oil spill corridor",
                "message": "Hazard on route. Avoid area.",
                "severity": "HIGH",
                "hotspot_id": hotspot_id,
                "latitude": midpoint_lat,
                "longitude": midpoint_lon,
                "radius_meters": 500,
                "location_text": "Corridor Midpoint",
                "status": "PUBLISHED",
            })
            store.set_hotspot_status(hotspot_id, "PUBLISHED")

            # Route check with PUBLISHED alert: Avoids alert area
            res_published = (await client.post("/api/worker/route", json=route_payload)).json()
            assert res_published["found"] is True
            assert res_published["selected"] == "alternative"
            assert res_published["adjustedForSafety"] is True
            assert res_published["safeAlternativeFound"] is True
            assert any(a["id"] == ann_id for a in res_published["blockingAlerts"])
    finally:
        with store.connect() as conn:
            if ann_id:
                conn.execute("DELETE FROM safety_announcement WHERE id = ?", (ann_id,))
            conn.execute("DELETE FROM safety_hotspot WHERE id = ?", (hotspot_id,))
            conn.commit()


@pytest.mark.anyio
async def test_india_location_validation():
    """Validates that India coordinates are accepted while international points are rejected."""
    assert roles_api._plausibly_india(12.9716, 77.5946) is True  # Bengaluru
    assert roles_api._plausibly_india(19.0760, 72.8777) is True  # Mumbai
    assert roles_api._plausibly_india(28.6139, 77.2090) is True  # Delhi

    # International coordinates outside bounding box
    assert roles_api._plausibly_india(51.5074, -0.1278) is False  # London
    assert roles_api._plausibly_india(40.7128, -74.0060) is False  # New York
    assert roles_api._plausibly_india(1.3521, 103.8198) is False  # Singapore

    # Test via API
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Rejected coordinate
        res_ny = await client.post("/api/worker/verify-location", json={"latitude": 40.7128, "longitude": -74.0060})
        assert res_ny.status_code == 200
        body_ny = res_ny.json()
        assert body_ny["accepted"] is False
        assert body_ny["reason"] == roles_api.INDIA_ONLY_MESSAGE

        # Inside bounding box
        res_blr = await client.post("/api/worker/verify-location", json={"latitude": 12.9716, "longitude": 77.5946})
        assert res_blr.status_code == 200
        body_blr = res_blr.json()
        assert body_blr["accepted"] is True


@pytest.mark.anyio
async def test_case_1_and_case_2_routing_metrics():
    """
    Validates Case 1 (KR Puram -> Whitefield Baseline) and Case 2 (Midpoint Alert Avoidance).
    Exact coordinates:
      Start: (13.007516, 77.695935)
      Dest:  (12.9957428, 77.7579489)
      Midpoint Alert: (13.0043943, 77.728249)
    """
    kr_puram = (13.007516, 77.695935)
    whitefield = (12.9957428, 77.7579489)
    midpoint = (13.0043943, 77.728249)

    service = routing.service()

    # --- CASE 1: Baseline Route (Zero alerts in range) ---
    case1 = service.route(kr_puram, whitefield, alerts=[])
    assert case1["found"] is True
    assert case1["selected"] == "shortest"
    assert case1["adjusted_for_safety"] is False
    assert case1["alerts_near_route"] == []
    assert case1["blocking_alerts"] == []
    assert case1["alternatives_evaluated"] == 0

    base_dist = case1["distance_meters"]
    base_points = case1["route"]
    assert 8000 < base_dist < 9000, f"Expected baseline ~8335 m, got {base_dist}"

    # --- CASE 2: 500m Published Alert on Corridor Midpoint ---
    midpoint_alert = {
        "id": 9999,
        "title": "Midpoint Corridor Hazard",
        "latitude": midpoint[0],
        "longitude": midpoint[1],
        "radius_meters": 500,
    }

    case2 = service.route(kr_puram, whitefield, alerts=[midpoint_alert], safety_radius=500)
    assert case2["found"] is True
    assert case2["selected"] == "alternative"
    assert case2["adjusted_for_safety"] is True
    assert case2["safe_alternative_found"] is True
    assert any(a["id"] == 9999 for a in case2["blocking_alerts"])
    assert len(case2["alerts_near_route"]) == 0, "Selected alternative route must have 0 alerts in range"

    # Geometry check: Alternative path points must differ from baseline path
    alt_points = case2["route"]
    assert alt_points != base_points, "Alternative route geometry must differ from baseline"

    # Detour ratio check
    alt_dist = case2["distance_meters"]
    detour_ratio = alt_dist / base_dist
    assert detour_ratio > 1.0, f"Alternative route ({alt_dist}m) must be longer than baseline ({base_dist}m)"
    assert detour_ratio <= routing.MAX_ROUTE_DETOUR_RATIO, (
        f"Detour ratio {detour_ratio:.3f} exceeds MAX_ROUTE_DETOUR_RATIO {routing.MAX_ROUTE_DETOUR_RATIO}"
    )
