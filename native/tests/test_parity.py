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
    "get_working_directory_lines",
    "get_blob_lines",
    "get_commit_diff",
    "get_commits",
    "get_changeset_data",
    "get_commit_range_changed_files",
    "get_commit_range_diff",
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
    "get_repository_kind",
    "add_safe_directory",
    "stage_files",
    "apply_patch_to_index",
    "determine_mergeability",
    "get_commits_between",
    "get_ahead_behind_range",
    "get_boolean_config_value",
    "warn_about_remote_commits",
    "install_global_lfs_filters",
    "install_lfs_hooks",
    "format_patch",
    "parse_trailers",
    "merge_trailers",
    "get_global_config_path",
    "is_using_lfs",
    "is_tracked_by_lfs",
    "get_recent_branches",
    "get_files_with_conflict_markers",
    "parse_credential",
    "format_credential",
    "get_branch_checkouts",
    "fetch_refspec",
    "get_binary_paths",
    "get_cherry_pick_snapshot",
    "get_rebase_snapshot",
    "get_last_desktop_stash_entry_for_branch",
    "move_stash_entry",
    "fetch_tags_to_push",
    "fast_forward_branches",
    "get_branches_differing_from_upstream",
    "get_merged_branches",
    "get_index_changes",
    "check_patch",
    "get_files_diff_text",
    "get_branch_merge_base_diff",
    "get_branch_merge_base_changed_files",
    "get_branches_pointed_at",
    "get_authors",
    "get_symbolic_ref",
    "prune_forked_remotes",
    "find_forked_remotes_to_prune",
    "create_desktop_stash_entry",
    "discard_working_files",
    "ensure_upstream_remote",
    "delete_ref",
    "undo_first_commit",
    "do_merge_commits_exist_after_commit",
    "get_last_fetched",
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
    assert BannerType.OPEN_THANK_YOU_CARD in BannerType


def test_window_actions_cover_menus() -> None:
    src = open(MainWindow.__init__.__code__.co_filename, encoding="utf-8").read()
    from github_desktop.ui import stash, history, diff_view

    src += open(stash.__file__, encoding="utf-8").read()
    src += open(history.__file__, encoding="utf-8").read()
    src += open(diff_view.__file__, encoding="utf-8").read()
    from github_desktop.ui import dialogs as dialogs_mod, tutorial, checks
    from github_desktop.github import ci_checks, repo_rules
    from github_desktop.ui import multi_commit

    src += open(dialogs_mod.__file__, encoding="utf-8").read()
    src += open(tutorial.__file__, encoding="utf-8").read()
    src += open(checks.__file__, encoding="utf-8").read()
    src += open(ci_checks.__file__, encoding="utf-8").read()
    src += open(multi_commit.__file__, encoding="utf-8").read()
    src += open(repo_rules.__file__, encoding="utf-8").read()
    from github_desktop import thank_you, custom_integration
    from github_desktop.git import progress as git_progress

    src += open(thank_you.__file__, encoding="utf-8").read()
    src += open(custom_integration.__file__, encoding="utf-8").read()
    src += open(git_progress.__file__, encoding="utf-8").read()
    src += open(git_ops.__file__, encoding="utf-8").read()
    from github_desktop.git import askpass as git_askpass
    from github_desktop import store as store_mod, models as models_mod

    src += open(git_askpass.__file__, encoding="utf-8").read()
    src += open(store_mod.__file__, encoding="utf-8").read()
    src += open(models_mod.__file__, encoding="utf-8").read()
    from github_desktop import push_pull, commit_dnd
    from github_desktop.ui import css as css_mod

    src += open(push_pull.__file__, encoding="utf-8").read()
    src += open(commit_dnd.__file__, encoding="utf-8").read()
    src += open(css_mod.__file__, encoding="utf-8").read()
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
        "install-cli",
        "toggle-changes-filter",
        "zoom-in",
        "update-from-default",
        "release-notes",
    ]:
        assert action in src
    for phrase in [
        "Discard changes",
        "Copy SHA",
        "Side-by-side",
        "Cherry-pick",
        "Ignore file",
        "Install command line tool",
        "Zoom in",
        "Modified",
        "Stashed changes",
        "Search commits",
        "Can't find this repository",
        "Open in default program",
        "Switch to pull request",
        "Release notes",
        "Get started",
        "Exit tutorial",
        "Re-run failed checks",
        "All checks have passed",
        "View logs",
        "GitHub Enterprise",
        "line endings",
        "Create a merge commit",
        "Checking for ability to merge automatically",
        "View conflicts",
        "Confirm abort",
        "will require force push",
        "Do not show this message again",
        "repository rules",
        "Open with default program",
        "Completeness indicator",
        "protected branch",
        "I understand",
        "Copilot is powered by AI",
        "Able to merge automatically",
        "Stop amending",
        "most recent commit",
        "Undo commit?",
        "hidden changes",
        "Update existing Git LFS filters",
        "Edit global Git config",
        "Unknown co-authors",
        "Cloning…",
        "Thanks so much for all your hard work",
        "You contributed:",
        "Configure custom editor",
        "%TARGET_PATH%",
        "leftover conflict marker",
        "Leftover conflict markers remain",
        "Open Your Card",
        "Explore projects on GitHub",
        "You're done!",
        "Explore GitHub",
        "The branch also exists on the remote",
        "Yes, delete this branch on the remote",
        "This branch may have an open pull request associated with it.",
        "1 tag",
        "github-desktop-",
        "GIT_ASKPASS",
        "The authenticity of host",
        "Publish your repository to GitHub",
        "Commit anyway",
        "View stash",
        "Re-authorization required",
        "versioning-large-files",
        "Contribute to the parent repository",
        "Stash all changes?",
        "placeholder_id",
        "discarded permanently",
        "Force push",
        "detached HEAD",
        "Selecting lines is disabled when hiding whitespace changes",
        "Return to in progress tutorial",
        "Copy relative path",
        "This email address doesn't match your GitHub account",
        "with rebase",
        "rebase.backend=merge",
        "leave the tutorial",
        "Last fetched",
        "Never fetched",
        "Allow me to expose this secret",
        "It's a false positive",
        "Unable to squash",
        "Unable to reorder",
        "commit-drop-squash",
        "underline-links",
        "Reverting first commit",
        "pan-down-symbolic",
    ]:
        assert phrase in src
