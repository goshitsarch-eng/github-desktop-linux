"""Strip `origin/` from a ref (Desktop `removeRemotePrefix`)."""

from __future__ import annotations

import re

_PREFIX = re.compile(r".*?/(.*)")


def remove_remote_prefix(name: str) -> str | None:
    """Desktop `removeRemotePrefix`: `origin/a/b` → `a/b`; no slash → `None`."""
    match = _PREFIX.match(name)
    if match is None:
        return None
    return match.group(1)
