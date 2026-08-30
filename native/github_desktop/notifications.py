"""Desktop notifications over the freedesktop D-Bus spec, with notify-send fallback.

KDE's notification daemon (Plasma) implements ``org.freedesktop.Notifications``
like every other Linux desktop, so QtDBus is the native path here and
``notify-send`` covers sessions without a running daemon on the bus.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from typing import Any, Callable

from .linux import spawn
from .logging import get_logger
from .mainloop import has_gui, post_or_call
from .version import APP_ID, APP_NAME

log = get_logger()

NOTIFICATION_BUS_NAME = "org.freedesktop.Notifications"
NOTIFICATION_BUS_PATH = "/org/freedesktop/Notifications"

_activation_handler: Callable[[str], None] | None = None
_dbus_notifier: Any = None

NOTIFICATION_SETTINGS_COMMANDS = (
    ("gnome-control-center", "notifications"),
    ("io.elementary.switchboard", "notifications"),
    ("systemsettings", "kcm_notifications"),
    ("unity-control-center", "notifications"),
)

NOTIFY_SEND_DEFAULT_ACTION = "default"


def get_notification_settings_command() -> list[str] | None:
    """Linux stand-in for Desktop `getNotificationSettingsUrl`."""
    for cmd in NOTIFICATION_SETTINGS_COMMANDS:
        if shutil.which(cmd[0]):
            return list(cmd)
    return None


def open_notification_settings() -> None:
    cmd = get_notification_settings_command()
    if cmd:
        spawn(cmd[0], cmd[1:], start_new_session=True)
        return
    spawn("xdg-open", ["settings://"], start_new_session=True)


def get_notifications_permission() -> str:
    """Return `granted`, `denied`, or `default` like Desktop's main-process probe."""
    override = os.environ.get("GITHUB_DESKTOP_NOTIFICATIONS_PERMISSION")
    if override:
        return override
    if shutil.which("notify-send"):
        return "granted"
    if _notifier() is not None:
        return "granted"
    return "default"


def request_notifications_permission() -> str:
    """Desktop `requestNotificationsPermission`: send a probe notification."""
    show_notification(
        "GitHub Desktop",
        "Notifications are enabled for GitHub Desktop.",
        enabled=True,
        notification_id="permission-probe",
    )
    return get_notifications_permission()


def notification_preference_hint(enabled: bool, permission: str | None = None) -> str:
    """Copy from Desktop `preferences/notifications.tsx`."""
    if not enabled:
        return ""
    permission = permission or get_notifications_permission()
    if permission == "default":
        return (
            "You need to grant permission to display these notifications from GitHub Desktop."
        )
    if permission == "denied":
        return (
            "GitHub Desktop has no permission to display notifications. "
            "Please, enable them in the Notifications Settings."
        )
    return (
        "Make sure notifications are properly configured for GitHub Desktop in the "
        "Notifications Settings."
    )


def notify_send_command(title: str, body: str, *, with_action: bool = False) -> list[str]:
    """Build a notify-send argv. GNOME supports `--action=default:Open` and `--wait`."""
    cmd = ["notify-send"]
    if with_action:
        cmd.extend(["--wait", "--action=default:Open"])
    cmd.extend([title, body])
    return cmd


def set_activation_handler(handler: Callable[[str], None] | None) -> None:
    """Install the callback run when the user clicks a notification.

    The Qt application registers its ``open-notification`` route here so this
    module stays free of any UI import.
    """
    global _activation_handler
    _activation_handler = handler


def _activate_open_notification(notification_id: str) -> None:
    def go() -> None:
        handler = _activation_handler
        if handler is None:
            return
        try:
            handler(notification_id or "")
        except Exception as exc:
            log.debug("open-notification activate failed: %s", exc)

    post_or_call(go)


