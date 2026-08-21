"""Desktop `lib/format-date.ts` — en-US date formatting."""

from __future__ import annotations

from datetime import datetime


def format_date(when: datetime | None, *, date_style: str = "full", time_style: str = "short") -> str:
    """Desktop `formatDate` in the en-US locale.

    Invalid dates become ``Invalid date``. Default options match
    ``dateStyle: 'full'`` and ``timeStyle: 'short'``.
    """
    if when is None:
        return "Invalid date"
    try:
        local = when.astimezone() if getattr(when, "tzinfo", None) else when
        if date_style == "full" and time_style == "short":
            return f"{local.strftime('%A, %B')} {local.day}, {local.strftime('%Y at %-I:%M %p')}"
        if date_style == "medium" and time_style == "short":
            return f"{local.strftime('%b')} {local.day}, {local.strftime('%Y, %-I:%M %p')}"
        return local.strftime("%c")
    except (OSError, OverflowError, ValueError, TypeError):
        return "Invalid date"
