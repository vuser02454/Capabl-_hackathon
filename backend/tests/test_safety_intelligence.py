"""Incident-domain routing, authority lookup, geographic history and the admin audit trail.

Three things are load-bearing here and each is tested from the failure side as well as the happy
one:

1. ROUTING must be reproducible. A report that mentions an assault has to reach the security
   branch every time, and a housekeeping observation must never reach it. The router is regex-based
   precisely so this can be asserted rather than hoped for.

2. AUTHORITY LOOKUP must never invent. The tests assert that an unmappable authority type reports
   why it cannot be looked up, that a transport failure degrades to "unavailable" instead of
   raising, and that an OSM object without a phone number comes back with `verified: False` rather
   than a plausible-looking number.

3. THE EXPLANATION must cite only stored evidence. Every claim in an assessment is checked against
   the reports that were actually inserted, and the no-history case is asserted to say so rather
   than to produce a confident-sounding empty summary.

No test here touches the network: the Overpass client is driven through an injected opener.
"""

import json
import io
import pytest
from fastapi.testclient import TestClient
from urllib.error import HTTPError, URLError

from safety import authority, domains, geo, history, llm, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "intel.db")
    monkeypatch.setattr(store, "PHOTO_DIR", tmp_path / "report_photos")
    store.init()
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


def _stored(text, lat=BENGALURU[0], lon=BENGALURU[1], hazards=("Oil spill",), level="MEDIUM"):
    """Insert one report with an analysis, as the graph would."""
    return store.save_report(
        {"report_text": text, "source": "test", "latitude": lat, "longitude": lon,
         "location": "Loading Bay", "location_source": "browser_gps"},
        {"risk_level": level, "risk_score": 40, "hazards": list(hazards),
         "summary": text[:60], "recommendations": {}},
    )


# --- incident domain routing --------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("A person was assaulted near the east entrance by an intruder.", "VIOLENCE_SECURITY"),
    ("Thick smoke and flames are coming from the switchboard room.", "FIRE"),
    ("An exposed live wire is sparking near the wet floor.", "ELECTRICAL"),
    ("I saw leopard pug marks near the damaged perimeter fence.", "WILDLIFE"),
    ("A worker is unconscious and not breathing after a fall.", "MEDICAL"),
    ("Caustic solvent fumes are escaping from the drum store.", "CHEMICAL"),
    ("Cartons are stacked in the walkway, poor housekeeping.", "GENERAL_SAFETY"),
    ("The canteen tea is served cold every morning.", "OTHER"),
])
def test_each_domain_routes_to_its_own_branch(text, expected):
    assert domains.classify(text)["domain"] == expected


def test_routing_carries_the_phrase_that_decided_it():
    result = domains.classify("A person was assaulted near the east entrance.")
    # A routing decision that cannot be checked is not much better than a random one.
    assert result["matched_text"].lower() == "assaulted"
    assert "assaulted" in result["evidence"]


def test_urgency_wins_over_match_count():
    # Four housekeeping words and one fire word: it is still a fire.
    text = "Clutter, debris, obstruction and untidy stacking — and there is smoke from the panel."
    assert domains.classify(text)["domain"] == "FIRE"


def test_the_losing_domain_is_still_reported():
    result = domains.classify("There is smoke near the stacked cartons blocking the exit.")
    assert result["domain"] == "FIRE"
    assert "GENERAL_SAFETY" in [m["domain"] for m in result["also_matched"]]


def test_only_emergency_domains_get_an_authority():
    assert domains.DOMAIN_AUTHORITY["VIOLENCE_SECURITY"] == "POLICE"
    assert domains.DOMAIN_AUTHORITY["GENERAL_SAFETY"] is None
    assert "GENERAL_SAFETY" not in domains.EMERGENCY_DOMAINS


def test_an_unclassifiable_report_is_OTHER_not_a_guess():
    assert domains.classify("")["domain"] == "OTHER"
    assert domains.classify("")["authority_type"] is None


