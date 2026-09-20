"""Nearby water bodies via Overpass, and Nominatim forward geocoding.

Both talk to donated OpenStreetMap infrastructure, so the contract under test is as much about
courtesy and graceful failure as about parsing: throttle, cache, cap, and never turn an outage
into an exception that breaks an agent.

No test here touches the network — every client is a stub.
"""

import json
from typing import Any, Dict, List

import pytest

from core.errors import GeocodingError, InvalidLocationError
from services.geocoding_service import (
    NominatimClient,
    ReverseGeocodingService,
    is_water_feature,
    parse_search,
)
from services.overpass_service import (
    NearbyWaterService,
    OverpassUnavailable,
    WATER_KINDS,
    build_query,
    nearest_water_body,
    parse_elements,
)

BENGALURU = (12.9345, 77.6745)


def _element(osm_id: int, tags: Dict[str, Any], lat: float, lon: float, kind: str = "way") -> Dict[str, Any]:
    return {"type": kind, "id": osm_id, "center": {"lat": lat, "lon": lon}, "tags": tags}


class StubOverpass:
    """Records every query it is handed, so throttling and caching are observable."""

    def __init__(self, payload: Any = None, error: Exception = None):
        self.payload = payload if payload is not None else {"elements": []}
        self.error = error
        self.calls: List[str] = []

    def query(self, query: str) -> Any:
        self.calls.append(query)
        if self.error:
            raise self.error
        return self.payload


def _service(client, **kwargs) -> NearbyWaterService:
    slept: List[float] = []
    ticks = iter(range(1, 10_000))
    service = NearbyWaterService(
        client,
        clock=lambda: float(next(ticks)) * 1000,  # far apart: never throttles unless asked
        sleep=slept.append,
        **kwargs,
    )
    service.slept = slept  # type: ignore[attr-defined]
    return service


# ------------------------------------------------------------------ query building


def test_query_asks_for_centres_and_bounds_the_server_side_timeout():
    query = build_query(12.9345, 77.6745, 1500, 25)
    assert "[out:json][timeout:25]" in query
    assert "(around:1500,12.934500,77.674500)" in query
    # `out center` keeps ways/relations to one coordinate instead of full geometry.
    assert query.rstrip().endswith("out center tags;")


def test_query_covers_standing_water_and_waterways():
    query = build_query(0, 0, 500, 10)
    assert '["natural"="water"]' in query
    assert "river|stream|canal|drain" in query
    assert '["landuse"~"^(reservoir|basin)$"]' in query


# ------------------------------------------------------------------ parsing


def test_parses_and_sorts_by_distance():
    payload = {
        "elements": [
            _element(2, {"natural": "water", "water": "lake", "name": "Far Lake"}, 12.95, 77.6745),
            _element(1, {"waterway": "drain"}, 12.9350, 77.6745),
        ]
    }
    features = parse_elements(payload, *BENGALURU)
    assert [f.osm_id for f in features] == ["way/1", "way/2"]
    assert features[0].label == "Storm drain" and features[0].flowing is True
    assert features[1].label == "Lake" and features[1].flowing is False


def test_unnamed_features_are_kept_but_marked():
    features = parse_elements({"elements": [_element(1, {"natural": "water"}, *BENGALURU)]}, *BENGALURU)
    assert features[0].name is None
    assert features[0].display_name == "Unnamed water body"
    # natural=water with no subtype is standing water, not a river.
    assert features[0].kind == "lake"


def test_non_water_elements_are_dropped():
    payload = {"elements": [_element(1, {"highway": "residential", "name": "Main Road"}, *BENGALURU)]}
    assert parse_elements(payload, *BENGALURU) == []


def test_elements_without_usable_coordinates_are_skipped():
    payload = {"elements": [{"type": "way", "id": 1, "tags": {"natural": "water"}}]}
    assert parse_elements(payload, *BENGALURU) == []


def test_duplicate_ids_are_collapsed():
    element = _element(1, {"natural": "water", "name": "Lake"}, *BENGALURU)
    features = parse_elements({"elements": [element, dict(element)]}, *BENGALURU)
    assert len(features) == 1


def test_named_feature_wins_a_distance_tie():
    payload = {
        "elements": [
            _element(1, {"waterway": "drain"}, *BENGALURU),
            _element(2, {"natural": "water", "name": "Named Lake"}, *BENGALURU),
        ]
    }
    assert parse_elements(payload, *BENGALURU)[0].name == "Named Lake"


def test_malformed_payload_is_reported_not_crashed():
    with pytest.raises(OverpassUnavailable):
        parse_elements("not a dict", *BENGALURU)
    assert parse_elements({"elements": "nonsense"}, *BENGALURU) == []


def test_every_water_kind_has_a_label():
    for kind, (label, flowing) in WATER_KINDS.items():
        assert label and isinstance(flowing, bool)


# ------------------------------------------------------------------ the service


def test_nearest_named_is_chosen_before_the_limit_truncates():
    """The bug this guards: urban water is a mesh of unnamed drains, so the named lake a report
    must cite sits far down the distance ordering — 39th, in the Bellandur case."""
    elements = [_element(i, {"waterway": "drain"}, 12.9346 + i * 0.0001, 77.6745) for i in range(30)]
    elements.append(_element(999, {"natural": "water", "name": "Bellandur Lake"}, 12.9480, 77.6745))
    service = _service(StubOverpass({"elements": elements}))

    bodies, named, _cached = service.nearby(*BENGALURU, radius_m=1500, limit=5)

    assert len(bodies) == 5
    assert all(body.name is None for body in bodies)  # the lake is NOT in the truncated list
    assert named is not None and named.name == "Bellandur Lake"


