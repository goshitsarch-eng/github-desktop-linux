"""Text shown by the main window: banners, empty states, reorder announcements.

The window itself is QML (``ui/qml/Main.qml``); the strings and the rules for
choosing between them stay here in Python where the parity tests can reach
them.
"""

from __future__ import annotations

from ..models import AppFileStatusKind, BannerType, ComparisonMode, HistoryTabMode

STATUS_CLASS = {
    AppFileStatusKind.NEW: "file-status-new",
    AppFileStatusKind.UNTRACKED: "file-status-new",
    AppFileStatusKind.MODIFIED: "file-status-modified",
    AppFileStatusKind.DELETED: "file-status-deleted",
    AppFileStatusKind.RENAMED: "file-status-renamed",
    AppFileStatusKind.COPIED: "file-status-renamed",
    AppFileStatusKind.CONFLICTED: "file-status-conflicted",
}
CONFLICT_BANNER_KINDS = {
    BannerType.MERGE_CONFLICTS_FOUND,
    BannerType.REBASE_CONFLICTS_FOUND,
    BannerType.CHERRY_PICK_CONFLICTS_FOUND,
    BannerType.CONFLICTS_FOUND,
}
SUCCESS_BANNER_KINDS = {
    BannerType.SUCCESSFUL_MERGE,
    BannerType.SUCCESSFUL_REBASE,
    BannerType.SUCCESSFUL_CHERRY_PICK,
    BannerType.SUCCESSFUL_SQUASH,
    BannerType.SUCCESSFUL_REORDER,
}


def _banner_noun(count: int) -> str:
    return "commit" if count == 1 else "commits"


def keyboard_reorder_intro_message(count: int) -> str:
    """Desktop commit-list aria live copy before an insertion point is chosen."""
    plural = "s" if count != 1 else ""
    return (
        f"Use the Up and Down arrow keys to choose a new location for the selected commit{plural}, "
        "then press Enter to confirm or Escape to cancel."
    )


def keyboard_reorder_insert_message(count: int, row: int, total: int) -> str:
    """Desktop `Press Enter to insert the selected commit(s) before commit N`."""
    plural = "s" if count != 1 else ""
    insertion_point = f"before commit {row + 1}" if row < total else f"after commit {row}"
    return (
        f"Press Enter to insert the selected commit{plural} {insertion_point} or Escape to cancel."
    )


KEYBOARD_REORDER_MOVE_HINT = "Use ↑ ↓ to choose a new location."
KEYBOARD_REORDER_CONFIRM_HINT = "Press ⏎ to confirm."
REPOSITORY_MISSING_TITLE = "Can't find this repository"
NO_HISTORY = "No history"
NO_COMMITS_TO_LIST = "No commits to list"
NO_COMMIT_SELECTED = "No commit selected"
NoCommitSelected = NO_COMMIT_SELECTED


def commit_list_empty_message(
    *,
    history_mode: HistoryTabMode,
    comparison_mode: ComparisonMode | None = None,
    branch_name: str | None = None,
) -> str:
    """Desktop `CommitList` `emptyListMessage` from `compare.tsx`."""
    if history_mode != HistoryTabMode.COMPARE:
        return NO_HISTORY
    name = branch_name or ""
    # Desktop defaults Compare to Ahead; Behind is the only other comparisonMode.
    if comparison_mode == ComparisonMode.BEHIND:
        return f"Your branch is up to date with the compared branch ({name})"
    return f"The compared branch ({name}) is up to date with your branch"


def format_banner_text(kind: BannerType, banner) -> str:
    """Desktop success/conflict banner copy."""
    if kind == BannerType.SUCCESSFUL_MERGE:
        if banner.their_branch:
            return f"Successfully merged {banner.their_branch} into {banner.our_branch or ''}"
        return f"Successfully merged into {banner.our_branch or ''}"
    if kind == BannerType.SUCCESSFUL_REBASE:
        if banner.target_branch and banner.their_branch:
            return f"Successfully rebased {banner.target_branch} onto {banner.their_branch}"
        return f"Successfully rebased {banner.target_branch or ''}"
    if kind == BannerType.SUCCESSFUL_CHERRY_PICK:
        target = banner.target_branch or ""
        return f"Successfully copied {banner.count} {_banner_noun(banner.count)} to {target}."
    if kind == BannerType.SUCCESSFUL_SQUASH:
        return f"Successfully squashed {banner.count} {_banner_noun(banner.count)}."
    if kind == BannerType.SUCCESSFUL_REORDER:
        return f"Successfully reordered {banner.count} {_banner_noun(banner.count)}."
    if kind == BannerType.MERGE_CONFLICTS_FOUND:
        return f"Resolve conflicts and commit to merge into {banner.our_branch or ''}."
    if kind == BannerType.REBASE_CONFLICTS_FOUND:
        return f"Resolve conflicts to continue rebasing {banner.target_branch or ''}."
    if kind == BannerType.CHERRY_PICK_CONFLICTS_FOUND:
        return f"Resolve conflicts to continue cherry-picking onto {banner.target_branch or ''}."
    if kind == BannerType.CONFLICTS_FOUND:
        op = banner.operation_description or "the operation"
        if banner.target_branch:
            return f"Resolve conflicts to continue {op} {banner.target_branch}."
        return f"Resolve conflicts to continue {op}."
    if kind == BannerType.BRANCH_ALREADY_UP_TO_DATE:
        ours = banner.our_branch or ""
        if banner.their_branch:
            return f"{ours} is already up to date with {banner.their_branch}"
        return f"{ours} is already up to date"
    if kind == BannerType.CHERRY_PICK_UNDONE:
        target = banner.target_branch or ""
        return (
            f"Cherry-pick undone. Successfully removed the {banner.count} copied "
            f"{_banner_noun(banner.count)} from {target}."
        )
    if kind == BannerType.SQUASH_UNDONE:
        return f"Squash of {banner.count} {_banner_noun(banner.count)} undone."
    if kind == BannerType.REORDER_UNDONE:
        return f"Reorder of {banner.count} {_banner_noun(banner.count)} undone."
    mapping = {
        BannerType.OPEN_THANK_YOU_CARD: "The Desktop team would like to thank you for your contributions.",
        BannerType.DETACHED_HEAD: "You are in a detached HEAD state. Create a branch to keep your work.",
        BannerType.ACCESSIBILITY_SETTINGS: (
            "Check out the new accessibility settings to control the visibility of "
            "the link underlines and diff check marks."
        ),
        BannerType.OS_VERSION_NO_LONGER_SUPPORTED: (
            "This operating system is no longer supported. Software updates have been disabled."
        ),
    }
    return mapping.get(kind, kind.value)
