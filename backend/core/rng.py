"""Deterministic pseudo-random helpers.

The frontend (src/lib/rng.ts) implements the same algorithms bit-for-bit, so demo
mode in the browser and the FastAPI backend produce identical mock outputs.
"""

from typing import Callable

MASK32 = 0xFFFFFFFF


def fnv1a(text: str) -> int:
    """32-bit FNV-1a hash of a UTF-8 string."""
    value = 0x811C9DC5
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 0x01000193) & MASK32
    return value


def mulberry32(seed: int) -> Callable[[], float]:
    """Small seeded PRNG returning floats in [0, 1)."""
    state = seed & MASK32

    def next_float() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK32
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK32
        t = t ^ ((t + (((t ^ (t >> 7)) * (t | 61)) & MASK32)) & MASK32)
        return ((t ^ (t >> 14)) & MASK32) / 4294967296

    return next_float


def seeded(key: str) -> Callable[[], float]:
    return mulberry32(fnv1a(key))
