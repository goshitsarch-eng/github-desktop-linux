"""Hex digest of a file on disk (Desktop `getFileHash`)."""

from __future__ import annotations

import hashlib
from typing import Literal

HashKind = Literal["sha1", "sha256"]


def get_file_hash(path: str, kind: HashKind = "sha256") -> str:
    """Desktop `getFileHash`: stream the file and return a hex digest."""
    digest = hashlib.sha256() if kind == "sha256" else hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()
