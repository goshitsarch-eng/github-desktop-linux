"""Release notes from changelog.json, with a bundled fallback for the current version."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .version import APP_NAME, __version__

# Desktop `getChangeLog` in `lib/release-notes.ts`.
CHANGELOG_URL = "https://central.github.com/deployments/desktop/desktop/changelog.json"

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


def get_change_log(limit: int | None = 250) -> list[dict[str, Any]]:
    """Desktop `getChangeLog` — remote changelog.json, empty on failure or offline."""
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
        return []
    parsed = urllib.parse.urlparse(CHANGELOG_URL)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    if limit is not None:
        query["limit"] = str(limit)
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    req = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": f"{APP_NAME}/{__version__}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, UnicodeDecodeError):
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        releases = data.get("releases")
        if isinstance(releases, dict):
            return [
                {"version": str(ver), "notes": list(notes or [])}
                for ver, notes in releases.items()
                if isinstance(notes, list)
            ]
    return []


def notes_from_changelog(releases: list[dict[str, Any]] | None = None) -> list[str]:
    """Flatten `notes` arrays from Desktop `ReleaseMetadata` entries."""
    items = releases if releases is not None else get_change_log(250)
    notes: list[str] = []
    for item in items:
        for line in item.get("notes") or []:
            if isinstance(line, str):
                notes.append(line)
    return notes
