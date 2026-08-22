"""Desktop `lib/fatal-error.ts` — unwrap helpers and exhaustive checks."""

from __future__ import annotations

from typing import NoReturn, TypeVar

T = TypeVar("T")


def fatal_error(msg: str) -> NoReturn:
    """Desktop `fatalError`: throw an error."""
    raise RuntimeError(msg)


def assert_never(x: object, message: str) -> NoReturn:
    """Desktop `assertNever`: runtime exception for a bypassed exhaustive check."""
    raise RuntimeError(message)


def force_unwrap(message: str, x: T | None) -> T:
    """Desktop `forceUnwrap`: throw when the value is nullish (`== null`).

    ``False`` and ``0`` are expected values and must not throw.
    """
    if x is None:
        return fatal_error(message)
    return x


def assert_non_nullable(x: T | None, message: str) -> T:
    """Desktop `assertNonNullable`."""
    if x is None:
        return fatal_error(message)
    return x
