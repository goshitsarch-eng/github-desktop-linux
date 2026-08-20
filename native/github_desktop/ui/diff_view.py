"""Interactive unified / side-by-side / image diffs with Desktop hunk expansion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from ..git.diff import hunk_line_span, side_by_side_rows
from ..models import (
    DiffHunkExpansionType,
    DiffLine,
    DiffLineType,
    DiffSelection,
    DiffType,
    FileDiff,
    ImageDiff,
    ImageDiffType,
    TextDiff,
)
from .menus import MenuItem, attach_right_click, clear_box, copy_text, show_context_menu
from .syntax import markup_for_diff_line

try:
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
except (ValueError, ImportError):
    GdkPixbuf = None  # type: ignore[misc, assignment]

VIRTUALIZE_AFTER = 400


@dataclass
class RowSpec:
    kind: str
    hunk_index: int
    expansion: DiffHunkExpansionType
    hunk_start: int
    hunk_length: int
    line: DiffLine | None = None
    left: DiffLine | None = None
    right: DiffLine | None = None
    index: int | None = None
    left_i: int | None = None
    right_i: int | None = None


class DiffRowItem(GObject.Object):
    __gtype_name__ = "GitHubDesktopDiffRowItem"

    def __init__(self, spec: RowSpec) -> None:
        super().__init__()
        self.spec = spec


class DiffViewer(Gtk.Box):
    def __init__(
        self,
        *,
        interactive: bool = False,
        on_line_toggle: Callable[[str, int, bool], None] | None = None,
        on_hunk_toggle: Callable[[str, int, int, bool], None] | None = None,
        on_discard_selection: Callable[[str], None] | None = None,
        on_expand_hunk: Callable[[int, str], None] | None = None,
        on_expand_whole: Callable[[], None] | None = None,
        on_collapse: Callable[[], None] | None = None,
        on_expand: Callable[[], None] | None = None,
        on_image_mode: Callable[[str], None] | None = None,
        on_open_submodule: Callable[[str], None] | None = None,
        on_open_binary: Callable[[str], None] | None = None,
        on_hide_whitespace_changed: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("diff-view")
        self.interactive = interactive
        self.on_line_toggle = on_line_toggle
        self.on_hunk_toggle = on_hunk_toggle
        self.on_discard_selection = on_discard_selection
        self.on_expand_hunk = on_expand_hunk
        self.on_expand_whole = on_expand_whole or on_expand
        self.on_collapse = on_collapse
        self.on_expand = on_expand
        self.on_image_mode = on_image_mode
        self.on_open_submodule = on_open_submodule
        self.on_open_binary = on_open_binary
        self.on_hide_whitespace_changed = on_hide_whitespace_changed
        self._toolbar = Gtk.Box(spacing=6)
        self._toolbar.add_css_class("diff-toolbar")
        self.append(self._toolbar)
        self._search_revealer = Gtk.Revealer()
        search_row = Gtk.Box(spacing=6)
        search_row.add_css_class("diff-search")
        self._search_entry = Gtk.SearchEntry()
        self._search_entry.set_placeholder_text("Search…")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("search-changed", lambda *_: self._run_search(self._search_entry.get_text(), "next"))
        self._search_entry.connect("activate", lambda *_: self._run_search(self._search_entry.get_text(), "next"))
        prev_btn = Gtk.Button(icon_name="go-up-symbolic")
        prev_btn.add_css_class("flat")
        prev_btn.connect("clicked", lambda *_: self._run_search(self._search_entry.get_text(), "previous"))
        next_btn = Gtk.Button(icon_name="go-down-symbolic")
        next_btn.add_css_class("flat")
        next_btn.connect("clicked", lambda *_: self._run_search(self._search_entry.get_text(), "next"))
        self._search_count = Gtk.Label(label="")
        self._search_count.add_css_class("dim-label")
        close_search = Gtk.Button(icon_name="window-close-symbolic")
        close_search.add_css_class("flat")
        close_search.connect("clicked", lambda *_: self.close_search())
        search_row.append(self._search_entry)
        search_row.append(prev_btn)
        search_row.append(next_btn)
        search_row.append(self._search_count)
        search_row.append(close_search)
        self._search_revealer.set_child(search_row)
        self.append(self._search_revealer)
        self._hint_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._hint_box.add_css_class("whitespace-hint")
        self._hint_box.set_visible(False)
        self._hint = Gtk.Label(xalign=0, wrap=True)
        self._hint_box.append(self._hint)
        show_ws = Gtk.Button(label="Show whitespace changes")
        show_ws.add_css_class("pill")
        show_ws.set_halign(Gtk.Align.START)
        show_ws.connect("clicked", self._on_show_whitespace)
        self._hint_show = show_ws
        self._hint_box.append(show_ws)
        self.append(self._hint_box)
        self._scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._scroll.set_child(self._inner)
        self.append(self._scroll)
        self._path = ""
        self._show_checks = True
        self._tab_size = 4
        self._selection: DiffSelection | None = None
        self._list_store: Gio.ListStore | None = None
        self._list_view: Gtk.ListView | None = None
        self._row_specs: list[RowSpec] = []
        self._row_widgets: list[Gtk.Widget] = []
        self._search_query = ""
        self._search_matches: list[int] = []
        self._search_cursor = 0
        self._diff: FileDiff | None = None
        self._comments: list = []
        self._hide_whitespace = False
        self.set_focusable(True)
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

    def render(
        self,
        diff: FileDiff | None,
        *,
        path: str = "",
        selection: DiffSelection | None = None,
        side_by_side: bool = False,
        image_mode: str = ImageDiffType.TWO_UP.value,
        show_checks: bool = True,
        hide_whitespace: bool = False,
        can_collapse: bool = False,
        tab_size: int = 4,
        comments: list | None = None,
    ) -> None:
        self._path = path
        self._show_checks = show_checks
        self._tab_size = max(1, tab_size)
        self._selection = selection
        self._comments = list(comments or [])
        self._row_specs = []
        self._row_widgets = []
        self._list_view = None
        clear_box(self._toolbar)
        self._hint_box.set_visible(False)
        self._scroll.set_child(self._inner)
        clear_box(self._inner)
        self._list_store = None
        self._diff = diff
        self._hide_whitespace = hide_whitespace
        if diff is None:
            self._inner.append(Adw.StatusPage(title="No file selected", icon_name="document-symbolic"))
            return
        kind = getattr(diff, "kind", None)
        if kind == DiffType.BINARY:
            page = Adw.StatusPage(title="Binary file", description="This file can't be displayed as text.")
            if self.on_open_binary and path:
                btn = Gtk.Button(label="Open in default program")
                btn.add_css_class("pill")
                btn.add_css_class("suggested-action")
                btn.set_halign(Gtk.Align.CENTER)
                btn.connect("clicked", lambda *_: self.on_open_binary and self.on_open_binary(self._path))
                page.set_child(btn)
            self._inner.append(page)
            return
        if kind == DiffType.IMAGE and isinstance(diff, ImageDiff):
            self._render_image(diff, image_mode)
            return
        if kind in (DiffType.LARGE_TEXT, DiffType.UNRENDERABLE):
            page = Adw.StatusPage(title="Diff too large to display")
            if self.on_open_binary and path:
                btn = Gtk.Button(label="Open in default program")
                btn.add_css_class("pill")
                btn.connect("clicked", lambda *_: self.on_open_binary and self.on_open_binary(self._path))
                page.set_child(btn)
            self._inner.append(page)
            return
        if kind == DiffType.SUBMODULE:
            self._render_submodule(diff)
            return
        if not isinstance(diff, TextDiff):
            self._inner.append(Gtk.Label(label="Unable to display this diff"))
            return
        if hide_whitespace:
            self._hint.set_text("Selecting lines is disabled when hiding whitespace changes.")
            self._hint_box.set_visible(True)
        if diff.has_hidden_bidi_chars or diff.line_endings_change:
            warn_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            warn_box.add_css_class("diff-contents-warning")
            if diff.has_hidden_bidi_chars:
                warn = Gtk.Label(
                    label="This diff contains bidirectional Unicode text that may be interpreted or compiled differently than what appears below. To review, open the file in an editor that reveals hidden Unicode characters.",
                    wrap=True,
                    xalign=0,
                )
                warn.add_css_class("warning")
                warn_box.append(warn)
                link = Gtk.LinkButton(
                    uri="https://github.co/hiddenchars",
                    label="Learn more about bidirectional Unicode characters",
                )
                link.set_halign(Gtk.Align.START)
                warn_box.append(link)
            if diff.line_endings_change:
                frm, to = diff.line_endings_change
                ending = Gtk.Label(
                    label=f"This diff contains a change in line endings from '{frm}' to '{to}'.",
                    wrap=True,
                    xalign=0,
                )
                ending.add_css_class("warning")
                warn_box.append(ending)
            self._inner.append(warn_box)
        self._fill_toolbar(diff, can_collapse)
        rows = self._flatten(diff, side_by_side)
        self._row_specs = rows
        if len(rows) >= VIRTUALIZE_AFTER:
            self._render_listview(rows, selection)
        else:
            for spec in rows:
                widget = self._widget_for(spec, selection)
                self._row_widgets.append(widget)
                self._inner.append(widget)
        if self._search_revealer.get_reveal_child() and self._search_query:
            self._run_search(self._search_query, "next")

    def _fill_toolbar(self, diff: TextDiff, can_collapse: bool) -> None:
        expandable = any(h.expansion_type != DiffHunkExpansionType.NONE for h in diff.hunks)
        if expandable and self.on_expand_whole:
            whole = Gtk.Button(label="Expand whole file")
            whole.add_css_class("flat")
            whole.connect("clicked", lambda *_: self.on_expand_whole and self.on_expand_whole())
            self._toolbar.append(whole)
        if can_collapse and self.on_collapse:
            collapse = Gtk.Button(label="Collapse expanded lines")
            collapse.add_css_class("flat")
            collapse.connect("clicked", lambda *_: self.on_collapse and self.on_collapse())
            self._toolbar.append(collapse)
        find = Gtk.Button(label="Find")
        find.add_css_class("flat")
        find.set_tooltip_text("Find in diff (Ctrl+F)")
        find.connect("clicked", lambda *_: self.start_search())
        self._toolbar.append(find)

    def start_search(self) -> None:
        self._search_revealer.set_reveal_child(True)
        self._search_entry.grab_focus()

    def _on_show_whitespace(self, *_args: object) -> None:
        self._hide_whitespace = False
        self._hint_box.set_visible(False)
        if self.on_hide_whitespace_changed:
            self.on_hide_whitespace_changed(False)

    def close_search(self) -> None:
        self._search_revealer.set_reveal_child(False)
        self._search_query = ""
        self._search_matches = []
        self._search_cursor = 0
        self._search_count.set_text("")
        self._apply_search_highlight()

    def _on_key(self, _controller, keyval: int, _keycode: int, state: Gdk.ModifierType) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.start_search()
            return True
        if keyval == Gdk.KEY_Escape and self._search_revealer.get_reveal_child():
            self.close_search()
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self._search_revealer.get_reveal_child():
            self._run_search(self._search_entry.get_text(), "previous" if shift else "next")
            return True
        return False

    def _spec_text(self, spec: RowSpec) -> str:
        parts = []
        for line in (spec.line, spec.left, spec.right):
            if line is not None and line.text:
                parts.append(line.text)
        return " ".join(parts)

    def _run_search(self, query: str, direction: str) -> None:
        query = query or ""
        self._search_query = query
        needle = query.lower().strip()
        if not needle:
            self._search_matches = []
            self._search_cursor = 0
            self._search_count.set_text("")
            self._apply_search_highlight()
            return
        matches = [i for i, spec in enumerate(self._row_specs) if needle in self._spec_text(spec).lower()]
        if query == getattr(self, "_last_search_query", None) and self._search_matches == matches and matches:
            delta = -1 if direction == "previous" else 1
            self._search_cursor = (self._search_cursor + delta) % len(matches)
        else:
            self._search_matches = matches
            self._search_cursor = len(matches) - 1 if direction == "previous" and matches else 0
        self._last_search_query = query
        if not matches:
            self._search_count.set_text("No results")
            self._apply_search_highlight()
            return
        self._search_count.set_text(f"{self._search_cursor + 1} of {len(matches)}")
        self._apply_search_highlight()
        index = matches[self._search_cursor]
        if self._list_view is not None:
            try:
                self._list_view.scroll_to(index, Gtk.ListScrollFlags.FOCUS, None)
            except Exception:
                pass
        elif index < len(self._row_widgets):
            widget = self._row_widgets[index]
            try:
                widget.grab_focus()
            except Exception:
                pass

    def _apply_search_highlight(self) -> None:
        current = None
        if self._search_matches:
            current = self._search_matches[self._search_cursor]
        for i, widget in enumerate(self._row_widgets):
            widget.remove_css_class("diff-search-hit")
            widget.remove_css_class("diff-search-current")
            if i in self._search_matches:
                widget.add_css_class("diff-search-hit")
            if current is not None and i == current:
                widget.add_css_class("diff-search-current")
        if self._list_view is not None and self._list_store is not None:
            self._list_view.queue_draw()

    def _decorate_search(self, widget: Gtk.Widget, spec: RowSpec) -> None:
        needle = self._search_query.lower().strip()
        if not needle or needle not in self._spec_text(spec).lower():
            return
        widget.add_css_class("diff-search-hit")
        if self._search_matches and self._row_specs:
            try:
                index = self._row_specs.index(spec)
            except ValueError:
                return
            if self._search_matches and index == self._search_matches[self._search_cursor]:
                widget.add_css_class("diff-search-current")

    def _render_submodule(self, diff) -> None:
        from ..models import SubmoduleDiff

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        title = Gtk.Label(label="Submodule changes", xalign=0)
        title.add_css_class("heading")
        box.append(title)
        path = getattr(diff, "path", "") or self._path
        box.append(Gtk.Label(label=path, xalign=0))
        url = getattr(diff, "url", None)
        if url:
            box.append(Gtk.Label(label=f"Remote: {url}", xalign=0))
        old_sha = getattr(diff, "old_sha", None)
        new_sha = getattr(diff, "new_sha", None)
        if old_sha or new_sha:
            box.append(
                Gtk.Label(
                    label=f"{(old_sha or 'none')[:7]} → {(new_sha or 'none')[:7]}",
                    xalign=0,
                )
            )
        status = getattr(diff, "status", None)
        if status:
            if status.commit_changed:
                box.append(Gtk.Label(label="The checked-out commit changed.", xalign=0))
            if status.modified_changes:
                box.append(Gtk.Label(label="The submodule has modified content.", xalign=0))
            if status.untracked_changes:
                box.append(Gtk.Label(label="The submodule has untracked content.", xalign=0))
        full = getattr(diff, "full_path", "") or ""
        if full and self.on_open_submodule:
            open_btn = Gtk.Button(label="Open submodule")
            open_btn.add_css_class("suggested-action")
            open_btn.set_halign(Gtk.Align.START)
            open_btn.connect("clicked", lambda *_ , p=full: self.on_open_submodule and self.on_open_submodule(p))
            box.append(open_btn)
        elif isinstance(diff, SubmoduleDiff) and not full:
            box.append(Gtk.Label(label="This submodule isn't checked out locally.", xalign=0))
        self._inner.append(box)

    def _flatten(self, diff: TextDiff, side_by_side: bool) -> list[RowSpec]:
        rows: list[RowSpec] = []
        for hunk_index, hunk in enumerate(diff.hunks):
            start, length = hunk_line_span(diff, hunk_index)
            if side_by_side:
                for kind, left, right, left_i, right_i in side_by_side_rows(hunk):
                    if kind == "hunk" and left is not None:
                        rows.append(
                            RowSpec(
                                "hunk",
                                hunk_index,
                                hunk.expansion_type,
                                start,
                                length,
                                line=left,
                            )
                        )
                        continue
                    rows.append(
                        RowSpec(
                            "split",
                            hunk_index,
                            hunk.expansion_type,
                            start,
                            length,
                            left=left,
                            right=right,
                            left_i=left_i,
                            right_i=right_i,
                        )
                    )
                continue
            for line in hunk.lines:
                idx = line.diff_line_number if line.diff_line_number is not None else start
                if line.kind == DiffLineType.HUNK:
                    rows.append(
                        RowSpec("hunk", hunk_index, hunk.expansion_type, start, length, line=line)
                    )
                    continue
                rows.append(
                    RowSpec("unified", hunk_index, hunk.expansion_type, start, length, line=line, index=idx)
                )
        return rows

    def _render_listview(self, rows: list[RowSpec], selection: DiffSelection | None) -> None:
        store = Gio.ListStore.new(DiffRowItem)
        for spec in rows:
            store.append(DiffRowItem(spec))
        self._list_store = store
        factory = Gtk.SignalListItemFactory()
        factory.connect("bind", lambda _f, item: self._bind_list_item(item, selection))
        listview = Gtk.ListView.new(Gtk.NoSelection.new(store), factory)
        listview.add_css_class("diff-list")
        self._list_view = listview
        self._scroll.set_child(listview)

    def _bind_list_item(self, list_item, selection: DiffSelection | None) -> None:
        item = list_item.get_item()
        if item is None:
            return
        list_item.set_child(self._widget_for(item.spec, selection))

    def _widget_for(self, spec: RowSpec, selection: DiffSelection | None) -> Gtk.Widget:
        if spec.kind == "hunk" and spec.line is not None:
            widget = self._hunk_header(spec.line, spec.hunk_start, spec.hunk_length, selection, spec.hunk_index, spec.expansion)
        elif spec.kind == "split":
            widget = self._split_row(spec, selection)
        elif spec.line is not None and spec.index is not None:
            widget = self._unified_line(spec.line, spec.index, selection)
        else:
            widget = Gtk.Box()
        self._decorate_search(widget, spec)
        comments = self._comments_for(spec)
        if not comments:
            return widget
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        wrap.append(widget)
        for comment in comments:
            wrap.append(self._comment_bubble(comment))
        return wrap

    def _comments_for(self, spec: RowSpec) -> list:
        line = spec.line or spec.right or spec.left
        if line is None or not self._comments:
            return []
        matched = []
        for comment in self._comments:
            path = getattr(comment, "path", "")
            if path and path != self._path:
                continue
            line_no = getattr(comment, "line", None)
            original = getattr(comment, "original_line", None)
            if line_no and line.new_line_number == line_no:
                matched.append(comment)
            elif original and line.old_line_number == original:
                matched.append(comment)
        return matched

    def _comment_bubble(self, comment) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        box.add_css_class("diff-comment")
        user = getattr(comment, "user", "") or "comment"
        header = Gtk.Label(label=f"{user} commented", xalign=0)
        header.add_css_class("heading")
        body = Gtk.Label(label=getattr(comment, "body", "") or "", xalign=0, wrap=True)
        box.append(header)
        box.append(body)
        url = getattr(comment, "html_url", "")
        if url:
            from ..shells import open_external

            link = Gtk.Button(label="View on GitHub")
            link.add_css_class("flat")
            link.connect("clicked", lambda *_ , u=url: open_external(u))
            box.append(link)
        return box

    def _hunk_header(
        self,
        line: DiffLine,
        start: int,
        length: int,
        selection: DiffSelection | None,
        hunk_index: int,
        expansion: DiffHunkExpansionType,
    ) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.add_css_class("diff-line")
        row.add_css_class("diff-hunk")
        dummy = not line.text
        if self.interactive and self._show_checks and not dummy:
            check = Gtk.CheckButton()
            included = True
            if selection is not None:
                selectable = [i for i in range(start, start + length) if selection.is_selectable(i)]
                included = bool(selectable) and all(selection.is_selected(i) for i in selectable)
                if selectable and not included and any(selection.is_selected(i) for i in selectable):
                    check.set_inconsistent(True)
            check.set_active(included)
            check.set_tooltip_text("Include this hunk")
            check.connect(
                "toggled",
                lambda btn, s=start, n=length: self.on_hunk_toggle and self.on_hunk_toggle(self._path, s, n, btn.get_active()),
            )
            row.append(check)
        row.append(self._expansion_buttons(hunk_index, expansion))
        label = Gtk.Label(label=line.text or "Expand remaining file", xalign=0, hexpand=True)
        label.add_css_class("diff-hunk-text")
        row.append(label)
        attach_right_click(row, lambda *_: self._hunk_menu(start, length, selection, hunk_index, expansion))
        return row

    def _expansion_buttons(self, hunk_index: int, expansion: DiffHunkExpansionType) -> Gtk.Widget:
        box = Gtk.Box(spacing=2)

        def add_btn(label: str, tooltip: str, kind: str, index: int) -> None:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.add_css_class("diff-expand")
            btn.set_tooltip_text(tooltip)
            btn.connect("clicked", lambda *_: self.on_expand_hunk and self.on_expand_hunk(index, kind))
            box.append(btn)

        if expansion == DiffHunkExpansionType.UP:
            add_btn("▲", "Expand up", "up", hunk_index)
        elif expansion == DiffHunkExpansionType.DOWN:
            add_btn("▼", "Expand down", "down", hunk_index - 1)
        elif expansion == DiffHunkExpansionType.SHORT:
            add_btn("↕", "Expand all", "up", hunk_index)
        elif expansion == DiffHunkExpansionType.BOTH:
            add_btn("▼", "Expand down", "down", hunk_index - 1)
            add_btn("▲", "Expand up", "up", hunk_index)
        return box

    def _markup(self, line: DiffLine) -> str:
        old_map = getattr(self._diff, "old_line_markup", None) if self._diff is not None else None
        new_map = getattr(self._diff, "new_line_markup", None) if self._diff is not None else None
        return markup_for_diff_line(
            line,
            self._path,
            old_markup=old_map,
            new_markup=new_map,
            tab_size=self._tab_size,
        )

    def _unified_line(self, line: DiffLine, index: int, selection: DiffSelection | None) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.add_css_class("diff-line")
        if line.kind == DiffLineType.ADD:
            row.add_css_class("diff-add")
        elif line.kind == DiffLineType.DELETE:
            row.add_css_class("diff-del")
        if self.interactive and self._show_checks and line.selectable and not getattr(self, "_hide_whitespace", False):
            check = Gtk.CheckButton()
            active = selection.is_selected(index) if selection else True
            check.set_active(active)
            if not active:
                row.add_css_class("diff-excluded")
            check.connect(
                "toggled",
                lambda btn, i=index: self.on_line_toggle and self.on_line_toggle(self._path, i, btn.get_active()),
            )
            row.append(check)
        old = Gtk.Label(label=str(line.old_line_number or ""))
        new = Gtk.Label(label=str(line.new_line_number or ""))
        old.add_css_class("diff-num")
        new.add_css_class("diff-num")
        text = Gtk.Label(xalign=0, hexpand=True)
        text.set_use_markup(True)
        text.set_selectable(True)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        prefix = line.text[:1] if line.text[:1] in "+- " else " "
        text.set_markup(f"{prefix}{self._markup(line)}")
        row.append(old)
        row.append(new)
        row.append(text)
        attach_right_click(row, lambda *_ , i=index: self._line_menu(i, selection, line))
        return row

    def _split_row(self, spec: RowSpec, selection: DiffSelection | None) -> Gtk.Widget:
        row = Gtk.Box(spacing=0)
        row.add_css_class("diff-line")
        left_box = self._split_cell(spec.left, spec.left_i, selection, delete=True)
        right_box = self._split_cell(spec.right, spec.right_i, selection, delete=False)
        left_box.set_hexpand(True)
        right_box.set_hexpand(True)
        row.append(left_box)
        row.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        row.append(right_box)
        return row

    def _split_cell(
        self,
        line: DiffLine | None,
        index: int | None,
        selection: DiffSelection | None,
        *,
        delete: bool,
    ) -> Gtk.Widget:
        box = Gtk.Box(spacing=6)
        box.add_css_class("diff-side")
        if line is None:
            box.add_css_class("diff-empty")
            box.append(Gtk.Label(label=" ", hexpand=True))
            return box
        if line.kind == DiffLineType.ADD:
            box.add_css_class("diff-add")
        elif line.kind == DiffLineType.DELETE:
            box.add_css_class("diff-del")
        if self.interactive and self._show_checks and line.selectable and index is not None and not getattr(self, "_hide_whitespace", False):
            check = Gtk.CheckButton()
            active = selection.is_selected(index) if selection else True
            check.set_active(active)
            check.connect(
                "toggled",
                lambda btn, i=index: self.on_line_toggle and self.on_line_toggle(self._path, i, btn.get_active()),
            )
            box.append(check)
        num = line.old_line_number if delete else line.new_line_number
        nlab = Gtk.Label(label=str(num or ""))
        nlab.add_css_class("diff-num")
        text = Gtk.Label(xalign=0, hexpand=True)
        text.set_use_markup(True)
        text.set_selectable(True)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_markup(self._markup(line))
        box.append(nlab)
        box.append(text)
        return box

    def _line_menu(self, index: int, selection: DiffSelection | None, line: DiffLine | None = None) -> None:
        items: list[MenuItem] = []
        if self.interactive and selection is not None and not getattr(self, "_hide_whitespace", False):
            selected = selection.is_selected(index)
            items.append(
                (
                    "Exclude line" if selected else "Include line",
                    lambda: self.on_line_toggle and self.on_line_toggle(self._path, index, not selected),
                    True,
                )
            )
            items.append(
                (
                    "Discard selected lines…",
                    lambda: self.on_discard_selection and self.on_discard_selection(self._path),
                    True,
                )
            )
            items.append(None)
        copied = (line.text[1:] if line and line.text[:1] in "+- " else (line.text if line else ""))
        items.append(("Copy", lambda: copy_text(copied), True))
        if self.on_expand_whole:
            items.append(("Expand whole file", lambda: self.on_expand_whole and self.on_expand_whole(), True))
        if self.on_collapse:
            items.append(("Collapse expanded lines", lambda: self.on_collapse and self.on_collapse(), True))
        show_context_menu(self, items)

    def _hunk_menu(
        self,
        start: int,
        length: int,
        selection: DiffSelection | None,
        hunk_index: int,
        expansion: DiffHunkExpansionType,
    ) -> None:
        items: list[MenuItem] = []
        if self.interactive:
            items.append(("Include hunk", lambda: self.on_hunk_toggle and self.on_hunk_toggle(self._path, start, length, True), True))
            items.append(("Exclude hunk", lambda: self.on_hunk_toggle and self.on_hunk_toggle(self._path, start, length, False), True))
            items.append(("Discard selected lines…", lambda: self.on_discard_selection and self.on_discard_selection(self._path), True))
        if expansion == DiffHunkExpansionType.UP:
            items.append(("Expand up", lambda: self.on_expand_hunk and self.on_expand_hunk(hunk_index, "up"), True))
        elif expansion == DiffHunkExpansionType.DOWN:
            items.append(("Expand down", lambda: self.on_expand_hunk and self.on_expand_hunk(hunk_index - 1, "down"), True))
        elif expansion == DiffHunkExpansionType.SHORT:
            items.append(("Expand all", lambda: self.on_expand_hunk and self.on_expand_hunk(hunk_index, "up"), True))
        elif expansion == DiffHunkExpansionType.BOTH:
            items.append(("Expand up", lambda: self.on_expand_hunk and self.on_expand_hunk(hunk_index, "up"), True))
            items.append(("Expand down", lambda: self.on_expand_hunk and self.on_expand_hunk(hunk_index - 1, "down"), True))
        if self.on_expand_whole:
            items.append(("Expand whole file", lambda: self.on_expand_whole and self.on_expand_whole(), True))
        show_context_menu(self, items)

    def _render_image(self, diff: ImageDiff, mode: str) -> None:
        toolbar = Gtk.Box(spacing=6)
        toolbar.add_css_class("image-diff-toolbar")
        group = Gtk.Box(spacing=4)
        for value, label in (
            (ImageDiffType.TWO_UP.value, "2-up"),
            (ImageDiffType.SWIPE.value, "Swipe"),
            (ImageDiffType.ONION.value, "Onion"),
            (ImageDiffType.DIFFERENCE.value, "Difference"),
        ):
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(mode == value)
            btn.connect("toggled", lambda b, v=value: b.get_active() and self.on_image_mode and self.on_image_mode(v))
            group.append(btn)
        toolbar.append(group)
        self._inner.append(toolbar)
        prev_tex = _texture_from_bytes(diff.previous)
        cur_tex = _texture_from_bytes(diff.current)
        if not prev_tex and cur_tex:
            panels = ((cur_tex, diff.current, "Added"),)
        elif prev_tex and not cur_tex:
            panels = ((prev_tex, diff.previous, "Deleted"),)
        else:
            panels = ((prev_tex, diff.previous, "Previous"), (cur_tex, diff.current, "Current"))
        if mode == ImageDiffType.SWIPE.value and prev_tex and cur_tex:
            self._inner.append(_swipe_images(prev_tex, cur_tex, diff.previous, diff.current))
        elif mode == ImageDiffType.ONION.value and prev_tex and cur_tex:
            self._inner.append(_onion_images(prev_tex, cur_tex))
        elif mode == ImageDiffType.DIFFERENCE.value and prev_tex and cur_tex:
            self._inner.append(_difference_images(diff.previous, diff.current))
        else:
            box = Gtk.Box(spacing=12)
            for tex, blob, title in panels:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                header_class = "image-diff-current" if title in {"Added", "Current"} else "image-diff-previous"
                col.add_css_class(header_class)
                heading = Gtk.Label(label=title, xalign=0)
                heading.add_css_class("image-diff-header")
                col.append(heading)
                meta = _image_dimensions_label(tex, blob)
                if meta:
                    hint = Gtk.Label(label=meta, xalign=0)
                    hint.add_css_class("dim-label")
                    col.append(hint)
                col.append(_picture(tex))
                box.append(col)
            self._inner.append(box)


def _format_byte_size(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def _image_dimensions_label(tex: Gdk.Texture | None, blob: bytes | None) -> str:
    parts: list[str] = []
    if tex is not None:
        parts.append(f"{tex.get_width()}×{tex.get_height()}")
    if blob:
        parts.append(_format_byte_size(len(blob)))
    return " · ".join(parts)


def _picture(tex: Gdk.Texture | None) -> Gtk.Widget:
    if tex is None:
        return Gtk.Label(label="(none)")
    pic = Gtk.Picture.new_for_paintable(tex)
    pic.set_size_request(240, 240)
    pic.set_can_shrink(True)
    return pic


def _pixbuf_from_bytes(blob: bytes | None):
    if not blob or GdkPixbuf is None:
        return None
    try:
        loader = GdkPixbuf.PixbufLoader()
        loader.write(blob)
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None


def _texture_from_bytes(blob: bytes | None) -> Gdk.Texture | None:
    pix = _pixbuf_from_bytes(blob)
    if pix:
        return Gdk.Texture.new_for_pixbuf(pix)
    return None


def _swipe_images(
    previous: Gdk.Texture | None,
    current: Gdk.Texture | None,
    previous_blob: bytes | None = None,
    current_blob: bytes | None = None,
) -> Gtk.Widget:
    """Desktop `Swipe`: 0% is all current, 100% is all previous, clipped overlay."""
    max_w = max(
        previous.get_width() if previous else 1,
        current.get_width() if current else 1,
        1,
    )
    max_h = max(
        previous.get_height() if previous else 1,
        current.get_height() if current else 1,
        1,
    )
    display_w = min(max_w, 480)
    display_h = max(1, int(round(max_h * (display_w / max_w))))
    prev_pix = _pixbuf_from_bytes(previous_blob)
    curr_pix = _pixbuf_from_bytes(current_blob)
    if prev_pix is None and previous is not None:
        prev_pix = _pixbuf_from_bytes(
            bytes(previous.save_to_png_bytes().get_data()) if hasattr(previous, "save_to_png_bytes") else b""
        )
    if curr_pix is None and current is not None:
        curr_pix = _pixbuf_from_bytes(
            bytes(current.save_to_png_bytes().get_data()) if hasattr(current, "save_to_png_bytes") else b""
        )
    if prev_pix is not None and (prev_pix.get_width() != display_w or prev_pix.get_height() != display_h):
        prev_pix = prev_pix.scale_simple(display_w, display_h, GdkPixbuf.InterpType.BILINEAR)
    if curr_pix is not None and (curr_pix.get_width() != display_w or curr_pix.get_height() != display_h):
        curr_pix = curr_pix.scale_simple(display_w, display_h, GdkPixbuf.InterpType.BILINEAR)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.add_css_class("image-diff-swipe")
    state = {"percent": 0.0}
    area = Gtk.DrawingArea()
    area.set_content_width(display_w)
    area.set_content_height(display_h)
    area.add_css_class("image-diff-swipe-canvas")

    def draw(_area, cr, width: int, height: int) -> None:
        # Slider 0 = all current (split at left); 100 = all previous (split at right).
        split = int(width * (state["percent"] / 100.0))
        if prev_pix is not None and split > 0:
            cr.save()
            cr.rectangle(0, 0, split, height)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, prev_pix, 0, 0)
            cr.paint()
            cr.restore()
        if curr_pix is not None and split < width:
            cr.save()
            cr.rectangle(split, 0, width - split, height)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, curr_pix, 0, 0)
            cr.paint()
            cr.restore()
        cr.set_source_rgba(0.2, 0.55, 0.95, 0.95)
        cr.set_line_width(2)
        cr.move_to(split, 0)
        cr.line_to(split, height)
        cr.stroke()

    area.set_draw_func(draw)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 0.1)
    scale.set_value(0)
    scale.set_draw_value(False)
    scale.set_hexpand(True)
    scale.add_css_class("slider")

    def on_change(widget: Gtk.Scale) -> None:
        state["percent"] = widget.get_value()
        area.queue_draw()

    scale.connect("value-changed", on_change)
    root.append(scale)
    root.append(area)
    return root


def _onion_images(previous: Gdk.Texture | None, current: Gdk.Texture | None) -> Gtk.Widget:
    overlay = Gtk.Overlay()
    overlay.set_child(_picture(previous))
    top = _picture(current)
    top.set_opacity(0.5)
    overlay.add_overlay(top)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.append(overlay)
    scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.05)
    scale.set_value(0.5)
    scale.connect("value-changed", lambda s: top.set_opacity(s.get_value()))
    box.append(scale)
    return box


def _difference_images(previous: bytes | None, current: bytes | None) -> Gtk.Widget:
    if GdkPixbuf is None or not previous or not current:
        box = Gtk.Box(spacing=12)
        box.append(_picture(_texture_from_bytes(previous)))
        box.append(_picture(_texture_from_bytes(current)))
        return box
    try:
        from gi.repository import GLib

        def load(data: bytes):
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            return loader.get_pixbuf()

        a = load(previous)
        b = load(current)
        if a is None or b is None:
            raise RuntimeError("decode")
        width = min(a.get_width(), b.get_width(), 640)
        height = min(a.get_height(), b.get_height(), 640)
        if a.get_width() != width or a.get_height() != height:
            a = a.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        if b.get_width() != width or b.get_height() != height:
            b = b.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
        pa = bytes(a.read_pixel_bytes().get_data())
        pb = bytes(b.read_pixel_bytes().get_data())
        n_a = a.get_n_channels()
        n_b = b.get_n_channels()
        rsa = a.get_rowstride()
        rsb = b.get_rowstride()
        out = bytearray(width * height * 4)
        for y in range(height):
            for x in range(width):
                ia = y * rsa + x * n_a
                ib = y * rsb + x * n_b
                ra, ga, ba_ = pa[ia], pa[ia + 1], pa[ia + 2]
                rb, gb, bb = pb[ib], pb[ib + 1], pb[ib + 2]
                oi = (y * width + x) * 4
                if abs(ra - rb) > 12 or abs(ga - gb) > 12 or abs(ba_ - bb) > 12:
                    out[oi : oi + 4] = b"\xdc\x32\x2f\xff"
                else:
                    out[oi] = rb
                    out[oi + 1] = gb
                    out[oi + 2] = bb
                    out[oi + 3] = 255
        pix = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(out)), GdkPixbuf.Colorspace.RGB, True, 8, width, height, width * 4
        )
        return _picture(Gdk.Texture.new_for_pixbuf(pix))
    except Exception:
        box = Gtk.Box(spacing=12)
        box.append(_picture(_texture_from_bytes(previous)))
        box.append(_picture(_texture_from_bytes(current)))
        return box
