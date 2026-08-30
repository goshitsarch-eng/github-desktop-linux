"""Circular avatar with initials fallback and optional GitHub/Gravatar image."""

from __future__ import annotations

import os

_CACHE: dict[str, bytes] = {}
_FAILED: set[str] = set()
MAX_DISPLAYED_AVATARS = 3


def _offline() -> bool:
    if os.environ.get("GITHUB_DESKTOP_OFFLINE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False


def users_from_commit(commit: object, github: object | None = None) -> list[tuple[str, str]]:
    users: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, email: str) -> None:
        key = (name or "", (email or "").lower())
        if key in seen or not (name or email):
            return
        seen.add(key)
        users.append((name or "", email or ""))

    author = getattr(commit, "author", None)
    if author is not None:
        add(getattr(author, "name", "") or "", getattr(author, "email", "") or "")
    for co in getattr(commit, "co_authors", None) or []:
        add(getattr(co, "name", "") or "", getattr(co, "email", "") or "")
    committer = getattr(commit, "committer", None)
    if committer is not None and not getattr(commit, "authored_by_committer", True):
        from ..models import is_web_flow_committer

        cname = getattr(committer, "name", "") or ""
        cemail = getattr(committer, "email", "") or ""
        web_flow = github is not None and is_web_flow_committer(commit, github)
        co_authored = any(
            (getattr(co, "name", "") or "") == cname and (getattr(co, "email", "") or "") == cemail
            for co in getattr(commit, "co_authors", None) or []
        )
        if not web_flow and not co_authored:
            add(cname, cemail)
    return users


def users_from_commits(commits: list[object], github: object | None = None) -> list[tuple[str, str]]:
    users: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        for name, email in users_from_commit(commit, github):
            key = (name, email.lower())
            if key in seen:
                continue
            seen.add(key)
            users.append((name, email))
    return users
