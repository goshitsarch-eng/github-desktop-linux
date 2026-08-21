"""Expandable commit summary matching GitHub Desktop's history header."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from ..models import ChangesetData, Commit, GitHubRepository
from ..shells import open_external
from .avatar import AvatarStack, users_from_commits
from .menus import copy_text


class ExpandableCommitSummary(Gtk.Box):
    def __init__(self, *, on_copy_sha: Callable[[str], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("expandable-commit-summary")
        self._on_copy_sha = on_copy_sha or (lambda sha: copy_text(sha))
        self._summary = Gtk.Label(xalign=0)
        self._summary.add_css_class("commit-summary")
        self._summary.set_wrap(True)
        self._summary.set_use_markup(True)
        self._summary.connect("activate-link", self._on_link)
        self._meta = Gtk.Label(xalign=0)
        self._meta.add_css_class("commit-sha")
        self._meta.set_wrap(True)
        self._stats = Gtk.Label(xalign=0)
        self._stats.add_css_class("commit-stats")
        self._body = Gtk.Label(xalign=0)
        self._body.set_wrap(True)
        self._body.set_visible(False)
        self._body.set_use_markup(True)
        self._body.connect("activate-link", self._on_link)
        self._toggle = Gtk.Button(label="Expand")
        self._toggle.add_css_class("flat")
        self._toggle.set_halign(Gtk.Align.START)
        self._toggle.connect("clicked", self._on_toggle)
        self._sha_btn = Gtk.Button(label="Copy SHA")
        self._sha_btn.add_css_class("flat")
        self._unreachable_btn = Gtk.Button(label="")
        self._unreachable_btn.add_css_class("flat")
        self._unreachable_btn.set_visible(False)
        self._reachable_btn = Gtk.Button(label="")
        self._reachable_btn.add_css_class("flat")
        self._reachable_btn.set_visible(False)
        actions = Gtk.Box(spacing=6)
        actions.append(self._toggle)
        actions.append(self._sha_btn)
        actions.append(self._reachable_btn)
        actions.append(self._unreachable_btn)
        self._sha_btn.connect("clicked", lambda *_: self._sha and self._on_copy_sha(self._sha))
        self._on_unreachable: Callable[[], None] | None = None
        self._on_highlight: Callable[[list[str]], None] | None = None
        self._unreachable_btn.connect("clicked", lambda *_: self._on_unreachable and self._on_unreachable())
        self._reachable_btn.connect("clicked", lambda *_: self._on_unreachable and self._on_unreachable())
        un_motion = Gtk.EventControllerMotion()
        un_motion.connect("enter", lambda *_: self._highlight_not_in_diff())
        un_motion.connect("leave", lambda *_: self._highlight_none())
        self._unreachable_btn.add_controller(un_motion)
        in_motion = Gtk.EventControllerMotion()
        in_motion.connect("enter", lambda *_: self._highlight_in_diff())
        in_motion.connect("leave", lambda *_: self._highlight_none())
        self._reachable_btn.add_controller(in_motion)
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
        on_highlight: Callable[[list[str]], None] | None = None,
        github: GitHubRepository | None = None,
    ) -> None:
        self._expanded = expanded
        self._on_unreachable = on_unreachable
        self._on_highlight = on_highlight
        if not commits:
            self._summary.set_text("No commit selected")
            self._meta.set_text("")
            self._meta.set_tooltip_text("")
            self._stats.set_text("")
            self._body.set_text("")
            self._body.set_visible(False)
            self._unreachable_btn.set_visible(False)
            self._reachable_btn.set_visible(False)
            self._sha = ""
            self._set_avatar(users_from_commits(commits, github))
            return
        primary = commits[0]
        self._sha = primary.sha
        self._body_text = primary.body
        self._set_avatar(users_from_commits(commits, github))
        if len(commits) == 1:
            from .emoji import expand_shortcodes
            from ..models import format_commit_attribution
            from ..push_pull import format_commit_relative_time
            from ..text_tokens import Tokenizer, tokens_as_markup, tokens_as_text, wrap_rich_text_commit_message

            has_empty = not (primary.summary or "").strip()
            if has_empty:
                from html import escape

                summary = "Empty commit message"
                self._body_text = escape(primary.body or "")
                self._summary.set_text(summary)
            else:
                wrapped = wrap_rich_text_commit_message(
                    primary.summary,
                    primary.body,
                    Tokenizer(github=github),
                )
                self._summary.set_markup(tokens_as_markup(wrapped.summary))
                self._body_text = tokens_as_markup(wrapped.body) or expand_shortcodes(
                    tokens_as_text(wrapped.body)
                )
            if has_empty:
                self._summary.add_css_class("empty-summary")
            else:
                self._summary.remove_css_class("empty-summary")
            tags = (" · " + ", ".join(primary.tags)) if primary.tags else ""
            attribution = format_commit_attribution(primary, github)
            relative = format_commit_relative_time(primary.author.date)
            from ..format_date import format_date

            self._meta.set_text(
                f"{attribution} • {relative} · {primary.author.email} · {primary.short_sha}{tags}"
            )
            self._meta.set_tooltip_text(format_date(primary.author.date))
        else:
            in_diff = set(shas_in_diff or [])
            shown = len(in_diff) or len(commits)
            self._summary.set_text(f"Showing changes from {shown} commits")
            authors = sorted({c.author.name for c in commits})
            self._meta.set_text(
                f"{', '.join(authors[:4])}"
                + (f" +{len(authors) - 4}" if len(authors) > 4 else "")
                + f" · {commits[-1].short_sha}…{commits[0].short_sha}"
            )
            self._meta.set_tooltip_text("")
            self._body_text = ""
        if changeset:
            files = len(changeset.files)
            self._stats.set_text(
                f"{files} file{'s' if files != 1 else ''}  +{changeset.lines_added}  −{changeset.lines_deleted}"
            )
        else:
            self._stats.set_text("")
        self._body.set_markup(self._body_text or "")
        self._body.set_visible(self._expanded and bool(self._body_text))
        self._toggle.set_visible(bool(self._body_text) or len(commits) > 1)
        self._toggle.set_label("Collapse" if self._expanded else "Expand")
        unreachable = 0
        self._in_diff_shas = list(shas_in_diff or [])
        self._selected_shas = [c.sha for c in commits]
        if len(commits) > 1:
            in_diff = set(self._in_diff_shas)
            unreachable = sum(1 for c in commits if c.sha not in in_diff)
        if unreachable:
            noun = "commit" if unreachable == 1 else "commits"
            self._unreachable_btn.set_label(f"{unreachable} unreachable {noun} not included")
            self._unreachable_btn.set_visible(True)
            shown = len(commits) - unreachable
            shown_noun = "commit" if shown == 1 else "commits"
            self._reachable_btn.set_label(f"{shown} {shown_noun} in this diff")
            self._reachable_btn.set_visible(True)
        else:
            self._unreachable_btn.set_visible(False)
            self._reachable_btn.set_visible(False)

    def _highlight_in_diff(self) -> None:
        if self._on_highlight:
            self._on_highlight(list(getattr(self, "_in_diff_shas", [])))

    def _highlight_not_in_diff(self) -> None:
        if not self._on_highlight:
            return
        in_diff = set(getattr(self, "_in_diff_shas", []))
        self._on_highlight([sha for sha in getattr(self, "_selected_shas", []) if sha not in in_diff])

    def _highlight_none(self) -> None:
        if self._on_highlight:
            self._on_highlight([])

    def _set_avatar(self, users: list[tuple[str, str]]) -> None:
        child = self._avatar_slot.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._avatar_slot.remove(child)
            child = nxt
        if users:
            self._avatar_slot.append(AvatarStack(users, size=32))

    def _on_toggle(self, *_args: object) -> None:
        self._expanded = not self._expanded
        self._body.set_visible(self._expanded and bool(self._body_text))
        self._toggle.set_label("Collapse" if self._expanded else "Expand")

    def _on_link(self, _label: Gtk.Label, uri: str) -> bool:
        open_external(uri)
        return True
