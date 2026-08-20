"""Commit-email attribution helpers matching Desktop's lib/email.ts."""

from __future__ import annotations

from urllib.parse import urlparse

from .models import Account


def stealth_email_host_for_endpoint(endpoint: str) -> str:
    if "api.github.com" in (endpoint or ""):
        return "users.noreply.github.com"
    try:
        host = urlparse(endpoint).hostname or ""
    except ValueError:
        host = ""
    if host:
        return f"users.noreply.{host}"
    return "users.noreply.github.com"


def stealth_email_for_user(user_id: int, login: str, endpoint: str) -> str:
    return f"{user_id}+{login}@{stealth_email_host_for_endpoint(endpoint)}"


def legacy_stealth_email_for_user(login: str, endpoint: str) -> str:
    return f"{login}@{stealth_email_host_for_endpoint(endpoint)}"


def lookup_preferred_email(account: Account) -> str:
    emails = [e for e in account.emails if e]
    if not emails:
        return stealth_email_for_user(account.id, account.login, account.endpoint)
    stealth_suffix = f"@{stealth_email_host_for_endpoint(account.endpoint)}"
    for email in emails:
        if email.lower().endswith(stealth_suffix.lower()):
            return email
    return emails[0]


def is_attributable_email_for(account: Account, email: str) -> bool:
    """True when a commit with this email would be attributed to the signed-in account."""
    needle = (email or "").strip().lower()
    if not needle:
        return False
    known = {e.strip().lower() for e in account.emails if e}
    if needle in known:
        return True
    return needle in {
        stealth_email_for_user(account.id, account.login, account.endpoint).lower(),
        legacy_stealth_email_for_user(account.login, account.endpoint).lower(),
    }
