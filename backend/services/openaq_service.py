"""Air-quality data source consumed by the Air Quality Agent.

    LocationContext (browser GPS or preset coordinates)
      -> AirQualityAgent
      -> OpenAQProvider: nearby stations        GET /v3/locations?coordinates=lat,lon&radius=...
      -> best suitable station                  distance + recency + pollutant coverage + monitor status
      -> latest PM2.5 / PM10 / NO2 / O3         GET /v3/locations/{id}/latest
         (gaps filled from the next-nearest stations; delayed readings are labelled)
      -> 24-h PM2.5 baseline                    GET /v3/sensors/{id}/hours
      -> AirQualityReading -> AirAgentResult -> Coordinator

MockAirQualityProvider serves the demo dataset (Demo Mode, or no API key configured).
"""

import json
import math
import socket
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:  # Python 3.8+
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from config import settings
from core.errors import (
    DataSourceError,
    EcoSentinelError,
    NoMonitoringDataError,
    ProviderNotConfiguredError,
    SensorDataUnavailableError,
)
from core.geo import haversine_km
from core.risk import round_half_up
from data.history import generate_history
from data.locations import nearest_profile
from schemas import LocationContext
from services.location_service import demo_site

POLLUTANTS = ("pm25", "pm10", "no2", "o3")
LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "o3": "O₃"}
# Gas concentration conversion to µg/m³ at 25 °C and 1 atm.
PPM_TO_UGM3 = {"no2": 1880.0, "o3": 1960.0}
MAX_RADIUS_M = 25000
STATION_CACHE_SECONDS = 6 * 3600
LATEST_CACHE_SECONDS = 5 * 60
BASELINE_CACHE_SECONDS = 30 * 60
MAX_LATEST_CALLS = 6  # stations queried per analysis (OpenAQ allows 60 requests/minute)
LIVE_MAX_AGE_MINUTES = 180  # older lead readings are reported as "delayed", never "live"

# Station suitability = distance (km) + penalties expressed in kilometres.
STALE_PENALTY_KM = 50.0
LOW_COST_PENALTY_KM = 4.0
NO_PM25_PENALTY_KM = 6.0
MISSING_POLLUTANT_PENALTY_KM = 1.0


@dataclass(frozen=True)
class AirQualityReading:
    station_id: str
    station_name: str
    pm25: Optional[float]
    pm10: Optional[float]
    no2: Optional[float]
    o3: Optional[float]
    observed_at: datetime
    provider: str
    is_mock: bool
    distance_km: Optional[float] = None
    reference_grade: bool = True
    notes: Tuple[str, ...] = ()
    source_url: Optional[str] = None
    sources: Tuple[Tuple[str, str], ...] = ()  # (pollutant, "Station (2.1 km)")
    delayed: Tuple[str, ...] = ()  # pollutants older than the freshness window
    station_latitude: Optional[float] = None
    station_longitude: Optional[float] = None
    data_age_minutes: Optional[int] = None
    freshness: str = "demo"  # live | delayed | demo


class AirQualityProvider(Protocol):
    name: str
    network: str

    def get_latest(self, location: LocationContext) -> AirQualityReading: ...

    def get_pm25_baseline(self, location: LocationContext) -> Optional[float]: ...


# --------------------------------------------------------------------------- mock


class MockAirQualityProvider:
    name = "Demo dataset (OpenAQ-compatible)"
    network = "demo air-quality"

    def get_latest(self, location: LocationContext) -> AirQualityReading:
        profile, _ = nearest_profile(location.latitude, location.longitude)
        air = profile.get("air")
        if not air:
            raise SensorDataUnavailableError("No demo air-quality station is configured near this location.")
        lat, lon, simulated = demo_site(location, air.get("latitude"), air.get("longitude"), 0.9, 0.8)
        return AirQualityReading(
            station_id="DEMO-AIR" if simulated else air["stationId"],
            station_name="Simulated air station (demo)" if simulated else air["stationName"],
            pm25=air.get("pm25"),
            pm10=air.get("pm10"),
            no2=air.get("no2"),
            o3=air.get("o3"),
            observed_at=datetime.now(timezone.utc),
            provider=self.name,
            is_mock=True,
            distance_km=round_half_up(haversine_km(location.latitude, location.longitude, lat, lon), 1),
            station_latitude=lat,
            station_longitude=lon,
            data_age_minutes=0,
            freshness="demo",
        )

    def get_pm25_baseline(self, location: LocationContext) -> Optional[float]:
        profile, _ = nearest_profile(location.latitude, location.longitude)
        values = [p.pm25 for p in generate_history(profile, "24h")[:-1] if p.pm25 is not None]
        return sum(values) / len(values) if values else None


