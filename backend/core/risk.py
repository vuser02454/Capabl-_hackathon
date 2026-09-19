"""Shared risk-scoring primitives used by every agent."""

import math
from typing import Iterable

MODERATE_THRESHOLD = 0.40
HIGH_THRESHOLD = 0.70


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def round_half_up(value: float, digits: int = 2) -> float:
    """Round like JavaScript's Math.round so backend and frontend agree."""
    factor = 10 ** digits
    return math.floor(value * factor + 0.5) / factor


def risk_level_for(score: float) -> str:
    if score >= HIGH_THRESHOLD:
        return "HIGH"
    if score >= MODERATE_THRESHOLD:
        return "MODERATE"
    return "LOW"


def join_and(items: Iterable[str]) -> str:
    values = list(items)
    if len(values) <= 1:
        return "".join(values)
    return ", ".join(values[:-1]) + " and " + values[-1]


def format_number(value: float) -> str:
    """91.0 -> '91', 27.4 -> '27.4' (matches JS String(number))."""
    return str(int(value)) if float(value).is_integer() else str(value)
