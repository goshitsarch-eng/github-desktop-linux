"""Desktop-parity multi-commit operation wizard: merge, squash, rebase, cherry-pick, conflicts."""

from __future__ import annotations

import os
import re
from pathlib import Path

from ..models import ComputedAction, GitStatusEntry, MergeTreeResult, MultiCommitOperationKind
from ..truncate import truncate_with_ellipsis

MERGE_OPTIONS = (
    (
        MultiCommitOperationKind.MERGE,
        "Create a merge commit",
        "The commits from the selected branch will be added to the current branch via a merge commit.",
    ),
    (
        MultiCommitOperationKind.SQUASH,
        "Squash and merge",
        "The commits in the selected branch will be combined into one commit in the current branch.",
    ),
    (
        MultiCommitOperationKind.REBASE,
        "Rebase",
        "The commits from the selected branch will be rebased and added to the current branch.",
    ),
)


def get_merge_options() -> tuple:
    """Desktop `getMergeOptions()` labels for the compare Merge CTA dropdown."""
    return MERGE_OPTIONS


def editor_button_string(editor_name: str | None) -> str:
    """Desktop `editorButtonString`."""
    return f"Open in {editor_name or 'editor'}"


def editor_button_tooltip(editor_name: str | None) -> str | None:
    """Desktop `editorButtonTooltip` (Linux)."""
    if editor_name:
        return None
    return "No editor configured in Options > Advanced"


def manual_conflict_status_copy(
    status,
    *,
    our_branch: str | None,
    their_branch: str | None,
) -> str:
    """Desktop unmerged-file `manualConflictString` / deleted-file copy."""
    us, them = getattr(status, "us", None), getattr(status, "them", None)
    if us != GitStatusEntry.DELETED and them != GitStatusEntry.DELETED:
        return "Manual conflict"
    target_branch = "target branch"
    if us == GitStatusEntry.DELETED and our_branch:
        target_branch = our_branch
    if them == GitStatusEntry.DELETED and their_branch:
        target_branch = their_branch
    return f"File does not exist on {target_branch}."


def merge_cta_message(
    kind: MultiCommitOperationKind | str,
    current: str,
    compare: str,
    commit_count: int,
    action: ComputedAction | None,
    conflicted_files: int = 0,
) -> tuple[str, bool]:
    """Copy from Desktop `merge-call-to-action-with-conflicts.tsx`.

    Returns ``(message, can_proceed)``. Loading uses
    ``Checking for ability to merge automatically…`` (or squash/rebase).
    Invalid merge: ``Unable to merge unrelated histories in this repository``.
    Conflicts: ``There will be N conflicted file(s) when merging …``.
    """
    if isinstance(kind, MultiCommitOperationKind):
        op = kind.value.lower()
        is_rebase = kind == MultiCommitOperationKind.REBASE
    else:
        op = str(kind).lower()
        is_rebase = op == "rebase"
    if action is None or action == ComputedAction.LOADING:
        return f"Checking for ability to {op} automatically…", False
    if action == ComputedAction.INVALID:
        if is_rebase:
            return "Unable to start rebase. Check you have chosen a valid branch.", False
        return "Unable to merge unrelated histories in this repository", False
    if commit_count <= 0:
        return "", False
    if is_rebase:
        if action != ComputedAction.CLEAN:
            return "", False
        noun = "commit" if commit_count == 1 else "commits"
        return (
            f"This will update {current} by applying its {commit_count} {noun} on top of {compare}",
            True,
        )
    if action == ComputedAction.CONFLICTS:
        noun = "file" if conflicted_files == 1 else "files"
        return (
            f"There will be {conflicted_files} conflicted {noun} when merging {compare} into {current}",
            True,
        )
    noun = "commit" if commit_count == 1 else "commits"
    return (
        f"This will merge {commit_count} {noun} from {compare} into {current}",
        True,
    )


