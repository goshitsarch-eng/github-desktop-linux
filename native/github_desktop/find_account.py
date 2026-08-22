"""Pick the GitHub account for a clone URL (Desktop `findAccountForRemoteURL`)."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from urllib.parse import urlparse

from .errors import APIError
from .models import Account, html_url_from_endpoint
from .remote_parsing import parse_remote, parse_repository_identifier

CanAccess = Callable[[Account, str, str], bool]


def _account_html_hostname(account: Account) -> str:
    return (urlparse(html_url_from_endpoint(account.endpoint)).hostname or "").lower()


def _sort_accounts(accounts: Sequence[Account]) -> list[Account]:
    """Authenticated GitHub.com, then Enterprise, then anonymous GitHub.com."""

    def key(account: Account) -> tuple[int, int]:
        if account.is_dotcom:
            return (0 if account.token else 2, 0)
        return (1, 0)

    return sorted(accounts, key=key)


def can_access_repository_using_api(account: Account, owner: str, name: str) -> bool:
    """Desktop `canAccessRepositoryUsingAPI`."""
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("GITHUB_DESKTOP_ALLOW_META_PROBE") != "1":
        return False
    try:
        from .github.api import GitHubAPI

        return GitHubAPI.from_account(account).fetch_repository(owner, name) is not None
    except APIError:
        return False


def find_account_for_remote_url(
    url_or_repository_alias: str,
    accounts: Sequence[Account],
    can_access_repository: CanAccess | None = None,
) -> Account | None:
    """Desktop `findAccountForRemoteURL`."""
    all_accounts = [*accounts, Account.anonymous()]
    parsed = parse_remote(url_or_repository_alias)
    if parsed is not None:
        host = (parsed.hostname or "").lower()
        for account in all_accounts:
            if host == _account_html_hostname(account):
                return account
    ident = parse_repository_identifier(url_or_repository_alias)
    if ident is None:
        return None
    probe = can_access_repository or can_access_repository_using_api
    wanted = (ident.hostname or "").lower() or None
    for account in _sort_accounts(all_accounts):
        if wanted is not None and _account_html_hostname(account) != wanted:
            continue
        if probe(account, ident.owner, ident.name):
            return account
    return None
