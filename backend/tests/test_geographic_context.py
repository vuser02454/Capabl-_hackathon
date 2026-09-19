"""Geographic context enrichment: Overpass -> normalized GeographicContext -> LangGraph.

The contract under test is mostly about what this data is NOT. Overpass reports what OSM
contributors have MAPPED; it holds no measurements. So these tests pin down that:

  - coordinates turn into normalized, categorised, distance-sorted features;
  - every Overpass failure mode degrades to `available=False` with a reason, never an exception;
  - the enrichment never reaches the Coordinator and never moves a risk score.

No test here touches the network — the Overpass client is always a stub.
"""

import asyncio
from typing import Any, Dict, List

import pytest

from schemas import GeographicContext
from services import location_service
from services.overpass_service import (
    CONTEXT_KIND_LABELS,
    CONTEXT_SELECTORS,
    GeographicContextService,
    OverpassUnavailable,
    build_context_query,
    parse_context_elements,
)

BENGALURU = (12.9716, 77.5946)


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


def _service(client, **kwargs) -> GeographicContextService:
    ticks = iter(range(1, 10_000))
    return GeographicContextService(
        client,
        clock=lambda: float(next(ticks)) * 1000,  # far apart: never throttles unless asked
        sleep=lambda _seconds: None,
        **kwargs,
    )


# --------------------------------------------------------------------------- query construction


def test_one_query_covers_every_category():
    query = build_context_query(*BENGALURU, 1500, 25)
    assert 'landuse"="industrial' in query
    assert 'landuse"="landfill' in query
    assert 'waterway"~"^(river|stream|canal|drain)$' in query
    assert 'highway"~"^(motorway|trunk|primary)$' in query
    # A single union, not one request per category: Overpass is donated infrastructure.
    assert query.count("[out:json]") == 1


def test_query_bounds_the_radius_and_the_server_side_timeout():
    query = build_context_query(*BENGALURU, 1500, 25)
    assert "(around:1500,12.971600,77.594600)" in query
    assert "[timeout:25]" in query
    # `out center` collapses ways/relations to one point, which is all a distance needs.
    assert query.endswith("out center tags;")


def test_only_major_roads_are_requested():
    """Every residential street would swamp the result while saying nothing about emissions."""
    query = build_context_query(*BENGALURU, 1500, 25)
    assert "residential" not in query
    assert "service" not in query


# --------------------------------------------------------------------------- parsing


def test_features_are_categorised_and_sorted_by_distance():
    payload = {
        "elements": [
            _element(1, {"highway": "primary", "name": "Outer Ring Road"}, 12.9800, 77.5946),
            _element(2, {"landuse": "landfill", "name": "Mavallipura"}, 12.9720, 77.5946),
            _element(3, {"landuse": "industrial", "name": "Peenya Estate"}, 12.9750, 77.5946),
        ]
    }
    features = parse_context_elements(payload, *BENGALURU)
    assert [f.category for f in features] == ["waste", "industrial", "road"]
    assert [f.name for f in features] == ["Mavallipura", "Peenya Estate", "Outer Ring Road"]
    assert features[0].distance_km < features[1].distance_km < features[2].distance_km


def test_each_category_gets_a_human_label():
    payload = {
        "elements": [
            _element(1, {"landuse": "landfill"}, 12.9720, 77.5946),
            _element(2, {"man_made": "works"}, 12.9721, 77.5946),
            _element(3, {"waterway": "drain"}, 12.9722, 77.5946),
            _element(4, {"highway": "trunk"}, 12.9723, 77.5946),
        ]
    }
    labels = {f.kind: f.label for f in parse_context_elements(payload, *BENGALURU)}
    assert labels == {
        "landfill": "Landfill",
        "works": "Factory / works",
        "drain": "Storm drain",
        "trunk": "Trunk road",
    }


def test_unnamed_features_are_kept():
    """An unnamed landfill is still a mapped landfill worth reporting."""
    payload = {"elements": [_element(1, {"landuse": "landfill"}, 12.9720, 77.5946)]}
    features = parse_context_elements(payload, *BENGALURU)
    assert len(features) == 1 and features[0].name is None


