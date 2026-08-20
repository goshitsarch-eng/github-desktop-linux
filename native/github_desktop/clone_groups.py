"""Clone-repository grouping matching Desktop `groupRepositories`."""

from __future__ import annotations

from collections import defaultdict

from .models import GitHubRepository

YOUR_REPOSITORIES = "Your repositories"


def group_cloneable_repositories(
    repositories: list[GitHubRepository],
    login: str,
) -> list[tuple[str, list[GitHubRepository]]]:
    """Group cloneable repos into Your repositories, then organizations.

    Port of Desktop `app/src/ui/clone-repository/group-repositories.ts`.
    """
    groups: dict[str, list[GitHubRepository]] = defaultdict(list)
    login_key = (login or "").casefold()
    for repo in repositories:
        owner = repo.owner or ""
        key = YOUR_REPOSITORIES if owner.casefold() == login_key and login_key else owner
        groups[key].append(repo)
    for items in groups.values():
        items.sort(key=lambda item: item.name.casefold())

    def sort_key(identifier: str) -> tuple[int, str]:
        if identifier == YOUR_REPOSITORIES:
            return (0, "")
        return (1, identifier.casefold())

    return [(name, groups[name]) for name in sorted(groups, key=sort_key)]