def test_nearest_named_is_none_when_nothing_nearby_is_named():
    service = _service(StubOverpass({"elements": [_element(1, {"waterway": "drain"}, *BENGALURU)]}))
    _bodies, named, _cached = service.nearby(*BENGALURU)
    assert named is None


def test_second_call_at_the_same_point_is_served_from_cache():
    client = StubOverpass({"elements": [_element(1, {"natural": "water", "name": "Lake"}, *BENGALURU)]})
    service = _service(client)

    service.nearby(*BENGALURU, radius_m=1500)
    _bodies, named, cached = service.nearby(12.93452, 77.67452, radius_m=1500)

    assert cached is True
    assert named.name == "Lake"
    assert len(client.calls) == 1  # no second request to donated infrastructure


def test_cache_holds_the_full_list_so_a_larger_limit_still_hits():
    elements = [_element(i, {"waterway": "drain"}, 12.9346 + i * 0.0001, 77.6745) for i in range(20)]
    client = StubOverpass({"elements": elements})
    service = _service(client)

    first, _named, _cached = service.nearby(*BENGALURU, radius_m=1500, limit=3)
    second, _named2, cached = service.nearby(*BENGALURU, radius_m=1500, limit=15)

    assert len(first) == 3 and len(second) == 15
    assert cached is True and len(client.calls) == 1


def test_a_different_radius_is_not_a_cache_hit():
    client = StubOverpass({"elements": []})
    service = _service(client)
    service.nearby(*BENGALURU, radius_m=500)
    _bodies, _named, cached = service.nearby(*BENGALURU, radius_m=3000)
    assert cached is False
    assert len(client.calls) == 2  # a 500 m answer cannot answer a 3 km question


def test_radius_and_limit_are_capped(monkeypatch):
    from config import settings

    client = StubOverpass({"elements": []})
    service = _service(client)
    service.nearby(*BENGALURU, radius_m=999_999)
    assert f"around:{settings.overpass_max_radius_m}," in client.calls[0]


def test_requests_are_throttled_to_protect_a_free_service():
    client = StubOverpass({"elements": []})
    slept: List[float] = []
    service = NearbyWaterService(client, clock=lambda: 100.0, sleep=slept.append, min_interval_s=1.0)

    service.nearby(12.90, 77.60)
    service.nearby(12.80, 77.50)  # far enough to miss the cache

    assert slept and slept[0] == pytest.approx(1.0)


def test_invalid_coordinates_are_rejected_before_any_request():
    client = StubOverpass({"elements": []})
    with pytest.raises(InvalidLocationError):
        _service(client).nearby(999, 999)
    assert client.calls == []


def test_outage_never_escapes_to_the_caller():
    """nearest_water_body is called from report enrichment; it must degrade, not raise."""
    import services.overpass_service as module

    service = _service(StubOverpass(error=OverpassUnavailable("Overpass is busy.")))
    module._service = service
    try:
        assert nearest_water_body(*BENGALURU) is None
    finally:
        module._service = None


# ------------------------------------------------------------------ Nominatim forward search


class StubNominatim:
    def __init__(self, payload: Any):
        self.payload = payload
        self.queries: List[str] = []

    def search(self, query: str, limit: int, country_codes=None) -> Any:
        self.queries.append(query)
        return self.payload

    def reverse(self, lat: float, lon: float) -> Any:  # pragma: no cover - unused here
        raise AssertionError("reverse should not be called")


def _match(name: str, category: str, place_type: str, lat: str = "12.9", lon: str = "77.6"):
    return {"display_name": name, "lat": lat, "lon": lon, "category": category, "type": place_type}


def test_search_flags_water_features_from_the_search_response_shape():
    """/search labels a lake `category="water"`, unlike /reverse — the shape that broke isWater."""
    matches = parse_search([_match("Bellandur Lake", "water", "lake")])
    assert matches[0].is_water is True


def test_search_does_not_flag_ordinary_places():
    matches = parse_search([_match("Bengaluru", "place", "city")])
    assert matches[0].is_water is False


def test_is_water_accepts_both_endpoint_shapes():
    assert is_water_feature("water", "lake") is True        # /search
    assert is_water_feature("natural", "water") is True      # /reverse
    assert is_water_feature("waterway", "river") is True
    assert is_water_feature("landuse", "reservoir") is True
    assert is_water_feature("place", "city") is False


def test_search_skips_entries_without_usable_coordinates():
    payload = [{"display_name": "Broken", "lat": "abc", "lon": "77.6"}, _match("Good", "place", "city")]
    matches = parse_search(payload)
    assert [m.display_name for m in matches] == ["Good"]


def test_search_rejects_an_unreadable_response():
    with pytest.raises(GeocodingError):
        parse_search({"not": "a list"})


def test_search_caches_by_normalised_query():
    client = StubNominatim([_match("Bellandur Lake", "water", "lake")])
    service = ReverseGeocodingService(client, clock=lambda: 100.0, sleep=lambda _s: None)

    first, cached_first = service.search("Bellandur Lake")
    second, cached_second = service.search("  bellandur   lake  ")

    assert cached_first is False and cached_second is True
    assert len(client.queries) == 1
    assert first[0].display_name == second[0].display_name


def test_empty_search_is_rejected():
    service = ReverseGeocodingService(StubNominatim([]), clock=lambda: 100.0, sleep=lambda _s: None)
    with pytest.raises(InvalidLocationError):
        service.search("   ")
