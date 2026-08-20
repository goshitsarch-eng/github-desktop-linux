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
from .syntax import highlight_diff_line

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
        self._toolbar = Gtk.Box(spacing=6)
        self._toolbar.add_css_class("diff-toolbar")
        self.append(self._toolbar)
        self._hint = Gtk.Label(xalign=0)
        self._hint.add_css_class("whitespace-hint")
        self._hint.set_visible(False)
        self.append(self._hint)
        self._scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._scroll.set_child(self._inner)
        self.append(self._scroll)
        self._path = ""
        self._show_checks = True
        self._tab_size = 4
        self._selection: DiffSelection | None = None
        self._list_store: Gio.ListStore | None = None

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
    ) -> None:
        self._path = path
        self._show_checks = show_checks
        self._tab_size = max(1, tab_size)
        self._selection = selection
        clear_box(self._toolbar)
        self._hint.set_visible(False)
        self._scroll.set_child(self._inner)
        clear_box(self._inner)
        self._list_store = None
        if diff is None:
            self._inner.append(Adw.StatusPage(title="No file selected", icon_name="document-symbolic"))
            return
        kind = getattr(diff, "kind", None)
        if kind == DiffType.BINARY:
            self._inner.append(Adw.StatusPage(title="Binary file", description="This file can't be displayed as text."))
            return
        if kind == DiffType.IMAGE and isinstance(diff, ImageDiff):
            self._render_image(diff, image_mode)
            return
        if kind in (DiffType.LARGE_TEXT, DiffType.UNRENDERABLE):
            self._inner.append(Adw.StatusPage(title="Diff too large to display"))
            return
        if kind == DiffType.SUBMODULE:
            self._inner.append(Adw.StatusPage(title="Submodule", description=getattr(diff, "path", "") or path))
            return
        if not isinstance(diff, TextDiff):
            self._inner.append(Gtk.Label(label="Unable to display this diff"))
            return
        if hide_whitespace:
            self._hint.set_text("Whitespace changes are hidden. Turn off Hide whitespace to review them.")
            self._hint.set_visible(True)
        if diff.has_hidden_bidi_chars:
            warn = Gtk.Label(label="This diff contains hidden bidirectional Unicode characters.")
            warn.add_css_class("warning")
            self._inner.append(warn)
        self._fill_toolbar(diff, can_collapse)
        rows = self._flatten(diff, side_by_side)
        if len(rows) >= VIRTUALIZE_AFTER:
            self._render_listview(rows, selection)
            return
        for spec in rows:
            self._inner.append(self._widget_for(spec, selection))

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
        self._scroll.set_child(listview)

    def _bind_list_item(self, list_item, selection: DiffSelection | None) -> None:
        item = list_item.get_item()
        if item is None:
            return
        list_item.set_child(self._widget_for(item.spec, selection))

    def _widget_for(self, spec: RowSpec, selection: DiffSelection | None) -> Gtk.Widget:
        if spec.kind == "hunk" and spec.line is not None:
            return self._hunk_header(spec.line, spec.hunk_start, spec.hunk_length, selection, spec.hunk_index, spec.expansion)
        if spec.kind == "split":
            return self._split_row(spec, selection)
        if spec.line is not None and spec.index is not None:
            return self._unified_line(spec.line, spec.index, selection)
        return Gtk.Box()

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

    def _unified_line(self, line: DiffLine, index: int, selection: DiffSelection | None) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.add_css_class("diff-line")
        if line.kind == DiffLineType.ADD:
            row.add_css_class("diff-add")
        elif line.kind == DiffLineType.DELETE:
            row.add_css_class("diff-del")
        if self.interactive and self._show_checks and line.selectable:
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
        body = line.text[1:] if line.text[:1] in "+- " else line.text
        body = body.replace("\t", " " * self._tab_size)
        text = Gtk.Label(xalign=0, hexpand=True)
        text.set_use_markup(True)
        text.set_selectable(True)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        prefix = line.text[:1] if line.text[:1] in "+- " else " "
        text.set_markup(f"{prefix}{highlight_diff_line(body, self._path)}")
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
        if self.interactive and self._show_checks and line.selectable and index is not None:
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
        body = line.text[1:] if line.text[:1] in "+- " else line.text
        body = body.replace("\t", " " * self._tab_size)
        text = Gtk.Label(xalign=0, hexpand=True)
        text.set_use_markup(True)
        text.set_selectable(True)
        text.set_ellipsize(Pango.EllipsizeMode.END)
        text.set_markup(highlight_diff_line(body, self._path))
        box.append(nlab)
        box.append(text)
        return box

    def _line_menu(self, index: int, selection: DiffSelection | None, line: DiffLine | None = None) -> None:
        items: list[MenuItem] = []
        if self.interactive and selection is not None:
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
        if mode == ImageDiffType.SWIPE.value:
            self._inner.append(_swipe_images(prev_tex, cur_tex))
        elif mode == ImageDiffType.ONION.value:
            self._inner.append(_onion_images(prev_tex, cur_tex))
        elif mode == ImageDiffType.DIFFERENCE.value:
            self._inner.append(_difference_images(diff.previous, diff.current))
        else:
            box = Gtk.Box(spacing=12)
            for tex, title in ((prev_tex, "Previous"), (cur_tex, "Current")):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                col.append(Gtk.Label(label=title))
                col.append(_picture(tex))
                box.append(col)
            self._inner.append(box)


def _picture(tex: Gdk.Texture | None) -> Gtk.Widget:
    if tex is None:
        return Gtk.Label(label="(none)")
    pic = Gtk.Picture.new_for_paintable(tex)
    pic.set_size_request(240, 240)
    pic.set_can_shrink(True)
    return pic


def _texture_from_bytes(blob: bytes | None) -> Gdk.Texture | None:
    if not blob or GdkPixbuf is None:
        return None
    try:
        loader = GdkPixbuf.PixbufLoader()
        loader.write(blob)
        loader.close()
        pix = loader.get_pixbuf()
        if pix:
            return Gdk.Texture.new_for_pixbuf(pix)
    except Exception:
        return None
    return None


def _swipe_images(previous: Gdk.Texture | None, current: Gdk.Texture | None) -> Gtk.Widget:
    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    paned.set_start_child(_picture(previous))
    paned.set_end_child(_picture(current))
    paned.set_wide_handle(True)
    paned.set_position(240)
    return paned


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
