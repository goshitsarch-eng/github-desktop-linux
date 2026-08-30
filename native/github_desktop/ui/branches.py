"""Searchable Branches / Pull Requests foldout matching GitHub Desktop."""

from __future__ import annotations

from collections.abc import Callable

from ..models import Branch
from ..push_pull import format_commit_relative_time


def generate_branch_context_menu_items(
    name: str,
    *,
    is_local: bool,
    on_rename: Callable[[str], None] | None = None,
    on_delete: Callable[[str], None] | None = None,
    on_view_pull_request: Callable[[], None] | None = None,
) -> list:
    """Desktop `generateBranchContextMenuItems` (toolbar + branch list)."""
    items: list = []
    if on_rename is not None:
        items.append(("Rename…", lambda: on_rename(name), is_local))
    items.append(("Copy branch name", lambda: copy_text(name), True))
    if on_view_pull_request is not None:
        items.append(("View Pull Request on GitHub", on_view_pull_request, True))
    items.append(None)
    if on_delete is not None:
        items.append(("Delete…", lambda: on_delete(name), True))
    return items


def generate_pull_request_context_menu_items(
    on_view_pull_request: Callable[[], None] | None = None,
) -> list:
    """Desktop `generatePullRequestContextMenuItems`."""
    items: list = []
    if on_view_pull_request is not None:
        items.append(("View Pull Request on GitHub", on_view_pull_request, True))
    return items


def branch_group_label(identifier: str) -> str:
    """Desktop Linux `getGroupLabel`."""
    if identifier == "default":
        return "Default branch"
    if identifier == "recent":
        return "Recent branches"
    return "Other branches"


WOULD_YOU_LIKE_TO = "Would you like to "
CREATE_A_NEW_BRANCH_LINK = "create a new branch"
AND_GET_GOING_ON_YOUR_NEXT_PROJECT = " and get going on your next project?"
CREATE_A_PULL_REQUEST_LINK = "create a pull request"
FROM_THE_CURRENT_BRANCH = " from the current branch?"


def no_pull_requests_cta_parts(*, is_on_default_branch: bool) -> tuple[str, str, str]:
    """Desktop `renderCallToAction` prefix, LinkButton label, suffix."""
    if is_on_default_branch:
        return (WOULD_YOU_LIKE_TO, CREATE_A_NEW_BRANCH_LINK, AND_GET_GOING_ON_YOUR_NEXT_PROJECT)
    return (WOULD_YOU_LIKE_TO, CREATE_A_PULL_REQUEST_LINK, FROM_THE_CURRENT_BRANCH)


def no_pull_requests_cta_sentence(*, is_on_default_branch: bool) -> str:
    prefix, link, suffix = no_pull_requests_cta_parts(is_on_default_branch=is_on_default_branch)
    return f"{prefix}{link}{suffix}"


def group_branches(
    branches: list[Branch],
    *,
    current: str | None,
    default_name: str | None,
    recent_names: list[str],
) -> list[tuple[str, list[Branch]]]:
    """Desktop `groupBranches` with Linux `getGroupLabel` (fork remotes stay hidden)."""
    by_name = {b.name: b for b in branches}
    used: set[str] = set()
    groups: list[tuple[str, list[Branch]]] = []
    if default_name and default_name in by_name:
        groups.append((branch_group_label("default"), [by_name[default_name]]))
        used.add(default_name)
    recent: list[Branch] = []
    for name in recent_names:
        branch = by_name.get(name)
        if branch and name not in used:
            recent.append(branch)
            used.add(name)
    if recent:
        groups.append((branch_group_label("recent"), recent))
    others = [
        branch
        for branch in branches
        if branch.name not in used and not branch.is_desktop_fork_remote_branch
    ]
    if others:
        groups.append((branch_group_label("other"), others))
    if current:
        for _title, items in groups:
            items.sort(key=lambda b: (0 if b.name == current else 1, b.name.lower()))
    return groups


def compare_placeholder_text(*, has_non_fork_branch: bool, comparing: bool) -> str:
    """Desktop `getPlaceholderText` (Linux). Compare mode uses Filter branches."""
    if not has_non_fork_branch:
        return "No branches to compare"
    if not comparing:
        return "Select branch to compare…"
    return "Filter branches"


groupBranches = group_branches
getGroupLabel = branch_group_label
getPlaceholderText = compare_placeholder_text


def _relative_iso(value: str) -> str:
    if not value:
        return ""
    from datetime import datetime, timezone

    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return format_commit_relative_time(when)


def _absolute_iso(value: str) -> str:
    """Desktop RelativeTime tooltip: `formatDate` with dateStyle full / timeStyle short."""
    if not value:
        return ""
    from datetime import datetime, timezone

    from ..format_date import format_date

    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return format_date(when)
