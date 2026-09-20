"""Persistent worker identity, location events, and geo-tagged report history.

Two things are load-bearing here.

THE DATA BOUNDARY. A worker's queries are filtered in SQL to their own rows, so a response cannot
contain another worker's records whatever else changes. That is tested from the failing side: the
assertions are that another worker's report is NOT returned, and that asking for it is
indistinguishable from asking for one that does not exist. Note that this is a data boundary, not
a security one — the project has no authentication, `employee_id` is a handle rather than a
credential, and the tests assert what the boundary actually provides rather than implying more.

IDEMPOTENCE. Seeding runs against a live database that already holds reports the demo depends on.
The tests assert that re-running creates nothing new AND that rows which existed beforehand are
still there afterwards, because "creates no duplicates" would also be satisfied by wiping first.
"""

import pytest
from fastapi.testclient import TestClient

from safety import llm, people, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "people.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "report_photos")
    store.init()
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


@pytest.fixture
def seeded(db):
    people.seed_demo_data()
    return db


def _worker(employee_id="EMP001", name="Worker 001", department="Warehouse"):
    return store.upsert_user({"employee_id": employee_id, "name": name,
                              "email": f"{employee_id.lower()}@example.com",
                              "role": "WORKER", "department": department})


# --- 1, 2: worker creation and lookup ---------------------------------------------------------

def test_a_worker_is_created_with_the_expected_fields(db):
    worker_id = _worker()
    row = store.get_user(worker_id)
    assert row["employee_id"] == "EMP001"
    assert row["name"] == "Worker 001"
    assert row["role"] == "WORKER"
    assert row["department"] == "Warehouse"
    assert row["status"] == "ACTIVE"
    assert row["created_at"] and row["updated_at"]


def test_a_worker_is_found_by_the_id_on_their_badge(db):
    _worker()
    assert store.find_user("EMP001")["name"] == "Worker 001"
    assert store.find_user("  EMP001  ")["name"] == "Worker 001"   # whitespace is tolerated
    assert store.find_user("NOBODY") is None


def test_the_employee_id_is_unique_so_a_second_upsert_updates(db):
    first = _worker()
    second = store.upsert_user({"employee_id": "EMP001", "name": "Renamed",
                                "role": "WORKER", "department": "Logistics"})
    assert first == second
    assert store.count_users() == 1
    assert store.get_user(first)["department"] == "Logistics"


def test_an_unknown_role_is_refused(db):
    with pytest.raises(ValueError, match="Unknown role"):
        store.upsert_user({"employee_id": "EMP900", "role": "SUPERUSER"})


def test_admins_and_workers_are_listed_separately(db):
    _worker()
    store.upsert_user({"employee_id": "ADM001", "name": "Admin", "role": "SAFETY_ADMIN"})
    assert store.count_users("WORKER") == 1
    assert store.count_users("SAFETY_ADMIN") == 1


# --- 3-7: report creation, persistence, and its geo fields --------------------------------------

def _submit(client, employee_id="EMP001", text="Oil spill near the loading bay.", **over):
    body = {"report_text": text, "employee_id": employee_id,
            "latitude": BENGALURU[0], "longitude": BENGALURU[1], "gps_accuracy": 12.5,
            "location_source": "browser_gps", "location_text": "Loading Bay",
            "location_captured_at": "2026-09-20T10:15:00+00:00"}
    body.update(over)
    return client.post("/api/worker/reports", json=body)


def test_a_submitted_report_is_attributed_to_its_author(client, db):
    _worker()
    response = _submit(client)
    assert response.status_code == 200
    assert response.json()["worker"]["employeeId"] == "EMP001"


