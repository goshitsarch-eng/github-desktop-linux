"""Local push/fetch/pull against a file:// remote (no network)."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.ops import (
    add_remote,
    checkout_branch,
    create_branch,
    fetch,
    get_status,
    pull,
    push,
)
from tests.conftest import run_git


def test_push_fetch_pull_file_remote(git_repo: Path, tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    run_git(git_repo, "clone", "--bare", str(git_repo), str(bare))
    work = tmp_path / "work"
    run_git(git_repo, "clone", str(bare), str(work))
    run_git(work, "config", "user.name", "Test User")
    run_git(work, "config", "user.email", "test@example.com")
    (work / "extra.txt").write_text("e\n", encoding="utf-8")
    run_git(work, "add", "extra.txt")
    run_git(work, "commit", "-m", "extra")
    push(str(work), "origin", "main", "main")
    # fetch into original
    add_remote(str(git_repo), "copy", str(bare))
    fetch(str(git_repo), "copy")
    status = get_status(str(git_repo))
    assert status
    # create a second clone and pull
    other = tmp_path / "other"
    run_git(git_repo, "clone", str(bare), str(other))
    run_git(other, "config", "user.name", "Test User")
    run_git(other, "config", "user.email", "test@example.com")
    # make remote ahead
    (work / "more.txt").write_text("m\n", encoding="utf-8")
    run_git(work, "add", "more.txt")
    run_git(work, "commit", "-m", "more")
    push(str(work), "origin", "main", "main")
    pull(str(other), "origin", "main")
    assert (other / "more.txt").exists()
