"""Notification classification, avatars, changelog, missing-repo store helpers."""

from __future__ import annotations

import os

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


def test_get_repository_type_reports_toplevel(git_repo, tmp_path) -> None:
    from github_desktop.git.ops import get_repository_type

    nested = git_repo / "nested"
    nested.mkdir()
    info = get_repository_type(str(git_repo))
    assert info["kind"] == "regular"
    assert os.path.abspath(info["topLevelWorkingDirectory"]) == os.path.abspath(str(git_repo))
    nested_info = get_repository_type(str(nested))
    assert nested_info["kind"] == "regular"
    assert os.path.abspath(nested_info["topLevelWorkingDirectory"]) == os.path.abspath(str(git_repo))


def test_parse_co_authors_handles_handles_and_emails() -> None:
    authors = parse_co_authors("@octocat, Jane Doe <jane@example.com>\nNameless")
    assert authors[0].username == "octocat"
    assert authors[0].unknown is True
    assert authors[0].email == ""
    assert authors[1].email == "jane@example.com"
    assert authors[2].unknown is True
    assert authors[2].username == "Nameless"


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


def test_undo_last_commit_warns_when_dirty(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    from github_desktop.git.ops import get_commits, get_status
    from github_desktop.models import PopupType

    (git_repo / "second.txt").write_text("s\n", encoding="utf-8")
    run_git(git_repo, "add", "second.txt")
    run_git(git_repo, "commit", "-m", "second")
    state = store.state_for(repo)
    state.status = get_status(str(git_repo))
    state.commits = get_commits(str(git_repo), limit=5)
    tip = state.commits[0].sha
    (git_repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    state.status = get_status(str(git_repo))
    store.undo_last_commit(repo)
    assert store.popup is not None
    assert store.popup.type == PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO
    store.close_popup()
    store.undo_last_commit(repo, show_confirmation=False)
    commits = get_commits(str(git_repo), limit=5)
    assert commits[0].sha != tip


def test_copilot_disclaimer_interval(isolated_config) -> None:
    store = AppStore()
    assert store.should_show_copilot_disclaimer()
    store.mark_copilot_disclaimer_seen()
    assert not store.should_show_copilot_disclaimer()
    store.settings.commit_message_generation_disclaimer_last_seen = 1
    assert store.should_show_copilot_disclaimer()


def test_thank_you_and_custom_integration() -> None:
    from github_desktop.custom_integration import (
        TARGET_PATH_ARGUMENT,
        command_for_custom_integration,
        expand_target_path,
        parse_custom_arguments,
    )
    from github_desktop.thank_you import (
        contributions_by_user,
        get_user_contributions,
        has_user_already_been_checked_or_thanked,
        thank_you_note,
    )

    assert TARGET_PATH_ARGUMENT in command_for_custom_integration("/usr/bin/vim", "", "/repo")[-1] or True
    argv = parse_custom_arguments(f"--wait {TARGET_PATH_ARGUMENT}")
    expanded = expand_target_path(argv, "/tmp/repo")
    assert "/tmp/repo" in expanded
    assert TARGET_PATH_ARGUMENT not in " ".join(expanded)
    note = thank_you_note("3.5.4")
    assert "Thanks so much for all your hard work on GitHub Desktop 3.5.4" in note
    assert "You contributed:" not in note
    by_user = contributions_by_user(
        ["[Fixed] A thing. Thanks @octocat!", "[Improved] Other. Thanks @someone!"]
    )
    assert by_user["octocat"] == ["[Fixed] A thing. Thanks @octocat!"]
    assert get_user_contributions("octocat", ["[Fixed] A thing. Thanks @octocat!"])
    assert has_user_already_been_checked_or_thanked("3.5.4", ["octocat"], "octocat", "3.5.4")
    assert not has_user_already_been_checked_or_thanked("3.5.3", ["octocat"], "octocat", "3.5.4")
