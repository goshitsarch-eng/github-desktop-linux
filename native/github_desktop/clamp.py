"""Desktop `lib/clamp.ts`."""

from __future__ import annotations


def clamp(value: float, min_value: float, max_value: float) -> float:
    """Desktop `clamp`: coerce a number into ``[min, max]`` inclusive."""
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value
