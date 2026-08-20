"""Desktop notifications via Gio / notify-send."""

from __future__ import annotations

import os
import shutil
import subprocess

from .linux import spawn
from .logging import get_logger

log = get_logger()

NOTIFICATION_SETTINGS_COMMANDS = (
    ("gnome-control-center", "notifications"),
    ("io.elementary.switchboard", "notifications"),
    ("systemsettings", "kcm_notifications"),
    ("unity-control-center", "notifications"),
)


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
    try:
        from gi.repository import Gio

        if Gio.Application.get_default() is not None:
            return "granted"
    except Exception:
        pass
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


def show_notification(title: str, body: str, *, enabled: bool = True, notification_id: str | None = None) -> None:
    if not enabled:
        return
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib

        app = Gio.Application.get_default()
        if app is not None:
            notification = Gio.Notification.new(title)
            notification.set_body(body)
            try:
                notification.set_default_action_and_target_value(
                    "app.open-notification", GLib.Variant.new_string(notification_id or "")
                )
            except Exception:
                pass
            app.send_notification(notification_id, notification)
            return
    except Exception as exc:
        log.debug("Gio notification failed: %s", exc)
    try:
        import subprocess

        subprocess.Popen(["notify-send", title, body], start_new_session=True)
    except OSError as exc:
        log.debug("notify-send failed: %s", exc)
