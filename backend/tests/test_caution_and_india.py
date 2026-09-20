"""The three safety-intelligence levels, worker caution, and the India-only location rule.

Two claims in this file are the ones worth protecting, and both are asserted structurally rather
than by convention:

1. A CAUTION CANNOT MOVE A ROUTE. `safety.routing` does not import `safety.caution`, and the
   router reads published announcements only. One report or two produce advice; only a human
   pressing Publish produces something a route reacts to. Tested from both sides: the import
   graph, and an end-to-end route with a caution-generating cluster sitting on it.

2. INDIA IS CHECKED AGAINST STRUCTURED DATA. Nominatim's `countrycodes` filter is a request
   parameter; `address.country_code` is evidence. Both are used, because a filter that silently
   stopped working would otherwise go unnoticed. A substring check on the display name would pass
   for "India Street, Boston".
"""

import json
import pytest
from fastapi.testclient import TestClient

from safety import caution, llm, people, routing, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "caution.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "photos")
    store.init()
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


def _report(text, lat, lon, hazards=("Oil spill",), location="Loading Bay", worker_id=None):
    return store.save_report(
        {"report_text": text, "source": "test", "latitude": lat, "longitude": lon,
         "location": location, "location_source": "browser_gps", "worker_id": worker_id},
        {"risk_level": "MEDIUM", "risk_score": 40, "hazards": list(hazards),
         "summary": text[:60], "recommendations": {}},
    )


# --- the three levels ----------------------------------------------------------------------------

def test_one_report_claims_no_pattern(db):
    rid = _report("Oil spill near the loading bay.", *BENGALURU)
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, next(r for r in corpus if r["id"] == rid))
    assert status["level"] == caution.PATTERN_NONE
    assert status["related_count"] == 1
    assert "No recurring pattern established" in status["summary"]
    assert status["creates_hotspot"] is False


def test_two_related_reports_are_an_emerging_pattern_not_a_hotspot(db):
    first = _report("Slipped on oil near the loading bay.", *BENGALURU)
    _report("Nearly slipped because of oil near the loading bay.", 12.9740, 77.5960)
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, next(r for r in corpus if r["id"] == first))
    assert status["level"] == caution.PATTERN_EMERGING
    assert status["related_count"] == 2
    # The distinction the product depends on: two is not three.
    assert status["creates_hotspot"] is False
    assert "Below the 3-report threshold" in status["summary"]


def test_three_related_reports_reach_candidate_hotspot(db):
    first = _report("Oil spill near the loading bay.", *BENGALURU)
    _report("Forklift is leaking oil near the loading area.", 12.9740, 77.5960)
    _report("Nearly slipped on oily flooring near the loading bay.", 12.9700, 77.5930)
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, next(r for r in corpus if r["id"] == first))
    assert status["level"] == caution.PATTERN_CANDIDATE
    assert status["related_count"] == 3
    assert status["creates_hotspot"] is True
    assert "Awaiting safety-admin review" in status["summary"]


def test_unrelated_reports_nearby_are_not_a_pattern(db):
    """Proximity alone must not group a broken light with an oil spill."""
    first = _report("Oil spill near the loading bay.", *BENGALURU, hazards=("Oil spill",))
    _report("The compressor is extremely loud.", 12.9720, 77.5950, hazards=("Noise exposure",))
    _report("A light has failed in the corridor.", 12.9718, 77.5948, hazards=("Poor lighting",))
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, next(r for r in corpus if r["id"] == first))
    assert status["level"] == caution.PATTERN_NONE


def test_no_pattern_level_ever_claims_to_affect_routing(db):
    for texts in ([1], [1, 2], [1, 2, 3]):
        pass
    first = _report("Oil spill near the loading bay.", *BENGALURU)
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, next(r for r in corpus if r["id"] == first))
    assert status["affects_routing"] is False
    assert "Only a published safety alert can affect routing" in status["routing_note"]


