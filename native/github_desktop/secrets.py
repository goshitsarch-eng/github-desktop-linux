"""Secret Service (libsecret) token storage with a file fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .logging import get_logger
from .paths import config_dir

log = get_logger()
SERVICE = "GitHub Desktop"
GENERIC_SERVICE = "GitHub Desktop Generic"


def _file_store() -> Path:
    path = config_dir() / "secrets.json"
    return path


def _read_file() -> dict[str, dict[str, str]]:
    path = _file_store()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_file(data: dict[str, dict[str, str]]) -> None:
    path = _file_store()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _secret_schema():
    try:
        import gi

        gi.require_version("Secret", "1")
        from gi.repository import Secret

        return Secret.Schema.new(
            "io.github.desktop.GitHubDesktop",
            Secret.SchemaFlags.NONE,
            {
                "service": Secret.SchemaAttributeType.STRING,
                "account": Secret.SchemaAttributeType.STRING,
            },
        )
    except Exception:
        return None


def _use_libsecret() -> bool:
    if os.environ.get("GITHUB_DESKTOP_FILE_SECRETS") == "1":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return False
    return _secret_schema() is not None


def set_password(service: str, account: str, password: str) -> None:
    if _use_libsecret():
        schema = _secret_schema()
        try:
            from gi.repository import Secret

            Secret.password_store_sync(
                schema,
                {"service": service, "account": account},
                Secret.COLLECTION_DEFAULT,
                f"{service} ({account})",
                password,
                None,
            )
            return
        except Exception as exc:
            log.debug("libsecret store failed, using file: %s", exc)
    data = _read_file()
    data.setdefault(service, {})[account] = password
    _write_file(data)


def get_password(service: str, account: str) -> str | None:
    if _use_libsecret():
        schema = _secret_schema()
        try:
            from gi.repository import Secret

            value = Secret.password_lookup_sync(schema, {"service": service, "account": account}, None)
            if value:
                return value
        except Exception as exc:
            log.debug("libsecret lookup failed: %s", exc)
    data = _read_file()
    return data.get(service, {}).get(account)


def delete_password(service: str, account: str) -> None:
    if _use_libsecret():
        schema = _secret_schema()
        try:
            from gi.repository import Secret

            Secret.password_clear_sync(schema, {"service": service, "account": account}, None)
        except Exception as exc:
            log.debug("libsecret delete failed: %s", exc)
    data = _read_file()
    if service in data and account in data[service]:
        del data[service][account]
        _write_file(data)


def set_token(login_endpoint: str, token: str) -> None:
    set_password(SERVICE, login_endpoint, token)


def get_token(login_endpoint: str) -> str | None:
    return get_password(SERVICE, login_endpoint)


def delete_token(login_endpoint: str) -> None:
    delete_password(SERVICE, login_endpoint)


def set_generic(host: str, username: str, password: str) -> None:
    set_password(GENERIC_SERVICE, f"{username}@{host}", password)
    set_password(GENERIC_SERVICE, f"username@{host}", username)


def get_generic(host: str, username: str | None = None) -> tuple[str | None, str | None]:
    if username:
        return username, get_password(GENERIC_SERVICE, f"{username}@{host}")
    stored_user = get_password(GENERIC_SERVICE, f"username@{host}")
    if stored_user:
        return stored_user, get_password(GENERIC_SERVICE, f"{stored_user}@{host}")
    return None, None


def delete_generic(host: str, username: str) -> None:
    """Desktop `deleteGenericCredential`."""
    delete_password(GENERIC_SERVICE, f"{username}@{host}")
    stored_user = get_password(GENERIC_SERVICE, f"username@{host}")
    if stored_user == username:
        delete_password(GENERIC_SERVICE, f"username@{host}")
