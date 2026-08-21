"""Locate the default branch (Desktop `findDefaultBranch`)."""

from __future__ import annotations

from typing import Sequence

from .models import (
    UPSTREAM_REMOTE_NAME,
    Branch,
    BranchType,
    ForkContributionTarget,
    Repository,
    fork_contribution_target,
    is_repository_with_github_repository,
)


def is_forked_repository_contributing_to_parent(repo: Repository) -> bool:
    """Desktop `isForkedRepositoryContributingToParent`."""
    return bool(repo.is_fork and fork_contribution_target(repo) == ForkContributionTarget.PARENT)


def find_default_branch(
    repository: Repository,
    branches: Sequence[Branch],
    default_remote_name: str | None,
    *,
    remote_head: str | None = None,
    init_default_branch: str = "main",
) -> Branch | None:
    """Desktop `findDefaultBranch`.

    Prefers a local branch tracking the contribution-target remote HEAD, then a
    local branch named the same as that HEAD, then the remote branch itself.
    """
    remote_name = UPSTREAM_REMOTE_NAME if is_forked_repository_contributing_to_parent(repository) else default_remote_name
    default_branch_name = remote_head or init_default_branch
    remote_ref = f"{remote_name}/{remote_head}" if remote_name and remote_head else None

    local_hit: Branch | None = None
    local_tracking_hit: Branch | None = None
    remote_hit: Branch | None = None
    for branch in branches:
        if branch.type == BranchType.LOCAL:
            if branch.name == default_branch_name:
                local_hit = branch
            if remote_ref and branch.upstream == remote_ref:
                if local_tracking_hit is None or branch.name == default_branch_name:
                    local_tracking_hit = branch
        elif remote_ref and branch.name == remote_ref:
            remote_hit = branch
    return local_tracking_hit or local_hit or remote_hit


def find_contribution_target_default_branch(
    repository: Repository,
    default_branch: Branch | None,
    upstream_default_branch: Branch | None = None,
) -> Branch | None:
    """Desktop `findContributionTargetDefaultBranch`.

    Prefer ``upstream_default_branch`` when the repository is associated with
    GitHub (that branch is only populated while contributing to a fork parent);
    otherwise return ``default_branch``.
    """
    if is_repository_with_github_repository(repository):
        return upstream_default_branch if upstream_default_branch is not None else default_branch
    return default_branch
