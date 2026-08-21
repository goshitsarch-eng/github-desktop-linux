"""Desktop nameOf / getGitHubHtmlUrl / sanitizedRefName / getAuthorIdentity."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from github_desktop.git.ops import get_author_identity
from github_desktop.models import (
    CommitIdentity,
    ForkContributionTarget,
    GitHubRepository,
    Repository,
    assert_is_repository_with_github_repository,
    get_github_html_url,
    get_non_fork_github_repository,
    is_forked_repository_contributing_to_parent,
    name_of,
    sanitize_ref_name,
    sanitized_ref_name,
    test_for_invalid_chars,
)


def _github(
    owner: str,
    name: str,
    *,
    parent: GitHubRepository | None = None,
) -> GitHubRepository:
    return GitHubRepository(
        name=name,
        owner=owner,
        html_url=f"https://github.com/{owner}/{name}",
        clone_url=f"https://github.com/{owner}/{name}.git",
        fork=parent is not None,
        parent=parent,
    )


def test_sanitized_ref_name_matches_desktop() -> None:
    assert sanitize_ref_name("this-is/fine") == "this-is/fine"
    assert sanitize_ref_name(".this..is\\not fine:yo?|is-it") == "this-is-not-fine-yo-is-it"
    assert sanitize_ref_name("hello/") == "hello-"
    assert sanitize_ref_name("++but-can-still-keep-the-rest") == "but-can-still-keep-the-rest"
    assert sanitize_ref_name("--but-can-still-keep-the-rest") == "but-can-still-keep-the-rest"
    assert sanitize_ref_name("foo.lock.lock") == "foo.lock-"
    assert sanitize_ref_name("hello\r\nworld") == "hello-world"
    assert sanitize_ref_name(".first.dot.is.not.ok") == "first.dot.is.not.ok"
    assert sanitize_ref_name("branch--name") == "branch--name"
    assert sanitize_ref_name("release 1") == "release-1"
    assert sanitized_ref_name("foo:bar") == "foo-bar"
    assert not test_for_invalid_chars("")
    assert not test_for_invalid_chars("this-is/fine")
    assert test_for_invalid_chars("foo:bar")
    assert test_for_invalid_chars("hello/")
    assert test_for_invalid_chars("foo.lock")


def test_name_of_and_github_html_url() -> None:
    local = Repository(1, "/tmp/app", "app")
    assert name_of(local) == "app"
    assert get_github_html_url(local) is None
    with pytest.raises(RuntimeError, match="Repository must be GitHub repository"):
        assert_is_repository_with_github_repository(local)
        get_non_fork_github_repository(local)

    parent = _github("desktop", "desktop")
    associated = Repository(2, "/tmp/desktop", "desktop", github=parent)
    assert name_of(associated) == "desktop/desktop"
    assert get_github_html_url(associated) == "https://github.com/desktop/desktop"
    assert get_non_fork_github_repository(associated) is parent

    fork = _github("me", "desktop", parent=parent)
    contributing = Repository(3, "/tmp/fork", "desktop", github=fork)
    assert is_forked_repository_contributing_to_parent(contributing)
    assert name_of(contributing) == "me/desktop"
    assert get_github_html_url(contributing) == "https://github.com/desktop/desktop"
    assert get_non_fork_github_repository(contributing) is parent

    self_target = Repository(
        4,
        "/tmp/fork",
        "desktop",
        github=fork,
        workflow_preferences={"fork_target": ForkContributionTarget.SELF.value},
    )
    assert not is_forked_repository_contributing_to_parent(self_target)
    assert get_github_html_url(self_target) == "https://github.com/me/desktop"
    assert get_non_fork_github_repository(self_target) is fork


def test_parse_identity_matches_desktop() -> None:
    ident = CommitIdentity.parse_identity(
        "Markus Olsson <j.markus.olsson@gmail.com> 1475670580 +0200"
    )
    assert ident.name == "Markus Olsson"
    assert ident.email == "j.markus.olsson@gmail.com"
    assert ident.tz_offset == 120
    with pytest.raises(ValueError, match="Couldn't parse identity"):
        CommitIdentity.parse_identity("not-an-ident")
    fallback = CommitIdentity.parse_raw("not-an-ident")
    assert fallback.name == "not-an-ident"
    assert fallback.email == ""


def test_get_author_identity_matches_git_var(git_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name, email = get_author_identity(str(git_repo))
    assert name == "Test User"
    assert email == "test@example.com"

    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(key, raising=False)
    subprocess.run(["git", "config", "--local", "user.useConfigOnly", "true"], cwd=git_repo, check=True)
    subprocess.run(["git", "config", "--local", "--unset-all", "user.name"], cwd=git_repo, check=False)
    subprocess.run(["git", "config", "--local", "--unset-all", "user.email"], cwd=git_repo, check=False)
    name, email = get_author_identity(str(git_repo))
    assert name is None
    assert email is None
