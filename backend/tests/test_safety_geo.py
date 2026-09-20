"""Geographic hotspot detection, human review, and the worker/admin privacy boundary.

The 1 km rule is tested from both sides: a cluster that should form, and four that should not.
Getting the negatives right matters more than the positive — a detector that flags everything is
indistinguishable from one that flags the right thing, until someone acts on it.

Privacy is tested as a boundary, not a filter: the worker payload is asserted to LACK the fields
rather than the admin payload asserted to have them, because a leak is an extra key appearing, not
an expected key going missing.
"""

import pytest
from fastapi.testclient import TestClient

from safety import geo, llm, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "geo.db")
    store.init()
    return tmp_path


def _report(rid, lat, lon, hazards, level="HIGH", created="2026-09-20T10:00:00Z", location="Loading Bay"):
    return {"id": rid, "latitude": lat, "longitude": lon, "hazards": hazards,
            "risk_level": level, "created_at": created, "location": location}


# --- distance ---------------------------------------------------------------------------------

def test_haversine_matches_known_distance():
    # 0.01 degrees of latitude is ~1111 m anywhere on the globe.
    metres = geo.haversine_meters(12.9716, 77.5946, 12.9816, 77.5946)
    assert 1100 < metres < 1120


def test_haversine_is_zero_for_the_same_point():
    assert geo.haversine_meters(*BENGALURU, *BENGALURU) == pytest.approx(0, abs=1e-6)


def test_haversine_is_symmetric():
    a = geo.haversine_meters(12.9716, 77.5946, 12.9800, 77.6000)
    b = geo.haversine_meters(12.9800, 77.6000, 12.9716, 77.5946)
    assert a == pytest.approx(b)


# --- the 1 km rule ------------------------------------------------------------------------------

def test_the_configured_radius_is_exactly_one_kilometre():
    assert geo.HOTSPOT_RADIUS_METERS == 1000
    assert geo.HOTSPOT_MIN_REPORTS == 3


def test_three_related_reports_within_one_km_create_a_candidate():
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9720, 77.5950, ["Vehicle / forklift", "Oil spill"]),
        _report(3, 12.9725, 77.5955, ["Slip / trip / fall"]),
    ]
    hotspots = geo.detect_hotspots(reports)
    assert len(hotspots) == 1
    assert hotspots[0]["report_count"] == 3
    assert hotspots[0]["radius_meters"] == 1000
    assert hotspots[0]["primary_hazard"] == "Oil spill / slip hazard"
    assert sorted(hotspots[0]["report_ids"]) == [1, 2, 3]


def test_two_related_reports_within_one_km_do_not():
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9720, 77.5950, ["Oil spill"]),
    ]
    assert geo.detect_hotspots(reports) == []


def test_three_unrelated_reports_within_one_km_do_not_become_one_hotspot():
    """Proximity alone must not merge an oil spill, a noise complaint and a blocked exit."""
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9717, 77.5947, ["Noise exposure"]),
        _report(3, 12.9718, 77.5948, ["Blocked egress"]),
    ]
    assert geo.detect_hotspots(reports) == []


def test_related_reports_beyond_one_km_are_not_grouped():
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9720, 77.5950, ["Oil spill"]),
        _report(3, 13.0500, 77.5946, ["Oil spill"]),  # ~8.7 km away
    ]
    assert geo.detect_hotspots(reports) == []


def test_a_report_without_coordinates_is_ignored_not_crashed_on():
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        {"id": 2, "latitude": None, "longitude": None, "hazards": ["Oil spill"],
         "risk_level": "HIGH", "created_at": "t"},
        _report(3, 12.9720, 77.5950, ["Oil spill"]),
    ]
    assert geo.detect_hotspots(reports) == []  # only two locatable reports remain


def test_clustering_is_not_anchored_to_the_first_report():
    """A chain A-B-C where A and C are >1 km apart still forms one cluster through B."""
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9780, 77.5946, ["Oil spill"]),   # ~710 m from #1
        _report(3, 12.9845, 77.5946, ["Oil spill"]),   # ~720 m from #2, ~1.43 km from #1
    ]
    hotspots = geo.detect_hotspots(reports)
    assert len(hotspots) == 1 and hotspots[0]["report_count"] == 3


def test_hotspot_records_its_own_spread_separately_from_the_rule_radius():
    reports = [_report(i, 12.9716 + i * 0.001, 77.5946, ["Oil spill"]) for i in range(3)]
    hotspot = geo.detect_hotspots(reports)[0]
    assert hotspot["radius_meters"] == 1000
    assert hotspot["max_spread_meters"] < 200  # the actual cluster is far tighter than the rule


