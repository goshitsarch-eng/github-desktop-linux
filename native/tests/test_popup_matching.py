"""Desktop PopupManager, truncateWithEllipsis, large files, matching, last-push."""

from __future__ import annotations

from github_desktop.github.notifications import (
    classify_notification,
    is_valid_notification_pull_request_review,
)
from github_desktop.infer_last_push import infer_last_push_for_repository
from github_desktop.large_files import RECEIVE_LIMIT, get_large_file_paths
from github_desktop.models import (
    Account,
    AppFileStatusKind,
    DiffSelection,
    DiffSelectionType,
    FileStatus,
    GitHubRepository,
    PopupType,
    Remote,
    Repository,
    WorkingDirectoryFileChange,
)
from github_desktop.popup_manager import PopupManager
from github_desktop.remote_parsing import (
    match_existing_repository,
    match_github_repository,
    parse_repository_identifier,
    repository_matches_remote,
    url_matches_clone_url,
    urls_match,
)
from github_desktop.store import AppStore
from github_desktop.truncate import truncate_with_ellipsis


def test_truncate_with_ellipsis_matches_desktop() -> None:
    assert truncate_with_ellipsis("short", 25) == "short"
    s = "this-is-max-length-string"
    assert truncate_with_ellipsis(s, len(s)) == s
    assert truncate_with_ellipsis("this-string-exceeds-max-length", 25) == "this-string-exceeds-max-l…"
    moons = "🌝🌛🌜🌚🌕🌖🌗🌘🌑🌒🌓🌔☀\uFE0F"
    assert truncate_with_ellipsis(moons, 25) == moons
    long_moons = "🌝🌛🌜🌚🌕🌖🌗🌘🌑🌒🌓🌔☀\uFE0F🌤⛅\uFE0F🌥☁\uFE0F🌦🌧⛈🌩🌨"
    assert truncate_with_ellipsis(long_moons, 22) == long_moons
    assert truncate_with_ellipsis(long_moons, 13) == "🌝🌛🌜🌚🌕🌖🌗🌘🌑🌒🌓🌔☀\uFE0F…"


def test_popup_manager_errors_stay_on_top(isolated_config) -> None:
    store = AppStore()
    store.show_popup(PopupType.PREFERENCES)
    store.show_popup(PopupType.ERROR, error="boom")
    assert store.popup is not None and store.popup.type == PopupType.ERROR
    assert [item.type for item in store.all_popups] == [PopupType.PREFERENCES, PopupType.ERROR]
    store.show_popup(PopupType.ABOUT)
    assert store.popup is not None and store.popup.type == PopupType.ERROR
    assert [item.type for item in store.all_popups] == [
        PopupType.PREFERENCES,
        PopupType.ABOUT,
        PopupType.ERROR,
    ]
    store.show_popup(PopupType.PREFERENCES)
    assert [item.type for item in store.all_popups].count(PopupType.PREFERENCES) == 1
    store.close_popup()
    assert store.popup is not None and store.popup.type == PopupType.ABOUT


def test_popup_manager_drops_oldest_at_limit() -> None:
    manager = PopupManager(popup_limit=3)
    from github_desktop.models import Popup

    manager.add_popup(Popup(PopupType.ERROR, {"error": "1"}))
    manager.add_popup(Popup(PopupType.ERROR, {"error": "2"}))
    manager.add_popup(Popup(PopupType.ERROR, {"error": "3"}))
    manager.add_popup(Popup(PopupType.ERROR, {"error": "4"}))
    assert [p.payload["error"] for p in manager.all_popups] == ["2", "3", "4"]


def test_get_large_file_paths(tmp_path) -> None:
    big = tmp_path / "big.bin"
    small = tmp_path / "small.bin"
    big.write_bytes(b"x" * 20)
    small.write_bytes(b"y" * 5)
    included = WorkingDirectoryFileChange("big.bin", FileStatus(kind=AppFileStatusKind.NEW))
    skipped = WorkingDirectoryFileChange(
        "small.bin",
        FileStatus(kind=AppFileStatusKind.NEW),
        selection=DiffSelection.from_initial_selection(DiffSelectionType.NONE),
    )
    assert get_large_file_paths(str(tmp_path), [included, skipped], limit=10) == ["big.bin"]
    assert RECEIVE_LIMIT == 100 * 1024 * 1024
    assert get_large_file_paths(str(tmp_path), [included], limit=20) == []


def test_urls_match_and_repository_matching() -> None:
    assert urls_match("https://github.com/o/r.git", "git@github.com:o/r.git")
    ident = parse_repository_identifier("octocat/Hello-World")
    assert ident is not None
    assert ident.owner == "octocat" and ident.name == "Hello-World" and ident.hostname is None
    assert parse_repository_identifier("https://github.com/octocat/Hello-World.git") is not None
    gh = GitHubRepository(
        name="r",
        owner="o",
        html_url="https://github.com/o/r",
        clone_url="https://github.com/o/r.git",
    )
    assert url_matches_clone_url("https://github.com/o/r.git", gh)
    remote = Remote(name="origin", url="https://github.com/o/r.git")
    assert repository_matches_remote(gh, remote)
    account = Account(login="me", endpoint="https://api.github.com", token="x")
    matched = match_github_repository([account], "https://github.com/desktop/desktop.git")
    assert matched is not None
    assert matched.owner == "desktop" and matched.name == "desktop"
    repo = Repository(id=1, path="/tmp/foo", name="foo")
    assert match_existing_repository([repo], "/tmp/foo") is repo
    assert match_existing_repository([repo], "/tmp/bar") is None


def test_is_valid_notification_pull_request_review() -> None:
    assert is_valid_notification_pull_request_review({"state": "APPROVED"})
    assert is_valid_notification_pull_request_review("CHANGES_REQUESTED")
    assert is_valid_notification_pull_request_review("COMMENTED")
    assert not is_valid_notification_pull_request_review("DISMISSED")
    note = {
        "subject": {"title": "Fix", "type": "PullRequest"},
        "repository": {"full_name": "o/r"},
    }
    dismissed = classify_notification(note, {"state": "DISMISSED", "submitted_at": "2026-01-01T00:00:00Z", "user": {"login": "x"}})
    assert dismissed.popup is None


def test_infer_last_push_uses_api() -> None:
    account = Account(login="me", endpoint="https://api.github.com", token="tok")
    repo = Repository(
        id=1,
        path="/tmp/r",
        name="r",
        github=GitHubRepository(name="r", owner="o", html_url="https://github.com/o/r", clone_url="https://github.com/o/r.git"),
    )
    seen: list[str] = []

    class FakeAPI:
        def __init__(self, *a, **k):
            pass

        @classmethod
        def from_account(cls, account):
            return cls()

        def get(self, path, **kwargs):
            seen.append(path)
            return {"pushed_at": "2026-08-01T00:00:00Z"}

    import github_desktop.infer_last_push as mod

    original = mod.GitHubAPI
    mod.GitHubAPI = FakeAPI  # type: ignore[misc]
    try:
        stamp = infer_last_push_for_repository([account], repo, "https://github.com/o/r.git")
    finally:
        mod.GitHubAPI = original  # type: ignore[misc]
    assert stamp is not None
    assert seen == ["/repos/o/r"]
