"""Reusable geographic helpers. Mirrors frontend/src/lib/geo.ts."""

import math
from typing import Any, Tuple

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two WGS84 points in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def offset_point(lat: float, lon: float, north_km: float, east_km: float) -> Tuple[float, float]:
    """Move a point by a small north/east offset (equirectangular approximation)."""
    new_lat = lat + north_km / 110.574
    new_lon = lon + east_km / (111.320 * math.cos(math.radians(lat)))
    return new_lat, new_lon


def valid_coordinates(lat: Any, lon: Any) -> bool:
    return (
        isinstance(lat, (int, float))
        and isinstance(lon, (int, float))
        and math.isfinite(lat)
        and math.isfinite(lon)
        and -90 <= lat <= 90
        and -180 <= lon <= 180
    )