# --------------------------------------------------------------------------- OpenAQ helpers


def parse_utc(value: Any) -> Optional[datetime]:
    """Parse an OpenAQ DatetimeObject ({"utc": ..., "local": ...}) or ISO string."""
    raw = value.get("utc") if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def to_ugm3(parameter: str, value: float, units: Optional[str]) -> Optional[float]:
    """Normalise a concentration to µg/m³; None when the unit is unsupported."""
    unit = (units or "").strip().lower().replace("µ", "u").replace("μ", "u").replace("³", "3")
    if unit in {"ug/m3", "ugm3"}:
        return value
    factor = PPM_TO_UGM3.get(parameter)
    if factor and unit == "ppm":
        return value * factor
    if factor and unit == "ppb":
        return value * factor / 1000
    return None


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours(delta: timedelta) -> float:
    return delta.total_seconds() / 3600


@dataclass(frozen=True)
class OpenAQStation:
    id: int
    name: str
    locality: Optional[str]
    distance_km: float
    is_monitor: bool
    datetime_last: Optional[datetime]
    sensors: Dict[str, Tuple[int, str]]  # parameter -> (sensor id, units)
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @property
    def label(self) -> str:
        return f"{self.name} ({self.distance_km:.1f} km)" if math.isfinite(self.distance_km) else self.name


def parse_station(raw: Dict[str, Any], lat: float, lon: float) -> Optional[OpenAQStation]:
    """Parse an OpenAQ location; distance is measured from the analysis coordinates."""
    sensors: Dict[str, Tuple[int, str]] = {}
    for sensor in raw.get("sensors") or []:
        parameter = sensor.get("parameter") or {}
        key = parameter.get("name")
        if key not in POLLUTANTS or sensor.get("id") is None:
            continue
        units = parameter.get("units") or ""
        existing = sensors.get(key)
        # Prefer µg/m³ sensors when a station reports a gas in several units.
        if existing is None or (to_ugm3(key, 1.0, existing[1]) != 1.0 and to_ugm3(key, 1.0, units) == 1.0):
            sensors[key] = (int(sensor["id"]), units)
    if not sensors:
        return None

    coordinates = raw.get("coordinates") or {}
    station_lat, station_lon = coordinates.get("latitude"), coordinates.get("longitude")
    if station_lat is not None and station_lon is not None:
        distance_km = haversine_km(lat, lon, float(station_lat), float(station_lon))
    elif raw.get("distance") is not None:
        distance_km = float(raw["distance"]) / 1000
    else:
        distance_km = float("inf")
    return OpenAQStation(
        id=int(raw["id"]),
        name=raw.get("name") or f"OpenAQ location {raw['id']}",
        locality=raw.get("locality"),
        distance_km=distance_km,
        is_monitor=bool(raw.get("isMonitor")),
        datetime_last=parse_utc(raw.get("datetimeLast")),
        sensors=sensors,
        latitude=float(station_lat) if station_lat is not None else None,
        longitude=float(station_lon) if station_lon is not None else None,
    )


def station_score(station: OpenAQStation, now: datetime, max_age: timedelta) -> float:
    """Lower is better: distance plus penalties for stale data, low-cost hardware and missing pollutants."""
    fresh = station.datetime_last is not None and now - station.datetime_last <= max_age
    score = station.distance_km if math.isfinite(station.distance_km) else 1000.0
    if not fresh:
        score += STALE_PENALTY_KM
    if not station.is_monitor:
        score += LOW_COST_PENALTY_KM
    if "pm25" not in station.sensors:
        score += NO_PM25_PENALTY_KM
    score += MISSING_POLLUTANT_PENALTY_KM * (len(POLLUTANTS) - len(station.sensors))
    return score


