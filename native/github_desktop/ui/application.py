"""Adw.Application entry: single instance, menus, protocol handlers, CLI."""

from __future__ import annotations

import os
import sys
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

from ..exception_reporting import install_exception_hook, set_unhandled_rejection_handler
from ..git.runner import is_git_on_path
from ..linux import get_os
from ..logging import get_logger
from ..models import FetchType, PopupType
from ..protocol import is_protocol_url, parse_app_url
from ..stats import SendStatsInterval
from ..store import AppStore, PULL_REQUEST_INTERVAL
from ..theme import apply_theme
from ..version import APP_ID, APP_NAME, PROTOCOL_SCHEMES, __version__
from .css import load_css
from .window import MainWindow

log = get_logger()


class DesktopApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.store = AppStore()
        self.window: MainWindow | None = None
        self.set_resource_base_path("/io/github/desktop/GitHubDesktop")
        self.connect("activate", self._on_activate)
        self.connect("open", self._on_open)
        self.connect("command-line", self._on_command_line)
        self.connect("startup", self._on_startup)
        self._launch_started = time.monotonic()

    def _on_startup(self, *_args: object) -> None:
        load_css()
        apply_theme(self.store.settings.theme)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])
        checkout = Gio.SimpleAction.new("checkout", GLib.VariantType.new("s"))
        checkout.connect("activate", self._on_checkout)
        self.add_action(checkout)
        open_pr = Gio.SimpleAction.new("open-pr", GLib.VariantType.new("s"))
        open_pr.connect("activate", self._on_open_pr)
        self.add_action(open_pr)
        open_note = Gio.SimpleAction.new("open-notification", GLib.VariantType.new("s"))
        open_note.connect("activate", self._on_open_notification)
        self.add_action(open_note)
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *_: self.store.show_popup(PopupType.ABOUT))
        self.add_action(about)
        log.info("launching: %s (%s)", __version__, get_os())
        if not is_git_on_path():
            GLib.idle_add(lambda: self.store.show_popup(PopupType.INSTALL_GIT) or False)

    def _on_activate(self, *_args: object) -> None:
        first = self.window is None
        if first:
            self.window = MainWindow(self, self.store)
        self.window.present()
        self.store.apply_theme()
        if first:
            elapsed_ms = max(0.0, (time.monotonic() - self._launch_started) * 1000)
            self.store.stats.record_launch_stats(
                {"mainReadyTime": elapsed_ms, "loadTime": elapsed_ms, "rendererReadyTime": 0}
            )
            self.store.stats.note_ui_activity()
        repo = self.store.selected_repository
        if repo:
            self.store.refresh_repository(repo)
        if not first:
            return
        GLib.timeout_add_seconds(30, self._poll_notifications)
        GLib.timeout_add_seconds(3 * 60, self._poll_commit_status)
        GLib.idle_add(lambda: self.store.check_thank_you() or False)
        GLib.idle_add(lambda: self.store.report_stats() or False)
        GLib.idle_add(self._install_global_lfs_filters)
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            skew = 1 + (os.getpid() % 30)
            GLib.timeout_add_seconds(skew, self._background_fetch_tick)
            GLib.timeout_add_seconds(skew, self._indicator_tick)
            GLib.timeout_add_seconds(2 * 60, self._pr_updater_tick)
            GLib.timeout_add_seconds(SendStatsInterval, self._stats_tick)

    def _install_global_lfs_filters(self) -> bool:
        """Desktop `installGlobalLFSFilters(false)` from deferred launch actions."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False

        def work() -> None:
            from ..git.ops import install_global_lfs_filters

            install_global_lfs_filters(False)

        def done(exc: BaseException | None, *_a: object) -> None:
            if exc:
                log.debug("installGlobalLFSFilters failed: %s", exc)

        self.store._run(work, done)
        return False

    def _poll_notifications(self) -> bool:
        self.store.poll_notifications()
        return True

    def _poll_commit_status(self) -> bool:
        """Desktop `subscribeToCommitStatus`: refresh CI about every 3 minutes."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False
        try:
            self.store.poll_commit_status()
        except Exception as exc:
            log.debug("commit status poll failed: %s", exc)
        return True

    def _background_fetch_tick(self) -> bool:
        """Desktop BackgroundFetcher: quiet fetch of the selected GitHub repository."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False
        repo = self.store.selected_repository
        if repo:
            try:
                self.store.fetch_repo(repo, FetchType.BACKGROUND_TASK)
            except Exception as exc:
                log.debug("background fetch tick failed: %s", exc)
        interval = max(int(self.store.background_fetch_interval), 5 * 60)
        GLib.timeout_add_seconds(interval, self._background_fetch_tick)
        return False

    def _indicator_tick(self) -> bool:
        """Desktop RepositoryIndicatorUpdater: ahead/behind for every repository."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False
        try:
            self.store.refresh_repo_indicators()
        except Exception as exc:
            log.debug("indicator tick failed: %s", exc)
        GLib.timeout_add_seconds(15 * 60, self._indicator_tick)
        return False

    def _pr_updater_tick(self) -> bool:
        """Desktop `PullRequestUpdater`: refresh PRs about every 30 minutes."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False
        try:
            self.store.refresh_pull_requests()
        except Exception as exc:
            log.debug("pull request updater failed: %s", exc)
        GLib.timeout_add_seconds(PULL_REQUEST_INTERVAL, self._pr_updater_tick)
        return False

    def _stats_tick(self) -> bool:
        """Desktop `SendStatsInterval` — retry `reportStats` every 4 hours."""
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            return False
        try:
            self.store.report_stats()
        except Exception as exc:
            log.debug("reportStats tick failed: %s", exc)
        return True

    def _on_open(self, _app, files, _n, _hint) -> None:
        self.activate()
        for file in files:
            uri = file.get_uri()
            path = file.get_path()
            if uri and is_protocol_url(uri):
                self.store.handle_url_action(uri)
            elif path:
                self.store.handle_cli([f"--cli-open={path}"])

    def _on_command_line(self, _app, command_line) -> int:
        argv = command_line.get_arguments()
        self.activate()
        rest = list(argv[1:])
        if rest:
            self.store.handle_cli(rest)
            for arg in rest:
                if is_protocol_url(arg):
                    self.store.handle_url_action(arg)
        return 0

    def _on_checkout(self, _action, param) -> None:
        name = param.get_string() if param else ""
        repo = self.store.selected_repository
        if repo and name:
            branch = next((b for b in self.store.state_for(repo).branches if b.name == name), None)
            if branch:
                self.store.checkout(repo, branch)
            else:
                self.store._checkout_named_branch(repo, name)

    def _on_open_pr(self, _action, param) -> None:
        from ..shells import open_external

        url = param.get_string() if param else ""
        if url:
            open_external(url)

    def _on_open_notification(self, _action, param) -> None:
        ident = param.get_string() if param else ""
        self.activate()
        if ident:
            self.store.open_stored_notification(ident)


def run(argv: list[str] | None = None) -> int:
    install_exception_hook()
    app = DesktopApplication()
    set_unhandled_rejection_handler(lambda: app.store.stats.increment("unhandledRejectionCount"))
    return app.run(argv or sys.argv)
