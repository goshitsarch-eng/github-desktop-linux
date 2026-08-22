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

# Desktop Linux `refreshAfterCheckout` / push-pull refresh (Darwin: Refreshing Repository).
REFRESHING_REPOSITORY = "Refreshing repository"
FAST_FORWARDING_BRANCHES = "Fast-forwarding branches"
CHECKING_OUT = "Checking out"
HANG_ON = "Hang on…"
PUBLISH_THIS_REPOSITORY_TO_GITHUB = "Publish this repository to GitHub"
PUBLISH_THIS_BRANCH_TO_GITHUB = "Publish this branch to GitHub"
PUBLISH_THIS_BRANCH_TO_THE_REMOTE = "Publish this branch to the remote"
CANNOT_PUBLISH_NO_COMMITS = "Cannot publish: no commits"
CANNOT_PUBLISH_DETACHED_HEAD = "Cannot publish detached HEAD"
REBASE_IN_PROGRESS = "Rebase in progress"
PUSH_PULL_BUTTON_STATE_ID = "push-pull-button-state"


@dataclass(frozen=True)
class PushPullPresentation:
    """What the toolbar push/pull control should show and do."""

    label: str
    action: str
    menu_items: tuple[str, ...]
    sensitive: bool = True
    remote_name: str | None = None
    icon: str = ICON_FETCH
    description: str = ""
    ahead_behind: str = ""


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


def render_ahead_behind(*, ahead: int, behind: int, num_tags_to_push: int = 0) -> str:
    """Desktop `PushPullButton.renderAheadBehind` — tags count as ahead."""
    numTagsToPush = num_tags_to_push
    up = ahead + numTagsToPush
    parts: list[str] = []
    if up:
        parts.append(f"↑{up}")
    if behind:
        parts.append(f"↓{behind}")
    return " ".join(parts)


renderAheadBehind = render_ahead_behind


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
    last_fetched: str = "Never fetched",
    rebase_in_progress: bool = False,
    is_github: bool = True,
) -> PushPullPresentation:
    """Mirror Desktop `PushPullButton.renderButton` branching."""
    badge = render_ahead_behind(ahead=ahead, behind=behind, num_tags_to_push=tag_count)
    if remote_name is None:
        return PushPullPresentation(
            "Publish repository",
            "push",
            (),
            remote_name=None,
            icon=ICON_PUBLISH,
            description=PUBLISH_THIS_REPOSITORY_TO_GITHUB,
        )
    if not current_tip:
        return PushPullPresentation(
            "Publish branch",
            "none",
            (),
            sensitive=False,
            remote_name=remote_name,
            icon=ICON_PUBLISH,
            description=CANNOT_PUBLISH_NO_COMMITS,
        )
    if not current_branch:
        return PushPullPresentation(
            "Publish branch",
            "none",
            (),
            sensitive=False,
            remote_name=remote_name,
            icon=ICON_PUBLISH,
            description=REBASE_IN_PROGRESS if rebase_in_progress else CANNOT_PUBLISH_DETACHED_HEAD,
        )
    if not has_upstream:
        return PushPullPresentation(
            "Publish branch",
            "push",
            ("fetch",),
            remote_name=remote_name,
            icon=ICON_PUBLISH,
            description=(
                PUBLISH_THIS_BRANCH_TO_GITHUB if is_github else PUBLISH_THIS_BRANCH_TO_THE_REMOTE
            ),
        )
    if force_push == ForcePushBranchState.RECOMMENDED:
        return PushPullPresentation(
            f"Force push {remote_name}",
            "force-push",
            ("fetch",),
            remote_name=remote_name,
            icon=ICON_FORCE_PUSH,
            description=last_fetched,
            ahead_behind=badge,
        )
    if behind > 0:
        menu: tuple[str, ...] = ("fetch",)
        if force_push != ForcePushBranchState.NOT_AVAILABLE:
            menu = ("fetch", "force-push")
        if pull_with_rebase:
            label = f"Pull {remote_name} with rebase"
        else:
            label = f"Pull {remote_name}"
        return PushPullPresentation(
            label,
            "pull",
            menu,
            remote_name=remote_name,
            icon=ICON_PULL,
            description=last_fetched,
            ahead_behind=badge,
        )
    if ahead > 0 or tag_count > 0:
        return PushPullPresentation(
            f"Push {remote_name}",
            "push",
            ("fetch",),
            remote_name=remote_name,
            icon=ICON_PUSH,
            description=last_fetched,
            ahead_behind=badge,
        )
    return PushPullPresentation(
        f"Fetch {remote_name}",
        "fetch",
        (),
        remote_name=remote_name,
        icon=ICON_FETCH,
        description=last_fetched,
    )


def network_progress_chrome(
    *,
    title: str,
    description: str = "",
    value: float = 0.0,
) -> tuple[str, str, str]:
    """Desktop `PushPullButton.progressButton`: label, description, tooltip."""
    subtitle = description or HANG_ON
    percent = int(round(value * 100)) if value > 0 else 0
    label = f"{title} {percent}%" if percent else title
    return label, subtitle, subtitle


progressButton = network_progress_chrome
