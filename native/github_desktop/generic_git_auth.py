"""Desktop `lib/generic-git-auth.ts` — generic host username/password."""

from __future__ import annotations

from urllib.parse import urlparse

from .auth import get_key_for_endpoint
from .secrets import (
    GENERIC_GIT_AUTH_USERNAME_KEY_PREFIX,
    delete_generic as delete_generic_host,
    get_generic as get_generic_host,
    get_password,
    set_generic as set_generic_host,
    set_password,
    delete_password,
)


def get_key_for_username(endpoint: str) -> str:
    """Desktop ``genericGitAuth/username/${endpoint}`` localStorage key."""
    return f"{GENERIC_GIT_AUTH_USERNAME_KEY_PREFIX}{endpoint}"


def _host(endpoint: str) -> str:
    raw = endpoint if "://" in endpoint else f"https://{endpoint}"
    return (urlparse(raw).hostname or endpoint).lower()


def get_generic_username(endpoint: str) -> str | None:
    """Desktop `getGenericUsername`."""
    stored = get_password("GitHub Desktop Generic", get_key_for_username(endpoint))
    if stored:
        return stored
    user, _password = get_generic_host(_host(endpoint))
    return user


def set_generic_username(endpoint: str, username: str) -> None:
    """Desktop `setGenericUsername`."""
    set_password("GitHub Desktop Generic", get_key_for_username(endpoint), username)
    set_password("GitHub Desktop Generic", f"username@{_host(endpoint)}", username)


def set_generic_password(endpoint: str, username: str, password: str) -> None:
    """Desktop `setGenericPassword`: TokenStore ``getKeyForEndpoint`` + username."""
    set_password(get_key_for_endpoint(endpoint), username, password)
    set_generic_host(_host(endpoint), username, password)


def set_generic_credential(endpoint: str, username: str, password: str) -> None:
    """Desktop `setGenericCredential`."""
    set_generic_username(endpoint, username)
    set_generic_password(endpoint, username, password)


def get_generic_password(endpoint: str, username: str) -> str | None:
    """Desktop `getGenericPassword`."""
    stored = get_password(get_key_for_endpoint(endpoint), username)
    if stored:
        return stored
    _user, password = get_generic_host(_host(endpoint), username)
    return password


def delete_generic_credential(endpoint: str, username: str) -> None:
    """Desktop `deleteGenericCredential`."""
    delete_password("GitHub Desktop Generic", get_key_for_username(endpoint))
    delete_password(get_key_for_endpoint(endpoint), username)
    delete_generic_host(_host(endpoint), username)