# --- serious incident markers -------------------------------------------------------------------

def test_a_fatality_in_the_text_is_marked_serious():
    markers = domains.serious_incident_markers("A contractor was killed when the scaffold collapsed.")
    assert "Fatality" in [m["label"] for m in markers]


def test_an_ordinary_report_carries_no_serious_marker():
    assert domains.serious_incident_markers("Cartons are stacked in the walkway.") == []


# --- authority lookup ---------------------------------------------------------------------------

def _opener(payload=None, error=None):
    """Stand in for urlopen. Returns an Overpass payload, or raises the given transport error."""
    calls = {"n": 0}

    class _Response:
        def read(self):
            return json.dumps(payload or {"elements": []}).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    def opener(request, timeout=None):
        calls["n"] += 1
        if error is not None:
            raise error
        return _Response()

    opener.calls = calls
    return opener


def _service(opener):
    # No sleeping in tests; the throttle and the retry pause are both driven through these.
    return authority.AuthorityLookupService(opener=opener, sleep=lambda _s: None,
                                            clock=lambda: 0.0, min_interval_s=0)


POLICE_PAYLOAD = {"elements": [
    {"type": "node", "id": 1, "lat": 12.9760, "lon": 77.5950,
     "tags": {"amenity": "police", "name": "Cubbon Park Police Station",
              "phone": "+91 80 2294 2222", "addr:street": "Kasturba Road", "addr:city": "Bengaluru"}},
    {"type": "node", "id": 2, "lat": 12.9900, "lon": 77.6000,
     "tags": {"amenity": "police", "name": "Unlisted Outpost"}},
]}


def test_lookup_returns_real_osm_fields_and_a_computed_distance():
    result = _service(_opener(POLICE_PAYLOAD)).lookup(*BENGALURU, "POLICE")
    assert result["available"] is True
    nearest = result["results"][0]
    assert nearest["name"] == "Cubbon Park Police Station"
    assert nearest["phone"] == "+91 80 2294 2222"
    assert nearest["address"] == "Kasturba Road, Bengaluru"
    # Distance is arithmetic over two real coordinates, not an OSM field.
    assert 400 < nearest["distance_meters"] < 700
    assert nearest["source"] == "OpenStreetMap (Overpass API)"


def test_an_authority_without_a_phone_is_not_marked_verified():
    result = _service(_opener(POLICE_PAYLOAD)).lookup(*BENGALURU, "POLICE")
    unlisted = next(r for r in result["results"] if r["name"] == "Unlisted Outpost")
    # The absence of a number must read as absence, never as an unconfirmed-but-plausible one.
    assert unlisted["phone"] is None
    assert unlisted["verified"] is False


def test_nearest_first():
    results = _service(_opener(POLICE_PAYLOAD)).lookup(*BENGALURU, "POLICE")["results"]
    assert results == sorted(results, key=lambda r: r["distance_meters"])


def test_an_unnamed_osm_object_is_skipped_rather_than_named_for_it():
    payload = {"elements": [{"type": "node", "id": 9, "lat": 12.98, "lon": 77.60,
                             "tags": {"amenity": "police"}}]}
    result = _service(_opener(payload)).lookup(*BENGALURU, "POLICE")
    assert result["results"] == []
    assert "No police found" in result["reason"]


def test_a_transport_failure_degrades_instead_of_raising():
    result = _service(_opener(error=URLError("boom"))).lookup(*BENGALURU, "POLICE")
    assert result["available"] is False
    assert result["results"] == []
    assert result["reason"] == "Authority lookup unavailable."


def test_a_transient_status_is_retried_once():
    error = HTTPError("u", 429, "Too Many Requests", {}, io.BytesIO(b""))
    opener = _opener(error=error)
    _service(opener).lookup(*BENGALURU, "POLICE")
    assert opener.calls["n"] == 2  # one retry, then it gives up rather than hammering Overpass


