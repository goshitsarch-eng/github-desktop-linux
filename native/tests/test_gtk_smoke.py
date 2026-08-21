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
    from gi.repository import Adw, Gdk, GLib

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
            assert win.lookup_action("edit-undo")
            assert win.lookup_action("edit-redo")
            assert win.lookup_action("increase-resizable")
            assert win.lookup_action("decrease-resizable")
            assert win.lookup_action("pr-suggested-preview")
            assert hasattr(win, "_menu_btn")
            assert hasattr(win, "_changes_paned")
            assert hasattr(win, "_branches_foldout")
            from github_desktop.ui.menus import (
                DefaultMaxWidth,
                nudge_resizable_width,
                resizableComponentClass,
                resizable_limit,
                resize_active_resizable,
            )

            sidebar = win._changes_paned.get_start_child()
            assert sidebar.has_css_class(resizableComponentClass)
            min_w = max(220, resizable_limit(win.store.sidebar_constraints.min, 220))
            max_w = resizable_limit(win.store.sidebar_constraints.max, DefaultMaxWidth)
            win._changes_paned.set_position(250)
            before = win._changes_paned.get_position()
            assert resize_active_resizable(win._file_list, True)
            assert win._changes_paned.get_position() == nudge_resizable_width(before, True, min_w, max_w)
            assert "Repository sidebar width increased" in getattr(sidebar, "_resize_message", "")
            after = win._changes_paned.get_position()
            assert resize_active_resizable(win._file_list, False)
            assert win._changes_paned.get_position() == nudge_resizable_width(after, False, min_w, max_w)
            sidebar_pos = win._changes_paned.get_position()
            assert not resize_active_resizable(win._diff_view, True)
            assert win._changes_paned.get_position() == sidebar_pos
            files_start = win._hist_files_paned.get_start_child()
            assert files_start.has_css_class(resizableComponentClass)
            files_min = max(100, resizable_limit(win.store.commit_summary_constraints.min, 100))
            files_max = resizable_limit(win.store.commit_summary_constraints.max, DefaultMaxWidth)
            win._hist_files_paned.set_position(250)
            files_before = win._hist_files_paned.get_position()
            assert resize_active_resizable(win._hist_files, True)
            assert win._hist_files_paned.get_position() == nudge_resizable_width(
                files_before, True, files_min, files_max
            )
            stash_files = win._stash_viewer._files_paned.get_start_child()
            assert stash_files.has_css_class(resizableComponentClass)
            branch_wrap = win._branch_btn.get_parent()
            assert branch_wrap.has_css_class("toolbar-resizable")
            assert branch_wrap.has_css_class(resizableComponentClass)
            win._resize_active_resizable(True)
            assert win.lookup_action("increase-resizable").get_enabled() is False
            win.store.app_focused_element_changed(True)
            win._sync_resizable_menu()
            assert win.lookup_action("increase-resizable").get_enabled() is True
            win.store.app_focused_element_changed(False)
            win._sync_resizable_menu()
            assert win.lookup_action("increase-resizable").get_enabled() is False
            from github_desktop.models import FoldoutType, RepositorySectionTab

            win._view_stack.set_visible_child_name("history")
            win.store.set_section(RepositorySectionTab.HISTORY)
            win.store.show_foldout(FoldoutType.BRANCH)
            win._go_to_commit_message()
            assert win.store.section == RepositorySectionTab.CHANGES
            assert win._view_stack.get_visible_child_name() == "changes"
            assert win.store.foldout is None
            assert win.store.focus_commit_message is False
            win.store.close_current_foldout()
            win.store.set_section(RepositorySectionTab.CHANGES)
            win._view_stack.set_visible_child_name("changes")
            win._change_tab()
            assert win.store.section == RepositorySectionTab.HISTORY
            assert win._view_stack.get_visible_child_name() == "history"
            win._change_tab()
            assert win.store.section == RepositorySectionTab.CHANGES
            win.store.show_foldout(FoldoutType.BRANCH)
            assert win._on_global_key(None, Gdk.KEY_Tab, 0, Gdk.ModifierType.CONTROL_MASK) is False
            win.store.close_current_foldout()
            win._select_all_list_box(win._commit_list)
            win._select_all_list_box(win._file_list)
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
            from github_desktop.models import ImageDiff, ImageDiffType

            png = bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c089"
                "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
            )
            viewer.render(ImageDiff(previous=png, current=png), path="a.png", image_mode=ImageDiffType.SWIPE.value)
            viewer.render(ImageDiff(previous=None, current=png), path="new.png")
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
            win._show_window_info("Press F11 to exit fullscreen", hold_ms=1)
            win._show_zoom_info(1.1)
            win._hide_window_info()
            if hasattr(win, "_repo_filter"):
                win._repo_filter.set_text("zzz-no-such-repo")
                win._refresh_repo_list()
                win._repo_filter.set_text("")
                win._refresh_repo_list()
            if hasattr(win, "_branches_foldout"):
                win._branches_foldout.refresh(
                    [],
                    [],
                    current=None,
                    default_name=None,
                    recent=[],
                    has_github=False,
                )
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
                show_delete_branch,
                show_filtered_commit,
                show_lfs_mismatch,
                show_thank_you,
                show_unknown_authors,
                show_warn_undo,
            )

            show_multi_commit(win, store, {"kind": "Merge"})
            show_multi_commit(win, store, {"kind": "Cherry-pick", "shas": ["deadbeef"]})
            show_warn_force_push(win, store, {"operation": "Rebase"})
            show_confirm_abort(win, "Merge", lambda: None)
            show_conflicts_dialog(win, store, "Merge")
            from github_desktop.ui.multi_commit import show_operation_progress

            progress = show_operation_progress(win, "Rebase", commit_count=2, summary="topic")
            progress.update(type("P", (), {"position": 2, "total": 2, "value": 1.0, "current_commit_summary": "done"})())
            progress.close()
            show_thank_you(win, {"friendly_name": "Ada", "contributions": ["[Fixed] A thing. Thanks @ada!"]})
            from github_desktop.ui.checks import CompletenessDonut

            CompletenessDonut({"success": 2, "failure": 1, "in_progress": 1})
            show_create_branch(win, store, {})
            show_delete_branch(win, store, {"branch": "main"})
            show_acknowledgements(win)
            show_copilot_disclaimer(win, store)
            show_warn_undo(win, store, {"is_working_directory_clean": False})
            show_unknown_authors(win, {"authors": []})
            show_filtered_commit(win, store, {})
            show_lfs_mismatch(win, store)
            from github_desktop.ui.dialogs import show_initialize_lfs

            show_initialize_lfs(win, store, {"paths": [str(git_repo)]})
            from github_desktop.ui.dialogs import show_create_tag

            show_create_tag(win, store, {"sha": "deadbeef"})
            from github_desktop.ui.dialogs import show_ssh_passphrase, show_local_changes_overwritten

            show_ssh_passphrase(win, {"key_path": "/tmp/id_rsa", "on_submit": lambda *_: None})
            show_local_changes_overwritten(win, store, {"files": ["a.txt"], "retry_kind": "checkout"})
            from github_desktop.models import CloningRepository

            cloning = CloningRepository(id=-1, path=str(git_repo), url="https://github.com/desktop/desktop.git")
            store.cloning = [cloning]
            store.select_cloning(cloning.id)
            win._refresh_repo()
            assert win._repo_content.get_visible_child_name() == "cloning"
            store.select_repository(repos[0].id)
            from github_desktop.ui.dialogs import show_create_repository

            show_create_repository(win, store, "")
            from github_desktop.ui.dialogs import show_add_repository

            show_add_repository(win, store, str(git_repo))
            from unittest.mock import patch

            from github_desktop.models import Account
            from github_desktop.ui.dialogs import show_clone_repository, show_publish

            store.accounts = [
                Account(login="octocat", endpoint="https://api.github.com", token="test-token")
            ]
            with patch("github_desktop.github.api.GitHubAPI.fetch_orgs", return_value=[{"login": "acme"}]), patch(
                "github_desktop.github.api.GitHubAPI.fetch_repos", return_value=[]
            ), patch(
                "github_desktop.github.api.GitHubAPI.load_cloneable_repositories",
                lambda self, callback: None,
            ):
                show_publish(win, store)
                show_clone_repository(win, store, {})
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
