"""Linux editors/shells, tag validation, submodule include, cherry-pick, popups."""

from __future__ import annotations

import os
from pathlib import Path

from github_desktop.editors import LINUX_EDITORS, expand_editor_path, first_existing_editor_path
from github_desktop.github.repo_rules import (
    RepoRulesMetadataFailure,
    RepoRulesMetadataFailures,
    repo_rules_failure_heading,
    ruleset_url,
)
from github_desktop.models import (
    AppFileStatusKind,
    DiffSelection,
    DiffSelectionType,
    FileStatus,
    GitHubRepository,
    MaxTagNameLength,
    PopupType,
    SubmoduleStatus,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
    create_tag_error,
    is_partially_committable_submodule,
    is_uncommittable_submodule,
    sanitize_ref_name,
    submodule_include_tooltip,
)
from github_desktop.notifications import get_notifications_permission, notification_preference_hint
from github_desktop.shells import KNOWN_SHELLS, LINUX_SHELL_PATHS
from github_desktop.store import AppStore
from github_desktop.git.ops import get_status


def test_linux_editor_paths_include_flatpak_and_snap() -> None:
    paths = [path for _name, entries, _args in LINUX_EDITORS for path in entries]
    assert "/snap/bin/code" in paths
    assert any("com.visualstudio.code" in path for path in paths)
    assert any(path.startswith(".local/share/flatpak") for path in paths)
    resolved = expand_editor_path(
        ".local/share/flatpak/app/com.visualstudio.code/current/active/export/bin/com.visualstudio.code"
    )
    assert resolved.startswith(os.path.expanduser("~"))
    assert os.path.basename(resolved) == "com.visualstudio.code"


def test_first_existing_editor_path(tmp_path: Path) -> None:
    binary = tmp_path / "code"
    binary.write_text("", encoding="utf-8")
    found = first_existing_editor_path(("/missing/code", str(binary)))
    assert found == str(binary)
    assert first_existing_editor_path(("/definitely/missing",)) is None


def test_linux_shells_include_desktop_terminals() -> None:
    names = {name for name, _bins, _args in KNOWN_SHELLS}
    assert {"Ghostty", "Warp", "MATE Terminal", "URxvt", "LXDE Terminal", "Elementary Terminal"} <= names
    assert LINUX_SHELL_PATHS["Warp"] == ("/usr/bin/warp-terminal",)
    assert LINUX_SHELL_PATHS["Ghostty"] == ("/usr/bin/ghostty",)
    ghostty_args = next(args for name, _bins, args in KNOWN_SHELLS if name == "Ghostty")
    assert ghostty_args == ("--working-directory={cwd}",)


def test_create_tag_validation() -> None:
    assert MaxTagNameLength == 245
    assert create_tag_error("") is None
    assert create_tag_error("v1") is None
    assert "longer than 245" in (create_tag_error("x" * 246) or "")
    assert "already exists" in (create_tag_error("v1", {"v1": "abc"}) or "")
    assert sanitize_ref_name("release 1") == "release-1"


def test_uncommittable_and_partial_submodule() -> None:
    dirty = WorkingDirectoryFileChange(
        "vendor/lib",
        FileStatus(
            AppFileStatusKind.MODIFIED,
            submodule_status=SubmoduleStatus(commit_changed=False, modified_changes=True),
        ),
    )
    partial = WorkingDirectoryFileChange(
        "vendor/lib",
        FileStatus(
            AppFileStatusKind.MODIFIED,
            submodule_status=SubmoduleStatus(commit_changed=True, untracked_changes=True),
        ),
    )
    regular = WorkingDirectoryFileChange("README.md", FileStatus(AppFileStatusKind.MODIFIED))
    assert is_uncommittable_submodule(dirty)
    assert not is_partially_committable_submodule(dirty)
    assert "cannot be added to a commit" in (submodule_include_tooltip(dirty) or "")
    assert is_partially_committable_submodule(partial)
    assert "Only changes that have been committed" in (submodule_include_tooltip(partial) or "")
    assert not is_uncommittable_submodule(regular)
    included = WorkingDirectoryFileChange("ok.txt", FileStatus(AppFileStatusKind.NEW))
    status = WorkingDirectoryStatus.from_files([dirty, included])
    updated = status.with_include_all_files(True)
    by_path = {item.path: item for item in updated.files}
    assert by_path["vendor/lib"].selection.get_selection_type() == DiffSelectionType.NONE
    assert by_path["ok.txt"].selection.get_selection_type() == DiffSelectionType.ALL