def test_an_unmappable_authority_says_why_rather_than_inventing_one():
    for kind in ("WILDLIFE_AUTHORITY", "ELECTRICAL_SERVICE"):
        result = _service(_opener()).lookup(*BENGALURU, kind)
        assert result["available"] is False
        assert result["results"] == []
        assert "OpenStreetMap" in result["reason"]


def test_a_domain_with_no_authority_is_not_given_one():
    result = _service(_opener()).lookup(*BENGALURU, None)
    assert result["available"] is False
    assert "no associated emergency authority" in result["reason"]


def test_results_are_cached_so_one_location_is_not_queried_twice():
    opener = _opener(POLICE_PAYLOAD)
    service = _service(opener)
    service.lookup(*BENGALURU, "POLICE")
    second = service.lookup(*BENGALURU, "POLICE")
    assert second["cached"] is True
    assert opener.calls["n"] == 1


# --- geographic incident history ----------------------------------------------------------------

def test_history_counts_only_reports_inside_the_radius(db):
    _stored("Oil spill near the bay.")
    _stored("Oil on the floor again.", lat=12.9740)                     # ~270 m
    _stored("Oil spill in the far warehouse.", lat=12.9716, lon=77.6400)  # ~4.9 km
    corpus = store.all_analyses()
    block = history.summarise(corpus, *BENGALURU, geo.HOTSPOT_RADIUS_METERS)
    assert block["report_count"] == 2
    assert block["radius_meters"] == 1000


def test_history_excludes_the_reports_being_looked_at(db):
    first = _stored("Oil spill near the bay.")
    _stored("Oil on the floor again.")
    corpus = store.all_analyses()
    block = history.summarise(corpus, *BENGALURU, exclude_ids=[first])
    assert first not in block["report_ids"]
    assert block["report_count"] == 1


def test_history_breaks_down_risk_and_finds_recurring_hazards(db):
    _stored("Oil spill one.", hazards=("Oil spill",), level="HIGH")
    _stored("Oil spill two.", hazards=("Oil spill",), level="MEDIUM")
    _stored("Noise complaint.", hazards=("Noise exposure",), level="LOW")
    block = history.summarise(store.all_analyses(), *BENGALURU)
    assert block["risk_breakdown"] == {"HIGH": 1, "MEDIUM": 1, "LOW": 1}
    recurring = {item["hazard"]: item["count"] for item in block["recurring_hazards"]}
    # Two occurrences is recurring; one is not.
    assert recurring == {"Oil spill": 2}


def test_history_surfaces_a_serious_past_incident_with_its_report_id(db):
    grave = _stored("A contractor was killed by an animal attack near the fence.",
                    hazards=("Wildlife",), level="HIGH")
    block = history.summarise(store.all_analyses(), *BENGALURU)
    assert block["serious_incident_count"] == 1
    assert block["serious_incidents"][0]["report_id"] == grave
    assert "Fatality" in block["serious_incidents"][0]["markers"]


def test_a_report_without_coordinates_is_not_counted_as_nearby(db):
    store.save_report({"report_text": "Oil spill, location unknown.", "source": "test"},
                      {"risk_level": "LOW", "risk_score": 10, "hazards": ["Oil spill"]})
    block = history.summarise(store.all_analyses(), *BENGALURU)
    assert block["report_count"] == 0


# --- explainable assessment ---------------------------------------------------------------------

def test_no_history_is_stated_plainly_rather_than_summarised_emptily(db):
    block = history.summarise(store.all_analyses(), *BENGALURU)
    said = history.assessment(block, {"domain": "GENERAL_SAFETY", "hazards": []})
    assert "No previous safety reports" in said["statement"]
    assert said["findings"] == []
    assert said["evidence_report_ids"] == []


