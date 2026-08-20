"""GTK 4 + libadwaita smoke tests (single Application.run per process)."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("GTK_A11Y", "none")
os.environ.setdefault("ADW_DISABLE_PORTAL", "1")

pytest.importorskip("gi")


def test_gtk_window_preferences_and_theme(isolated_config, git_repo) -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib

    from github_desktop.models import ApplicationTheme
    from github_desktop.store import AppStore
    from github_desktop.theme import apply_theme
    from github_desktop.ui.css import load_css
    from github_desktop.ui.dialogs import show_about, show_preferences
    from github_desktop.ui.window import MainWindow

    errors: list[str] = []
    app = Adw.Application(application_id="io.github.desktop.GitHubDesktop.smoketest")

    def on_activate(application) -> None:
        try:
            load_css()
            apply_theme(ApplicationTheme.LIGHT)
            apply_theme(ApplicationTheme.DARK)
            apply_theme(ApplicationTheme.SYSTEM)
            store = AppStore()
            repos = store.add_repositories([str(git_repo)])
            (git_repo / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
            from github_desktop.git.ops import get_status

            store.state_for(repos[0]).status = get_status(str(git_repo))
            store.select_repository(repos[0].id)
            win = MainWindow(application, store)
            assert win.lookup_action("clone-repository")
            assert win.lookup_action("preferences")
            assert win.lookup_action("push")
            assert win.lookup_action("create-branch")
            assert win.lookup_action("open-pull-request")
            child = win._stack.get_visible_child_name()
            assert child in {"welcome", "empty", "repo"}
            win._refresh_files()
            win._refresh_history()
            show_about(win)
            show_preferences(win, store)
            from github_desktop.ui.diff_view import DiffViewer
            from github_desktop.git.diff import parse_unified_diff
            from github_desktop.models import DiffSelection, DiffSelectionType

            viewer = DiffViewer(
                interactive=True,
                on_line_toggle=lambda *_: None,
                on_hunk_toggle=lambda *_: None,
            )
            sample = parse_unified_diff(
                "@@ -1,1 +1,2 @@\n hello\n+world\n"
            )
            selection = DiffSelection.from_initial_selection(DiffSelectionType.ALL)
            viewer.render(sample, path="README.md", selection=selection, side_by_side=True)
            viewer.render(sample, path="README.md", selection=selection, side_by_side=False)
            win.close()
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            application.quit()

    app.connect("activate", on_activate)
    GLib.timeout_add(10000, app.quit)
    app.run([])
    assert errors == [], errors
