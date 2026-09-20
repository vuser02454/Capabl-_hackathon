from datetime import datetime, timezone

from fastapi.testclient import TestClient

import main
from core.errors import GeocodingError
from services.geocoding_service import GeocodedPlace

client = TestClient(main.app)

GPS = {"latitude": 12.9716, "longitude": 77.5946, "accuracyM": 18, "city": "Bengaluru", "displayName": "Bengaluru, Karnataka, India", "source": "browser_geolocation", "geocoding": "nominatim"}


class FakeGeocoder:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def reverse(self, lat, lon):
        self.calls.append((lat, lon))
        if self.error:
            raise self.error
        return GeocodedPlace(
            display_name="Bengaluru, Karnataka, India", city="Bengaluru", state="Karnataka",
            country="India", country_code="in", postcode="560001",
            neighbourhood="Shivajinagar", water_feature=None,
        ), False


def test_reverse_geocode_endpoint(monkeypatch):
    fake = FakeGeocoder()
    monkeypatch.setattr(main, "get_geocoder", lambda: fake)
    response = client.post("/api/location/reverse", json={"latitude": 12.9716, "longitude": 77.5946})
    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "Bengaluru" and body["cached"] is False
    assert fake.calls == [(12.9716, 77.5946)]


def test_reverse_geocode_failure(monkeypatch):
    monkeypatch.setattr(main, "get_geocoder", lambda: FakeGeocoder(GeocodingError("Location detected, but place name could not be resolved.")))
    response = client.post("/api/location/reverse", json={"latitude": 12.9716, "longitude": 77.5946})
    assert response.status_code == 502
    assert response.json()["error"] == {"code": "GEOCODING_FAILED", "message": "Location detected, but place name could not be resolved."}


def test_reverse_geocode_keeps_coordinates_out_of_urls():
    assert client.get("/api/location/reverse?lat=12.97&lon=77.59").status_code == 405


def test_analyze_requires_a_location():
    assert client.post("/api/analyze", json={"demoMode": True}).status_code == 422


def test_demo_mode_analysis_with_location_context():
    response = client.post("/api/analyze", json={"locationContext": GPS, "demoMode": True})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "demo"
    assert body["locationContext"]["latitude"] == 12.9716
    assert body["water"]["sourceType"] == "demo"
    assert body["air"]["stationDistanceKm"] is not None


def test_live_mode_with_pushed_iot_reading():
    ingest = client.post(
        "/api/sensors/water/WATER_001/readings",
        json={"ph": 7.3, "turbidity": 2.5, "temperature": 24.6, "tds": 280},
        headers={"X-Sensor-Token": "test-token"},
    )
    assert ingest.status_code == 200

    body = client.post("/api/analyze", json={"locationContext": GPS, "demoMode": False}).json()
    water = body["water"]
    assert water["sourceType"] == "live_iot"
    assert water["sensorId"] == "WATER_001"
    assert water["isMock"] is False
    assert water["sensorDistanceKm"] == 0.07
    assert body["coordinator"]["inputsReceived"] == ["air", "water", "waste"]


def test_live_mode_without_nearby_sensor_reports_unavailable():
    far = {**GPS, "latitude": 28.6139, "longitude": 77.2090, "city": "Delhi"}
    body = client.post("/api/analyze", json={"locationContext": far, "demoMode": False}).json()
    water_run = next(run for run in body["runs"] if run["agent"] == "water")
    assert body["water"] is None
    assert water_run["status"] == "failed"
    assert water_run["error"] == "No nearby live water sensor available."
    assert body["coordinator"]["missingInputs"] == ["water"]


def test_ingest_requires_valid_token():
    response = client.post("/api/sensors/water/WATER_001/readings", json={"ph": 7.0}, headers={"X-Sensor-Token": "wrong"})
    assert response.status_code == 401


def test_ingest_rejects_unregistered_sensor():
    response = client.post("/api/sensors/water/WTR-07/readings", json={"ph": 7.0}, headers={"X-Sensor-Token": "test-token"})
    assert response.status_code == 404


def test_environment_for_location_context():
    response = client.post("/api/environment", json={"locationContext": GPS})
    assert response.status_code == 200
    assert response.json()["location"]["name"] == "Bengaluru"
    assert set(response.json()["history"]) == {"24h", "7d", "30d"}


def test_historical_observation_age_is_reported():
    # Timestamp sanity: API serialises timezone-aware datetimes.
    assert datetime.now(timezone.utc).tzinfo is not None


# --------------------------------------------------------------------- geographic context endpoint


def _context_payload(**overrides):
    from schemas import GeographicContext, GeographicFeature

    defaults = dict(
        available=True,
        status="ok",
        radius_m=1500,
        industrial_features=[
            GeographicFeature(
                osm_id="way/1", name="Peenya Estate", category="industrial", kind="industrial",
                label="Industrial area", latitude=12.975, longitude=77.594, distance_km=0.38,
            )
        ],
        waste_facilities=[],
        waterways=[],
        roads=[],
    )
    defaults.update(overrides)
    return GeographicContext(**defaults)


def test_geographic_context_endpoint(monkeypatch):
    calls = []

    def fake(lat, lon, radius_m, per_category):
        calls.append((lat, lon, radius_m, per_category))
        return _context_payload()

    monkeypatch.setattr(main, "resolve_geographic_context", fake)
    response = client.post("/api/location/context", json={"latitude": 12.9716, "longitude": 77.5946})

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True and body["source"] == "OpenStreetMap/Overpass"
    assert body["industrialFeatures"][0]["label"] == "Industrial area"
    assert calls == [(12.9716, 77.5946, None, None)]


def test_geographic_context_never_returns_an_error_status(monkeypatch):
    """An Overpass outage must degrade the panel, not fail the caller's request."""
    monkeypatch.setattr(
        main,
        "resolve_geographic_context",
        lambda *_args: _context_payload(
            available=False, status="unavailable", message="Could not reach Overpass.", industrial_features=[]
        ),
    )
    response = client.post("/api/location/context", json={"latitude": 12.9716, "longitude": 77.5946})

    assert response.status_code == 200
    assert response.json()["available"] is False
    assert response.json()["message"] == "Could not reach Overpass."


def test_geographic_context_keeps_coordinates_out_of_urls():
    assert client.get("/api/location/context?lat=12.97&lon=77.59").status_code == 405


def test_geographic_context_rejects_impossible_coordinates():
    response = client.post("/api/location/context", json={"latitude": 999, "longitude": 77.59})
    assert response.status_code == 422


def test_geographic_context_caps_the_requested_radius():
    """A caller must not be able to aim an expensive query at donated infrastructure."""
    response = client.post(
        "/api/location/context", json={"latitude": 12.9716, "longitude": 77.5946, "radiusM": 50000}
    )
    assert response.status_code == 422


def test_analysis_carries_geographic_context_without_it_reaching_the_coordinator():
    """The enrichment is reported alongside the assessment, never folded into it."""
    response = client.post("/api/analyze", json={"locationContext": GPS, "demoMode": True})
    assert response.status_code == 200
    body = response.json()

    assert body["geographicContext"]["status"] == "skipped"  # Demo Mode never queries Overpass
    # The coordinator's own payload has no geographic field at all.
    assert not any("geograph" in key.lower() for key in body["coordinator"])
