"""Desktop copy: banners, file status labels, clone empty list, menus, trash."""

from __future__ import annotations

from github_desktop.git.progress import format_bytes
from github_desktop.models import (
    AppFileStatusKind,
    Banner,
    BannerType,
    FileStatus,
    PopupType,
    map_status,
    path_label,
)
from github_desktop.store import AppStore
from github_desktop.ui.dialogs import _clone_list_empty_title
from github_desktop.ui.diff_view import _image_two_up_footer, _image_two_up_summary
from github_desktop.ui.menus import (
    FileDoesNotExistOnDiskLabel,
    TrashNameLabel,
    committed_file_context_items,
    is_safe_file_extension,
    view_on_github_label,
)
from github_desktop.ui.window import format_banner_text


def test_map_status_and_path_label() -> None:
    assert map_status(FileStatus(kind=AppFileStatusKind.UNTRACKED)) == "New"
    assert map_status(FileStatus(kind=AppFileStatusKind.NEW)) == "New"
    resolved = FileStatus(kind=AppFileStatusKind.CONFLICTED, conflict_marker_count=0)
    assert map_status(resolved) == "Resolved"
    conflicted = FileStatus(kind=AppFileStatusKind.CONFLICTED, conflict_marker_count=3)
    assert map_status(conflicted) == "Conflicted"
    renamed = FileStatus(kind=AppFileStatusKind.RENAMED, old_path="old.txt")
    assert path_label("new.txt", renamed) == "old.txt → new.txt"
    assert path_label("keep.txt", FileStatus(kind=AppFileStatusKind.MODIFIED)) == "keep.txt"


def test_format_bytes_unfixed_matches_desktop_two_up() -> None:
    assert format_bytes(1024, 1) == "1.0 KiB"
    assert format_bytes(1024, 2, False) == "1 KiB"
    assert format_bytes(1536, 2, False) == "1.5 KiB"


def test_success_banner_copy() -> None:
    merge = Banner(BannerType.SUCCESSFUL_MERGE, our_branch="main", their_branch="feature")
    assert format_banner_text(BannerType.SUCCESSFUL_MERGE, merge) == "Successfully merged feature into main"
    merge_ours = Banner(BannerType.SUCCESSFUL_MERGE, our_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_MERGE, merge_ours) == "Successfully merged into main"
    rebase = Banner(BannerType.SUCCESSFUL_REBASE, target_branch="topic", their_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_REBASE, rebase) == "Successfully rebased topic onto main"
    cherry = Banner(BannerType.SUCCESSFUL_CHERRY_PICK, count=2, target_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_CHERRY_PICK, cherry) == "Successfully copied 2 commits to main."
    squash = Banner(BannerType.SUCCESSFUL_SQUASH, count=1)
    assert format_banner_text(BannerType.SUCCESSFUL_SQUASH, squash) == "Successfully squashed 1 commit."
    merge_conflicts = Banner(BannerType.MERGE_CONFLICTS_FOUND, our_branch="main")
    assert format_banner_text(BannerType.MERGE_CONFLICTS_FOUND, merge_conflicts) == (
        "Resolve conflicts and commit to merge into main."
    )
    rebase_conflicts = Banner(BannerType.REBASE_CONFLICTS_FOUND, target_branch="topic")
    assert format_banner_text(BannerType.REBASE_CONFLICTS_FOUND, rebase_conflicts) == (
        "Resolve conflicts to continue rebasing topic."
    )
    cherry_conflicts = Banner(BannerType.CHERRY_PICK_CONFLICTS_FOUND, target_branch="main")
    assert format_banner_text(BannerType.CHERRY_PICK_CONFLICTS_FOUND, cherry_conflicts) == (
        "Resolve conflicts to continue cherry-picking onto main."
    )
    up_to_date = Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, our_branch="main", their_branch="origin/main")
    assert format_banner_text(BannerType.BRANCH_ALREADY_UP_TO_DATE, up_to_date) == (
        "main is already up to date with origin/main"
    )
    cherry_undone = Banner(BannerType.CHERRY_PICK_UNDONE, count=2, target_branch="main")
    assert "Cherry-pick undone. Successfully removed the 2 copied commits from main." in format_banner_text(
        BannerType.CHERRY_PICK_UNDONE, cherry_undone
    )
    squash_undone = Banner(BannerType.SQUASH_UNDONE, count=1)
    assert format_banner_text(BannerType.SQUASH_UNDONE, squash_undone) == "Squash of 1 commit undone."
    reorder = Banner(BannerType.SUCCESSFUL_REORDER, count=3)
    assert format_banner_text(BannerType.SUCCESSFUL_REORDER, reorder) == "Successfully reordered 3 commits."


