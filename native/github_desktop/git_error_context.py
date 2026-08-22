"""Desktop `GitErrorContext` and `ErrorWithMetadata` for error-dialog titles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import Branch, RetryAction, RetryActionType
from .regex import get_file_from_exceeds_error

COPILOT_PLANS_URL = "https://github.com/features/copilot/plans"
LFS_DOCS_URL = "https://gh.io/lfs"


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
    git_error: str | None = None,
    copilot_quota: bool = False,
) -> str:
    """Desktop `AppError.getTitle` for quota, file-size, clone, push, and create-repository."""
    # Copilot quota and oversized-push titles win over retry-action copy.
    if copilot_quota:
        return "Quota exceeded"
    if git_error == "PushWithFileSizeExceedingLimit":
        return "File size limit exceeded"
    if title:
        return title
    if retry_clone:
        return "Clone failed"
    retry_type = retry_action.type if isinstance(retry_action, RetryAction) else retry_action
    if retry_type in {RetryActionType.PUSH, "push", "Push"}:
        return "Failed to push"
    if retry_type in {RetryActionType.CLONE, "clone", "Clone"}:
        return "Clone failed"
    kind = None
    if isinstance(git_context, GitErrorContext):
        kind = git_context.kind
    elif isinstance(git_context, dict):
        kind = git_context.get("kind")
    if kind == "create-repository":
        return "Failed creating repository"
    return "Error"


def format_app_error_body(
    message: str,
    *,
    git_error: str | None = None,
    stderr: str = "",
    copilot_quota: bool = False,
) -> str:
    """Desktop `AppError.renderErrorMessage` as AlertDialog body text."""
    if git_error == "PushWithFileSizeExceedingLimit":
        files = get_file_from_exceeds_error(stderr)
        parts = [message]
        if files:
            parts.append("Files that exceed the limit\n" + "\n".join(files))
        parts.append(
            f"See {LFS_DOCS_URL} for more information on managing large files on GitHub"
        )
        return "\n\n".join(parts)
    if copilot_quota:
        return (
            f"{message}\n\n"
            f"Upgrade to increase your limit.\n"
            f"{COPILOT_PLANS_URL}"
        )
    return message
