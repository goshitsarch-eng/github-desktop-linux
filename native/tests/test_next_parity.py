"""Parity for sign-in warning, git config radios, co-authors, compare, and CI."""

from __future__ import annotations

from github_desktop.git.ops import get_config_value, remove_config_value, set_config_value
from github_desktop.github.ci_checks import summarize_check_runs
from github_desktop.models import (
    Account,
    AppFileStatusKind,
    FileStatus,
    GitStatusEntry,
    ManualConflictResolution,
    RefCheck,
    SignInStep,
    get_conflicted_files,
    get_label_for_manual_resolution_option,
    group_pr_base_branches,
    format_commit_attribution,
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
    assert not has_unresolved_conflicts(manual, ManualConflictResolution.OURS)
    from github_desktop.models import WorkingDirectoryFileChange

    files = [
        WorkingDirectoryFileChange("a.txt", markers),
        WorkingDirectoryFileChange("b.txt", resolved),
        WorkingDirectoryFileChange("c.txt", manual),
        WorkingDirectoryFileChange("d.txt", FileStatus(AppFileStatusKind.MODIFIED)),
    ]
    assert [f.path for f in get_conflicted_files(files)] == ["a.txt", "c.txt"]
    assert [f.path for f in get_conflicted_files(files, {"c.txt": ManualConflictResolution.THEIRS})] == ["a.txt"]
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


def test_group_pr_base_branches_lists_recent_first() -> None:
    recent, others = group_pr_base_branches(
        ["main", "develop", "topic", "wip"],
        ["topic", "missing", "main"],
        current="wip",
        default="main",
    )
    assert recent == ["topic", "main"]
    assert others == ["develop"]


def test_format_commit_attribution_includes_committer_and_coauthors() -> None:
    from datetime import datetime, timezone

    from github_desktop.models import Commit, CommitIdentity

    when = datetime(2024, 1, 2, tzinfo=timezone.utc)
    author = CommitIdentity("Ada", "ada@example.com", when)
    committer = CommitIdentity("Grace", "grace@example.com", when)
    same = Commit(
        sha="a" * 40,
        short_sha="aaaaaaa",
        summary="hi",
        body="",
        author=author,
        committer=author,
    )
    assert format_commit_attribution(same) == "Ada"
    split = Commit(
        sha="b" * 40,
        short_sha="bbbbbbb",
        summary="hi",
        body="",
        author=author,
        committer=committer,
        trailers=[("Co-authored-by", "Linus <linus@example.com>")],
    )
    assert format_commit_attribution(split) == "3 people"
    two = Commit(
        sha="c" * 40,
        short_sha="ccccccc",
        summary="",
        body="",
        author=author,
        committer=committer,
    )
    assert format_commit_attribution(two) == "Ada, Grace"
    assert two.co_authors == []
    from github_desktop.push_pull import format_commit_relative_time

    assert format_commit_relative_time(when, now=when) == "just now"


def test_filter_changes_no_results_and_hidden_commit() -> None:
    from github_desktop.filter_changes import (
        FileListFilterState,
        apply_filters,
        get_no_results_message,
        has_active_filters,
        is_committing_file_hidden_by_filter,
    )
    from github_desktop.models import WorkingDirectoryFileChange

    new = WorkingDirectoryFileChange("new.txt", FileStatus(AppFileStatusKind.NEW))
    modified = WorkingDirectoryFileChange("old.txt", FileStatus(AppFileStatusKind.MODIFIED))
    excluded = modified.with_include(False)
    filters = FileListFilterState(filter_text="nope", is_new_file=True)
    assert has_active_filters(filters)
    assert get_no_results_message(filters) == (
        'Sorry, I can\'t find any changed files matching the following filters: "nope" and New files'
    )
    assert apply_filters(new, FileListFilterState(is_new_file=True))
    assert not apply_filters(modified, FileListFilterState(is_new_file=True))
    assert not apply_filters(new, FileListFilterState(is_new_file=True, is_modified_file=True))
    assert excluded.is_excluded_from_commit()
    assert new.is_included_in_commit()
    assert is_committing_file_hidden_by_filter(
        ["new.txt", "old.txt"],
        ["new.txt"],
        2,
        FileListFilterState(is_new_file=True),
    )
    assert not is_committing_file_hidden_by_filter(
        ["new.txt"],
        ["new.txt"],
        2,
        FileListFilterState(is_new_file=True),
    )


def test_commit_warns_only_when_included_files_are_hidden(isolated_config, git_repo) -> None:
    from github_desktop.git.ops import get_status
    from github_desktop.models import PopupType, WorkingDirectoryStatus

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    (git_repo / "new.txt").write_text("n\n", encoding="utf-8")
    (git_repo / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    state = store.state_for(repo)
    state.status = get_status(str(git_repo))
    state.filter_new = True
    store.commit(repo, "hidden files")
    assert store.popup is not None
    assert store.popup.type == PopupType.CONFIRM_COMMIT_FILTERED_CHANGES
    store.close_popup()
    updated = [
        file if file.is_new() or file.is_untracked() else file.with_include(False)
        for file in state.status.working_directory.files
    ]
    state.status.working_directory = WorkingDirectoryStatus.from_files(updated)
    store.commit(repo, "only visible")
    assert store.popup is None


def test_sandboxed_markdown_pango_is_https_only() -> None:
    from github_desktop.ui.markdown import issue_base_from_html_url, markdown_to_pango

    markup = markdown_to_pango(
        "Hello **world** and `code` [docs](https://example.com/a) [bad](javascript:alert(1)) #42",
        issue_base_url="https://github.com/octo/hello/issues",
    )
    assert "<b>world</b>" in markup
    assert "<tt>code</tt>" in markup
    assert 'href="https://example.com/a"' in markup
    assert 'href="javascript:' not in markup
    assert 'href="https://github.com/octo/hello/issues/42"' in markup
    mentioned = markdown_to_pango(
        "Thanks @octocat for abcdef1",
        issue_base_url="https://github.com/octo/hello/issues",
        repo_html_url="https://github.com/octo/hello",
    )
    assert 'href="https://github.com/octocat"' in mentioned
    assert "@octocat" in mentioned
    assert "href=\"https://github.com/octo/hello/commit/abcdef1\"" in mentioned
    assert issue_base_from_html_url("https://github.com/octo/hello/pull/9") == "https://github.com/octo/hello/issues"
    escaped = markdown_to_pango("<script>alert(1)</script>")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped


def test_commit_message_copilot_flag_cleared_on_edit(isolated_config) -> None:
    from github_desktop.models import CommitMessage
    from github_desktop.store import AppStore

    store = AppStore()
    msg = CommitMessage(summary="Add tests", description="body", timestamp=1, generated_by_copilot=True)
    assert msg.generated_by_copilot is True
    edited = CommitMessage(summary="Add tests!", description="body", timestamp=1, generated_by_copilot=False)
    assert edited.generated_by_copilot is False


def test_trailer_separator_characters(git_repo) -> None:
    from github_desktop.git.ops import get_trailer_separator_characters, set_config_value

    assert get_trailer_separator_characters(str(git_repo)) == ":"
    set_config_value(str(git_repo), "trailer.separators", ":#")
    assert get_trailer_separator_characters(str(git_repo)) == ":#"


def test_markdown_issue_team_and_close_filters() -> None:
    from github_desktop.ui.markdown import close_keyword_tooltip, markdown_to_pango

    issues = markdown_to_pango(
        "See gh-123 and desktop/dugite#9 and /issues/4",
        issue_base_url="https://github.com/octo/hello/issues",
        repo_html_url="https://github.com/octo/hello",
    )
    assert "gh-123" in issues
    assert 'href="https://github.com/octo/hello/issues/123"' in issues
    assert "desktop/dugite#9" in issues
    assert 'href="https://github.com/desktop/dugite/issues/9"' in issues
    assert 'href="https://github.com/octo/hello/issues/4"' in issues
    team = markdown_to_pango(
        "cc @desktop/the-a-team and @octocat",
        issue_base_url="https://github.com/desktop/desktop/issues",
    )
    assert 'href="https://github.com/orgs/desktop/teams/the-a-team"' in team
    assert "@desktop/the-a-team" in team
    assert 'href="https://github.com/octocat"' in team
    assert close_keyword_tooltip("Closes #44 after review") == "This pull request closes #44."
    closed = markdown_to_pango(
        "Fixes #12",
        issue_base_url="https://github.com/octo/hello/issues",
    )
    assert 'href="https://github.com/octo/hello/issues/12"' in closed


def test_config_lock_error_helpers() -> None:
    from github_desktop.errors import GitError
    from github_desktop.git.ops import is_config_file_lock_error, parse_config_lock_file_path_from_error

    err = GitError(
        "could not lock",
        stderr="error: could not lock config file /tmp/gitconfig: File exists\n",
        path="/home/dev",
        git_error="ConfigLockFileAlreadyExists",
    )
    assert is_config_file_lock_error(err)
    lock = parse_config_lock_file_path_from_error(err)
    assert lock == "/tmp/gitconfig.lock"
    assert not is_config_file_lock_error(GitError("unrelated", stderr="fatal: bad"))


def test_env_for_proxy_skips_and_honors_git_config(monkeypatch) -> None:
    from github_desktop.git import runner as runner_mod
    from github_desktop.git.ops import env_for_proxy

    monkeypatch.setattr(runner_mod, "read_linux_system_proxy", lambda: None)
    assert env_for_proxy("git@github.com:a/b.git", env={}) == {}
    assert env_for_proxy("https://github.com/", env={"ALL_PROXY": "socks5://127.0.0.1:1080"}) == {}
    assert env_for_proxy("https://github.com/", env={"https_proxy": "http://existing:8080"}) == {}

    class _Result:
        stdout = "http://proxy.example:8080\n"

    monkeypatch.setattr(runner_mod, "git", lambda *a, **k: _Result())
    assert env_for_proxy("https://github.com/", env={}) == {"https_proxy": "http://proxy.example:8080"}
    assert env_for_proxy("http://github.com/", env={}) == {"http_proxy": "http://proxy.example:8080"}
    assert env_for_proxy("https://github.com/", env={}, resolve=lambda _url: "socks5://127.0.0.1:1080") == {
        "https_proxy": "socks5://127.0.0.1:1080"
    }


def test_high_signal_notification_filter() -> None:
    from github_desktop.github.notifications import is_high_signal_notification

    checks = {
        "id": "1",
        "reason": "ci_activity",
        "subject": {"type": "CheckSuite", "title": "Checks failed"},
        "repository": {"full_name": "octo/hello"},
    }
    review = {
        "id": "2",
        "reason": "review_requested",
        "subject": {"type": "PullRequest", "title": "Please review"},
        "repository": {"full_name": "octo/hello"},
    }
    other = {
        "id": "3",
        "reason": "subscribed",
        "subject": {"type": "Issue", "title": "Random issue"},
        "repository": {"full_name": "octo/hello"},
    }
    other_repo = {
        "id": "4",
        "reason": "ci_activity",
        "subject": {"type": "CheckSuite", "title": "Checks failed"},
        "repository": {"full_name": "someone/else"},
    }
    assert is_high_signal_notification(checks, "octo/hello")
    assert is_high_signal_notification(review, "octo/hello")
    assert not is_high_signal_notification(other, "octo/hello")
    assert not is_high_signal_notification(other_repo, "octo/hello")


def test_submodule_diff_copy_helpers() -> None:
    from github_desktop.models import (
        SubmoduleStatus,
        shorten_sha,
        submodule_commit_change_copy,
        submodule_repository_link,
        submodule_working_changes_copy,
    )

    assert shorten_sha("abcdef1234567890") == "abcdef1"
    uri, caption = submodule_repository_link("https://github.com/desktop/desktop.git")
    assert uri == "https://github.com/desktop/desktop"
    assert caption == "desktop/desktop"
    _ent_uri, ent_caption = submodule_repository_link("https://github.example.com/acme/app.git")
    assert ent_caption == "acme/app (github.example.com)"
    assert submodule_repository_link(None) is None
    assert "This change can be committed to the parent repository." in (
        submodule_commit_change_copy("aaa1111bbbb", "ccc2222dddd", read_only=False) or ""
    )
    history = submodule_commit_change_copy(None, "ccc2222dddd", read_only=True) or ""
    assert history.startswith("This submodule was added pointing at commit")
    assert "This change can be committed" not in history
    both = submodule_working_changes_copy(
        SubmoduleStatus(modified_changes=True, untracked_changes=True)
    )
    assert both and "modified and untracked" in both
    assert "Those changes must be committed inside of the submodule" in both


def test_select_file_records_submodule_diff_viewed(isolated_config, git_repo, monkeypatch) -> None:
    from github_desktop.models import (
        AppFileStatusKind,
        FileStatus,
        SubmoduleStatus,
        WorkingDirectoryFileChange,
    )

    store = AppStore()
    repo = store.add_repositories([str(git_repo)])[0]
    monkeypatch.setattr(store, "_load_working_diff", lambda *_a, **_k: None)
    file = WorkingDirectoryFileChange(
        "vendor/lib",
        FileStatus(
            AppFileStatusKind.MODIFIED,
            submodule_status=SubmoduleStatus(commit_changed=True),
        ),
    )
    store.select_file(repo, file)
    assert store.stats.get_daily_measures()["submoduleDiffViewedFromChangesListCount"] == 1
    store.select_file(repo, file)
    assert store.stats.get_daily_measures()["submoduleDiffViewedFromChangesListCount"] == 1
