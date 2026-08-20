"""Remaining Desktop-parity helpers: forks, SAML, oversized, protocol, banners."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import overwritten_files_from_error, parse_saml_organization
from github_desktop.git.ops import ensure_upstream_remote, get_remotes
from github_desktop.models import (
    Banner,
    BannerType,
    ForkContributionTarget,
    GitHubRepository,
    PopupType,
    Repository,
    fork_contribution_target,
    github_for_contribution,
    github_from_dict,
    github_to_dict,
)
from github_desktop.protocol import OpenRepositoryAction, parse_app_url
from github_desktop.store import AppStore
from tests.conftest import run_git


SAMPLE_SAML = """
remote: The `acme-org' organization has enabled or enforced SAML SSO.
remote: To access this repository, you must re-authorize the OAuth Application.
fatal: Could not read from remote repository.
"""

SAMPLE_OVERWRITE = """
error: Your local changes to the following files would be overwritten by checkout:
	src/app.ts
	README.md
Please commit your changes or stash them before you switch branches.
Aborting
"""


def test_parse_saml_organization() -> None:
    assert parse_saml_organization(SAMPLE_SAML) == "acme-org"
    assert parse_saml_organization("unrelated") is None


def test_overwritten_files_from_error() -> None:
    assert overwritten_files_from_error(SAMPLE_OVERWRITE) == ["src/app.ts", "README.md"]


def test_github_dict_roundtrip_includes_parent() -> None:
    parent = GitHubRepository("upstream", "acme", "https://github.com/acme/upstream", "https://github.com/acme/upstream.git")
    fork = GitHubRepository(
        "upstream",
        "me",
        "https://github.com/me/upstream",
        "https://github.com/me/upstream.git",
        fork=True,
        parent=parent,
    )
    restored = github_from_dict(github_to_dict(fork))
    assert restored is not None
    assert restored.fork
    assert restored.parent is not None
    assert restored.parent.owner == "acme"


def test_fork_contribution_target_parent_by_default() -> None:
    parent = GitHubRepository("app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git")
    fork = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git", fork=True, parent=parent)
    repo = Repository(1, "/tmp/app", "app", github=fork)
    assert fork_contribution_target(repo) == ForkContributionTarget.PARENT
    assert github_for_contribution(repo) is parent
    repo.workflow_preferences["fork_target"] = ForkContributionTarget.SELF.value
    assert github_for_contribution(repo) is fork


def test_ensure_upstream_remote_adds_and_detects_mismatch(git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://github.com/me/app.git")
    action, remote = ensure_upstream_remote(git_repo.as_posix(), "https://github.com/acme/app.git")
    assert action == "added"
    assert remote is not None
    assert remote.name == "upstream"
    names = {r.name for r in get_remotes(git_repo.as_posix())}
    assert "upstream" in names
    action, existing = ensure_upstream_remote(git_repo.as_posix(), "https://github.com/other/app.git")
    assert action == "mismatch"
    assert existing is not None


def test_open_pull_request_gates_unpublished_branch(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = None
    store.open_pull_request(repo)
    assert store.popup is not None
    assert store.popup.type == PopupType.PUSH_BRANCH_COMMITS
    assert store.popup.payload.get("unpublished") is True


def test_protocol_openrepo_keeps_pr_and_filepath() -> None:
    action = parse_app_url(
        "x-github-client://openRepo/https://github.com/desktop/desktop?pr=42&filepath=README.md"
    )
    assert isinstance(action, OpenRepositoryAction)
    assert action.pr == "42"
    assert action.filepath == "README.md"


def test_banner_undo_sha_roundtrip() -> None:
    banner = Banner(BannerType.SUCCESSFUL_MERGE, their_branch="main", undo_sha="abc123")
    assert banner.undo_sha == "abc123"


def test_convert_repository_to_fork_rewires_remotes(isolated_config, git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://github.com/acme/app.git")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    parent = GitHubRepository("app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git")
    repo.github = parent
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=parent,
    )
    store.convert_repository_to_fork(repo, fork)
    remotes = {r.name: r.url for r in get_remotes(str(git_repo))}
    from github_desktop.remote_parsing import parse_remote

    origin = parse_remote(remotes["origin"])
    upstream = parse_remote(remotes["upstream"])
    assert origin is not None and origin.owner == "me" and origin.name == "app"
    assert upstream is not None and upstream.owner == "acme" and upstream.name == "app"
    assert repo.github is fork
    assert store.popup is not None
    assert store.popup.type == PopupType.CHOOSE_FORK_SETTINGS
