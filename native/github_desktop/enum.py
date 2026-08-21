"""Desktop `lib/enum.ts`."""

from __future__ import annotations

from enum import Enum
from typing import Any, Iterable, Mapping, TypeVar

T = TypeVar("T")


def parse_enum_value(enum_obj: Mapping[str, T] | type[Enum] | Iterable[T], value: str) -> T | None:
    """Desktop `parseEnumValue`: match a stored string to an enum value."""
    values: Iterable[Any]
    if isinstance(enum_obj, Mapping):
        values = enum_obj.values()
    elif isinstance(enum_obj, type) and issubclass(enum_obj, Enum):
        values = (member.value for member in enum_obj)
    else:
        values = enum_obj
    for item in values:
        if item == value:
            return item
    return None
