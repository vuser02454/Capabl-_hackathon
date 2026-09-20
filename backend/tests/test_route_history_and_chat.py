"""Persisted route events, their classification, and the grounded chatbot.

Two claims carry the weight here.

ROUTE HISTORY IS EVIDENCE, NOT RECONSTRUCTION. The geometry served to the worker is stored and
returned verbatim. A route rebuilt later from start + destination would use today's map and
today's alerts, so "did EMP007 pass through this area" would be answered about a route nobody
walked. The tests assert the stored geometry survives, and that a worker appears in an
affected-workers list only because their recorded route came within the radius.

THE CHATBOT CANNOT INVENT OR ACT. It reaches the database only through the fixed read-only
functions in `chat_tools`, so a question it has no tool for returns "not enough recorded data"
rather than prose. A request to publish or dismiss is refused before any tool runs. A worker's
tools take the caller's own id, so naming another worker cannot widen the answer.
"""

import json
import pytest
from fastapi.testclient import TestClient

from safety import chat, chat_tools, llm, routes_history, routing, store

START = {"latitude": 12.9700, "longitude": 77.5900}
END = {"latitude": 12.9850, "longitude": 77.5900}


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    """Answers must be composed deterministically, so the tests read the real facts."""
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "routes.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "photos")
    store.init()
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


def _ladder_service():
    payload = {"elements": [
        {"type": "way", "id": 1, "nodes": [1, 2, 3, 6], "tags": {"highway": "footway"},
         "geometry": [{"lat": 12.9700, "lon": 77.5900}, {"lat": 12.9750, "lon": 77.5900},
                      {"lat": 12.9800, "lon": 77.5900}, {"lat": 12.9850, "lon": 77.5900}]},
        {"type": "way", "id": 2, "nodes": [1, 4, 5, 6], "tags": {"highway": "footway"},
         "geometry": [{"lat": 12.9700, "lon": 77.5900}, {"lat": 12.9725, "lon": 77.5960},
                      {"lat": 12.9825, "lon": 77.5960}, {"lat": 12.9850, "lon": 77.5900}]},
    ]}

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
    return routing.RoutingService(provider)


@pytest.fixture
def routed(monkeypatch):
    monkeypatch.setattr(routing, "_SERVICE", _ladder_service())


def _worker(client, employee_id="EMP001", name="Worker 001"):
    return store.upsert_user({"employee_id": employee_id, "name": name,
                              "email": f"{employee_id.lower()}@example.com",
                              "role": "WORKER", "department": "Warehouse"})


def _route(client, employee_id=None):
    body = {"start": START, "destination": END}
    if employee_id:
        body["employee_id"] = employee_id
    return client.post("/api/worker/route", json=body)


def _publish(client, latitude, longitude, severity="HIGH", radius=150, title="Oil spill",
             restricted=False):
    return client.post("/api/admin/announcements", json={
        "title": title, "message": "Avoid.", "severity": severity,
        "latitude": latitude, "longitude": longitude, "radius_meters": radius,
        "restricted": restricted, "location_text": "Bay"}).json()["announcement"]


# --- 1, 8, 9, 10: an event is persisted, with both geometries ---------------------------------

def test_a_route_request_persists_an_event(client, db, routed):
    _worker(client)
    response = _route(client, "EMP001")
    assert response.status_code == 200
    assert response.json()["routeEventId"] is not None
    assert store.count_route_events() == 1


def test_the_event_preserves_both_geometries(client, db, routed):
    _worker(client)
    _publish(client, 12.9775, 77.5868)                 # forces a detour
    event_id = _route(client, "EMP001").json()["routeEventId"]

    stored = store.get_route_event(event_id)
    # Both routes are kept: the one the worker walked, and the one they would have.
    assert len(stored["selected_route_geometry"]) > 1
    assert len(stored["original_route_geometry"]) > 1
    assert stored["original_route_geometry"] != stored["selected_route_geometry"]
    # Ordered coordinate pairs, not a summary.
    assert set(stored["selected_route_geometry"][0]) == {"latitude", "longitude"}


def test_every_alternative_branch_supplies_the_rejected_geometry(client, db, routed):
    """Regression: one of the two alternative branches omitted `original_route_geometry`.

    The recorder used to fall back to the selected route when it was missing, so the event stored
    original == selected — which reads as evidence that no detour occurred, on the very events
    where one did. The fallback is gone and both branches now supply it; this pins both halves.
    """
    _worker(client)
    _publish(client, 12.9775, 77.5868, severity="HIGH")
    event_id = _route(client, "EMP001").json()["routeEventId"]

    stored = store.get_route_event(event_id)
    assert stored["route_adjusted_for_safety"] is True
    assert stored["original_route_geometry"], "the rejected route was not recorded"
    assert stored["original_route_geometry"] != stored["selected_route_geometry"]
    # And the distances agree with the geometries rather than contradicting them.
    assert stored["original_distance_meters"] < stored["selected_distance_meters"]


