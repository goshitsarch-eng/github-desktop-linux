"""Desktop gitignore formatting, calculateConflicts, contribution-target, and auth errors."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import AUTH_FAILURE_ERRORS, is_auth_failure_error
from github_desktop.find_default_branch import find_contribution_target_default_branch
from github_desktop.git.ops import (
    AUTHENTICATION_ERRORS,
    append_ignore_rule,
    env_for_authentication,
    format_gitignore_contents,
    get_current_upstream_ref,
    get_current_upstream_remote_name,
    read_gitignore,
    read_gitignore_at_root,
    save_gitignore,
)
from github_desktop.local_storage import set_item
from github_desktop.models import (
    Branch,
    BranchType,
    GitHubRepository,
    Repository,
    calculate_conflicts,
    is_repository_with_forked_github_repository,
    is_repository_with_github_repository,
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


def test_read_gitignore_at_root_missing_is_none(git_repo: Path) -> None:
    assert read_gitignore_at_root(str(git_repo)) is None
    assert read_gitignore(str(git_repo)) == ""


def test_format_gitignore_contents_matches_desktop_autocrlf(git_repo: Path, monkeypatch) -> None:
    from github_desktop.git import ops as git_ops

    def _config(_repo: str, key: str) -> str | None:
        values = {
            "core.autocrlf": None,
            "core.safecrlf": None,
        }
        return values.get(key)

    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: _config(repo, key))
    assert format_gitignore_contents("", str(git_repo)) == ""
    assert format_gitignore_contents("node_modules\n", str(git_repo)) == "node_modules\n"
    assert format_gitignore_contents("node_modules", str(git_repo)) == "node_modules\n"

    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: "true" if key == "core.autocrlf" else None)
    assert format_gitignore_contents("node_modules", str(git_repo)) == "node_modules\n"

    # Desktop's quirky else: any set autocrlf other than 'true' appends CRLF.
    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: "input" if key == "core.autocrlf" else None)
    assert format_gitignore_contents("node_modules", str(git_repo)) == "node_modules\r\n"
    assert format_gitignore_contents("node_modules\n", str(git_repo)) == "node_modules\n"

    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: "true")
    assert format_gitignore_contents("a\nb", str(git_repo)) == "a\r\nb\r\n"
    assert format_gitignore_contents("node_modules", str(git_repo)) == "node_modules\r\n"


def test_save_gitignore_empty_deletes_file(git_repo: Path) -> None:
    ignore = git_repo / ".gitignore"
    ignore.write_text("node_modules\n", encoding="utf-8")
    save_gitignore(str(git_repo), "")
    assert not ignore.exists()
    assert read_gitignore_at_root(str(git_repo)) is None
    save_gitignore(str(git_repo), "")  # missing file must not raise


def test_save_gitignore_autocrlf_true_safecrlf_true_appends_crlf(git_repo: Path) -> None:
    run_git(git_repo, "config", "core.autocrlf", "true")
    run_git(git_repo, "config", "core.safecrlf", "true")
    save_gitignore(str(git_repo), "node_modules")
    contents = read_gitignore_at_root(str(git_repo))
    assert contents is not None
    assert contents.endswith("\r\n")
    run_git(git_repo, "add", ".gitignore")
    run_git(git_repo, "commit", "-m", "create the ignore file")


def test_append_ignore_rule_with_autocrlf_true(git_repo: Path) -> None:
    run_git(git_repo, "config", "core.autocrlf", "true")
    run_git(git_repo, "config", "core.safecrlf", "false")
    (git_repo / ".gitignore").write_text("node_modules\n", encoding="utf-8")
    append_ignore_rule(str(git_repo), ["yarn-error.log", ".eslintcache", "dist/"])
    assert (git_repo / ".gitignore").read_text(encoding="utf-8") == (
        "node_modules\nyarn-error.log\n.eslintcache\ndist/\n"
    )


def test_calculate_conflicts_rounds_markers_up() -> None:
    assert calculate_conflicts(0) == 0
    assert calculate_conflicts(1) == 1
    assert calculate_conflicts(3) == 1
    assert calculate_conflicts(4) == 2
    assert calculate_conflicts(6) == 2


def test_find_contribution_target_default_branch() -> None:
    default = _branch("main")
    upstream = _branch("develop", remote="upstream", btype=BranchType.REMOTE)
    local = Repository(1, "/tmp/app", "app")
    assert not is_repository_with_github_repository(local)
    assert find_contribution_target_default_branch(local, default, upstream) is default

    parent = GitHubRepository(
        "app",
        "acme",
        "https://github.com/acme/app",
        "https://github.com/acme/app.git",
        default_branch="develop",
    )
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=parent,
        default_branch="main",
    )
    github_repo = Repository(2, "/tmp/app", "app", github=fork)
    assert is_repository_with_github_repository(github_repo)
    assert is_repository_with_forked_github_repository(github_repo)
    assert find_contribution_target_default_branch(github_repo, default, upstream) is upstream
    assert find_contribution_target_default_branch(github_repo, default, None) is default


def test_authentication_errors_distinct_from_auth_failure_errors() -> None:
    assert AUTHENTICATION_ERRORS == {
        "HTTPSAuthenticationFailed",
        "SSHAuthenticationFailed",
        "HTTPSRepositoryNotFound",
        "SSHRepositoryNotFound",
    }
    assert "SSHPermissionDenied" in AUTH_FAILURE_ERRORS
    assert "SSHPermissionDenied" not in AUTHENTICATION_ERRORS
    assert "HTTPSRepositoryNotFound" not in AUTH_FAILURE_ERRORS
    assert is_auth_failure_error("HTTPSAuthenticationFailed")
    assert not is_auth_failure_error("HTTPSRepositoryNotFound")


def test_env_for_authentication_reads_git_trace(isolated_config, monkeypatch) -> None:
    monkeypatch.delenv("GIT_TRACE", raising=False)
    assert env_for_authentication()["GIT_TRACE"] == "0"
    set_item("git-trace", "1")
    assert env_for_authentication()["GIT_TRACE"] == "1"
    monkeypatch.setenv("GIT_TRACE", "2")
    set_item("git-trace", "")
    # Empty localStorage falls through to the process environment, then "0".
    assert env_for_authentication()["GIT_TRACE"] == "2"


def test_get_current_upstream_ref_from_clone(git_repo: Path, tmp_path: Path) -> None:
    clone = tmp_path / "clone"
    run_git(tmp_path, "clone", str(git_repo), "clone")
    assert get_current_upstream_ref(str(clone)) == "refs/remotes/origin/main"
    assert get_current_upstream_remote_name(str(clone)) == "origin"
    assert get_current_upstream_ref(str(git_repo)) is None
    assert get_current_upstream_remote_name(str(git_repo)) is None
