"""Desktop notifications via Gio / notify-send."""

from __future__ import annotations

from .logging import get_logger

log = get_logger()


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
