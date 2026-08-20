"""Push/pull/fetch toolbar presentation matching Desktop's PushPullButton."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ForcePushBranchState


@dataclass(frozen=True)
class PushPullPresentation:
    """What the toolbar push/pull control should show and do."""

    label: str
    action: str
    menu_items: tuple[str, ...]
    sensitive: bool = True
    remote_name: str | None = None


def format_relative_past(seconds: float) -> str:
    """English relative time for a duration that already elapsed."""
    sec = round(abs(seconds))
    if sec < 45:
        return "just now"
    minutes = round(sec / 60)
    if minutes < 45:
        return "a minute ago" if minutes == 1 else f"{minutes} minutes ago"
    hours = round(minutes / 60)
    if hours < 24:
        return "an hour ago" if hours == 1 else f"{hours} hours ago"
    days = round(hours / 24)
    if days < 30:
        return "a day ago" if days == 1 else f"{days} days ago"
    months = round(days / 30)
    if months < 18:
        return "a month ago" if months == 1 else f"{months} months ago"
    years = round(months / 12)
    return "a year ago" if years == 1 else f"{years} years ago"


def format_last_fetched(ts: float | None, *, now: float | None = None) -> str:
    """Desktop subtitle: 'Last fetched just now' / 'Never fetched'."""
    if ts is None:
        return "Never fetched"
    import time

    current = time.time() if now is None else now
    return f"Last fetched {format_relative_past(current - ts)}"


def describe_push_pull(
    *,
    remote_name: str | None,
    current_branch: str | None,
    current_tip: str | None,
    has_upstream: bool,
    ahead: int,
    behind: int,
    tag_count: int,
    force_push: ForcePushBranchState,
    pull_with_rebase: bool = False,
) -> PushPullPresentation:
    """Mirror Desktop `PushPullButton.renderButton` branching."""
    if remote_name is None:
        return PushPullPresentation("Publish repository", "push", (), remote_name=None)
    if not current_tip:
        return PushPullPresentation("Publish branch", "none", (), sensitive=False, remote_name=remote_name)
    if not current_branch:
        return PushPullPresentation("Publish branch", "none", (), sensitive=False, remote_name=remote_name)
    if not has_upstream:
        return PushPullPresentation("Publish branch", "push", ("fetch",), remote_name=remote_name)
    if force_push == ForcePushBranchState.RECOMMENDED:
        return PushPullPresentation("Force push", "force-push", ("fetch",), remote_name=remote_name)
    if behind > 0:
        menu: tuple[str, ...] = ("fetch",)
        if force_push != ForcePushBranchState.NOT_AVAILABLE:
            menu = ("fetch", "force-push")
        if pull_with_rebase:
            label = f"Pull {behind} with rebase"
        else:
            label = f"Pull {behind}"
        return PushPullPresentation(label, "pull", menu, remote_name=remote_name)
    if ahead > 0 or tag_count > 0:
        extra = ""
        if ahead > 0 and tag_count:
            extra = f" and {tag_count} tag" + ("s" if tag_count != 1 else "")
            label = f"Push {ahead}{extra}"
        elif ahead > 0:
            label = f"Push {ahead}"
        else:
            label = "Push 1 tag" if tag_count == 1 else f"Push {tag_count} tags"
        return PushPullPresentation(label, "push", ("fetch",), remote_name=remote_name)
    return PushPullPresentation(f"Fetch {remote_name}", "fetch", (), remote_name=remote_name)
