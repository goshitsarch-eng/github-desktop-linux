"""Qt entry point: one instance, the QML engine, and the background timers.

Single-instance behaviour is a ``QLocalServer`` keyed on the application id.
A second launch hands its argv to the running instance over that socket and
exits, which is what makes ``github open <path>`` and the
``x-github-client://`` protocol handler open a repository in the window that
is already on screen.
"""

from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication

from ..exception_reporting import install_exception_hook, set_unhandled_rejection_handler
from ..git.runner import is_git_on_path
from ..linux import get_os
from ..logging import get_logger
from ..models import FetchType, PopupType
from ..notifications import set_activation_handler
from ..protocol import is_protocol_url
from ..stats import SendStatsInterval
from ..store import PULL_REQUEST_INTERVAL, AppStore
from ..version import APP_ID, APP_NAME, __version__
from .bridge import AppBridge
from .filepicker import PickedFolder, resolve_picked_url
from .popups import PopupBridge
from .theme_bridge import ThemeBridge

log = get_logger()

QML_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")
SOCKET_NAME = f"{APP_ID}.instance"
POLL_NOTIFICATIONS_MS = 30 * 1000
POLL_COMMIT_STATUS_MS = 3 * 60 * 1000
INDICATOR_INTERVAL_MS = 15 * 60 * 1000


def _offline() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"))


