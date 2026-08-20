"""Install the `github` command-line helper (Linux equivalent of Desktop's CLI tool)."""

from __future__ import annotations

import os
import stat
from pathlib import Path


WRAPPER = """#!/usr/bin/env python3
import os
import sys

NATIVE = {native!r}
if NATIVE not in sys.path:
    sys.path.insert(0, NATIVE)
os.environ["PYTHONPATH"] = NATIVE + os.pathsep + os.environ.get("PYTHONPATH", "")

from github_desktop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
"""


def default_install_path() -> Path:
    return Path.home() / ".local" / "bin" / "github"


def native_package_root() -> Path:
    return Path(__file__).resolve().parents[1]


def install_cli(dest: Path | None = None) -> Path:
    """Write a launcher to ~/.local/bin/github and make it executable."""
    path = dest or default_install_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(WRAPPER.format(native=str(native_package_root())), encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def cli_is_installed(dest: Path | None = None) -> bool:
    path = dest or default_install_path()
    return path.is_file() and os.access(path, os.X_OK)
