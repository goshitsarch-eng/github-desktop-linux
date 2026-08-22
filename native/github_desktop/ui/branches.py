"""Searchable Branches / Pull Requests foldout matching GitHub Desktop."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from ..models import Branch, BranchesTab, BranchType, PopupType, PullRequest
from ..fuzzy_find import filter_items
from ..push_pull import format_commit_relative_time
from ..shells import open_external
from .markdown import issue_base_from_html_url, sandboxed_markdown_label
from .menus import attach_right_click, clear_box, copy_text, show_context_menu, view_on_github_label
from .text_box import search_entry


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


# Desktop `NoPullRequests.renderCallToAction` (`no-pull-requests.tsx`).
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
        on_view_pr_github: Callable[[PullRequest], None] | None = None,
        on_cherry_pick: Callable[[Branch, str], None] | None = None,
        on_cherry_pick_pr: Callable[[PullRequest, str], None] | None = None,
        on_cherry_pick_new_branch: Callable[[str], None] | None = None,
        on_create_pr: Callable[[], None] | None = None,
        on_tab: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.set_has_arrow(True)
        self.set_autohide(True)
        self._on_checkout = on_checkout
        self._on_create = on_create
        self._on_create_pr = on_create_pr
        self._on_rename = on_rename
        self._on_delete = on_delete
        self._on_merge = on_merge
        self._on_pr = on_pr
        self._on_view_github = on_view_github
        self._on_view_pr_github = on_view_pr_github
        self._on_cherry_pick = on_cherry_pick
        self._on_cherry_pick_pr = on_cherry_pick_pr
        self._on_cherry_pick_new_branch = on_cherry_pick_new_branch
        self._on_tab = on_tab
        self._updating_tab = False
        self._current_name: str | None = None
        self._github = False

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_size_request(max(365, 360), 420)
        root.set_margin_top(8)
        root.set_margin_bottom(8)
        root.set_margin_start(8)
        root.set_margin_end(8)

        self._search = search_entry()
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
        new_btn = Gtk.Button(label="New branch")
        new_btn.add_css_class("new-branch-drop")
        new_btn.connect("clicked", lambda *_: self._on_create())
        if on_cherry_pick_new_branch:
            try:
                drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

                def on_new_drop(_t, value, _x, _y):
                    if value and self._on_cherry_pick_new_branch:
                        self.popdown()
                        self._on_cherry_pick_new_branch(str(value))
                        return True
                    return False

                drop.connect("drop", on_new_drop)
                new_btn.add_controller(drop)
            except Exception:
                pass
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
        self._stack.add_titled(pr_page, "prs", "Pull requests")

        self._stack.connect("notify::visible-child", self._on_visible_tab)

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
        self._repository_name = ""
        self._on_default_branch = True
        self._prs_loading = False
        self._enterprise = False

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
        repository_name: str = "",
        is_on_default_branch: bool = True,
        prs_loading: bool = False,
        enterprise: bool = False,
        selected_tab: str | None = None,
    ) -> None:
        self._branches = list(branches)
        self._prs = list(pull_requests)
        self._pr_checks = dict(pr_checks or {})
        self._current_name = current
        self._default_name = default_name
        self._recent = list(recent)
        self._github = has_github
        self._repository_name = repository_name
        self._on_default_branch = is_on_default_branch
        self._prs_loading = prs_loading
        self._enterprise = enterprise
        self._search.set_placeholder_text("Find a branch or pull request…")
        wanted = "prs" if selected_tab == BranchesTab.PULL_REQUESTS.value else "branches"
        if selected_tab is not None and self._stack.get_visible_child_name() != wanted:
            self._updating_tab = True
            self._stack.set_visible_child_name(wanted)
            self._updating_tab = False
        self._refilter()

    def _on_visible_tab(self, *_args: object) -> None:
        if self._updating_tab or self._on_tab is None:
            return
        name = self._stack.get_visible_child_name() or "branches"
        tab = BranchesTab.PULL_REQUESTS.value if name == "prs" else BranchesTab.BRANCHES.value
        self._on_tab(tab)

    def popup_and_focus(self) -> None:
        self.popup()
        self._search.grab_focus()

    def set_foldout_width(self, width: int) -> None:
        """Desktop branch foldout `minWidth: 365` and `width: branchDropdownWidth`."""
        child = self.get_child()
        if child is not None:
            child.set_size_request(max(365, int(width)), 420)

    def _needle(self) -> str:
        return self._search.get_text().strip()

    def _refilter(self) -> None:
        needle = self._needle()
        clear_box(self._branch_list)
        filtered = filter_items(needle, self._branches, lambda b: [b.name, b.upstream or ""])
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
        if not filtered:
            self._branch_list.append(self._no_branches_row())
        clear_box(self._pr_list)
        prs = filter_items(
            needle,
            self._prs,
            lambda pr: [f"#{pr.number} {pr.title}", f"{pr.author} {pr.head_ref}"],
        )
        if not prs:
            self._pr_list.append(self._pr_empty_state(bool(needle)))
            return
        for pr in prs:
            when = _relative_iso(pr.created_at)
            subtitle = " · ".join(part for part in (pr.author, pr.head_ref, when) if part)
            row = Adw.ActionRow(title=f"#{pr.number} {pr.title}", subtitle=subtitle)
            absolute = _absolute_iso(pr.created_at)
            if absolute:
                row.set_tooltip_text(absolute)
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
            attach_right_click(
                row,
                lambda _w, r=row, p=pr: self._on_pull_request_item_context_menu(r, p),
            )
            if self._on_cherry_pick_pr and pr.head_ref != self._current_name:
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

    def _pr_empty_state(self, is_search: bool) -> Gtk.Widget:
        """Desktop `NoPullRequests` blank slate."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("no-pull-requests")
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(12)
        box.set_margin_end(12)
        if not self._github:
            title = Gtk.Label(label="This repository is not on GitHub", wrap=True, xalign=0)
            title.add_css_class("title-4")
            box.append(title)
        elif self._prs_loading:
            title = Gtk.Label(label="Hang tight", wrap=True, xalign=0)
            title.add_css_class("title-4")
            box.append(title)
            box.append(Gtk.Label(label="Loading pull requests as fast as I can!", wrap=True, xalign=0))
        elif is_search:
            title = Gtk.Label(label="Sorry, I can't find that pull request!", wrap=True, xalign=0)
            title.add_css_class("title-4")
            box.append(title)
        else:
            title = Gtk.Label(label="You're all set!", wrap=True, xalign=0)
            title.add_css_class("title-4")
            box.append(title)
            name = self._repository_name or "this repository"
            box.append(Gtk.Label(label=f"No open pull requests in {name}", wrap=True, xalign=0))
        if self._github and not is_search and not self._prs_loading:
            _, link_text, _ = no_pull_requests_cta_parts(
                is_on_default_branch=self._on_default_branch
            )
            cta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            cta.add_css_class("call-to-action")
            sentence = Gtk.Label(
                label=no_pull_requests_cta_sentence(is_on_default_branch=self._on_default_branch),
                wrap=True,
                xalign=0,
            )
            cta.append(sentence)
            link = Gtk.Button()
            link.add_css_class("flat")
            link.add_css_class("link-button-component")
            link.set_halign(Gtk.Align.START)
            link.set_child(Gtk.Label(label=link_text))
            if self._on_default_branch:
                link.connect("clicked", lambda *_: (self.popdown(), self._on_create()))
            else:
                link.connect(
                    "clicked",
                    lambda *_: (self.popdown(), self._on_create_pr() if self._on_create_pr else None),
                )
            cta.append(link)
            box.append(cta)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_child(box)
        return row

    def _no_branches_row(self) -> Gtk.Widget:
        """Desktop `NoBranches` blank slate."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("no-branches")
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(12)
        box.set_margin_end(12)
        title = Gtk.Label(label="Sorry, I can't find that branch", wrap=True, xalign=0)
        title.add_css_class("title-4")
        box.append(title)
        subtitle = Gtk.Label(label="Do you want to create a new branch instead?", wrap=True, xalign=0)
        box.append(subtitle)
        cta = Gtk.Button(label="Create new branch")
        cta.add_css_class("create-branch-button")
        cta.connect("clicked", lambda *_: (self.popdown(), self._on_create()))
        box.append(cta)
        protip = Gtk.Label(
            label="ProTip! Press Ctrl+Shift+N to quickly create a new branch from anywhere within the app",
            wrap=True,
            xalign=0,
        )
        protip.add_css_class("protip")
        box.append(protip)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_child(box)
        return row

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
        view = Gtk.Button(label=view_on_github_label(enterprise=self._enterprise))
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
        box.append(
            sandboxed_markdown_label(
                pr.body or "",
                issue_base_url=issue_base_from_html_url(pr.html_url),
                max_chars=800,
                empty="No description provided.",
            )
        )
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
        if self._on_cherry_pick and branch.name != self._current_name:
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

    def _on_pull_request_item_context_menu(self, row: Gtk.Widget, pr: PullRequest) -> None:
        """Desktop `onPullRequestItemContextMenu`."""
        self._hide_pr_quick()
        try:
            self._pr_quick.unparent()
        except Exception:
            pass
        view = self._on_view_pr_github
        if view is None:
            return
        show_context_menu(
            row,
            generate_pull_request_context_menu_items(
                on_view_pull_request=lambda: view(pr),
            ),
        )

    def _branch_menu(self, row: Gtk.Widget, branch: Branch) -> None:
        show_context_menu(
            row,
            generate_branch_context_menu_items(
                branch.name,
                is_local=branch.type == BranchType.LOCAL,
                on_rename=lambda _name: self._on_rename(branch),
                on_delete=lambda _name: self._on_delete(branch),
            ),
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
