"""Credential storage backends.

Order of preference:

1. **KWallet** over D-Bus (``org.kde.kwalletd6``, then ``kwalletd5``). This is
   the native store on a KDE Plasma session and its interface takes only
   simple types, so QtDBus talks to it directly.
2. **Secret Service** through the ``secret-tool`` helper, which covers GNOME
   and any other session running a Secret Service daemon. It is only used when
   the binary is installed; nothing in this process links against it.
3. A ``0600`` JSON file under the config directory, handled by
   :mod:`github_desktop.secrets`.

Every backend exposes the same ``store``/``lookup``/``clear`` triple keyed by
a *service* and an *account*, matching the shape the rest of the app uses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from .logging import get_logger
from .version import APP_ID, APP_NAME

log = get_logger()

KWALLET_SERVICES = (
    ("org.kde.kwalletd6", "/modules/kwalletd6"),
    ("org.kde.kwalletd5", "/modules/kwalletd5"),
)
KWALLET_INTERFACE = "org.kde.KWallet"
SECRET_TOOL = "secret-tool"

_kwallet: Any = None


class KWalletBackend:
    """Talks to ``kwalletd`` over D-Bus.

    Wallet handles are re-opened per operation: kwalletd closes handles when
    the wallet is locked or the daemon restarts, and a stale handle silently
    fails writes.
    """

    def __init__(self, interface: Any) -> None:
        self._interface = interface

    @property
    def name(self) -> str:
        return "kwallet"

    def _call(self, method: str, *args: Any) -> Any:
        from PySide6.QtDBus import QDBusMessage

        reply = self._interface.call(method, *args)
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            raise RuntimeError(f"{method}: {reply.errorMessage()}")
        arguments = reply.arguments()
        return arguments[0] if arguments else None

    def _open(self) -> int:
        wallet = self._call("localWallet")
        if not wallet:
            raise RuntimeError("no local wallet configured")
        # wId 0: kwalletd parents its unlock prompt to the active window.
        handle = int(self._call("open", str(wallet), 0, APP_ID))
        if handle < 0:
            raise RuntimeError(f"could not open wallet {wallet!r}")
        return handle

    def _close(self, handle: int) -> None:
        try:
            self._call("close", handle, False, APP_ID)
        except Exception as exc:  # pragma: no cover - best effort
            log.debug("kwallet close failed: %s", exc)

    def store(self, service: str, account: str, password: str) -> bool:
        handle = self._open()
        try:
            if not bool(self._call("hasFolder", handle, service, APP_ID)):
                self._call("createFolder", handle, service, APP_ID)
            result = int(self._call("writePassword", handle, service, account, password, APP_ID))
            return result == 0
        finally:
            self._close(handle)

    def lookup(self, service: str, account: str) -> str | None:
        handle = self._open()
        try:
            if not bool(self._call("hasEntry", handle, service, account, APP_ID)):
                return None
            value = self._call("readPassword", handle, service, account, APP_ID)
            return str(value) if value else None
        finally:
            self._close(handle)

    def clear(self, service: str, account: str) -> bool:
        handle = self._open()
        try:
            if not bool(self._call("hasEntry", handle, service, account, APP_ID)):
                return True
            return int(self._call("removeEntry", handle, service, account, APP_ID)) == 0
        finally:
            self._close(handle)


class SecretToolBackend:
    """Secret Service access through libsecret's ``secret-tool`` helper."""

    @property
    def name(self) -> str:
        return "secret-service"

    @staticmethod
    def _attributes(service: str, account: str) -> list[str]:
        return ["service", service, "account", account]

    def store(self, service: str, account: str, password: str) -> bool:
        result = subprocess.run(
            [SECRET_TOOL, "store", "--label", f"{service} ({account})", *self._attributes(service, account)],
            input=password,
            text=True,
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0

    def lookup(self, service: str, account: str) -> str | None:
        result = subprocess.run(
            [SECRET_TOOL, "lookup", *self._attributes(service, account)],
            text=True,
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        # secret-tool writes the secret verbatim; only a trailing newline that
        # the shell added is safe to strip.
        return result.stdout.removesuffix("\n") or None

    def clear(self, service: str, account: str) -> bool:
        result = subprocess.run(
            [SECRET_TOOL, "clear", *self._attributes(service, account)],
            text=True,
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0


def _kwallet_backend() -> KWalletBackend | None:
    global _kwallet
    if _kwallet is not None:
        return _kwallet or None
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            _kwallet = False
            return None
        for service, path in KWALLET_SERVICES:
            interface = QDBusInterface(service, path, KWALLET_INTERFACE, bus)
            if interface.isValid():
                _kwallet = KWalletBackend(interface)
                return _kwallet
    except Exception as exc:
        log.debug("kwallet unavailable: %s", exc)
    _kwallet = False
    return None


def reset_backend_cache() -> None:
    """Forget the probed KWallet connection (used by tests)."""
    global _kwallet
    _kwallet = None


def get_backend() -> KWalletBackend | SecretToolBackend | None:
    """Return the best available keyring backend, or None to use the file store."""
    if os.environ.get("GITHUB_DESKTOP_FILE_SECRETS") == "1":
        return None
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return None
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    backend = _kwallet_backend()
    if backend is not None:
        return backend
    if shutil.which(SECRET_TOOL):
        return SecretToolBackend()
    return None


def backend_name() -> str:
    """Human-readable name of the active backend, for Preferences and logs."""
    backend = get_backend()
    if backend is None:
        return "encrypted file"
    return backend.name


__all__ = [
    "APP_NAME",
    "KWalletBackend",
    "SecretToolBackend",
    "backend_name",
    "get_backend",
    "reset_backend_cache",
]
