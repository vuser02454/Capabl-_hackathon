"""Dijkstra, the OSM walking graph, and safety-aware routing.

Dijkstra is tested on hand-built graphs where the right answer is known by construction, so a
failure points at the algorithm rather than at OpenStreetMap. Nothing here touches the network:
the Overpass client is driven through an injected opener returning a fixed payload.

The distinction that matters most is tested explicitly: a PUBLISHED alert may bend a worker's
route, and a candidate hotspot may not. Candidates are unreviewed hypotheses that workers never
see, and a route that quietly steered around one would leak its existence through the path.

The other load-bearing assertion is that reported distance is real ground distance. A
safety-aware route's Dijkstra COST is inflated by penalties; telling a worker that inflated number
as "distance" would be a lie about how far they have to walk.
"""

import json
import math
import pytest
from fastapi.testclient import TestClient
from urllib.error import HTTPError, URLError
import io

from safety import llm, routing, store

BENGALURU = (12.9716, 77.5946)


@pytest.fixture(autouse=True)
def _no_llm(monkeypatch):
    monkeypatch.setattr(llm, "available", lambda: False)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "routing.db")
    store.init()
    return tmp_path


@pytest.fixture
def client(db):
    from main import app
    return TestClient(app)


# --- a graph whose answer is known by construction ------------------------------------------
#
#   A(1) --111m-- B(2) --111m-- C(3)        the short way:  A -> B -> C  = 222 m
#    \                          /
#     \------ D(4), far east ---/           the long way:   A -> D -> C  = ~2.2 km

def _diamond() -> routing.RoadGraph:
    graph = routing.RoadGraph()
    graph.add_node(1, 12.9700, 77.5900)
    graph.add_node(2, 12.9710, 77.5900)
    graph.add_node(3, 12.9720, 77.5900)
    graph.add_node(4, 12.9700, 77.6000)
    graph.add_edge(1, 2, "footway")
    graph.add_edge(2, 3, "footway")
    graph.add_edge(1, 4, "footway")
    graph.add_edge(4, 3, "footway")
    return graph


def _metres(_a, _b, metres, _highway):
    return metres


# --- Dijkstra ---------------------------------------------------------------------------------

def test_dijkstra_finds_the_shorter_of_two_routes():
    path, cost = routing.dijkstra(_diamond(), 1, 3, weight=_metres)
    assert path == [1, 2, 3]
    assert 215 < cost < 230


def test_the_reconstructed_path_is_contiguous_in_the_graph():
    graph = _diamond()
    path, _ = routing.dijkstra(graph, 1, 3, weight=_metres)
    for first, second in zip(path, path[1:]):
        assert second in [n for n, _m, _h in graph.adjacency[first]]


def test_path_length_matches_the_sum_of_its_segments():
    graph = _diamond()
    path, cost = routing.dijkstra(graph, 1, 3, weight=_metres)
    # With a pure-distance weight the cost and the ground distance are the same number.
    assert graph.path_length_meters(path) == pytest.approx(cost, rel=1e-9)


def test_start_equals_destination_is_a_zero_length_route():
    assert routing.dijkstra(_diamond(), 1, 1, weight=_metres) == ([1], 0.0)


def test_an_unreachable_destination_returns_no_path_rather_than_raising():
    graph = _diamond()
    graph.add_node(99, 13.5, 78.5)        # island: added but never connected
    path, cost = routing.dijkstra(graph, 1, 99, weight=_metres)
    assert path == []
    assert cost == math.inf


def test_an_unknown_node_is_not_routable():
    assert routing.dijkstra(_diamond(), 1, 12345, weight=_metres) == ([], math.inf)


def test_an_impassable_edge_forces_the_long_way_round():
    graph = _diamond()

    def blocked(a, b, metres, _highway):
        return None if {a, b} in ({1, 2}, {2, 3}) else metres

    path, _ = routing.dijkstra(graph, 1, 3, weight=blocked)
    assert path == [1, 4, 3]


def test_blocking_every_route_reports_no_path():
    graph = _diamond()
    path, cost = routing.dijkstra(graph, 1, 3, weight=lambda *_args: None)
    assert path == []
    assert cost == math.inf


