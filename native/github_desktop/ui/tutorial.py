"""Onboarding tutorial panel matching GitHub Desktop's Get started steps."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from ..models import TutorialStep

ORDERED = [
    TutorialStep.PICK_EDITOR,
    TutorialStep.CREATE_BRANCH,
    TutorialStep.EDIT_FILE,
    TutorialStep.MAKE_COMMIT,
    TutorialStep.PUSH_BRANCH,
    TutorialStep.OPEN_PULL_REQUEST,
]


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
        done = current == TutorialStep.ALL_COMPLETE
        self._done.set_visible(done)
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
