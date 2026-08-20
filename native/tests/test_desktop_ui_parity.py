"""Notification classification, avatars, changelog, missing-repo store helpers."""

from __future__ import annotations

from github_desktop.avatars import avatar_urls, initials_for, login_from_email
from github_desktop.changelog import CURRENT_NOTES, load_release_notes
from github_desktop.git.expansion import copy_text_diff
from github_desktop.git.ops import get_repository_kind
from github_desktop.github.notifications import classify_notification
from github_desktop.models import PopupType, TextDiff, parse_co_authors
from github_desktop.store import AppStore
from tests.conftest import run_git


def test_login_from_noreply_email() -> None:
    assert login_from_email("42+octocat@users.noreply.github.com") == "octocat"
    assert login_from_email("octocat@users.noreply.github.com") == "octocat"
    assert login_from_email("person@example.com") is None


def test_initials_and_avatar_urls() -> None:
    assert initials_for("Jane Doe") == "JD"
    urls = avatar_urls(email="jane@example.com", login="jane", size=32)
    assert any("avatars.githubusercontent.com/jane" in u for u in urls)
    assert any("email=jane%40example.com" in u or "email=jane@example.com" in u for u in urls)


def test_classify_review_notification() -> None:
    note = {
        "id": "1",
        "subject": {"title": "Fix login", "type": "PullRequest", "url": "https://api.github.com/repos/o/r/pulls/3"},
        "repository": {"full_name": "o/r"},
    }
    payload = {
        "state": "CHANGES_REQUESTED",
        "body": "Please update tests",
        "html_url": "https://github.com/o/r/pull/3#pullrequestreview-1",
        "submitted_at": "2026-01-01T00:00:00Z",
        "user": {"login": "reviewer"},
        "number": 3,
        "title": "Fix login",
    }
    action = classify_notification(note, payload)
    assert action.popup == PopupType.PULL_REQUEST_REVIEW
    assert action.payload["review"]["state"] == "CHANGES_REQUESTED"
    assert "reviewer" in action.body


def test_classify_checks_failed() -> None:
    note = {
        "id": "2",
        "subject": {"title": "CI", "type": "CheckSuite"},
        "repository": {"full_name": "o/r"},
    }
    action = classify_notification(note, None)
    assert action.popup == PopupType.PULL_REQUEST_CHECKS_FAILED


def test_classify_pr_comment() -> None:
    note = {
        "id": "3",
        "subject": {"title": "Fix login", "type": "PullRequest"},
        "repository": {"full_name": "o/r"},
    }
    payload = {
        "body": "Looks good",
        "html_url": "https://github.com/o/r/pull/3#issuecomment-1",
        "created_at": "2026-01-01T00:00:00Z",
        "user": {"login": "friend"},
    }
    action = classify_notification(note, payload)
    assert action.popup == PopupType.PULL_REQUEST_COMMENT


def test_load_release_notes_current_version() -> None:
    version, notes = load_release_notes("3.5.4")
    assert version == "3.5.4"
    assert notes
    assert any("LFS" in line or "whitespace" in line.lower() or line in CURRENT_NOTES for line in notes)


def test_copy_text_diff_keeps_syntax_maps() -> None:
    diff = TextDiff(text="x", old_line_markup={1: "old"}, new_line_markup={1: "new"})
    copied = copy_text_diff(diff)
    assert copied.old_line_markup == {1: "old"}
    assert copied.new_line_markup == {1: "new"}
    copied.old_line_markup[2] = "mut"
    assert 2 not in diff.old_line_markup


def test_get_repository_kind(git_repo, tmp_path) -> None:
    assert get_repository_kind(str(git_repo)) == "regular"
    assert get_repository_kind(str(tmp_path / "missing")) == "missing"


def test_parse_co_authors_handles_handles_and_emails() -> None:
    authors = parse_co_authors("@octocat, Jane Doe <jane@example.com>\nNameless")
    assert authors[0].username == "octocat"
    assert authors[0].email.endswith("users.noreply.github.com")
    assert authors[1].email == "jane@example.com"
    assert authors[2].unknown is True


def test_relocate_repository(isolated_config, git_repo, tmp_path) -> None:
    other = tmp_path / "relocated"
    other.mkdir()
    run_git(other, "init")
    run_git(other, "config", "user.email", "dev@example.com")
    run_git(other, "config", "user.name", "Dev")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    store.relocate_repository(repo, str(other))
    assert repo.path == str(other)
    assert not repo.is_missing


def test_start_and_stop_amending(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    from github_desktop.git.ops import get_commits, get_status

    state = store.state_for(repo)
    state.status = get_status(str(git_repo))
    state.commits = get_commits(str(git_repo), limit=5)
    state.local_commit_shas = [state.commits[0].sha]
    store.start_amending(repo)
    assert state.commit_to_amend is not None
    assert state.commit_to_amend.sha == state.commits[0].sha
    store.stop_amending(repo)
    assert state.commit_to_amend is None