def test_risk_level_of_a_hotspot_is_the_worst_of_its_members():
    reports = [
        _report(1, 12.9716, 77.5946, ["Oil spill"], level="LOW"),
        _report(2, 12.9718, 77.5948, ["Oil spill"], level="HIGH"),
        _report(3, 12.9720, 77.5950, ["Oil spill"], level="MEDIUM"),
    ]
    assert geo.detect_hotspots(reports)[0]["risk_level"] == "HIGH"


# --- persistence and review ---------------------------------------------------------------------

def test_hotspot_persists_and_starts_pending_review(db):
    candidate = geo.detect_hotspots([
        _report(1, 12.9716, 77.5946, ["Oil spill"]),
        _report(2, 12.9718, 77.5948, ["Oil spill"]),
        _report(3, 12.9720, 77.5950, ["Slip / trip / fall"]),
    ])[0]
    hotspot_id = store.upsert_hotspot(candidate)
    stored = store.get_hotspot(hotspot_id)
    assert stored["status"] == "PENDING_REVIEW"
    assert stored["flag_source"] == "ai_detected"
    assert stored["radius_meters"] == 1000


def test_rerunning_detection_updates_rather_than_duplicates(db):
    reports = [_report(i, 12.9716 + i * 0.0005, 77.5946, ["Oil spill"]) for i in range(1, 4)]
    candidate = geo.detect_hotspots(reports)[0]
    first = store.upsert_hotspot(candidate)
    second = store.upsert_hotspot(candidate)
    assert first == second
    assert len(store.list_hotspots()) == 1


@pytest.mark.parametrize("status", ["ACKNOWLEDGED", "INVESTIGATING", "PUBLISHED", "RESOLVED", "DISMISSED"])
def test_admin_can_move_a_hotspot_through_every_review_state(db, status):
    candidate = geo.detect_hotspots([_report(i, 12.9716 + i * 0.0005, 77.5946, ["Oil spill"])
                                     for i in range(1, 4)])[0]
    hotspot_id = store.upsert_hotspot(candidate)
    updated = store.set_hotspot_status(hotspot_id, status, notes="reviewed")
    assert updated["status"] == status
    assert updated["review_notes"] == "reviewed"


def test_an_unknown_status_is_rejected(db):
    candidate = geo.detect_hotspots([_report(i, 12.9716 + i * 0.0005, 77.5946, ["Oil spill"])
                                     for i in range(1, 4)])[0]
    hotspot_id = store.upsert_hotspot(candidate)
    with pytest.raises(ValueError):
        store.set_hotspot_status(hotspot_id, "DEFINITELY_DANGEROUS")


# --- the API, including the privacy boundary ------------------------------------------------------

def _client():
    import main

    return TestClient(main.app)


def test_worker_report_accepts_and_stores_a_gps_fix(db):
    response = _client().post("/api/worker/reports", json={
        "report_text": "Oil spill near the loading bay, nearly slipped.",
        "latitude": 12.9716, "longitude": 77.5946,
        "gps_accuracy": 18.0, "location_source": "browser_gps",
    })
    assert response.status_code == 200
    body = response.json()
    assert body["location"]["gpsAccuracy"] == 18.0
    assert body["location"]["locationSource"] == "browser_gps"
    assert body["analysis"]["riskLevel"] in ("LOW", "MEDIUM", "HIGH")


def test_manual_map_location_is_accepted(db):
    response = _client().post("/api/worker/reports", json={
        "report_text": "Blocked fire exit in the packaging hall.",
        "latitude": 12.97, "longitude": 77.59, "location_source": "manual_map",
    })
    assert response.status_code == 200
    assert response.json()["location"]["locationSource"] == "manual_map"


def test_a_report_without_any_location_still_succeeds(db):
    """GPS denial must never block a safety report."""
    response = _client().post("/api/worker/reports",
                              json={"report_text": "Ladder with a damaged stile in the workshop."})
    assert response.status_code == 200
    assert response.json()["location"]["latitude"] is None


def test_half_a_coordinate_pair_is_rejected(db):
    response = _client().post("/api/worker/reports",
                              json={"report_text": "Oil spill.", "latitude": 12.97})
    assert response.status_code == 422


def test_an_unknown_location_source_falls_back_to_unknown(db):
    response = _client().post("/api/worker/reports", json={
        "report_text": "Oil spill near loading bay.",
        "latitude": 12.97, "longitude": 77.59, "location_source": "satellite_laser",
    })
    assert response.json()["location"]["locationSource"] == "unknown"


