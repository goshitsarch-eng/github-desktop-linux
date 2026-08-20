"""Searchable Branches / Pull Requests foldout matching GitHub Desktop."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from ..models import Branch, BranchType, PopupType, PullRequest
from ..shells import open_external
from .menus import attach_right_click, clear_box, copy_text, show_context_menu


def group_branches(
    branches: list[Branch],
    *,
    current: str | None,
    default_name: str | None,
    recent_names: list[str],
) -> list[tuple[str, list[Branch]]]:
    by_name = {b.name: b for b in branches}
    used: set[str] = set()
    groups: list[tuple[str, list[Branch]]] = []
    if default_name and default_name in by_name:
        groups.append(("Default", [by_name[default_name]]))
        used.add(default_name)
    recent: list[Branch] = []
    for name in recent_names:
        branch = by_name.get(name)
        if branch and name not in used:
            recent.append(branch)
            used.add(name)
    if recent:
        groups.append(("Recent", recent))
    others = [b for b in branches if b.name not in used]
    locals_ = [b for b in others if b.type == BranchType.LOCAL]
    remotes = [b for b in others if b.type == BranchType.REMOTE]
    if locals_:
        groups.append(("Other", locals_))
    if remotes:
        groups.append(("Remote", remotes))
    if current:
        for _title, items in groups:
            items.sort(key=lambda b: (0 if b.name == current else 1, b.name.lower()))
    return groups


class BranchesFoldout(Gtk.Popover):
    def __init__(
        self,
        *,
        on_checkout: Callable[[Branch], None],
        on_create: Callable[[], None],
        on_rename: Callable[[Branch], None],
        on_delete: Callable[[Branch], None],
        on_merge: Callable[[Branch], None],
        on_pr: Callable[[PullRequest], None],
        on_view_github: Callable[[Branch], None],
        on_cherry_pick: Callable[[Branch, str], None] | None = None,
        on_cherry_pick_pr: Callable[[PullRequest, str], None] | None = None,
    ) -> None:
        super().__init__()
        self.set_has_arrow(True)
        self.set_autohide(True)
        self._on_checkout = on_checkout
        self._on_create = on_create
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._on_merge = on_merge
        self._on_pr = on_pr
        self._on_view_github = on_view_github
        self._on_cherry_pick = on_cherry_pick
        self._on_cherry_pick_pr = on_cherry_pick_pr
        self._current_name: str | None = None
        self._github = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_size_request(360, 420)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        self._search = Gtk.SearchEntry()
        self._search.set_placeholder_text("Find a branch…")
        self._search.connect("search-changed", lambda *_: self._refilter())
        root.append(self._search)

        switcher = Adw.ViewSwitcher()
        self._stack = Adw.ViewStack()
        switcher.set_stack(self._stack)
        root.append(switcher)

        branches_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        branch_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        branch_scroll.set_min_content_height(260)
        self._branch_list = Gtk.ListBox()
        self._branch_list.add_css_class("boxed-list")
        self._branch_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._branch_list.connect("row-activated", self._on_branch_row)
        branch_scroll.set_child(self._branch_list)
        branches_page.append(branch_scroll)
        new_btn = Gtk.Button(label="New branch…")
        new_btn.connect("clicked", lambda *_: self._on_create())
        branches_page.append(new_btn)
        self._merge_btn = Gtk.Button(label="Merge into current branch")
        self._merge_btn.connect("clicked", self._on_merge_clicked)
        branches_page.append(self._merge_btn)
        self._stack.add_titled(branches_page, "branches", "Branches")

        pr_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        pr_scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        pr_scroll.set_min_content_height(260)
        self._pr_list = Gtk.ListBox()
        self._pr_list.add_css_class("boxed-list")
        self._pr_list.connect("row-activated", self._on_pr_row)
        pr_scroll.set_child(self._pr_list)
        pr_page.append(pr_scroll)
        self._stack.add_titled(pr_page, "prs", "Pull Requests")

        root.append(self._stack)
        self.set_child(root)
        self._branches: list[Branch] = []
        self._prs: list[PullRequest] = []
        self._pr_checks: dict[int, str] = {}
        self._pr_quick = Gtk.Popover()
        self._pr_quick.set_autohide(False)
        self._pr_quick.set_has_arrow(True)
        self._pr_quick.set_position(Gtk.PositionType.RIGHT)
        self._pr_quick_timer = 0
        self._pr_quick_pr: PullRequest | None = None
        self.connect("notify::visible", lambda *_: None if self.get_visible() else self._hide_pr_quick())
        self._default_name: str | None = None
        self._recent: list[str] = []

    def refresh(
        self,
        branches: list[Branch],
        pull_requests: list[PullRequest],
        *,
        current: str | None,
        default_name: str | None,
        recent: list[str],
        has_github: bool,
        pr_checks: dict[int, str] | None = None,
    ) -> None:
        self._branches = list(branches)
        self._prs = list(pull_requests)
        self._pr_checks = dict(pr_checks or {})
        self._current_name = current
        self._default_name = default_name
        self._recent = list(recent)
        self._github = has_github
        self._search.set_placeholder_text("Find a branch or pull request…")
        self._refilter()

    def popup_and_focus(self) -> None:
        self.popup()
        self._search.grab_focus()

    def _needle(self) -> str:
        return self._search.get_text().strip().lower()

    def _refilter(self) -> None:
        needle = self._needle()
        clear_box(self._branch_list)
        filtered = [b for b in self._branches if not needle or needle in b.name.lower()]
        groups = group_branches(
            filtered,
            current=self._current_name,
            default_name=self._default_name,
            recent_names=self._recent,
        )
        for title, items in groups:
            if not items:
                continue
            header = Gtk.ListBoxRow()
            header.set_selectable(False)
            header.set_activatable(False)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("heading")
            header.set_child(label)
            self._branch_list.append(header)
            for branch in items:
                self._branch_list.append(self._branch_row(branch))
        clear_box(self._pr_list)
        prs = [
            pr
            for pr in self._prs
            if not needle or needle in pr.title.lower() or needle in str(pr.number) or needle in pr.author.lower()
        ]
        if not prs:
            empty = Adw.ActionRow(title="No pull requests" if self._github else "This repository is not on GitHub")
            self._pr_list.append(empty)
            return
        for pr in prs:
            row = Adw.ActionRow(title=f"#{pr.number} {pr.title}", subtitle=f"{pr.author} · {pr.head_ref}")
            status = self._pr_checks.get(pr.number)
            if status:
                icons = {
                    "success": "emblem-ok-symbolic",
                    "failure": "dialog-error-symbolic",
                    "pending": "emblem-synchronizing-symbolic",
                }
                img = Gtk.Image.new_from_icon_name(icons.get(status, "dialog-question-symbolic"))
                img.add_css_class(f"checks-{status}")
                img.set_tooltip_text(f"CIStatus: {status}")
                row.add_suffix(img)
            if pr.draft:
                row.add_suffix(Gtk.Label(label="Draft"))
            row.set_activatable(True)
            row._pr = pr  # type: ignore[attr-defined]
            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda *_a, r=row, p=pr: self._schedule_pr_quick(r, p))
            motion.connect("leave", lambda *_a: self._schedule_hide_pr_quick())
            row.add_controller(motion)
            if self._on_cherry_pick_pr:
                try:
                    drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

                    def on_drop(_t, value, _x, _y, target=pr):
                        if value and self._on_cherry_pick_pr:
                            self.popdown()
                            self._on_cherry_pick_pr(target, str(value))
                            return True
                        return False

                    drop.connect("drop", on_drop)
                    row.add_controller(drop)
                except Exception:
                    pass
            self._pr_list.append(row)

    def _cancel_pr_quick_timer(self) -> None:
        if self._pr_quick_timer:
            GLib.source_remove(self._pr_quick_timer)
            self._pr_quick_timer = 0

    def _schedule_pr_quick(self, row: Gtk.Widget, pr: PullRequest) -> None:
        self._cancel_pr_quick_timer()
        self._pr_quick_timer = GLib.timeout_add(250, lambda: self._show_pr_quick(row, pr) or False)

    def _schedule_hide_pr_quick(self) -> None:
        self._cancel_pr_quick_timer()
        self._pr_quick_timer = GLib.timeout_add(200, lambda: self._hide_pr_quick() or False)

    def _show_pr_quick(self, row: Gtk.Widget, pr: PullRequest) -> None:
        """Desktop `PullRequestQuickView` hover card."""
        self._cancel_pr_quick_timer()
        self._pr_quick_pr = pr
        try:
            self._pr_quick.unparent()
        except Exception:
            pass
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_size_request(280, -1)
        header = Gtk.Box(spacing=8)
        header.append(Gtk.Label(label="Review requested" if not pr.draft else "Draft pull request", xalign=0, hexpand=True))
        view = Gtk.Button(label="View on GitHub")
        view.add_css_class("flat")
        view.connect("clicked", lambda *_: (self._hide_pr_quick(), open_external(pr.html_url)))
        header.append(view)
        box.append(header)
        status = Gtk.Label(label="Draft" if pr.draft else "Open", xalign=0)
        status.add_css_class("heading")
        box.append(status)
        title = Gtk.Label(label=pr.title, wrap=True, xalign=0)
        title.add_css_class("title-4")
        box.append(title)
        body_text = (pr.body or "").strip() or "No description provided."
        body = Gtk.Label(label=body_text[:800], wrap=True, xalign=0)
        body.add_css_class("dim-label")
        box.append(body)
        stay = Gtk.EventControllerMotion()
        stay.connect("enter", lambda *_: self._cancel_pr_quick_timer())
        stay.connect("leave", lambda *_: self._schedule_hide_pr_quick())
        box.add_controller(stay)
        self._pr_quick.set_child(box)
        self._pr_quick.set_parent(row)
        self._pr_quick.popup()

    def _hide_pr_quick(self) -> None:
        self._cancel_pr_quick_timer()
        try:
            self._pr_quick.popdown()
        except Exception:
            pass
        self._pr_quick_pr = None

    def _branch_row(self, branch: Branch) -> Gtk.Widget:
        subtitle = "Current branch" if branch.name == self._current_name else (branch.upstream or branch.type.value)
        row = Adw.ActionRow(title=branch.name, subtitle=subtitle)
        row.set_activatable(True)
        row._branch = branch  # type: ignore[attr-defined]
        attach_right_click(row, lambda *_ , b=branch, r=row: self._branch_menu(r, b))
        if self._on_cherry_pick:
            try:
                drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

                def on_drop(_t, value, _x, _y, target=branch):
                    if value and self._on_cherry_pick:
                        self.popdown()
                        self._on_cherry_pick(target, str(value))
                        return True
                    return False

                drop.connect("drop", on_drop)
                row.add_controller(drop)
            except Exception:
                pass
        return row

    def _branch_menu(self, row: Gtk.Widget, branch: Branch) -> None:
        show_context_menu(
            row,
            [
                ("Checkout", lambda: self._on_checkout(branch), branch.name != self._current_name),
                ("Rename…", lambda: self._on_rename(branch), branch.type == BranchType.LOCAL),
                ("Delete…", lambda: self._on_delete(branch), branch.name != self._current_name),
                None,
                ("Copy branch name", lambda: copy_text(branch.name), True),
                ("View on GitHub", lambda: self._on_view_github(branch), self._github),
            ],
        )

    def _on_branch_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        branch = getattr(row, "_branch", None)
        if branch is None:
            return
        self.popdown()
        self._on_checkout(branch)

    def _on_pr_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        pr = getattr(row, "_pr", None)
        if pr is None:
            return
        self.popdown()
        self._on_pr(pr)

    def _on_merge_clicked(self, *_args: object) -> None:
        row = self._branch_list.get_selected_row()
        branch = getattr(row, "_branch", None) if row else None
        if branch is None:
            return
        self.popdown()
        self._on_merge(branch)