def test_weights_and_not_hop_count_decide_the_route():
    """Two cheap hops must beat one expensive hop.

    Exercised through the weight function rather than through geometry: with haversine distances
    the triangle inequality guarantees a direct edge is never longer than a detour, so only a
    non-metric cost (which is exactly what safety weighting is) can distinguish the two.
    """
    graph = _diamond()
    graph.add_edge(1, 3, "primary")       # one direct hop, made expensive below

    def cost(_a, b, metres, highway):
        return metres * (20 if highway == "primary" else 1)

    path, _ = routing.dijkstra(graph, 1, 3, weight=cost)
    assert path == [1, 2, 3]              # three nodes, and still the cheaper route


# --- nearest node -----------------------------------------------------------------------------

def test_nearest_node_snaps_to_the_closest_point():
    graph = _diamond()
    found = graph.nearest_node(12.97005, 77.5900)
    assert found is not None and found[0] == 1
    assert found[1] < 20


def test_a_point_far_from_the_network_cannot_be_snapped():
    # A point in the middle of nowhere has no walkable node, and that is a real answer.
    assert _diamond().nearest_node(13.9, 78.9) is None


def test_the_snap_limit_is_respected():
    graph = _diamond()
    assert graph.nearest_node(12.9700, 77.5900, max_meters=1) is not None
    assert graph.nearest_node(12.9705, 77.5900, max_meters=10) is None


# --- graph construction from OSM --------------------------------------------------------------

OSM_PAYLOAD = {
    "elements": [
        {"type": "way", "id": 10, "nodes": [1, 2, 3], "tags": {"highway": "footway"},
         "geometry": [{"lat": 12.9700, "lon": 77.5900},
                      {"lat": 12.9710, "lon": 77.5900},
                      {"lat": 12.9720, "lon": 77.5900}]},
        # Shares node 3, so the two ways join into one connected network.
        {"type": "way", "id": 11, "nodes": [3, 4], "tags": {"highway": "residential"},
         "geometry": [{"lat": 12.9720, "lon": 77.5900},
                      {"lat": 12.9730, "lon": 77.5900}]},
    ]
}


def test_a_way_becomes_a_chain_of_edges():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    assert graph.node_count == 4
    assert graph.edge_count == 3


def test_ways_sharing_a_node_form_one_connected_network():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    path, _ = routing.dijkstra(graph, 1, 4, weight=_metres)
    assert path == [1, 2, 3, 4]


def test_edges_are_walkable_in_both_directions():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    assert routing.dijkstra(graph, 4, 1, weight=_metres)[0] == [4, 3, 2, 1]


def test_edge_weight_is_the_real_distance_between_its_endpoints():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    _neighbour, metres, highway = graph.adjacency[1][0]
    assert 105 < metres < 118          # 0.001 deg of latitude
    assert highway == "footway"


def test_geometry_points_without_an_osm_id_still_join_the_way():
    """Overpass can return more geometry points than node ids; the way must not fragment."""
    payload = {"elements": [{"type": "way", "id": 1, "nodes": [1],
                             "tags": {"highway": "path"},
                             "geometry": [{"lat": 12.97, "lon": 77.59},
                                          {"lat": 12.971, "lon": 77.59},
                                          {"lat": 12.972, "lon": 77.59}]}]}
    graph = routing.OSMGraphProvider.build_graph(payload)
    assert graph.node_count == 3
    assert graph.edge_count == 2


def test_pedestrian_ways_are_preferred_over_busy_roads():
    # Same length, different highway type: the footway must cost less.
    assert routing._base_cost(100, "footway") < routing._base_cost(100, "primary")
    assert routing._base_cost(100, "footway") < routing._base_cost(100, "service")


def test_the_query_excludes_motorways():
    assert "motorway" not in routing.WALKABLE_HIGHWAYS
    assert "motorway_link" not in routing.WALKABLE_HIGHWAYS


# --- bounding box ------------------------------------------------------------------------------

def test_the_bounding_box_contains_both_endpoints_with_padding():
    south, west, north, east = routing.bounding_box([BENGALURU, (12.9784, 77.5960)], 600)
    assert south < 12.9716 and north > 12.9784
    assert west < 77.5946 and east > 77.5960


def test_the_box_is_widened_for_longitude_because_degrees_shrink_with_latitude():
    south, west, north, east = routing.bounding_box([(12.97, 77.59)], 1000)
    lat_span, lon_span = north - south, east - west
    assert lon_span > lat_span   # cos(12.97°) < 1, so a metre is more degrees of longitude


