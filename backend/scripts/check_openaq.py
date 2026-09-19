"""Smoke-test the OpenAQ integration from the command line.

    cd backend && ../.venv/bin/python scripts/check_openaq.py Bengaluru
    cd backend && ../.venv/bin/python scripts/check_openaq.py 12.9716,77.5946
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import settings  # noqa: E402
from core.errors import EcoSentinelError  # noqa: E402
from schemas import LocationContext  # noqa: E402
from services.location_service import resolve_location  # noqa: E402
from services.openaq_service import POLLUTANTS, OpenAQProvider  # noqa: E402


def _context(arg: str) -> LocationContext:
    if "," in arg:
        lat, lon = (float(part) for part in arg.split(",", 1))
        return LocationContext(latitude=lat, longitude=lon, source="browser_geolocation")
    return resolve_location(arg, None)


def main() -> int:
    arg = " ".join(sys.argv[1:]) or "Bengaluru"
    if not settings.openaq_api_key:
        print("OPENAQ_API_KEY is not set. Add it to backend/.env (see backend/.env.example).")
        return 1

    provider = OpenAQProvider(
        settings.openaq_api_key,
        radius_m=settings.openaq_radius_m,
        max_age_hours=settings.openaq_max_age_hours,
        fill_max_age_hours=settings.openaq_fill_max_age_hours,
    )
    try:
        location = _context(arg)
        station = provider.nearest_station(location)
        print(f"Best station    : {station.name} (OpenAQ #{station.id})")
        print(f"Distance        : {station.distance_km:.1f} km · reference monitor: {station.is_monitor}")
        print(f"Last update     : {station.datetime_last}")
        print(f"Sensors         : {', '.join(f'{k} [{v[1]}]' for k, v in station.sensors.items())}")

        reading = provider.get_latest(location)
        print("Latest (µg/m³)  :", ", ".join(f"{key}={getattr(reading, key)}" for key in POLLUTANTS))
        print(f"Freshness       : {reading.freshness} ({reading.data_age_minutes} min old)")
        for key, source in reading.sources:
            print(f"Source          : {key} <- {source}{' (delayed)' if key in reading.delayed else ''}")
        for note in reading.notes:
            print("Note            :", note)
        print("24-h PM2.5 mean :", provider.get_pm25_baseline(location))
    except (EcoSentinelError, ValueError) as exc:
        print(f"{getattr(exc, 'code', 'ERROR')}: {getattr(exc, 'message', exc)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