def test_uncategorised_elements_are_dropped():
    payload = {
        "elements": [
            _element(1, {"amenity": "cafe", "name": "Coffee"}, 12.9720, 77.5946),
            _element(2, {"highway": "residential", "name": "A lane"}, 12.9720, 77.5946),
        ]
    }
    assert parse_context_elements(payload, *BENGALURU) == []


def test_elements_without_usable_coordinates_are_skipped():
    payload = {"elements": [{"type": "way", "id": 1, "tags": {"landuse": "landfill"}}]}
    assert parse_context_elements(payload, *BENGALURU) == []


def test_duplicate_ids_are_collapsed():
    payload = {"elements": [_element(7, {"landuse": "industrial"}, 12.972, 77.594)] * 3}
    assert len(parse_context_elements(payload, *BENGALURU)) == 1


def test_malformed_payload_is_reported_not_crashed():
    with pytest.raises(OverpassUnavailable):
        parse_context_elements("not json", *BENGALURU)


def test_every_selector_category_has_a_kind_label():
    """A category with no label would surface a raw OSM tag in the UI."""
    assert set(CONTEXT_SELECTORS) == {"industrial", "waste", "waterway", "road"}
    assert set(CONTEXT_KIND_LABELS).issuperset({"industrial", "landfill", "drain", "primary"})


# --------------------------------------------------------------------------- service behaviour


def test_categories_are_truncated_independently():
    """A dense mesh of mapped drains must not crowd out the one mapped landfill."""
    elements = [_element(i, {"waterway": "drain"}, 12.9717 + i / 100000, 77.5946) for i in range(30)]
    elements.append(_element(999, {"landuse": "landfill", "name": "Far landfill"}, 13.0, 77.62))
    grouped, _radius, _cached = _service(StubOverpass({"elements": elements})).context(
        *BENGALURU, per_category=5
    )
    assert len(grouped["waterway"]) == 5
    assert [f.name for f in grouped["waste"]] == ["Far landfill"]


def test_second_call_at_the_same_point_is_served_from_cache():
    client = StubOverpass({"elements": [_element(1, {"landuse": "industrial"}, 12.972, 77.594)]})
    service = _service(client)
    service.context(*BENGALURU)
    _grouped, _radius, cached = service.context(*BENGALURU)
    assert cached is True and len(client.calls) == 1


def test_a_different_radius_is_not_a_cache_hit():
    """A 500 m answer is not a valid answer for a 2 km question."""
    client = StubOverpass()
    service = _service(client)
    service.context(*BENGALURU, radius_m=500)
    service.context(*BENGALURU, radius_m=2000)
    assert len(client.calls) == 2


def test_cache_holds_the_full_list_so_a_larger_cap_still_hits():
    elements = [_element(i, {"landuse": "industrial"}, 12.9717 + i / 100000, 77.5946) for i in range(10)]
    client = StubOverpass({"elements": elements})
    service = _service(client)
    service.context(*BENGALURU, per_category=2)
    grouped, _radius, cached = service.context(*BENGALURU, per_category=8)
    assert cached is True and len(grouped["industrial"]) == 8 and len(client.calls) == 1


def test_requests_are_throttled_to_protect_a_free_service():
    slept: List[float] = []
    now = [100.0]
    service = GeographicContextService(
        StubOverpass(), clock=lambda: now[0], sleep=slept.append, min_interval_s=1.0
    )
    service.context(*BENGALURU, radius_m=500)
    now[0] += 0.25
    service.context(*BENGALURU, radius_m=2000)  # different radius: a real second request
    assert slept and slept[0] == pytest.approx(0.75)


def test_radius_and_per_category_are_capped(monkeypatch):
    client = StubOverpass()
    _grouped, radius, _cached = _service(client).context(*BENGALURU, radius_m=99999, per_category=999)
    assert radius <= 5000
    assert f"around:{radius}," in client.calls[0]


# --------------------------------------------------------------------------- failure degradation


class _PatchedSettings:
    """Settings is a frozen dataclass; wrap it to override one attribute for a test."""

    def __init__(self, base, **overrides):
        object.__setattr__(self, "_base", base)
        object.__setattr__(self, "_overrides", overrides)

    def __getattr__(self, name):
        overrides = object.__getattribute__(self, "_overrides")
        if name in overrides:
            return overrides[name]
        return getattr(object.__getattribute__(self, "_base"), name)


