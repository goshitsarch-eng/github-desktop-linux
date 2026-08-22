"""Infer the remote last-push time (Desktop `infer-last-push-for-repository.ts`)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from .errors import APIError
from .github.api import GitHubAPI
from .logging import get_logger
from .models import Account, Repository
from .remote_parsing import match_github_repository

log = get_logger()


def _parse_pushed_at(value: str | None) -> float | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.timestamp()


def infer_last_push_for_repository(
    accounts: Sequence[Account],
    repo: Repository,
    current_remote_url: str | None = None,
) -> float | None:
    """Desktop `inferLastPushForRepository`: `pushed_at` from the GitHub API.

    Prefers the current remote when it matches an account, then the associated
    `GitHubRepository`. Returns a unix timestamp, or `None` if unknown.
    """
    account: Account | None = None
    owner = ""
    name = ""
    if current_remote_url:
        matched = match_github_repository(accounts, current_remote_url)
        if matched is not None:
            owner, name, account = matched.owner, matched.name, matched.account
    if account is None and repo.github is not None:
        owner, name = repo.github.owner, repo.github.name
        account = next((item for item in accounts if item.endpoint == repo.github.endpoint), None)
    if account is None or not owner or not name:
        return None
    try:
        data = GitHubAPI.from_account(account).get(f"/repos/{owner}/{name}")
    except APIError as exc:
        log.debug("inferLastPushForRepository failed for %s/%s: %s", owner, name, exc)
        return None
    if not isinstance(data, dict):
        return None
    return _parse_pushed_at(data.get("pushed_at"))
