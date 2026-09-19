"""Location-aware water source resolution for the Water Quality Agent.

    LocationContext (latitude, longitude)
      -> WaterQualityAgent
      -> LocationAwareWaterProvider — priority:
           1. nearest EcoSentinel IoT sensor         ESP32 -> Firebase RTDB  (/sensors/{id}/latest)
                                                     ESP32 -> MQTT bridge / POST /api/sensors/water/{id}/readings
           2. nearest configured monitoring station  JSON endpoint per station
           3. latest observation in a water-quality dataset (ECOSENTINEL_WATER_DATASET_PATH)
           4. demo data — Demo Mode only
      -> WaterSensorReading (source type, distance, data age)

Sources live in shared/water_sensors.json. Nothing here is specific to one city, and
Nominatim is never used as a water-quality source.
"""

import json
import socket
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

try:
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from config import settings
from core.errors import DataSourceError, EcoSentinelError, ProviderNotConfiguredError, SensorDataUnavailableError
from core.geo import haversine_km, offset_point
from core.risk import round_half_up
from data.locations import find_profile, nearest_profile
from schemas import LocationContext
from services.location_service import DEMO_SITE_RADIUS_KM

NO_SENSOR_MESSAGE = "No nearby live water sensor available."
HISTORICAL_MESSAGE = "Live water sensor unavailable. Showing latest available water observation."
SOURCE_LABELS = {
    "live_iot": "EcoSentinel Water Sensor",
    "monitoring_station": "Configured water monitoring station",
    "historical": "Water-quality dataset",
    "demo": "EcoSentinel Demo Data",
}


@dataclass(frozen=True)
class WaterSensorReading:
    sensor_id: str
    sensor_name: str
    status: str  # online | degraded | offline
    ph: Optional[float]
    turbidity: Optional[float]
    temperature: Optional[float]
    observed_at: datetime
    provider: str
    is_mock: bool
    tds: Optional[float] = None
    source_type: str = "demo"  # live_iot | monitoring_station | historical | demo
    source_label: str = SOURCE_LABELS["demo"]
    distance_km: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    data_age_minutes: Optional[int] = None
    notes: Tuple[str, ...] = ()


class WaterSensorProvider(Protocol):
    name: str
    network: str

    def get_latest(self, location: LocationContext) -> WaterSensorReading: ...


# --------------------------------------------------------------------------- registry


@dataclass(frozen=True)
class WaterSource:
    sensor_id: str
    name: str
    kind: str  # iot | monitoring_station
    provider: str  # demo | mqtt | firebase | http_json
    latitude: float
    longitude: float
    parameters: Tuple[str, ...] = ()
    enabled: bool = True
    url: Optional[str] = None
    profile_id: Optional[str] = None