def test_workers_never_see_unpublished_hotspots(db):
    client = _client()
    for index in range(3):
        client.post("/api/worker/reports", json={
            "report_text": "Oil spill near the loading bay, floor is slippery.",
            "latitude": 12.9716 + index * 0.0005, "longitude": 77.5946,
            "location_source": "browser_gps",
        })
    assert client.get("/api/admin/hotspots").json()["count"] >= 1
    # ...but nothing has been published, so the worker sees nothing.
    assert client.get("/api/worker/alerts").json()["alerts"] == []
    assert client.get("/api/worker/map").json()["alerts"] == []


def test_a_published_alert_reaches_workers_without_leaking_internals(db):
    client = _client()
    client.post("/api/admin/announcements", json={
        "title": "Safety Alert — Loading Bay",
        "message": "Oil-spill/slip hazard reported. Avoid the marked area.",
        "latitude": 12.9716, "longitude": 77.5946, "severity": "HIGH",
    })
    alerts = client.get("/api/worker/alerts").json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["title"].startswith("Safety Alert")
    assert alert["issuedBy"] == "Safety Team"
    # The privacy boundary: none of these may ever appear in a worker payload.
    for leaked in ("reportIds", "report_ids", "reviewNotes", "review_notes",
                   "reportedBy", "reporter", "supportingReports"):
        assert leaked not in alert


def test_admin_sees_supporting_reports_that_workers_do_not(db):
    client = _client()
    for index in range(3):
        client.post("/api/worker/reports", json={
            "report_text": "Forklift leaking oil by the loading bay, slip risk.",
            "latitude": 12.9716 + index * 0.0005, "longitude": 77.5946,
            "location_source": "browser_gps",
        })
    hotspots = client.get("/api/admin/hotspots").json()["hotspots"]
    assert hotspots
    detail = client.get(f"/api/admin/hotspots/{hotspots[0]['id']}").json()
    assert detail["supportingReports"]
    assert detail["hotspot"]["isAiDetected"] is True
    assert detail["rule"]["radiusMeters"] == 1000


@pytest.mark.parametrize("action,expected", [
    ("acknowledge", "ACKNOWLEDGED"), ("investigate", "INVESTIGATING"),
    ("publish", "PUBLISHED"), ("resolve", "RESOLVED"), ("dismiss", "DISMISSED"),
])
def test_every_admin_review_action_is_reachable_over_http(db, action, expected):
    client = _client()
    for index in range(3):
        client.post("/api/worker/reports", json={
            "report_text": "Oil on the floor near the loading bay.",
            "latitude": 12.9716 + index * 0.0005, "longitude": 77.5946,
            "location_source": "browser_gps",
        })
    hotspot_id = client.get("/api/admin/hotspots").json()["hotspots"][0]["id"]
    response = client.post(f"/api/admin/hotspots/{hotspot_id}/{action}", json={"notes": "ok"})
    assert response.status_code == 200
    assert response.json()["status"] == expected


def test_an_unknown_admin_action_is_404(db):
    assert _client().post("/api/admin/hotspots/1/nuke").status_code == 404


def test_admin_flag_is_distinguishable_from_an_ai_candidate(db):
    response = _client().post("/api/admin/hotspots/flag", json={
        "latitude": 12.97, "longitude": 77.59,
        "reason": "Contractor excavation without barriers", "severity": "HIGH",
    })
    hotspot = response.json()["hotspot"]
    assert hotspot["flagSource"] == "admin_flagged"
    assert hotspot["isAiDetected"] is False
    # No supporting reports are invented for a manual flag.
    assert hotspot["reportCount"] == 0
    assert hotspot["reportIds"] == []


def test_admin_map_returns_reports_hotspots_and_the_rule(db):
    client = _client()
    client.post("/api/worker/reports", json={
        "report_text": "Oil spill near loading bay.",
        "latitude": 12.9716, "longitude": 77.5946, "location_source": "browser_gps",
    })
    body = client.get("/api/admin/map").json()
    assert body["rule"]["minReports"] == 3
    assert body["rule"]["radiusMeters"] == 1000
    assert any(r["latitude"] is not None for r in body["reports"])


def test_the_hotspot_rule_is_reported_not_hardcoded_in_the_ui(db):
    rule = _client().get("/api/admin/hotspots").json()["rule"]
    assert "1 km" in rule["summary"]
    assert "demo threshold" in rule["disclaimer"].lower()