class _DBusNotifier:
    """``org.freedesktop.Notifications`` client with click-through actions.

    Plasma, GNOME, Xfce and the standalone daemons all implement this
    interface, so one code path covers every session that has a notification
    server on the bus. Notifications carry a ``default`` action so clicking the
    popup routes back into the app through :func:`set_activation_handler`.
    """

    def __init__(self, interface: Any) -> None:
        self._interface = interface
        self._ids: dict[int, str] = {}

    def _on_action_invoked(self, dbus_id: int, action_key: str) -> None:
        if action_key != NOTIFY_SEND_DEFAULT_ACTION:
            return
        notification_id = self._ids.get(int(dbus_id))
        if notification_id is not None:
            _activate_open_notification(notification_id)

    def _on_closed(self, dbus_id: int, _reason: int) -> None:
        self._ids.pop(int(dbus_id), None)

    def notify(self, title: str, body: str, notification_id: str | None) -> bool:
        from PySide6.QtDBus import QDBusMessage

        actions = [NOTIFY_SEND_DEFAULT_ACTION, "Open"] if notification_id else []
        hints = {"desktop-entry": APP_ID}
        reply = self._interface.call(
            "Notify",
            APP_NAME,
            0,
            APP_ID,
            title,
            body,
            actions,
            hints,
            -1,
        )
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            log.debug("D-Bus notification failed: %s", reply.errorMessage())
            return False
        arguments = reply.arguments()
        if notification_id and arguments:
            try:
                self._ids[int(arguments[0])] = notification_id
            except (TypeError, ValueError):
                pass
        return True


def _notifier() -> _DBusNotifier | None:
    """Return the shared D-Bus notifier, or None when it is unavailable.

    Requires a live Qt application: QtDBus signal delivery needs an event loop,
    and without one the notify-send fallback is the honest answer.
    """
    global _dbus_notifier
    if _dbus_notifier is not None:
        return _dbus_notifier or None
    if not has_gui():
        return None
    try:
        from PySide6.QtDBus import QDBusConnection, QDBusInterface

        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            _dbus_notifier = False
            return None
        interface = QDBusInterface(
            NOTIFICATION_BUS_NAME, NOTIFICATION_BUS_PATH, NOTIFICATION_BUS_NAME, bus
        )
        if not interface.isValid():
            _dbus_notifier = False
            return None
        notifier = _DBusNotifier(interface)
        bus.connect(
            NOTIFICATION_BUS_NAME,
            NOTIFICATION_BUS_PATH,
            NOTIFICATION_BUS_NAME,
            "ActionInvoked",
            notifier._on_action_invoked,
        )
        bus.connect(
            NOTIFICATION_BUS_NAME,
            NOTIFICATION_BUS_PATH,
            NOTIFICATION_BUS_NAME,
            "NotificationClosed",
            notifier._on_closed,
        )
    except Exception as exc:
        log.debug("D-Bus notifications unavailable: %s", exc)
        _dbus_notifier = False
        return None
    _dbus_notifier = notifier
    return notifier


def notify_send_fallback(title: str, body: str, notification_id: str | None = None) -> None:
    """Clickable notify-send stand-in when the D-Bus daemon is unavailable."""
    if not shutil.which("notify-send"):
        return
    with_action = bool(notification_id)
    cmd = notify_send_command(title, body, with_action=with_action)
    if not with_action:
        try:
            subprocess.Popen(cmd, start_new_session=True)
        except OSError as exc:
            log.debug("notify-send failed: %s", exc)
        return

    def wait_and_open() -> None:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        except Exception as exc:
            log.debug("notify-send failed: %s", exc)
            return
        if result.returncode != 0:
            try:
                subprocess.Popen(
                    notify_send_command(title, body, with_action=False),
                    start_new_session=True,
                )
            except OSError as exc:
                log.debug("notify-send failed: %s", exc)
            return
        if (result.stdout or "").strip() == NOTIFY_SEND_DEFAULT_ACTION:
            _activate_open_notification(notification_id or "")

    threading.Thread(target=wait_and_open, daemon=True).start()


def show_notification(title: str, body: str, *, enabled: bool = True, notification_id: str | None = None) -> None:
    if not enabled:
        return
    notifier = _notifier()
    if notifier is not None and notifier.notify(title, body, notification_id):
        return
    try:
        notify_send_fallback(title, body, notification_id)
    except OSError as exc:
        log.debug("notify-send failed: %s", exc)