def parse_sources(payload: Any) -> List[WaterSource]:
    sources: List[WaterSource] = []
    for raw in (payload or {}).get("sensors") or []:
        try:
            sources.append(
                WaterSource(
                    sensor_id=str(raw["sensorId"]),
                    name=str(raw.get("name") or raw["sensorId"]),
                    kind=str(raw.get("kind", "iot")),
                    provider=str(raw.get("provider", "demo")),
                    latitude=float(raw["latitude"]),
                    longitude=float(raw["longitude"]),
                    parameters=tuple(raw.get("parameters") or ()),
                    enabled=bool(raw.get("enabled", True)),
                    url=raw.get("url") or None,
                    profile_id=raw.get("profileId"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return sources


@lru_cache(maxsize=4)
def load_registry(path: str) -> Tuple[WaterSource, ...]:
    try:
        return tuple(parse_sources(json.loads(Path(path).read_text(encoding="utf-8"))))
    except (OSError, ValueError):
        return ()


class WaterSourceRegistry:
    def __init__(self, sources: Iterable[WaterSource]):
        self.sources = tuple(sources)

    def find(self, sensor_id: str) -> Optional[WaterSource]:
        return next((s for s in self.sources if s.sensor_id == sensor_id), None)

    def nearest(
        self,
        lat: float,
        lon: float,
        kinds: Set[str],
        providers: Optional[Set[str]] = None,
        exclude_providers: Set[str] = frozenset(),  # type: ignore[assignment]
        max_km: Optional[float] = None,
    ) -> List[Tuple[WaterSource, float]]:
        hits = []
        for source in self.sources:
            if not source.enabled or source.kind not in kinds:
                continue
            if providers is not None and source.provider not in providers:
                continue
            if source.provider in exclude_providers:
                continue
            distance = haversine_km(lat, lon, source.latitude, source.longitude)
            if max_km is not None and distance > max_km:
                continue
            hits.append((source, distance))
        return sorted(hits, key=lambda hit: hit[1])


# --------------------------------------------------------------------------- telemetry readers


def parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value / 1000 if value > 1e12 else value, tz=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def payload_time(payload: Dict[str, Any]) -> Optional[datetime]:
    for key in ("observedAt", "observed_at", "timestamp", "ts"):
        if key in payload:
            return parse_time(payload[key])
    return None


def _number(payload: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return None


def fetch_json(url: str, label: str, timeout: float = 5.0, opener: Callable[..., Any] = urlopen) -> Optional[Dict[str, Any]]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "EcoSentinel-AI/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise DataSourceError(f"{label} request failed (HTTP {exc.code}).")
    except (URLError, socket.timeout, TimeoutError, ConnectionError):
        raise DataSourceError(f"Could not reach {label}.")
    except ValueError:
        raise DataSourceError(f"{label} returned unreadable data.")
    return data if isinstance(data, dict) else None


class LatestReadingCache:
    """Thread-safe latest reading per sensor, filled by an MQTT bridge or the HTTP ingest endpoint."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._readings: Dict[str, Dict[str, Any]] = {}

    def ingest(self, sensor_id: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            self._readings[sensor_id] = dict(payload)

    def get(self, sensor_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            reading = self._readings.get(sensor_id)
            return dict(reading) if reading else None

    def clear(self) -> None:
        with self._lock:
            self._readings.clear()


class PushReader:
    """ESP32 -> MQTT (via bridge) or ESP32 -> HTTP push; readings arrive in LatestReadingCache."""

    def __init__(self, cache: LatestReadingCache):
        self.cache = cache

    def read(self, source: WaterSource) -> Optional[Dict[str, Any]]:
        return self.cache.get(source.sensor_id)


class FirebaseReader:
    """ESP32 -> Firebase Realtime Database: GET {FIREBASE_DB_URL}/sensors/{sensorId}/latest.json"""

    def __init__(self, db_url: str, auth_token: Optional[str] = None, timeout: float = 5.0, opener: Callable[..., Any] = urlopen):
        self.db_url = db_url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = timeout
        self.opener = opener

    def read(self, source: WaterSource) -> Optional[Dict[str, Any]]:
        url = f"{self.db_url}/sensors/{quote(source.sensor_id)}/latest.json"
        if self.auth_token:
            url += f"?{urlencode({'auth': self.auth_token})}"
        return fetch_json(url, "Firebase telemetry", self.timeout, self.opener)


class HttpJsonReader:
    """Configured monitoring station exposing its latest reading as JSON."""

    def __init__(self, timeout: float = 5.0, opener: Callable[..., Any] = urlopen):
        self.timeout = timeout
        self.opener = opener

    def read(self, source: WaterSource) -> Optional[Dict[str, Any]]:
        return fetch_json(source.url, "Monitoring station", self.timeout, self.opener) if source.url else None


# --------------------------------------------------------------------------- historical dataset


@dataclass(frozen=True)
class WaterObservation:
    site_id: str
    name: str
    latitude: float
    longitude: float
    observed_at: datetime
    ph: Optional[float]
    turbidity: Optional[float]
    temperature: Optional[float]
    tds: Optional[float]
    source: str


def parse_dataset(payload: Any) -> List[WaterObservation]:
    observations: List[WaterObservation] = []
    for raw in (payload or {}).get("observations") or []:
        try:
            observed = parse_time(raw.get("observedAt"))
            if observed is None:
                continue
            observations.append(
                WaterObservation(
                    site_id=str(raw["siteId"]),
                    name=str(raw.get("name") or raw["siteId"]),
                    latitude=float(raw["latitude"]),
                    longitude=float(raw["longitude"]),
                    observed_at=observed,
                    ph=_number(raw, "ph"),
                    turbidity=_number(raw, "turbidity"),
                    temperature=_number(raw, "temperature"),
                    tds=_number(raw, "tds"),
                    source=str(raw.get("source") or "Water-quality dataset"),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return observations


@lru_cache(maxsize=4)
def load_dataset(path: str) -> Tuple[WaterObservation, ...]:
    try:
        return tuple(parse_dataset(json.loads(Path(path).read_text(encoding="utf-8"))))
    except (OSError, ValueError):
        return ()


class WaterDataset:
    def __init__(self, observations: Iterable[WaterObservation]):
        self.observations = tuple(observations)

    def nearest(self, lat: float, lon: float, max_km: float) -> Optional[Tuple[WaterObservation, float]]:
        hits = [
            (obs, haversine_km(lat, lon, obs.latitude, obs.longitude))
            for obs in self.observations
        ]
        hits = [hit for hit in hits if hit[1] <= max_km]
        if not hits:
            return None
        # Nearest site first; for the same site the most recent observation wins.
        return min(hits, key=lambda hit: (round(hit[1], 3), -hit[0].observed_at.timestamp()))


# --------------------------------------------------------------------------- resolver


def _age_minutes(now: datetime, observed: datetime) -> int:
    return max(0, int((now - observed).total_seconds() // 60))


class LocationAwareWaterProvider:
    def __init__(
        self,
        registry: WaterSourceRegistry,
        readers: Optional[Dict[str, Any]] = None,
        dataset: Optional[WaterDataset] = None,
        demo_mode: bool = False,
        sensor_radius_km: float = 10.0,
        dataset_radius_km: float = 25.0,
        max_age_minutes: float = 60.0,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.registry = registry
        self.readers = readers or {}
        self.dataset = dataset
        self.demo_mode = demo_mode
        self.sensor_radius_km = sensor_radius_km
        self.dataset_radius_km = dataset_radius_km
        self.max_age_minutes = max_age_minutes
        self.clock = clock
        self.name = "Demo IoT sensor (ESP32 profile)" if demo_mode else "Water resolver (IoT → station → dataset)"
        self.network = "demo water sensors" if demo_mode else "water sensors and monitoring stations"

    def get_latest(self, location: LocationContext) -> WaterSensorReading:
        now = self.clock()
        if self.demo_mode:
            return self._demo(location, now)

        notes: List[str] = []
        for kind, source_type in (("iot", "live_iot"), ("monitoring_station", "monitoring_station")):
            nearby = self.registry.nearest(
                location.latitude, location.longitude, kinds={kind}, exclude_providers={"demo"}, max_km=self.sensor_radius_km
            )
            for source, distance in nearby:
                reader = self.readers.get(source.provider)
                if reader is None:
                    notes.append(f"{source.name}: {source.provider} provider is not configured")
                    continue
                try:
                    payload = reader.read(source)
                except EcoSentinelError as exc:
                    notes.append(f"{source.name}: {exc.message}")
                    continue
                if not payload:
                    notes.append(f"{source.name}: no telemetry received yet")
                    continue
                observed = payload_time(payload)
                if observed is None or _age_minutes(now, observed) > self.max_age_minutes:
                    notes.append(f"{source.name}: latest reading is older than {self.max_age_minutes:.0f} min")
                    continue
                return WaterSensorReading(
                    sensor_id=source.sensor_id,
                    sensor_name=source.name,
                    status="online",
                    ph=_number(payload, "ph"),
                    turbidity=_number(payload, "turbidity", "turbidity_ntu"),
                    temperature=_number(payload, "temperature", "temperature_c", "temp"),
                    tds=_number(payload, "tds", "tds_ppm", "tds_mg_l"),
                    observed_at=observed,
                    provider=f"{SOURCE_LABELS[source_type]} ({source.provider})",
                    is_mock=False,
                    source_type=source_type,
                    source_label=SOURCE_LABELS[source_type],
                    distance_km=round_half_up(distance, 2),
                    latitude=source.latitude,
                    longitude=source.longitude,
                    data_age_minutes=_age_minutes(now, observed),
                    notes=tuple(notes),
                )

        if self.dataset is not None:
            hit = self.dataset.nearest(location.latitude, location.longitude, self.dataset_radius_km)
            if hit is not None:
                obs, distance = hit
                return WaterSensorReading(
                    sensor_id=obs.site_id,
                    sensor_name=obs.name,
                    status="offline",
                    ph=obs.ph,
                    turbidity=obs.turbidity,
                    temperature=obs.temperature,
                    tds=obs.tds,
                    observed_at=obs.observed_at,
                    provider=f"{SOURCE_LABELS['historical']} · {obs.source}",
                    is_mock=False,
                    source_type="historical",
                    source_label=f"{SOURCE_LABELS['historical']} · {obs.source}",
                    distance_km=round_half_up(distance, 2),
                    latitude=obs.latitude,
                    longitude=obs.longitude,
                    data_age_minutes=_age_minutes(now, obs.observed_at),
                    notes=(HISTORICAL_MESSAGE, *notes),
                )

        raise SensorDataUnavailableError(NO_SENSOR_MESSAGE)

    def _demo(self, location: LocationContext, now: datetime) -> WaterSensorReading:
        hits = self.registry.nearest(
            location.latitude, location.longitude, kinds={"iot", "monitoring_station"}, providers={"demo"}, max_km=DEMO_SITE_RADIUS_KM
        )
        profile = find_profile(hits[0][0].profile_id) if hits and hits[0][0].profile_id else None
        if hits and profile:
            source, distance = hits[0]
            sensor_id, name, lat, lon = source.sensor_id, source.name, source.latitude, source.longitude
        else:
            profile, _ = nearest_profile(location.latitude, location.longitude)
            lat, lon = offset_point(location.latitude, location.longitude, -1.1, 1.4)
            distance = haversine_km(location.latitude, location.longitude, lat, lon)
            sensor_id, name = "DEMO-WATER", "Simulated water sensor (demo)"

        water = profile.get("water") or {}
        if not water or water.get("status") == "offline":
            raise SensorDataUnavailableError(f"Demo water sensor {sensor_id} is offline — no telemetry received.")
        return WaterSensorReading(
            sensor_id=sensor_id,
            sensor_name=name,
            status=water.get("status", "online"),
            ph=water.get("ph"),
            turbidity=water.get("turbidity"),
            temperature=water.get("temperature"),
            observed_at=now,
            provider=self.name,
            is_mock=True,
            source_type="demo",
            source_label=SOURCE_LABELS["demo"],
            distance_km=round_half_up(distance, 2),
            latitude=lat,
            longitude=lon,
            data_age_minutes=0,
        )


# --------------------------------------------------------------------------- factory

reading_cache = LatestReadingCache()


def get_water_provider(demo_mode: bool) -> WaterSensorProvider:
    registry = WaterSourceRegistry(load_registry(settings.water_registry_path))
    common = dict(
        sensor_radius_km=settings.water_sensor_radius_km,
        dataset_radius_km=settings.water_dataset_radius_km,
        max_age_minutes=settings.water_max_age_minutes,
    )
    mode = settings.water_provider.strip().lower()
    if demo_mode or mode == "mock":
        return LocationAwareWaterProvider(registry, demo_mode=True, **common)
    if mode != "auto":
        raise ProviderNotConfiguredError(f"Unknown water provider '{settings.water_provider}'. Use auto or mock.")

    readers: Dict[str, Any] = {"mqtt": PushReader(reading_cache), "http_json": HttpJsonReader()}
    if settings.firebase_db_url:
        readers["firebase"] = FirebaseReader(settings.firebase_db_url, settings.firebase_auth_token)
    dataset = WaterDataset(load_dataset(settings.water_dataset_path)) if settings.water_dataset_path else None
    return LocationAwareWaterProvider(registry, readers, dataset, demo_mode=False, **common)
