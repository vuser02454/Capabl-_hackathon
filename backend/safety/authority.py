"""Nearest relevant authority for an incident domain, from OpenStreetMap.

The hard rule here is that nothing is invented. A station name, address or phone number is
returned only when OpenStreetMap actually carries it for that object; anything absent comes back
as `None` and is rendered as "not listed" rather than filled in with something plausible. A
fabricated emergency number is worse than no number, because someone might dial it.

Distance IS computed rather than read from OSM — that is arithmetic over two real coordinates,
not invented data — and is reported as a straight-line distance, which is what it is.

Two authority types have no dependable OpenStreetMap tag:

    WILDLIFE_AUTHORITY   forest / wildlife offices are tagged inconsistently across regions
    ELECTRICAL_SERVICE   utility operators are not a mapped amenity

For those the service reports that lookup is unavailable and says why. The safety analysis
continues regardless — an authority lookup failing must never stop a report being analysed.

Usage-policy safeguards mirror the existing Nominatim client: identifying User-Agent, a serialised
one-request-per-interval throttle, a short timeout and an in-memory cache.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from safety.geo import haversine_meters

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_USER_AGENT = "EcoSentinel-Safety/1.0 (hackathon project; authority lookup)"

#: Authority type -> the OSM selectors that identify it. An empty tuple means "not mappable".
OSM_SELECTORS: Dict[str, Tuple[str, ...]] = {
    "POLICE": ('["amenity"="police"]',),
    "FIRE_STATION": ('["amenity"="fire_station"]',),
    "EMERGENCY_MEDICAL": ('["amenity"="hospital"]', '["amenity"="clinic"]', '["emergency"="yes"]'),
    "WILDLIFE_AUTHORITY": (),
    "ELECTRICAL_SERVICE": (),
}

AUTHORITY_LABEL = {
    "POLICE": "Police",
    "FIRE_STATION": "Fire service",
    "EMERGENCY_MEDICAL": "Emergency medical",
    "WILDLIFE_AUTHORITY": "Wildlife / animal control",
    "ELECTRICAL_SERVICE": "Electrical utility",
}

#: Why an unmappable type cannot be looked up. Shown verbatim, so the gap is explained not hidden.
UNMAPPABLE_REASON = {
    "WILDLIFE_AUTHORITY":
        "OpenStreetMap has no consistent tag for wildlife or animal-control offices, so no "
        "verified contact can be retrieved. Use the local forest or municipal animal-control "
        "directory.",
    "ELECTRICAL_SERVICE":
        "Electrical utility operators are not mapped as an OpenStreetMap amenity, so no verified "
        "contact can be retrieved. Use the site's registered electrical contractor or the local "
        "distribution utility.",
}

DEFAULT_RADIUS_METERS = 10_000
MAX_RESULTS = 3


class AuthorityLookupError(RuntimeError):
    """Raised when the lookup could not be completed. Never fatal to a safety analysis."""


def _tag(tags: Dict[str, str], *keys: str) -> Optional[str]:
    """First non-empty tag among `keys`, or None. Never a placeholder."""
    for key in keys:
        value = (tags.get(key) or "").strip()
        if value:
            return value
    return None


def _address(tags: Dict[str, str]) -> Optional[str]:
    """Reassemble an address from OSM's addr:* tags. Returns None when nothing is tagged."""
    parts = [
        " ".join(filter(None, [_tag(tags, "addr:housenumber"), _tag(tags, "addr:street")])),
        _tag(tags, "addr:suburb", "addr:neighbourhood"),
        _tag(tags, "addr:city", "addr:town", "addr:village"),
        _tag(tags, "addr:postcode"),
    ]
    joined = ", ".join(part for part in parts if part)
    return joined or None


def _element_position(element: Dict[str, Any]) -> Optional[Tuple[float, float]]:
    """A node carries lat/lon directly; a way or relation carries a `center` (out center)."""
    if element.get("lat") is not None and element.get("lon") is not None:
        return float(element["lat"]), float(element["lon"])
    centre = element.get("center") or {}
    if centre.get("lat") is not None and centre.get("lon") is not None:
        return float(centre["lat"]), float(centre["lon"])
    return None


