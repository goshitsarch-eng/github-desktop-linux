"""Desktop `lib/clamp.ts`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConstrainedValue:
    """Desktop `IConstrainedValue`."""

    value: float
    min: float = float("-inf")
    max: float = float("inf")


def constrain(
    value: ConstrainedValue | float,
    min_value: float = float("-inf"),
    max_value: float = float("inf"),
) -> ConstrainedValue:
    """Desktop `constrain`: CSS min-width takes precedence over max-width."""
    constrained_max = min_value if max_value < min_value else max_value
    raw = value if isinstance(value, (int, float)) else value.value
    return ConstrainedValue(value=float(raw), min=float(min_value), max=float(constrained_max))


def clamp(
    value: ConstrainedValue | float,
    min_value: float = float("-inf"),
    max_value: float = float("inf"),
) -> float:
    """Desktop `clamp`: coerce a number into ``[min, max]`` inclusive."""
    if not isinstance(value, (int, float)):
        return clamp(value.value, value.min, value.max)
    if value < min_value:
        return min_value
    if value > max_value:
        return max_value
    return value
