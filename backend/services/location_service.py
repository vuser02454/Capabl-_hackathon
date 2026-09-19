"""Central location resolution.

Every analysis starts with exactly one LocationContext (live browser GPS or a preset
monitoring area). Agents receive that context; none of them parse coordinates or
call a geocoder themselves. Precise coordinates are never logged or persisted.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple

from config import settings
from core.errors import InvalidLocationError
from core.geo import haversine_km, offset_point, valid_coordinates
from data.locations import Location, get_location
from schemas import GeographicContext, GeographicFeature, LocationContext

# Demo sites further than this from the analysis location are replaced by a
# clearly labelled simulated site near the user.
DEMO_SITE_RADIUS_KM = 50.0


def context_from_profile(profile: Location) -> LocationContext:
    return LocationContext(
        latitude=profile["lat"],
        longitude=profile["lon"],
        display_name=f"{profile['name']}, {profile['region']}, India",
        city=profile["name"],
        state=profile["region"],
        country="India",
        source="preset",
        geocoding="preset",
        preset_id=profile["id"],
        timestamp=datetime.now(timezone.utc),
    )


def resolve_location(name: Optional[str], context: Optional[LocationContext]) -> LocationContext:
    """Build the analysis LocationContext from a request."""
    if context is not None:
        if not valid_coordinates(context.latitude, context.longitude):
            raise InvalidLocationError("Location coordinates are invalid.")
        return context
    if name:
        return context_from_profile(get_location(name))
    raise InvalidLocationError("Please choose a location to analyze.")


def location_label(context: LocationContext) -> str:
    """Short human-readable name used in reports and the coordinator's reasoning."""
    if context.city:
        return context.city
    if context.neighbourhood:
        return context.neighbourhood
    if context.display_name:
        return context.display_name.split(",")[0].strip()
    return "Your location"


def demo_site(
    context: LocationContext,
    site_lat: Optional[float],
    site_lon: Optional[float],
    north_km: float,
    east_km: float,
) -> Tuple[float, float, bool]:
    """Return (lat, lon, simulated) for a demo site relative to the analysis location."""
    if site_lat is not None and site_lon is not None:
        if haversine_km(context.latitude, context.longitude, site_lat, site_lon) <= DEMO_SITE_RADIUS_KM:
            return site_lat, site_lon, False
    lat, lon = offset_point(context.latitude, context.longitude, north_km, east_km)
    return lat, lon, True


# --------------------------------------------------------------------------- geographic context

#: Overpass category -> the GeographicContext field it fills.
_CONTEXT_FIELDS = {
    "industrial": "industrial_features",
    "waste": "waste_facilities",
    "waterway": "waterways",
    "road": "roads",
}


def resolve_geographic_context(
    latitude: float,
    longitude: float,
    radius_m: Optional[int] = None,
    per_category: Optional[int] = None,
) -> GeographicContext:
    """What OpenStreetMap has MAPPED around a point. Never raises, never scores anything.

    This is descriptive enrichment: it answers "what is around here?", not "is it polluted?".
    A mapped factory is a polygon somebody drew, not an emission — so every failure mode
    (Overpass off, unreachable, rate-limited, malformed) returns `available=False` with a
    reason rather than an exception, and the analysis carries on with whatever it has.
    """
    # Imported here so this module stays importable when Overpass is switched off entirely.
    from services.overpass_service import OverpassUnavailable, get_geographic_context_service

    if not settings.overpass_enabled:
        return GeographicContext(
            available=False,
            status="disabled",
            message="Geographic context lookup is switched off on this backend.",
        )
    if not valid_coordinates(latitude, longitude):
        return GeographicContext(
            available=False, status="unavailable", message="Location coordinates are invalid."
        )

    try:
        grouped, radius, cached = get_geographic_context_service().context(
            latitude, longitude, radius_m, per_category
        )
    except (OverpassUnavailable, InvalidLocationError) as exc:
        return GeographicContext(available=False, status="unavailable", message=exc.message)
    except Exception:  # a context lookup must never be able to fail an analysis
        return GeographicContext(
            available=False, status="unavailable", message="Geographic context is unavailable right now."
        )

    fields = {
        field: [GeographicFeature(**feature.as_dict()) for feature in grouped.get(category, [])]
        for category, field in _CONTEXT_FIELDS.items()
    }
    total = sum(len(values) for values in fields.values())
    return GeographicContext(
        available=total > 0,
        status="ok",
        radius_m=radius,
        cached=cached,
        message=None
        if total
        else f"No mapped industrial, waste, waterway or major-road features within {radius} m.",
        **fields,
    )
