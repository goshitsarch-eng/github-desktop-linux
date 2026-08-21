"""Pick the signed-in account for an API endpoint or GitHub repository.

Desktop `getAccountForEndpoint` (`lib/api.ts`) and
`getAccountForRepository` (`lib/get-account-for-repository.ts`).
"""

from __future__ import annotations

from collections.abc import Sequence

from .models import Account, Repository


def get_account_for_endpoint(accounts: Sequence[Account], endpoint: str | None) -> Account | None:
    """Desktop `getAccountForEndpoint`: first account whose API endpoint matches."""
    if not endpoint:
        return None
    return next((account for account in accounts if account.endpoint == endpoint), None)


def get_account_for_repository(accounts: Sequence[Account], repository: Repository) -> Account | None:
    """Desktop `getAccountForRepository`: account for `repository.gitHubRepository.endpoint`."""
    github = repository.github
    if github is None:
        return None
    return get_account_for_endpoint(accounts, github.endpoint)
