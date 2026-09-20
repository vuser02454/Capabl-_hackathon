"""Forward and reverse geocoding via OpenStreetMap Nominatim.

Nominatim provides GEOGRAPHIC CONTEXT ONLY (place names, nearby named water features).
It never provides environmental measurements.

Usage-policy safeguards (https://operations.osmfoundation.org/policies/nominatim/):
- identifying User-Agent (ECOSENTINEL_NOMINATIM_USER_AGENT)
- at most one request per second, requests serialized
- in-memory cache; no new request unless the position moved more than
  ECOSENTINEL_GEOCODE_CACHE_DISTANCE_M (default 100 m)
- only lat/lon (or a search string) and an optional contact email are sent; nothing is logged
  or persisted

Two directions are supported:
    reverse   coordinates -> place name (used by browser geolocation)
    search    free-text place name -> coordinates (lets any place be analysed, not just the
              presets in shared/locations.json)
"""

import json
import socket
import threading
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import settings
from core.errors import GeocodingError, InvalidLocationError
from core.geo import haversine_km, valid_coordinates

NATURAL_WATER_TYPES = {"water", "bay", "wetland", "spring", "strait", "coastline", "beach"}
WATER_ADDRESS_KEYS = ("water", "river", "lake", "reservoir", "waterway", "stream", "canal", "bay")


def is_water_feature(category: Optional[str], place_type: Optional[str]) -> bool:
    """Does this Nominatim (category, type) pair describe a water feature?

    The two endpoints label the same place differently: /reverse reports the raw OSM key
    (`natural=water`, `waterway=river`), while /search reports the resolved feature class, so
    Bellandur Lake comes back as `category="water", type="lake"`. Both shapes are accepted here
    rather than in each parser, which is what let `isWater` quietly return False for every lake.
    """
    if category == "waterway" or category == "water":
        return True
    if category == "natural" and place_type in NATURAL_WATER_TYPES:
        return True
    if category == "landuse" and place_type in {"reservoir", "basin"}:
        return True
    return False
UNRESOLVED_MESSAGE = "Location detected, but place name could not be resolved."
SEARCH_FAILED_MESSAGE = "Place search is unavailable right now."


@dataclass(frozen=True)
class GeocodedPlace:
    display_name: Optional[str]
    city: Optional[str]
    state: Optional[str]
    country: Optional[str]
    #: ISO 3166-1 alpha-2, lowercased. The country NAME is localised and free-text; the code is
    #: what a country check can actually be written against.
    country_code: Optional[str]
    postcode: Optional[str]
    neighbourhood: Optional[str]
    water_feature: Optional[str]

    def as_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