def _enable_overpass(monkeypatch, client: StubOverpass) -> None:
    """conftest.py disables Overpass suite-wide. Re-enable it against a stub for one test."""
    from services import overpass_service

    monkeypatch.setattr(
        location_service, "settings", _PatchedSettings(location_service.settings, overpass_enabled=True)
    )
    monkeypatch.setattr(overpass_service, "get_geographic_context_service", lambda: _service(client))


def test_disabled_overpass_returns_a_reason_not_an_error():
    """conftest.py switches Overpass off for the whole suite, so this is the default path."""
    context = location_service.resolve_geographic_context(*BENGALURU)
    assert isinstance(context, GeographicContext)
    assert context.available is False and context.status == "disabled"
    assert context.industrial_features == [] and context.waste_facilities == []


def test_invalid_coordinates_never_raise(monkeypatch):
    _enable_overpass(monkeypatch, StubOverpass())
    context = location_service.resolve_geographic_context(1000.0, 77.5946)
    assert context.available is False and context.status == "unavailable"


@pytest.mark.parametrize(
    "failure",
    [
        OverpassUnavailable("OpenStreetMap's Overpass service is rate-limiting or busy."),
        OverpassUnavailable("Could not reach Overpass (URLError)."),
        OverpassUnavailable("Overpass returned malformed JSON."),
        RuntimeError("something entirely unexpected"),
    ],
)
def test_every_overpass_failure_degrades_to_a_structured_result(monkeypatch, failure):
    _enable_overpass(monkeypatch, StubOverpass(error=failure))
    context = location_service.resolve_geographic_context(*BENGALURU)
    assert context.available is False
    assert context.status == "unavailable"
    assert context.message  # the UI must be able to say why


def test_no_mapped_features_is_reported_as_such(monkeypatch):
    _enable_overpass(monkeypatch, StubOverpass({"elements": []}))
    context = location_service.resolve_geographic_context(*BENGALURU)
    assert context.available is False and context.status == "ok"
    assert "No mapped" in (context.message or "")


def test_features_are_normalised_onto_the_schema(monkeypatch):
    payload = {
        "elements": [
            _element(1, {"landuse": "industrial", "name": "Peenya"}, 12.9750, 77.5946),
            _element(2, {"landuse": "landfill"}, 12.9760, 77.5946),
            _element(3, {"waterway": "drain"}, 12.9718, 77.5946),
            _element(4, {"highway": "primary", "name": "ORR"}, 12.9800, 77.5946),
        ]
    }
    _enable_overpass(monkeypatch, StubOverpass(payload))
    context = location_service.resolve_geographic_context(*BENGALURU)

    assert context.available is True and context.status == "ok"
    assert context.source == "OpenStreetMap/Overpass"
    assert [f.name for f in context.industrial_features] == ["Peenya"]
    assert [f.label for f in context.waste_facilities] == ["Landfill"]
    assert [f.label for f in context.waterways] == ["Storm drain"]
    assert [f.name for f in context.roads] == ["ORR"]
    assert context.total_features == 4
    # Distances are measured from the analysis point, not assumed.
    assert context.industrial_features[0].distance_km == pytest.approx(0.378, abs=0.05)


# --------------------------------------------------------------------------- graph integration


def test_demo_mode_skips_overpass_entirely():
    """Demo Mode must not query donated infrastructure for a fabricated location."""
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    result = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))
    assert result.geographic_context is not None
    assert result.geographic_context.status == "skipped"
    assert result.geographic_context.available is False


def test_context_enrichment_never_reaches_the_coordinator():
    """A mapped factory must not be able to move a risk score.

    The enrichment node writes to the analysis result only; CoordinatorInput carries the typed
    specialist reports and a location label, and nothing else.
    """
    import dataclasses

    from agents.coordinator_agent import CoordinatorInput

    fields = {field.name for field in dataclasses.fields(CoordinatorInput)}
    assert fields == {"location", "air", "water", "waste"}


def test_enrichment_failure_does_not_change_the_risk_score(monkeypatch):
    """Scores with Overpass down must equal scores with Overpass never consulted."""
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    baseline = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))

    _enable_overpass(monkeypatch, StubOverpass(error=OverpassUnavailable("down")))
    degraded = asyncio.run(LangGraphOrchestrator(demo_mode=True).analyze("Bengaluru", None))

    assert degraded.coordinator.overall_score == baseline.coordinator.overall_score
    assert degraded.coordinator.confidence == baseline.coordinator.confidence
    assert [run.status for run in degraded.runs] == [run.status for run in baseline.runs]


