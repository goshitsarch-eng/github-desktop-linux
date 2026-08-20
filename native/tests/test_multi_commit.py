"""Multi-commit operation helpers: merge-tree, ahead/behind, canStartOperation."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.ops import (
    checkout_branch,
    create_branch,
    determine_mergeability,
    get_ahead_behind,
    get_ahead_behind_range,
    get_boolean_config_value,
    get_commits_between,
    warn_about_remote_commits,
)
from github_desktop.models import Branch, BranchType, ComputedAction
from github_desktop.ui.multi_commit import can_start_operation
from tests.conftest import run_git


def _commit_file(repo: Path, name: str, content: str, message: str) -> None:
    (repo / name).write_text(content, encoding="utf-8")
    run_git(repo, "add", name)
    run_git(repo, "commit", "-m", message)


def test_determine_mergeability_clean(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "topic.txt", "t\n", "topic")
    checkout_branch(git_repo.as_posix(), "main")
    ours = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    theirs = run_git(git_repo, "rev-parse", "topic").stdout.strip()
    result = determine_mergeability(git_repo.as_posix(), ours, theirs)
    assert result.kind == ComputedAction.CLEAN
    assert result.conflicted_files == 0


def test_determine_mergeability_conflicts(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "README.md", "main-change\n", "main edit")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "README.md", "topic-change\n", "topic edit")
    checkout_branch(git_repo.as_posix(), "main")
    ours = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    theirs = run_git(git_repo, "rev-parse", "topic").stdout.strip()
    result = determine_mergeability(git_repo.as_posix(), ours, theirs)
    assert result.kind == ComputedAction.CONFLICTS
    assert result.conflicted_files >= 1


def test_get_commits_between_and_ahead_behind(git_repo: Path) -> None:
    create_branch(git_repo.as_posix(), "topic")
    checkout_branch(git_repo.as_posix(), "topic")
    _commit_file(git_repo, "on-topic.txt", "t\n", "on topic")
    checkout_branch(git_repo.as_posix(), "main")
    _commit_file(git_repo, "on-main.txt", "m\n", "on main")
    behind = get_commits_between(git_repo.as_posix(), "main", "topic")
    ahead = get_commits_between(git_repo.as_posix(), "topic", "main")
    assert behind is not None and any(c.summary == "on topic" for c in behind)
    assert ahead is not None and any(c.summary == "on main" for c in ahead)
    ab = get_ahead_behind_range(git_repo.as_posix(), "...topic")
    assert ab is not None
    assert ab.behind == len(behind)
    tracking = get_ahead_behind(git_repo.as_posix(), "topic")
    assert tracking is not None
    assert tracking.behind == len(behind)
    assert tracking.ahead == len(ahead)


def test_can_start_operation() -> None:
    assert can_start_operation(None, "main", 2, ComputedAction.CLEAN) is False
    assert can_start_operation("main", "main", 2, ComputedAction.CLEAN) is False
    assert can_start_operation("topic", "main", 0, ComputedAction.CLEAN) is False
    assert can_start_operation("topic", "main", 2, ComputedAction.LOADING) is False
    assert can_start_operation("topic", "main", 2, ComputedAction.INVALID) is False
    assert can_start_operation("topic", "main", 0, ComputedAction.CONFLICTS) is True
    assert can_start_operation("topic", "main", 2, ComputedAction.CLEAN) is True


def test_warn_about_remote_commits_without_upstream(git_repo: Path) -> None:
    branch = Branch(name="main", upstream=None, tip_sha="abc", type=BranchType.LOCAL)
    assert warn_about_remote_commits(git_repo.as_posix(), branch, "HEAD") is False


def test_get_boolean_config_value(git_repo: Path) -> None:
    key = "githubdesktop.test.bool"
    assert get_boolean_config_value(git_repo.as_posix(), key) is None
    run_git(git_repo, "config", key, "true")
    assert get_boolean_config_value(git_repo.as_posix(), key) is True
    run_git(git_repo, "config", key, "false")
    assert get_boolean_config_value(git_repo.as_posix(), key) is False
