"""Find a fork's `upstream` remote (Desktop `findUpstreamRemote`)."""

from __future__ import annotations

from typing import Sequence

from .models import UPSTREAM_REMOTE_NAME, GitHubRepository, Remote
from .remote_parsing import repository_matches_remote

UpstreamRemoteName = UPSTREAM_REMOTE_NAME


def find_upstream_remote(parent: GitHubRepository, remotes: Sequence[Remote]) -> Remote | None:
    """Desktop `findUpstreamRemote`.

    Returns the remote named ``upstream`` when its URL matches ``parent``.
    """
    upstream = next((item for item in remotes if item.name == UpstreamRemoteName), None)
    if upstream is None:
        return None
    return upstream if repository_matches_remote(parent, upstream) else None