def test_graph_exposes_the_enrichment_node():
    from agents.langgraph_orchestrator import LangGraphOrchestrator

    graph = LangGraphOrchestrator(demo_mode=True)._graph.get_graph()
    node_ids = set(graph.nodes)
    assert "context_enrichment" in node_ids
    # It hangs off triage, in the same parallel wave as the specialist investigators.
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("triage_environment", "context_enrichment") in edges
    assert ("context_enrichment", "coordinate") in edges


def test_a_stalled_overpass_cannot_stall_the_analysis(monkeypatch):
    """Regression: the Coordinator fan-in waits on the enrichment node.

    Observed live against a busy Overpass, an unbounded node hung the whole assessment for over
    120 s — past the frontend's own 30 s limit. Enrichment is optional; the assessment is not.
    """
    import threading
    import time as _time

    from agents import langgraph_orchestrator as lg

    # An Overpass call that never comes back on its own. The event lets the test release the
    # worker thread afterwards, instead of leaving it to be joined at interpreter shutdown.
    release = threading.Event()

    def _stalls(*_args, **_kwargs):
        release.wait(30)
        return GeographicContext(available=True, status="ok")  # far too late to be used

    monkeypatch.setattr(lg, "resolve_geographic_context", _stalls)
    # Settings is a frozen dataclass, so swap the module's reference rather than the attribute.
    monkeypatch.setattr(lg, "settings", _PatchedSettings(lg.settings, overpass_context_timeout_seconds=0.2))

    # A plain loop, not asyncio.run(): run_until_complete returns as soon as the graph finishes,
    # which is exactly what a request handler experiences. asyncio.run would additionally wait for
    # the abandoned worker thread at shutdown, which uvicorn never does.
    loop = asyncio.new_event_loop()
    try:
        started = _time.perf_counter()
        result = loop.run_until_complete(lg.LangGraphOrchestrator(demo_mode=False).analyze("Bengaluru", None))
        elapsed = _time.perf_counter() - started
    finally:
        release.set()
        loop.close()

    assert elapsed < 10, f"analysis waited {elapsed:.1f}s on an unresponsive Overpass"
    assert result.geographic_context.available is False
    assert result.geographic_context.status == "unavailable"
    assert "timed out" in (result.geographic_context.message or "")
    # The assessment itself still completed.
    assert result.coordinator is not None


def test_the_context_timeout_stays_under_the_frontend_analysis_timeout():
    """A node timeout above the client's own limit would be no protection at all."""
    from config import settings as real_settings

    # frontend/src/services/apiClient.ts gives POST /api/analyze 30 s.
    assert 0 < real_settings.overpass_context_timeout_seconds <= 15


def test_both_overpass_services_share_one_request_budget():
    """Overpass rate-limits the client, not the code path.

    An analysis can want both nearby water bodies and geographic context. With a throttle each,
    the two would spend two slots per second between them; sharing one keeps the process to a
    single outstanding request.
    """
    from services.overpass_service import NearbyWaterService, OverpassThrottle

    slept = []
    now = [100.0]
    shared = OverpassThrottle(min_interval_s=1.0, clock=lambda: now[0], sleep=slept.append)

    water = NearbyWaterService(StubOverpass(), throttle=shared)
    context = GeographicContextService(StubOverpass(), throttle=shared)

    water.nearby(*BENGALURU)
    now[0] += 0.3
    context.context(*BENGALURU)  # a different service, but the same budget

    assert slept == [pytest.approx(0.7)]


def test_the_factories_hand_out_the_same_throttle():
    from services import overpass_service

    assert (
        overpass_service.get_nearby_water_service().throttle
        is overpass_service.get_geographic_context_service().throttle
    )


def test_a_directly_constructed_service_gets_a_private_throttle():
    """Tests must stay isolated from one another's request history."""
    from services.overpass_service import NearbyWaterService

    assert GeographicContextService(StubOverpass()).throttle is not NearbyWaterService(StubOverpass()).throttle
