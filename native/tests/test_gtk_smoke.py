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

    from github_desktop.models import ApplicationTheme, TutorialStep
    from github_desktop.store import AppStore
    from github_desktop.theme import apply_theme
    from github_desktop.ui.css import load_css
    from github_desktop.ui.dialogs import show_about, show_preferences, show_release_notes, show_pull_request_review, show_checks
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
            assert win.lookup_action("install-cli")
            assert win.lookup_action("zoom-in")
            assert win.lookup_action("toggle-changes-filter")
            assert hasattr(win, "_branches_foldout")
            child = win._stack.get_visible_child_name()
            assert child in {"welcome", "empty", "repo"}
            win._refresh_files()
            win._refresh_history()
            show_about(win)
            show_preferences(win, store)
            from github_desktop.ui.diff_view import DiffViewer
            from github_desktop.git.diff import parse_unified_diff
            from github_desktop.models import BinaryDiff, DiffSelection, DiffSelectionType

            sample = parse_unified_diff(
                "@@ -10,3 +10,4 @@\n hello\n-world\n+world!\n line\n"
            )
            from github_desktop.git.expansion import apply_expansion_metadata

            sample = apply_expansion_metadata(sample, old_line_count=40, new_line_count=40)
            selection = DiffSelection.from_initial_selection(DiffSelectionType.ALL)
            viewer = DiffViewer(
                interactive=True,
                on_line_toggle=lambda *_: None,
                on_hunk_toggle=lambda *_: None,
                on_expand_hunk=lambda *_: None,
                on_expand_whole=lambda: None,
            )
            viewer.render(sample, path="README.md", selection=selection, side_by_side=True)
            viewer.render(sample, path="README.md", selection=selection, side_by_side=False)
            viewer.render(BinaryDiff(), path="photo.bin")
            viewer.start_search()
            viewer.close_search()
            assert hasattr(win, "_stash_viewer")
            assert hasattr(win, "_commit_summary")
            assert hasattr(win, "_history_filter")
            assert hasattr(win, "_repo_content")
            assert hasattr(win, "_missing_page")
            assert hasattr(win, "_tutorial_panel")
            win._tutorial_panel.refresh(TutorialStep.PICK_EDITOR, "GNOME Text Editor")
            win._commit_summary.bind([], None)
            win._find()
            show_release_notes(win)
            show_checks(win, store, {"error": "CI failed", "title": "Demo PR"})
            from github_desktop.ui.checks import show_rerun_checks
            from github_desktop.models import RefCheck
            from github_desktop.ui.avatar import AvatarStack

            show_rerun_checks(win, store, {"failed_only": True, "checks": []})
            stack = AvatarStack([("Ada Lovelace", "ada@example.com"), ("Grace Hopper", "grace@example.com")], size=24)
            assert stack.get_first_child() is not None
            sample_run = RefCheck(id=1, name="build", description="Failed after 1m", status="completed", conclusion="failure")
            show_checks(win, store, {"error": "1 check failed in your pull request", "title": "Demo PR", "checks": [sample_run]})
            show_pull_request_review(
                win,
                store,
                {
                    "review": {
                        "state": "COMMENTED",
                        "body": "Looks good",
                        "html_url": "https://github.com/example/repo/pull/1",
                        "user": {"login": "octocat"},
                    },
                    "pull_request": {"number": 1, "title": "Demo", "html_url": "https://github.com/example/repo/pull/1"},
                    "should_checkout": False,
                },
            )
            from github_desktop.ui.multi_commit import (
                show_confirm_abort,
                show_conflicts_dialog,
                show_multi_commit,
                show_warn_force_push,
            )
            from github_desktop.ui.dialogs import (
                show_acknowledgements,
                show_copilot_disclaimer,
                show_create_branch,
                show_filtered_commit,
                show_lfs_mismatch,
                show_unknown_authors,
                show_warn_undo,
            )

            show_multi_commit(win, store, {"kind": "Merge"})
            show_multi_commit(win, store, {"kind": "Cherry-pick", "shas": ["deadbeef"]})
            show_warn_force_push(win, store, {"operation": "Rebase"})
            show_confirm_abort(win, "Merge", lambda: None)
            show_conflicts_dialog(win, store, "Merge")
            from github_desktop.ui.checks import CompletenessDonut

            CompletenessDonut({"success": 2, "failure": 1, "in_progress": 1})
            show_create_branch(win, store, {})
            show_acknowledgements(win)
            show_copilot_disclaimer(win, store)
            show_warn_undo(win, store, {"is_working_directory_clean": False})
            show_unknown_authors(win, {"authors": []})
            show_filtered_commit(win, store, {})
            show_lfs_mismatch(win, store)
            repos[0].is_missing = True
            win._show_missing(repos[0])
            win._repo_content.set_visible_child_name("missing")
            win._branches_foldout.refresh([], [], current="main", default_name="main", recent=[], has_github=False)
            win.close()
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            application.quit()

    app.connect("activate", on_activate)
    GLib.timeout_add(10000, app.quit)
    app.run([])
    assert errors == [], errors
