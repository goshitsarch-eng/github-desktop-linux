"""Desktop `lib/local-storage.ts` — JSON key/value store matching Electron localStorage."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping, Sequence

from .enum import parse_enum_value
from .paths import config_dir

# Default delimiter for stringifying and parsing arrays of numbers
NumberArrayDelimiter = ","

_cache: dict[str, dict[str, str]] = {}


def _path():
    return config_dir() / "local-storage.json"


def _load() -> dict[str, str]:
    path = _path()
    key = str(path)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    store = {str(k): "" if v is None else str(v) for k, v in raw.items()}
    _cache[key] = store
    return store


def _save(store: dict[str, str]) -> None:
    path = _path()
    _cache[str(path)] = store
    path.write_text(json.dumps(store, indent=2), encoding="utf-8")


def get_item(key: str) -> str | None:
    store = _load()
    return store.get(key)


def set_item(key: str, value: str) -> None:
    store = _load()
    store[key] = value
    _save(store)


def remove_item(key: str) -> None:
    store = _load()
    if key in store:
        del store[key]
        _save(store)


def _parse_int(text: str) -> int | None:
    match = re.match(r"^[+-]?\d+", text.strip())
    if not match:
        return None
    return int(match.group(0), 10)


def _parse_float(text: str) -> float | None:
    match = re.match(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", text.strip())
    if not match:
        return None
    try:
        value = float(match.group(0))
    except ValueError:
        return None
    if value != value:  # NaN
        return None
    return value


def get_boolean(key: str, default_value: bool | None = None) -> bool | None:
    """Desktop `getBoolean`. ``'1'``/``'true'`` are true; ``'0'``/``'false'`` are false."""
    value = get_item(key)
    if value is None:
        return default_value
    if value in {"1", "true"}:
        return True
    if value in {"0", "false"}:
        return False
    return default_value


def set_boolean(key: str, value: bool) -> None:
    """Desktop `setBoolean`: stores ``'1'`` or ``'0'``."""
    set_item(key, "1" if value else "0")


def get_number(key: str, default_value: int | None = None) -> int | None:
    """Desktop `getNumber` (`parseInt`)."""
    text = get_item(key)
    if text is None or text == "":
        return default_value
    value = _parse_int(text)
    return default_value if value is None else value


def get_float_number(key: str, default_value: float | None = None) -> float | None:
    """Desktop `getFloatNumber` (`parseFloat`)."""
    text = get_item(key)
    if text is None or text == "":
        return default_value
    value = _parse_float(text)
    return default_value if value is None else value


def set_number(key: str, value: int | float) -> None:
    """Desktop `setNumber`."""
    set_item(key, str(value))


def get_number_array(key: str) -> list[float]:
    """Desktop `getNumberArray`."""
    text = get_item(key) or ""
    values: list[float] = []
    for part in text.split(NumberArrayDelimiter):
        parsed = _parse_float(part)
        if parsed is not None:
            values.append(parsed)
    return values


def set_number_array(key: str, values: Sequence[int | float]) -> None:
    """Desktop `setNumberArray`."""
    set_item(key, NumberArrayDelimiter.join(str(v) for v in values))


def get_string_array(key: str) -> list[str]:
    """Desktop `getStringArray`."""
    raw = get_item(key) or "[]"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        return []
    return list(parsed)


def set_string_array(key: str, values: Sequence[str]) -> None:
    """Desktop `setStringArray`."""
    set_item(key, json.dumps(list(values)))


def get_enum(key: str, enum_obj: Mapping[str, Any] | type) -> Any | None:
    """Desktop `getEnum`."""
    stored = get_item(key)
    if stored is None:
        return None
    return parse_enum_value(enum_obj, stored)


def get_object(key: str) -> Any | None:
    """Desktop `getObject`."""
    raw = get_item(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_object(key: str, value: object) -> None:
    """Desktop `setObject`."""
    set_item(key, json.dumps(value))
