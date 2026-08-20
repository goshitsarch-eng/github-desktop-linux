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
