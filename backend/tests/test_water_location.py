import io
from datetime import datetime, timedelta, timezone

import pytest

from agents.base import AgentTrace
from agents.water_agent import WaterQualityAgent
from config import settings
from core.errors import SensorDataUnavailableError
from schemas import LocationContext
from services.water_sensor_service import (
    HISTORICAL_MESSAGE,
    NO_SENSOR_MESSAGE,
    FirebaseReader,
    LatestReadingCache,
    LocationAwareWaterProvider,
    PushReader,
    WaterDataset,
    WaterObservation,
    WaterSource,
    WaterSourceRegistry,
    load_registry,
)

NOW = datetime.now(timezone.utc)
NODE = WaterSource("WATER_001", "EcoSentinel Water Node 01", "iot", "mqtt", 12.9720, 77.5951, ("ph", "turbidity", "temperature"))
FAR_NODE = WaterSource("WATER_002", "Far node", "iot", "mqtt", 12.99, 77.62)
STATION = WaterSource("WQ-1", "City monitoring station", "monitoring_station", "http_json", 12.98, 77.60, url="https://station.example/latest")
DEMO = WaterSource("WTR-07", "Demo node", "iot", "demo", 12.9717, 77.5947, profile_id="bengaluru")


def live_provider(sources, cache=None, readers=None, dataset=None):
    cache = cache or LatestReadingCache()
    return LocationAwareWaterProvider(
        WaterSourceRegistry(sources),
        readers=readers if readers is not None else {"mqtt": PushReader(cache)},
        dataset=dataset,
        demo_mode=False,
    )


def test_nearest_sensor_selection(bengaluru_gps):
    hits = WaterSourceRegistry([FAR_NODE, NODE]).nearest(12.9716, 77.5946, kinds={"iot"})
    assert hits[0][0].sensor_id == "WATER_001"
    assert round(hits[0][1], 2) == 0.07


def test_live_iot_reading_from_nearest_sensor(bengaluru_gps):
    cache = LatestReadingCache()
    cache.ingest("WATER_001", {"ph": 7.2, "turbidity": 3.1, "temperature": 25.0, "tds": 310, "observed_at": NOW.isoformat()})
    reading = live_provider([FAR_NODE, NODE], cache).get_latest(bengaluru_gps)
    assert reading.sensor_id == "WATER_001"
    assert reading.source_type == "live_iot"
    assert reading.is_mock is False
    assert reading.distance_km == 0.07
    assert reading.tds == 310


def test_water_sensor_unavailable(bengaluru_gps):
    with pytest.raises(SensorDataUnavailableError, match=NO_SENSOR_MESSAGE):
        live_provider([NODE]).get_latest(bengaluru_gps)


def test_stale_iot_reading_is_not_treated_as_live(bengaluru_gps):
    cache = LatestReadingCache()
    cache.ingest("WATER_001", {"ph": 7.0, "observed_at": (NOW - timedelta(hours=3)).isoformat()})
    with pytest.raises(SensorDataUnavailableError):
        live_provider([NODE], cache).get_latest(bengaluru_gps)


def test_monitoring_station_used_when_no_iot_sensor(bengaluru_gps):
    class StationReader:
        def read(self, source):
            return {"ph": 7.4, "turbidity": 8.0, "temperature": 26.5, "observedAt": NOW.isoformat()}

    reading = live_provider([NODE, STATION], readers={"mqtt": PushReader(LatestReadingCache()), "http_json": StationReader()}).get_latest(bengaluru_gps)
    assert reading.source_type == "monitoring_station"
    assert reading.sensor_id == "WQ-1"
    assert any("no telemetry received" in note for note in reading.notes)


def test_historical_water_fallback(bengaluru_gps):
    dataset = WaterDataset([
        WaterObservation("SITE-1", "River site", 12.95, 77.60, NOW - timedelta(days=20), 7.8, 12.0, 24.0, 480.0, "State dataset"),
        WaterObservation("SITE-1", "River site", 12.95, 77.60, NOW - timedelta(days=50), 7.5, 9.0, 23.0, 450.0, "State dataset"),
    ])
    reading = live_provider([NODE], dataset=dataset).get_latest(bengaluru_gps)
    assert reading.source_type == "historical"
    assert reading.is_mock is False
    assert reading.notes[0] == HISTORICAL_MESSAGE
    assert reading.ph == 7.8  # most recent observation for the nearest site
    assert reading.data_age_minutes >= 20 * 24 * 60


def test_live_mode_never_uses_demo_sensors(bengaluru_gps):
    with pytest.raises(SensorDataUnavailableError):
        live_provider([DEMO]).get_latest(bengaluru_gps)


def test_demo_mode_uses_demo_registry():
    provider = LocationAwareWaterProvider(WaterSourceRegistry(load_registry(settings.water_registry_path)), demo_mode=True)
    reading = provider.get_latest(LocationContext(latitude=12.9716, longitude=77.5946))
    assert (reading.sensor_id, reading.source_type, reading.is_mock) == ("WTR-07", "demo", True)
    assert (reading.ph, reading.turbidity, reading.temperature) == (6.4, 14, 27.4)


def test_demo_mode_far_from_demo_sites_is_simulated_nearby():
    provider = LocationAwareWaterProvider(WaterSourceRegistry(load_registry(settings.water_registry_path)), demo_mode=True)
    reading = provider.get_latest(LocationContext(latitude=48.8566, longitude=2.3522))
    assert reading.sensor_id == "DEMO-WATER" and reading.is_mock is True
    assert reading.distance_km < 3


def test_water_agent_reports_source_and_distance(bengaluru_gps):
    cache = LatestReadingCache()
    cache.ingest("WATER_001", {"ph": 7.2, "turbidity": 3.1, "temperature": 25.0, "observed_at": NOW.isoformat()})
    trace = AgentTrace()
    result = WaterQualityAgent(live_provider([NODE], cache)).run(bengaluru_gps, trace)
    assert result.source_type == "live_iot"
    assert result.sensor_distance_km == 0.07
    assert result.source_location.latitude == 12.9720
    assert "Sensor selected · EcoSentinel Water Node 01 (WATER_001) · 0.07 km away" in trace.steps
    assert "Data source · LIVE IOT · EcoSentinel water sensor" in trace.steps


def test_firebase_reader_requests_sensor_path():
    captured = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def opener(request, timeout):
        captured["url"] = request.full_url
        return Response(b'{"ph": 7.0, "observedAt": 1700000000000}')

    payload = FirebaseReader("https://demo-rtdb.example", "secret", opener=opener).read(NODE)
    assert captured["url"] == "https://demo-rtdb.example/sensors/WATER_001/latest.json?auth=secret"
    assert payload["ph"] == 7.0