# --- the conditional safety rule ------------------------------------------------------------------
#
# The rule under test, in order:
#
#   1. Always run plain Dijkstra.
#   2. If the result comes no closer than ROUTE_SAFETY_RADIUS_METERS to a PUBLISHED alert, return
#      it unchanged and compute nothing else.
#   3. Only if it does, generate alternatives by distance and return the first clear one.
#   4. If none is clear, say so rather than presenting the shortest route as if it passed.
#
# The most important negatives are that no alternative is computed when none is needed, and that
# candidate hotspots and the 1 km hotspot radius play no part whatsoever.

#   A ladder with two ways from 1 to 6:
#     upper  1-2-3-6   shorter, runs along longitude 77.5900
#     lower  1-4-5-6   longer, bows east to 77.5960
#
#   Two constraints shape these numbers, and both are load-bearing:
#     * the branches are ~650 m apart, so one alert cannot reach both under a 500 m radius;
#     * the lower branch is 1.51x the upper, inside MAX_ROUTE_DETOUR_RATIO (1.6), so it is a
#       usable alternative. An earlier fixture made it 2.26x, which the detour limit correctly
#       rejected — proving the limit worked, but leaving nothing to test selection with.
def _ladder() -> routing.RoadGraph:
    graph = routing.RoadGraph()
    for node_id, lat, lon in [(1, 12.9700, 77.5900), (2, 12.9750, 77.5900), (3, 12.9800, 77.5900),
                              (6, 12.9850, 77.5900), (4, 12.9725, 77.5960), (5, 12.9825, 77.5960)]:
        graph.add_node(node_id, lat, lon)
    for a, b in [(1, 2), (2, 3), (3, 6), (1, 4), (4, 5), (5, 6)]:
        graph.add_edge(a, b, "footway")
    return graph


def _alert(lat, lon, radius=150, restricted=False, alert_id=1, title="Oil spill"):
    return {"id": alert_id, "title": title, "severity": "HIGH", "latitude": lat,
            "longitude": lon, "radius_meters": radius, "location_text": "Bay",
            "restricted": restricted}


LADDER_PAYLOAD = {"elements": [
    {"type": "way", "id": 1, "nodes": [1, 2, 3, 6], "tags": {"highway": "footway"},
     "geometry": [{"lat": 12.9700, "lon": 77.5900}, {"lat": 12.9750, "lon": 77.5900},
                  {"lat": 12.9800, "lon": 77.5900}, {"lat": 12.9850, "lon": 77.5900}]},
    {"type": "way", "id": 2, "nodes": [1, 4, 5, 6], "tags": {"highway": "footway"},
     "geometry": [{"lat": 12.9700, "lon": 77.5900}, {"lat": 12.9725, "lon": 77.5960},
                  {"lat": 12.9825, "lon": 77.5960}, {"lat": 12.9850, "lon": 77.5900}]},
]}


# --- radius semantics -------------------------------------------------------------------------

def test_the_route_safety_radius_is_not_the_hotspot_radius():
    """Three different numbers answering three different questions; conflating them is the bug."""
    from safety.geo import HOTSPOT_RADIUS_METERS
    assert routing.ROUTE_SAFETY_RADIUS_METERS == 500
    assert HOTSPOT_RADIUS_METERS == 1000
    assert routing.ROUTE_SAFETY_RADIUS_METERS != HOTSPOT_RADIUS_METERS


def test_an_alert_beyond_the_safety_radius_does_not_intersect():
    graph = _ladder()
    # Well east of both branches — outside the 500 m safety radius.
    found = routing.alerts_intersecting(graph, [1, 2, 3, 6], [_alert(12.9775, 77.6060)])
    assert found == []


def test_an_alert_inside_the_safety_radius_intersects():
    graph = _ladder()
    # 347 m west of the path, measured to the segment it runs along.
    found = routing.alerts_intersecting(graph, [1, 2, 3, 6], [_alert(12.9775, 77.5868)])
    assert len(found) == 1
    assert found[0]["closest_approach_meters"] <= 500


