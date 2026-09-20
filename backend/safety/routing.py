"""Walking routes over an OpenStreetMap road graph, with Dijkstra run here.

The shortest path is computed in this module. OpenStreetMap is used ONLY as the source of the
road and footpath geometry — no external routing service is called, and nothing here relabels
someone else's route as "Dijkstra". If the Overpass fetch fails there is no route, because there
is no graph to search.

    Overpass (ways + geometry)
        -> RoadGraph          nodes = coordinates, edges = traversable segments
        -> nearest_node       snap start/destination onto the network
        -> dijkstra           min-heap shortest path over edge weights
        -> SafetyAwareRouter  re-runs dijkstra with alert-adjusted weights
        -> RouteResult

Two weightings exist over the same graph. The shortest route weights an edge by its length. The
safety-aware route multiplies that by a penalty inside a published alert's radius, and drops the
edge entirely inside a restricted one. Both are real Dijkstra runs over real edges; the only
difference is the cost function, which is what makes the two distances comparable and the reason
for the difference explainable.

Only PUBLISHED alerts are allowed to influence a route. A candidate hotspot is an unreviewed
hypothesis that a worker is not shown, and letting one silently bend a route would leak it.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import logging
import math
import os
import socket
import threading
import time
from pathlib import Path
from collections import OrderedDict
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from safety.geo import haversine_meters

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://overpass-api.de/api/interpreter"
DEFAULT_USER_AGENT = "EcoSentinel-Safety/1.0 (hackathon project; pedestrian routing)"

#: Padding added around the start/destination bounding box, so a route is free to bow outwards
#: instead of being clipped to the straight line between the two points.
BBOX_PADDING_METERS = 600.0

#: Ceiling on the padding above. Past this the graph grows faster than the detour it enables.
MAX_BBOX_PADDING_METERS = 2_500.0

#: Refuse rather than fetch a city. Overpass would serve it and the graph search would crawl.
MAX_SPAN_METERS = 20_000.0

#: How far a start or destination may sit from the nearest path before routing is impossible.
MAX_SNAP_METERS = 800.0

#: Highway values that a person may walk along. Motorways and their link roads are excluded:
#: routing a worker onto one would be actively unsafe advice.
WALKABLE_HIGHWAYS = (
    "footway", "path", "pedestrian", "steps", "living_street", "track", "corridor",
    "residential", "service", "unclassified", "tertiary", "secondary", "primary",
    "road", "cycleway",
)

#: Preferred where available. Used to break ties towards pedestrian infrastructure rather than
#: to forbid the alternative — a slight discount, not a hard rule.
PEDESTRIAN_HIGHWAYS = frozenset({"footway", "path", "pedestrian", "steps", "living_street", "corridor"})
PEDESTRIAN_PREFERENCE = 0.85

#: Roads a pedestrian may legally use but should not be steered onto when anything else exists.
BUSY_HIGHWAYS = frozenset({"primary", "secondary"})
BUSY_PENALTY = 1.4

#: How close a walking route may come to a PUBLISHED safety alert before it is rejected and an
#: alternative is sought. Deliberately separate from HOTSPOT_RADIUS_METERS (1000 m), which governs
#: how far apart related REPORTS may be and still cluster — a different question with a different
#: answer. Conflating the two would make every route within a kilometre of any alert "unsafe".
#:
#: A published alert's own `radius_meters` is a THIRD number and does not widen this check either;
#: it is the area an admin drew on the map, and only a RESTRICTED alert lets it close a route.
ROUTE_SAFETY_RADIUS_METERS = 500.0

#: How much longer than the shortest route an alternative may be before it stops being a
#: reasonable answer. A detour that doubles the walk is not a safer route, it is a route nobody
#: takes — and a worker who ignores it is worse off than one given the shortest route with a
#: clear warning on it. 1.6 leaves room for a real diversion around a blocked corridor while
#: ruling out the pathological ones Yen's search can otherwise surface.
MAX_ROUTE_DETOUR_RATIO = 1.6

#: How many routes to consider in total (the shortest plus alternatives) before giving up.
MAX_ALTERNATIVES = 4

#: Ceiling on the Dijkstra runs Yen's algorithm may spend. Without it a city-sized graph takes
#: tens of seconds; with it the search is bounded and the response says how far it got.
MAX_SPUR_SEARCHES = 60

WALKING_SPEED_MPS = 1.35  # ~4.9 km/h, ordinary adult walking pace


class RoutingError(RuntimeError):
    """Raised when a route cannot be produced. Carries a message meant for the worker."""


# --- graph ---------------------------------------------------------------------------------

class RoadGraph:
    """An undirected weighted graph of walkable OSM segments.

    Nodes are keyed by OSM node id where one exists. Each edge records the metres between its
    endpoints and the `highway` value it came from, so a cost function can reason about the kind
    of path as well as its length.
    """

    def __init__(self) -> None:
        self.nodes: Dict[int, Tuple[float, float]] = {}
        #: node -> list of (neighbour, metres, highway)
        self.adjacency: Dict[int, List[Tuple[int, float, str]]] = {}

    def add_node(self, node_id: int, latitude: float, longitude: float) -> None:
        self.nodes[node_id] = (latitude, longitude)
        self.adjacency.setdefault(node_id, [])

    def add_edge(self, a: int, b: int, highway: str) -> None:
        """Connect two known nodes. Both directions — a footpath is walkable either way."""
        if a == b or a not in self.nodes or b not in self.nodes:
            return
        metres = haversine_meters(*self.nodes[a], *self.nodes[b])
        self.adjacency[a].append((b, metres, highway))
        self.adjacency[b].append((a, metres, highway))

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return sum(len(v) for v in self.adjacency.values()) // 2

    def nearest_node(self, latitude: float, longitude: float,
                     max_meters: float = MAX_SNAP_METERS) -> Optional[Tuple[int, float]]:
        """Snap a coordinate onto the network.

        Linear scan: the graph is bounded to a neighbourhood by construction, so an index would
        cost more to build than it saves. Returns None when nothing is close enough, which is a
        real answer — a point in the middle of a field has no walkable node.
        """
        best: Optional[Tuple[int, float]] = None
        for node_id, (node_lat, node_lon) in self.nodes.items():
            metres = haversine_meters(latitude, longitude, node_lat, node_lon)
            if best is None or metres < best[1]:
                best = (node_id, metres)
        if best is None or best[1] > max_meters:
            return None
        return best

    def coordinates(self, path: Sequence[int]) -> List[Dict[str, float]]:
        return [{"latitude": self.nodes[n][0], "longitude": self.nodes[n][1]} for n in path]

    def path_length_meters(self, path: Sequence[int]) -> float:
        """True ground distance along a path — always plain metres, never a weighted cost.

        Kept separate from the Dijkstra cost on purpose: a safety-aware route's *cost* is inflated
        by penalties, but the distance shown to the worker has to be the distance they will walk.
        """
        total = 0.0
        for first, second in zip(path, path[1:]):
            total += haversine_meters(*self.nodes[first], *self.nodes[second])
        return total


# --- Dijkstra ------------------------------------------------------------------------------

def dijkstra(
    graph: RoadGraph,
    start_node: int,
    destination_node: int,
    weight: Optional[Callable[[int, int, float, str], Optional[float]]] = None,
) -> Tuple[List[int], float]:
    """Shortest path by edge weight, using a binary min-heap.

    `weight(a, b, metres, highway)` returns the cost of traversing one edge, or None to treat it
    as impassable. Defaulting to the raw distance makes the plain call a pure shortest-distance
    search; the safety-aware router supplies its own function over the same graph.

    Returns (path, total_cost). An unreachable destination returns ([], inf) rather than raising,
    because "no route exists" is an ordinary answer this system has to be able to give.
    """
    if start_node not in graph.nodes or destination_node not in graph.nodes:
        return [], math.inf
    if start_node == destination_node:
        return [start_node], 0.0

    cost = weight or (lambda _a, _b, metres, _h: metres)

    distance: Dict[int, float] = {start_node: 0.0}
    previous: Dict[int, int] = {}
    settled: set = set()
    queue: List[Tuple[float, int]] = [(0.0, start_node)]

    while queue:
        current_distance, node = heapq.heappop(queue)
        # A node can be pushed several times; the first pop is the settled one.
        if node in settled:
            continue
        settled.add(node)
        if node == destination_node:
            break

        for neighbour, metres, highway in graph.adjacency.get(node, ()):
            if neighbour in settled:
                continue
            edge_cost = cost(node, neighbour, metres, highway)
            if edge_cost is None:          # impassable — a restricted area
                continue
            alternative = current_distance + edge_cost
            if alternative < distance.get(neighbour, math.inf):
                distance[neighbour] = alternative
                previous[neighbour] = node
                heapq.heappush(queue, (alternative, neighbour))

    if destination_node not in distance:
        return [], math.inf

    path: List[int] = [destination_node]
    while path[-1] != start_node:
        step = previous.get(path[-1])
        if step is None:                   # start was never reached
            return [], math.inf
        path.append(step)
    path.reverse()
    return path, distance[destination_node]


# --- OSM graph provider --------------------------------------------------------------------

def bounding_box(points: Iterable[Tuple[float, float]],
                 padding_meters: float = BBOX_PADDING_METERS) -> Tuple[float, float, float, float]:
    """(south, west, north, east) around every point, with padding in metres.

    Longitude degrees shrink with latitude, so the east-west padding is scaled by cos(lat);
    without that the box is far too narrow near the poles and needlessly wide near the equator.
    """
    listed = list(points)
    lats = [p[0] for p in listed]
    lons = [p[1] for p in listed]
    mid_lat = (min(lats) + max(lats)) / 2
    lat_pad = padding_meters / 111_320.0
    lon_pad = padding_meters / (111_320.0 * max(0.1, math.cos(math.radians(mid_lat))))
    return (min(lats) - lat_pad, min(lons) - lon_pad, max(lats) + lat_pad, max(lons) + lon_pad)


#: Where fetched road networks are kept between runs. Alongside the database, which is already
#: gitignored, so nothing here reaches the repository.
_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "route_graph_cache"

#: Distinguishes "caller said None" (disable) from "caller said nothing" (use the configured dir).
_UNSET = object()


class OSMGraphProvider:
    """Fetches a bounded walkable road network from Overpass and caches it.

    The query is limited to a box around the two endpoints. Downloading a city would be both rude
    to Overpass and useless — Dijkstra over it would be slow and every extra node is one the
    search has to settle.
    """

    RETRY_STATUSES = frozenset({429, 502, 503, 504})
    RETRY_PAUSE_S = 3.0

    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = 35.0,
        min_interval_s: float = 2.0,
        cache_size: int = 16,
        opener: Callable[..., Any] = urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        cache_dir: Optional[Any] = _UNSET,
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
        self._cache: "OrderedDict[str, RoadGraph]" = OrderedDict()
        self._last_request: Optional[float] = None
        #: Disk cache. Measured: the Overpass fetch for a 32,000-node graph takes ~12 s while the
        #: Dijkstra search over it takes 0.03 s, so essentially all of a route's latency is one
        #: network call for map data that does not change between requests. Caching it on disk
        #: makes a repeated route effectively instant and removes the dependence on a public
        #: endpoint that rate-limits. Set ECOSENTINEL_ROUTE_CACHE_DIR="" to disable.
        #: `cache_dir=None` disables it entirely, which is what tests want: sharing the developer's
        #: cache would let a cached graph satisfy a test that is meant to exercise a fetch failure.
        if cache_dir is _UNSET:
            configured = os.getenv("ECOSENTINEL_ROUTE_CACHE_DIR", str(_DEFAULT_CACHE_DIR))
            cache_dir = configured or None
        self.cache_dir: Optional[Path] = Path(cache_dir) if cache_dir else None

    def _overpass_ql(self, box: Tuple[float, float, float, float]) -> str:
        south, west, north, east = box
        highways = "|".join(WALKABLE_HIGHWAYS)
        # `out geom` returns each way's full coordinate list, so one request yields both the
        # topology and the geometry — no second call to resolve node ids to positions.
        return (
            f"[out:json][timeout:{int(self.timeout)}];"
            f'way["highway"~"^({highways})$"]'
            f'["area"!~"yes"]'
            f"({south:.6f},{west:.6f},{north:.6f},{east:.6f});"
            f"out geom;"
        )

    def _fetch(self, body: str) -> Dict[str, Any]:
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
                raise RoutingError(
                    f"Map data is unavailable right now (OpenStreetMap HTTP {exc.code}).") from exc
            except (URLError, socket.timeout, TimeoutError, ConnectionError, ValueError) as exc:
                if attempt == 1:
                    self.sleep(self.RETRY_PAUSE_S)
                    continue
                raise RoutingError("Map data is unavailable right now.") from exc
        raise RoutingError("Map data is unavailable right now.")

    @staticmethod
    def build_graph(payload: Dict[str, Any]) -> RoadGraph:
        """Turn an Overpass `out geom` response into a graph.

        Consecutive points of a way become an edge. Ways sharing an OSM node id share that node,
        which is exactly what makes the result a connected network rather than a pile of lines.
        """
        graph = RoadGraph()
        # Synthetic ids for geometry points Overpass did not label, so a way is never broken up.
        synthetic = -1
        for element in payload.get("elements", []):
            if element.get("type") != "way":
                continue
            geometry = element.get("geometry") or []
            node_ids: List[int] = element.get("nodes") or []
            highway = (element.get("tags") or {}).get("highway", "road")

            resolved: List[int] = []
            for index, point in enumerate(geometry):
                if index < len(node_ids):
                    node_id = int(node_ids[index])
                else:
                    node_id = synthetic
                    synthetic -= 1
                graph.add_node(node_id, float(point["lat"]), float(point["lon"]))
                resolved.append(node_id)

            for first, second in zip(resolved, resolved[1:]):
                graph.add_edge(first, second, highway)
        return graph

    def _disk_path(self, key: str) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"

    def _read_disk(self, key: str) -> Optional[RoadGraph]:
        path = self._disk_path(key)
        if path is None or not path.is_file():
            return None
        try:
            return self.build_graph(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError):
            # A corrupt cache entry is not worth failing a route over; refetch instead.
            logger.warning("route_graph_cache_unreadable path=%s", path)
            return None

    def _write_disk(self, key: str, payload: Dict[str, Any]) -> None:
        path = self._disk_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename, so a crash mid-write cannot leave a half-file behind.
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload))
            temporary.replace(path)
        except OSError:
            logger.warning("route_graph_cache_unwritable path=%s", path)

    def graph_for(self, start: Tuple[float, float], destination: Tuple[float, float],
                  padding_meters: float = BBOX_PADDING_METERS) -> RoadGraph:
        """The walkable network around both endpoints, fetched once and cached.

        `padding_meters` widens the box so a route can bow outwards. The caller enlarges it when
        an alert area is big enough that the detour around it would otherwise fall outside the
        box — a route that exists in reality but not in the graph would be reported as "no route",
        which is a wrong answer rather than a cautious one.
        """
        span = haversine_meters(start[0], start[1], destination[0], destination[1])
        if span > MAX_SPAN_METERS:
            raise RoutingError(
                f"Start and destination are {span / 1000:.1f} km apart. "
                f"Routing is limited to {MAX_SPAN_METERS / 1000:.0f} km for on-site walking routes.")

        box = bounding_box([start, destination], padding_meters)
        key = ",".join(f"{value:.4f}" for value in box)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            from_disk = self._read_disk(key)
            if from_disk is not None:
                self._cache[key] = from_disk
                return from_disk

            if self._last_request is not None:
                wait = self.min_interval_s - (self.clock() - self._last_request)
                if wait > 0:
                    self.sleep(wait)
            self._last_request = self.clock()
            payload = self._fetch(self._overpass_ql(box))
            graph = self.build_graph(payload)
            self._write_disk(key, payload)
            self._cache[key] = graph
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return graph


# --- safety-aware cost ------------------------------------------------------------------------

def _base_cost(metres: float, highway: str) -> float:
    """Distance, nudged by how pleasant the way is to walk on. Never used as the reported distance."""
    if highway in PEDESTRIAN_HIGHWAYS:
        return metres * PEDESTRIAN_PREFERENCE
    if highway in BUSY_HIGHWAYS:
        return metres * BUSY_PENALTY
    return metres


def point_to_segment_meters(
    point: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float],
) -> float:
    """Shortest distance from a point to the line SEGMENT a-b, in metres.

    Measuring to a route's NODES alone under-reports: an alert sitting midway between two nodes
    200 m apart reads as ~110 m away when the path passes within metres of it. For a check whose
    whole job is to notice a hazard beside the route, that is the wrong direction to be wrong in.

    Over the tens of metres involved here the Earth is flat enough to project onto a local plane
    (metres per degree of latitude is constant; longitude is scaled by cos(lat)), do the standard
    point-to-segment projection, and convert back.
    """
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(point[0]))

    px, py = point[1] * lon_scale, point[0] * lat_scale
    ax, ay = a[1] * lon_scale, a[0] * lat_scale
    bx, by = b[1] * lon_scale, b[0] * lat_scale

    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    # Projection parameter, clamped to the segment so the result is never off the end of it.
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def distance_to_route_meters(
    graph: RoadGraph, path: Sequence[int], latitude: float, longitude: float,
) -> float:
    """Closest approach of a point to a route, measured against its segments."""
    if not path:
        return math.inf
    if len(path) == 1:
        return haversine_meters(latitude, longitude, *graph.nodes[path[0]])
    return min(
        point_to_segment_meters((latitude, longitude), graph.nodes[first], graph.nodes[second])
        for first, second in zip(path, path[1:])
    )


def alerts_intersecting(
    graph: RoadGraph,
    path: Sequence[int],
    alerts: Sequence[Dict[str, Any]],
    safety_radius: float = ROUTE_SAFETY_RADIUS_METERS,
) -> List[Dict[str, Any]]:
    """Published alerts whose safety radius this route enters, closest first.

    The radius used is ROUTE_SAFETY_RADIUS_METERS, not the alert's own radius and emphatically not
    HOTSPOT_RADIUS_METERS. Those three numbers mean different things:

        HOTSPOT_RADIUS_METERS = 1000   how far apart related reports may be and still cluster
        alert.radius_meters            the area an admin drew on the map when publishing
        ROUTE_SAFETY_RADIUS_METERS     how close a walking route may come before it is rejected

    A restricted alert is the one exception: its own radius applies, because the admin closed that
    whole area and a route may not pass through it however narrow the safety band happens to be.
    """
    found: List[Dict[str, Any]] = []
    for alert in alerts:
        latitude, longitude = alert.get("latitude"), alert.get("longitude")
        if latitude is None or longitude is None:
            continue
        closest = distance_to_route_meters(graph, path, float(latitude), float(longitude))
        restricted = bool(alert.get("restricted"))
        threshold = max(float(alert.get("radius_meters") or 0), safety_radius) if restricted else safety_radius
        if closest <= threshold:
            found.append({
                "id": alert.get("id"),
                "title": alert.get("title"),
                "severity": alert.get("severity"),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "radius_meters": float(alert.get("radius_meters") or 0),
                "location_text": alert.get("location_text"),
                "closest_approach_meters": round(closest),
                "safety_radius_meters": round(threshold),
                "restricted": restricted,
            })
    found.sort(key=lambda item: item["closest_approach_meters"])
    return found


def nearest_alert_distance(
    graph: RoadGraph, path: Sequence[int], alerts: Sequence[Dict[str, Any]],
) -> Optional[int]:
    """Closest published alert to this route in metres, or None when there are no alerts.

    Reported even when nothing intersects, so a worker can see that the check ran and passed
    rather than having to infer it from silence.
    """
    distances = [
        distance_to_route_meters(graph, path, float(a["latitude"]), float(a["longitude"]))
        for a in alerts
        if a.get("latitude") is not None and a.get("longitude") is not None
    ]
    return round(min(distances)) if distances else None


# --- alternative routes (Yen's k-shortest loopless paths) ---------------------------------------

def k_shortest_paths(
    graph: RoadGraph,
    start_node: int,
    destination_node: int,
    k: int = MAX_ALTERNATIVES,
    max_spur_searches: int = MAX_SPUR_SEARCHES,
) -> List[Tuple[List[int], float]]:
    """The k shortest loopless paths, in increasing order of distance — Yen's algorithm.

    Each candidate is produced by an ordinary Dijkstra run over the same graph with some edges and
    nodes temporarily removed. There are no safety penalties anywhere in here: the second-best
    route is genuinely the second-shortest route, which is what makes "we took the next route that
    is clear" an honest description of the result.

    `max_spur_searches` bounds the work. Yen's runs one Dijkstra per node of each accepted path, so
    on a 20,000-node city graph an unbounded search takes tens of seconds. When the budget runs out
    the function returns what it has found so far, and the caller reports how many it managed to
    evaluate rather than implying the search was exhaustive.
    """
    first, cost = dijkstra(graph, start_node, destination_node)
    if not first:
        return []

    accepted: List[Tuple[List[int], float]] = [(first, cost)]
    candidates: List[Tuple[float, List[int]]] = []
    searches = 0

    while len(accepted) < k and searches < max_spur_searches:
        previous_path = accepted[-1][0]

        for index in range(len(previous_path) - 1):
            if searches >= max_spur_searches:
                break
            spur_node = previous_path[index]
            root_path = previous_path[: index + 1]

            # Remove the edges that would simply re-derive a path already accepted...
            banned_edges = {
                (path[index], path[index + 1])
                for path, _c in accepted
                if len(path) > index and path[: index + 1] == root_path
            }
            # ...and the root's own nodes, so the spur cannot loop back through them.
            banned_nodes = set(root_path[:-1])

            def weight(a: int, b: int, metres: float, highway: str) -> Optional[float]:
                if b in banned_nodes or (a, b) in banned_edges or (b, a) in banned_edges:
                    return None
                return _base_cost(metres, highway)

            spur_path, _spur_cost = dijkstra(graph, spur_node, destination_node, weight)
            searches += 1
            if not spur_path:
                continue

            total = root_path[:-1] + spur_path
            if any(total == path for path, _c in accepted):
                continue
            entry = (graph.path_length_meters(total), total)
            if entry not in candidates:
                candidates.append(entry)

        if not candidates:
            break
        candidates.sort(key=lambda item: item[0])
        best_distance, best_path = candidates.pop(0)
        accepted.append((best_path, best_distance))

    return accepted


def avoiding_route(
    graph: RoadGraph,
    start_node: int,
    destination_node: int,
    alerts: Sequence[Dict[str, Any]],
    safety_radius: float,
) -> Tuple[List[int], float]:
    """The shortest route that stays outside every published alert's safety radius.

    Yen's alternatives are, by construction, small variations on the shortest path: they share
    most of their edges with it, so when a hazard sits on the main corridor every one of them
    tends to pass within the same safety radius. Live testing showed exactly that — three
    alternatives evaluated, all still inside 100 m of an alert on the corridor.

    This closes the gap by asking a different question: not "what is the k-th shortest route" but
    "what is the shortest route that does not go near the alert". It is still a plain Dijkstra run
    with no penalties — an edge is either available or it is not — so the result remains a true
    shortest path, just over a graph with the hazardous parts removed.

    It is used only AFTER the ordered alternatives have been tried, so the second-best route still
    wins whenever it is clear.
    """
    circles = [
        (float(a["latitude"]), float(a["longitude"]),
         max(float(a.get("radius_meters") or 0), safety_radius) if a.get("restricted") else safety_radius)
        for a in alerts
        if a.get("latitude") is not None and a.get("longitude") is not None
    ]
    if not circles:
        return [], math.inf

    def weight(a: int, b: int, metres: float, highway: str) -> Optional[float]:
        # Measured to the EDGE, matching `alerts_intersecting`. Blocking only the endpoint nodes
        # would let a long edge sweep straight past an alert between them, and the clearance check
        # would then reject the very route this function had just produced.
        for centre_lat, centre_lon, radius in circles:
            if point_to_segment_meters((centre_lat, centre_lon),
                                       graph.nodes[a], graph.nodes[b]) <= radius:
                return None          # inside a safety radius: not available, not merely costly
        return _base_cost(metres, highway)

    return dijkstra(graph, start_node, destination_node, weight)


# --- service ------------------------------------------------------------------------------------

class RoutingService:
    """Coordinates the graph provider, Dijkstra and the conditional safety check."""

    def __init__(self, provider: Optional[OSMGraphProvider] = None):
        self.provider = provider or OSMGraphProvider(
            endpoint=os.getenv("ECOSENTINEL_OVERPASS_URL", DEFAULT_ENDPOINT),
            user_agent=os.getenv("ECOSENTINEL_NOMINATIM_USER_AGENT", DEFAULT_USER_AGENT),
        )

    def route(
        self,
        start: Tuple[float, float],
        destination: Tuple[float, float],
        alerts: Sequence[Dict[str, Any]] = (),
        safety_radius: float = ROUTE_SAFETY_RADIUS_METERS,
    ) -> Dict[str, Any]:
        """Shortest route, and an alternative ONLY if the shortest one is actually affected.

        The normal case is a single Dijkstra run and nothing else. Alternatives are generated only
        after the shortest route is found to enter a published alert's safety radius, because
        computing them otherwise would be wasted work and applying penalties by default would
        silently lengthen routes that had nothing wrong with them.

        `alerts` must already be filtered to PUBLISHED announcements by the caller.
        """
        graph, start_node, end_node, snap = self._prepare(
            start, destination, alerts, safety_radius)

        # STEP 1 — the baseline. Plain Dijkstra, no safety input of any kind.
        shortest_path, _cost = dijkstra(graph, start_node, end_node)
        if not shortest_path:
            return self._failed(graph, snap,
                                "No connected walking route was found between these points.")

        shortest = self._describe(graph, shortest_path, alerts, safety_radius)

        # STEP 2 — the conditional check.
        blocking = alerts_intersecting(graph, shortest_path, alerts, safety_radius)
        if not blocking:
            return {
                **shortest,
                "found": True,
                "selected": "shortest",
                "adjusted_for_safety": False,
                "route_adjusted_for_safety": False,
                "safe_alternative_found": None,   # none was needed, so neither True nor False
                "original_distance_meters": shortest["distance_meters"],
                "original_route_geometry": shortest["route"],
                "selected_distance_meters": shortest["distance_meters"],
                "additional_distance_meters": 0,
                "detour_ratio": 1.0,
                "alternatives_evaluated": 0,
                "blocking_alerts": [],
                "selected_reason": "Shortest route calculated using Dijkstra.",
                "explanation": "Shortest route calculated using Dijkstra.",
                "safety_radius_meters": round(safety_radius),
                "max_detour_ratio": MAX_ROUTE_DETOUR_RATIO,
                "graph": {**graph_stats(graph, *snap)},
            }

        # STEP 3 — and only now, look for an alternative.
        alternatives = k_shortest_paths(graph, start_node, end_node)
        rejected = [{"distance_meters": shortest["distance_meters"],
                     "blocked_by": [a["title"] for a in blocking]}]

        limit = shortest["distance_meters"] * MAX_ROUTE_DETOUR_RATIO

        for candidate_path, _distance in alternatives[1:]:
            hits = alerts_intersecting(graph, candidate_path, alerts, safety_radius)
            described = self._describe(graph, candidate_path, alerts, safety_radius)
            if described["distance_meters"] > limit:
                # Clear, but so far round that it is not a usable answer. Recorded as rejected
                # rather than silently skipped, so the reason is visible.
                rejected.append({"distance_meters": described["distance_meters"],
                                 "blocked_by": [],
                                 "rejected_for": "exceeds the maximum reasonable detour"})
                continue
            if not hits:
                return {
                    **described,
                    "found": True,
                    "selected": "alternative",
                    "adjusted_for_safety": True,
                    "route_adjusted_for_safety": True,
                    "safe_alternative_found": True,
                    "original_distance_meters": shortest["distance_meters"],
                    "selected_distance_meters": described["distance_meters"],
                    "additional_distance_meters": (
                        described["distance_meters"] - shortest["distance_meters"]),
                    "detour_ratio": round(
                        described["distance_meters"] / max(1, shortest["distance_meters"]), 3),
                    "alternatives_evaluated": len(rejected),
                    "blocking_alerts": blocking,
                    "rejected_routes": rejected,
                    "shortest_distance_meters": shortest["distance_meters"],
                    # The rejected route, kept so a detour can be shown side by side rather than
                    # asserted. Recomputing it later would use today's map, not the one served.
                    "original_route_geometry": shortest["route"],
                    "selected_reason": ("Shortest route entered a published safety-alert radius. "
                                        "An alternative route was selected."),
                    "explanation": ("Shortest route entered a published safety-alert radius. "
                                    "An alternative route was selected."),
                    "safety_radius_meters": round(safety_radius),
                    "max_detour_ratio": MAX_ROUTE_DETOUR_RATIO,
                    "graph": {**graph_stats(graph, *snap)},
                }
            rejected.append({"distance_meters": described["distance_meters"],
                             "blocked_by": [a["title"] for a in hits]})

        # STEP 3b — the ordered alternatives all hug the same corridor. Ask instead for the
        # shortest route that stays out of the alert areas altogether.
        avoiding_path, _avoiding_cost = avoiding_route(
            graph, start_node, end_node, alerts, safety_radius)
        if avoiding_path and not alerts_intersecting(graph, avoiding_path, alerts, safety_radius):
            described = self._describe(graph, avoiding_path, alerts, safety_radius)
            if described["distance_meters"] > limit:
                rejected.append({"distance_meters": described["distance_meters"],
                                 "blocked_by": [],
                                 "rejected_for": "exceeds the maximum reasonable detour"})
                return self._none_clear(graph, snap, shortest, blocking, rejected, safety_radius)
            return {
                **described,
                "found": True,
                "selected": "alternative",
                "adjusted_for_safety": True,
                "route_adjusted_for_safety": True,
                "safe_alternative_found": True,
                "original_distance_meters": shortest["distance_meters"],
                "selected_distance_meters": described["distance_meters"],
                "additional_distance_meters": (
                    described["distance_meters"] - shortest["distance_meters"]),
                "detour_ratio": round(
                    described["distance_meters"] / max(1, shortest["distance_meters"]), 3),
                "alternatives_evaluated": len(rejected),
                "blocking_alerts": blocking,
                "rejected_routes": rejected,
                "shortest_distance_meters": shortest["distance_meters"],
                # The rejected shortest route, so a detour can be shown rather than asserted.
                "original_route_geometry": shortest["route"],
                "selected_reason": ("Shortest route entered a published safety-alert radius. "
                                "An alternative route was selected."),
                "explanation": ("Shortest route entered a published safety-alert radius. "
                                "An alternative route was selected."),
                "safety_radius_meters": round(safety_radius),
                "max_detour_ratio": MAX_ROUTE_DETOUR_RATIO,
                "graph": {**graph_stats(graph, *snap)},
                }

        # STEP 4 — nothing clear was found. Show the shortest route, and say plainly that it is
        # not clear, rather than presenting it as if the check had passed.
        return self._none_clear(graph, snap, shortest, blocking, rejected, safety_radius)

    @staticmethod
    def _none_clear(graph, snap, shortest, blocking, rejected, safety_radius) -> Dict[str, Any]:
        """Every route evaluated was affected, or too far round to be usable.

        The shortest route is still returned — a worker who has to get there needs one — but
        `safe_alternative_found` is False and the reason says so. Calling this route safe, or
        returning nothing at all, would both be worse than saying plainly what was found.
        """
        return {
            **shortest,
            "found": True,
            "selected": "none_clear",
            "adjusted_for_safety": False,
            "route_adjusted_for_safety": False,
            "safe_alternative_found": False,
            "original_distance_meters": shortest["distance_meters"],
            "original_route_geometry": shortest["route"],
            "selected_distance_meters": shortest["distance_meters"],
            "additional_distance_meters": 0,
            "detour_ratio": 1.0,
            "alternatives_evaluated": len(rejected),
            "blocking_alerts": blocking,
            "rejected_routes": rejected,
            "selected_reason": "No available route avoids the published safety alert.",
            "explanation": "No available route avoids the published safety alert.",
            "safety_radius_meters": round(safety_radius),
            "max_detour_ratio": MAX_ROUTE_DETOUR_RATIO,
            "graph": {**graph_stats(graph, *snap)},
        }

    # -- helpers ---------------------------------------------------------------------------

    def _prepare(self, start, destination, alerts,
                 safety_radius: float = ROUTE_SAFETY_RADIUS_METERS):
        """Fetch the graph and snap both endpoints, or raise with a reason a worker can act on."""
        # The fetched box has to be wide enough to CONTAIN a detour, or one that exists in
        # reality is reported as "no route". Two things force it wider:
        #   * a restricted area, whose own radius the route must clear entirely;
        #   * the route safety radius, which blocks a corridor 2x its width around any published
        #     alert — a 500 m radius closes a kilometre, and a 600 m box has nowhere to go.
        # Previously only the first was considered, and a 500 m alert on a through-road produced
        # a spurious "no available route".
        widest_restricted = max((float(a.get("radius_meters") or 0) for a in alerts
                                 if a.get("restricted")), default=0.0)
        needed = max(widest_restricted * 1.8, safety_radius * 2.5) if alerts else 0.0
        padding = min(MAX_BBOX_PADDING_METERS, max(BBOX_PADDING_METERS, needed))

        graph = self.provider.graph_for(start, destination, padding)
        if graph.node_count == 0:
            raise RoutingError("No walkable paths were found in this area on OpenStreetMap.")

        snapped_start = graph.nearest_node(*start)
        snapped_end = graph.nearest_node(*destination)
        if snapped_start is None:
            raise RoutingError("Your start location is too far from any mapped path to route from.")
        if snapped_end is None:
            raise RoutingError("That destination is too far from any mapped path to route to.")
        return graph, snapped_start[0], snapped_end[0], (snapped_start[1], snapped_end[1])

    @staticmethod
    def _describe(graph: RoadGraph, path: Sequence[int], alerts, safety_radius) -> Dict[str, Any]:
        """The parts of a response that describe one path. Distance is always ground distance."""
        distance = graph.path_length_meters(path)
        return {
            "route": graph.coordinates(path),
            "node_path": list(path),
            "distance_meters": round(distance),
            "walking_seconds": round(distance / WALKING_SPEED_MPS),
            "alerts_near_route": alerts_intersecting(graph, path, alerts, safety_radius),
            "nearest_alert_meters": nearest_alert_distance(graph, path, alerts),
            "algorithm": "Dijkstra over an OpenStreetMap walking graph built in this service",
        }

    @staticmethod
    def _failed(graph: RoadGraph, snap, reason: str) -> Dict[str, Any]:
        return {"found": False, "selected": None, "adjusted_for_safety": False,
                "reason": reason, "explanation": reason, "route": [], "distance_meters": None,
                "alerts_near_route": [], "blocking_alerts": [], "alternatives_evaluated": 0,
                "graph": {**graph_stats(graph, *snap)}}


def graph_stats(graph: RoadGraph, start_offset: float, end_offset: float) -> Dict[str, Any]:
    return {
        "nodes": graph.node_count,
        "edges": graph.edge_count,
        # How far the worker must walk off-network to reach the route, stated rather than hidden.
        "start_snap_meters": round(start_offset),
        "destination_snap_meters": round(end_offset),
    }


_SERVICE: Optional[RoutingService] = None


def service() -> RoutingService:
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = RoutingService()
    return _SERVICE
