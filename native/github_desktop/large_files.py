"""Working-directory files larger than GitHub's receive limit (Desktop `large-files.ts`)."""

from __future__ import annotations

import os
from typing import Sequence

from .logging import get_logger
from .models import DiffSelectionType, OVERSIZED_FILE_BYTES, WorkingDirectoryFileChange

log = get_logger()

# Desktop `ReceiveLimit` — 100 MiB.
RECEIVE_LIMIT = OVERSIZED_FILE_BYTES


def get_large_file_paths(
    repo_path: str,
    files: Sequence[WorkingDirectoryFileChange],
    *,
    limit: int = RECEIVE_LIMIT,
) -> list[str]:
    """Desktop `getLargeFilePaths`: included files strictly larger than `limit` bytes."""
    names: list[str] = []
    for file in files:
        if file.selection.get_selection_type() == DiffSelectionType.NONE:
            continue
        full = os.path.join(repo_path, file.path)
        try:
            if os.path.isfile(full) and os.path.getsize(full) > limit:
                names.append(file.path)
        except OSError as exc:
            log.debug("Unable to get the file size for %s: %s", full, exc)
    return names