def test_the_alerts_own_radius_does_not_widen_the_check_for_an_ordinary_alert():
    """A 1 km alert circle must not make every route within a kilometre 'unsafe'."""
    graph = _ladder()
    far = _alert(12.9775, 77.6060, radius=1000)       # clear of both branches, drawn 1 km wide
    assert routing.alerts_intersecting(graph, [1, 2, 3, 6], [far]) == []


def test_a_restricted_area_uses_its_own_radius_because_the_area_is_closed():
    graph = _ladder()
    closed = _alert(12.9775, 77.5965, radius=1000, restricted=True)   # 705 m from the path
    found = routing.alerts_intersecting(graph, [1, 2, 3, 6], [closed])
    assert len(found) == 1
    assert found[0]["restricted"] is True


def test_distance_is_measured_to_the_route_not_to_its_nodes():
    """An alert between two widely spaced nodes must not read as further away than it is.

    Node-only measurement put a hazard 71 m from the path at 132 m — past a 100 m threshold, so
    the route would have been declared clear. For a check whose job is to notice a hazard beside
    the route, under-reporting is the dangerous direction.
    """
    graph = routing.RoadGraph()
    graph.add_node(1, 12.9700, 77.5900)
    graph.add_node(2, 12.9800, 77.5900)          # ~1113 m apart
    graph.add_edge(1, 2, "footway")

    midpoint_alert = (12.9750, 77.5868)          # 347 m west, exactly halfway along
    to_nodes = min(routing.haversine_meters(*midpoint_alert, *graph.nodes[n]) for n in (1, 2))
    to_segment = routing.distance_to_route_meters(graph, [1, 2], *midpoint_alert)

    # Node-only measurement puts this hazard outside the 500 m radius; it is inside it.
    assert 640 < to_nodes < 680
    assert 340 < to_segment < 355
    assert to_segment < routing.ROUTE_SAFETY_RADIUS_METERS < to_nodes


def test_a_point_beside_the_end_of_a_segment_is_not_projected_past_it():
    """Clamping matters: without it a point off the end reads as nearer than it is."""
    graph = routing.RoadGraph()
    graph.add_node(1, 12.9700, 77.5900)
    graph.add_node(2, 12.9710, 77.5900)
    graph.add_edge(1, 2, "footway")
    beyond = routing.distance_to_route_meters(graph, [1, 2], 12.9740, 77.5900)  # 333 m past node 2
    assert 320 < beyond < 345


def test_the_safety_radius_is_configurable():
    graph = _ladder()
    alert = [_alert(12.9775, 77.5965)]                # 705 m from the upper path
    assert routing.alerts_intersecting(graph, [1, 2, 3, 6], alert, safety_radius=500) == []
    assert routing.alerts_intersecting(graph, [1, 2, 3, 6], alert, safety_radius=800) != []


# --- Yen's alternatives -------------------------------------------------------------------------

def test_alternatives_are_ordered_by_distance():
    paths = routing.k_shortest_paths(_ladder(), 1, 6, k=4)
    assert [p for p, _d in paths][:2] == [[1, 2, 3, 6], [1, 4, 5, 6]]
    assert paths[0][1] < paths[1][1]


def test_alternatives_are_loopless_and_distinct():
    paths = routing.k_shortest_paths(_ladder(), 1, 6, k=4)
    for path, _distance in paths:
        assert len(path) == len(set(path))
    assert len({tuple(p) for p, _d in paths}) == len(paths)


def test_a_graph_with_one_route_yields_no_alternatives():
    graph = routing.RoadGraph()
    for node_id, lat in [(1, 12.9700), (2, 12.9710), (3, 12.9720)]:
        graph.add_node(node_id, lat, 77.5900)
    graph.add_edge(1, 2, "footway")
    graph.add_edge(2, 3, "footway")
    assert len(routing.k_shortest_paths(graph, 1, 3, k=4)) == 1


def test_the_spur_budget_is_respected():
    # A tiny budget must not hang or raise; it simply returns fewer routes.
    paths = routing.k_shortest_paths(_ladder(), 1, 6, k=4, max_spur_searches=1)
    assert len(paths) >= 1


# --- the conditional rule, end to end -------------------------------------------------------------

def _provider(payload=None, error=None):
    """Stand in for the Overpass client: serves a fixed payload, or raises a transport error."""
    class _Response:
        def read(self):
            return json.dumps(payload or LADDER_PAYLOAD).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    def opener(request, timeout=None):
        if error is not None:
            raise error
        return _Response()

    return routing.OSMGraphProvider(opener=opener, sleep=lambda _s: None,
                                    clock=lambda: 0.0, min_interval_s=0, cache_dir=None)