def test_popup_stack_preserves_previous(isolated_config) -> None:
    store = AppStore()
    store.show_popup(PopupType.ABOUT)
    store.show_popup(PopupType.PREFERENCES)
    assert store.popup is not None and store.popup.type == PopupType.PREFERENCES
    assert [item.type for item in store.all_popups] == [PopupType.ABOUT, PopupType.PREFERENCES]
    store.close_popup()
    assert store.popup is not None and store.popup.type == PopupType.ABOUT
    pending = store.take_popups()
    assert [item.type for item in pending] == [PopupType.ABOUT]
    assert store.popup is None
    assert store.all_popups == []


def test_cherry_pick_skips_current_branch(isolated_config, git_repo: Path, monkeypatch) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = get_status(str(git_repo))
    current = store.state_for(repo).status.current_branch
    ran: list[bool] = []
    monkeypatch.setattr(store, "_run", lambda work, done: ran.append(True))
    store.cherry_pick_commits(repo, ["deadbeef"], target_branch=current)
    assert ran == []
    store.cherry_pick_commits(repo, ["deadbeef"], target_branch="other")
    assert ran == [True]


def test_set_file_included_skips_uncommittable_submodule(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    dirty = WorkingDirectoryFileChange(
        "vendor/lib",
        FileStatus(
            AppFileStatusKind.MODIFIED,
            submodule_status=SubmoduleStatus(commit_changed=False, modified_changes=True),
        ),
        DiffSelection.from_initial_selection(DiffSelectionType.NONE),
    )
    store.state_for(repo).status = get_status(str(git_repo))
    status = store.state_for(repo).status
    assert status is not None
    status.working_directory = WorkingDirectoryStatus.from_files([dirty])
    store.set_file_included(repo, "vendor/lib", True)
    again = store.state_for(repo).status.working_directory.find_file("vendor/lib")
    assert again is not None
    assert again.selection.get_selection_type() == DiffSelectionType.NONE


def test_repo_ruleset_links_and_failure_copy() -> None:
    gh = GitHubRepository(
        name="hello",
        owner="octocat",
        html_url="https://github.com/octocat/hello",
        clone_url="https://github.com/octocat/hello.git",
        endpoint="https://api.github.com",
    )
    assert ruleset_url(gh, 42) == "https://github.com/octocat/hello/rules/42"
    failed = RepoRulesMetadataFailures(failed=[RepoRulesMetadataFailure('must start with "feat:"', 42)])
    text = repo_rules_failure_heading("This commit message", failed)
    assert "fails 1 rule." in text
    bypassed = RepoRulesMetadataFailures(bypassed=[RepoRulesMetadataFailure("must end with @github.com", 3)])
    caution = repo_rules_failure_heading("The email in your Git config", bypassed)
    assert "bypass it" in caution
    assert "Proceed with caution!" in caution


def test_commit_message_rule_failure_popover_linux_copy() -> None:
    from github_desktop.github.repo_rules import (
        COMMIT_MESSAGE_RULE_FAILURES_HEADER,
        COMMIT_MSG_ERROR_BTN_ID,
        commit_message_failure_hint_aria_label,
        commit_message_rule_failures_header,
    )

    assert commit_message_rule_failures_header() == "Commit message rule failures"
    assert COMMIT_MESSAGE_RULE_FAILURES_HEADER == "Commit message rule failures"
    assert COMMIT_MSG_ERROR_BTN_ID == "commit-message-failure-hint"
    assert commit_message_failure_hint_aria_label(can_bypass=False) == (
        "Error: Commit message fails repository rules. View details."
    )
    assert commit_message_failure_hint_aria_label(can_bypass=True) == (
        "Warning: Commit message fails repository rules, but you can bypass them. View details."
    )


def test_notification_permission_copy(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_DESKTOP_NOTIFICATIONS_PERMISSION", "denied")
    hint = notification_preference_hint(True)
    assert "no permission to display notifications" in hint
    assert "Notifications Settings" in hint
    monkeypatch.setenv("GITHUB_DESKTOP_NOTIFICATIONS_PERMISSION", "default")
    assert "grant permission" in notification_preference_hint(True)
    assert notification_preference_hint(False) == ""
    assert get_notifications_permission() == "default"