class DesktopApplication(QApplication):
    """The application object. Owns the store, the engine and the timers.

    ``QApplication`` rather than ``QGuiApplication`` so the crash reporter can
    put up a message box and so the native folder dialog is available; the
    interface itself is entirely QML.
    """

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self.setApplicationName(APP_NAME)
        self.setApplicationDisplayName(APP_NAME)
        self.setApplicationVersion(__version__)
        self.setOrganizationName(APP_NAME)
        self.setDesktopFileName(APP_ID)
        self.setWindowIcon(QIcon.fromTheme(APP_ID))
        # Breeze is the Qt Quick Controls style on Plasma; org.kde.desktop
        # picks up whatever the user actually has configured.
        QQuickStyle.setStyle(os.environ.get("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop"))

        self.store = AppStore()
        self.bridge = AppBridge(self.store)
        self.theme = ThemeBridge(self.store)
        self.popups = PopupBridge(self.store, self.bridge)
        self.engine: QQmlApplicationEngine | None = None
        self._server = None
        self._launch_started = time.monotonic()
        set_activation_handler(self._open_notification)

    # -- QML -------------------------------------------------------------

    def load_ui(self) -> bool:
        """Build the QML engine and load the main window. False if it failed."""
        engine = QQmlApplicationEngine()
        context = engine.rootContext()
        context.setContextProperty("app", self.bridge)
        context.setContextProperty("theming", self.theme)
        context.setContextProperty("popups", self.popups)
        engine.addImportPath(QML_DIR)
        engine.load(QUrl.fromLocalFile(os.path.join(QML_DIR, "Main.qml")))
        if not engine.rootObjects():
            log.error(
                "Could not load the Kirigami interface. Install Kirigami "
                "(qml6-module-org-kde-kirigami on Debian/Ubuntu, "
                "kf6-kirigami on Fedora, kirigami on Arch)."
            )
            return False
        self.engine = engine
        return True

    # -- single instance ---------------------------------------------------

    def claim_instance(self) -> bool:
        """Become the primary instance, or return False if one is running."""
        from PySide6.QtNetwork import QLocalServer

        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if not server.listen(SOCKET_NAME):
            # A stale socket outlives a crash; remove it and try once more.
            QLocalServer.removeServer(SOCKET_NAME)
            if not server.listen(SOCKET_NAME):
                return False
        server.newConnection.connect(self._on_second_instance)
        self._server = server
        return True

    @staticmethod
    def forward_to_running_instance(arguments: list[str]) -> bool:
        """Hand ``arguments`` to the running instance. False if none answered."""
        from PySide6.QtNetwork import QLocalSocket

        socket = QLocalSocket()
        socket.connectToServer(SOCKET_NAME)
        if not socket.waitForConnected(1000):
            return False
        socket.write(json.dumps(arguments).encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        return True

    def _on_second_instance(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return

        def read() -> None:
            try:
                payload = bytes(socket.readAll().data()).decode("utf-8")
                arguments = json.loads(payload) if payload else []
            except (ValueError, UnicodeDecodeError):
                arguments = []
            socket.deleteLater()
            self.raise_window()
            self.handle_arguments(arguments)

        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)

    def raise_window(self) -> None:
        for window in self.topLevelWindows():
            window.show()
            window.raise_()
            window.requestActivate()

    # -- CLI / protocol ----------------------------------------------------

    def handle_arguments(self, arguments: list[str]) -> None:
        """Route protocol URLs and CLI arguments to the store.

        A protocol URL (``x-github-client://`` and friends) is an action to
        perform; anything else is CLI input like ``open <path>`` or
        ``clone <owner/name>``.
        """
        urls = [arg for arg in arguments if is_protocol_url(arg)]
        cli_arguments = [arg for arg in arguments if arg not in urls]
        if cli_arguments:
            try:
                self.store.handle_cli(cli_arguments)
            except Exception as exc:
                log.debug("CLI arguments failed: %s", exc)
        for url in urls:
            try:
                self.store.handle_url_action(url)
            except Exception as exc:
                log.debug("protocol URL failed: %s", exc)

    def _open_notification(self, notification_id: str) -> None:
        self.raise_window()
        if notification_id:
            self.store.open_stored_notification(notification_id)

    # -- startup / timers --------------------------------------------------

    def start(self, arguments: list[str]) -> None:
        log.info("launching: %s (%s)", __version__, get_os())
        self.theme.refresh()
        if not is_git_on_path():
            QTimer.singleShot(0, lambda: self.store.show_popup(PopupType.INSTALL_GIT))
        QTimer.singleShot(0, self.store.check_thank_you)
        QTimer.singleShot(0, self.store.report_stats)
        QTimer.singleShot(0, self._install_global_lfs_filters)

        elapsed_ms = max(0.0, (time.monotonic() - self._launch_started) * 1000)
        self.store.stats.record_launch_stats(
            {"mainReadyTime": elapsed_ms, "loadTime": elapsed_ms, "rendererReadyTime": 0}
        )
        self.store.stats.note_ui_activity()

        self._timer(POLL_NOTIFICATIONS_MS, self.store.poll_notifications, repeat=True)
        self._timer(POLL_COMMIT_STATUS_MS, self._poll_commit_status, repeat=True)
        if not _offline():
            # Stagger the first tick per process so several open windows do
            # not all hit the network on the same second.
            skew_ms = (1 + os.getpid() % 30) * 1000
            QTimer.singleShot(skew_ms, self._background_fetch_tick)
            QTimer.singleShot(skew_ms, self._indicator_tick)
            self._timer(2 * 60 * 1000, self._pr_updater_tick, repeat=True)
            self._timer(SendStatsInterval * 1000, self._stats_tick, repeat=True)
        if arguments:
            self.handle_arguments(arguments)
        repo = self.store.selected_repository
        if repo is not None:
            self.store.refresh_repository(repo)

    def _timer(self, interval_ms: int, callback, *, repeat: bool = False) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(int(interval_ms))
        timer.setSingleShot(not repeat)
        timer.timeout.connect(lambda: self._guard(callback))
        timer.start()
        return timer

    @staticmethod
    def _guard(callback) -> None:
        try:
            callback()
        except Exception as exc:
            log.debug("periodic task failed: %s", exc)

    def _install_global_lfs_filters(self) -> None:
        """Desktop `installGlobalLFSFilters(false)` from deferred launch actions."""
        if _offline():
            return

        def work() -> None:
            from ..git.ops import install_global_lfs_filters

            install_global_lfs_filters(False)

        def done(exc: BaseException | None, *_args: object) -> None:
            if exc:
                log.debug("installGlobalLFSFilters failed: %s", exc)

        self.store._run(work, done)

    def _poll_commit_status(self) -> None:
        """Desktop `subscribeToCommitStatus`: refresh CI about every 3 minutes."""
        if _offline():
            return
        self.store.poll_commit_status()

    def _background_fetch_tick(self) -> None:
        """Desktop BackgroundFetcher: quiet fetch of the selected repository."""
        if _offline():
            return
        repo = self.store.selected_repository
        if repo:
            self._guard(lambda: self.store.fetch_repo(repo, FetchType.BACKGROUND_TASK))
        interval = max(int(self.store.background_fetch_interval), 5 * 60)
        QTimer.singleShot(interval * 1000, self._background_fetch_tick)

    def _indicator_tick(self) -> None:
        """Desktop RepositoryIndicatorUpdater: ahead/behind for every repository."""
        if _offline():
            return
        self._guard(self.store.refresh_repo_indicators)
        QTimer.singleShot(INDICATOR_INTERVAL_MS, self._indicator_tick)

    def _pr_updater_tick(self) -> None:
        """Desktop `PullRequestUpdater`: refresh PRs about every 30 minutes."""
        if _offline():
            return
        self._guard(self.store.refresh_pull_requests)
        QTimer.singleShot(PULL_REQUEST_INTERVAL * 1000, self._pr_updater_tick)

    def _stats_tick(self) -> None:
        """Desktop `SendStatsInterval` — retry `reportStats` every 4 hours."""
        if _offline():
            return
        self._guard(self.store.report_stats)


def run(argv: list[str] | None = None) -> int:
    """Start the application, or hand off to an instance already running."""
    arguments = list(argv if argv is not None else sys.argv)
    rest = arguments[1:]

    # Qt 6 defaults to per-monitor DPI awareness; only the rounding policy is
    # still worth setting so fractional scaling does not round text up.
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    install_exception_hook()
    app = DesktopApplication(arguments)
    set_unhandled_rejection_handler(lambda: app.store.stats.increment("unhandledRejectionCount"))

    if not app.claim_instance():
        if DesktopApplication.forward_to_running_instance(rest):
            return 0
        log.warning("another instance holds the socket but is not answering; continuing")

    if not app.load_ui():
        return 1
    app.start(rest)
    return app.exec()


__all__ = ["DesktopApplication", "PickedFolder", "resolve_picked_url", "run"]
