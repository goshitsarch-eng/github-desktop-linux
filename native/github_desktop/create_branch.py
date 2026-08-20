"""Desktop `lib/create-branch`: resolve Create Branch start points."""

from __future__ import annotations

from .models import (
    Branch,
    BranchType,
    ForkContributionTarget,
    Repository,
    StartPoint,
    TipState,
    fork_contribution_target,
)


def get_start_point(
    *,
    tip_kind: TipState | str | None,
    default_branch: Branch | None,
    upstream_default_branch: Branch | None,
    preferred: StartPoint = StartPoint.UPSTREAM_DEFAULT_BRANCH,
) -> StartPoint:
    """Desktop `getStartPoint`."""
    kind = tip_kind.value if isinstance(tip_kind, TipState) else (tip_kind or "")
    if kind in (TipState.DETACHED.value, "Detached"):
        return StartPoint.HEAD
    if preferred == StartPoint.UPSTREAM_DEFAULT_BRANCH and upstream_default_branch is not None:
        return preferred
    if preferred == StartPoint.DEFAULT_BRANCH and default_branch is not None:
        return preferred
    if preferred == StartPoint.CURRENT_BRANCH and kind == TipState.VALID.value:
        return preferred
    if preferred == StartPoint.HEAD:
        return preferred
    if upstream_default_branch is not None:
        return StartPoint.UPSTREAM_DEFAULT_BRANCH
    if default_branch is not None:
        return StartPoint.DEFAULT_BRANCH
    if kind == TipState.VALID.value:
        return StartPoint.CURRENT_BRANCH
    return StartPoint.HEAD


def upstream_default_branch_for(
    repo: Repository,
    branches: list[Branch],
    default_name: str | None,
) -> Branch | None:
    """Remote branch tracking the fork parent's default (Desktop `upstreamDefaultBranch`)."""
    if not repo.is_fork or fork_contribution_target(repo) != ForkContributionTarget.PARENT:
        return None
    parent = repo.github.parent if repo.github else None
    name = (parent.default_branch if parent else None) or default_name
    if not name:
        return None
    for branch in branches:
        if branch.type == BranchType.REMOTE and branch.name_without_remote == name:
            remote = (branch.remote or "").lower()
            if remote in ("upstream", "origin") or branch.name.startswith("upstream/"):
                return branch
    for branch in branches:
        if branch.name in (f"upstream/{name}", f"origin/{name}"):
            return branch
    return None
