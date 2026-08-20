"""Repository sidebar grouping matching Desktop `ui/repositories-list/group-repositories.ts`."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from .models import Repository, html_url_from_endpoint, is_dotcom_endpoint

# Show a Recent group once the user has more repositories than this.
RECENT_REPOSITORIES_THRESHOLD = 7
# Desktop `RecentRepositoriesLength`: stored ids for previously selected repos.
RECENT_REPOSITORIES_LENGTH = 3


@dataclass
class RepositoryListItem:
    repository: Repository
    needs_disambiguation: bool = False


@dataclass
class RepositoryListGroup:
    kind: str
    key: str
    label: str
    items: list[RepositoryListItem] = field(default_factory=list)


def get_host_for_repository(repo: Repository) -> str:
    github = repo.github
    if github is None:
        return ""
    html = (github.html_url or html_url_from_endpoint(github.endpoint or "")).rstrip("/")
    host = urlparse(html).hostname if html else None
    return host or "Enterprise"


def get_group_for_repository(repo: Repository) -> tuple[str, str, str]:
    github = repo.github
    if github is not None:
        endpoint = github.endpoint or ""
        html = github.html_url or ""
        if is_dotcom_endpoint(endpoint) or html.startswith("https://github.com/") or html.startswith("http://github.com/"):
            owner = github.owner
            return "dotcom", f"1:dotcom:{owner}", owner
        host = get_host_for_repository(repo)
        return "enterprise", f"2:enterprise:{host}", host
    return "other", "3:other", "Other"


def group_repositories(
    repositories: list[Repository],
    recent_repository_ids: list[int] | None = None,
) -> list[RepositoryListGroup]:
    """Desktop `groupRepositories`: Recent (if >7 repos), GitHub.com by owner, Enterprise by host, Other."""
    include_recent = len(repositories) > RECENT_REPOSITORIES_THRESHOLD
    recent_set = set(recent_repository_ids or ()) if include_recent else set()
    groups: dict[str, RepositoryListGroup] = {}

    def add(kind: str, key: str, label: str, repo: Repository) -> None:
        group = groups.get(key)
        if group is None:
            group = RepositoryListGroup(kind, key, label)
            groups[key] = group
        group.items.append(RepositoryListItem(repo))

    for repo in repositories:
        if include_recent and repo.id in recent_set:
            add("recent", "0:recent", "Recent", repo)
        kind, key, label = get_group_for_repository(repo)
        add(kind, key, label, repo)

    all_names: dict[str, int] = {}
    for group in groups.values():
        if group.kind == "recent":
            continue
        for item in group.items:
            title = item.repository.display_name
            all_names[title] = all_names.get(title, 0) + 1

    ordered = [groups[key] for key in sorted(groups)]
    for group in ordered:
        group_names: dict[str, int] = {}
        for item in group.items:
            title = item.repository.display_name
            group_names[title] = group_names.get(title, 0) + 1
        for item in group.items:
            title = item.repository.display_name
            item.needs_disambiguation = (
                group_names.get(title, 0) > 1 and group.kind == "enterprise"
            ) or (all_names.get(title, 0) > 1 and group.kind == "recent")
        group.items.sort(key=lambda item: (item.repository.display_name or "").casefold())
    return ordered
