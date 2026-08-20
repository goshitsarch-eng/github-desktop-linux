"""Thank-you card helpers matching Desktop's `lib/thank-you`."""

from __future__ import annotations

import re

from .changelog import CURRENT_NOTES, load_release_notes
from .version import __version__

# Desktop: /\.\sThanks\s@.+!/i then slice(10, -1) to drop ". Thanks @" and trailing "!".
_THANKS_RE = re.compile(r"\.\sThanks\s@(.+?)!", re.I)


def has_user_already_been_checked_or_thanked(
    version: str,
    checked_users: list[str],
    login: str,
    current_version: str,
) -> bool:
    if not version or not checked_users:
        return False
    return login in checked_users and version == current_version


def contributions_by_user(notes: list[str] | None = None) -> dict[str, list[str]]:
    lines = list(notes) if notes is not None else []
    if notes is None:
        _version, bundled = load_release_notes()
        lines = list(bundled) or list(CURRENT_NOTES)
    by_login: dict[str, list[str]] = {}
    for line in lines:
        match = _THANKS_RE.search(line)
        if match is None:
            continue
        handle = match.group(1)
        by_login.setdefault(handle, []).append(line)
    return by_login


def get_user_contributions(login: str, notes: list[str] | None = None) -> list[str]:
    return list(contributions_by_user(notes).get(login, []))


def thank_you_note(version: str | None = None) -> str:
    suffix = f" {version}" if version else ""
    return (
        f"Thanks so much for all your hard work on GitHub Desktop{suffix}. We're "
        "so grateful for your willingness to contribute and make the app better "
        "for everyone!"
    )


def current_app_version() -> str:
    return __version__
