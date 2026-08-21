"""Desktop `git/core` expectedErrors / successExitCodes handling."""

from __future__ import annotations

from pathlib import Path
from shutil import copy

import pytest

from github_desktop.errors import GitError, classify_git_error
from github_desktop.git.ops import (
    get_ahead_behind_range,
    get_branches,
    get_commit_range_changed_files,
    get_commits,
    get_commits_in_range,
    get_partial_blob_contents_catch_path_not_in_ref,
    get_remotes,
    parse_config_lock_file_path_from_error,
)
from github_desktop.git.runner import GitResult, git, is_git_error
from tests.conftest import run_git

_REV_LIST_MISSING = ["rev-list", "--left-right", "--count", "some-ref", "--"]


def test_classify_bad_revision() -> None:
    assert classify_git_error("fatal: bad revision 'x'") == "BadRevision"
    assert classify_git_error("fatal: not a git repository (or any of the parent directories): .git") == (
        "NotAGitRepository"
    )
    assert (
        classify_git_error("error: unable to delete 'refs/heads/gone': remote ref does not exist")
        == "BranchDeletionFailed"
    )
    assert (
        classify_git_error("fatal: path 'u.txt' exists on disk, but not in 'HEAD'")
        == "PathExistsButNotInRef"
    )
    assert classify_git_error("fatal: detected dubious ownership in repository at '/tmp'") == "UnsafeDirectory"
    assert (
        classify_git_error("CONFLICT (modify/delete): README.md deleted in HEAD and modified in abc")
        == "ConflictModifyDeletedInBranch"
    )


def test_is_git_error_matches_desktop() -> None:
    err = GitError("fatal: bad revision", git_error="BadRevision")
    assert is_git_error(err)
    assert is_git_error(err, "BadRevision")
    assert not is_git_error(err, "SSHKeyAuditUnverified")
    assert not is_git_error(RuntimeError("nope"))
    assert is_git_error(GitError("plain"))
    assert not is_git_error(GitError("plain"), "BadRevision")


def test_expected_errors_do_not_throw(git_repo: Path) -> None:
    result = git(_REV_LIST_MISSING, git_repo, expected_errors={"BadRevision"}, name="test")
    assert result.git_error == "BadRevision"
    assert result.exit_code == 128
    assert result.path == str(git_repo)


def test_unexpected_errors_throw(git_repo: Path) -> None:
    with pytest.raises(GitError) as caught:
        git(_REV_LIST_MISSING, git_repo, expected_errors={"SSHKeyAuditUnverified"}, name="test")
    assert is_git_error(caught.value, "BadRevision")
    assert caught.value.exit_code == 128


def test_success_exit_codes_do_not_throw(git_repo: Path) -> None:
    result = git(_REV_LIST_MISSING, git_repo, success_exit_codes={128}, name="test")
    assert result.exit_code == 128
    assert result.git_error is None


def test_unexpected_exit_codes_throw(git_repo: Path) -> None:
    with pytest.raises(GitError):
        git(_REV_LIST_MISSING, git_repo, success_exit_codes={2}, name="test")


def test_string_expected_errors_is_one_name(git_repo: Path) -> None:
    result = git(_REV_LIST_MISSING, git_repo, expected_errors="BadRevision", name="test")
    assert result.git_error == "BadRevision"


def test_ahead_behind_and_commits_in_range_bad_revision(git_repo: Path) -> None:
    assert get_ahead_behind_range(str(git_repo), "some-ref") is None
    assert get_commits_in_range(str(git_repo), "some-ref") is None


def test_branches_and_remotes_outside_a_repository(tmp_path: Path) -> None:
    # pytest's tmp_path lives under /tmp, which is a Git work tree in this
    # environment. Create the empty dir outside any repository.
    empty = Path.home() / f"not-a-repo-{tmp_path.name}"
    empty.mkdir()
    try:
        assert get_branches(str(empty)) == []
        assert get_remotes(str(empty)) == []
    finally:
        empty.rmdir()


def test_partial_blob_path_exists_but_not_in_ref(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("hello\n", encoding="utf-8")
    assert get_partial_blob_contents_catch_path_not_in_ref(str(git_repo), "HEAD", "untracked.txt") is None


def test_commit_range_changed_files_root_uses_null_tree(git_repo: Path) -> None:
    (git_repo / "added.txt").write_text("new\n", encoding="utf-8")
    run_git(git_repo, "add", "added.txt")
    run_git(git_repo, "commit", "-m", "add file")
    commits = get_commits(str(git_repo), limit=10)
    newest, oldest = commits[0], commits[-1]
    data = get_commit_range_changed_files(str(git_repo), oldest.sha, newest.sha)
    assert any(f.path == "added.txt" for f in data.files)


def test_config_lock_file_expected_error_and_path(git_repo: Path) -> None:
    config = git_repo / ".git" / "config"
    lock = git_repo / ".git" / "config.lock"
    copy(config, lock)
    result = git(
        ["config", "--local", "user.name", "niik"],
        git_repo,
        expected_errors={"ConfigLockFileAlreadyExists"},
        name="test",
    )
    assert result.exit_code == 255
    assert result.git_error == "ConfigLockFileAlreadyExists"
    parsed = parse_config_lock_file_path_from_error(result)
    assert parsed == str(lock.resolve())


def test_parse_config_lock_file_path_normalizes_absolute() -> None:
    result = GitResult(
        stdout="",
        stderr="error: could not lock config file /Users/markus/.gitconfig: File exists\n",
        exit_code=255,
        args=["config"],
        git_error="ConfigLockFileAlreadyExists",
        path="/",
    )
    assert parse_config_lock_file_path_from_error(result) == "/Users/markus/.gitconfig.lock"


def test_ensure_relative_path_matches_desktop() -> None:
    from github_desktop.git.ops import ensure_relative_path

    assert ensure_relative_path("README.md") == "README.md"
    assert ensure_relative_path("/tmp/abs.txt") == ":(top,literal)/tmp/abs.txt"


def test_get_commit_diff_root_and_later_commits(git_repo: Path) -> None:
    from github_desktop.git.ops import get_commit_diff
    from github_desktop.models import TextDiff

    commits = get_commits(str(git_repo), limit=5)
    root = commits[-1]
    diff = get_commit_diff(str(git_repo), "README.md", root.sha)
    assert isinstance(diff, TextDiff)
    assert any(line.text.endswith("hello") or "hello" in line.text for hunk in diff.hunks for line in hunk.lines)

    (git_repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "second")
    head = get_commits(str(git_repo), limit=1)[0]
    later = get_commit_diff(str(git_repo), "README.md", head.sha)
    assert isinstance(later, TextDiff)
    assert any("world" in line.text for hunk in later.hunks for line in hunk.lines)