def _service():
    class _Response:
        def read(self):
            return json.dumps(LADDER_PAYLOAD).encode()
        def __enter__(self):
            return self
        def __exit__(self, *exc):
            return False

    # cache_dir=None is essential: the on-disk cache is keyed by bounding box, so without it a
    # graph built from an earlier version of this fixture is served instead of the current one,
    # and the tests silently assert against geometry that is no longer in the file.
    provider = routing.OSMGraphProvider(opener=lambda r, timeout=None: _Response(),
                                        sleep=lambda _s: None, clock=lambda: 0.0,
                                        min_interval_s=0, cache_dir=None)
    return routing.RoutingService(provider)


START, END = (12.9700, 77.5900), (12.9850, 77.5900)


def test_1_no_alert_at_all_returns_the_plain_dijkstra_route():
    result = _service().route(START, END, [])
    assert result["selected"] == "shortest"
    assert result["adjusted_for_safety"] is False
    # Nothing beyond the first Dijkstra run was computed.
    assert result["alternatives_evaluated"] == 0
    assert result["explanation"] == "Shortest route calculated using Dijkstra."
    assert result["node_path"] == [1, 2, 3, 6]


def test_2_an_alert_outside_the_safety_radius_leaves_the_route_untouched():
    far = _alert(12.9775, 77.6060)                    # clear of both — outside the 500 m radius
    result = _service().route(START, END, [far])
    assert result["selected"] == "shortest"
    assert result["adjusted_for_safety"] is False
    assert result["alternatives_evaluated"] == 0
    assert result["blocking_alerts"] == []
    # The check is reported as having run, so a clear route is visibly clear.
    assert result["nearest_alert_meters"] > routing.ROUTE_SAFETY_RADIUS_METERS


def test_3_an_alert_inside_the_safety_radius_activates_alternative_routing():
    near = _alert(12.9775, 77.5868)                   # 347 m west of the upper path only
    result = _service().route(START, END, [near])
    assert result["adjusted_for_safety"] is True
    assert result["selected"] == "alternative"
    assert result["alternatives_evaluated"] >= 1
    assert [a["title"] for a in result["blocking_alerts"]] == ["Oil spill"]


def test_4_the_next_clear_route_by_distance_is_selected():
    near = _alert(12.9775, 77.5868)
    result = _service().route(START, END, [near])
    assert result["node_path"] == [1, 4, 5, 6]        # the second-shortest route
    assert result["alerts_near_route"] == []
    assert result["explanation"] == (
        "Shortest route entered a published safety-alert radius. "
        "An alternative route was selected.")


def test_4b_the_alternative_is_longer_and_both_distances_are_reported():
    near = _alert(12.9775, 77.5868)
    result = _service().route(START, END, [near])
    assert result["distance_meters"] > result["shortest_distance_meters"]


def test_5_a_blocked_alternative_is_recorded_as_rejected():
    # Two alerts, one on each branch: the lower one is further out, so it is checked and rejected.
    both = [_alert(12.9775, 77.5868, alert_id=1, title="Upper spill"),
            _alert(12.9775, 77.5992, alert_id=2, title="Lower spill")]
    result = _service().route(START, END, both)
    assert result["selected"] == "none_clear"
    titles = [t for entry in result["rejected_routes"] for t in entry["blocked_by"]]
    assert "Upper spill" in titles and "Lower spill" in titles


def test_6_when_nothing_is_clear_the_route_is_not_presented_as_safe():
    both = [_alert(12.9775, 77.5868, alert_id=1), _alert(12.9775, 77.5992, alert_id=2)]
    result = _service().route(START, END, both)
    assert result["found"] is True                    # a route is still shown...
    assert result["selected"] == "none_clear"         # ...but never labelled safe
    assert result["adjusted_for_safety"] is False
    assert result["explanation"] == "No available route avoids the published safety alert."
    assert result["alerts_near_route"] != []


def test_10_the_route_distance_is_identical_with_and_without_a_distant_alert():
    """No alert in range must mean no change at all — not merely a similar route."""
    plain = _service().route(START, END, [])
    with_far_alert = _service().route(START, END, [_alert(12.9710, 77.5941)])
    assert with_far_alert["node_path"] == plain["node_path"]
    assert with_far_alert["distance_meters"] == plain["distance_meters"]


