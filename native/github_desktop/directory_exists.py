"""Desktop `lib/directory-exists.ts`."""

from __future__ import annotations

import os


def directory_exists(path: str) -> bool:
    """Desktop `directoryExists`: path exists and is a directory."""
    try:
        return os.path.isdir(path)
    except OSError:
        return False
