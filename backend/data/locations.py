"""Location registry backed by shared/locations.json (also used by the frontend)."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.errors import InvalidLocationError, NoMonitoringDataError
from core.geo import haversine_km

SHARED_LOCATIONS = Path(__file__).resolve().parents[2] / "shared" / "locations.json"

Location = Dict[str, Any]


def _normalise(name: str) -> str:
    return " ".join(name.strip().lower().replace("-", " ").replace("_", " ").split())


@lru_cache(maxsize=1)
def _registry() -> Dict[str, Any]:
    return json.loads(SHARED_LOCATIONS.read_text(encoding="utf-8"))


def list_locations() -> List[Location]:
    return list(_registry()["locations"])


def get_location(name: str) -> Location:
    """Resolve a user-supplied location name, raising a typed error when unsupported."""
    key = _normalise(name or "")
    if not key:
        raise InvalidLocationError("Please choose a location to analyze.")

    for location in _registry()["locations"]:
        names = [location["id"], location["name"], *location.get("aliases", [])]
        if key in {_normalise(n) for n in names}:
            return location

    for uncovered in _registry()["noCoverage"]:
        if key == _normalise(uncovered):
            raise NoMonitoringDataError(
                f"No monitoring stations are deployed in {uncovered} yet."
            )

    raise InvalidLocationError(f"'{name.strip()}' is not a recognised monitoring location.")


def find_profile(profile_id: str) -> Optional[Location]:
    return next((loc for loc in _registry()["locations"] if loc["id"] == profile_id), None)


def nearest_profile(lat: float, lon: float) -> Tuple[Location, float]:
    """Closest demo profile to a coordinate (used only by demo providers and demo history)."""
    distances = [(loc, haversine_km(lat, lon, loc["lat"], loc["lon"])) for loc in _registry()["locations"]]
    return min(distances, key=lambda item: item[1])
