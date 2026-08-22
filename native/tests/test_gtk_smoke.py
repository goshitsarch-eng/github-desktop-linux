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
    from github_desktop.ui.dialogs import show_about, show_preferences, show_release_notes, show_pull_request_review, show_checks, show_push_branch_commits
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
            from github_desktop.ui.menus import REPOSITORY_TOOLBAR_DESCRIPTION

            assert win._repo_desc.get_text() == REPOSITORY_TOOLBAR_DESCRIPTION
            assert win._repo_title.get_text() != "No repository"
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
            assert win.lookup_action("new-repository").get_enabled() is False
            store.welcome_step = None
            from github_desktop.models import Branch, BranchType

            repo_state = store.state_for(repos[0])
            tip_name = repo_state.status.current_branch if repo_state.status else "main"
            tip_sha = (repo_state.status.current_tip if repo_state.status else None) or "HEAD"
            repo_state.branches = [Branch(tip_name or "main", None, tip_sha, BranchType.LOCAL)]
            win._sync_menu_state()
            assert win.lookup_action("new-repository").get_enabled() is True
            assert win.lookup_action("push").get_enabled() is True
            assert win.lookup_action("create-branch").get_enabled() is True
            assert win.lookup_action("delete-branch").get_enabled() is False
            assert win.lookup_action("pull").get_enabled() is False
            assert win.lookup_action("stash-all").get_enabled() is True
            assert win.lookup_action("discard-all").get_enabled() is True
            assert win._hidden_changes_warning.has_css_class("hidden-changes-warning")
            assert win._hidden_changes_warning.get_name() == "hidden-changes-warning"
            assert not win._hidden_changes_warning.get_visible()
            from github_desktop.models import AheadBehind

            assert win._push_menu_label() == "Push"
            from github_desktop.menu_update import file_quit_label, go_to_summary_label

            def _gio_menu_labels(model) -> list[str]:
                labels: list[str] = []
                for index in range(model.get_n_items()):
                    value = model.get_item_attribute_value(index, "label", None)
                    if value is not None:
                        labels.append(value.get_string())
                    for link_name in ("submenu", "section"):
                        linked = model.get_item_link(index, link_name)
                        if linked is not None:
                            labels.extend(_gio_menu_labels(linked))
                return labels

            menu_labels = _gio_menu_labels(win._app_menu())
            assert file_quit_label() in menu_labels
            assert go_to_summary_label() in menu_labels
            assert "Quit" not in menu_labels
            assert "Go to summary" not in menu_labels
            if repo_state.status is not None:
                repo_state.status.current_upstream_branch = "origin/main"
            repo_state.ahead_behind = AheadBehind(ahead=1, behind=1)
            repo_state.force_push_with_lease_on[tip_name or "main"] = tip_sha
            assert win._push_menu_label() == "Force push…"
            store.settings.confirm_force_push = False
            store.settings.ask_for_confirmation_on_force_push = False
            pushed: list[bool] = []
            original_push = store.push_repo
            store.push_repo = lambda _repo, force=False, on_success=None: pushed.append(force)  # type: ignore[method-assign]
            win._push_from_menu()
            assert pushed == [True]
            store.push_repo = original_push  # type: ignore[method-assign]
            store.settings.confirm_force_push = True
            store.settings.ask_for_confirmation_on_force_push = True
            repo_state.force_push_with_lease_on.clear()
            repo_state.ahead_behind = None
            if repo_state.status is not None:
                repo_state.status.current_upstream_branch = None
            status = store.state_for(repos[0]).status
            saved_branch = status.current_branch if status else "main"
            saved_tip = status.current_tip if status else None
            if status is not None:
                status.current_branch = None
            win._sync_menu_state()
            assert win.lookup_action("push").get_enabled() is False
            assert win.lookup_action("compare-to-branch").get_enabled() is False
            if status is not None:
                status.current_branch = saved_branch
                status.current_tip = saved_tip
            repos[0].is_missing = True
            win._sync_menu_state()
            assert win.lookup_action("open-external-editor").get_enabled() is False
            assert win.lookup_action("remove-repository").get_enabled() is True
            from github_desktop.models import GitHubRepository

            repos[0].github = GitHubRepository(
                "app", "me", "https://github.com/me/app", "https://github.com/me/app.git"
            )
            win._sync_menu_state()
            assert win.lookup_action("view-on-github").get_enabled() is True
            repos[0].is_missing = False
            repos[0].github = None
            win._sync_menu_state()
            assert win.lookup_action("push").get_enabled() is True
            from github_desktop.models import Popup, PopupType as MenuPopupType

            store._popups.add_popup(Popup(MenuPopupType.ABOUT))
            win._sync_menu_state()
            assert win.lookup_action("push").get_enabled() is False
            assert win.lookup_action("new-repository").get_enabled() is False
            store._popups.clear()
            win._sync_menu_state()
            assert win.lookup_action("push").get_enabled() is True
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
            assert viewer.has_css_class("seamless-diff-switcher")
            viewer.render(None, path="README.md")
            assert viewer.isLoadingDiff is True
            assert viewer.has_css_class("loading")
            assert not viewer.has_css_class("has-diff")
            assert viewer._loading_indicator.get_visible()
            viewer.render(sample, path="README.md", selection=selection, side_by_side=True)
            assert viewer.isLoadingDiff is False
            kept = viewer._inner.get_first_child()
            assert kept is not None
            viewer.render(None, path="other.md")
            assert viewer.isLoadingDiff is True
            assert viewer.has_css_class("loading")
            assert viewer.has_css_class("has-diff")
            assert viewer._inner.get_first_child() is kept
            viewer.render(sample, path="README.md", selection=selection, side_by_side=False)
            assert viewer.isLoadingDiff is False
            from github_desktop.ui.diff_view import diff_search_no_results, diff_search_result_message

            viewer.start_search()
            viewer._run_search("zzzznotfound", "next")
            assert viewer._search_count.get_text() == diff_search_no_results("zzzznotfound")
            viewer._run_search("hello", "next")
            assert viewer._search_count.get_text().startswith("Result ")
            assert 'for "hello"' in viewer._search_count.get_text()
            viewer.close_search()
            viewer._on_expand_whole_clicked()
            assert viewer.ariaLiveMessage == "Expanded"
            assert viewer._aria_live.get_text() == "Expanded"
            viewer.render(None, path="")
            assert viewer.isLoadingDiff is False
            viewer.render(BinaryDiff(), path="photo.bin")
            from github_desktop.models import ImageDiff, ImageDiffType

            png = bytes.fromhex(
                "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c089"
                "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
            )
            viewer.render(ImageDiff(previous=png, current=png), path="a.png", image_mode=ImageDiffType.SWIPE.value)
            viewer.render(ImageDiff(previous=None, current=png), path="new.png")
            assert hasattr(win, "_stash_viewer")
            assert hasattr(win, "_commit_summary")
            assert hasattr(win, "_history_filter")
            assert hasattr(win, "_repo_content")
            assert hasattr(win, "_missing_page")
            assert hasattr(win, "_tutorial_panel")
            win._tutorial_panel.refresh(TutorialStep.PICK_EDITOR, "GNOME Text Editor")
            from github_desktop.models import Remote

            assert win._branch_btn.has_css_class("nudge-arrow")
            assert win._summary.has_css_class("summary-field")
            assert win._summary.has_css_class("nudge-arrow")
            store.tutorial_step = TutorialStep.CREATE_BRANCH
            win._update_tutorial_nudge()
            assert win._branch_btn.has_css_class("nudge-arrow-up")
            assert not win._summary.has_css_class("nudge-arrow-left")
            assert win._branch_nudge.get_visible()
            store.tutorial_step = TutorialStep.MAKE_COMMIT
            win._update_tutorial_nudge()
            assert win._summary.has_css_class("nudge-arrow-left")
            assert not win._branch_btn.has_css_class("nudge-arrow-up")
            assert win._commit_nudge.get_visible()
            repo_state = store.state_for(repos[0])
            repo_state.remotes = [Remote(name="origin", url="https://github.com/octocat/hello.git")]
            if repo_state.status is not None:
                repo_state.status.current_upstream_branch = None
            store.tutorial_step = TutorialStep.PUSH_BRANCH
            win._update_tutorial_nudge()
            assert win._push_btn.has_css_class("nudge-arrow")
            assert win._push_btn.has_css_class("nudge-arrow-up")
            assert win._push_nudge.get_visible()
            store.tutorial_step = TutorialStep.NOT_APPLICABLE
            win._update_tutorial_nudge()
            assert not win._branch_btn.has_css_class("nudge-arrow-up")
            assert not win._push_btn.has_css_class("nudge-arrow-up")
            assert not win._summary.has_css_class("nudge-arrow-left")
            from github_desktop.ui.length_hint import (
                LENGTH_HINT,
                SummaryLengthHint,
            )

            assert isinstance(win._length_hint, SummaryLengthHint)
            assert win._length_hint.has_css_class(LENGTH_HINT)
            assert not win._length_hint.get_visible()
            win._summary.set_text("x" * 51)
            win._update_commit_warnings()
            assert win._length_hint.get_visible()
            assert win._summary_row.has_css_class("with-trailing-icon")
            assert win._length_hint.renderSummaryLengthHint() is win._length_hint
            assert win._length_hint.ariaLiveMessage()
            win._summary.set_text("short")
            win._update_commit_warnings()
            assert not win._length_hint.get_visible()
            from github_desktop.ui.copy_button import (
                COPIED,
                COPY_BUTTON,
                COPY_THE_FULL_SHA,
                CopyButton,
            )

            copy_btn = CopyButton(copy_content="deadbeef", aria_label=COPY_THE_FULL_SHA)
            assert copy_btn.has_css_class(COPY_BUTTON)
            assert copy_btn.get_tooltip_text() == COPY_THE_FULL_SHA
            assert copy_btn.showCopied is False
            copy_btn._on_copy()
            assert copy_btn.showCopied is True
            assert copy_btn.get_tooltip_text() == COPIED
            assert copy_btn.ariaLiveMessage() == COPIED
            assert win._commit_summary._sha_btn.has_css_class(COPY_BUTTON)
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
                from github_desktop.models import Branch, BranchType as _BranchType

                win._branches_foldout.refresh(
                    [
                        Branch("main", None, "aaa", _BranchType.LOCAL),
                        Branch("topic", None, "bbb", _BranchType.LOCAL),
                    ],
                    [],
                    current="topic",
                    default_name="main",
                    recent=["topic"],
                    has_github=True,
                )
                foldout_labels: list[str] = []
                row = win._branches_foldout._branch_list.get_first_child()
                while row is not None:
                    child = row.get_child()
                    if hasattr(child, "get_text"):
                        foldout_labels.append(child.get_text())
                    row = row.get_next_sibling()
                assert "Default branch" in foldout_labels
                assert "Recent branches" in foldout_labels
                prs_page = win._branches_foldout._stack.get_child_by_name("prs")
                assert win._branches_foldout._stack.get_page(prs_page).get_title() == "Pull requests"
                from github_desktop.ui.branches import (
                    CREATE_A_PULL_REQUEST_LINK,
                    no_pull_requests_cta_sentence,
                )

                win._branches_foldout._github = True
                win._branches_foldout._on_default_branch = False
                empty = win._branches_foldout._pr_empty_state(False)
                empty_box = empty.get_child()
                assert empty_box.has_css_class("no-pull-requests")
                cta = empty_box.get_last_child()
                assert cta.has_css_class("call-to-action")
                assert cta.get_first_child().get_text() == no_pull_requests_cta_sentence(
                    is_on_default_branch=False
                )
                assert cta.get_first_child().get_next_sibling().get_child().get_text() == (
                    CREATE_A_PULL_REQUEST_LINK
                )
            show_release_notes(win)
            show_push_branch_commits(win, store, {"unpublished": True, "branch": "topic"})
            show_push_branch_commits(win, store, {"unpublished": False, "unpushed": 2, "branch": "topic"})
            show_checks(win, store, {"error": "CI failed", "title": "Demo PR"})
            from github_desktop.ui.checks import show_rerun_checks
            from github_desktop.models import RefCheck
            from github_desktop.ui.avatar import AvatarStack

            show_rerun_checks(win, store, {"failed_only": True, "checks": []})
            stack = AvatarStack([("Ada Lovelace", "ada@example.com"), ("Grace Hopper", "grace@example.com")], size=24)
            assert stack.get_first_child() is not None
            from github_desktop.ui.commit_message_avatar import CommitMessageAvatar

            avatar = CommitMessageAvatar(store, win)
            avatar.refresh(repos[0])
            assert avatar.renderAvatar() is avatar.widget
            assert avatar.renderWarningPopover() is not None
            assert avatar.renderGitConfigPopover() is not None
            sample_run = RefCheck(id=1, name="build", description="Failed after 1m", status="completed", conclusion="failure")
            show_checks(win, store, {"error": "1 check failed in your pull request", "title": "Demo PR", "checks": [sample_run]})
            from github_desktop.github.ci_checks import THERE_ARE_NO_STEPS, VIEW_CHECK_DETAILS, areNoSteps
            from github_desktop.ui.checks import CICheckRunNoStepItem, _run_expander

            assert areNoSteps(sample_run)
            blank = CICheckRunNoStepItem(html_url="https://github.com/example/repo/runs/1")
            assert blank.has_css_class("ci-check-run-no-steps")
            copy_box = blank.get_first_child()
            assert copy_box.get_first_child().get_text() == THERE_ARE_NO_STEPS
            details_btn = copy_box.get_first_child().get_next_sibling()
            assert details_btn.get_child().get_first_child().get_text() == VIEW_CHECK_DETAILS
            expander = _run_expander(sample_run)
            assert expander.has_css_class("no-steps")
            from github_desktop.models import CheckStep

            stepped = RefCheck(
                id=2,
                name="linux",
                description="Successful in 1m",
                status="completed",
                conclusion="success",
                steps=[CheckStep(name="Set up job", number=1, status="completed", conclusion="success")],
            )
            assert not _run_expander(stepped).has_css_class("no-steps")
            from github_desktop.ui.checks import CICheckRunStepListHeader
            from github_desktop.github.ci_checks import get_combined_status_summary

            header = CICheckRunStepListHeader(stepped)
            assert header.has_css_class("ci-check-run-steps-header")
            assert header.get_first_child().get_text() == get_combined_status_summary(
                stepped.steps, "step"
            )
            empty_header = CICheckRunStepListHeader(sample_run)
            assert not empty_header.get_visible()
            from github_desktop.ui.checks import LoadingCheckRuns
            from github_desktop.github.ci_checks import CHECK_RUNS_INCOMING, CHECK_RUN_STEPS_INCOMING, STAND_BY

            loading = LoadingCheckRuns(steps=False)
            assert loading.has_css_class("loading-check-runs")
            title = loading.get_first_child().get_next_sibling()
            assert title.get_text() == STAND_BY
            assert title.get_next_sibling().get_text() == CHECK_RUNS_INCOMING
            steps_loading = LoadingCheckRuns(steps=True)
            assert steps_loading.get_first_child().get_next_sibling().get_next_sibling().get_text() == CHECK_RUN_STEPS_INCOMING
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
            store.select_repository(None)
            win._refresh_repo()
            assert win._repo_content.get_visible_child_name() == "none"
            assert win._no_repository_selected.get_title() == "No repository selected"
            assert win._no_repository_selected.has_css_class("blankslate")
            assert win._no_repository_selected.has_css_class("panel")
            store.select_repository(repos[0].id)
            (git_repo / "second.txt").write_text("two\n", encoding="utf-8")
            from github_desktop.git.ops import get_status as refresh_status
            from github_desktop.filter_changes import files_selected_label

            store.state_for(repos[0]).status = refresh_status(str(git_repo))
            win._refresh_files()
            file_rows = []
            child = win._file_list.get_first_child()
            while child is not None:
                if getattr(child, "_file", None) is not None:
                    file_rows.append(child)
                child = child.get_next_sibling()
            assert len(file_rows) >= 2
            win._building = True
            try:
                win._file_list.unselect_all()
                win._file_list.select_row(file_rows[0])
                win._file_list.select_row(file_rows[1])
            finally:
                win._building = False
            win._on_selected_rows_changed(win._file_list)
            assert win._changes_diff_stack.get_visible_child_name() == "multiple"
            assert win._multiple_selection_label.get_text() == files_selected_label(2)
            assert win._multiple_selection.has_css_class("blankslate")
            assert win._multiple_selection.get_name() == "no-changes"
            win._building = True
            try:
                win._file_list.unselect_all()
                win._file_list.select_row(file_rows[0])
            finally:
                win._building = False
            win._on_selected_rows_changed(win._file_list)
            assert win._changes_diff_stack.get_visible_child_name() == "diff"
            from github_desktop.filter_changes import hidden_changes_adjust_filters_label
            from github_desktop.models import ChangesListFilter

            assert not win._hidden_changes_warning.get_visible()
            store.set_filter_kind(repos[0], "new", True)
            assert win._hidden_changes_warning.get_visible()
            included = [
                file
                for file in store.state_for(repos[0]).status.working_directory.files
                if file.include
            ]
            assert win._hidden_changes_link_label.get_text() == hidden_changes_adjust_filters_label(
                len(included)
            )
            win._show_files_to_be_committed()
            assert store.state_for(repos[0]).file_filter == ChangesListFilter.INCLUDED.value
            assert not store.state_for(repos[0]).filter_new
            assert not win._hidden_changes_warning.get_visible()
            store.clear_changes_filter(repos[0])
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
