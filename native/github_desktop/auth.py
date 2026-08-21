"""Desktop `lib/auth.ts` — TokenStore keys for GitHub accounts."""

from __future__ import annotations

import os
from typing import Any


def _token_store_app_name() -> str:
    # Desktop: `const appName = __DEV__ ? 'GitHub Desktop Dev' : 'GitHub'`
    if os.environ.get("GITHUB_DESKTOP_DEV"):
        return "GitHub Desktop Dev"
    return "GitHub"


def get_key_for_endpoint(endpoint: str) -> str:
    """Desktop `getKeyForEndpoint`: ``${appName} - ${endpoint}``."""
    app_name = _token_store_app_name()
    return f"{app_name} - {endpoint}"


def get_key_for_account(account: Any) -> str:
    """Desktop `getKeyForAccount`: TokenStore key for the account endpoint."""
    return get_key_for_endpoint(getattr(account, "endpoint", "") or "")