def test_clone_list_empty_copy() -> None:
    class Account:
        login = "hubot"
        friendly_endpoint = "GitHub.com"

    assert (
        _clone_list_empty_title(Account(), "desktop")
        == "Sorry, I can't find any repository matching desktop"
    )
    assert (
        _clone_list_empty_title(Account(), "")
        == "Looks like there are no repositories for hubot on GitHub.com."
    )


def test_image_two_up_copy() -> None:
    footer = _image_two_up_footer(None, b"x" * 1024)
    assert footer.startswith("W: 0px | H: 0px | Size: ")
    assert "KiB" in footer
    assert _image_two_up_summary(b"a" * 100, b"a" * 100) == "Diff: No size difference"
    bigger = _image_two_up_summary(b"a" * 1000, b"a" * 2000)
    assert bigger.startswith("Diff: +")
    assert "(200%)" in bigger


def test_committed_file_menu_missing_and_github_enterprise() -> None:
    assert is_safe_file_extension(".sh")
    assert view_on_github_label(enterprise=True) == "View on GitHub Enterprise"
    assert view_on_github_label(enterprise=False) == "View on GitHub"
    missing = committed_file_context_items(
        full_path="/tmp/missing.txt",
        relative_path="missing.txt",
        exists=False,
        editor_label="Open in external editor",
        on_reveal=lambda: None,
        on_open_editor=lambda: None,
        on_open_default=lambda: None,
        view_github_label="View on GitHub",
        on_view_github=lambda: None,
        view_github_enabled=False,
    )
    assert missing == [(FileDoesNotExistOnDiskLabel, missing[0][1], False)]
    present = committed_file_context_items(
        full_path="/tmp/file.txt",
        relative_path="file.txt",
        exists=True,
        editor_label="Open in Code",
        on_reveal=lambda: None,
        on_open_editor=lambda: None,
        on_open_default=lambda: None,
        view_github_label="View on GitHub Enterprise",
        on_view_github=lambda: None,
        view_github_enabled=False,
    )
    labels = [item[0] for item in present if item is not None]
    assert labels[0] == "Show in your File Manager"
    assert "Copy file path" in labels
    assert "Copy relative file path" in labels
    assert "View on GitHub Enterprise" in labels


