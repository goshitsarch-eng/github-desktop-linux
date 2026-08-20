"""Expandable commit summary matching GitHub Desktop's history header."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from ..models import ChangesetData, Commit
from .avatar import Avatar
from .menus import copy_text


class ExpandableCommitSummary(Gtk.Box):
    def __init__(self, *, on_copy_sha: Callable[[str], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("expandable-commit-summary")
        self._on_copy_sha = on_copy_sha or (lambda sha: copy_text(sha))
        self._summary = Gtk.Label(xalign=0)
        self._summary.add_css_class("commit-summary")
        self._summary.set_wrap(True)
        self._meta = Gtk.Label(xalign=0)
        self._meta.add_css_class("commit-sha")
        self._meta.set_wrap(True)
        self._stats = Gtk.Label(xalign=0)
        self._stats.add_css_class("commit-stats")
        self._body = Gtk.Label(xalign=0)
        self._body.set_wrap(True)
        self._body.set_visible(False)
        self._toggle = Gtk.Button(label="Expand")
        self._toggle.add_css_class("flat")
        self._toggle.set_halign(Gtk.Align.START)
        self._toggle.connect("clicked", self._on_toggle)
        self._sha_btn = Gtk.Button(label="Copy SHA")
        self._sha_btn.add_css_class("flat")
        self._unreachable_btn = Gtk.Button(label="")
        self._unreachable_btn.add_css_class("flat")
        self._unreachable_btn.set_visible(False)
        actions = Gtk.Box(spacing=6)
        actions.append(self._toggle)
        actions.append(self._sha_btn)
        actions.append(self._unreachable_btn)
        self._sha_btn.connect("clicked", lambda *_: self._sha and self._on_copy_sha(self._sha))
        self._on_unreachable: Callable[[], None] | None = None
        self._unreachable_btn.connect("clicked", lambda *_: self._on_unreachable and self._on_unreachable())
        self._header = Gtk.Box(spacing=10)
        self._avatar_slot = Gtk.Box()
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        texts.set_hexpand(True)
        texts.append(self._summary)
        texts.append(self._meta)
        self._header.append(self._avatar_slot)
        self._header.append(texts)
        self.append(self._header)
        self.append(self._stats)
        self.append(actions)
        self.append(self._body)
        self._expanded = False
        self._sha = ""
        self._body_text = ""

    def bind(
        self,
        commits: list[Commit],
        changeset: ChangesetData | None,
        *,
        expanded: bool = False,
        shas_in_diff: list[str] | None = None,
        on_unreachable: Callable[[], None] | None = None,
    ) -> None:
        self._expanded = expanded
        self._on_unreachable = on_unreachable
        if not commits:
            self._summary.set_text("No commit selected")
            self._meta.set_text("")
            self._stats.set_text("")
            self._body.set_text("")
            self._body.set_visible(False)
            self._unreachable_btn.set_visible(False)
            self._sha = ""
            self._set_avatar("", "")
            return
        primary = commits[0]
        self._sha = primary.sha
        self._body_text = primary.body
        self._set_avatar(primary.author.name, primary.author.email)
        if len(commits) == 1:
            summary = primary.summary or "Empty commit message"
            self._summary.set_text(summary)
            tags = (" · " + ", ".join(primary.tags)) if primary.tags else ""
            self._meta.set_text(
                f"{primary.author.name} <{primary.author.email}> · "
                f"{primary.author.date.strftime('%Y-%m-%d %H:%M')} · {primary.short_sha}{tags}"
            )
        else:
            self._summary.set_text(f"{len(commits)} commits selected")
            authors = sorted({c.author.name for c in commits})
            self._meta.set_text(
                f"{', '.join(authors[:4])}"
                + (f" +{len(authors) - 4}" if len(authors) > 4 else "")
                + f" · {commits[-1].short_sha}…{commits[0].short_sha}"
            )
        if changeset:
            files = len(changeset.files)
            self._stats.set_text(
                f"{files} file{'s' if files != 1 else ''}  +{changeset.lines_added}  −{changeset.lines_deleted}"
            )
        else:
            self._stats.set_text("")
        self._body.set_text(self._body_text)
        self._body.set_visible(self._expanded and bool(self._body_text))
        self._toggle.set_visible(bool(self._body_text) or len(commits) > 1)
        self._toggle.set_label("Collapse" if self._expanded else "Expand")
        unreachable = 0
        if len(commits) > 1:
            in_diff = set(shas_in_diff or [])
            unreachable = sum(1 for c in commits if c.sha not in in_diff)
        if unreachable:
            noun = "commit" if unreachable == 1 else "commits"
            self._unreachable_btn.set_label(f"{unreachable} {noun} not in this diff")
            self._unreachable_btn.set_visible(True)
        else:
            self._unreachable_btn.set_visible(False)

    def _set_avatar(self, name: str, email: str) -> None:
        child = self._avatar_slot.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._avatar_slot.remove(child)
            child = nxt
        if name or email:
            self._avatar_slot.append(Avatar(name, email, size=32))

    def _on_toggle(self, *_args: object) -> None:
        self._expanded = not self._expanded
        self._body.set_visible(self._expanded and bool(self._body_text))
        self._toggle.set_label("Collapse" if self._expanded else "Expand")