def test_the_recorder_does_not_substitute_the_selected_route_for_a_missing_original():
    """The masking behaviour itself, asserted directly."""
    import inspect
    from safety import routes_history
    source = inspect.getsource(routes_history.record)
    assert 'result.get("original_route_geometry", [])' in source
    assert 'original_route_geometry") or result.get("route")' not in source


def test_the_event_preserves_the_alert_association(client, db, routed):
    _worker(client)
    alert = _publish(client, 12.9775, 77.5868, severity="HIGH")
    event_id = _route(client, "EMP001").json()["routeEventId"]

    stored = store.get_route_event(event_id)
    assert stored["affecting_alert_id"] == alert["id"]
    assert stored["affecting_alert_severity"] == "HIGH"
    assert stored["affecting_alert_radius_meters"] == 150
    assert stored["minimum_distance_to_alert_meters"] is not None


def test_the_detour_ratio_is_stored_and_consistent(client, db, routed):
    _worker(client)
    _publish(client, 12.9775, 77.5868)
    event_id = _route(client, "EMP001").json()["routeEventId"]

    stored = store.get_route_event(event_id)
    original, selected = stored["original_distance_meters"], stored["selected_distance_meters"]
    assert selected > original
    assert stored["detour_distance_meters"] == selected - original
    assert stored["detour_ratio"] == pytest.approx(selected / original, rel=1e-2)
    assert stored["detour_ratio"] <= routing.MAX_ROUTE_DETOUR_RATIO


def test_an_unattributed_route_is_still_recorded_but_owned_by_nobody(client, db, routed):
    _route(client)                                      # no employee_id
    events = store.list_route_events()
    assert len(events) == 1
    assert events[0]["employee_id"] is None


# --- 5, 6, 7: classification -------------------------------------------------------------------

def test_a_clear_route_is_classified_normal(client, db, routed):
    _worker(client)
    body = _route(client, "EMP001").json()
    assert body["classification"] == routes_history.NORMAL_ROUTE
    assert store.get_route_event(body["routeEventId"])["classification"] == "NORMAL_ROUTE"


def test_a_high_severity_alert_forcing_a_detour_is_classified_as_one(client, db, routed):
    _worker(client)
    _publish(client, 12.9775, 77.5868, severity="HIGH")
    body = _route(client, "EMP001").json()
    assert body["routeAdjustedForSafety"] is True
    assert body["classification"] == routes_history.HIGH_HAZARD_DETOUR


def test_a_moderate_alert_forcing_a_detour_is_not_called_high_hazard(client, db, routed):
    """A detour is still a detour, but MEDIUM severity is not the high-hazard case."""
    _worker(client)
    _publish(client, 12.9775, 77.5868, severity="MEDIUM")
    body = _route(client, "EMP001").json()
    assert body["routeAdjustedForSafety"] is True
    assert body["classification"] == routes_history.MODERATE_HAZARD_PASSED


def test_no_clear_alternative_is_classified_as_such(client, db, routed):
    _worker(client)
    # Both branches blocked: nothing is clear.
    _publish(client, 12.9775, 77.5868, title="Upper")
    _publish(client, 12.9775, 77.5992, title="Lower")
    body = _route(client, "EMP001").json()
    assert body["selected"] == "none_clear"
    assert body["classification"] == routes_history.NO_SAFE_ALTERNATIVE
    assert body["safeAlternativeFound"] is False


def test_classification_is_a_pure_function_of_the_routing_result():
    """No model, no database — a dict in, a string out."""
    assert routes_history.classify({"selected": "shortest", "adjusted_for_safety": False,
                                    "alerts_near_route": [], "blocking_alerts": []}) == "NORMAL_ROUTE"
    assert routes_history.classify({"selected": "none_clear"}) == "NO_SAFE_ALTERNATIVE"
    assert routes_history.classify({
        "selected": "alternative", "adjusted_for_safety": True,
        "blocking_alerts": [{"severity": "HIGH", "closest_approach_meters": 10}],
    }) == "HIGH_HAZARD_DETOUR"


# --- 2, 3, 4: who may read a route event ---------------------------------------------------------

def test_a_worker_reads_their_own_routes(client, db, routed):
    _worker(client, "EMP001")
    _route(client, "EMP001")
    body = client.get("/api/worker/routes", params={"employee_id": "EMP001"}).json()
    assert body["count"] == 1
    assert "no history exists" in body["note"].lower() or "were not recorded" in body["note"]