def test_the_assessment_cites_counts_that_match_the_stored_rows(db):
    _stored("Oil spill one.", hazards=("Oil spill",), level="HIGH")
    _stored("Oil spill two.", hazards=("Oil spill",), level="MEDIUM")
    block = history.summarise(store.all_analyses(), *BENGALURU)
    said = history.assessment(block, {"domain": "GENERAL_SAFETY", "hazards": ["Oil spill"]})
    assert "2 previous safety reports within 1 km" in said["statement"]
    assert "1 HIGH, 1 MEDIUM, 0 LOW" in said["statement"]
    assert said["evidence_report_ids"] == block["report_ids"]
    assert said["basis"] == "stored reports"


def test_the_assessment_names_the_overlap_with_the_current_report(db):
    _stored("Oil spill one.", hazards=("Oil spill",))
    _stored("Oil spill two.", hazards=("Oil spill",))
    block = history.summarise(store.all_analyses(), *BENGALURU)
    said = history.assessment(block, {"domain": "GENERAL_SAFETY", "hazards": ["Oil spill"]})
    assert "already appear" in said["statement"]


def test_a_past_fatality_is_related_to_a_current_wildlife_report_without_asserting_presence(db):
    _stored("A contractor was killed by an animal attack near the fence.", hazards=("Wildlife",))
    block = history.summarise(store.all_analyses(), *BENGALURU)
    said = history.assessment(block, {"domain": "WILDLIFE", "hazards": ["Wildlife"]})
    assert "previous serious wildlife-related incident is on record" in said["statement"]
    assert "current report contains wildlife indicators" in said["statement"]
    # The line the product must never cross.
    assert "definitely" not in said["statement"].lower()
    assert "there are wild animals" not in said["statement"].lower()


def test_no_serious_relation_is_drawn_when_the_history_has_none(db):
    _stored("Someone saw a stray dog near the gate.", hazards=("Wildlife",))
    block = history.summarise(store.all_analyses(), *BENGALURU)
    said = history.assessment(block, {"domain": "WILDLIFE", "hazards": ["Wildlife"]})
    assert "on record in this geographic area" not in said["statement"]


# --- photo evidence -----------------------------------------------------------------------------

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)


def test_a_photo_is_associated_with_the_report_and_its_confirmed_fix(client, db):
    posted = client.post("/api/worker/reports", json={
        "report_text": "Oil spill near the loading bay.",
        "latitude": BENGALURU[0], "longitude": BENGALURU[1], "gps_accuracy": 12.0,
        "location_source": "browser_gps", "location_text": "Loading Bay",
    })
    assert posted.status_code == 200
    report_id = posted.json()["reportId"]

    attached = client.post(f"/api/worker/reports/{report_id}/photo",
                           files={"file": ("photo.png", PNG, "image/png")},
                           data={"photo_source": "live_camera"})
    assert attached.status_code == 200
    assert attached.json()["photoSource"] == "live_camera"

    detail = client.get(f"/api/admin/reports/{report_id}").json()
    evidence = detail["evidence"]
    assert evidence["hasPhoto"] is True
    assert evidence["photoSource"] == "live_camera"
    # The geotag is the in-app fix, and the payload says so rather than leaving it implied.
    assert evidence["locationSource"] == "browser_gps"
    assert evidence["gpsAccuracy"] == 12.0
    assert "not from photo EXIF" in evidence["geotagNote"]


def test_the_photo_is_served_back_byte_for_byte(client, db):
    report_id = client.post("/api/worker/reports", json={"report_text": "Oil spill."}).json()["reportId"]
    client.post(f"/api/worker/reports/{report_id}/photo",
                files={"file": ("photo.png", PNG, "image/png")}, data={"photo_source": "live_camera"})
    served = client.get(f"/api/admin/reports/{report_id}/photo")
    assert served.status_code == 200
    assert served.content == PNG


def test_an_unsupported_image_type_is_refused_rather_than_stored_under_a_guess(client, db):
    report_id = client.post("/api/worker/reports", json={"report_text": "Oil spill."}).json()["reportId"]
    refused = client.post(f"/api/worker/reports/{report_id}/photo",
                          files={"file": ("x.gif", b"GIF89a", "image/gif")},
                          data={"photo_source": "live_camera"})
    assert refused.status_code == 415