def merge_cta_can_proceed(
    kind: MultiCommitOperationKind | str,
    commit_count: int,
    merge_tree: MergeTreeResult | None,
) -> bool:
    """Desktop `isUpdateBranchDisabled` inverted: rebase needs Clean; merge blocks Invalid."""
    if commit_count <= 0:
        return False
    if isinstance(kind, str):
        is_rebase = kind.lower() == "rebase"
    else:
        is_rebase = kind == MultiCommitOperationKind.REBASE
    if merge_tree is None:
        return False
    if is_rebase:
        return merge_tree.kind == ComputedAction.CLEAN
    return merge_tree.kind != ComputedAction.INVALID


def can_start_operation(
    selected_name: str | None,
    current_name: str | None,
    commit_count: int | None,
    status_kind: ComputedAction | None,
) -> bool:
    if not selected_name or selected_name == current_name:
        return False
    if status_kind == ComputedAction.LOADING:
        return False
    if status_kind == ComputedAction.CONFLICTS:
        return True
    if commit_count is None or commit_count == 0:
        return False
    return status_kind != ComputedAction.INVALID


def _truncate(name: str, limit: int = 40) -> str:
    """Desktop `truncateWithEllipsis` for choose-branch titles."""
    return truncate_with_ellipsis(name, limit)


def _choose_title(kind: str, current: str) -> str:
    name = _truncate(current)
    if kind == MultiCommitOperationKind.SQUASH:
        return f"Squash and merge into {name}"
    if kind == MultiCommitOperationKind.REBASE:
        return f"Rebase {name}"
    return f"Merge into {name}"


def _start_label(kind: str, current: str | None) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Rebase"
    if kind == MultiCommitOperationKind.SQUASH:
        return "Squash and merge"
    if current:
        return f"Merge into {current}"
    return "Merge"


def _merge_preview_text(
    current: str,
    other: str,
    commit_count: int,
    status: ComputedAction,
    conflicted: int,
) -> str:
    if status == ComputedAction.LOADING:
        return "Checking for ability to merge automatically..."
    if status == ComputedAction.INVALID:
        return "Unable to merge unrelated histories in this repository"
    if status == ComputedAction.CONFLICTS:
        noun = "file" if conflicted == 1 else "files"
        return f"There will be {conflicted} conflicted {noun} when merging {other} into {current}"
    if commit_count == 0:
        return f"{current} is already up to date with {other}"
    noun = "commit" if commit_count == 1 else "commits"
    return f"This will merge {commit_count} {noun} from {other} into {current}"


def _rebase_preview_text(
    current: str,
    base: str,
    ahead: int,
    behind: int,
    status: ComputedAction,
) -> str:
    if status == ComputedAction.LOADING:
        return "Checking for ability to rebase automatically…"
    if status == ComputedAction.INVALID:
        return "Unable to start rebase. Check you have chosen a valid branch."
    if behind > 0 and ahead <= 0:
        noun = "commit" if behind == 1 else "commits"
        return f"This will fast-forward {current} by {behind} {noun} to match {base}"
    if behind > 0 and ahead > 0:
        noun = "commit" if ahead == 1 else "commits"
        return f"This will update {current} by applying its {ahead} {noun} on top of {base}"
    return f"{current} is already up to date with {base}"


def _their_branch(repo, status) -> str:
    if status.rebase_internal_state:
        return status.rebase_internal_state.target_branch
    merge_msg = os.path.join(repo.path, ".git", "MERGE_MSG")
    try:
        first = Path(merge_msg).read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return "theirs"
    match = re.search(r"Merge (?:remote-tracking )?branch '([^']+)'", first)
    if match:
        return match.group(1).split("/")[-1]
    return "theirs"


def _continue_label(kind: str) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Continue rebase"
    if kind == MultiCommitOperationKind.CHERRY_PICK:
        return "Continue cherry-pick"
    return "Commit merge"


def _abort_label(kind: str) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Abort rebase"
    if kind == MultiCommitOperationKind.CHERRY_PICK:
        return "Abort cherry-pick"
    return "Abort merge"
