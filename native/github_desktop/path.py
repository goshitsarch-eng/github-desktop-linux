"""Desktop `lib/path.ts` — stay inside a repository root when opening files."""

from __future__ import annotations

import os
from pathlib import Path
from posixpath import abspath as posix_abspath
from posixpath import join as posix_join
from posixpath import normpath as posix_normalize
from ntpath import abspath as win32_abspath
from ntpath import join as win32_join
from ntpath import normpath as win32_normalize


def encode_path_as_url(*path_segments: str) -> str:
    """Desktop `encodePathAsUrl`: resolve and encode as a ``file://`` URL."""
    resolved = os.path.abspath(os.path.join(*path_segments) if path_segments else ".")
    return Path(resolved).as_uri()


def _abspath_join(join, abspath):
    def resolve(*parts: str) -> str:
        return abspath(join(*parts) if parts else ".")

    return resolve


def _resolve_within(
    root_path: str,
    path_segments: list[str],
    *,
    style: str | None = None,
) -> str | None:
    # An empty root path would let all relative paths through.
    if not root_path:
        return None
    if style == "posix":
        join, normalize, resolve = posix_join, posix_normalize, _abspath_join(posix_join, posix_abspath)
    elif style == "win32":
        join, normalize, resolve = win32_join, win32_normalize, _abspath_join(win32_join, win32_abspath)
    else:
        join, normalize, resolve = os.path.join, os.path.normpath, _abspath_join(os.path.join, os.path.abspath)

    normalized_root = normalize(root_path)
    normalized_relative = normalize(join(*path_segments) if path_segments else "")

    # Null bytes has no place in paths.
    if "\0" in normalized_root or "\0" in normalized_relative:
        return None

    resolved = resolve(normalized_root, normalized_relative)
    try:
        real_root = os.path.realpath(normalized_root, strict=True)
        real_resolved = os.path.realpath(resolved, strict=True)
    except (OSError, ValueError):
        return None
    return resolved if real_resolved.startswith(real_root) else None


def resolve_within(root_path: str, *path_segments: str) -> str | None:
    """Desktop `resolveWithin`: absolute path under ``rootPath``, or ``None``."""
    return _resolve_within(root_path, list(path_segments))


def resolve_within_posix(root_path: str, *path_segments: str) -> str | None:
    """Desktop `resolveWithinPosix`."""
    return _resolve_within(root_path, list(path_segments), style="posix")


def resolve_within_win32(root_path: str, *path_segments: str) -> str | None:
    """Desktop `resolveWithinWin32`."""
    return _resolve_within(root_path, list(path_segments), style="win32")
