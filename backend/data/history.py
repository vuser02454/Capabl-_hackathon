"""Mock historical series for trend charts and anomaly baselines.

Mirrors frontend/src/services/mock/history.ts. Replace with provider history
(OpenAQ /measurements, sensor time-series store, detection log) when live.
"""

import math
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from core.risk import round_half_up
from core.rng import seeded
from data.locations import Location
from schemas import TrendPoint

# range -> (number of points, hours between points)
RANGES: Dict[str, tuple] = {"24h": (24, 1), "7d": (28, 6), "30d": (30, 24)}


def _ramp(current: float, start_ratio: float, progress: float) -> float:
    return current * (start_ratio + (1 - start_ratio) * progress)


def generate_history(location: Location, range_key: str = "24h") -> List[TrendPoint]:
    if range_key not in RANGES:
        raise ValueError(f"Unsupported range '{range_key}'")

    points, step = RANGES[range_key]
    rng = seeded(f"history:{location['id']}:{range_key}")
    trend = location.get("trend", {})
    air, water, waste = location["air"], location["water"], location["waste"]
    total_waste = waste["plastic"] + waste["paper"] + waste["other"]
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    series: List[TrendPoint] = []
    for i in range(points):
        progress = i / (points - 1)
        hours_ago = (points - 1 - i) * step
        r_air, r_water, r_waste = rng(), rng(), rng()
        latest = i == points - 1
        diurnal = math.sin(2 * math.pi * hours_ago / 24)

        pm25: Optional[float] = None
        if air.get("pm25") is not None:
            pm25 = air["pm25"] if latest else round_half_up(
                _ramp(air["pm25"], trend.get("air", 0.75), progress)
                * (1 + 0.1 * diurnal)
                * (1 + (r_air - 0.5) * 0.18),
                1,
            )

        turbidity: Optional[float] = None
        if water.get("turbidity") is not None:
            turbidity = water["turbidity"] if latest else round_half_up(
                _ramp(water["turbidity"], trend.get("water", 0.75), progress)
                * (1 + (r_water - 0.5) * 0.3),
                1,
            )

        waste_count = total_waste if latest else int(
            round_half_up(
                _ramp(total_waste, trend.get("waste", 0.75), progress) * (1 + (r_waste - 0.5) * 0.4),
                0,
            )
        )

        series.append(
            TrendPoint(
                hours_ago=hours_ago,
                timestamp=now - timedelta(hours=hours_ago),
                pm25=pm25,
                turbidity=turbidity,
                waste_count=waste_count,
            )
        )
    return series
