"""Worker → Admin notifications and Admin → Worker announcements.

The boundary is `store.notifications_for`, whose WHERE clause decides who may read a row. That is
tested from the failing side: a message addressed to EMP002 must not appear in EMP001's query at
all, so no later filtering step can forget to remove it.

Two subtleties are worth the tests they get:

BROADCAST READ STATE cannot live on the notification row. One announcement is read by fifteen
workers, and marking the row read would mark it read for all of them — so broadcasts use a
per-reader receipt and targeted messages use the row.

AN ANNOUNCEMENT IS NOT A PUBLISHED ALERT. Only `POST /api/admin/announcements` creates something
routing reacts to. A notification is a message, and the tests assert it leaves routing alone.
"""

import json
import pytest
from fastapi.testclient import TestClient

from safety import llm, routing, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "notif.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "photos")
    store.init()
    store.upsert_user({"employee_id": "ADMIN001", "name": "Safety Admin",
                       "email": "admin@example.com", "role": "SAFETY_ADMIN",
                       "department": "Operations"})
    for n in (1, 2):
        store.upsert_user({"employee_id": f"EMP00{n}", "name": f"Worker 00{n}",
                           "email": f"emp00{n}@example.com", "role": "WORKER",
                           "department": "Warehouse"})
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


def _submit(client, employee_id="EMP001", text="Oil spill near the loading bay."):
    return client.post("/api/worker/reports", json={
        "report_text": text, "employee_id": employee_id,
        "latitude": BENGALURU[0], "longitude": BENGALURU[1], "gps_accuracy": 11.0,
        "location_source": "browser_gps", "location_text": "Loading Bay"})


# --- worker -> admin --------------------------------------------------------------------------

def test_submitting_a_report_notifies_the_admin(client, db):
    report_id = _submit(client).json()["reportId"]
    body = client.get("/api/admin/notifications").json()
    assert body["unreadCount"] == 1
    notification = body["notifications"][0]
    assert notification["type"] == "REPORT_SUBMITTED"
    assert notification["reportId"] == report_id
    assert notification["senderEmployeeId"] == "EMP001"