def test_the_report_persists_after_the_request(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    # Read back through the store, not the response, so persistence is what is being checked.
    stored = store.report_for_worker(report_id, worker_id)
    assert stored is not None
    assert stored["report_text"] == "Oil spill near the loading bay."


def test_the_stored_report_keeps_its_coordinates(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    stored = store.report_for_worker(report_id, worker_id)
    assert stored["latitude"] == pytest.approx(BENGALURU[0])
    assert stored["longitude"] == pytest.approx(BENGALURU[1])
    assert stored["gps_accuracy"] == 12.5


def test_the_stored_report_keeps_its_location_source(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    assert store.report_for_worker(report_id, worker_id)["location_source"] == "browser_gps"


def test_the_stored_report_keeps_both_timestamps(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    stored = store.report_for_worker(report_id, worker_id)
    assert stored["created_at"]                                   # when it was filed
    assert stored["location_captured_at"] == "2026-09-20T10:15:00+00:00"   # when the fix was taken


def test_a_report_without_an_author_is_still_accepted(client, db):
    """An unattributed report must never be refused — that would lose the hazard, not just the name."""
    response = client.post("/api/worker/reports", json={"report_text": "Oil on the floor."})
    assert response.status_code == 200
    assert response.json()["worker"] is None


def test_the_geotag_comes_from_the_confirmed_fix_not_from_a_photo(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    client.post(f"/api/worker/reports/{report_id}/photo",
                files={"file": ("p.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")},
                data={"photo_source": "live_camera"})
    stored = store.report_for_worker(report_id, worker_id)
    # The photo is attached, and the coordinates are still the ones the worker confirmed.
    assert stored["photo_source"] == "live_camera"
    assert stored["latitude"] == pytest.approx(BENGALURU[0])
    assert stored["location_source"] == "browser_gps"

    evidence = client.get(f"/api/admin/reports/{report_id}").json()["evidence"]
    assert "not from photo EXIF" in evidence["geotagNote"]


# --- 8, 9: a worker sees their own reports and only their own ------------------------------------

def test_a_worker_retrieves_their_own_reports(client, db):
    _worker()
    _submit(client, text="First report.")
    _submit(client, text="Second report.")
    body = client.get("/api/worker/reports", params={"employee_id": "EMP001"}).json()
    assert body["count"] == 2
    assert {r["reportText"] for r in body["reports"]} == {"First report.", "Second report."}


def test_a_worker_cannot_retrieve_another_workers_reports(client, db):
    _worker("EMP001")
    _worker("EMP002", name="Worker 002")
    _submit(client, employee_id="EMP001", text="Belongs to one.")
    _submit(client, employee_id="EMP002", text="Belongs to two.")

    one = client.get("/api/worker/reports", params={"employee_id": "EMP001"}).json()
    texts = {r["reportText"] for r in one["reports"]}
    assert texts == {"Belongs to one."}
    assert "Belongs to two." not in texts


def test_another_workers_report_is_indistinguishable_from_one_that_does_not_exist(client, db):
    _worker("EMP001")
    _worker("EMP002", name="Worker 002")
    other_id = _submit(client, employee_id="EMP002", text="Not yours.").json()["reportId"]

    denied = client.get(f"/api/worker/reports/{other_id}", params={"employee_id": "EMP001"})
    missing = client.get("/api/worker/reports/999999", params={"employee_id": "EMP001"})
    # Saying "exists, but not yours" would itself disclose that it exists.
    assert denied.status_code == missing.status_code == 404


def test_a_worker_sees_their_own_report_in_detail(client, db):
    _worker()
    report_id = _submit(client).json()["reportId"]
    body = client.get(f"/api/worker/reports/{report_id}", params={"employee_id": "EMP001"}).json()
    assert body["report"]["id"] == report_id
    assert body["report"]["riskLevel"] in ("LOW", "MEDIUM", "HIGH")
    assert body["report"]["latitude"] == pytest.approx(BENGALURU[0])


def test_a_workers_own_report_carries_no_admin_only_fields(client, db):
    _worker()
    _submit(client)
    row = client.get("/api/worker/reports", params={"employee_id": "EMP001"}).json()["reports"][0]
    for leaked in ("reviewNotes", "reviewedBy", "hotspotId", "supportingReports", "contributions"):
        assert leaked not in row


def test_an_unknown_employee_id_is_a_404(client, db):
    assert client.get("/api/worker/reports", params={"employee_id": "NOBODY"}).status_code == 404


def test_an_admins_id_cannot_be_used_on_the_worker_endpoints(client, db):
    store.upsert_user({"employee_id": "ADM001", "name": "Admin", "role": "SAFETY_ADMIN"})
    assert client.get("/api/worker/reports", params={"employee_id": "ADM001"}).status_code == 403


# --- 10: admin access --------------------------------------------------------------------------

def test_an_admin_can_list_the_roster_with_report_counts(client, seeded):
    body = client.get("/api/admin/workers").json()
    assert body["count"] == people.WORKER_COUNT + people.ADMIN_COUNT
    workers = [w for w in body["workers"] if w["role"] == "WORKER"]
    assert all(w["reportCount"] > 0 for w in workers)
    assert "Synthetic demo identities" in body["syntheticNotice"]


def test_an_admin_can_read_one_workers_reports(client, seeded):
    body = client.get("/api/admin/workers/EMP001/reports").json()
    assert body["worker"]["employeeId"] == "EMP001"
    assert body["count"] > 0
    first = body["reports"][0]
    assert {"id", "createdAt", "riskLevel", "latitude", "location"} <= set(first)


def test_admin_report_access_does_not_include_location_history(client, seeded):
    """Knowing where a worker has been is not needed to act on a report, so it is not offered."""
    body = client.get("/api/admin/workers/EMP001/reports").json()
    assert "locations" not in body
    assert "locationHistory" not in body


def test_an_unknown_worker_is_a_404_for_the_admin_too(client, seeded):
    assert client.get("/api/admin/workers/NOBODY/reports").status_code == 404


# --- 11: location history persists ----------------------------------------------------------------

def test_submitting_a_report_with_a_fix_records_one_location_event(client, db):
    worker_id = _worker()
    report_id = _submit(client).json()["reportId"]
    history = store.location_history(worker_id)
    assert len(history) == 1
    assert history[0]["report_id"] == report_id
    assert history[0]["location_source"] == "browser_gps"
    assert history[0]["gps_accuracy"] == 12.5


def test_a_report_without_a_fix_records_no_location_event(client, db):
    """No coordinates means nothing to record — not a row with nulls in it."""
    worker_id = _worker()
    client.post("/api/worker/reports", json={"report_text": "Oil on the floor.",
                                             "employee_id": "EMP001"})
    assert store.location_history(worker_id) == []


def test_an_explicit_location_request_is_recorded(client, db):
    _worker()
    response = client.post("/api/worker/locations", json={
        "employee_id": "EMP001", "latitude": BENGALURU[0], "longitude": BENGALURU[1],
        "gps_accuracy": 9.0, "location_source": "browser_gps"})
    assert response.status_code == 200
    assert "not tracked continuously" in response.json()["note"]


def test_a_worker_reads_their_own_location_history(client, db):
    _worker()
    client.post("/api/worker/locations", json={"employee_id": "EMP001",
                                               "latitude": BENGALURU[0], "longitude": BENGALURU[1]})
    body = client.get("/api/worker/location-history", params={"employee_id": "EMP001"}).json()
    assert body["count"] == 1
    assert "does not track workers continuously" in body["note"]


def test_a_worker_cannot_read_another_workers_location_history(client, db):
    _worker("EMP001")
    _worker("EMP002", name="Worker 002")
    client.post("/api/worker/locations", json={"employee_id": "EMP002",
                                               "latitude": BENGALURU[0], "longitude": BENGALURU[1]})
    body = client.get("/api/worker/location-history", params={"employee_id": "EMP001"}).json()
    assert body["count"] == 0


def test_a_location_event_needs_both_coordinates(db):
    worker_id = _worker()
    with pytest.raises(ValueError, match="both latitude and longitude"):
        store.record_location({"worker_id": worker_id, "latitude": 12.97, "longitude": None})


def test_there_is_no_endpoint_that_records_location_without_an_explicit_request(client, db):
    """The privacy guarantee, asserted structurally: only two writers exist.

    If a background or bulk location writer were ever added, this test would not catch it — but a
    route that accepts a stream of positions would, and none exists.
    """
    # Asserted against the SOURCE, not the route table: the guarantee is about which code paths
    # write a location row, and a route's name or method says nothing about that. Counting call
    # sites catches a new writer however it is exposed — or not exposed at all.
    import inspect
    from safety import roles_api

    source = inspect.getsource(roles_api)
    call_sites = source.count("store.record_location")

    # Exactly two: the explicit POST /api/worker/locations, and report submission carrying a fix.
    assert call_sites == 2, (
        f"{call_sites} call sites write a location row; expected exactly 2 "
        "(explicit request, and report submission)."
    )
    assert "record_worker_location" in source     # the explicit endpoint
    assert "submit_worker_report" in source       # the report path


# --- 12: reports accumulate rather than replacing each other -------------------------------------

def test_multiple_reports_do_not_overwrite_each_other(client, db):
    _worker()
    ids = [_submit(client, text=f"Report number {n}.").json()["reportId"] for n in range(1, 4)]
    assert len(set(ids)) == 3
    body = client.get("/api/worker/reports", params={"employee_id": "EMP001"}).json()
    assert body["count"] == 3
    assert {r["id"] for r in body["reports"]} == set(ids)


def test_report_history_is_newest_first(client, db):
    _worker()
    _submit(client, text="Older.")
    _submit(client, text="Newer.")
    reports = client.get("/api/worker/reports", params={"employee_id": "EMP001"}).json()["reports"]
    assert reports[0]["reportText"] == "Newer."


# --- 13, 14: seeding is idempotent and destroys nothing --------------------------------------------

def test_seeding_creates_the_expected_roster(db):
    outcome = people.seed_demo_data()
    assert outcome["users"]["workers"] == people.WORKER_COUNT
    assert outcome["users"]["admins"] == people.ADMIN_COUNT
    assert outcome["reports"]["reports_created"] == sum(people.REPORTS_PER_WORKER)


def test_running_the_seed_twice_creates_no_duplicates(db):
    people.seed_demo_data()
    before = people.summary()
    second = people.seed_demo_data()
    assert second["users"]["created"] == 0
    assert second["reports"]["reports_created"] == 0
    assert second["reports"]["reports_skipped_as_duplicates"] > 0
    assert people.summary() == before


def test_seeding_leaves_reports_that_already_existed_untouched(client, db):
    """"No duplicates" would also be satisfied by wiping first, so this checks the other half."""
    _worker("EMP500", name="Pre-existing")
    existing_id = _submit(client, employee_id="EMP500", text="Filed before any seeding.").json()["reportId"]
    before_total = store.count()

    people.seed_demo_data()

    still_there = store.get_report(existing_id)
    assert still_there is not None
    assert still_there["report"]["report_text"] == "Filed before any seeding."
    # The roster's history plus the three demonstration scenarios; nothing removed.
    scenario_reports = sum(len(s["reports"]) for s in people.SCENARIOS.values())
    assert store.count() == before_total + sum(people.REPORTS_PER_WORKER) + scenario_reports


def test_no_worker_receives_the_same_report_text_twice(seeded):
    with store.connect() as conn:
        duplicates = conn.execute(
            """SELECT worker_id, report_text, COUNT(*) AS n FROM safety_report
               WHERE worker_id IS NOT NULL GROUP BY worker_id, report_text HAVING n > 1"""
        ).fetchall()
    assert duplicates == []


def test_the_seed_is_deterministic(db, tmp_path, monkeypatch):
    people.seed_demo_data()
    first = [(r["report_text"], r["latitude"], r["longitude"])
             for r in store.reports_for_worker(store.find_user("EMP001")["id"])]

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "second.db")
    store.init()
    people.seed_demo_data()
    second = [(r["report_text"], r["latitude"], r["longitude"])
              for r in store.reports_for_worker(store.find_user("EMP001")["id"])]
    assert first == second


# --- seeded data is labelled as seeded --------------------------------------------------------------

def test_seeded_rows_are_labelled_rather_than_posing_as_device_fixes(seeded):
    """Invented coordinates must not sit in the same field real GPS fixes use."""
    rows = store.reports_for_worker(store.find_user("EMP001")["id"])
    assert rows
    assert all(row["location_source"] == "demo_seed" for row in rows)
    assert all(row["source"] == "demo_seed" for row in rows)


def test_seeded_identities_use_a_reserved_email_domain(seeded):
    for user in store.list_users():
        assert user["email"].endswith("@example.com")   # RFC 2606: can never be a real address


def test_seeded_reports_are_spread_across_departments(seeded):
    departments = {w["department"] for w in store.list_users("WORKER")}
    assert len(departments) >= 5
    assert departments <= set(store.DEPARTMENTS)


def test_seeded_reports_carry_coordinates_and_some_carry_a_photo_association(seeded):
    summary = people.summary()
    scenario_reports = sum(len(s["reports"]) for s in people.SCENARIOS.values())
    assert summary["geotagged_reports"] >= sum(people.REPORTS_PER_WORKER)
    assert summary["photo_associated_reports"] > 0
    # One location event per seeded report, from both the roster history and the scenarios.
    assert summary["location_records"] == sum(people.REPORTS_PER_WORKER) + scenario_reports


# --- the worker profile endpoint ------------------------------------------------------------------

def test_the_profile_reports_what_is_on_file(client, seeded):
    body = client.get("/api/worker/me", params={"employee_id": "EMP001"}).json()
    assert body["worker"]["employeeId"] == "EMP001"
    assert body["reportCount"] > 0
    assert body["locationEventCount"] > 0
    # The absence of authentication is stated, not implied.
    assert "not authentication" in body["note"]
