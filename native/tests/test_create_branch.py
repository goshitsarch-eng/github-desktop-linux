"""Desktop create-branch start points and `git branch --no-track`."""

from __future__ import annotations

from pathlib import Path

from github_desktop.create_branch import get_start_point, upstream_default_branch_for
from github_desktop.git.ops import create_branch, get_config_value
from github_desktop.models import (
    Account,
    Branch,
    BranchType,
    ForkContributionTarget,
    GitHubRepository,
    Repository,
    StartPoint,
    TipState,
)
from tests.conftest import run_git


def _branch(name: str, *, remote: str | None = None, btype: BranchType = BranchType.LOCAL) -> Branch:
    full = name if remote is None else f"{remote}/{name}"
    return Branch(
        name=full,
        upstream=None,
        tip_sha="abc1234",
        type=btype,
        remote=remote,
        ref=f"refs/heads/{name}" if btype == BranchType.LOCAL else f"refs/remotes/{remote}/{name}",
    )


def test_get_start_point_prefers_upstream_then_default_then_current() -> None:
    default = _branch("main")
    upstream = _branch("main", remote="upstream", btype=BranchType.REMOTE)
    assert get_start_point(
        tip_kind=TipState.VALID,
        default_branch=default,
        upstream_default_branch=upstream,
    ) == StartPoint.UPSTREAM_DEFAULT_BRANCH
    assert get_start_point(
        tip_kind=TipState.VALID,
        default_branch=default,
        upstream_default_branch=None,
    ) == StartPoint.DEFAULT_BRANCH
    assert get_start_point(
        tip_kind=TipState.VALID,
        default_branch=None,
        upstream_default_branch=None,
    ) == StartPoint.CURRENT_BRANCH
    assert get_start_point(
        tip_kind=TipState.DETACHED,
        default_branch=default,
        upstream_default_branch=upstream,
    ) == StartPoint.HEAD
    assert get_start_point(
        tip_kind=TipState.UNBORN,
        default_branch=None,
        upstream_default_branch=None,
        preferred=StartPoint.CURRENT_BRANCH,
    ) == StartPoint.HEAD


def test_upstream_default_branch_for_fork_parent() -> None:
    parent = GitHubRepository(
        name="desktop",
        owner="desktop",
        html_url="https://github.com/desktop/desktop",
        clone_url="https://github.com/desktop/desktop.git",
        default_branch="main",
    )
    fork = GitHubRepository(
        name="desktop",
        owner="me",
        html_url="https://github.com/me/desktop",
        clone_url="https://github.com/me/desktop.git",
        fork=True,
        parent=parent,
        default_branch="main",
    )
    repo = Repository(id=1, path="/tmp/desktop", name="desktop", github=fork)
    repo.workflow_preferences = {"fork_target": ForkContributionTarget.PARENT.value}
    upstream = _branch("main", remote="upstream", btype=BranchType.REMOTE)
    found = upstream_default_branch_for(repo, [upstream], "main")
    assert found is not None
    assert found.name == "upstream/main"


