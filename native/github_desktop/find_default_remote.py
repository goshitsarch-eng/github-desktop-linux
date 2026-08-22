"""Default remote selection (Desktop `findDefaultRemote`)."""

from __future__ import annotations

from typing import Sequence

from .models import Remote


def find_default_remote(remotes: Sequence[Remote]) -> Remote | None:
    """Desktop `findDefaultRemote`: `origin`, else the first remote, else `None`."""
    if not remotes:
        return None
    return next((item for item in remotes if item.name == "origin"), remotes[0])
