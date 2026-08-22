"""Desktop `lib/file-system.ts` — temp paths and partial reads."""

from __future__ import annotations

import os
import secrets as stdlib_secrets
import tempfile


def get_temp_file_path(name: str) -> str:
    """Desktop `getTempFilePath`.

    ``join(tmpdir(), `${name}-${randomBytes(8).toString('hex')}`)``. The file
    itself is not created.
    """
    return os.path.join(tempfile.gettempdir(), f"{name}-{stdlib_secrets.token_hex(8)}")


def read_partial_file(path: str, start: int, end: int) -> bytes:
    """Desktop `readPartialFile`: read ``start`` through inclusive ``end``.

    Node ``createReadStream({ start, end })`` treats ``end`` as inclusive, so
    ``(0, n - 1)`` yields ``n`` bytes.
    """
    if end < start:
        return b""
    length = end - start + 1
    with open(path, "rb") as fh:
        if start:
            fh.seek(start)
        return fh.read(length)
