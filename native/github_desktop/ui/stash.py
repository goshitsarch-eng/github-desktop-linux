"""Desktop-style stash diff viewer: header, file list, read-only diffs."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk

from ..models import CommittedFileChange, StashEntry, map_status, path_label
from ..settings import defaultStashedFilesWidth, tabSizeDefault
from .diff_view import DiffViewer
from .menus import attach_keyboard_resize, attach_paned_reset, clear_box


class StashDiffViewer(Gtk.Box):
    def __init__(
        self,
        *,
        on_restore: Callable[[], None],
        on_discard: Callable[[], None],
        on_select_file: Callable[[CommittedFileChange], None],
        on_close: Callable[[], None] | None = None,
        on_expand_hunk: Callable[[int, str], None] | None = None,
        on_expand_whole: Callable[[], None] | None = None,
        on_collapse: Callable[[], None] | None = None,
        on_open_submodule: Callable[[str], None] | None = None,
        on_image_mode: Callable[[str], None] | None = None,
        on_open_binary: Callable[[str], None] | None = None,
        files_width: int = defaultStashedFilesWidth,
        on_reset_width: Callable[[], None] | None = None,
        on_width_changed: Callable[[int], None] | None = None,
        get_min_width: Callable[[], int] | None = None,
        get_max_width: Callable[[], int] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("stash-diff-viewer")
        self._on_select_file = on_select_file
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header.add_css_class("stash-header")
        title = Gtk.Label(label="Stashed changes", xalign=0)
        title.add_css_class("heading")
        row = Gtk.Box(spacing=8)
        restore = Gtk.Button(label="Restore")
        restore.add_css_class("suggested-action")
        restore.connect("clicked", lambda *_: on_restore())
        discard = Gtk.Button(label="Discard")
        discard.add_css_class("destructive-action")
        discard.connect("clicked", lambda *_: on_discard())
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda *_: on_close and on_close())
        explain = Gtk.Label(label="Restore will move your stashed files to the Changes list.", xalign=0)
        explain.add_css_class("dim-label")
        explain.set_wrap(True)
        row.append(restore)
        row.append(discard)
        row.append(close_btn)
        row.append(explain)
        header.append(title)
        header.append(row)
        self.append(header)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        files_box.set_size_request(240, -1)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._file_list = Gtk.ListBox()
        self._file_list.add_css_class("boxed-list")
        self._file_list.connect("row-activated", self._on_row)
        scroller.set_child(self._file_list)
        files_box.append(scroller)
        paned.set_start_child(files_box)
        self.diff_view = DiffViewer(
            interactive=False,
            on_expand_hunk=on_expand_hunk,
            on_expand_whole=on_expand_whole,
            on_collapse=on_collapse,
            on_open_submodule=on_open_submodule,
            on_image_mode=on_image_mode,
            on_open_binary=on_open_binary,
        )
        paned.set_end_child(self.diff_view)
        paned.set_position(max(180, int(files_width or defaultStashedFilesWidth)))
        if on_reset_width is not None:
            attach_paned_reset(paned, on_reset_width)
        if on_width_changed is not None:
            def _on_stash_width(moved, *_args: object) -> None:
                pos = moved.get_position()
                if pos > 0:
                    on_width_changed(pos)

            paned.connect("notify::position", _on_stash_width)
        attach_keyboard_resize(
            files_box,
            get_width=lambda: int(paned.get_position()),
            on_resize=lambda width: paned.set_position(int(width)),
            get_min=get_min_width or (lambda: 100),
            get_max=get_max_width or (lambda: 350),
            description="Stash file list",
        )
        self._files_paned = paned
        self.append(paned)

    def refresh(
        self,
        stash: StashEntry | None,
        files: list[CommittedFileChange],
        selected: CommittedFileChange | None,
        diff,
        *,
        side_by_side: bool = False,
        image_mode: str = "TwoUp",
        hide_whitespace: bool = False,
        can_collapse: bool = False,
        tab_size: int = tabSizeDefault,
        loading: bool = False,
    ) -> None:
        clear_box(self._file_list)
        if loading and not files:
            row = Gtk.ListBoxRow()
            row.set_selectable(False)
            row.set_activatable(False)
            label = Gtk.Label(label="Loading…", xalign=0)
            label.add_css_class("dim-label")
            row.set_child(label)
            self._file_list.append(row)
            self.diff_view.render(None, loading=True)
            return
        for file in files:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=8)
            label = Gtk.Label(label=path_label(file.path, file.status), xalign=0, hexpand=True)
            badge = Gtk.Label(label=map_status(file.status))
            box.append(label)
            box.append(badge)
            row.set_child(box)
            row._file = file  # type: ignore[attr-defined]
            self._file_list.append(row)
            if selected and file.path == selected.path:
                self._file_list.select_row(row)
        path = selected.path if selected else ""
        self.diff_view.render(
            diff,
            path=path,
            side_by_side=side_by_side,
            image_mode=image_mode,
            show_checks=False,
            hide_whitespace=hide_whitespace,
            can_collapse=can_collapse,
            tab_size=tab_size,
        )

    def _on_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        file = getattr(row, "_file", None)
        if file is not None:
            self._on_select_file(file)
