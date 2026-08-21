"""Commit URLs on GitHub (Desktop `createCommitURL`)."""

from __future__ import annotations

import hashlib

from .models import GitHubRepository


def create_commit_url(
    github: GitHubRepository | None,
    sha: str,
    file_path: str | None = None,
) -> str | None:
    """Desktop `createCommitURL`: `/commit/{sha}` plus optional `#diff-` file hash."""
    if github is None:
        return None
    base = (github.html_url or "").rstrip("/")
    if not base:
        return None
    url = f"{base}/commit/{sha}"
    if file_path is None:
        return url
    digest = hashlib.sha256(file_path.encode("utf-8")).hexdigest()
    return f"{url}#diff-{digest}"
