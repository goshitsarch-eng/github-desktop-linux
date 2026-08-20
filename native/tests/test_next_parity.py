"""Parity for sign-in warning, git config radios, co-authors, compare, and CI."""

from __future__ import annotations

from github_desktop.git.ops import get_config_value, remove_config_value, set_config_value
from github_desktop.github.ci_checks import summarize_check_runs
from github_desktop.models import (
    Account,
    AppFileStatusKind,
    FileStatus,
    GitStatusEntry,
    RefCheck,
    SignInStep,
    get_label_for_manual_resolution_option,
    has_unresolved_conflicts,
    is_conflict_with_markers,
    is_manual_conflict,
    stealth_email_for_account,
    account_email_choices,
)
from github_desktop.store import AppStore
from tests.conftest import run_git


def test_stealth_email_and_account_choices() -> None:
    account = Account(login="octocat", endpoint="https://api.github.com", token="x", id=42, emails=["octocat@github.com"])
    assert stealth_email_for_account(account) == "42+octocat@users.noreply.github.com"
    choices = account_email_choices(account)
    assert "octocat@github.com" in choices
    assert "42+octocat@users.noreply.github.com" in choices


def test_begin_sign_in_existing_account_warning(isolated_config) -> None:
    store = AppStore()
    store.accounts = [
        Account(login="octocat", endpoint="https://api.github.com", token="x", id=1),
    ]
    store.begin_sign_in(False)
    assert store.sign_in_step == SignInStep.EXISTING_ACCOUNT_WARNING
    assert store.sign_in_existing is not None
    assert store.sign_in_existing.login == "octocat"
    store.continue_existing_account_warning()
    assert store.sign_in_step == SignInStep.AUTHENTICATION


def test_begin_sign_in_without_existing_goes_to_auth(isolated_config) -> None:
    store = AppStore()
    store.begin_sign_in(False)
    assert store.sign_in_step == SignInStep.AUTHENTICATION
    store.begin_sign_in(True)
    assert store.sign_in_step == SignInStep.ENDPOINT_ENTRY


def test_get_config_value_local_only(git_repo) -> None:
    path = git_repo.as_posix()
    assert get_config_value(path, "user.name", local_only=True) == "Test User"
    remove_config_value(path, "user.name")
    remove_config_value(path, "user.email")
    assert get_config_value(path, "user.name", local_only=True) is None
    set_config_value(path, "user.name", "Local Dev")
    assert get_config_value(path, "user.name", local_only=True) == "Local Dev"


def test_ahead_behind_between_cache(isolated_config, git_repo) -> None:
    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "topic.txt").write_text("topic\n", encoding="utf-8")
    run_git(git_repo, "add", "topic.txt")
    run_git(git_repo, "commit", "-m", "topic")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    main_sha = run_git(git_repo, "rev-parse", "main").stdout.strip()
    topic_sha = run_git(git_repo, "rev-parse", "topic").stdout.strip()
    ab = store.ahead_behind_between(repo, main_sha, topic_sha)
    assert ab is not None
    assert ab.ahead == 0
    assert ab.behind == 1
    cached = store.ahead_behind_between(repo, main_sha, topic_sha)
    assert cached is ab


def test_conflict_helpers_and_labels() -> None:
    markers = FileStatus(AppFileStatusKind.CONFLICTED, conflict_marker_count=2)
    resolved = FileStatus(AppFileStatusKind.CONFLICTED, conflict_marker_count=0)
    manual = FileStatus(
        AppFileStatusKind.CONFLICTED,
        conflict_marker_count=None,
        us=GitStatusEntry.ADDED,
        them=GitStatusEntry.DELETED,
    )
    assert is_conflict_with_markers(markers)
    assert has_unresolved_conflicts(markers)
    assert not has_unresolved_conflicts(resolved)
    assert is_manual_conflict(manual)
    assert has_unresolved_conflicts(manual)
    assert get_label_for_manual_resolution_option(GitStatusEntry.ADDED, "main") == "Use the added file from main"
    assert get_label_for_manual_resolution_option(GitStatusEntry.DELETED, "topic") == "Do not include this file on topic"
    assert get_label_for_manual_resolution_option(GitStatusEntry.UPDATED_BUT_UNMERGED, "main") == "Use the modified file from main"


def test_summarize_check_runs() -> None:
    assert summarize_check_runs([]) == ""
    pending = RefCheck(id=1, name="ci", description="", status="in_progress", conclusion=None)
    ok = RefCheck(id=2, name="ci", description="", status="completed", conclusion="success")
    fail = RefCheck(id=3, name="ci", description="", status="completed", conclusion="failure")
    assert summarize_check_runs([pending]) == "pending"
    assert summarize_check_runs([ok]) == "success"
    assert summarize_check_runs([ok, fail]) == "failure"


def test_poll_commit_status_skips_without_github(isolated_config, git_repo) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    store.poll_commit_status()
    repo = store.selected_repository
    assert repo is not None
    assert store.state_for(repo).check_runs == []