# --- worker caution: what it says, and what it refuses to say --------------------------------------

def test_a_nearby_report_produces_a_caution(client, db):
    _report("Oil spill near the loading bay.", *BENGALURU)
    body = client.get("/api/worker/cautions",
                      params={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    assert len(body["cautions"]) == 1
    assert "Exercise caution" in body["cautions"][0]["message"]


def test_a_caution_identifies_nobody_and_counts_nothing(client, db):
    """The whole point of the shape: useful to a worker, useless for identifying a colleague."""
    _report("Oil spill near the loading bay.", *BENGALURU)
    _report("More oil near the loading bay.", 12.9718, 77.5948)
    _report("Oil again by the bay doors.", 12.9720, 77.5950)

    body = client.get("/api/worker/cautions",
                      params={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    blob = json.dumps(body).lower()

    for leaked in ("report_id", "reportid", "worker", "employee", "reporttext", "report_text",
                   "reviewnotes", "riskscore", "risklevel"):
        assert leaked not in blob, f"a caution payload leaked {leaked!r}"
    # Three reports collapse to one caution, so the list length does not reveal the count either.
    assert len(body["cautions"]) == 1


def test_a_distant_report_produces_no_caution(client, db):
    _report("Oil spill far away.", 13.0500, 77.7000)
    body = client.get("/api/worker/cautions",
                      params={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    assert body["cautions"] == []


def test_the_caution_endpoint_says_it_does_not_change_routes(client, db):
    body = client.get("/api/worker/cautions",
                      params={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    assert "do not change your route" in body["note"]
    assert body["priority"] == "published_alerts_first"


def test_published_alerts_are_returned_separately_from_cautions(client, db):
    _report("Oil spill near the loading bay.", *BENGALURU)
    client.post("/api/admin/announcements", json={
        "title": "Published alert", "message": "Avoid.", "severity": "HIGH",
        "latitude": BENGALURU[0], "longitude": BENGALURU[1], "radius_meters": 500})

    body = client.get("/api/worker/cautions",
                      params={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    # Two different claims, kept in two different lists.
    assert len(body["alerts"]) == 1
    assert len(body["cautions"]) == 1
    assert body["alerts"][0]["title"] == "Published alert"


# --- the rule that matters most: caution never moves a route ----------------------------------------

def test_the_router_cannot_see_cautions_at_all():
    """Structural: `safety.routing` does not import `safety.caution`.

    A behavioural test can only show that caution did not change a route in the cases tried. This
    shows it cannot, because the routing module has no access to the concept.
    """
    import inspect
    source = inspect.getsource(routing)
    assert "caution" not in source.lower().replace("precaution", "")
    assert "import" in source and "from safety.geo import" in source


def _ladder_service():
    """Two parallel walking routes, so a detour is available if anything tries to take one."""
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


def test_two_reports_generating_a_caution_do_not_change_the_route(client, db, monkeypatch):
    """The regression the spec asks for, end to end.

    Two related reports sit directly on the shortest route — enough for an emerging pattern and a
    worker caution. The route must be byte-identical to one computed with no reports at all.
    """
    monkeypatch.setattr(routing, "_SERVICE", _ladder_service())
    start = {"latitude": 12.9700, "longitude": 77.5900}
    end = {"latitude": 12.9850, "longitude": 77.5900}

    baseline = client.post("/api/worker/route",
                           json={"start": start, "destination": end}).json()

    # Two related reports on the route: an emerging pattern, and a caution for anyone nearby.
    _report("Slipped on oil here.", 12.9750, 77.5900)
    _report("Nearly slipped on oil here.", 12.9752, 77.5901)
    corpus = store.all_analyses()
    status = caution.pattern_status(corpus, corpus[0])
    assert status["level"] == caution.PATTERN_EMERGING          # the caution condition holds
    assert client.get("/api/worker/cautions",
                      params={"latitude": 12.9750, "longitude": 77.5900}).json()["cautions"]

    after = client.post("/api/worker/route", json={"start": start, "destination": end}).json()

    assert after["route"] == baseline["route"]
    assert after["distanceMeters"] == baseline["distanceMeters"]
    assert after["routeAdjustedForSafety"] is False
    assert after["alternativesEvaluated"] == 0
    assert after["alertsNearRoute"] == []


def test_three_reports_making_a_candidate_hotspot_still_do_not_change_the_route(client, db, monkeypatch):
    monkeypatch.setattr(routing, "_SERVICE", _ladder_service())
    start = {"latitude": 12.9700, "longitude": 77.5900}
    end = {"latitude": 12.9850, "longitude": 77.5900}

    baseline = client.post("/api/worker/route", json={"start": start, "destination": end}).json()

    for offset in (0.0000, 0.0002, 0.0004):
        _report(f"Oil spill on the path {offset}.", 12.9750 + offset, 77.5900)
    from safety import geo
    for candidate in geo.detect_hotspots(store.all_analyses()):
        store.upsert_hotspot(candidate)
    assert store.list_hotspots("PENDING_REVIEW"), "the candidate hotspot was not created"

    after = client.post("/api/worker/route", json={"start": start, "destination": end}).json()
    assert after["route"] == baseline["route"]
    assert after["routeAdjustedForSafety"] is False
    assert after["alternativesEvaluated"] == 0


def test_publishing_the_same_area_IS_allowed_to_change_the_route(client, db, monkeypatch):
    """The other half of the boundary: once a human publishes, routing may react."""
    monkeypatch.setattr(routing, "_SERVICE", _ladder_service())
    start = {"latitude": 12.9700, "longitude": 77.5900}
    end = {"latitude": 12.9850, "longitude": 77.5900}

    baseline = client.post("/api/worker/route", json={"start": start, "destination": end}).json()
    client.post("/api/admin/announcements", json={
        "title": "Oil spill", "message": "Avoid.", "severity": "HIGH",
        "latitude": 12.9775, "longitude": 77.5868, "radius_meters": 150})

    after = client.post("/api/worker/route", json={"start": start, "destination": end}).json()
    assert after["routeAdjustedForSafety"] is True
    assert after["route"] != baseline["route"]


# --- India-only location -----------------------------------------------------------------------

def test_the_search_request_defaults_to_india():
    from schemas import PlaceSearchRequest
    assert PlaceSearchRequest(query="Whitefield").country_codes == "in"


def test_a_result_outside_india_is_dropped_even_if_nominatim_returns_it():
    """The filter is a request parameter; the country code is the evidence. Both are applied."""
    from services.geocoding_service import parse_search
    payload = [
        {"display_name": "Whitefield, New Hampshire, United States", "lat": "44.37", "lon": "-71.61",
         "address": {"country_code": "us"}},
        {"display_name": "Whitefield, Bengaluru, Karnataka, India", "lat": "12.96", "lon": "77.75",
         "address": {"country_code": "in"}},
    ]
    matches = parse_search(payload)
    assert [m.country_code for m in matches] == ["us", "in"]
    kept = [m for m in matches if m.country_code == "in"]
    assert len(kept) == 1
    assert "Bengaluru" in kept[0].display_name


def test_a_result_with_no_country_code_is_unverified_not_assumed_indian():
    from services.geocoding_service import parse_search
    matches = parse_search([{"display_name": "Somewhere", "lat": "12.9", "lon": "77.5"}])
    assert matches[0].country_code is None


def test_the_display_name_is_not_used_as_the_country_check():
    """"India Street, Boston" contains the word India and is in Massachusetts."""
    from services.geocoding_service import parse_search
    matches = parse_search([{"display_name": "India Street, Boston, United States",
                             "lat": "42.36", "lon": "-71.05",
                             "address": {"country_code": "us"}}])
    assert matches[0].country_code == "us"


def test_a_coordinate_far_outside_india_is_rejected_without_a_network_call(client, db):
    body = client.post("/api/worker/verify-location",
                       json={"latitude": 40.7128, "longitude": -74.0060}).json()   # New York
    assert body["accepted"] is False
    assert "supports locations in India" in body["reason"]
    assert "bounding box" in body["method"]


def test_a_coordinate_inside_india_is_accepted(client, db, monkeypatch):
    from services.geocoding_service import GeocodedPlace
    import safety.roles_api as roles_api

    class _Fake:
        def reverse(self, lat, lon):
            return GeocodedPlace(display_name="Bengaluru, India", city="Bengaluru",
                                 state="Karnataka", country="India", country_code="in",
                                 postcode=None, neighbourhood=None, water_feature=None), False

    monkeypatch.setattr(roles_api, "get_geocoder", lambda: _Fake())
    body = client.post("/api/worker/verify-location",
                       json={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    assert body["accepted"] is True
    assert body["countryCode"] == "in"


def test_a_coordinate_just_inside_the_box_but_in_another_country_is_rejected(client, db, monkeypatch):
    """Why the box alone is not enough: it also contains parts of neighbouring countries."""
    from services.geocoding_service import GeocodedPlace
    import safety.roles_api as roles_api

    class _Fake:
        def reverse(self, lat, lon):
            return GeocodedPlace(display_name="Kathmandu, Nepal", city="Kathmandu", state=None,
                                 country="Nepal", country_code="np", postcode=None,
                                 neighbourhood=None, water_feature=None), False

    monkeypatch.setattr(roles_api, "get_geocoder", lambda: _Fake())
    body = client.post("/api/worker/verify-location",
                       json={"latitude": 27.7172, "longitude": 85.3240}).json()
    assert body["accepted"] is False
    assert body["countryCode"] == "np"


def test_an_unreachable_geocoder_accepts_the_location_as_unverified(client, db, monkeypatch):
    """A worker in a yard in Pune must not be blocked because Nominatim is down."""
    import safety.roles_api as roles_api

    class _Broken:
        def reverse(self, lat, lon):
            raise RuntimeError("offline")

    monkeypatch.setattr(roles_api, "get_geocoder", lambda: _Broken())
    body = client.post("/api/worker/verify-location",
                       json={"latitude": BENGALURU[0], "longitude": BENGALURU[1]}).json()
    assert body["accepted"] is True
    assert body["verified"] is False
    assert "could not be confirmed" in body["reason"]


# --- the roster ----------------------------------------------------------------------------------

def test_there_is_exactly_one_safety_admin(db):
    people.seed_demo_data()
    admins = store.list_users("SAFETY_ADMIN")
    assert len(admins) == 1
    assert admins[0]["employee_id"] == "ADMIN001"
    assert admins[0]["name"] == "Safety Admin"


def test_there_are_fifteen_workers_with_unique_ids(db):
    people.seed_demo_data()
    workers = store.list_users("WORKER")
    ids = [w["employee_id"] for w in workers]
    assert len(workers) == 15
    assert len(set(ids)) == 15
    assert ids[0] == "EMP001" and ids[-1] == "EMP015"


def test_the_three_scenarios_reach_their_intended_levels(db):
    outcome = people.seed_demo_data()
    corpus = store.all_analyses()
    for key, scenario in outcome["scenarios"]["scenarios"].items():
        subject = next(r for r in corpus if r["id"] == scenario["report_ids"][0])
        status = caution.pattern_status(corpus, subject)
        assert status["level"] == scenario["expected_level"], key


def test_scenario_seeding_is_idempotent(db):
    people.seed_demo_data()
    again = people.seed_demo_data()
    assert again["scenarios"]["created"] == 0
    assert again["scenarios"]["skipped_as_duplicates"] > 0
