"""Desktop `main-process/exception-reporting.ts` and uncaught-exception UX."""

from __future__ import annotations

import os
import sys
import threading
import traceback
import urllib.error
import urllib.parse
import urllib.request
from types import TracebackType
from typing import Any, Callable

from .linux import get_architecture
from .logging import get_logger
from .stats import env_skips_stats_network, get_has_opted_out_of_stats, get_renderer_guid
from .version import APP_NAME, __version__

log = get_logger()

ErrorEndpoint = "https://central.github.com/api/desktop/exception"
NonFatalErrorEndpoint = "https://central.github.com/api/desktop-non-fatal/exception"

_has_sent_fatal_error = False
_has_shown_uncaught = False
_unhandled_rejection_handler: Callable[[], None] | None = None


def set_unhandled_rejection_handler(handler: Callable[[], None] | None) -> None:
    global _unhandled_rejection_handler
    _unhandled_rejection_handler = handler


def _app_sha() -> str:
    return os.environ.get("GITHUB_DESKTOP_SHA") or os.environ.get("GITHUB_SHA") or ""


def report_error(
    error: BaseException,
    extra: dict[str, str] | None = None,
    *,
    non_fatal: bool = False,
) -> None:
    """Desktop `reportError` — POST form-encoded crash details to Central."""
    global _has_sent_fatal_error
    if env_skips_stats_network():
        return
    if non_fatal and get_has_opted_out_of_stats():
        return
    if not non_fatal:
        if _has_sent_fatal_error:
            return
        _has_sent_fatal_error = True
    data: dict[str, str] = {
        "name": type(error).__name__,
        "message": str(error) or type(error).__name__,
        "platform": sys.platform,
        "architecture": get_architecture(),
        "sha": _app_sha(),
        "version": __version__,
        "guid": get_renderer_guid(),
    }
    stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    if stack.strip():
        data["stack"] = stack
    if extra:
        data.update(extra)
    body = urllib.parse.urlencode(data).encode("utf-8")
    url = NonFatalErrorEndpoint if non_fatal else ErrorEndpoint
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if getattr(resp, "status", 200) != 200:
                raise RuntimeError(f"Got {resp.status} from central")
        log.info("Error report submitted")
    except Exception as exc:
        log.error("Failed submitting error report: %s", exc)


def show_uncaught_exception(error: BaseException, *, is_launch_error: bool = False) -> None:
    """Desktop `showUncaughtException` — log, report, and show an unrecoverable error dialog."""
    global _has_shown_uncaught
    log.error("%s", "".join(traceback.format_exception(type(error), error, error.__traceback__)))
    if _has_shown_uncaught:
        return
    _has_shown_uncaught = True
    report_error(error, non_fatal=False)
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _present_crash_dialog(error, is_launch_error=is_launch_error)


def _present_crash_dialog(error: BaseException, *, is_launch_error: bool) -> None:
    stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    message = (
        f"{APP_NAME} has encountered an unrecoverable error and will need to restart.\n\n"
        "This has been reported to the team, but if you encounter this repeatedly please report "
        f"this issue to the GitHub Desktop issue tracker.\n\n{stack or error}"
    )
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gio, GLib

        def present() -> bool:
            dialog = Adw.AlertDialog(heading="Unrecoverable error", body=message[:4000])
            dialog.add_response("quit", "Quit")
            dialog.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_close_response("quit")
            parent = None
            app = Gio.Application.get_default()
            if app is not None:
                parent = app.get_active_window()

            def on_response(*_args: Any) -> None:
                if app is not None:
                    app.quit()

            dialog.connect("response", on_response)
            if parent is not None:
                dialog.present(parent)
            else:
                dialog.present()
            return False

        if Gio.Application.get_default() is not None:
            GLib.idle_add(present)
        else:
            present()
    except Exception as exc:
        log.error("Failed to show crash dialog: %s", exc)
        print(message, file=sys.stderr)


def _excepthook(
    exc_type: type[BaseException],
    exc: BaseException | None,
    tb: TracebackType | None,
) -> None:
    if exc is None:
        exc = exc_type()  # type: ignore[misc]
    if tb is not None and getattr(exc, "__traceback__", None) is None:
        exc = exc.with_traceback(tb)
    show_uncaught_exception(exc)


def _thread_hook(args: threading.ExceptHookArgs) -> None:
    err = args.exc_value or args.exc_type()  # type: ignore[misc]
    log.error("unhandled thread exception: %s", err)
    if _unhandled_rejection_handler is not None:
        try:
            _unhandled_rejection_handler()
        except Exception:
            pass
    report_error(err, extra={"thread": args.thread.name if args.thread else ""}, non_fatal=True)


def install_exception_hook() -> None:
    """Install `sys.excepthook` / `threading.excepthook` matching Desktop's crash path."""
    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