def test_remove_repository_trash_failure_keeps_repo(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    monkeypatch.setattr("github_desktop.store.move_item_to_trash", lambda _path: False)
    store.remove_repository(repo, True)
    assert any(item.id == repo.id for item in store.repositories)
    assert store.popup is not None
    assert store.popup.type == PopupType.ERROR
    assert f"Failed to move the repository directory to {TrashNameLabel}." in store.popup.payload["error"]


def test_remove_repository_trash_success(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    monkeypatch.setattr("github_desktop.store.move_item_to_trash", lambda _path: True)
    store.remove_repository(repo, True)
    assert all(item.id != repo.id for item in store.repositories)
    assert git_repo.exists()


def test_commit_autocompletion_matches_desktop() -> None:
    from types import SimpleNamespace

    from github_desktop.ui.autocompletion import (
        SUMMARY_LENGTH_HINT,
        UNREACHABLE_COMMITS_LEARN_MORE,
        completion_insert_text,
        completion_matches,
        summary_length_hint,
        token_before_cursor,
        unreachable_commits_message,
    )
    from github_desktop.ui.emoji import matching_shortcodes

    assert token_before_cursor("Fix #12", 7) == "#12"
    assert token_before_cursor("hey @octo", 9) == "@octo"
    assert completion_insert_text("#42 Fix login") == "#42"
    assert completion_insert_text("@hubot") == "@hubot"
    assert completion_insert_text(":rocket:") == "🚀"
    state = SimpleNamespace(
        issues=[(1, "First"), (42, "Fix login"), (12, "Docs")],
        mentions=["octocat", "hubot"],
        mentionables=[{"login": "octocat", "name": "The Octocat"}],
        current_branch_protected=True,
        status=SimpleNamespace(current_branch="main"),
    )
    issues = completion_matches(state, "#1")
    assert "#12 Docs" in issues
    assert "#1 First" in issues
    assert "#42 Fix login" not in issues
    users = completion_matches(state, "@oc")
    assert any(item.startswith("@octocat") for item in users)
    assert ":tada:" in matching_shortcodes("tad")
    assert matching_shortcodes(":")
    assert summary_length_hint("x" * 51, True) == SUMMARY_LENGTH_HINT
    assert summary_length_hint("short", True) is None
    assert "not in the ancestry path" in unreachable_commits_message(unreachable_tab=True, count=2)
    assert "Learn more" not in unreachable_commits_message(unreachable_tab=False, count=1)
    assert "unreachable-commits.md" in UNREACHABLE_COMMITS_LEARN_MORE


def test_refresh_issues_is_noop_without_github(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    store.refresh_issues(repos[0])
    assert store.state_for(repos[0]).issues == []


def test_commit_summary_placeholder_matches_desktop() -> None:
    from github_desktop.models import (
        AppFileStatusKind,
        DiffSelection,
        DiffSelectionType,
        FileStatus,
        WorkingDirectoryFileChange,
        commit_summary_placeholder,
    )

    created = WorkingDirectoryFileChange(
        "src/app.py",
        FileStatus(kind=AppFileStatusKind.NEW),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    deleted = WorkingDirectoryFileChange(
        "gone.txt",
        FileStatus(kind=AppFileStatusKind.DELETED),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    modified = WorkingDirectoryFileChange(
        "readme.md",
        FileStatus(kind=AppFileStatusKind.MODIFIED),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    excluded = WorkingDirectoryFileChange(
        "skip.py",
        FileStatus(kind=AppFileStatusKind.MODIFIED),
        DiffSelection.from_initial_selection(DiffSelectionType.NONE),
    )
    assert commit_summary_placeholder([created]) == "Create app.py"
    assert commit_summary_placeholder([deleted]) == "Delete gone.txt"
    assert commit_summary_placeholder([modified]) == "Update readme.md"
    assert commit_summary_placeholder([created, modified]) == "Summary (required)"
    assert commit_summary_placeholder([created], tutorial=True) == "Summary (required)"
    assert commit_summary_placeholder([created, excluded]) == "Create app.py"


def test_history_tokens_markup_links_issues() -> None:
    from github_desktop.text_tokens import Tokenizer, tokens_as_markup

    markup = tokens_as_markup(Tokenizer().tokenize("See https://example.com"))
    assert 'href="https://example.com"' in markup
    assert "See " in markup


def test_delete_oauth_token_skips_empty_token() -> None:
    from github_desktop.github.api import delete_oauth_token
    from github_desktop.models import Account

    account = Account(login="hubot", endpoint="https://api.github.com", token="")
    assert delete_oauth_token(account) is False


def test_get_discard_label_matches_desktop_linux() -> None:
    from github_desktop.git.diff import DiffRangeType
    from github_desktop.ui.diff_view import get_discard_label

    assert get_discard_label(DiffRangeType.ADDITIONS, 1) == "Discard added line…"
    assert get_discard_label(DiffRangeType.DELETIONS, 2) == "Discard removed lines…"
    assert get_discard_label(DiffRangeType.MIXED, 1, confirm=False) == "Discard modified line"
    assert get_discard_label(DiffRangeType.ADDITIONS, 2, confirm=False) == "Discard added lines"


def test_keyboard_reorder_copy() -> None:
    from github_desktop.ui.window import keyboard_reorder_insert_message, keyboard_reorder_intro_message

    assert keyboard_reorder_intro_message(1) == (
        "Use the Up and Down arrow keys to choose a new location for the selected commit, "
        "then press Enter to confirm or Escape to cancel."
    )
    assert "selected commits" in keyboard_reorder_intro_message(2)
    assert keyboard_reorder_insert_message(1, 0, 5) == (
        "Press Enter to insert the selected commit before commit 1 or Escape to cancel."
    )
    assert keyboard_reorder_insert_message(2, 5, 5) == (
        "Press Enter to insert the selected commits after commit 5 or Escape to cancel."
    )


def test_enable_commit_message_generation_requires_flag_and_entitlement() -> None:
    from github_desktop.models import Account, enable_commit_message_generation

    none = Account(login="hubot", endpoint="https://api.github.com", token="t")
    assert enable_commit_message_generation(none) is False
    assert enable_commit_message_generation(None) is False
    flagged = Account(
        login="hubot",
        endpoint="https://api.github.com",
        token="t",
        features=["desktop_copilot_generate_commit_message"],
        is_copilot_desktop_enabled=False,
    )
    assert enable_commit_message_generation(flagged) is False
    entitled = Account(
        login="hubot",
        endpoint="https://api.github.com",
        token="t",
        features=["desktop_copilot_generate_commit_message"],
        is_copilot_desktop_enabled=True,
    )
    assert enable_commit_message_generation(entitled) is True


def test_push_protection_bypass_uses_secret_scanning_path() -> None:
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_post(path, body=None, **kwargs):
        seen.append(path)
        return {"id": 1}

    api.post = fake_post  # type: ignore[method-assign]
    api.create_push_protection_bypass("desktop", "desktop", "false_positive", "ph")
    assert seen == ["/repos/desktop/desktop/secret-scanning/push-protection-bypasses"]
