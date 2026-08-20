"""Adw.Application entry: single instance, menus, protocol handlers, CLI."""

from __future__ import annotations

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk

from ..errors import GitNotFoundError
from ..git.ops import checkout_branch
from ..git.runner import find_git
from ..logging import get_logger
from ..models import PopupType
from ..protocol import is_protocol_url, parse_app_url
from ..store import AppStore
from ..theme import apply_theme
from ..version import APP_ID, APP_NAME, PROTOCOL_SCHEMES
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
        about = Gio.SimpleAction.new("about", None)
        about.connect("activate", lambda *_: self.store.show_popup(PopupType.ABOUT))
        self.add_action(about)
        try:
            find_git()
        except GitNotFoundError:
            GLib.idle_add(lambda: self.store.show_popup(PopupType.INSTALL_GIT) or False)

    def _on_activate(self, *_args: object) -> None:
        if self.window is None:
            self.window = MainWindow(self, self.store)
            self.window.present()
        else:
            self.window.present()
        self.store.apply_theme()
        repo = self.store.selected_repository
        if repo:
            self.store.refresh_repository(repo)
        GLib.timeout_add_seconds(30, self._poll_notifications)
        GLib.idle_add(lambda: self.store.check_thank_you() or False)

    def _poll_notifications(self) -> bool:
        self.store.poll_notifications()
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
            from ..models import Branch, BranchType

            branch = next((b for b in self.store.state_for(repo).branches if b.name == name), None)
            if branch:
                self.store.checkout(repo, branch)
            else:
                checkout_branch(repo.path, name)
                self.store.refresh_repository(repo)

    def _on_open_pr(self, _action, param) -> None:
        from ..shells import open_external

        url = param.get_string() if param else ""
        if url:
            open_external(url)


def run(argv: list[str] | None = None) -> int:
    app = DesktopApplication()
    return app.run(argv or sys.argv)
