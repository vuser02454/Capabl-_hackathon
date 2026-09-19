"""Nearby water bodies from OpenStreetMap, via the Overpass API.

Why this exists
---------------
Reverse geocoding answers "what is the address here?" and only mentions a water feature when the
clicked point happens to sit on one. Overpass answers the question a water report actually needs:
*which named water bodies are near this point, and how far away is each?* That is what turns
"12.93450, 77.67450" into "Bellandur Lake, 180 m away".

Scope
-----
GEOGRAPHIC CONTEXT ONLY. Overpass returns OSM geometry and tags — names, types, areas. It carries
no water-quality information whatsoever, and nothing here ever produces a measurement or a risk
score. A lake being named does not make it clean or dirty.

Usage policy (https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)
------------------------------------------------------------------------------
Overpass is donated infrastructure with no API key and real limits. This client:
- sends an identifying User-Agent
- serialises requests and enforces a minimum interval between them
- caches by position, so panning a few metres never re-queries
- caps the search radius and the result count
- sets an explicit server-side [timeout:] so a runaway query is dropped by the server too

Every failure degrades to an empty result with a reason, never an exception into an agent.
"""

import json
import socket
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings
from core.errors import InvalidLocationError
from core.geo import haversine_km, valid_coordinates

#: OSM tag -> (human label, whether it is a flowing waterway).
WATER_KINDS: Dict[str, Tuple[str, bool]] = {
    "lake": ("Lake", False),
    "pond": ("Pond", False),
    "reservoir": ("Reservoir", False),
    "basin": ("Basin", False),
    "lagoon": ("Lagoon", False),
    "oxbow": ("Oxbow lake", False),
    "wastewater": ("Wastewater basin", False),
    "river": ("River", True),
    "stream": ("Stream", True),
    "canal": ("Canal", True),
    "drain": ("Storm drain", True),
    "ditch": ("Ditch", True),
    "riverbank": ("Riverbank", True),
}

UNNAMED = "Unnamed water body"


@dataclass(frozen=True)
class WaterFeature:
    """One OSM water feature near the query point."""

    osm_id: str
    name: Optional[str]
    kind: str            # raw OSM tag value, e.g. "lake", "drain"
    label: str           # human label, e.g. "Lake", "Storm drain"
    flowing: bool
    latitude: float
    longitude: float
    distance_km: float

    @property
    def display_name(self) -> str:
        return self.name or UNNAMED

    def as_dict(self) -> Dict[str, Any]:
        return {
            "osmId": self.osm_id,
            "name": self.name,
            "kind": self.kind,
            "label": self.label,
            "flowing": self.flowing,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "distanceKm": round(self.distance_km, 3),
        }


