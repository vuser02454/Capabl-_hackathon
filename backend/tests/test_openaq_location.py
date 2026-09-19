from datetime import datetime, timedelta, timezone
from urllib.error import URLError

import pytest

from agents.air_agent import AirQualityAgent
from agents.base import AgentTrace
from core.errors import DataSourceError, NoMonitoringDataError
from services import openaq_service
from services.openaq_service import OpenAQClient, OpenAQProvider, parse_station, station_score

NOW = datetime.now(timezone.utc)


def dt(delta):
    moment = NOW - delta
    return {"utc": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "local": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}


def sensor(sensor_id, name, units="µg/m³"):
    return {"id": sensor_id, "name": name, "parameter": {"id": 1, "name": name, "units": units, "displayName": name}}


LOW_COST_CLOSE = {  # ~0.9 km, fresh, PM2.5 only
    "id": 1, "name": "Low-cost sensor", "isMobile": False, "isMonitor": False,
    "coordinates": {"latitude": 12.9796, "longitude": 77.5946}, "datetimeLast": dt(timedelta(minutes=10)),
    "sensors": [sensor(11, "pm25")],
}
REFERENCE_FRESH = {  # ~3.3 km, fresh, all pollutants
    "id": 2, "name": "Reference monitor", "isMobile": False, "isMonitor": True,
    "coordinates": {"latitude": 13.0016, "longitude": 77.5946}, "datetimeLast": dt(timedelta(minutes=30)),
    "sensors": [sensor(21, "pm25"), sensor(22, "pm10"), sensor(23, "no2"), sensor(24, "o3")],
}
REFERENCE_STALE = {  # ~0.4 km, reference, but weeks old
    "id": 3, "name": "Stale monitor", "isMobile": False, "isMonitor": True,
    "coordinates": {"latitude": 12.9756, "longitude": 77.5946}, "datetimeLast": dt(timedelta(days=30)),
    "sensors": [sensor(31, "pm25"), sensor(32, "pm10"), sensor(33, "no2"), sensor(34, "o3")],
}
MOBILE = {"id": 4, "name": "Mobile", "isMobile": True, "isMonitor": True, "coordinates": {"latitude": 12.9716, "longitude": 77.5946},
          "datetimeLast": dt(timedelta(minutes=1)), "sensors": [sensor(41, "pm25")]}

LATEST = {
    2: [
        {"sensorsId": 21, "value": 42.0, "datetime": dt(timedelta(minutes=30))},
        {"sensorsId": 22, "value": 78.0, "datetime": dt(timedelta(minutes=30))},
        {"sensorsId": 23, "value": 31.0, "datetime": dt(timedelta(minutes=30))},
        {"sensorsId": 24, "value": 20.0, "datetime": dt(timedelta(minutes=30))},
    ]
}


class FakeOpenAQ:
    def __init__(self, locations, latest=None, error=None):
        self.locations = locations
        self.latest = latest or {}
        self.error = error
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if self.error:
            raise self.error
        if path == "/locations":
            return {"results": self.locations}
        if path.endswith("/latest"):
            return {"results": self.latest.get(int(path.split("/")[2]), [])}
        return {"results": []}


def provider_for(client):
    return OpenAQProvider("test-key", client=client)


def test_openaq_receives_live_coordinates(bengaluru_gps):
    client = FakeOpenAQ([REFERENCE_FRESH], LATEST)
    provider_for(client).get_latest(bengaluru_gps)
    path, params = client.calls[0]
    assert path == "/locations"
    assert params["coordinates"] == "12.9716,77.5946"
    assert params["radius"] == 25000


def test_best_suitable_station_selected(bengaluru_gps):
    client = FakeOpenAQ([LOW_COST_CLOSE, REFERENCE_STALE, REFERENCE_FRESH, MOBILE], LATEST)
    reading = provider_for(client).get_latest(bengaluru_gps)
    assert reading.station_name == "Reference monitor"
    assert reading.distance_km == pytest.approx(3.3, abs=0.1)
    assert (reading.pm25, reading.pm10, reading.no2) == (42.0, 78.0, 31.0)
    assert reading.freshness == "live"
    assert reading.data_age_minutes is not None and reading.data_age_minutes <= 31
    assert (reading.station_latitude, reading.station_longitude) == (13.0016, 77.5946)


def test_station_score_weights_recency_hardware_and_coverage():
    now = NOW
    max_age = timedelta(hours=24)
    stations = {raw["name"]: parse_station(raw, 12.9716, 77.5946) for raw in (LOW_COST_CLOSE, REFERENCE_FRESH, REFERENCE_STALE)}
    scores = {name: station_score(station, now, max_age) for name, station in stations.items()}
    assert scores["Reference monitor"] < scores["Low-cost sensor"] < scores["Stale monitor"]


def test_no_station_found(bengaluru_gps):
    with pytest.raises(NoMonitoringDataError, match="No suitable nearby air-quality station found"):
        provider_for(FakeOpenAQ([MOBILE])).get_latest(bengaluru_gps)


def test_openaq_api_failure_message(monkeypatch):
    def broken(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(openaq_service, "urlopen", broken)
    with pytest.raises(DataSourceError, match="Air-quality provider temporarily unavailable"):
        OpenAQClient("key", "https://api.openaq.org/v3", 1).get("/locations")


def test_air_agent_builds_result_from_live_coordinates(bengaluru_gps):
    agent = AirQualityAgent(provider_for(FakeOpenAQ([REFERENCE_FRESH], LATEST)))
    trace = AgentTrace()
    result = agent.run(bengaluru_gps, trace)
    assert result.is_mock is False
    assert result.freshness == "live"
    assert result.station_name == "Reference monitor"
    assert result.source_location.latitude == 13.0016
    assert result.location == "Bengaluru"
    assert any(step.startswith("Searching nearby OpenAQ stations") for step in trace.steps)
    assert any(step.startswith("Station selected · Reference monitor · 3.3 km away") for step in trace.steps)
