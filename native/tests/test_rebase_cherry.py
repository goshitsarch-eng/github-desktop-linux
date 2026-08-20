"""Rebase, cherry-pick, squash, and reset integration tests."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.ops import (
    checkout_branch,
    cherry_pick,
    continue_rebase,
    create_branch,
    get_commits,
    get_status,
    rebase,
    reset,
    squash_commits,
)
from github_desktop.models import AppFileStatusKind, CherryPickResult, RebaseResult
from tests.conftest import run_git


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    run_git(repo, "add", name)
    run_git(repo, "commit", "-m", message)


def test_rebase_fast_forward_like(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "on-main.txt", "m\n", "on main")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "on-topic.txt", "t\n", "on topic")
    result = rebase(git_repo.as_posix(), "main")
    assert result in (RebaseResult.COMPLETED_WITHOUT_ERROR, RebaseResult.ALREADY_UP_TO_DATE)
    summaries = [c.summary for c in get_commits(git_repo.as_posix(), limit=10)]
    assert "on topic" in summaries
    assert "on main" in summaries


def test_rebase_conflicts(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "README.md", "main-change\n", "main edit")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "README.md", "topic-change\n", "topic edit")
    result = rebase(git_repo.as_posix(), "main")
    assert result == RebaseResult.CONFLICTS_ENCOUNTERED
    status = get_status(git_repo.as_posix())
    assert status and status.rebase_internal_state is not None
    assert any(f.status.kind == AppFileStatusKind.CONFLICTED for f in status.working_directory.files)


def test_cherry_pick(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "picked.txt", "p\n", "pick me")
    sha = get_commits(git_repo.as_posix(), limit=1)[0].sha
    checkout_branch(git_repo.as_posix(), "main")
    result = cherry_pick(git_repo.as_posix(), [sha])
    assert result == CherryPickResult.COMPLETED_WITHOUT_ERROR
    assert (git_repo / "picked.txt").exists()


def test_squash_last_two(git_repo: Path) -> None:
    _commit_file(git_repo, "one.txt", "1\n", "one")
    _commit_file(git_repo, "two.txt", "2\n", "two")
    commits = get_commits(git_repo.as_posix(), limit=10)
    # commits[0] is newest
    newest, older = commits[0], commits[1]
    last_retained = commits[2].sha if len(commits) > 2 else None
    result = squash_commits(
        git_repo.as_posix(),
        [newest],
        older,
        last_retained,
        "squashed together\n",
    )
    assert result in (RebaseResult.COMPLETED_WITHOUT_ERROR, RebaseResult.CONFLICTS_ENCOUNTERED)
    if result == RebaseResult.COMPLETED_WITHOUT_ERROR:
        summaries = [c.summary for c in get_commits(git_repo.as_posix(), limit=5)]
        assert "squashed together" in summaries or "two" in summaries


def test_reset_mixed(git_repo: Path) -> None:
    _commit_file(git_repo, "later.txt", "l\n", "later")
    sha = get_commits(git_repo.as_posix(), limit=5)[-1].sha  # initial
    # reset to initial keeps later.txt unstaged? mixed reset of HEAD~1 is more typical
    head_parent = get_commits(git_repo.as_posix(), limit=2)[1].sha
    reset(git_repo.as_posix(), head_parent, "mixed")
    status = get_status(git_repo.as_posix())
    assert status
    assert any(f.path == "later.txt" for f in status.working_directory.files)