def test_a_worker_cannot_read_another_workers_route(client, db, routed):
    _worker(client, "EMP001")
    _worker(client, "EMP002", name="Worker 002")
    event_id = _route(client, "EMP001").json()["routeEventId"]

    assert client.get(f"/api/worker/routes/{event_id}",
                      params={"employee_id": "EMP002"}).status_code == 404
    assert client.get("/api/worker/routes",
                      params={"employee_id": "EMP002"}).json()["count"] == 0
    # Identical to a route that does not exist, so absence is not a disclosure.
    assert client.get("/api/worker/routes/999999",
                      params={"employee_id": "EMP002"}).status_code == 404


def test_a_workers_own_route_carries_no_other_workers_details(client, db, routed):
    _worker(client, "EMP001")
    _route(client, "EMP001")
    row = client.get("/api/worker/routes", params={"employee_id": "EMP001"}).json()["routes"][0]
    for admin_only in ("employeeId", "workerName", "department", "alertsNearRoute"):
        assert admin_only not in row


def test_an_admin_reads_any_workers_routes(client, db, routed):
    _worker(client, "EMP001")
    _worker(client, "EMP002", name="Worker 002")
    _route(client, "EMP001")
    _route(client, "EMP002")

    assert client.get("/api/admin/routes").json()["count"] == 2
    one = client.get("/api/admin/workers/EMP001/routes").json()
    assert one["count"] == 1
    assert one["routes"][0]["employeeId"] == "EMP001"


def test_the_admin_route_list_summarises_by_classification(client, db, routed):
    _worker(client, "EMP001")
    _route(client, "EMP001")
    summary = client.get("/api/admin/routes").json()["summary"]
    assert summary["total"] == 1
    normal = next(c for c in summary["byClassification"]
                  if c["classification"] == "NORMAL_ROUTE")
    assert normal["count"] == 1
    assert "No history exists" in summary["coverageNote"] or "no history" in summary["coverageNote"].lower()


def test_admin_routes_can_be_filtered(client, db, routed):
    _worker(client, "EMP001")
    _worker(client, "EMP002", name="Worker 002")
    _route(client, "EMP001")
    _route(client, "EMP002")
    assert client.get("/api/admin/routes", params={"employee_id": "EMP001"}).json()["count"] == 1
    assert client.get("/api/admin/routes",
                      params={"classification": "NORMAL_ROUTE"}).json()["count"] == 2
    assert client.get("/api/admin/routes",
                      params={"classification": "HIGH_HAZARD_DETOUR"}).json()["count"] == 0


def test_an_unknown_classification_filter_is_refused(client, db):
    assert client.get("/api/admin/routes",
                      params={"classification": "SOMETHING"}).status_code == 422


# --- 12, 13, 14: who is listed as affected, and why ------------------------------------------------

def test_a_worker_is_listed_as_affected_only_from_stored_geometry(client, db, routed):
    _worker(client, "EMP001")
    alert = _publish(client, 12.9775, 77.5868, severity="HIGH")
    _route(client, "EMP001")

    body = client.get(f"/api/admin/alerts/{alert['id']}/affected-workers").json()
    assert body["count"] == 1
    assert body["workers"][0]["employeeId"] == "EMP001"
    assert body["workers"][0]["minimumDistanceToAlertMeters"] is not None
    # The provenance is stated, not implied.
    assert "stored route geometry" in body["evidence"]
    assert "Absence from this list is not evidence" in body["coverageNote"]


def test_a_route_that_never_came_near_is_not_listed(client, db, routed):
    _worker(client, "EMP001")
    _route(client, "EMP001")                            # recorded with no alert in range
    far = _publish(client, 13.5000, 78.5000, title="Elsewhere")
    body = client.get(f"/api/admin/alerts/{far['id']}/affected-workers").json()
    assert body["count"] == 0


def test_a_candidate_hotspot_creates_no_affected_worker_record(client, db, routed):
    """An unpublished candidate must not produce routing evidence about anybody."""
    _worker(client, "EMP001")
    store.upsert_hotspot({
        "latitude": 12.9750, "longitude": 77.5900, "radius_meters": 1000, "report_count": 3,
        "primary_hazard": "Oil spill", "related_hazards": [], "risk_level": "HIGH",
        "first_report_at": None, "latest_report_at": None, "report_ids": [1, 2, 3],
        "locations": [], "explanation": "", "flag_source": "ai_detected",
        "status": "PENDING_REVIEW"})

    body = _route(client, "EMP001").json()
    assert body["classification"] == routes_history.NORMAL_ROUTE
    stored = store.get_route_event(body["routeEventId"])
    assert stored["affecting_alert_id"] is None
    assert stored["alerts_near_route"] == []