def _first(address: Dict[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def parse_reverse(payload: Any) -> GeocodedPlace:
    """Normalise a Nominatim /reverse (format=jsonv2) response."""
    if not isinstance(payload, dict) or payload.get("error"):
        raise GeocodingError(UNRESOLVED_MESSAGE)
    address = payload.get("address") or {}

    water_feature = None
    category, place_type, name = payload.get("category"), payload.get("type"), payload.get("name")
    if isinstance(name, str) and name.strip() and is_water_feature(category, place_type):
        water_feature = name.strip()
    if water_feature is None:
        water_feature = _first(address, *WATER_ADDRESS_KEYS)

    place = GeocodedPlace(
        display_name=payload.get("display_name") if isinstance(payload.get("display_name"), str) else None,
        city=_first(address, "city", "town", "village", "municipality", "city_district", "county"),
        state=_first(address, "state", "region", "state_district"),
        country=_first(address, "country"),
        country_code=(_first(address, "country_code") or "").lower() or None,
        postcode=_first(address, "postcode"),
        neighbourhood=_first(address, "neighbourhood", "suburb", "quarter", "hamlet"),
        water_feature=water_feature,
    )
    if not (place.display_name or place.city or place.country):
        raise GeocodingError(UNRESOLVED_MESSAGE)
    return place


@dataclass(frozen=True)
class GeocodedMatch:
    """One forward-geocoding candidate: a place name resolved to coordinates."""

    display_name: str
    latitude: float
    longitude: float
    category: Optional[str]
    place_type: Optional[str]
    importance: Optional[float]
    #: True when the match is itself a water feature (a lake, river, reservoir...).
    is_water: bool
    #: ISO 3166-1 alpha-2 from Nominatim's structured address, lowercased. None when the
    #: response carried no address block — treated as unverified rather than as a match.
    country_code: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "displayName": self.display_name,
            "latitude": round(self.latitude, 6),
            "longitude": round(self.longitude, 6),
            "category": self.category,
            "placeType": self.place_type,
            "importance": self.importance,
            "isWater": self.is_water,
            "countryCode": self.country_code,
        }


def parse_search(payload: Any) -> List[GeocodedMatch]:
    """Normalise a Nominatim /search (format=jsonv2) response. Unusable entries are skipped."""
    if not isinstance(payload, list):
        raise GeocodingError("Place search returned an unreadable response.")

    matches: List[GeocodedMatch] = []
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        display_name = entry.get("display_name")
        if not (isinstance(display_name, str) and display_name.strip()):
            continue
        try:
            latitude, longitude = float(entry.get("lat")), float(entry.get("lon"))
        except (TypeError, ValueError):
            continue
        if not valid_coordinates(latitude, longitude):
            continue

        category, place_type = entry.get("category"), entry.get("type")
        importance = entry.get("importance")
        # Structured metadata, not a substring of display_name: "India Street, Boston" contains
        # the word India and would pass a text check while being in Massachusetts.
        address = entry.get("address")
        raw_country = address.get("country_code") if isinstance(address, dict) else None
        country_code = raw_country.strip().lower() if isinstance(raw_country, str) else None
        matches.append(
            GeocodedMatch(
                display_name=display_name.strip(),
                latitude=latitude,
                longitude=longitude,
                category=category if isinstance(category, str) else None,
                place_type=place_type if isinstance(place_type, str) else None,
                importance=float(importance) if isinstance(importance, (int, float)) else None,
                is_water=is_water_feature(
                    category if isinstance(category, str) else None,
                    place_type if isinstance(place_type, str) else None,
                ),
                country_code=country_code,
            )
        )
    return matches


class NominatimClient:
    def __init__(
        self,
        base_url: str,
        user_agent: str,
        email: Optional[str] = None,
        timeout: float = 6.0,
        opener: Callable[..., Any] = urlopen,
    ):
        self.base_url = base_url.rstrip("/")
        self.user_agent = user_agent
        self.email = email
        self.timeout = timeout
        self.opener = opener

    def _get(self, path: str, params: Dict[str, str], failure: str) -> Any:
        if self.email:
            params = {**params, "email": self.email}
        request = Request(
            f"{self.base_url}/{path}?{urlencode(params)}",
            headers={"User-Agent": self.user_agent, "Accept": "application/json", "Accept-Language": "en"},
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise GeocodingError(f"{failure} (Nominatim HTTP {exc.code})")
        except (URLError, socket.timeout, TimeoutError, ConnectionError, ValueError):
            raise GeocodingError(failure)

    def reverse(self, lat: float, lon: float) -> Dict[str, Any]:
        return self._get(
            "reverse", {"lat": f"{lat:.6f}", "lon": f"{lon:.6f}", "format": "jsonv2"}, UNRESOLVED_MESSAGE
        )

    def search(self, query: str, limit: int, country_codes: Optional[str] = None) -> Any:
        """Forward search. `country_codes` is Nominatim's own filter, applied server-side.

        Asking Nominatim to restrict the search is different from filtering its answer afterwards:
        the filter is applied before ranking, so the Indian results are the ones that come back
        ranked rather than the ones that survive. Appending "India" to the query string would not
        do this — it would just be more text to match.
        """
        return self._get(
            "search",
            # `addressdetails=1` is what makes `address.country_code` available; without it there
            # is nothing structured to validate a result against.
            {"q": query, "format": "jsonv2", "limit": str(limit), "addressdetails": "1",
             **({"countrycodes": country_codes} if country_codes else {})},
            SEARCH_FAILED_MESSAGE,
        )


class ReverseGeocodingService:
    """Distance-aware cache + throttle in front of a Nominatim client."""

    def __init__(
        self,
        client: Any,
        cache_distance_m: float = 100.0,
        cache_size: int = 128,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.client = client
        self.cache_distance_km = cache_distance_m / 1000
        self.cache_size = cache_size
        self.min_interval_s = min_interval_s
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._entries: List[Tuple[float, float, GeocodedPlace]] = []
        #: Forward-search results keyed by normalised query; insertion order gives LRU eviction.
        self._search_cache: "OrderedDict[str, List[GeocodedMatch]]" = OrderedDict()
        self._last_request: Optional[float] = None

    def _lookup(self, lat: float, lon: float) -> Optional[GeocodedPlace]:
        for index, (cached_lat, cached_lon, place) in enumerate(self._entries):
            if haversine_km(lat, lon, cached_lat, cached_lon) <= self.cache_distance_km:
                self._entries.append(self._entries.pop(index))  # most recently used last
                return place
        return None

    def reverse(self, lat: float, lon: float) -> Tuple[GeocodedPlace, bool]:
        """Return (place, cached). Raises GeocodingError when the place cannot be resolved."""
        if not valid_coordinates(lat, lon):
            raise InvalidLocationError("Location coordinates are invalid.")
        with self._lock:
            hit = self._lookup(lat, lon)
            if hit is not None:
                return hit, True
            if self._last_request is not None:
                wait = self.min_interval_s - (self.clock() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()
            place = parse_reverse(self.client.reverse(lat, lon))
            self._entries.append((lat, lon, place))
            del self._entries[: max(0, len(self._entries) - self.cache_size)]
            return place, False


    def search(self, query: str, limit: int = 5,
               country_codes: Optional[str] = None) -> Tuple[List[GeocodedMatch], bool]:
        """Free text -> candidate places. Returns (matches, cached).

        Shares the one-request-per-second throttle with reverse lookups, because Nominatim's usage
        policy counts every request to the service, not per endpoint.

        `country_codes` is applied TWICE on purpose: once as Nominatim's own server-side filter so
        the ranked results are the right ones, and once over the parsed response so a result whose
        structured address says otherwise is dropped rather than trusted. Belt and braces, because
        the filter is a request parameter and the country code is the actual evidence.
        """
        key = " ".join((query or "").strip().lower().split())
        if not key:
            raise InvalidLocationError("Enter a place to search for.")
        capped = max(1, min(limit, 10))
        wanted = {code.strip().lower() for code in (country_codes or "").split(",") if code.strip()}
        cache_key = f"{key}|{','.join(sorted(wanted))}"

        def keep(found: List[GeocodedMatch]) -> List[GeocodedMatch]:
            if not wanted:
                return found
            # A match with no country code is unverified, so it is dropped rather than assumed.
            return [m for m in found if m.country_code in wanted]

        with self._lock:
            cached = self._search_cache.get(cache_key)
            if cached is not None:
                self._search_cache[cache_key] = cached  # refresh recency
                return keep(cached)[:capped], True
            if self._last_request is not None:
                wait = self.min_interval_s - (self.clock() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()

            matches = parse_search(self.client.search(key, capped, country_codes))
            self._search_cache[cache_key] = matches
            while len(self._search_cache) > self.cache_size:
                self._search_cache.pop(next(iter(self._search_cache)))
            return keep(matches)[:capped], False


_geocoder_lock = threading.Lock()
_geocoder: Optional[ReverseGeocodingService] = None


def get_geocoder() -> ReverseGeocodingService:
    global _geocoder
    with _geocoder_lock:
        if _geocoder is None:
            _geocoder = ReverseGeocodingService(
                NominatimClient(settings.nominatim_base_url, settings.nominatim_user_agent, settings.nominatim_email),
                cache_distance_m=settings.geocode_cache_distance_m,
            )
        return _geocoder
