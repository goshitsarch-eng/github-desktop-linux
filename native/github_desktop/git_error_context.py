"""Desktop `GitErrorContext` and `ErrorWithMetadata` for error-dialog titles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Branch, RetryAction, RetryActionType


@dataclass
class GitErrorContext:
    """Desktop `GitErrorContext` attached to failable git operations."""

    kind: str
    their_branch: str | None = None
    current_branch: str | None = None
    branch_to_checkout: Branch | None = None


class ErrorWithMetadata(Exception):
    """Desktop `ErrorWithMetadata`: underlying git error plus retry/context."""

    def __init__(
        self,
        error: BaseException,
        *,
        git_context: GitErrorContext | None = None,
        retry_action: RetryAction | None = None,
        repository: Any | None = None,
        background_task: bool = False,
    ) -> None:
        super().__init__(str(error))
        self.underlying_error = error
        self.git_context = git_context
        self.retry_action = retry_action
        self.repository = repository
        self.background_task = background_task


def error_dialog_title(
    *,
    git_context: GitErrorContext | dict[str, Any] | None = None,
    retry_action: RetryAction | RetryActionType | str | None = None,
    title: str | None = None,
    retry_clone: bool = False,
) -> str:
    """Desktop `AppError.getTitle` for clone, push, and create-repository failures."""
    if title:
        return title
    if retry_clone:
        return "Clone failed"
    kind = None
    if isinstance(git_context, GitErrorContext):
        kind = git_context.kind
    elif isinstance(git_context, dict):
        kind = git_context.get("kind")
    if kind == "create-repository":
        return "Failed creating repository"
    retry_type = retry_action.type if isinstance(retry_action, RetryAction) else retry_action
    if retry_type in {RetryActionType.PUSH, "push", "Push"}:
        return "Failed to push"
    if retry_type in {RetryActionType.CLONE, "clone", "Clone"}:
        return "Clone failed"
    return "Error"