def test_only_rerouted_workers_appear_in_the_rerouted_list(client, db, routed):
    _worker(client, "EMP001")
    _worker(client, "EMP002", name="Worker 002")
    _route(client, "EMP001")                            # clear, before any alert

    alert = _publish(client, 12.9775, 77.5868, severity="HIGH")
    _route(client, "EMP002")                            # rerouted

    body = client.get(f"/api/admin/alerts/{alert['id']}/rerouted-workers").json()
    assert [w["employeeId"] for w in body["workers"]] == ["EMP002"]
    worker = body["workers"][0]
    assert worker["additionalDistanceMeters"] > 0
    assert worker["originalRouteGeometry"] != worker["selectedRouteGeometry"]


# --- the chatbot: grounding, refusal, and role scoping ---------------------------------------------

def test_the_chatbot_answers_from_stored_records(client, db, routed):
    _worker(client, "EMP001")
    alert = _publish(client, 12.9775, 77.5868, severity="HIGH")
    _route(client, "EMP001")

    body = client.post("/api/safety/chat", json={
        "question": f"Which workers were rerouted by alert #{alert['id']}?", "role": "admin"}).json()
    assert body["grounded"] is True
    assert "get_workers_rerouted_by_alert" in body["tools"]
    assert "EMP001" in json.dumps(body["evidence"])
    assert "1 worker" in body["answer"]


def test_the_chatbot_refuses_a_question_it_has_no_data_for(client, db):
    body = client.post("/api/safety/chat", json={
        "question": "What is the capital of France?", "role": "admin"}).json()
    assert body["grounded"] is False
    assert body["answer"] == chat.NO_DATA_ANSWER


def test_the_chatbot_will_not_act_on_a_safety_decision(client, db):
    for ask in ("Publish this hotspot", "Dismiss alert 3", "Contact the police",
                "Change the severity to HIGH", "Resolve this incident"):
        body = client.post("/api/safety/chat", json={"question": ask, "role": "admin"}).json()
        assert body["refused"] is True, ask
        assert "Safety Admin action" in body["answer"]
        assert body["tools"] == []


def test_a_worker_asking_about_another_worker_gets_their_own_records(client, db, routed):
    _worker(client, "EMP001")
    _worker(client, "EMP002", name="Worker 002")
    _route(client, "EMP002")                            # EMP002 has a route; EMP001 does not

    body = client.post("/api/safety/chat", json={
        "question": "Show me EMP002's routes", "role": "worker", "employee_id": "EMP001"}).json()

    blob = json.dumps(body)
    # The worker tool took EMP001 from the session, not EMP002 from the question.
    assert "EMP002" not in blob or body["grounded"] is False
    if body["grounded"]:
        assert '"employee_id": "EMP001"' in blob


def test_a_worker_cannot_reach_an_admin_tool(client, db):
    assert chat_tools.run("get_department_statistics", {}, role="worker")["error"]
    assert chat_tools.run("get_workers_rerouted_by_alert", {"alert_id": 1},
                          role="worker")["error"]


def test_every_chat_tool_is_read_only():
    """Structural: no tool writes. A mutating tool could not be added without failing this."""
    import inspect
    for name, tool in chat_tools.ADMIN_TOOLS.items():
        source = inspect.getsource(tool)
        for writer in ("save_report", "upsert_", "record_", "set_hotspot_status",
                       "create_announcement", "attach_", "DELETE", "UPDATE", "INSERT"):
            assert writer not in source, f"{name} appears to write via {writer}"


def test_the_worker_tool_table_is_a_strict_subset_of_what_exists():
    shared = set(chat_tools.WORKER_TOOLS) & set(chat_tools.ADMIN_TOOLS)
    own = set(chat_tools.WORKER_TOOLS) - set(chat_tools.ADMIN_TOOLS)
    assert shared == {"get_published_alerts"}
    # A worker's private tools are caller-scoped; none takes an employee id from the question.
    assert own == chat_tools.CALLER_SCOPED


def test_the_deterministic_answer_is_always_returned_beside_the_phrasing(client, db, routed):
    """What makes 'the model only phrases things' checkable rather than asserted."""
    _worker(client, "EMP001")
    _route(client, "EMP001")
    body = client.post("/api/safety/chat", json={
        "question": "What published alerts are affecting routing?", "role": "admin"}).json()
    assert body["deterministicAnswer"]
    assert body["answerSource"] == "deterministic"      # no LLM in this test run


def test_a_worker_must_identify_themselves(client, db):
    assert client.post("/api/safety/chat",
                       json={"question": "my reports", "role": "worker"}).status_code == 422


# --- dashboard ---------------------------------------------------------------------------------

def test_the_dashboard_counts_route_activity_from_stored_rows(client, db, routed):
    _worker(client, "EMP001")
    _publish(client, 12.9775, 77.5868, severity="HIGH")
    _route(client, "EMP001")

    data = client.get("/api/admin/dashboard").json()
    assert data["routeEventCount"] == 1
    assert data["workersReroutedFromHighHazards"] == 1
    assert data["workerCount"] == 1
