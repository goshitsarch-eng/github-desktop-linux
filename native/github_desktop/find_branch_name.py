"""Branch name used for protection / push-control (Desktop `findRemoteBranchName`)."""

from __future__ import annotations

from .models import Branch, GitHubRepository, Remote
from .remote_parsing import url_matches_clone_url


def find_remote_branch_name(
    branch: Branch | None,
    remote: Remote | None,
    github: GitHubRepository | None,
) -> str | None:
    """Desktop `findRemoteBranchName`.

    Use the upstream name when the current remote matches the associated GitHub
    repository; otherwise the local name (what a first push would create).
    """
    if branch is None:
        return None
    if (
        branch.upstream_without_remote
        and remote is not None
        and github is not None
        and url_matches_clone_url(remote.url, github)
    ):
        return branch.upstream_without_remote
    return branch.name_without_remote