class OverpassUnavailable(Exception):
    """Overpass could not answer. Callers degrade to "no nearby water bodies known"."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def build_query(lat: float, lon: float, radius_m: int, timeout_s: int) -> str:
    """Overpass QL for water areas and waterways within `radius_m` of a point.

    `out center` collapses ways/relations to a single representative coordinate, which is all a
    distance calculation needs and is dramatically cheaper than fetching full geometry.
    """
    around = f"(around:{radius_m},{lat:.6f},{lon:.6f})"
    return (
        f"[out:json][timeout:{timeout_s}];"
        "("
        f'node["natural"="water"]{around};'
        f'way["natural"="water"]{around};'
        f'relation["natural"="water"]{around};'
        f'way["waterway"~"^(river|stream|canal|drain|ditch|riverbank)$"]{around};'
        f'relation["waterway"~"^(river|stream|canal|drain|riverbank)$"]{around};'
        f'way["landuse"~"^(reservoir|basin)$"]{around};'
        ");"
        "out center tags;"
    )


def _kind_of(tags: Dict[str, Any]) -> Optional[str]:
    """The most specific water tag on an element, or None when it is not water."""
    waterway = tags.get("waterway")
    if isinstance(waterway, str) and waterway in WATER_KINDS:
        return waterway
    water = tags.get("water")
    if isinstance(water, str) and water in WATER_KINDS:
        return water
    landuse = tags.get("landuse")
    if isinstance(landuse, str) and landuse in WATER_KINDS:
        return landuse
    if tags.get("natural") == "water":
        return "lake"  # natural=water with no subtype: a standing water body
    return None


def parse_elements(payload: Any, lat: float, lon: float) -> List[WaterFeature]:
    """Normalise an Overpass response into distance-sorted WaterFeatures."""
    if not isinstance(payload, dict):
        raise OverpassUnavailable("Overpass returned an unreadable response.")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []

    features: List[WaterFeature] = []
    seen: set = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        kind = _kind_of(tags)
        if kind is None:
            continue

        centre = element.get("center") if isinstance(element.get("center"), dict) else element
        element_lat, element_lon = centre.get("lat"), centre.get("lon")
        if not valid_coordinates(element_lat, element_lon):
            continue

        osm_id = f"{element.get('type', 'element')}/{element.get('id')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)

        name = tags.get("name")
        label, flowing = WATER_KINDS[kind]
        features.append(
            WaterFeature(
                osm_id=osm_id,
                name=name.strip() if isinstance(name, str) and name.strip() else None,
                kind=kind,
                label=label,
                flowing=flowing,
                latitude=float(element_lat),
                longitude=float(element_lon),
                distance_km=haversine_km(lat, lon, float(element_lat), float(element_lon)),
            )
        )

    # Named features first at equal distance: "Bellandur Lake" is more use than "Unnamed water body".
    features.sort(key=lambda f: (round(f.distance_km, 3), f.name is None))
    return features


def _first_named(features: List[WaterFeature]) -> Optional[WaterFeature]:
    """Closest feature carrying a name, or None when nothing nearby is named."""
    return next((feature for feature in features if feature.name), None)


class OverpassThrottle:
    """Minimum interval between Overpass requests, shareable across services.

    Overpass rate-limits per client, not per code path, so two services each keeping their own
    one-per-second budget spend two slots per second between them. The factories below hand both
    services the SAME instance, which is what makes the shared budget real rather than aspirational
    — an analysis that wants water bodies and geographic context spends one slot at a time.

    Constructing a service without one gives it a private throttle, which is what tests want.
    """

    def __init__(
        self,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.min_interval_s = min_interval_s
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._last_request: Optional[float] = None

    def wait(self) -> None:
        with self._lock:
            if self._last_request is not None:
                delay = self.min_interval_s - (self.clock() - self._last_request)
                if delay > 0:
                    self.sleep(delay)
            self._last_request = self.clock()


class OverpassClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        timeout: float = 25.0,
        opener: Callable[..., Any] = urlopen,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.timeout = timeout
        self.opener = opener

    def query(self, query: str) -> Dict[str, Any]:
        # POST: an Overpass QL query is too long for a URL, and keeps coordinates out of any log.
        request = Request(
            self.base_url,
            data=urlencode({"data": query}).encode("utf-8"),
            headers={
                "User-Agent": self.user_agent,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            # 429/504 are Overpass's documented "you are over quota / too busy" responses.
            if exc.code in (429, 504):
                raise OverpassUnavailable("OpenStreetMap's Overpass service is rate-limiting or busy. Try again shortly.")
            raise OverpassUnavailable(f"Overpass returned HTTP {exc.code}.")
        except (URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            raise OverpassUnavailable(f"Could not reach Overpass ({exc.__class__.__name__}).")
        except ValueError:
            raise OverpassUnavailable("Overpass returned malformed JSON.")


class NearbyWaterService:
    """Distance-aware cache + throttle in front of an Overpass client.

    Mirrors ReverseGeocodingService deliberately: same caching shape, same courtesy to a free
    shared service, so there is one pattern to understand for both OSM APIs.
    """

    def __init__(
        self,
        client: Any,
        cache_distance_m: float = 250.0,
        cache_size: int = 64,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        throttle: Optional[OverpassThrottle] = None,
    ):
        self.client = client
        self.cache_distance_km = cache_distance_m / 1000
        self.cache_size = cache_size
        self.throttle = throttle or OverpassThrottle(min_interval_s, clock, sleep)
        self._lock = threading.Lock()
        self._entries: List[Tuple[float, float, int, List[WaterFeature]]] = []

    def _lookup(self, lat: float, lon: float, radius_m: int) -> Optional[List[WaterFeature]]:
        for index, (cached_lat, cached_lon, cached_radius, features) in enumerate(self._entries):
            # Only reuse a cache entry queried at the SAME radius: a 500 m answer is not a valid
            # answer for a 2 km question.
            if cached_radius == radius_m and haversine_km(lat, lon, cached_lat, cached_lon) <= self.cache_distance_km:
                self._entries.append(self._entries.pop(index))
                return features
        return None

    def nearby(
        self, lat: float, lon: float, radius_m: Optional[int] = None, limit: Optional[int] = None
    ) -> Tuple[List[WaterFeature], Optional[WaterFeature], bool]:
        """Return (features, nearest_named, cached).

        `nearest_named` is chosen from the FULL result set, never from the truncated list. Urban
        water is mapped as a dense mesh of unnamed drain and stream segments, so the named lake a
        report actually needs to cite routinely sits far down the distance ordering — around
        Bellandur Lake it is the 39th result. Picking it after truncation would silently return
        "no named water body" for a point a few hundred metres from a famous lake.

        Raises OverpassUnavailable when Overpass cannot answer.
        """
        if not valid_coordinates(lat, lon):
            raise InvalidLocationError("Location coordinates are invalid.")
        radius = max(50, min(int(radius_m or settings.overpass_radius_m), settings.overpass_max_radius_m))
        count = max(1, min(int(limit or settings.overpass_max_results), 50))

        with self._lock:
            hit = self._lookup(lat, lon, radius)
            if hit is not None:
                return hit[:count], _first_named(hit), True
            self.throttle.wait()

            query = build_query(lat, lon, radius, int(settings.overpass_timeout_seconds))
            features = parse_elements(self.client.query(query), lat, lon)
            # The cache holds the FULL list, so a later call with a bigger limit is still a hit.
            self._entries.append((lat, lon, radius, features))
            del self._entries[: max(0, len(self._entries) - self.cache_size)]
            return features[:count], _first_named(features), False


#: One Overpass budget for the whole process, shared by both services below.
_shared_throttle = OverpassThrottle()

_service_lock = threading.Lock()
_service: Optional[NearbyWaterService] = None


def get_nearby_water_service() -> NearbyWaterService:
    global _service
    with _service_lock:
        if _service is None:
            _service = NearbyWaterService(
                OverpassClient(
                    settings.overpass_base_url,
                    settings.nominatim_user_agent,  # one identity for both OSM services
                    timeout=settings.overpass_timeout_seconds + 5,
                ),
                cache_distance_m=settings.overpass_cache_distance_m,
                throttle=_shared_throttle,
            )
        return _service


def nearest_water_body(lat: float, lon: float) -> Optional[WaterFeature]:
    """Closest NAMED water body, or None. Never raises — callers treat absence as "unknown".

    Honours `overpass_enabled`, so switching the integration off genuinely stops every outbound
    request, including the report-enrichment path that does not go through the endpoint.
    """
    if not settings.overpass_enabled:
        return None
    try:
        features, named, _cached = get_nearby_water_service().nearby(lat, lon)
    except (OverpassUnavailable, InvalidLocationError):
        return None
    return named or (features[0] if features else None)


# =============================================================================================
# Geographic context: industrial / waste / road features near the analysis point
# =============================================================================================
#
# CONTEXT ONLY — READ THIS BEFORE USING THE OUTPUT.
#
# Everything below reports what OpenStreetMap contributors have MAPPED near a point. A mapped
# factory is not a measurement, an emission, or evidence of pollution: it means somebody drew a
# polygon and tagged it `landuse=industrial`. Presence tells you nothing about whether that site
# is operating, compliant, or emitting anything at all, and absence tells you nothing either —
# OSM coverage is uneven.
#
# So this data may be used to say:
#     "Industrial activity is mapped near the analysis location."
# and, alongside an actual measurement from a measuring provider:
#     "Elevated particulate observations alongside nearby mapped industrial features warrant
#      further investigation."
#
# It may NEVER be used to say "this factory is causing the pollution", and it never reaches the
# Coordinator or the risk score — see agents/langgraph_orchestrator.py, where the enrichment node
# writes to the analysis result only, never into CoordinatorInput.

#: Feature category -> (Overpass selectors, human label for the category).
#: Each selector is a full OSM tag filter; `{a}` is substituted with the `(around:...)` clause.
CONTEXT_SELECTORS: Dict[str, Tuple[Tuple[str, ...], str]] = {
    "industrial": (
        (
            'way["landuse"="industrial"]{a}',
            'relation["landuse"="industrial"]{a}',
            'way["man_made"="works"]{a}',
            'node["man_made"="works"]{a}',
        ),
        "Industrial",
    ),
    "waste": (
        (
            'way["landuse"="landfill"]{a}',
            'relation["landuse"="landfill"]{a}',
            'node["amenity"="waste_transfer_station"]{a}',
            'way["amenity"="waste_transfer_station"]{a}',
            'node["amenity"="waste_disposal"]{a}',
            'node["amenity"="recycling"]["recycling_type"="centre"]{a}',
            'way["amenity"="recycling"]["recycling_type"="centre"]{a}',
        ),
        "Waste facility",
    ),
    "waterway": (
        (
            'way["natural"="water"]{a}',
            'way["waterway"~"^(river|stream|canal|drain)$"]{a}',
        ),
        "Waterway",
    ),
    # Major roads only. Every residential street would swamp the result set while saying nothing:
    # traffic is a plausible emission source at trunk/primary scale, not on a side lane.
    "road": (
        (
            'way["highway"~"^(motorway|trunk|primary)$"]{a}',
        ),
        "Major road",
    ),
}

#: Human label for the specific OSM tag value behind a feature.
CONTEXT_KIND_LABELS: Dict[str, str] = {
    "industrial": "Industrial area",
    "works": "Factory / works",
    "landfill": "Landfill",
    "waste_transfer_station": "Waste transfer station",
    "waste_disposal": "Waste disposal point",
    "recycling": "Recycling centre",
    "water": "Water body",
    "river": "River",
    "stream": "Stream",
    "canal": "Canal",
    "drain": "Storm drain",
    "motorway": "Motorway",
    "trunk": "Trunk road",
    "primary": "Primary road",
}


@dataclass(frozen=True)
class ContextFeature:
    """One mapped OSM feature near the analysis point. Geography, never a measurement."""

    osm_id: str
    name: Optional[str]
    category: str   # industrial | waste | waterway | road
    kind: str       # raw OSM tag value, e.g. "landfill"
    label: str      # human label, e.g. "Landfill"
    latitude: float
    longitude: float
    distance_km: float

    def as_dict(self) -> Dict[str, Any]:
        return {
            "osmId": self.osm_id,
            "name": self.name,
            "category": self.category,
            "kind": self.kind,
            "label": self.label,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "distanceKm": round(self.distance_km, 3),
        }


def build_context_query(lat: float, lon: float, radius_m: int, timeout_s: int) -> str:
    """Overpass QL for the contextual feature categories within `radius_m` of a point.

    One query for all four categories rather than four queries: Overpass is donated
    infrastructure, and a single union costs the server far less than four round-trips.
    """
    around = f"(around:{radius_m},{lat:.6f},{lon:.6f})"
    parts = [
        selector.format(a=around) + ";"
        for selectors, _label in CONTEXT_SELECTORS.values()
        for selector in selectors
    ]
    return f"[out:json][timeout:{timeout_s}];(" + "".join(parts) + ");out center tags;"


def _categorise(tags: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """(category, raw kind) for an element, or None when it matches no context category."""
    landuse, man_made = tags.get("landuse"), tags.get("man_made")
    amenity, waterway, highway = tags.get("amenity"), tags.get("waterway"), tags.get("highway")

    if landuse == "industrial":
        return "industrial", "industrial"
    if man_made == "works":
        return "industrial", "works"
    if landuse == "landfill":
        return "waste", "landfill"
    if amenity in {"waste_transfer_station", "waste_disposal"}:
        return "waste", str(amenity)
    if amenity == "recycling":
        return "waste", "recycling"
    if isinstance(waterway, str) and waterway in {"river", "stream", "canal", "drain"}:
        return "waterway", waterway
    if tags.get("natural") == "water":
        return "waterway", "water"
    if isinstance(highway, str) and highway in {"motorway", "trunk", "primary"}:
        return "road", highway
    return None


def parse_context_elements(payload: Any, lat: float, lon: float) -> List[ContextFeature]:
    """Normalise an Overpass response into distance-sorted ContextFeatures."""
    if not isinstance(payload, dict):
        raise OverpassUnavailable("Overpass returned an unreadable response.")
    elements = payload.get("elements")
    if not isinstance(elements, list):
        return []

    features: List[ContextFeature] = []
    seen: set = set()
    for element in elements:
        if not isinstance(element, dict):
            continue
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            continue
        categorised = _categorise(tags)
        if categorised is None:
            continue
        category, kind = categorised

        centre = element.get("center") if isinstance(element.get("center"), dict) else element
        element_lat, element_lon = centre.get("lat"), centre.get("lon")
        if not valid_coordinates(element_lat, element_lon):
            continue

        osm_id = f"{element.get('type', 'element')}/{element.get('id')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)

        name = tags.get("name")
        features.append(
            ContextFeature(
                osm_id=osm_id,
                name=name.strip() if isinstance(name, str) and name.strip() else None,
                category=category,
                kind=kind,
                label=CONTEXT_KIND_LABELS.get(kind, kind.replace("_", " ").capitalize()),
                latitude=float(element_lat),
                longitude=float(element_lon),
                distance_km=haversine_km(lat, lon, float(element_lat), float(element_lon)),
            )
        )

    features.sort(key=lambda f: (round(f.distance_km, 3), f.name is None))
    return features


class GeographicContextService:
    """Distance-aware cache + throttle in front of an Overpass client, for context features.

    Deliberately the same shape as NearbyWaterService: same caching, same courtesy to a free
    shared service. Both are handed the same OverpassThrottle by their factories, so an analysis
    that wants water bodies and geographic context spends one request slot at a time rather than
    two — Overpass rate-limits the client, not the code path.
    """

    def __init__(
        self,
        client: Any,
        cache_distance_m: float = 250.0,
        cache_size: int = 64,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        throttle: Optional[OverpassThrottle] = None,
    ):
        self.client = client
        self.cache_distance_km = cache_distance_m / 1000
        self.cache_size = cache_size
        self.throttle = throttle or OverpassThrottle(min_interval_s, clock, sleep)
        self._lock = threading.Lock()
        self._entries: List[Tuple[float, float, int, List[ContextFeature]]] = []

    def _lookup(self, lat: float, lon: float, radius_m: int) -> Optional[List[ContextFeature]]:
        for index, (cached_lat, cached_lon, cached_radius, features) in enumerate(self._entries):
            if cached_radius == radius_m and haversine_km(lat, lon, cached_lat, cached_lon) <= self.cache_distance_km:
                self._entries.append(self._entries.pop(index))
                return features
        return None

    def context(
        self, lat: float, lon: float, radius_m: Optional[int] = None, per_category: Optional[int] = None
    ) -> Tuple[Dict[str, List[ContextFeature]], int, bool]:
        """Return ({category: features}, radius_m, cached).

        Each category is truncated independently, so a dense mesh of mapped drains can never
        crowd out the one mapped landfill — which is the feature an analyst actually wants to see.

        Raises OverpassUnavailable when Overpass cannot answer.
        """
        if not valid_coordinates(lat, lon):
            raise InvalidLocationError("Location coordinates are invalid.")
        radius = max(50, min(int(radius_m or settings.overpass_radius_m), settings.overpass_max_radius_m))
        count = max(1, min(int(per_category or settings.overpass_max_results), 50))

        with self._lock:
            features = self._lookup(lat, lon, radius)
            cached = features is not None
            if features is None:
                self.throttle.wait()
                query = build_context_query(lat, lon, radius, int(settings.overpass_timeout_seconds))
                features = parse_context_elements(self.client.query(query), lat, lon)
                # Cache the FULL list, so a later call with a bigger per-category cap still hits.
                self._entries.append((lat, lon, radius, features))
                del self._entries[: max(0, len(self._entries) - self.cache_size)]

        grouped: Dict[str, List[ContextFeature]] = {category: [] for category in CONTEXT_SELECTORS}
        for feature in features:
            bucket = grouped.setdefault(feature.category, [])
            if len(bucket) < count:
                bucket.append(feature)
        return grouped, radius, cached


_context_lock = threading.Lock()
_context_service: Optional[GeographicContextService] = None


def get_geographic_context_service() -> GeographicContextService:
    global _context_service
    with _context_lock:
        if _context_service is None:
            _context_service = GeographicContextService(
                OverpassClient(
                    settings.overpass_base_url,
                    settings.nominatim_user_agent,  # one identity for both OSM services
                    timeout=settings.overpass_timeout_seconds + 5,
                ),
                cache_distance_m=settings.overpass_cache_distance_m,
                throttle=_shared_throttle,
            )
        return _context_service
