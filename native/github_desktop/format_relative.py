"""Desktop `lib/format-relative.ts` plus RelativeTime presentation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .format_date import format_date

SECOND = 1000
MINUTE = SECOND * 60
HOUR = MINUTE * 60
DAY = HOUR * 24
MAX_INTERVAL = 2147483647


def _format_en_us_auto(value: int, unit: str) -> str:
    """``Intl.RelativeTimeFormat('en-US', { numeric: 'auto' })``."""
    abs_value = abs(value)
    past = value < 0
    if unit == "second" and abs_value == 0:
        return "now"
    if unit == "day" and abs_value == 1:
        return "yesterday" if past else "tomorrow"
    if unit == "month" and abs_value == 1:
        return "last month" if past else "next month"
    if unit == "year" and abs_value == 1:
        return "last year" if past else "next year"
    noun = unit if abs_value == 1 else f"{unit}s"
    if past:
        return f"{abs_value} {noun} ago"
    return f"in {abs_value} {noun}"


def format_relative(ms: float) -> str:
    """Desktop `formatRelative(ms)` using the time-elements thresholds.

    Lifted and adopted from
    https://github.com/github/time-elements/blob/428b02c9/src/relative-time.ts#L57
    """
    sign = -1 if ms < 0 else 1
    sec = round(abs(ms) / 1000)
    minutes = round(sec / 60)
    hr = round(minutes / 60)
    day = round(hr / 24)
    month = round(day / 30)
    year = round(month / 12)
    if sec < 45:
        return _format_en_us_auto(sec * sign, "second")
    if minutes < 45:
        return _format_en_us_auto(minutes * sign, "minute")
    if hr < 24:
        return _format_en_us_auto(hr * sign, "hour")
    if day < 30:
        return _format_en_us_auto(day * sign, "day")
    if month < 18:
        return _format_en_us_auto(month * sign, "month")
    return _format_en_us_auto(year * sign, "year")


def get_relative_time_info_from_date(
    then: datetime,
    only_relative: bool = True,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Desktop `getRelativeTimeInfoFromDate` (RelativeTime)."""
    current = now or datetime.now(timezone.utc)
    if getattr(then, "tzinfo", None) is None:
        then = then.replace(tzinfo=timezone.utc)
    if getattr(current, "tzinfo", None) is None:
        current = current.replace(tzinfo=timezone.utc)
    diff = (then - current).total_seconds() * 1000
    duration = abs(diff)
    absolute_text = format_date(then, date_style="full", time_style="short")
    relative_text = format_relative(diff)
    if diff > 0 and duration > MINUTE:
        return {
            "absolute_text": absolute_text,
            "relative_text": format_date(then, date_style="medium", time_style="short"),
            "duration": duration,
        }
    if duration < MINUTE:
        return {
            "absolute_text": absolute_text,
            "relative_text": "just now",
            "duration": MINUTE - duration,
        }
    if duration < HOUR:
        return {"absolute_text": absolute_text, "relative_text": relative_text, "duration": MINUTE}
    if duration < DAY:
        return {"absolute_text": absolute_text, "relative_text": relative_text, "duration": HOUR}
    if duration < 7 * DAY:
        return {"absolute_text": absolute_text, "relative_text": relative_text, "duration": 6 * HOUR}
    if only_relative:
        return {"absolute_text": absolute_text, "relative_text": relative_text, "duration": 6 * HOUR}
    return {
        "absolute_text": absolute_text,
        "relative_text": format_date(then, date_style="medium", time_style=""),
        "duration": None,
    }
