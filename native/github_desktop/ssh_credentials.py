"""SSH key passphrase and user-password storage (Desktop `ssh-credential-storage`)."""

from __future__ import annotations

from . import secrets
from .get_file_hash import get_file_hash
from .logging import get_logger
from .version import APP_NAME

log = get_logger()

# Legacy single-store key used before Desktop-matching store names.
LEGACY_SSH_SERVICE = "GitHub Desktop SSH"


def get_ssh_credential_store_key(name: str) -> str:
    """Desktop `getSSHCredentialStoreKey`."""
    return f"{APP_NAME} - {name}"


SSH_KEY_PASSPHRASE_STORE = get_ssh_credential_store_key("SSH key passphrases")
SSH_USER_PASSWORD_STORE = get_ssh_credential_store_key("SSH user password")


def get_hash_for_ssh_key(key_path: str) -> str:
    """Desktop `getHashForSSHKey`: SHA-256 of the key file."""
    return get_file_hash(key_path, "sha256")


def lookup_ssh_key_passphrase(key_path: str) -> tuple[str, str, str] | None:
    """Return ``(passphrase, store, key)`` for an SSH key, or None."""
    try:
        digest = get_hash_for_ssh_key(key_path)
        stored = secrets.get_password(SSH_KEY_PASSPHRASE_STORE, digest)
        if stored:
            return stored, SSH_KEY_PASSPHRASE_STORE, digest
    except Exception as exc:
        log.debug("Could not retrieve passphrase for SSH key: %s", exc)
    stored = secrets.get_password(LEGACY_SSH_SERVICE, key_path)
    if stored:
        return stored, LEGACY_SSH_SERVICE, key_path
    return None


def get_ssh_key_passphrase(key_path: str) -> str | None:
    """Desktop `getSSHKeyPassphrase`: look up by key-file hash, then legacy path."""
    found = lookup_ssh_key_passphrase(key_path)
    return found[0] if found else None


def set_ssh_key_passphrase(key_path: str, passphrase: str) -> tuple[str, str]:
    """Store a passphrase keyed by the SHA-256 of the key file.

    Returns ``(store, key)`` for `setMostRecentSSHCredential`.
    """
    try:
        digest = get_hash_for_ssh_key(key_path)
        secrets.set_password(SSH_KEY_PASSPHRASE_STORE, digest, passphrase)
        return SSH_KEY_PASSPHRASE_STORE, digest
    except Exception as exc:
        log.debug("Could not store passphrase for SSH key: %s", exc)
        secrets.set_password(LEGACY_SSH_SERVICE, key_path, passphrase)
        return LEGACY_SSH_SERVICE, key_path


def lookup_ssh_user_password(username: str) -> tuple[str, str, str] | None:
    """Return ``(password, store, key)`` for an SSH user, or None."""
    stored = secrets.get_password(SSH_USER_PASSWORD_STORE, username)
    if stored:
        return stored, SSH_USER_PASSWORD_STORE, username
    stored = secrets.get_password(LEGACY_SSH_SERVICE, username)
    if stored:
        return stored, LEGACY_SSH_SERVICE, username
    return None


def get_ssh_user_password(username: str) -> str | None:
    """Desktop `getSSHUserPassword`."""
    found = lookup_ssh_user_password(username)
    return found[0] if found else None


def set_ssh_user_password(username: str, password: str) -> tuple[str, str]:
    """Desktop `setSSHUserPassword`. Returns ``(store, key)``."""
    secrets.set_password(SSH_USER_PASSWORD_STORE, username, password)
    return SSH_USER_PASSWORD_STORE, username
