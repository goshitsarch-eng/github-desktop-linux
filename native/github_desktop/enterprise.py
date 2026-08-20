"""Validate a GitHub Enterprise sign-in URL (Desktop `enterprise-validate-url`)."""

from __future__ import annotations

import re
from urllib.parse import urlparse

INVALID_URL_ERROR_NAME = "invalid-url"  # Desktop `InvalidURLErrorName`
INVALID_PROTOCOL_ERROR_NAME = "invalid-protocol"  # Desktop `InvalidProtocolErrorName`
_DOTCOM_SIGN_IN = re.compile(r"^(?:https://)?(?:api\.)?github\.com(?:$|/)", re.I)


class EnterpriseURLError(ValueError):
    """Desktop `validateURL` failure (`error.name` is `invalid-url` or `invalid-protocol`)."""

    def __init__(self, message: str, name: str) -> None:
        super().__init__(message)
        self.name = name


def validate_url(address: str) -> str:
    """Desktop `validateURL`: require a non-empty https Enterprise address."""
    trimmed = address.strip()
    if not trimmed:
        raise EnterpriseURLError("Unknown address", INVALID_URL_ERROR_NAME)

    parsed = urlparse(trimmed)
    if not parsed.hostname:
        address = f"https://{trimmed}"
        parsed = urlparse(address)
    else:
        address = trimmed

    if not parsed.scheme:
        raise EnterpriseURLError("Invalid URL", INVALID_URL_ERROR_NAME)
    if parsed.scheme != "https":
        raise EnterpriseURLError("Invalid protocol", INVALID_PROTOCOL_ERROR_NAME)
    return address


def is_github_dotcom_address(url: str) -> bool:
    """Desktop sign-in-store: github.com in the Enterprise URL field redirects to dotcom."""
    return bool(_DOTCOM_SIGN_IN.match((url or "").strip()))