def test_the_avoidance_pass_finds_a_clear_route_the_ordered_alternatives_missed():
    """Yen's alternatives hug the shortest path, so a hazard on the main corridor blocks them all.

    Observed live: three alternatives evaluated, every one still within 100 m of the alert. The
    avoidance pass asks the other question — the shortest route that stays OUT of the alert areas
    — and it is still plain Dijkstra, just over a graph with the hazardous nodes made unavailable.
    """
    graph = _ladder()
    blocker = _alert(12.9775, 77.5868)                # 347 m west of the upper path only
    path, _cost = routing.avoiding_route(graph, 1, 6, [blocker],
                                         routing.ROUTE_SAFETY_RADIUS_METERS)
    assert path == [1, 4, 5, 6]
    assert routing.alerts_intersecting(graph, path, [blocker]) == []


def test_the_avoidance_pass_reports_nothing_when_every_route_is_blocked():
    graph = _ladder()
    both = [_alert(12.9775, 77.5868, alert_id=1), _alert(12.9775, 77.5992, alert_id=2)]
    path, cost = routing.avoiding_route(graph, 1, 6, both, routing.ROUTE_SAFETY_RADIUS_METERS)
    assert path == []
    assert cost == math.inf


def test_the_avoidance_pass_is_a_no_op_without_alerts():
    """It must never run in the ordinary case; with no alerts there is nothing to avoid."""
    path, cost = routing.avoiding_route(_ladder(), 1, 6, [], routing.ROUTE_SAFETY_RADIUS_METERS)
    assert path == []
    assert cost == math.inf


def test_the_ordered_alternative_wins_when_it_is_already_clear():
    """The avoidance pass is a fallback, not the primary path: second-best still wins first."""
    near = _alert(12.9775, 77.5868)
    result = _service().route(START, END, [near])
    assert result["node_path"] == [1, 4, 5, 6]        # the second-shortest route, not a rebuild
    assert result["alternatives_evaluated"] == 1      # only the shortest was rejected


def test_no_safety_penalty_is_applied_to_edge_costs_anywhere():
    """The second-best route must be genuinely second-shortest, not a penalty-warped path."""
    assert not hasattr(routing, "safety_weight")
    assert not hasattr(routing, "DEFAULT_ALERT_PENALTY")


# --- the HTTP endpoint ------------------------------------------------------------------------------

@pytest.fixture
def stub_routing(monkeypatch):
    """Point the endpoint at a stubbed Overpass so no test makes a network call."""
    monkeypatch.setattr(routing, "_SERVICE", _service())
    return routing._SERVICE


def _publish(client, latitude, longitude, radius=150, restricted=False, title="Oil spill"):
    return client.post("/api/admin/announcements", json={
        "title": title, "message": "Avoid the area.", "severity": "HIGH",
        "latitude": latitude, "longitude": longitude, "radius_meters": radius,
        "restricted": restricted, "location_text": "Bay",
    })


def _route(client, **over):
    return client.post("/api/worker/route", json={
        "start": {"latitude": START[0], "longitude": START[1]},
        "destination": {"latitude": END[0], "longitude": END[1]}, **over,
    })


def test_the_endpoint_returns_the_shortest_route_when_nothing_is_near(client, stub_routing):
    body = _route(client).json()
    assert body["found"] is True
    assert body["selected"] == "shortest"
    assert body["adjustedForSafety"] is False
    assert body["alternativesEvaluated"] == 0
    assert body["explanation"] == "Shortest route calculated using Dijkstra."
    assert body["safetyRadiusMeters"] == 500


def test_9_a_published_alert_inside_the_radius_changes_the_route(client, stub_routing, db):
    _publish(client, 12.9775, 77.5868)
    body = _route(client).json()
    assert body["adjustedForSafety"] is True
    assert body["selected"] == "alternative"
    assert body["nodePath"] == [1, 4, 5, 6]