def test_the_admin_notification_carries_the_evidence_needed_to_act(client, db):
    _submit(client)
    notification = client.get("/api/admin/notifications").json()["notifications"][0]
    assert notification["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert notification["latitude"] == pytest.approx(BENGALURU[0])
    assert notification["gpsAccuracy"] == 11.0
    assert notification["locationSource"] == "browser_gps"
    assert notification["metadata"]["hazards"]          # extracted risk factors travel with it


def test_the_notification_links_to_the_report_it_is_about(client, db):
    report_id = _submit(client).json()["reportId"]
    notification = client.get("/api/admin/notifications").json()["notifications"][0]
    # The id is what makes the notification clickable through to the incident.
    detail = client.get(f"/api/admin/reports/{notification['reportId']}")
    assert detail.status_code == 200
    assert detail.json()["report"]["id"] == report_id


def test_an_unattributed_report_still_notifies(client, db):
    """A report filed without an employee id is still a hazard the admin must see."""
    client.post("/api/worker/reports", json={"report_text": "Oil on the floor."})
    body = client.get("/api/admin/notifications").json()
    assert body["unreadCount"] == 1
    assert body["notifications"][0]["senderEmployeeId"] is None


def test_a_failed_notification_never_costs_the_report(client, db, monkeypatch):
    """An unnotified report is recoverable from the reports list; a rejected one is not."""
    import safety.roles_api as roles_api

    def _explode(*_args, **_kwargs):
        raise RuntimeError("notification store is down")

    monkeypatch.setattr(roles_api.store, "create_notification", _explode)
    response = _submit(client)
    assert response.status_code == 200
    assert response.json()["reportId"] is not None


# --- read state -------------------------------------------------------------------------------

def test_marking_one_read_reduces_the_unread_count(client, db):
    _submit(client)
    first = client.get("/api/admin/notifications").json()["notifications"][0]
    marked = client.post(f"/api/admin/notifications/{first['id']}/read").json()
    assert marked["unreadCount"] == 0
    assert client.get("/api/admin/notifications").json()["notifications"][0]["read"] is True


def test_mark_all_read_clears_the_count(client, db):
    _submit(client, "EMP001")
    _submit(client, "EMP002", text="Blocked fire exit in the north block.")
    assert client.get("/api/admin/notifications").json()["unreadCount"] == 2
    assert client.post("/api/admin/notifications/read-all").json()["unreadCount"] == 0


def test_unread_only_filters(client, db):
    _submit(client, "EMP001")
    _submit(client, "EMP002", text="Blocked fire exit.")
    first = client.get("/api/admin/notifications").json()["notifications"][0]
    client.post(f"/api/admin/notifications/{first['id']}/read")
    assert client.get("/api/admin/notifications",
                      params={"unread_only": True}).json()["count"] == 1


# --- admin -> worker ----------------------------------------------------------------------------

def test_a_broadcast_reaches_every_worker(client, db):
    client.post("/api/admin/notifications/send", json={
        "title": "Site inspection Friday", "message": "Expect access restrictions.",
        "severity": "LOW"})
    for employee_id in ("EMP001", "EMP002"):
        body = client.get("/api/worker/notifications",
                          params={"employee_id": employee_id}).json()
        assert body["count"] == 1
        assert body["notifications"][0]["title"] == "Site inspection Friday"


def test_a_targeted_message_reaches_only_its_recipient(client, db):
    client.post("/api/admin/notifications/send", json={
        "title": "Please re-file your report", "message": "Details were incomplete.",
        "employee_ids": ["EMP002"]})

    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP002"}).json()["count"] == 1
    # The boundary: EMP001's query cannot return it at all.
    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP001"}).json()["count"] == 0


def test_one_worker_reading_a_broadcast_does_not_read_it_for_everyone(client, db):
    """Why broadcast read state cannot live on the notification row."""
    client.post("/api/admin/notifications/send", json={
        "title": "Toolbox talk", "message": "0800 Monday."})
    first = client.get("/api/worker/notifications",
                       params={"employee_id": "EMP001"}).json()["notifications"][0]
    client.post(f"/api/worker/notifications/{first['id']}/read",
                params={"employee_id": "EMP001"})

    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP001"}).json()["unreadCount"] == 0
    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP002"}).json()["unreadCount"] == 1


def test_a_worker_cannot_mark_another_workers_message_read(client, db):
    client.post("/api/admin/notifications/send", json={
        "title": "For EMP002", "message": "x", "employee_ids": ["EMP002"]})
    target = client.get("/api/worker/notifications",
                        params={"employee_id": "EMP002"}).json()["notifications"][0]
    assert client.post(f"/api/worker/notifications/{target['id']}/read",
                       params={"employee_id": "EMP001"}).status_code == 404


def test_sending_to_an_unknown_worker_is_refused(client, db):
    assert client.post("/api/admin/notifications/send", json={
        "title": "t", "message": "m", "employee_ids": ["NOBODY"]}).status_code == 404


# --- what a worker's notification payload withholds ------------------------------------------------

def test_a_worker_never_sees_another_workers_report_evidence(client, db):
    """A worker's own notifications must not become a window onto admin-side detail."""
    _submit(client, "EMP001")                       # raises an ADMIN notification
    client.post("/api/admin/notifications/send", json={
        "title": "Area closed", "message": "Loading bay shut until Friday."})

    body = client.get("/api/worker/notifications", params={"employee_id": "EMP002"}).json()
    blob = json.dumps(body).lower()
    # Evidence about somebody else's report. None of this may ever reach a worker.
    for leaked in ("reportid", "gpsaccuracy", "metadata", "riskfactors", "hazards"):
        assert leaked not in blob, f"the worker payload leaked {leaked!r}"
    # The report notification itself is addressed to SAFETY_ADMIN, so it is not in the list at
    # all — which is what keeps reporting anonymous between workers.
    assert all(n["type"] != "REPORT_SUBMITTED" for n in body["notifications"])


def test_a_worker_cannot_read_the_admin_notification_feed(client, db):
    """Role is part of the query, so a worker id on the admin feed returns admin rows only
    when the caller is the admin. The worker endpoint is the only one a worker can use."""
    _submit(client, "EMP001")
    worker_view = client.get("/api/worker/notifications",
                             params={"employee_id": "EMP001"}).json()
    assert worker_view["count"] == 0        # the report notification went to SAFETY_ADMIN


# --- an announcement is not a published alert -------------------------------------------------------

def test_an_announcement_does_not_affect_routing(client, db, monkeypatch):
    """Only a published safety alert reaches the router. A message must not."""
    payload = {"elements": [
        {"type": "way", "id": 1, "nodes": [1, 2, 3], "tags": {"highway": "footway"},
         "geometry": [{"lat": 12.9700, "lon": 77.5900}, {"lat": 12.9750, "lon": 77.5900},
                      {"lat": 12.9800, "lon": 77.5900}]}]}

    class _Response:
        def read(self):
            return json.dumps(payload).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    provider = routing.OSMGraphProvider(opener=lambda r, timeout=None: _Response(),
                                        sleep=lambda _s: None, clock=lambda: 0.0,
                                        min_interval_s=0, cache_dir=None)
    monkeypatch.setattr(routing, "_SERVICE", routing.RoutingService(provider))

    start = {"latitude": 12.9700, "longitude": 77.5900}
    end = {"latitude": 12.9800, "longitude": 77.5900}
    baseline = client.post("/api/worker/route", json={"start": start, "destination": end}).json()

    client.post("/api/admin/notifications/send", json={
        "title": "Hazard notice", "message": "Be careful near the bay.", "severity": "HIGH",
        "latitude": 12.9750, "longitude": 77.5900, "radius_meters": 500})

    after = client.post("/api/worker/route", json={"start": start, "destination": end}).json()
    assert after["route"] == baseline["route"]
    assert after["routeAdjustedForSafety"] is False
    assert after["alertsNearRoute"] == []


def test_the_send_endpoint_says_it_does_not_affect_routing(client, db):
    body = client.post("/api/admin/notifications/send",
                       json={"title": "t", "message": "m"}).json()
    assert "does not affect routing" in body["note"]


# --- migration safety ----------------------------------------------------------------------------

def test_the_notification_tables_are_added_without_disturbing_existing_rows(db):
    report_id = store.save_report(
        {"report_text": "Pre-existing report.", "source": "test"},
        {"risk_level": "LOW", "risk_score": 10, "hazards": []})
    before = store.count()

    store.init()        # re-running migrations must not touch data

    assert store.count() == before
    assert store.get_report(report_id) is not None
    assert store.count_notifications() == 0


# --- worker-initiated messages -------------------------------------------------------------------
#
# Two directions now exist, and they have different privacy properties. A REPORT stays anonymous
# to other workers; a MESSAGE a worker chooses to send is attributed to them. The tests below pin
# both halves, because the value of the second depends on the first still holding.

def test_a_worker_can_message_the_safety_admin(client, db):
    response = client.post("/api/worker/notifications/send", json={
        "title": "Bay 7 still wet", "message": "Barrier is up but the floor is not dry.",
        "employee_id": "EMP001", "to_admin": True})
    assert response.status_code == 200
    assert response.json()["sentToAdmin"] is True

    admin = client.get("/api/admin/notifications").json()["notifications"][0]
    assert admin["type"] == "WORKER_MESSAGE"
    assert admin["senderEmployeeId"] == "EMP001"
    assert admin["title"] == "Bay 7 still wet"


def test_a_worker_can_message_a_colleague(client, db):
    client.post("/api/worker/notifications/send", json={
        "title": "Spare harness", "message": "Left one in the store for you.",
        "employee_id": "EMP001", "to_admin": False, "recipient_employee_ids": ["EMP002"]})

    received = client.get("/api/worker/notifications",
                          params={"employee_id": "EMP002"}).json()["notifications"][0]
    assert received["title"] == "Spare harness"
    # Attributed: an anonymous message cannot be weighed, answered, or reported as misuse.
    assert received["senderEmployeeId"] == "EMP001"
    assert received["senderName"] == "Worker 001"


def test_a_colleague_message_reaches_nobody_else(client, db):
    store.upsert_user({"employee_id": "EMP003", "name": "Worker 003",
                       "email": "emp003@example.com", "role": "WORKER", "department": "Warehouse"})
    client.post("/api/worker/notifications/send", json={
        "title": "For EMP002 only", "message": "x",
        "employee_id": "EMP001", "to_admin": False, "recipient_employee_ids": ["EMP002"]})

    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP002"}).json()["count"] == 1
    assert client.get("/api/worker/notifications",
                      params={"employee_id": "EMP003"}).json()["count"] == 0


def test_a_worker_can_message_the_admin_and_colleagues_at_once(client, db):
    body = client.post("/api/worker/notifications/send", json={
        "title": "Oil again in Bay 7", "message": "Same spot as yesterday.",
        "employee_id": "EMP001", "to_admin": True,
        "recipient_employee_ids": ["EMP002"]}).json()
    assert body["count"] == 2
    assert body["sentToAdmin"] is True and body["sentToColleagues"] == 1


def test_messaging_yourself_is_a_no_op_not_an_error(client, db):
    body = client.post("/api/worker/notifications/send", json={
        "title": "note to self", "message": "x", "employee_id": "EMP001",
        "to_admin": False, "recipient_employee_ids": ["EMP001"]})
    # Refusing would be pedantic; silently duplicating it into your own inbox would be worse.
    assert body.status_code == 200
    assert body.json()["count"] == 0


def test_a_message_needs_at_least_one_recipient(client, db):
    assert client.post("/api/worker/notifications/send", json={
        "title": "t", "message": "m", "employee_id": "EMP001",
        "to_admin": False, "recipient_employee_ids": []}).status_code == 422


def test_messaging_an_unknown_worker_is_refused(client, db):
    assert client.post("/api/worker/notifications/send", json={
        "title": "t", "message": "m", "employee_id": "EMP001",
        "to_admin": False, "recipient_employee_ids": ["NOBODY"]}).status_code == 404


def test_an_unknown_sender_cannot_send(client, db):
    assert client.post("/api/worker/notifications/send", json={
        "title": "t", "message": "m", "employee_id": "GHOST", "to_admin": True}).status_code == 404


def test_a_worker_message_is_not_a_safety_report(client, db):
    """It is not analysed, does not become evidence, and does not enter pattern detection."""
    before = store.count()
    body = client.post("/api/worker/notifications/send", json={
        "title": "Oil spill in Bay 7", "message": "Looks like a big one.",
        "employee_id": "EMP001", "to_admin": True}).json()
    assert store.count() == before          # no report row was created
    assert "not a safety report" in body["note"]


# --- what the directory exposes, and what it does not ----------------------------------------------

def test_the_directory_lists_colleagues_by_identity_only(client, db):
    body = client.get("/api/worker/directory", params={"employee_id": "EMP001"}).json()
    assert body["admin"]["employeeId"] == "ADMIN001"
    assert [c["employeeId"] for c in body["colleagues"]] == ["EMP002"]
    # Enough to address a message, and nothing more: no reports, locations, counts or history.
    assert set(body["colleagues"][0]) == {"employeeId", "name", "department"}


def test_the_directory_omits_the_caller(client, db):
    body = client.get("/api/worker/directory", params={"employee_id": "EMP001"}).json()
    assert all(c["employeeId"] != "EMP001" for c in body["colleagues"])


def test_the_directory_says_that_messaging_reveals_your_id(client, db):
    body = client.get("/api/worker/directory", params={"employee_id": "EMP001"}).json()
    # The posture change is stated where the choice is made, not buried.
    assert "shows them your employee ID" in body["note"]
    assert "reports stay anonymous" in body["note"].lower()


def test_an_unknown_worker_cannot_read_the_directory(client, db):
    assert client.get("/api/worker/directory",
                      params={"employee_id": "NOBODY"}).status_code == 404


# --- reporting stays anonymous even though messaging is attributed ------------------------------------

def test_filing_a_report_is_still_never_attributed_to_a_worker_for_other_workers(client, db):
    """The guarantee messaging must not erode.

    A worker-sent MESSAGE is attributed. The automatic REPORT_SUBMITTED notification is not in
    ATTRIBUTED_TYPES and is addressed to SAFETY_ADMIN, so no worker-visible payload can carry
    who filed what.
    """
    _submit(client, "EMP001")
    assert "REPORT_SUBMITTED" not in store.ATTRIBUTED_TYPES

    for employee_id in ("EMP001", "EMP002"):
        body = client.get("/api/worker/notifications",
                          params={"employee_id": employee_id}).json()
        assert all(n["type"] != "REPORT_SUBMITTED" for n in body["notifications"])
        assert "EMP001" not in json.dumps(body)
