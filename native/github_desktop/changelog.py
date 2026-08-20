"""Release notes from changelog.json, with a bundled fallback for the current version."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .version import __version__

# Mirrors changelog.json["releases"]["3.5.4"] so notes work without the Electron tree.
CURRENT_NOTES = [
    "[Fixed] Update Git LFS to 3.7.1 to address CVE-2025-26625",
    "[Fixed] Check run status icons in the re-run checks dialog have a status tooltip that is accessible by screenreaders - #21191",
    "[Fixed] The Whitespace hint popover appears when right-clicking diff lines while \"Hide whitespace changes\" is enabled - #20848. Thanks @zekariasasaminew!",
    "[Fixed] The cancel button in the sign-in dialog is enabled after sign-in attempt - #21144. Thanks @zekariasasaminew!",
    "[Fixed] The \"Update Email\" button in the \"Misattributed Commit\" popover works after login from a different account - #21176",
    "[Fixed] Improve host discovery when using authenticating proxies - #19039 #19120",
    "[Fixed] Fix diff search results highlights not visible on addition hunks - #21134",
    "[Fixed] Add Copilot commit message generation to context menu - #21000. Thanks @zekariasasaminew!",
    "[Fixed] Override system accent color for checkboxes and radio buttons - #21088",
    "[Improved] The icon contrast on the pull request check run button meets minimum 3:1 contrast requirements - #21189",
    "[Improved] Increased title bar height on macOS Tahoe - #21135. Thanks @berkcebi!",
    "[Improved] Display line change count in PR Preview Dialog - #21126. Thanks @iammola!",
    "[Improved] Allow users to skip commit message override confirmation - #21025. Thanks @ilyassesalama!",
    "[Improved] Allow generating commits with Copilot in non-GitHub repositories - #20698. Thanks @schroedermarius!",
]


def _changelog_paths() -> list[Path]:
    here = Path(__file__).resolve()
    env = os.environ.get("GITHUB_DESKTOP_CHANGELOG", "")
    candidates = [
        Path(env) if env else None,
        here.parents[2] / "changelog.json",  # workspace root (github-desktop-linux/changelog.json)
        here.parent / "data" / "changelog.json",
        Path("/usr/share/github-desktop/changelog.json"),
    ]
    return [p for p in candidates if p is not None]


def load_release_notes(version: str | None = None) -> tuple[str, list[str]]:
    """Return (version, note lines) for a Desktop release, newest stable notes if unknown."""
    wanted = version or __version__
    for path in _changelog_paths():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        releases = data.get("releases") or {}
        notes = releases.get(wanted)
        if notes:
            return wanted, list(notes)
        for ver, items in releases.items():
            if items and "beta" not in ver and "test" not in ver:
                return ver, list(items)
    if wanted == __version__ or version is None:
        return __version__, list(CURRENT_NOTES)
    return wanted, list(CURRENT_NOTES)
