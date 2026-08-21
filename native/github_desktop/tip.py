"""Desktop `lib/tip.ts` — HEAD tip helpers."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Branch, TipState


@dataclass
class Tip:
    """Desktop `Tip` union (unknown / unborn / detached / valid)."""

    kind: TipState
    branch: Branch | None = None
    current_sha: str | None = None
    ref: str | None = None


def get_tip_sha(tip: Tip) -> str:
    """Desktop `getTipSha`."""
    if tip.kind == TipState.VALID:
        return tip.branch.tip_sha if tip.branch is not None else "(unknown)"
    if tip.kind == TipState.DETACHED:
        return tip.current_sha or "(unknown)"
    return "(unknown)"


def tip_equals(left: Tip, right: Tip) -> bool:
    """Desktop `tipEquals`."""
    if left is right:
        return True
    if left.kind != right.kind:
        return False
    if left.kind == TipState.UNKNOWN:
        return True
    if left.kind == TipState.UNBORN:
        return left.ref == right.ref
    if left.kind == TipState.DETACHED:
        return left.current_sha == right.current_sha
    if left.kind == TipState.VALID:
        return _branch_equals(left.branch, right.branch)
    return False


def _branch_equals(left: Branch | None, right: Branch | None) -> bool:
    if left is right:
        return True
    if left is None or right is None:
        return False
    return (
        left.type == right.type
        and left.tip_sha == right.tip_sha
        and (left.remote or None) == (right.remote or None)
        and left.upstream == right.upstream
    )
