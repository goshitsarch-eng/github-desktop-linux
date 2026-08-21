"""Push/pull/fetch toolbar presentation matching Desktop's PushPullButton."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ForcePushBranchState


# Desktop octicons: upload, arrowUp, arrowDown, syncClockwise, forcePush.
ICON_PUBLISH = "network-transmit-symbolic"
ICON_PUSH = "go-up-symbolic"
ICON_PULL = "go-down-symbolic"
ICON_FETCH = "view-refresh-symbolic"
ICON_FORCE_PUSH = "go-up-symbolic"


@dataclass(frozen=True)
class PushPullPresentation:
    """What the toolbar push/pull control should show and do."""

    label: str
    action: str
    menu_items: tuple[str, ...]
    sensitive: bool = True
    remote_name: str | None = None
    icon: str = ICON_FETCH


def format_relative_past(seconds: float) -> str:
    """RelativeTime-style elapsed text for a duration that already elapsed."""
    from .format_relative import format_relative

    if abs(seconds) < 60:
        return "just now"
    return format_relative(-abs(seconds) * 1000)


def format_last_fetched(ts: float | None, *, now: float | None = None) -> str:
    """Desktop subtitle: 'Last fetched just now' / 'Never fetched'."""
    if ts is None:
        return "Never fetched"
    import time

    current = time.time() if now is None else now
    return f"Last fetched {format_relative_past(current - ts)}"


def format_commit_relative_time(when, *, now=None) -> str:
    """RelativeTime for commit list items (`just now`, `3 minutes ago`, …)."""
    from datetime import datetime, timezone

    from .format_relative import get_relative_time_info_from_date

    current = now or datetime.now(timezone.utc)
    return get_relative_time_info_from_date(when, only_relative=True, now=current)["relative_text"]


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
        return PushPullPresentation(
            "Publish repository", "push", (), remote_name=None, icon=ICON_PUBLISH
        )
    if not current_tip:
        return PushPullPresentation(
            "Publish branch", "none", (), sensitive=False, remote_name=remote_name, icon=ICON_PUBLISH
        )
    if not current_branch:
        return PushPullPresentation(
            "Publish branch", "none", (), sensitive=False, remote_name=remote_name, icon=ICON_PUBLISH
        )
    if not has_upstream:
        return PushPullPresentation(
            "Publish branch", "push", ("fetch",), remote_name=remote_name, icon=ICON_PUBLISH
        )
    if force_push == ForcePushBranchState.RECOMMENDED:
        return PushPullPresentation(
            "Force push", "force-push", ("fetch",), remote_name=remote_name, icon=ICON_FORCE_PUSH
        )
    if behind > 0:
        menu: tuple[str, ...] = ("fetch",)
        if force_push != ForcePushBranchState.NOT_AVAILABLE:
            menu = ("fetch", "force-push")
        if pull_with_rebase:
            label = f"Pull {behind} with rebase"
        else:
            label = f"Pull {behind}"
        return PushPullPresentation(label, "pull", menu, remote_name=remote_name, icon=ICON_PULL)
    if ahead > 0 or tag_count > 0:
        extra = ""
        if ahead > 0 and tag_count:
            extra = f" and {tag_count} tag" + ("s" if tag_count != 1 else "")
            label = f"Push {ahead}{extra}"
        elif ahead > 0:
            label = f"Push {ahead}"
        else:
            label = "Push 1 tag" if tag_count == 1 else f"Push {tag_count} tags"
        return PushPullPresentation(label, "push", ("fetch",), remote_name=remote_name, icon=ICON_PUSH)
    return PushPullPresentation(
        f"Fetch {remote_name}", "fetch", (), remote_name=remote_name, icon=ICON_FETCH
    )