def test_8_an_unpublished_announcement_does_not_affect_the_route(client, stub_routing, db):
    """Only PUBLISHED rows may influence routing; a draft must be inert."""
    store.create_announcement({
        "title": "Draft alert", "message": "Not published yet.", "severity": "HIGH",
        "latitude": 12.9775, "longitude": 77.5868, "radius_meters": 150,
        "location_text": "Bay", "status": "DRAFT",
    })
    body = _route(client).json()
    assert body["selected"] == "shortest"
    assert body["nodePath"] == [1, 2, 3, 6]
    assert body["blockingAlerts"] == []


def test_7_a_candidate_hotspot_does_not_affect_the_route(client, stub_routing, db):
    """The privacy boundary, expressed as routing behaviour.

    A PENDING_REVIEW hotspot sits directly on the shortest path, with the 1 km hotspot radius.
    It must neither appear in the response nor change the route — a detour around an unreviewed
    candidate would tell the worker it exists, which is what review is meant to prevent.
    """
    store.upsert_hotspot({
        "latitude": 12.9750, "longitude": 77.5900, "radius_meters": 1000, "report_count": 3,
        "primary_hazard": "Oil spill", "related_hazards": [], "risk_level": "HIGH",
        "first_report_at": None, "latest_report_at": None, "report_ids": [1, 2, 3],
        "locations": [], "explanation": "", "flag_source": "ai_detected",
        "status": "PENDING_REVIEW",
    })
    body = _route(client).json()
    assert body["selected"] == "shortest"
    assert body["adjustedForSafety"] is False
    assert body["nodePath"] == [1, 2, 3, 6]
    assert body["alertsNearRoute"] == []
    assert "reports under review are never used" in body["note"].lower()


def test_the_safety_radius_can_be_overridden_per_request(client, stub_routing, db):
    _publish(client, 12.9775, 77.5965)                # 705 m from the upper path
    default = _route(client).json()
    assert default["selected"] == "shortest"          # 500 m: out of range, route untouched
    assert default["blockingAlerts"] == []

    widened = _route(client, safety_radius_meters=800).json()
    # At 800 m the alert reaches both branches, so nothing can be cleared — but the shortest route
    # is now correctly identified as affected, which is what the wider radius is being tested for.
    assert widened["blockingAlerts"] != []
    assert widened["selected"] != "shortest"


def test_an_out_of_range_safety_radius_is_rejected(client, stub_routing):
    assert _route(client, safety_radius_meters=-5).status_code == 422
    assert _route(client, safety_radius_meters=99999).status_code == 422


def test_map_data_failure_is_a_503_with_an_explanation(client, monkeypatch):
    monkeypatch.setattr(routing, "_SERVICE",
                        routing.RoutingService(_provider(error=URLError("down"))))
    response = _route(client)
    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "Map data is unavailable" in body["error"]["message"]


# --- provenance: a generated line must never be presented as map data ------------------------------
#
# Regression for a real incident. The Overpass timeout had been cut to 12 s while a genuine query
# for a city block measures ~21 s, so every request timed out and a fabricated straight-line
# lattice took over — and was then labelled "Dijkstra over 95 OpenStreetMap nodes". The deployed
# app drew a perfectly straight line across a dense street grid and called it a mapped route.

def test_the_overpass_timeout_is_long_enough_for_a_real_query():
    """12 s was below the measured cost of a real city-block query and made failure the norm."""
    assert routing.OSMGraphProvider().timeout >= 25


def test_mirrors_are_tried_so_one_slow_host_does_not_force_an_estimate():
    provider = routing.OSMGraphProvider()
    endpoints = provider._endpoints()          # noqa: SLF001 — asserting the fallback order
    assert endpoints[0] == provider.endpoint
    assert len(endpoints) >= 2
    assert len(set(endpoints)) == len(endpoints)


def test_a_real_graph_is_labelled_openstreetmap():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    assert graph.source == "openstreetmap"


def test_the_fallback_graph_is_labelled_estimated():
    graph = routing.build_fallback_graph((12.97, 77.59), (12.98, 77.60))
    # The attribute exists so no caller can describe this geometry without knowing what it is.
    assert graph.source == "estimated"


