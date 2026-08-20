"""Linux Flatpak spawn/path helpers (Desktop `lib/helpers/linux.ts`)."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from typing import Any


def is_flatpak_build() -> bool:
    """Desktop `isFlatpakBuild`: `__LINUX__ && process.env.FLATPAK_HOST === '1'`."""
    return os.environ.get("FLATPAK_HOST") == "1"


def convert_to_flatpak_path(path: str) -> str:
    """Desktop `convertToFlatpakPath`.

    Node `path.join('/var/run/host', path)` discards the prefix when `path` is
    absolute, so `/usr/bin/code` stays `/usr/bin/code`. Relative paths are
    joined under `/var/run/host`.
    """
    if path.startswith("/opt/") or path.startswith("/var/lib/flatpak"):
        return path
    if os.path.isabs(path):
        return path
    return os.path.join("/var/run/host", path)


def format_working_directory_for_flatpak(path: str) -> str:
    """Desktop `formatWorkingDirectoryForFlatpak`: replace the first whitespace with a space."""
    for index, char in enumerate(path):
        if char.isspace():
            return path[:index] + " " + path[index + 1 :]
    return path


def format_path_for_flatpak(path: str) -> str:
    """Desktop `formatPathForFlatpak`."""
    prefix = "/var/lib/flatpak/app/"
    if path.startswith("/var/lib/flatpak/app"):
        return path.replace(prefix, "", 1)
    return path


def path_exists(path: str) -> bool:
    """Desktop `pathExists`: convert for Flatpak, then check the filesystem."""
    candidate = convert_to_flatpak_path(path) if is_flatpak_build() else path
    try:
        return os.path.exists(candidate)
    except OSError:
        return False


def spawn(path: str, args: Sequence[str] = (), **options: Any) -> subprocess.Popen:
    """Desktop `spawn`: `flatpak-spawn --host` when running as a Flatpak."""
    if is_flatpak_build():
        return subprocess.Popen(["flatpak-spawn", "--host", path, *args], **options)
    return subprocess.Popen([path, *args], **options)


def spawn_editor(path: str, working_directory: str, **options: Any) -> subprocess.Popen:
    """Desktop `spawnEditor`."""
    if is_flatpak_build():
        actual = format_path_for_flatpak(path)
        cwd = format_working_directory_for_flatpak(working_directory)
        return subprocess.Popen(["flatpak-spawn", "--host", actual, cwd], **options)
    return subprocess.Popen([path, working_directory], **options)
