"""Branch pushability from GitHub's `push_control` API (Desktop `lib/helpers/push-control`)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PushControl:
    """Desktop `IAPIPushControl`."""

    required_status_checks: list[str] = field(default_factory=list)
    required_approving_review_count: int = 0
    allow_actor: bool | None = True
    pattern: str | None = None
    required_signatures: bool = False
    required_linear_history: bool = False
    allow_deletions: bool | None = True
    allow_force_pushes: bool | None = True
    required_conversation_resolution: bool = False
    lock_branch: bool = False


def default_push_control() -> PushControl:
    """Used when `fetchPushControl` fails: assume the user can push."""
    return PushControl()


def is_branch_pushable(push_control: PushControl) -> bool:
    """Desktop `isBranchPushable`.

    `allow_actor !== false` so a missing/renamed API field defaults to allowing
    the push. Required checks or approving reviews still block pushing.
    """
    required = push_control.required_status_checks
    required_count = len(required) if isinstance(required, list) else 0
    no_merge_requirements = required_count == 0 and push_control.required_approving_review_count == 0
    return push_control.allow_actor is not False and no_merge_requirements
