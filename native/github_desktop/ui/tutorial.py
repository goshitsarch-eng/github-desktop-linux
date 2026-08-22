"""Onboarding tutorial panel matching GitHub Desktop's Get started steps."""

from __future__ import annotations

import os
from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from ..models import TutorialStep

ORDERED = [
    TutorialStep.PICK_EDITOR,
    TutorialStep.CREATE_BRANCH,
    TutorialStep.EDIT_FILE,
    TutorialStep.MAKE_COMMIT,
    TutorialStep.PUSH_BRANCH,
    TutorialStep.OPEN_PULL_REQUEST,
]

# Desktop `app/styles/ui/onboarding-tutorial/_nudge-arrow.scss`
NUDGE_ARROW = "nudge-arrow"
NUDGE_ARROW_UP = "nudge-arrow-up"
NUDGE_ARROW_LEFT = "nudge-arrow-left"
NUDGE_ARROW_Z_INDEX = 16

# Desktop `animation: pointup|pointleft 2s ease-out 6s infinite`
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


def set_css_class(widget: Gtk.Widget, name: str, enabled: bool) -> None:
    if enabled:
        if not widget.has_css_class(name):
            widget.add_css_class(name)
    elif widget.has_css_class(name):
        widget.remove_css_class(name)


def apply_nudge_arrow_classes(
    widget: Gtk.Widget | None,
    *,
    should_nudge: bool = False,
    direction: str = "up",
    base: bool = True,
) -> None:
    """Desktop `classNames('nudge-arrow', { 'nudge-arrow-up': shouldNudge })`."""
    if widget is None:
        return
    set_css_class(widget, NUDGE_ARROW, base)
    set_css_class(widget, NUDGE_ARROW_UP, bool(base and should_nudge and direction == "up"))
    set_css_class(widget, NUDGE_ARROW_LEFT, bool(base and should_nudge and direction == "left"))


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


class NudgeArrow(Gtk.DrawingArea):
    """Octicon-style tutorial pointer matching Desktop `_nudge-arrow.scss`."""

    def __init__(self, direction: str = "up") -> None:
        super().__init__()
        self._direction = "left" if direction == "left" else "up"
        self._offset = 55 if self._direction == "up" else 65
        self._source = 0
        self._started = 0.0
        self.add_css_class("nudge-arrow-graphic")
        self.add_css_class(NUDGE_ARROW)
        self.add_css_class(NUDGE_ARROW_UP if self._direction == "up" else NUDGE_ARROW_LEFT)
        if self._direction == "up":
            self.set_content_width(22)
            self.set_content_height(36)
            self.set_size_request(22, 36)
        else:
            self.set_content_width(36)
            self.set_content_height(22)
            self.set_size_request(36, 22)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.set_can_target(False)
        self.set_focusable(False)
        self.set_visible(False)
        self.set_opacity(0.0)
        try:
            self.set_accessible_role(Gtk.AccessibleRole.PRESENTATION)
        except Exception:
            pass
        self.set_draw_func(self._draw)
        self.connect("unrealize", lambda *_: self.stop())

    def set_nudging(self, active: bool) -> None:
        self.set_visible(bool(active))
        if active:
            self.start()
        else:
            self.stop()
            self.set_opacity(0.0)

    def start(self) -> None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            self.set_opacity(1.0)
            self._offset = 40 if self._direction == "up" else 50
            self.queue_draw()
            return
        if self._source:
            return
        self._started = GLib.get_monotonic_time() / 1000.0
        self._source = GLib.timeout_add(50, self._tick)

    def stop(self) -> None:
        if self._source:
            GLib.source_remove(self._source)
            self._source = 0

    def _tick(self) -> bool:
        elapsed = GLib.get_monotonic_time() / 1000.0 - self._started
        opacity, offset = nudge_arrow_frame(elapsed, direction=self._direction)
        self._offset = offset
        self.set_opacity(opacity)
        self.queue_draw()
        return True

    def _draw(self, _area: Gtk.DrawingArea, cr, width: float, height: float) -> None:
        cr.set_source_rgb(0x21 / 255.0, 0x88 / 255.0, 0xFF / 255.0)
        if self._direction == "up":
            sx = width / 22.0 if width else 1.0
            sy = height / 36.0 if height else 1.0
            cr.scale(sx, sy)
            cr.move_to(11, 6.6)
            cr.line_to(0, 19.8)
            cr.line_to(6.6, 19.8)
            cr.line_to(6.6, 28.6)
            cr.line_to(15.4, 28.6)
            cr.line_to(15.4, 19.8)
            cr.line_to(22, 19.8)
            cr.close_path()
        else:
            sx = width / 36.0 if width else 1.0
            sy = height / 22.0 if height else 1.0
            cr.scale(sx, sy)
            cr.move_to(7, 11)
            cr.line_to(20.2, 22)
            cr.line_to(20.2, 15.4)
            cr.line_to(29, 15.4)
            cr.line_to(29, 6.6)
            cr.line_to(20.2, 6.6)
            cr.line_to(20.2, 0)
            cr.close_path()
        cr.fill()



