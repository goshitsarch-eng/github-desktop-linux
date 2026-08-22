"""Durable Issues / PR / mentionable cache (Desktop IndexedDB stand-in).

Desktop `IssuesDatabase` / `PullRequestDatabase` / `GitHubUserDatabase` persist
issues, PRs, and mentionables so `getLatestUpdatedAt` can request API deltas
after a restart. Native stores the same snapshots in `github-api-cache.json`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields
from typing import Any

from .logging import get_logger
from .models import GitHubRepository, Issue, PullRequest
from .paths import state_dir

log = get_logger()


def api_cache_path():
    """XDG state file for per-repo GitHub API caches."""
    return state_dir() / "github-api-cache.json"


def github_cache_key(github: GitHubRepository | None) -> str | None:
    """Stable key matching a GitHubRepository identity (endpoint + owner/name)."""
    if github is None:
        return None
    endpoint = (github.endpoint or "").rstrip("/")
    owner = github.owner or ""
    name = github.name or ""
    if not owner or not name:
        return None
    return f"{endpoint}|{owner}/{name}"


def _load_all() -> dict[str, Any]:
    path = api_cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save_all(payload: dict[str, Any]) -> None:
    path = api_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_github_api_cache(github: GitHubRepository | None) -> dict[str, Any] | None:
    """Return the cached payload for a GitHub repository, or None."""
    key = github_cache_key(github)
    if not key:
        return None
    entry = _load_all().get(key)
    return entry if isinstance(entry, dict) else None


def _issue_to_dict(item: Issue | tuple | list) -> dict[str, Any]:
    if isinstance(item, Issue):
        return asdict(item)
    if isinstance(item, (tuple, list)) and len(item) >= 2:
        return {"number": int(item[0]), "title": str(item[1]), "state": "open", "updated_at": ""}
    if isinstance(item, dict):
        return {
            "number": int(item.get("number") or 0),
            "title": str(item.get("title") or ""),
            "state": str(item.get("state") or "open"),
            "updated_at": str(item.get("updated_at") or ""),
        }
    return {"number": 0, "title": str(item), "state": "open", "updated_at": ""}


def _issue_from_dict(data: dict[str, Any] | list | tuple) -> tuple[int, str]:
    if isinstance(data, (tuple, list)) and len(data) >= 2:
        return int(data[0]), str(data[1])
    if isinstance(data, dict):
        return int(data.get("number") or 0), str(data.get("title") or "")
    return 0, str(data)


_PR_FIELDS = {item.name for item in fields(PullRequest)}


def _pr_from_dict(data: dict[str, Any]) -> PullRequest:
    kwargs = {key: data[key] for key in _PR_FIELDS if key in data}
    kwargs.setdefault("number", 0)
    kwargs.setdefault("title", "")
    kwargs.setdefault("body", "")
    kwargs.setdefault("created_at", "")
    kwargs.setdefault("author", "")
    kwargs.setdefault("draft", False)
    kwargs.setdefault("head_ref", "")
    kwargs.setdefault("head_sha", "")
    kwargs.setdefault("base_ref", "")
    kwargs.setdefault("html_url", "")
    return PullRequest(**kwargs)


def store_github_api_cache(
    github: GitHubRepository | None,
    *,
    issues: list | None = None,
    issues_last_updated_at: str | None = None,
    pull_requests: list[PullRequest] | None = None,
    last_pr_updated_at: str | None = None,
    mentionables: list | None = None,
    mentionables_etag: str | None = None,
    mentionables_fetched_at: float | None = None,
) -> None:
    """Merge one repository's Issues / PR / mentionable snapshot into the cache file."""
    key = github_cache_key(github)
    if not key:
        return
    payload = _load_all()
    entry = dict(payload.get(key) or {})
    if issues is not None:
        entry["issues"] = [_issue_to_dict(item) for item in issues]
    if issues_last_updated_at is not None:
        entry["issues_last_updated_at"] = issues_last_updated_at
    if pull_requests is not None:
        entry["pull_requests"] = [asdict(item) for item in pull_requests]
    if last_pr_updated_at is not None:
        entry["last_pr_updated_at"] = last_pr_updated_at
    if mentionables is not None:
        entry["mentionables"] = list(mentionables)
    if mentionables_etag is not None:
        entry["mentionables_etag"] = mentionables_etag
    if mentionables_fetched_at is not None:
        entry["mentionables_fetched_at"] = mentionables_fetched_at
    payload[key] = entry
    try:
        _save_all(payload)
    except OSError:
        log.debug("unable to write GitHub API cache", exc_info=True)


def apply_github_api_cache(state: Any, github: GitHubRepository | None) -> None:
    """Hydrate a RepositoryViewState from disk so delta fetches can resume."""
    cached = load_github_api_cache(github)
    if not cached:
        return
    raw_issues = cached.get("issues") or []
    if isinstance(raw_issues, list):
        state.issues = [_issue_from_dict(item) for item in raw_issues]
    if cached.get("issues_last_updated_at"):
        state.issues_last_updated_at = cached.get("issues_last_updated_at")
    raw_prs = cached.get("pull_requests") or []
    if isinstance(raw_prs, list):
        state.pull_requests = [
            _pr_from_dict(item) for item in raw_prs if isinstance(item, dict)
        ]
    if cached.get("last_pr_updated_at"):
        state.last_pr_updated_at = cached.get("last_pr_updated_at")
    raw_mentionables = cached.get("mentionables") or []
    if isinstance(raw_mentionables, list):
        state.mentionables = list(raw_mentionables)
        state.mentions = [
            str(item.get("login") or item.get("name") or "")
            if isinstance(item, dict)
            else str(item)
            for item in raw_mentionables
        ]
        state.mentions = [name for name in state.mentions if name]
    if cached.get("mentionables_etag") is not None:
        state.mentionables_etag = cached.get("mentionables_etag")
    if cached.get("mentionables_fetched_at") is not None:
        try:
            state.mentionables_fetched_at = float(cached.get("mentionables_fetched_at") or 0.0)
        except (TypeError, ValueError):
            pass


def clear_github_api_cache(github: GitHubRepository | None) -> None:
    """Drop one repository's cache entry (Desktop deleting a repo's IndexedDB rows)."""
    key = github_cache_key(github)
    if not key:
        return
    payload = _load_all()
    if key in payload:
        payload.pop(key, None)
        try:
            _save_all(payload)
        except OSError:
            log.debug("unable to clear GitHub API cache", exc_info=True)
