"""Feature-parity inventory: every Desktop popup, menu, and git op is present."""

from __future__ import annotations

from github_desktop.models import BannerType, PopupType, PreferencesTab, RepositorySettingsTab
from github_desktop.git import ops as git_ops
from github_desktop.ui import dialogs
from github_desktop.ui.window import MainWindow


REQUIRED_GIT_FUNCS = [
    "get_status",
    "create_commit",
    "get_working_directory_diff",
    "get_commit_diff",
    "get_commits",
    "get_branches",
    "create_branch",
    "rename_branch",
    "delete_local_branch",
    "checkout_branch",
    "clone_repository",
    "init_repository",
    "fetch",
    "pull",
    "push",
    "merge",
    "rebase",
    "cherry_pick",
    "stash_push",
    "stash_pop",
    "create_tag",
    "discard_paths",
    "discard_changes_from_selection",
    "undo_commit",
    "reset",
    "revert",
    "squash_commits",
    "reorder_commits",
    "read_gitignore",
    "write_gitignore",
    "lfs_track",
    "get_submodules",
    "stage_files",
    "apply_patch_to_index",
]


def test_all_git_ops_exported() -> None:
    for name in REQUIRED_GIT_FUNCS:
        assert hasattr(git_ops, name), name
        assert callable(getattr(git_ops, name))


def test_all_popups_have_handlers() -> None:
    # present_popup mapping must mention every production popup
    import inspect

    src = inspect.getsource(dialogs.present_popup)
    missing = []
    skip = {
        # macOS-only in upstream
        PopupType.UNTRUSTED_CERTIFICATE,
    }
    for popup in PopupType:
        if popup in skip:
            continue
        if popup.value not in src and popup.name not in src and f"PopupType.{popup.name}" not in src:
            missing.append(popup)
    assert missing == [], f"dialogs missing {missing}"


def test_preferences_tabs() -> None:
    assert list(PreferencesTab) == [
        PreferencesTab.ACCOUNTS,
        PreferencesTab.INTEGRATIONS,
        PreferencesTab.GIT,
        PreferencesTab.APPEARANCE,
        PreferencesTab.NOTIFICATIONS,
        PreferencesTab.PROMPTS,
        PreferencesTab.ADVANCED,
        PreferencesTab.ACCESSIBILITY,
    ]


def test_repository_settings_tabs() -> None:
    assert {t.value for t in RepositorySettingsTab} == {
        "Remote",
        "IgnoredFiles",
        "GitConfig",
        "ForkSettings",
    }


def test_banners_defined() -> None:
    assert BannerType.SUCCESSFUL_MERGE in BannerType
    assert BannerType.REBASE_CONFLICTS_FOUND in BannerType
    assert BannerType.SUCCESSFUL_CHERRY_PICK in BannerType


def test_window_actions_cover_menus() -> None:
    src = open(MainWindow.__init__.__code__.co_filename, encoding="utf-8").read()
    for action in [
        "new-repository",
        "clone-repository",
        "preferences",
        "push",
        "pull",
        "fetch",
        "create-branch",
        "merge-branch",
        "rebase-branch",
        "open-pull-request",
        "generate-commit-message",
        "open-in-shell",
        "open-external-editor",
        "create-tag",
        "stash-all",
    ]:
        assert action in src
    for phrase in [
        "Discard changes",
        "Copy SHA",
        "Side-by-side",
        "Cherry-pick",
        "Ignore file",
    ]:
        assert phrase in src
