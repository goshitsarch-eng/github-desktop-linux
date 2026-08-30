"""Main-thread dispatch used by the store and other non-UI modules.

The application logic in this package must never import Qt directly: it runs
unchanged under pytest, under the ``github`` CLI and inside worker threads. It
only needs two things from whatever event loop happens to be running:

* :func:`is_gui_running` -- is there a Qt application on this process?
* :func:`post` -- run a callable on the GUI thread soon.

Both degrade to "no GUI, call it inline" when PySide6 is missing or no
``QCoreApplication`` has been constructed, which is what tests and the CLI
want. The Qt imports stay inside the functions so importing ``github_desktop``
never pulls in PySide6.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Callable

__all__ = [
    "has_gui",
    "is_gui_running",
    "is_gui_thread",
    "post",
    "post_or_call",
    "reset_dispatcher",
]

_dispatcher: Any = None
_dispatcher_lock = threading.Lock()


def _qt_app() -> Any:
    try:
        from PySide6.QtCore import QCoreApplication
    except Exception:
        return None
    return QCoreApplication.instance()


def _under_test() -> bool:
    """True while pytest is running a test.

    The Qt smoke tests construct a QApplication that then outlives them --
    Qt allows only one per process -- so its mere existence must not make the
    store start deferring work onto an event loop nobody is spinning. Tests
    always take the inline path, which is what the GTK build did too (it never
    constructed a Gio.Application under pytest).
    """
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def is_gui_running() -> bool:
    """True when a Qt application exists and we are not inside a test."""
    if _under_test():
        return False
    return _qt_app() is not None


def is_gui_thread() -> bool:
    """True when the caller is running on the Qt GUI thread."""
    app = _qt_app()
    if app is None:
        return False
    try:
        from PySide6.QtCore import QThread

        return QThread.currentThread() is app.thread()
    except Exception:
        return False


def _get_dispatcher() -> Any:
    global _dispatcher
    with _dispatcher_lock:
        if _dispatcher is not None:
            return _dispatcher
        app = _qt_app()
        if app is None:
            return None
        try:
            from PySide6.QtCore import QObject, Qt, Signal, Slot
        except Exception:
            return None

        class _Dispatcher(QObject):
            """Hops a callable onto the GUI thread via a queued connection."""

            queued = Signal(object)

            def __init__(self) -> None:
                super().__init__()
                self.queued.connect(self._invoke, Qt.QueuedConnection)

            @Slot(object)
            def _invoke(self, fn: Callable[[], Any]) -> None:
                try:
                    fn()
                except Exception:  # pragma: no cover - mirrors a queued invocation
                    from .logging import get_logger

                    get_logger().exception("queued main-thread callback failed")

        dispatcher = _Dispatcher()
        dispatcher.moveToThread(app.thread())
        _dispatcher = dispatcher
        return _dispatcher


def post(fn: Callable[[], Any]) -> bool:
    """Queue ``fn`` on the GUI thread.

    Returns True when it was queued, False when there is no GUI to queue it on
    (the caller is then expected to run ``fn`` itself, matching how the store
    behaved when marshalling to the main loop).
    """
    if _under_test() or _qt_app() is None:
        return False
    dispatcher = _get_dispatcher()
    if dispatcher is None:
        return False
    dispatcher.queued.emit(fn)
    return True


def post_or_call(fn: Callable[[], Any]) -> None:
    """Queue ``fn`` on the GUI thread, or call it inline when headless."""
    if not post(fn):
        fn()


def reset_dispatcher() -> None:
    """Drop the cached dispatcher (used by tests that tear down a QApplication)."""
    global _dispatcher
    with _dispatcher_lock:
        _dispatcher = None


def has_gui() -> bool:
    """True when a live Qt application is driving the UI.

    Same answer as :func:`is_gui_running`; kept as a separate name because
    callers read as "is there a UI to keep responsive?" rather than "should I
    marshal onto its thread?".
    """
    return is_gui_running()