def test_a_route_over_the_fallback_never_claims_openstreetmap():
    graph = routing.build_fallback_graph((12.9700, 77.5900), (12.9800, 77.5900))
    start = graph.nearest_node(12.9700, 77.5900)[0]
    end = graph.nearest_node(12.9800, 77.5900)[0]
    path, _cost = routing.dijkstra(graph, start, end)

    described = routing.RoutingService._describe(  # noqa: SLF001
        graph, path, [], routing.ROUTE_SAFETY_RADIUS_METERS)

    assert described["geometry_source"] == "estimated"
    # Naming OpenStreetMap is fine — saying it was UNREACHABLE is the explanation. What must
    # never appear is the claim that the route was computed over it.
    assert "Dijkstra over an OpenStreetMap" not in described["algorithm"]
    assert "generated here" in described["algorithm"]
    assert "do not follow roads" in described["algorithm"]
    # And it says so in words a worker can act on, rather than only in a machine field.
    assert described["estimate_warning"]
    assert "does not follow roads" in described["estimate_warning"]


def test_a_route_over_real_map_data_says_so_and_carries_no_warning():
    graph = routing.OSMGraphProvider.build_graph(OSM_PAYLOAD)
    path, _cost = routing.dijkstra(graph, 1, 4)
    described = routing.RoutingService._describe(  # noqa: SLF001
        graph, path, [], routing.ROUTE_SAFETY_RADIUS_METERS)

    assert described["geometry_source"] == "openstreetmap"
    assert "Dijkstra over an OpenStreetMap" in described["algorithm"]
    assert described["estimate_warning"] is None


def test_the_graph_stats_expose_the_source_beside_the_node_count():
    """A node count printed without its source is what made an invented lattice read as mapped."""
    graph = routing.build_fallback_graph((12.97, 77.59), (12.98, 77.60))
    stats = routing.graph_stats(graph, 0, 0)
    assert stats["source"] == "estimated"
    assert "nodes" in stats


def test_the_fallback_is_a_straight_corridor_not_a_road_network():
    """Documents what the fallback actually is, so nobody mistakes it for routing.

    Its length tracks the straight-line distance almost exactly. A real road route does not —
    the live KR Puram route measured 1.48x its straight line, while the fabricated one measured
    1.00x, which is what gave the incident away on screen.
    """
    start, destination = (13.02965, 77.69455), (13.02768, 77.68218)
    graph = routing.build_fallback_graph(start, destination)
    path, _cost = routing.dijkstra(graph, graph.nearest_node(*start)[0],
                                   graph.nearest_node(*destination)[0])
    straight = routing.haversine_meters(*start, *destination)
    assert graph.path_length_meters(path) / straight < 1.05


# --- the fetch budget scales with the distance asked for --------------------------------------
#
# The supported range spans a city block to a 20 km cross-city walk, and Overpass cost scales
# with the area. Measured live: 1.4 km apart fetches ~2,700 nodes in ~4 s; 18.5 km apart fetches
# ~64,000 nodes in ~22 s. One fixed budget cannot serve both — and exceeding it does not fail
# loudly, it silently produces a direct-line estimate, which is the defect this guards.

def test_the_limit_supports_a_twenty_kilometre_walk():
    assert routing.MAX_SPAN_METERS == 20_000


def test_a_long_route_gets_a_bigger_budget_than_a_short_one():
    provider = routing.OSMGraphProvider()
    short = provider.timeout_for(1_400)
    long = provider.timeout_for(18_500)
    assert long > short
    # The long case measured ~22 s; the budget must leave real headroom, not just clear it.
    assert long >= 60


def test_the_budget_is_clamped_at_both_ends():
    provider = routing.OSMGraphProvider()
    # A tiny query still gets enough to survive a loaded day.
    assert provider.timeout_for(50) >= routing.MIN_FETCH_TIMEOUT_S
    # And nothing holds a worker on a spinner indefinitely.
    assert provider.timeout_for(20_000) <= routing.MAX_FETCH_TIMEOUT_S


def test_the_server_side_query_budget_matches_the_client_one():
    """Overpass aborts on its own `[timeout:N]`, so a larger client budget alone achieves nothing."""
    provider = routing.OSMGraphProvider()
    box = routing.bounding_box([(13.0075, 77.6959), (12.8452, 77.6602)])
    query = provider._overpass_ql(box, 75.0)      # noqa: SLF001
    assert "[timeout:75]" in query


def test_a_journey_beyond_the_limit_is_refused_before_anything_is_fetched():
    service = routing.RoutingService(_provider())
    with pytest.raises(routing.RoutingError, match="limited to 20 km"):
        service.route((13.0, 77.6), (12.5, 77.2))
