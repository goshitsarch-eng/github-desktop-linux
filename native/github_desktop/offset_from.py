"""Millisecond date offsets matching Desktop `lib/offset-from.ts`."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Literal

UNITS_MS: dict[str, int] = {
    "year": 31_536_000_000,
    "years": 31_536_000_000,
    "day": 86_400_000,
    "days": 86_400_000,
    "hour": 3_600_000,
    "hours": 3_600_000,
    "minute": 60_000,
    "minutes": 60_000,
    "second": 1_000,
    "seconds": 1_000,
}

OffsetUnit = Literal[
    "year",
    "years",
    "day",
    "days",
    "hour",
    "hours",
    "minute",
    "minutes",
    "second",
    "seconds",
]


def offset_from(stamp: datetime | float | int, value: int | float, unit: str) -> datetime | float:
    """Desktop `offsetFrom`: shift a Date or epoch-ms value by `value` `unit`s.

    Passing a number returns milliseconds since the epoch. Passing a `datetime`
    returns a `datetime`.
    """
    delta = value * UNITS_MS[unit]
    if isinstance(stamp, datetime):
        millis = stamp.timestamp() * 1000.0 + delta
        return datetime.fromtimestamp(millis / 1000.0, tz=stamp.tzinfo)
    return float(stamp) + delta


def offset_from_now(value: int | float, unit: str) -> float:
    """Desktop `offsetFromNow`: epoch milliseconds offset from `Date.now()`."""
    return float(offset_from(time.time() * 1000.0, value, unit))
