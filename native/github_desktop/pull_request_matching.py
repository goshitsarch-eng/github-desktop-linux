"""Match the current branch to an open pull request (Desktop `pull-request-matching`)."""

from __future__ import annotations

from typing import Sequence

from .models import Branch, GitHubRepository, PullRequest, Remote
from .remote_parsing import parse_remote, repository_matches_remote, url_matches_remote


def _head_github_repository(pr: PullRequest) -> GitHubRepository | None:
    if not pr.head_clone_url:
        return None
    parsed = parse_remote(pr.head_clone_url)
    if parsed is None:
        return None
    html = f"https://{parsed.hostname}/{parsed.owner}/{parsed.name}"
    return GitHubRepository(
        name=parsed.name,
        owner=parsed.owner or pr.head_owner or "",
        html_url=html,
        clone_url=pr.head_clone_url,
        ssh_url=(
            pr.head_clone_url
            if parsed.protocol == "ssh"
            else f"git@{parsed.hostname}:{parsed.owner}/{parsed.name}.git"
        ),
    )


def is_pull_request_associated_with_branch(
    branch: Branch,
    pr: PullRequest,
    remote: Remote,
) -> bool:
    """Desktop `isPullRequestAssociatedWithBranch`."""
    if not branch.upstream_without_remote:
        return False
    if pr.head_ref != branch.upstream_without_remote:
        return False
    head = _head_github_repository(pr)
    if head is not None:
        return repository_matches_remote(head, remote)
    if pr.head_clone_url:
        return url_matches_remote(pr.head_clone_url, remote)
    return False


def find_associated_pull_request(
    branch: Branch,
    pull_requests: Sequence[PullRequest],
    remote: Remote,
) -> PullRequest | None:
    """Desktop `findAssociatedPullRequest`."""
    if not branch.upstream_without_remote:
        return None
    return next(
        (pr for pr in pull_requests if is_pull_request_associated_with_branch(branch, pr, remote)),
        None,
    )


def associated_pull_request_for(
    pull_requests: Sequence[PullRequest],
    *,
    current_branch: str | None,
    branches: Sequence[Branch],
    remotes: Sequence[Remote],
) -> PullRequest | None:
    """Resolve the current PR from refresh payloads (tip branch + current remote)."""
    if not current_branch or not remotes:
        return None
    branch = next((item for item in branches if item.name == current_branch and item.is_local), None)
    if branch is None:
        return None
    remote = next((item for item in remotes if item.name == "origin"), remotes[0])
    return find_associated_pull_request(branch, pull_requests, remote)