class TutorialPanel(Gtk.Box):
    def __init__(
        self,
        *,
        on_open_editor: Callable[[], None],
        on_open_pr: Callable[[], None],
        on_skip_editor: Callable[[], None],
        on_skip_pr: Callable[[], None],
        on_preferences: Callable[[], None],
        on_exit: Callable[[], None],
        on_explore: Callable[[], None] | None = None,
        on_create_repository: Callable[[], None] | None = None,
        on_add_repository: Callable[[], None] | None = None,
        on_announced: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("tutorial-panel")
        self.set_size_request(280, -1)
        self._on_open_editor = on_open_editor
        self._on_open_pr = on_open_pr
        self._on_skip_editor = on_skip_editor
        self._on_skip_pr = on_skip_pr
        self._on_preferences = on_preferences
        self._on_exit = on_exit
        self._on_explore = on_explore
        self._on_create_repository = on_create_repository
        self._on_add_repository = on_add_repository
        self._on_announced = on_announced
        self._expanders: dict[TutorialStep, Gtk.Expander] = {}
        title = Gtk.Label(label="Get started", xalign=0)
        title.add_css_class("title-4")
        self.append(title)
        subtitle = Gtk.Label(label="Complete these steps to learn GitHub Desktop.", xalign=0, wrap=True)
        subtitle.add_css_class("dim-label")
        self.append(subtitle)
        self._done = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        done_heading = Gtk.Label(label="You're done!", xalign=0)
        done_heading.add_css_class("heading")
        done_copy = Gtk.Label(
            label="You’ve learned the basics on how to use GitHub Desktop. Here are some suggestions for what to do next.",
            wrap=True,
            xalign=0,
        )
        self._done.append(done_heading)
        self._done.append(done_copy)
        explore = Gtk.Button(label="Explore projects on GitHub")
        explore.add_css_class("pill")
        explore.connect("clicked", lambda *_: self._on_explore and self._on_explore())
        create = Gtk.Button(label="Create a new repository")
        create.add_css_class("pill")
        create.connect("clicked", lambda *_: self._on_create_repository and self._on_create_repository())
        add_local = Gtk.Button(label="Add a local repository")
        add_local.add_css_class("pill")
        add_local.connect("clicked", lambda *_: self._on_add_repository and self._on_add_repository())
        self._done.append(explore)
        self._done.append(create)
        self._done.append(add_local)
        self._done.set_visible(False)
        self.append(self._done)
        steps = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for step, summary, description, shortcut in (
            (
                TutorialStep.PICK_EDITOR,
                "Install a text editor",
                "It doesn’t look like you have a text editor installed. We recommend Visual Studio Code, but feel free to use any.",
                "",
            ),
            (
                TutorialStep.CREATE_BRANCH,
                "Create a branch",
                "A branch lets you work on different versions of a repository at one time. Create one from Branch → New branch.",
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
                "In the summary field, write a short message that describes your changes, then click Commit to branch.",
                "",
            ),
            (
                TutorialStep.PUSH_BRANCH,
                "Publish to GitHub",
                "Publishing uploads your commits to this branch on GitHub. Use the Publish/Push button in the top bar.",
                "Ctrl+P",
            ),
            (
                TutorialStep.OPEN_PULL_REQUEST,
                "Open a pull request",
                "A pull request proposes your changes so someone can review and merge them. This tutorial PR stays private.",
                "Ctrl+R",
            ),
        ):
            expander = Gtk.Expander(label=summary)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            desc = Gtk.Label(label=description, wrap=True, xalign=0)
            inner.append(desc)
            if shortcut:
                inner.append(Gtk.Label(label=shortcut, xalign=0))
            if step == TutorialStep.PICK_EDITOR:
                have = Gtk.Button(label="I have an editor")
                have.add_css_class("pill")
                have.connect("clicked", lambda *_: self._on_skip_editor())
                prefs = Gtk.Button(label="Open options")
                prefs.add_css_class("flat")
                prefs.connect("clicked", lambda *_: self._on_preferences())
                inner.append(have)
                inner.append(prefs)
            if step == TutorialStep.EDIT_FILE:
                open_ed = Gtk.Button(label="Open editor")
                open_ed.add_css_class("suggested-action")
                open_ed.add_css_class("pill")
                open_ed.connect("clicked", lambda *_: self._on_open_editor())
                inner.append(open_ed)
            if step == TutorialStep.OPEN_PULL_REQUEST:
                pr = Gtk.Button(label="Open pull request")
                pr.add_css_class("suggested-action")
                pr.add_css_class("pill")
                pr.connect("clicked", lambda *_: self._on_open_pr())
                skip = Gtk.Button(label="Skip")
                skip.add_css_class("flat")
                skip.connect("clicked", lambda *_: self._on_skip_pr())
                inner.append(pr)
                inner.append(skip)
            expander.set_child(inner)
            expander._summary = summary  # type: ignore[attr-defined]
            self._expanders[step] = expander
            steps.append(expander)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(steps)
        self.append(scroller)
        exit_btn = Gtk.Button(label="Exit tutorial")
        exit_btn.connect("clicked", lambda *_: self._on_exit())
        self.append(exit_btn)

    def refresh(self, current: TutorialStep, editor_name: str | None = None) -> None:
        done = current in {TutorialStep.ALL_DONE, TutorialStep.ALL_COMPLETE, TutorialStep.ANNOUNCED}
        self._done.set_visible(done)
        if current == TutorialStep.ALL_DONE and self._on_announced:
            from gi.repository import GLib

            GLib.idle_add(self._on_announced)
        try:
            current_index = ORDERED.index(current)
        except ValueError:
            current_index = -1
        for index, step in enumerate(ORDERED):
            expander = self._expanders[step]
            complete = 0 <= current_index and index < current_index
            summary = getattr(expander, "_summary", expander.get_label())
            expander.set_label(("✓ " if complete else "") + summary)
            expander.set_expanded(step == current)
            if step == TutorialStep.PICK_EDITOR and editor_name and complete:
                child = expander.get_child()
                if isinstance(child, Gtk.Box):
                    first = child.get_first_child()
                    if isinstance(first, Gtk.Label):
                        first.set_text(f"Your default editor is {editor_name}. You can change it in Options.")
