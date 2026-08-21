"""Durable GitHub Issues / PR / mentionable cache."""

from __future__ import annotations

from github_desktop.api_cache import (
    apply_github_api_cache,
    clear_github_api_cache,
    github_cache_key,
    load_github_api_cache,
    store_github_api_cache,
)
from github_desktop.models import GitHubRepository, PullRequest, Repository
from github_desktop.store import AppStore, RepositoryViewState


def _github() -> GitHubRepository:
    return GitHubRepository(
        name="desktop",
        owner="desktop",
        html_url="https://github.com/desktop/desktop",
        clone_url="https://github.com/desktop/desktop.git",
        ssh_url="git@github.com:desktop/desktop.git",
        endpoint="https://api.github.com",
    )


def test_github_cache_key_uses_endpoint_owner_name() -> None:
    gh = _github()
    assert github_cache_key(gh) == "https://api.github.com|desktop/desktop"
    assert github_cache_key(None) is None


def test_store_and_load_issues_prs_mentionables(isolated_config) -> None:
    gh = _github()
    pr = PullRequest(
        number=12,
        title="Fix cache",
        body="",
        created_at="2026-01-01T00:00:00Z",
        author="niik",
        draft=False,
        head_ref="topic",
        head_sha="abc",
        base_ref="main",
        html_url="https://github.com/desktop/desktop/pull/12",
        updated_at="2026-01-02T00:00:00Z",
    )
    store_github_api_cache(
        gh,
        issues=[(42, "Ship GTK")],
        issues_last_updated_at="2026-01-02T00:00:00Z",
        pull_requests=[pr],
        last_pr_updated_at="2026-01-02T00:00:00Z",
        mentionables=[{"login": "niik", "name": "Markus"}],
        mentionables_etag='"etag-1"',
        mentionables_fetched_at=1_700_000_000.0,
    )
    cached = load_github_api_cache(gh)
    assert cached is not None
    assert cached["issues_last_updated_at"] == "2026-01-02T00:00:00Z"
    assert cached["pull_requests"][0]["number"] == 12

    state = RepositoryViewState()
    apply_github_api_cache(state, gh)
    assert state.issues == [(42, "Ship GTK")]
    assert state.issues_last_updated_at == "2026-01-02T00:00:00Z"
    assert state.pull_requests[0].title == "Fix cache"
    assert state.last_pr_updated_at == "2026-01-02T00:00:00Z"
    assert state.mentionables[0]["login"] == "niik"
    assert "niik" in state.mentions
    assert state.mentionables_etag == '"etag-1"'
    assert state.mentionables_fetched_at == 1_700_000_000.0


def test_appstore_hydrates_and_clears_cache(isolated_config, git_repo) -> None:
    gh = _github()
    store_github_api_cache(
        gh,
        issues=[(7, "Cached issue")],
        issues_last_updated_at="2026-01-03T00:00:00Z",
        pull_requests=[],
        last_pr_updated_at=None,
        mentionables=[],
    )
    first = AppStore()
    repo = Repository(id=first._next_id, path=str(git_repo), name="desktop", github=gh)
    first.repositories.append(repo)
    first.repo_state[repo.id] = RepositoryViewState()
    first._hydrate_github_api_cache(repo)
    assert first.state_for(repo).issues == [(7, "Cached issue")]
    assert first.state_for(repo).issues_last_updated_at == "2026-01-03T00:00:00Z"

    first._persist_github_api_cache(repo)
    first.remove_repository(repo)
    assert load_github_api_cache(gh) is None


def test_clear_missing_entry_is_noop(isolated_config) -> None:
    clear_github_api_cache(_github())
    assert load_github_api_cache(_github()) is None