def test_create_branch_no_track_skips_upstream(git_repo: Path, monkeypatch) -> None:
    run_git(git_repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    create_branch(str(git_repo), "from-origin", "origin/main", no_track=True)
    assert get_config_value(str(git_repo), "branch.from-origin.merge") is None
    seen: dict[str, list[str]] = {}

    def fake_git(args, repo, **kwargs):  # type: ignore[no-untyped-def]
        seen["args"] = list(args)

        class Result:
            stdout = ""
            exit_code = 0

        return Result()

    monkeypatch.setattr("github_desktop.git.ops.git", fake_git)
    create_branch(str(git_repo), "topic", "origin/main", no_track=True)
    assert seen["args"] == ["branch", "topic", "origin/main", "--no-track"]
    create_branch(str(git_repo), "topic", "origin/main")
    assert seen["args"] == ["branch", "topic", "origin/main"]


def test_git_email_not_found_warning_copy() -> None:
    from github_desktop.email import (
        GIT_EMAIL_NOT_FOUND_WARNING_FOR_SCREEN_READERS,
        buildScreenReaderMessage,
        git_email_attribution_warning,
        git_email_not_found_warning_aria_live,
    )

    github = Account(login="octocat", endpoint="https://api.github.com", token="x", emails=["octocat@github.com"], id=1)
    msg, mismatch = git_email_attribution_warning([github], "other@example.com")
    assert mismatch is True
    assert msg is not None
    assert "Your commits will be wrongly attributed" in msg
    assert "does not match your GitHub account" in msg
    ok, ok_mismatch = git_email_attribution_warning([github], "octocat@github.com")
    assert ok_mismatch is False
    assert ok is not None and "matches your GitHub account" in ok
    hidden, _ = git_email_attribution_warning([], "x@y.com")
    assert hidden is None
    assert buildScreenReaderMessage is git_email_not_found_warning_aria_live
    assert git_email_not_found_warning_aria_live([github], "other@example.com") == (
        "This email address does not match your GitHub account. "
        "Your commits will be wrongly attributed. "
    )
    assert (
        git_email_not_found_warning_aria_live([github], "octocat@github.com")
        == "This email address matches your GitHub account. "
    )
    assert git_email_not_found_warning_aria_live([], "x@y.com") is None
    assert git_email_not_found_warning_aria_live([github], "  ") is None
    assert (
        GIT_EMAIL_NOT_FOUND_WARNING_FOR_SCREEN_READERS
        == "git-email-not-found-warning-for-screen-readers"
    )


def test_git_rebase_and_auth_env_helpers() -> None:
    from github_desktop.git.ops import (
        env_for_authentication,
        env_for_remote_operation,
        get_fallback_url_for_proxy_resolve,
        git_rebase_arguments,
    )

    assert git_rebase_arguments() == ["-c", "rebase.backend=merge"]
    env = env_for_authentication()
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    combined = env_for_remote_operation("https://github.com/desktop/desktop.git")
    assert combined["GIT_TERMINAL_PROMPT"] == "0"
    assert get_fallback_url_for_proxy_resolve(remote_url="https://example.com/repo.git") == "https://example.com/repo.git"
    assert get_fallback_url_for_proxy_resolve() == "https://github.com"
    assert get_fallback_url_for_proxy_resolve(github_endpoint="https://api.github.com") == "https://github.com"
    assert get_fallback_url_for_proxy_resolve(
        github_endpoint="https://ghe.example.com/api/v3",
        remote_url="https://ignored.example/repo.git",
    ) == "https://ghe.example.com"


def test_get_description_for_error_matches_desktop() -> None:
    from github_desktop.errors import (
        classify_git_error,
        get_description_for_error,
        is_auth_failure_error,
        parse_bad_config_value_error_info,
    )

    assert is_auth_failure_error("HTTPSAuthenticationFailed")
    assert not is_auth_failure_error("PushNotFastForward")
    auth = get_description_for_error("HTTPSAuthenticationFailed", "")
    assert auth is not None
    assert "Authentication failed. Some common reasons include" in auth
    assert "File > Options." in auth
    assert get_description_for_error("PushNotFastForward", "") == (
        "The repository has been updated since you last pulled. Try pulling before pushing."
    )
    assert get_description_for_error("ConfigLockFileAlreadyExists", "") is None
    assert classify_git_error("fatal: Authentication failed for 'https://github.com/x/y.git'") == "HTTPSAuthenticationFailed"
    assert classify_git_error("error: failed to push some refs to 'origin'") == "PushNotFastForward"
    info = parse_bad_config_value_error_info("fatal: bad config value 'foo' for 'core.pager'")
    assert info == ("core.pager", "foo")
    assert "Unsupported value 'foo'" in (get_description_for_error("BadConfigValue", "fatal: bad config value 'foo' for 'core.pager'") or "")
