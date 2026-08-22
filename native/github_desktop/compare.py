"""Desktop `lib/compare.ts` — sort comparators used across lists."""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def compare(x: T, y: T) -> int:
    """Desktop `compare`: ascending using native less-than / greater-than."""
    if x < y:  # type: ignore[operator]
        return -1
    if x > y:  # type: ignore[operator]
        return 1
    return 0


def compare_descending(x: T, y: T) -> int:
    """Desktop `compareDescending`."""
    if x < y:  # type: ignore[operator]
        return 1
    if x > y:  # type: ignore[operator]
        return -1
    return 0


def case_insensitive_equals(x: str, y: str) -> bool:
    """Desktop `caseInsensitiveEquals`."""
    return x.lower() == y.lower()


def case_insensitive_compare(x: str, y: str) -> int:
    """Desktop `caseInsensitiveCompare`: ascending by ``toLowerCase``."""
    return compare(x.lower(), y.lower())


def case_insensitive_compare_descending(x: str, y: str) -> int:
    """Desktop `caseInsensitiveCompareDescending`."""
    return compare_descending(x.lower(), y.lower())