class OpenAQClient:
    """Minimal stdlib HTTP client for the OpenAQ v3 API."""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self.base_url}{path}{query}",
            headers={"X-API-Key": self.api_key, "Accept": "application/json", "User-Agent": "EcoSentinel-AI/1.0"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            if exc.code in (401, 403):
                raise ProviderNotConfiguredError("OpenAQ rejected the API key. Check OPENAQ_API_KEY in backend/.env.")
            if exc.code == 429:
                raise DataSourceError("Air-quality provider temporarily unavailable (OpenAQ rate limit reached).")
            raise DataSourceError(f"Air-quality provider temporarily unavailable (OpenAQ HTTP {exc.code}).")
        except (URLError, socket.timeout, TimeoutError, ConnectionError):
            raise DataSourceError("Air-quality provider temporarily unavailable (could not reach OpenAQ).")
        except ValueError:
            raise DataSourceError("Air-quality provider temporarily unavailable (unreadable OpenAQ response).")


# --------------------------------------------------------------------------- OpenAQ provider


class OpenAQProvider:
    name = "OpenAQ v3"
    network = "OpenAQ"

    def __init__(
        self,
        api_key: Optional[str],
        client: Optional[Any] = None,
        radius_m: int = MAX_RADIUS_M,
        max_age_hours: float = 24.0,
        fill_max_age_hours: float = 96.0,
    ):
        self.client = client or (
            OpenAQClient(api_key, settings.openaq_base_url, settings.openaq_timeout_seconds) if api_key else None
        )
        self.radius_m = max(1, min(int(radius_m), MAX_RADIUS_M))
        self.max_age = timedelta(hours=max_age_hours)
        self.fill_max_age = max(self.max_age, timedelta(hours=fill_max_age_hours))
        self._lock = threading.Lock()
        self._networks: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._latest_cache: Dict[int, Tuple[float, Dict[Any, Dict[str, Any]]]] = {}
        self._baseline_cache: Dict[int, Tuple[float, Optional[float]]] = {}
        self._pm25_sensor: Dict[str, Tuple[int, str]] = {}

    def _require_client(self) -> Any:
        if self.client is None:
            raise ProviderNotConfiguredError(
                "OpenAQ API key is missing. Add OPENAQ_API_KEY to backend/.env or switch to Demo Mode."
            )
        return self.client

    @staticmethod
    def _key(location: LocationContext) -> str:
        """~1 km grid cell: nearby positions share one station lookup."""
        return f"{location.latitude:.2f},{location.longitude:.2f}"

    @staticmethod
    def _fresh(moment: Optional[datetime], now: datetime, window: timedelta) -> bool:
        return moment is not None and now - moment <= window

    # ---------------------------------------------------------------- stations

    def _network(self, location: LocationContext) -> Tuple[OpenAQStation, List[OpenAQStation]]:
        """Best suitable station plus the other nearby stations (by distance) for gap filling."""
        client = self._require_client()
        lat, lon = location.latitude, location.longitude
        key = self._key(location)
        with self._lock:
            cached = self._networks.get(key)
        if cached and time.monotonic() - cached[0] < STATION_CACHE_SECONDS:
            rows = cached[1]
        else:
            payload = client.get("/locations", {"coordinates": f"{lat:.4f},{lon:.4f}", "radius": self.radius_m, "limit": 100})
            rows = [row for row in payload.get("results") or [] if isinstance(row, dict) and not row.get("isMobile")]
            with self._lock:
                self._networks[key] = (time.monotonic(), rows)

        candidates = [station for station in (parse_station(row, lat, lon) for row in rows) if station]
        if not candidates:
            raise NoMonitoringDataError(
                f"No suitable nearby air-quality station found within {self.radius_m // 1000} km."
            )
        now = datetime.now(timezone.utc)
        ranked = sorted(candidates, key=lambda s: (station_score(s, now, self.max_age), s.distance_km))
        return ranked[0], sorted(ranked[1:], key=lambda s: s.distance_km)

    def nearest_station(self, location: LocationContext) -> OpenAQStation:
        return self._network(location)[0]

    def _latest(self, station_id: int) -> Dict[Any, Dict[str, Any]]:
        with self._lock:
            cached = self._latest_cache.get(station_id)
        if cached and time.monotonic() - cached[0] < LATEST_CACHE_SECONDS:
            return cached[1]
        payload = self._require_client().get(f"/locations/{station_id}/latest", {"limit": 100})
        by_sensor = {item.get("sensorsId"): item for item in payload.get("results") or []}
        with self._lock:
            self._latest_cache[station_id] = (time.monotonic(), by_sensor)
        return by_sensor

    @staticmethod
    def _read(station: OpenAQStation, key: str, latest: Dict[Any, Dict[str, Any]]) -> Tuple[Optional[float], Optional[datetime], Optional[str]]:
        sensor = station.sensors.get(key)
        if not sensor:
            return None, None, None
        sensor_id, units = sensor
        item = latest.get(sensor_id)
        if not item or item.get("value") is None:
            return None, None, None
        value = to_ugm3(key, float(item["value"]), units)
        if value is None:
            return None, None, f"{LABELS[key]} at {station.name} uses unsupported units '{units}'"
        if value < 0:
            return None, None, f"{LABELS[key]} at {station.name} returned an invalid negative value"
        return round_half_up(value, 1), parse_utc(item.get("datetime")), None

    # ---------------------------------------------------------------- readings

    def get_latest(self, location: LocationContext) -> AirQualityReading:
        primary, others = self._network(location)
        now = datetime.now(timezone.utc)
        stations = [primary, *others]
        found: Dict[str, Tuple[float, Optional[datetime], OpenAQStation]] = {}
        fetched: Dict[int, Dict[Any, Dict[str, Any]]] = {}
        notes: List[str] = []

        # Pass 1: fresh readings only. Pass 2: latest available within the fill window.
        windows = [self.max_age] if self.fill_max_age <= self.max_age else [self.max_age, self.fill_max_age]
        for window in windows:
            for station in stations:
                wanted = [key for key in POLLUTANTS if key not in found and key in station.sensors]
                if not wanted:
                    continue
                if station is not primary and not self._fresh(station.datetime_last, now, window):
                    continue
                if station.id not in fetched:
                    if len(fetched) >= MAX_LATEST_CALLS:
                        continue
                    try:
                        fetched[station.id] = self._latest(station.id)
                    except EcoSentinelError:
                        if station is primary:
                            raise
                        fetched[station.id] = {}
                for key in wanted:
                    value, moment, problem = self._read(station, key, fetched[station.id])
                    if problem and problem not in notes:
                        notes.append(problem)
                    if value is not None and (moment is None or now - moment <= window):
                        found[key] = (value, moment, station)
                if len(found) == len(POLLUTANTS):
                    break
            if len(found) == len(POLLUTANTS):
                break

        if not found:
            raise SensorDataUnavailableError(
                "No recent PM2.5, PM10, NO₂ or O₃ readings are available from nearby OpenAQ stations."
            )

        lead_key = "pm25" if "pm25" in found else next(iter(found))
        lead_moment, lead = found[lead_key][1], found[lead_key][2]
        sources: List[Tuple[str, str]] = []
        delayed: List[str] = []
        for key in POLLUTANTS:
            if key not in found:
                if key in primary.sensors:
                    notes.append(f"{LABELS[key]} at {primary.name} is out of date and was ignored")
                continue
            _, moment, station = found[key]
            sources.append((key, station.label))
            if moment is not None and now - moment > self.max_age:
                delayed.append(key)
                notes.append(f"{LABELS[key]} uses the latest available reading from {station.name} ({_hours(now - moment):.0f} h old)")

        if "pm25" in found and "pm25" in found["pm25"][2].sensors:
            with self._lock:
                self._pm25_sensor[self._key(location)] = found["pm25"][2].sensors["pm25"]

        age_minutes = int((now - lead_moment).total_seconds() // 60) if lead_moment is not None else None
        moments = [m for _, m, _ in found.values() if m is not None]
        return AirQualityReading(
            station_id=f"OPENAQ-{lead.id}",
            station_name=lead.name,
            pm25=found.get("pm25", (None,))[0],
            pm10=found.get("pm10", (None,))[0],
            no2=found.get("no2", (None,))[0],
            o3=found.get("o3", (None,))[0],
            observed_at=lead_moment or (max(moments) if moments else now),
            provider=self.name,
            is_mock=False,
            distance_km=round_half_up(lead.distance_km, 1) if math.isfinite(lead.distance_km) else None,
            reference_grade=lead.is_monitor,
            notes=tuple(notes),
            source_url=f"https://explore.openaq.org/locations/{lead.id}",
            sources=tuple(sources),
            delayed=tuple(delayed),
            station_latitude=lead.latitude,
            station_longitude=lead.longitude,
            data_age_minutes=max(0, age_minutes) if age_minutes is not None else None,
            freshness="live" if age_minutes is not None and age_minutes <= LIVE_MAX_AGE_MINUTES else "delayed",
        )

    def get_pm25_baseline(self, location: LocationContext) -> Optional[float]:
        """Mean hourly PM2.5 over the previous 24 h (excluding the current hour); None if unavailable."""
        try:
            client = self._require_client()
            with self._lock:
                sensor = self._pm25_sensor.get(self._key(location))
            if sensor is None:
                sensor = self.nearest_station(location).sensors.get("pm25")
        except EcoSentinelError:
            return None
        if not sensor:
            return None

        sensor_id, units = sensor
        with self._lock:
            cached = self._baseline_cache.get(sensor_id)
        if cached and time.monotonic() - cached[0] < BASELINE_CACHE_SECONDS:
            return cached[1]

        now = datetime.now(timezone.utc)
        params = {"datetime_from": _iso(now - timedelta(hours=25)), "datetime_to": _iso(now), "limit": 48}
        try:
            payload = client.get(f"/sensors/{sensor_id}/hours", params)
        except EcoSentinelError:
            return None

        points: List[Tuple[datetime, float]] = []
        for row in payload.get("results") or []:
            started = parse_utc((row.get("period") or {}).get("datetimeFrom"))
            if row.get("value") is None or started is None:
                continue
            value = to_ugm3("pm25", float(row["value"]), units)
            if value is not None and value >= 0:
                points.append((started, value))
        points.sort(key=lambda point: point[0])
        history = [value for _, value in points[:-1]]
        baseline = sum(history) / len(history) if len(history) >= 6 else None
        with self._lock:
            self._baseline_cache[sensor_id] = (time.monotonic(), baseline)
        return baseline


# --------------------------------------------------------------------------- factory

_openaq_lock = threading.Lock()
_openaq_provider: Optional[OpenAQProvider] = None


def _shared_openaq_provider() -> OpenAQProvider:
    """One provider per process so station and reading caches survive across requests."""
    global _openaq_provider
    with _openaq_lock:
        if _openaq_provider is None:
            _openaq_provider = OpenAQProvider(
                settings.openaq_api_key,
                radius_m=settings.openaq_radius_m,
                max_age_hours=settings.openaq_max_age_hours,
                fill_max_age_hours=settings.openaq_fill_max_age_hours,
            )
        return _openaq_provider


def resolve_air_provider_mode() -> str:
    mode = settings.air_provider.strip().lower()
    if mode == "auto":
        return "openaq" if settings.openaq_api_key else "mock"
    return mode


def get_air_provider(demo_mode: bool) -> AirQualityProvider:
    if demo_mode:
        return MockAirQualityProvider()
    mode = resolve_air_provider_mode()
    if mode == "mock":
        return MockAirQualityProvider()
    if mode == "openaq":
        return _shared_openaq_provider()
    raise ProviderNotConfiguredError(f"Unknown air provider '{settings.air_provider}'. Use auto, openaq or mock.")