def test_a_report_without_a_photo_is_still_a_complete_report(client, db):
    posted = client.post("/api/worker/reports", json={"report_text": "Oil spill near the bay."})
    assert posted.status_code == 200
    detail = client.get(f"/api/admin/reports/{posted.json()['reportId']}").json()
    assert detail["evidence"]["hasPhoto"] is False
    assert detail["evidence"]["photoUrl"] is None
    assert detail["analysis"]["riskLevel"] in ("LOW", "MEDIUM", "HIGH")


def test_a_missing_photo_is_a_404_not_an_empty_body(client, db):
    report_id = client.post("/api/worker/reports", json={"report_text": "Oil spill."}).json()["reportId"]
    assert client.get(f"/api/admin/reports/{report_id}/photo").status_code == 404


# --- admin action tracking ----------------------------------------------------------------------

def test_an_action_is_recorded_with_its_authority_and_follow_up_flag(client, db):
    posted = client.post("/api/admin/actions", json={
        "action_taken": "contacted_police", "hotspot_id": None, "report_id": None,
        "authority_contacted": "Cubbon Park Police Station",
        "admin_notes": "Called the duty officer.", "outcome": "Patrol dispatched",
        "follow_up_required": True,
    })
    assert posted.status_code == 200
    assert posted.json()["label"] == "Contacted Police"
    # The system is a record-keeper here, and says so.
    assert "did not contact" in posted.json()["note"]

    listed = client.get("/api/admin/actions").json()
    assert listed["count"] == 1
    action = listed["actions"][0]
    assert action["authorityContacted"] == "Cubbon Park Police Station"
    assert action["followUpRequired"] == 1
    assert action["actionTimestamp"]


def test_an_unknown_action_is_refused(client, db):
    assert client.post("/api/admin/actions", json={"action_taken": "sent_the_army"}).status_code == 422


def test_the_available_actions_are_published_for_the_ui(client, db):
    available = {a["id"] for a in client.get("/api/admin/actions").json()["available"]}
    assert {"contacted_police", "contacted_fire_service", "contacted_wildlife_authority",
            "contacted_electrical_service", "internal_team_notified",
            "no_action_required"} <= available


# --- admin feedback -----------------------------------------------------------------------------

def test_negative_feedback_records_its_reason(client, db):
    posted = client.post("/api/admin/feedback",
                         json={"useful": False, "reason": "wrong_authority", "comment": "Wrong station."})
    assert posted.status_code == 200
    # One click must never reshape the rules for everyone.
    assert "never retrains" in posted.json()["note"]
    listed = client.get("/api/admin/feedback").json()
    assert listed["feedback"][0]["useful"] is False
    assert listed["feedback"][0]["reason"] == "wrong_authority"


def test_an_unknown_feedback_reason_is_refused(client, db):
    assert client.post("/api/admin/feedback",
                       json={"useful": False, "reason": "because"}).status_code == 422


def test_positive_feedback_needs_no_reason(client, db):
    assert client.post("/api/admin/feedback", json={"useful": True}).status_code == 200


# --- the admin dashboard ------------------------------------------------------------------------

def test_the_dashboard_counts_what_is_actually_stored(client, db):
    client.post("/api/worker/reports", json={
        "report_text": "Oil spill near the loading bay.",
        "latitude": BENGALURU[0], "longitude": BENGALURU[1], "location_source": "browser_gps"})
    client.post("/api/worker/reports", json={"report_text": "Cartons block the walkway."})

    data = client.get("/api/admin/dashboard").json()
    assert data["reportCount"] == 2
    assert data["geolocatedCount"] == 1     # only one carried a fix
    assert data["photoCount"] == 0
    assert data["rule"]["radiusMeters"] == 1000
    assert data["rule"]["minReports"] == 3
    assert sum(data["riskBreakdown"].values()) == 2
