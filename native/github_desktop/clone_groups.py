"""Clone-repository grouping matching Desktop `groupRepositories`."""

from __future__ import annotations

from functools import cmp_to_key
from collections import defaultdict

from .compare import case_insensitive_compare
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
        items.sort(key=cmp_to_key(lambda a, b: case_insensitive_compare(a.name, b.name)))

    def sort_key(identifier: str) -> tuple[int, str]:
        if identifier == YOUR_REPOSITORIES:
            return (0, "")
        return (1, identifier.casefold())

    return [(name, groups[name]) for name in sorted(groups, key=sort_key)]
