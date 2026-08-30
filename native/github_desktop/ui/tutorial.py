"""Onboarding tutorial panel matching GitHub Desktop's Get started steps."""

from __future__ import annotations

from ..models import TutorialStep

ORDERED = [
    TutorialStep.PICK_EDITOR,
    TutorialStep.CREATE_BRANCH,
    TutorialStep.EDIT_FILE,
    TutorialStep.MAKE_COMMIT,
    TutorialStep.PUSH_BRANCH,
    TutorialStep.OPEN_PULL_REQUEST,
]
NUDGE_ARROW = "nudge-arrow"
NUDGE_ARROW_UP = "nudge-arrow-up"
NUDGE_ARROW_LEFT = "nudge-arrow-left"
NUDGE_ARROW_Z_INDEX = 16
NUDGE_ARROW_DELAY_MS = 6000.0
NUDGE_ARROW_DURATION_MS = 2000.0


def shouldNudge(step: TutorialStep | None, target: str = "branch") -> bool:
    """Desktop `shouldNudge` on BranchDropdown (`CreateBranch`) and PushPullButton (`PushBranch`)."""
    if step is None:
        return False
    if target in {"branch", "CreateBranch", "branch-dropdown"}:
        return step == TutorialStep.CREATE_BRANCH
    if target in {"push", "PushBranch", "push-pull"}:
        return step == TutorialStep.PUSH_BRANCH
    return False


should_nudge = shouldNudge


def shouldNudgeToCommit(step: TutorialStep | None) -> bool:
    """Desktop `shouldNudgeToCommit` when `currentTutorialStep === TutorialStep.MakeCommit`."""
    return step == TutorialStep.MAKE_COMMIT


should_nudge_to_commit = shouldNudgeToCommit


def publishBranchButton(
    *,
    remote_name: str | None,
    current_branch: str | None,
    current_tip: str | None,
    has_upstream: bool,
    progress: bool = False,
) -> bool:
    """True when Desktop `PushPullButton.publishBranchButton` is the live chrome (the only push nudge host)."""
    if progress:
        return False
    return bool(remote_name and current_branch and current_tip and not has_upstream)


def nudge_arrow_frame(elapsed_ms: float, *, direction: str = "up") -> tuple[float, int]:
    """Opacity and inset for Desktop `pointup` / `pointleft` keyframes."""
    far = 55 if direction == "up" else 65
    near = 40 if direction == "up" else 50
    if elapsed_ms < NUDGE_ARROW_DELAY_MS:
        return 0.0, far
    pct = ((elapsed_ms - NUDGE_ARROW_DELAY_MS) % NUDGE_ARROW_DURATION_MS) / NUDGE_ARROW_DURATION_MS * 100.0
    keys = (
        (0.0, 0.0, far),
        (20.0, 0.0, far),
        (30.0, 1.0, near),
        (40.0, 1.0, near),
        (50.0, 1.0, far),
        (60.0, 1.0, near),
        (70.0, 1.0, near),
        (80.0, 0.0, far),
        (100.0, 0.0, far),
    )
    for index in range(len(keys) - 1):
        p0, o0, d0 = keys[index]
        p1, o1, d1 = keys[index + 1]
        if pct <= p1:
            span = p1 - p0
            t = 0.0 if span <= 0 else (pct - p0) / span
            return o0 + (o1 - o0) * t, int(round(d0 + (d1 - d0) * t))
    return 0.0, far


def nudge_arrow_state(*, should_nudge: bool = False, direction: str = "up") -> str:
    """Desktop `classNames('nudge-arrow', { 'nudge-arrow-up': shouldNudge })`.

    QML binds the returned state name, so the animation lives in
    ``ui/qml/NudgeArrow.qml`` rather than in a stylesheet.
    """
    if not should_nudge:
        return NUDGE_ARROW
    if direction == "left":
        return NUDGE_ARROW_LEFT
    return NUDGE_ARROW_UP


# Desktop's "Get started" steps, in order, with the copy the panel shows.
TUTORIAL_HEADING = "Let's get started!"
TUTORIAL_DONE_HEADING = "You're done!"
TUTORIAL_DONE_SUMMARY = (
    "You've learned the basics of using GitHub Desktop. Explore projects on GitHub, "
    "or start something of your own."
)
EXPLORE_GITHUB = "Explore GitHub"
EXPLORE_PROJECTS_ON_GITHUB = "Explore projects on GitHub"
RETURN_TO_TUTORIAL = "Return to in progress tutorial"
EXIT_TUTORIAL = "Exit tutorial"
LEAVE_TUTORIAL_BODY = (
    "If you leave the tutorial you can come back to it later, but your progress "
    "on the current step is not kept."
)
OPEN_OPTIONS = "Open options"
START_TUTORIAL = "Start tutorial"
NOT_NOW = "Not now"

TUTORIAL_STEPS: tuple[tuple[TutorialStep, str, str, str], ...] = (
    (
        TutorialStep.PICK_EDITOR,
        "Install a text editor",
        "It doesn’t look like you have a text editor installed. We recommend Visual Studio Code, "
        "but feel free to use any.",
        "",
    ),
    (
        TutorialStep.CREATE_BRANCH,
        "Create a branch",
        "A branch lets you work on different versions of a repository at one time. "
        "Create one from Branch → New branch.",
        "Ctrl+Shift+N",
    ),
    (
        TutorialStep.EDIT_FILE,
        "Edit a file",
        "Open this repository in your preferred text editor. Edit README.md, save it, and come back.",
        "Ctrl+Shift+A",
    ),
    (
        TutorialStep.MAKE_COMMIT,
        "Make a commit",
        "In the summary field, write a short message that describes your changes, "
        "then click Commit to branch.",
        "",
    ),
    (
        TutorialStep.PUSH_BRANCH,
        "Publish to GitHub",
        "Publishing uploads your commits to this branch on GitHub. "
        "Use the Publish/Push button in the top bar.",
        "Ctrl+P",
    ),
    (
        TutorialStep.OPEN_PULL_REQUEST,
        "Open a pull request",
        "A pull request proposes your changes so someone can review and merge them. "
        "This tutorial PR stays private.",
        "Ctrl+R",
    ),
)


def tutorial_steps(current: TutorialStep | None) -> list[dict[str, object]]:
    """The panel's step list, with which one is live and which are behind it."""
    order = [step for step, _summary, _description, _shortcut in TUTORIAL_STEPS]
    position = order.index(current) if current in order else len(order)
    steps: list[dict[str, object]] = []
    for index, (step, summary, description, shortcut) in enumerate(TUTORIAL_STEPS):
        is_current = step == current
        steps.append(
            {
                "step": step.value,
                "title": summary,
                "description": description,
                "shortcut": shortcut,
                "current": is_current,
                "complete": index < position,
                "nudge": is_current and shouldNudge(current, "branch"),
                "nudgeState": nudge_arrow_state(
                    should_nudge=is_current and shouldNudge(current, "branch")
                ),
            }
        )
    return steps