class AuthorityLookupService:
    """Overpass-backed lookup with a throttle and cache, matching the project's Nominatim client."""

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 8.0,
        min_interval_s: float = 2.0,
        cache_size: int = 64,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.endpoint = endpoint
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_interval_s = min_interval_s
        self.cache_size = cache_size
        self.opener = opener
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._cache: "OrderedDict[str, List[Dict[str, Any]]]" = OrderedDict()
        self._last_request: Optional[float] = None

    # -- transport --------------------------------------------------------------------------

    #: Overpass sheds load with 429/504 under even modest use. One retry after a short pause
    #: turned observed failures into successes during testing; more than that would be rude.
    RETRY_STATUSES = frozenset({429, 502, 503, 504})
    RETRY_PAUSE_S = 3.0

    def _query(self, body: str) -> Dict[str, Any]:
        for attempt in (1, 2):
            request = Request(
                self.endpoint,
                data=urlencode({"data": body}).encode("utf-8"),
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except HTTPError as exc:
                if exc.code in self.RETRY_STATUSES and attempt == 1:
                    self.sleep(self.RETRY_PAUSE_S)
                    continue
                raise AuthorityLookupError(f"Authority lookup unavailable (Overpass HTTP {exc.code}).")
            except (URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as exc:
                if attempt == 1:
                    self.sleep(self.RETRY_PAUSE_S)
                    continue
                raise AuthorityLookupError("Authority lookup unavailable.") from exc
        raise AuthorityLookupError("Authority lookup unavailable.")

    def _overpass_ql(self, authority_type: str, latitude: float, longitude: float, radius: int) -> str:
        clauses = "".join(
            f'{kind}{selector}(around:{radius},{latitude:.6f},{longitude:.6f});'
            for selector in OSM_SELECTORS[authority_type]
            for kind in ("node", "way", "relation")
        )
        # `out center` gives ways and relations a representative point to measure distance from.
        return f"[out:json][timeout:{int(self.timeout)}];({clauses});out center tags {MAX_RESULTS * 6};"

    # -- public API -------------------------------------------------------------------------

    def lookup(
        self,
        latitude: float,
        longitude: float,
        authority_type: Optional[str],
        radius_meters: int = DEFAULT_RADIUS_METERS,
    ) -> Dict[str, Any]:
        """Nearest authorities of one type. Never raises — failure is part of the return value.

        The caller is a graph node in the middle of a safety analysis, so a lookup problem is
        reported as data ("available": False) rather than thrown, and the analysis continues.
        """
        if not authority_type:
            return {"available": False, "authority_type": None, "results": [],
                    "reason": "This incident domain has no associated emergency authority.",
                    "source": None}

        label = AUTHORITY_LABEL.get(authority_type, authority_type)
        if authority_type not in OSM_SELECTORS:
            return {"available": False, "authority_type": authority_type, "label": label,
                    "results": [], "reason": f"Unknown authority type '{authority_type}'.", "source": None}

        if not OSM_SELECTORS[authority_type]:
            return {"available": False, "authority_type": authority_type, "label": label,
                    "results": [], "reason": UNMAPPABLE_REASON[authority_type], "source": None}

        key = f"{authority_type}:{latitude:.3f}:{longitude:.3f}:{radius_meters}"
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return {"available": True, "authority_type": authority_type, "label": label,
                        "results": self._cache[key], "cached": True,
                        "source": "OpenStreetMap (Overpass API)", "radius_meters": radius_meters}
            if self._last_request is not None:
                wait = self.min_interval_s - (self.clock() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()
            try:
                payload = self._query(self._overpass_ql(authority_type, latitude, longitude, radius_meters))
            except AuthorityLookupError as exc:
                logger.warning("authority_lookup_failed type=%s: %s", authority_type, exc)
                return {"available": False, "authority_type": authority_type, "label": label,
                        "results": [], "reason": str(exc), "source": "OpenStreetMap (Overpass API)"}

            results = self._parse(payload, latitude, longitude)
            self._cache[key] = results
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)

        return {"available": True, "authority_type": authority_type, "label": label,
                "results": results, "cached": False,
                "source": "OpenStreetMap (Overpass API)", "radius_meters": radius_meters,
                "reason": None if results else
                          f"No {label.lower()} found in OpenStreetMap within {radius_meters / 1000:.0f} km."}

    def _parse(self, payload: Dict[str, Any], latitude: float, longitude: float) -> List[Dict[str, Any]]:
        """Turn an Overpass response into authority records, nearest first.

        An element with no name is skipped: an unnamed point is not something an admin can act on,
        and naming it "Police station" would be inventing an identity for it.
        """
        found: List[Dict[str, Any]] = []
        for element in payload.get("elements", []):
            position = _element_position(element)
            tags = element.get("tags") or {}
            name = _tag(tags, "name", "official_name", "operator")
            if position is None or not name:
                continue
            phone = _tag(tags, "phone", "contact:phone", "emergency:phone")
            found.append({
                "name": name,
                "address": _address(tags),
                "phone": phone,
                # True only when OSM carried a contact number for this object. The UI must not
                # present an authority without one as if it had been confirmed.
                "verified": phone is not None,
                "distance_meters": round(haversine_meters(latitude, longitude, position[0], position[1])),
                "latitude": position[0],
                "longitude": position[1],
                "osm_id": f"{element.get('type')}/{element.get('id')}",
                "source": "OpenStreetMap (Overpass API)",
            })
        found.sort(key=lambda item: item["distance_meters"])
        return found[:MAX_RESULTS]


_SERVICE: Optional[AuthorityLookupService] = None


def service() -> AuthorityLookupService:
    """Process-wide singleton, so the throttle and cache are actually shared."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = AuthorityLookupService(
            endpoint=os.getenv("ECOSENTINEL_OVERPASS_URL", DEFAULT_ENDPOINT),
            user_agent=os.getenv("ECOSENTINEL_NOMINATIM_USER_AGENT", DEFAULT_USER_AGENT),
        )
    return _SERVICE


def lookup(latitude: float, longitude: float, authority_type: Optional[str],
           radius_meters: int = DEFAULT_RADIUS_METERS) -> Dict[str, Any]:
    """Module-level convenience wrapper over the shared service."""
    return service().lookup(latitude, longitude, authority_type, radius_meters)
