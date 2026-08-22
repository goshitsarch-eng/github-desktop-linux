"""Interactive unified / side-by-side / image diffs with Desktop hunk expansion."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk, Pango

from ..git.diff import (
    DiffRangeType,
    find_interactive_diff_range,
    find_interactive_original_diff_range,
    hunk_line_span,
    side_by_side_rows,
)
from ..git.progress import format_bytes
from ..models import (
    DiffHunkExpansionType,
    DiffLine,
    DiffLineType,
    DiffSelection,
    DiffType,
    FileDiff,
    ImageDiff,
    ImageDiffType,
    SubmoduleDiff,
    TextDiff,
    shorten_sha,
    submodule_commit_change_copy,
    submodule_repository_link,
    submodule_working_changes_copy,
)
from ..settings import tabSizeDefault
from .menus import MenuItem, attach_right_click, clear_box, copy_text, show_context_menu
from .copy_button import CopyButton, copy_the_full_sha_label
from .syntax import markup_for_diff_line

# Desktop Linux `DiffOptions` button/header: `Diff ${__DARWIN__ ? 'Settings' : 'Options'}`.
DIFF_OPTIONS_LABEL = "Diff Options"
# Desktop `seamless-diff-switcher.tsx` — fade the previous Diff after this many ms.
SlowDiffLoadingThreshold = 150


def diff_search_no_results(query: str) -> str:
    """Desktop AriaLiveContainer `ariaLiveMessage`: `No results for "{searchQuery}"`."""
    return f'No results for "{query}"'


def diff_search_result_message(index: int, total: int, query: str) -> str:
    """Desktop AriaLiveContainer `ariaLiveMessage`: `Result N of M for "{searchQuery}"` (1-based)."""
    return f'Result {index} of {total} for "{query}"'


# Desktop `ariaLiveMessage: 'Expanded'` after expand hunk / expand whole file.
DIFF_EXPANDED_ARIA_LIVE = "Expanded"
# Desktop `selected-commits.tsx` renderDiff: don't show both empty messages.
NO_FILE_SELECTED = "No file selected"


def diff_expanded_aria_live() -> str:
    """Desktop `ariaLiveMessage: 'Expanded'` after expand hunk / expand whole file."""
    return DIFF_EXPANDED_ARIA_LIVE


def diff_no_file_blankslate(*, has_files: bool) -> str:
    """Desktop History Diff when `file == null`.

    `changesetData.files.length === 0` → empty string; otherwise `No file selected`.
    """
    return NO_FILE_SELECTED if has_files else ""


def last_expanded_hunk_key(hunk_index: int, expansion_type: DiffHunkExpansionType | str) -> str:
    """Desktop hunkExpansionRefs key `${hunkIndex}-${expansionType}`."""
    return f"{hunk_index}-{expansion_type}"


def expansion_hunk_key_index(key: str) -> int:
    """Desktop `getHunkKeyIndex` for `focusAfterLastExpandedHunkChange`."""
    head, _, _rest = key.partition("-")
    try:
        return int(head or "0")
    except ValueError:
        return 0


def closest_expansion_focus_key(
    keys: Sequence[str],
    hunk_index: int,
    expansion_type: DiffHunkExpansionType | str,
) -> str | None:
    """Desktop `focusAfterLastExpandedHunkChange` button key, or None to focus the list."""
    key_list = list(keys)
    if not key_list:
        return None
    last = last_expanded_hunk_key(hunk_index, expansion_type)
    if last in key_list:
        return last
    ordered = sorted(key_list)
    for key in ordered:
        if expansion_hunk_key_index(key) >= hunk_index:
            return key
    for key in reversed(ordered):
        if expansion_hunk_key_index(key) <= hunk_index:
            return key
    return None


focusAfterLastExpandedHunkChange = closest_expansion_focus_key


def diff_options_label() -> str:
    """Desktop Linux `DiffOptions` aria-label / popover header."""
    return DIFF_OPTIONS_LABEL

try:
    import cairo
except ImportError:
    cairo = None  # type: ignore[misc, assignment]

try:
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
except (ValueError, ImportError):
    GdkPixbuf = None  # type: ignore[misc, assignment]

VIRTUALIZE_AFTER = 400
# Desktop `MouseScroller`
DEFAULT_SCROLL_EDGE = 30
SCROLL_SPEED = 5


def get_discard_label(range_type: DiffRangeType | None, num_lines: int, *, confirm: bool = True) -> str:
    """Desktop `getDiscardLabel` (Linux: lowercase added/removed/modified)."""
    suffix = "…" if confirm else ""
    plural = "s" if num_lines > 1 else ""
    if range_type == DiffRangeType.ADDITIONS:
        return f"Discard added line{plural}{suffix}"
    if range_type == DiffRangeType.DELETIONS:
        return f"Discard removed line{plural}{suffix}"
    return f"Discard modified line{plural}{suffix}"


def get_hunk_handle_label(range_type: DiffRangeType | None, first: int | None, last: int | None) -> str:
    """Desktop hunk-handle sr-only: `Lines {first} to {last} added|deleted|modified`."""
    kind = "modified"
    if range_type == DiffRangeType.ADDITIONS:
        kind = "added"
    elif range_type == DiffRangeType.DELETIONS:
        kind = "deleted"
    start = first if first is not None else 0
    end = last if last is not None else start
    return f"Lines {start} to {end} {kind}"


def hunks_expand_whole_file_enabled(hunks: Sequence) -> bool:
    """Desktop `buildExpandMenuItem` `.enabled` when the diff is not already expanded."""
    if not hunks:
        return False
    first = hunks[0]
    return len(hunks) != 1 or first.expansion_type != DiffHunkExpansionType.NONE


def build_expand_menu_item(
    *,
    can_expand_diff: bool,
    is_expanded: bool,
    hunks: Sequence,
) -> tuple[str, bool] | None:
    """Desktop `buildExpandMenuItem` (Linux). ``None`` when the diff cannot expand."""
    if not can_expand_diff:
        return None
    if is_expanded:
        return ("Collapse expanded lines", True)
    return ("Expand whole file", hunks_expand_whole_file_enabled(hunks))


def is_only_one_check_in_row(found) -> bool:
    """Desktop `isOnlyOneCheckInRow`: hide hunk-handle check-all for a single line."""
    if found is None:
        return True
    return found.to_index <= found.from_index


def is_text_diff(diff: FileDiff | None) -> bool:
    """Desktop SeamlessDiffSwitcher `isTextDiff` (Text or LargeText)."""
    if diff is None:
        return False
    kind = getattr(diff, "kind", None)
    return kind in (DiffType.TEXT, DiffType.LARGE_TEXT)


def is_loading_diff(diff: FileDiff | None, *, file_contents: object | None = True) -> bool:
    """Desktop SeamlessDiffSwitcher `isLoadingDiff`.

    A text diff stays loading until old/new file contents are available. Native
    loads those in the git worker before handing a `TextDiff` to the viewer, so
    `file_contents` defaults to already-present.
    """
    if diff is None:
        return True
    if is_text_diff(diff):
        return file_contents is None
    return False


isLoadingDiff = is_loading_diff


def isLoadingSlow(
    is_loading: bool,
    elapsed_ms: int,
    threshold: int = SlowDiffLoadingThreshold,
) -> bool:
    """Desktop `isLoadingSlow` once `SlowDiffLoadingThreshold` has elapsed."""
    return bool(is_loading) and elapsed_ms >= threshold


def is_seamless_file_loading(
    diff: FileDiff | None,
    path: str = "",
    *,
    loading: bool | None = None,
) -> bool:
    """True while SeamlessDiffSwitcher should keep the previous Diff painted."""
    if diff is not None:
        return is_loading_diff(diff)
    if loading is not None:
        return bool(loading)
    return bool(path)


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
    paired: DiffLine | None = None


class DiffRowItem(GObject.Object):
    __gtype_name__ = "GitHubDesktopDiffRowItem"

    def __init__(self, spec: RowSpec) -> None:
        super().__init__()
        self.spec = spec


class DiffViewer(Gtk.Box):
    """Diff pane plus Desktop `SeamlessDiffSwitcher` loading overlay."""

    def __init__(
        self,
        *,
        interactive: bool = False,
        on_line_toggle: Callable[[str, int, bool], None] | None = None,
        on_line_range_toggle: Callable[[str, int, int, bool], None] | None = None,
        on_hunk_toggle: Callable[[str, int, int, bool], None] | None = None,
        on_discard_selection: Callable[[str], None] | None = None,
        on_discard_range: Callable[[str, int, int], None] | None = None,
        on_expand_hunk: Callable[[int, str], None] | None = None,
        on_expand_whole: Callable[[], None] | None = None,
        on_collapse: Callable[[], None] | None = None,
        on_expand: Callable[[], None] | None = None,
        on_image_mode: Callable[[str], None] | None = None,
        on_open_submodule: Callable[[str], None] | None = None,
        on_open_binary: Callable[[str], None] | None = None,
        on_hide_whitespace_changed: Callable[[bool], None] | None = None,
        on_side_by_side_changed: Callable[[bool], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class("diff-view")
        self.add_css_class("seamless-diff-switcher")
        self.interactive = interactive
        self.on_line_toggle = on_line_toggle
        self.on_line_range_toggle = on_line_range_toggle
        self.on_hunk_toggle = on_hunk_toggle
        self.on_discard_selection = on_discard_selection
        self.on_discard_range = on_discard_range
        self.on_expand_hunk = on_expand_hunk
        self.on_expand_whole = on_expand_whole or on_expand
        self.on_collapse = on_collapse
        self.on_expand = on_expand
        self.on_image_mode = on_image_mode
        self.on_open_submodule = on_open_submodule
        self.on_open_binary = on_open_binary
        self.on_hide_whitespace_changed = on_hide_whitespace_changed
        self.on_side_by_side_changed = on_side_by_side_changed
        self.view_github_label = "View on GitHub"
        overlay = Gtk.Overlay()
        overlay.set_hexpand(True)
        overlay.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.add_css_class("diff-switcher-content")
        content.set_hexpand(True)
        content.set_vexpand(True)
        self._overlay = overlay
        self._content = content
        self._toolbar = Gtk.Box(spacing=6)
        self._toolbar.add_css_class("diff-toolbar")
        content.append(self._toolbar)
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
        content.append(self._search_revealer)
        self._hint_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._hint_box.add_css_class("whitespace-hint")
        self._hint_box.set_visible(False)
        self._hint = Gtk.Label(xalign=0, wrap=True)
        self._hint_box.append(self._hint)
        show_ws = Gtk.Button(label="Yes")
        show_ws.add_css_class("pill")
        show_ws.add_css_class("suggested-action")
        show_ws.set_halign(Gtk.Align.START)
        show_ws.connect("clicked", self._on_show_whitespace)
        self._hint_show = show_ws
        no_ws = Gtk.Button(label="No")
        no_ws.add_css_class("pill")
        no_ws.set_halign(Gtk.Align.START)
        no_ws.connect("clicked", lambda *_: self._hint_box.set_visible(False))
        hint_btns = Gtk.Box(spacing=8)
        hint_btns.append(show_ws)
        hint_btns.append(no_ws)
        self._hint_box.append(hint_btns)
        content.append(self._hint_box)
        self._scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._scroll.set_child(self._inner)
        content.append(self._scroll)
        overlay.set_child(content)
        indicator = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        indicator.add_css_class("loading-indicator")
        indicator.set_halign(Gtk.Align.CENTER)
        indicator.set_valign(Gtk.Align.CENTER)
        try:
            indicator.set_can_target(False)
        except Exception:
            pass
        spinner = Gtk.Spinner()
        spinner.set_size_request(32, 32)
        indicator.append(spinner)
        indicator.set_visible(False)
        overlay.add_overlay(indicator)
        self._loading_indicator = indicator
        self._loading_spinner = spinner
        self.append(overlay)
        self._aria_live = Gtk.Label(label="")
        self._aria_live.add_css_class("sr-only")
        self._aria_live.set_visible(False)
        try:
            self._aria_live.update_property(
                [Gtk.AccessibleProperty.LIVE],
                [Gtk.AccessibleLive.POLITE],
            )
        except Exception:
            pass
        self.append(self._aria_live)
        self._aria_live_message = ""
        self._path = ""
        self._show_checks = True
        self._tab_size = tabSizeDefault
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
        self._side_by_side = False
        self._force_show_large = False
        self._ask_discard_confirm = True
        self._can_collapse = False
        self._temporary_selection: dict[str, int | bool] | None = None
        self._hovered_hunk: int | None = None
        self._scroll_timer_id = 0
        self._line_widgets: dict[int, list[Gtk.Widget]] = {}
        self._is_loading_diff = False
        self._is_loading_slow = False
        self._slow_timeout_id = 0
        self.lastExpandedHunk: tuple[int, DiffHunkExpansionType] | None = None
        self.hunkExpansionRefs: dict[str, Gtk.Widget] = {}
        self._expansion_focus_idle = 0
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_focusable(True)
        self.connect("destroy", lambda *_: self._clear_slow_loading_timeout())
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_gutter_motion)
        self.add_controller(motion)
        legacy = Gtk.EventControllerLegacy()
        legacy.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)

        def on_legacy(_controller, event) -> bool:
            if self._temporary_selection is None:
                return False
            try:
                etype = event.get_event_type()
            except Exception:
                return False
            release = getattr(Gdk.EventType, "BUTTON_RELEASE", None)
            if release is not None and etype == release:
                self._end_gutter_selection()
            return False

        legacy.connect("event", on_legacy)
        self.add_controller(legacy)

    @property
    def isLoadingDiff(self) -> bool:
        """Desktop SeamlessDiffSwitcher `isLoadingDiff`."""
        return self._is_loading_diff

    @property
    def isLoadingSlow(self) -> bool:
        """Desktop SeamlessDiffSwitcher `isLoadingSlow`."""
        return self._is_loading_slow

    @property
    def ariaLiveMessage(self) -> str:
        """Desktop SideBySideDiff `ariaLiveMessage` (expand + search)."""
        return self._aria_live_message

    def _announce_expanded(self) -> None:
        """Desktop `ariaLiveMessage: 'Expanded'` after expand hunk / expand whole file."""
        message = diff_expanded_aria_live()
        self._aria_live_message = message
        self._aria_live.set_text("")
        self._aria_live.set_text(message)

    def _on_expand_whole_clicked(self) -> None:
        if self.on_expand_whole:
            self.on_expand_whole()
        self._announce_expanded()

    def _on_expand_hunk_clicked(
        self,
        hunk_index: int,
        kind: str,
        expansion_type: DiffHunkExpansionType | None = None,
    ) -> None:
        if expansion_type is None:
            expansion_type = (
                DiffHunkExpansionType.DOWN if kind == "down" else DiffHunkExpansionType.UP
            )
        self.lastExpandedHunk = (hunk_index, expansion_type)
        if self.on_expand_hunk:
            self.on_expand_hunk(hunk_index, kind)
        self._announce_expanded()

    def _schedule_expansion_focus(self) -> None:
        """Desktop componentDidUpdate → focusAfterLastExpandedHunkChange."""
        if self.lastExpandedHunk is None or self._expansion_focus_idle:
            return
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._expansion_focus_idle = GLib.idle_add(self._focus_after_last_expanded_hunk_change)

    def _focus_after_last_expanded_hunk_change(self) -> bool:
        self._expansion_focus_idle = 0
        if self.lastExpandedHunk is None:
            return False
        hunk_index, expansion_type = self.lastExpandedHunk
        if not self.hunkExpansionRefs:
            if self._list_view is not None:
                self._list_view.grab_focus()
            elif self._inner.get_first_child() is not None:
                self._inner.grab_focus()
            return False
        key = closest_expansion_focus_key(
            self.hunkExpansionRefs.keys(), hunk_index, expansion_type
        )
        button = self.hunkExpansionRefs.get(key) if key else None
        if button is not None:
            button.grab_focus()
        elif self._list_view is not None:
            self._list_view.grab_focus()
        return False

    focusAfterLastExpandedHunkChange = _focus_after_last_expanded_hunk_change

    def _if_ready(self, callback: Callable | None, *args: object) -> None:
        """Desktop SeamlessDiffSwitcher noops include/discard/open while `isLoadingDiff`."""
        if self._is_loading_diff or callback is None:
            return
        callback(*args)

    def _set_loading_diff(self, loading: bool) -> None:
        began_or_finished = loading != self._is_loading_diff
        self._is_loading_diff = loading
        if began_or_finished:
            # Desktop resets `isLoadingSlow` when loading starts or finishes.
            self._is_loading_slow = False
            self._clear_slow_loading_timeout()
            if loading:
                self._schedule_slow_loading_timeout()
        if not loading:
            self._is_loading_slow = False
            self._clear_slow_loading_timeout()
        self._apply_loading_chrome()

    def _schedule_slow_loading_timeout(self) -> None:
        self._clear_slow_loading_timeout()
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._slow_timeout_id = GLib.timeout_add(
            SlowDiffLoadingThreshold, self._on_slow_loading_timeout
        )

    def _clear_slow_loading_timeout(self) -> None:
        if self._slow_timeout_id:
            GLib.source_remove(self._slow_timeout_id)
            self._slow_timeout_id = 0

    def _on_slow_loading_timeout(self) -> bool:
        self._slow_timeout_id = 0
        if self._is_loading_diff:
            self._is_loading_slow = True
            self._apply_loading_chrome()
        return False

    def _apply_loading_chrome(self) -> None:
        has_diff = self._diff is not None
        for name in ("loading", "slow", "has-diff"):
            self.remove_css_class(name)
        if has_diff:
            self.add_css_class("has-diff")
        if self._is_loading_diff:
            self.add_css_class("loading")
            if self._is_loading_slow:
                self.add_css_class("slow")
        show_spinner = self._is_loading_diff and (not has_diff or self._is_loading_slow)
        self._loading_indicator.set_visible(show_spinner)
        if show_spinner:
            self._loading_spinner.start()
        else:
            self._loading_spinner.stop()
        fade = self._is_loading_diff and has_diff and self._is_loading_slow
        self._content.set_opacity(0.2 if fade else 1.0)

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
        tab_size: int = tabSizeDefault,
        comments: list | None = None,
        ask_discard_confirm: bool = True,
        loading: bool | None = None,
        has_files: bool = True,
    ) -> None:
        # Desktop `propSnapshot`: keep the previous Diff painted until the next one is ready.
        if is_seamless_file_loading(diff, path, loading=loading):
            self._set_loading_diff(True)
            return
        if path != self._path:
            self._force_show_large = False
            self.lastExpandedHunk = None
        self._path = path
        self._show_checks = show_checks
        self._tab_size = max(1, tab_size)
        self._selection = selection
        self._comments = list(comments or [])
        self._ask_discard_confirm = ask_discard_confirm
        self._can_collapse = can_collapse
        self._temporary_selection = None
        self._hovered_hunk = None
        self._clear_scroll_timer()
        self._line_widgets = {}
        self._row_specs = []
        self._row_widgets = []
        self.hunkExpansionRefs = {}
        self._list_view = None
        clear_box(self._toolbar)
        self._hint_box.set_visible(False)
        self._scroll.set_child(self._inner)
        clear_box(self._inner)
        self._list_store = None
        self._diff = diff
        self._set_loading_diff(False)
        self._hide_whitespace = hide_whitespace
        self._side_by_side = side_by_side
        if diff is None:
            message = diff_no_file_blankslate(has_files=has_files)
            if message:
                self._inner.append(
                    Adw.StatusPage(title=message, icon_name="document-symbolic")
                )
            else:
                empty = Gtk.Box()
                empty.set_name("diff")
                empty.add_css_class("panel")
                empty.add_css_class("blankslate")
                empty.set_hexpand(True)
                empty.set_vexpand(True)
                self._inner.append(empty)
            return
        kind = getattr(diff, "kind", None)
        if kind == DiffType.BINARY:
            page = Adw.StatusPage(title="This binary file has changed.")
            page.add_css_class("binary")
            if self.on_open_binary and path:
                btn = Gtk.Button(label="Open file in external program.")
                btn.add_css_class("pill")
                btn.add_css_class("suggested-action")
                btn.set_halign(Gtk.Align.CENTER)
                btn.connect("clicked", lambda *_: self._if_ready(self.on_open_binary, self._path))
                page.set_child(btn)
            self._inner.append(page)
            self._add_diff_options()
            return
        if kind == DiffType.IMAGE and isinstance(diff, ImageDiff):
            prev = _pixbuf_from_bytes(diff.previous)
            curr = _pixbuf_from_bytes(diff.current)
            if self._path.lower().endswith(".dds") and not prev and not curr:
                self._inner.append(
                    Adw.StatusPage(
                        title="Can't preview .dds on Linux",
                        description="DirectDraw Surface files need a DDS decoder Desktop ships for Electron. Open the file in an external editor to compare.",
                    )
                )
                self._add_diff_options()
                return
            self._render_image(diff, image_mode)
            self._add_diff_options()
            return
        if kind == DiffType.UNRENDERABLE:
            page = Adw.StatusPage(title="The diff is too large to be displayed.")
            if self.on_open_binary and path:
                btn = Gtk.Button(label="Open in default program")
                btn.add_css_class("pill")
                btn.connect("clicked", lambda *_: self._if_ready(self.on_open_binary, self._path))
                page.set_child(btn)
            self._inner.append(page)
            self._add_diff_options()
            return
        if kind == DiffType.LARGE_TEXT and not self._force_show_large:
            page = Adw.StatusPage(
                title="The diff is too large to be displayed by default.",
                description="You can try to show it anyway, but performance may be negatively impacted.",
            )
            actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            actions.set_halign(Gtk.Align.CENTER)
            show = Gtk.Button(label="Show diff")
            show.add_css_class("pill")
            show.add_css_class("suggested-action")
            show.connect("clicked", lambda *_: self._show_large_diff())
            actions.append(show)
            if self.on_open_binary and path:
                open_btn = Gtk.Button(label="Open in default program")
                open_btn.add_css_class("pill")
                open_btn.connect("clicked", lambda *_: self._if_ready(self.on_open_binary, self._path))
                actions.append(open_btn)
            page.set_child(actions)
            self._inner.append(page)
            self._add_diff_options()
            return
        if kind == DiffType.LARGE_TEXT:
            from ..models import LargeTextDiff

            if isinstance(diff, LargeTextDiff):
                diff = TextDiff(
                    text=diff.text,
                    hunks=list(diff.hunks),
                    line_endings_change=diff.line_endings_change,
                    max_line_number=diff.max_line_number,
                    has_hidden_bidi_chars=diff.has_hidden_bidi_chars,
                )
        if kind == DiffType.SUBMODULE:
            self._render_submodule(diff)
            self._add_diff_options()
            return
        if not isinstance(diff, TextDiff):
            self._inner.append(Gtk.Label(label="Unable to display this diff"))
            return
        if hide_whitespace:
            self._hint.set_text("Show whitespace changes?\nSelecting lines is disabled when hiding whitespace changes.")
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
        self._schedule_expansion_focus()
        if self._search_revealer.get_reveal_child() and self._search_query:
            self._run_search(self._search_query, "next")

    def _fill_toolbar(self, diff: TextDiff, can_collapse: bool) -> None:
        expandable = any(h.expansion_type != DiffHunkExpansionType.NONE for h in diff.hunks)
        if expandable and self.on_expand_whole:
            whole = Gtk.Button(label="Expand whole file")
            whole.add_css_class("flat")
            whole.connect("clicked", lambda *_: self._on_expand_whole_clicked())
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
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        self._toolbar.append(spacer)
        self._add_diff_options()

    def _add_diff_options(self) -> None:
        """Desktop `DiffOptions` popover: hide whitespace + unified/split display."""
        btn = Gtk.MenuButton()
        btn.add_css_class("flat")
        btn.add_css_class("diff-options-component")
        btn.set_icon_name("emblem-system-symbolic")
        btn.set_tooltip_text(diff_options_label())
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("diff-options-popover")
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(12)
        box.set_margin_end(12)
        heading = Gtk.Label(label=diff_options_label(), xalign=0)
        heading.add_css_class("heading")
        box.append(heading)
        ws_legend = Gtk.Label(label="Whitespace", xalign=0)
        ws_legend.add_css_class("diff-options-legend")
        box.append(ws_legend)
        hide = Gtk.CheckButton(label="Hide whitespace changes")
        hide.set_active(self._hide_whitespace)

        def on_hide(check: Gtk.CheckButton) -> None:
            hidden = check.get_active()
            self._hide_whitespace = hidden
            self._if_ready(self.on_hide_whitespace_changed, hidden)

        hide.connect("toggled", on_hide)
        box.append(hide)
        if self.interactive:
            note = Gtk.Label(
                label="Interacting with individual lines or hunks will be disabled while hiding whitespace.",
                wrap=True,
                xalign=0,
            )
            note.add_css_class("dim-label")
            note.add_css_class("secondary-text")
            box.append(note)
        display_legend = Gtk.Label(label="Diff display", xalign=0)
        display_legend.add_css_class("diff-options-legend")
        box.append(display_legend)
        unified = Gtk.CheckButton(label="Unified")
        split = Gtk.CheckButton(label="Split")
        split.set_tooltip_text("Side-by-side")
        split.set_group(unified)
        unified.set_active(not self._side_by_side)
        split.set_active(self._side_by_side)

        def on_unified(check: Gtk.CheckButton) -> None:
            if check.get_active() and self.on_side_by_side_changed:
                self.on_side_by_side_changed(False)

        def on_split(check: Gtk.CheckButton) -> None:
            if check.get_active() and self.on_side_by_side_changed:
                self.on_side_by_side_changed(True)

        unified.connect("toggled", on_unified)
        split.connect("toggled", on_split)
        box.append(unified)
        box.append(split)
        popover.set_child(box)
        btn.set_popover(popover)
        self._toolbar.append(btn)

    def start_search(self) -> None:
        self._search_revealer.set_reveal_child(True)
        self._search_entry.grab_focus()

    def _show_large_diff(self, *_args: object) -> None:
        self._force_show_large = True
        if self._diff is not None:
            self.render(
                self._diff,
                path=self._path,
                selection=self._selection,
                hide_whitespace=self._hide_whitespace,
            )

    def _on_show_whitespace(self, *_args: object) -> None:
        self._hide_whitespace = False
        self._hint_box.set_visible(False)
        self._if_ready(self.on_hide_whitespace_changed, False)

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
            self._search_count.set_text(diff_search_no_results(query))
            self._apply_search_highlight()
            return
        self._search_count.set_text(
            diff_search_result_message(self._search_cursor + 1, len(matches), query)
        )
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
        """Desktop `SubmoduleDiff` interstitial (`submodule-diff.tsx`)."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.add_css_class("submodule-diff")
        box.set_margin_top(24)
        box.set_margin_start(24)
        box.set_margin_end(24)
        title = Gtk.Label(label="Submodule changes", xalign=0)
        title.add_css_class("title-1")
        box.append(title)
        url = getattr(diff, "url", None)
        link_info = submodule_repository_link(url)
        if link_info:
            uri, caption = link_info
            info = Gtk.Box(spacing=6)
            info_label = Gtk.Label(label="This is a submodule based on the repository ", xalign=0)
            info_label.set_wrap(True)
            link = Gtk.LinkButton(uri=uri, label=caption)
            link.set_halign(Gtk.Align.START)
            info.append(info_label)
            info.append(link)
            box.append(info)
        old_sha = getattr(diff, "old_sha", None)
        new_sha = getattr(diff, "new_sha", None)
        read_only = not self.interactive
        change_copy = submodule_commit_change_copy(old_sha, new_sha, read_only=read_only)
        if change_copy:
            change = Gtk.Label(label=change_copy, xalign=0, wrap=True)
            box.append(change)
            if old_sha and new_sha:
                self._append_sha_copy(box, old_sha, "previous")
                self._append_sha_copy(box, new_sha, "new")
            elif new_sha:
                self._append_sha_copy(box, new_sha, None)
            elif old_sha:
                self._append_sha_copy(box, old_sha, None)
        working = submodule_working_changes_copy(getattr(diff, "status", None))
        if working:
            box.append(Gtk.Label(label=working, xalign=0, wrap=True))
        full = getattr(diff, "full_path", "") or ""
        # Desktop hides Open when `diff.url === null` (deleted submodule in history).
        if url is not None and self.on_open_submodule:
            action = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            action_title = Gtk.Label(label="Open this submodule on GitHub Desktop", xalign=0)
            action_title.add_css_class("heading")
            action_desc = Gtk.Label(
                label=(
                    "You can open this submodule on GitHub Desktop as a normal "
                    "repository to manage and commit any changes in it."
                ),
                xalign=0,
                wrap=True,
            )
            open_btn = Gtk.Button(label="Open repository")
            open_btn.add_css_class("suggested-action")
            open_btn.set_halign(Gtk.Align.START)
            if full:
                open_btn.connect(
                    "clicked",
                    lambda *_a, p=full: self._if_ready(self.on_open_submodule, p),
                )
            else:
                open_btn.set_sensitive(False)
            action.append(action_title)
            action.append(action_desc)
            action.append(open_btn)
            box.append(action)
        elif isinstance(diff, SubmoduleDiff) and not full:
            box.append(Gtk.Label(label="This submodule isn't checked out locally.", xalign=0))
        self._inner.append(box)

    def _append_sha_copy(self, box: Gtk.Box, sha: str, which: str | None) -> None:
        row = Gtk.Box(spacing=8)
        row.append(Gtk.Label(label=shorten_sha(sha), xalign=0))
        copy = CopyButton(copy_content=sha, aria_label=copy_the_full_sha_label(which))
        row.append(copy)
        box.append(row)

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
            for i, line in enumerate(hunk.lines):
                idx = line.diff_line_number if line.diff_line_number is not None else start
                if line.kind == DiffLineType.HUNK:
                    rows.append(
                        RowSpec("hunk", hunk_index, hunk.expansion_type, start, length, line=line)
                    )
                    continue
                paired = None
                if line.kind == DiffLineType.DELETE and i + 1 < len(hunk.lines) and hunk.lines[i + 1].kind == DiffLineType.ADD:
                    paired = hunk.lines[i + 1]
                elif line.kind == DiffLineType.ADD and i > 0 and hunk.lines[i - 1].kind == DiffLineType.DELETE:
                    paired = hunk.lines[i - 1]
                rows.append(
                    RowSpec(
                        "unified",
                        hunk_index,
                        hunk.expansion_type,
                        start,
                        length,
                        line=line,
                        index=idx,
                        paired=paired,
                    )
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
            widget = self._unified_line(spec.line, spec.index, selection, paired=spec.paired)
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

            link = Gtk.Button(label=self.view_github_label)
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
                lambda btn, s=start, n=length: self._if_ready(self.on_hunk_toggle, self._path, s, n, btn.get_active()),
            )
            row.append(check)
        row.append(self._expansion_buttons(hunk_index, expansion))
        label = Gtk.Label(label=line.text or "Expand remaining file", xalign=0, hexpand=True)
        label.add_css_class("diff-hunk-text")
        row.append(label)
        hover = Gtk.EventControllerMotion()
        hover_index = start + 1 if length > 1 else start
        hover.connect("enter", lambda *_a, i=hover_index: self._set_hovered_hunk(i))
        hover.connect("leave", lambda *_a: self._set_hovered_hunk(None))
        row.add_controller(hover)
        attach_right_click(row, lambda *_: self._hunk_menu(start, length, selection, hunk_index, expansion))
        return row

    def _expansion_buttons(self, hunk_index: int, expansion: DiffHunkExpansionType) -> Gtk.Widget:
        box = Gtk.Box(spacing=2)

        def add_btn(
            label: str,
            tooltip: str,
            kind: str,
            expand_index: int,
            expansion_type: DiffHunkExpansionType,
            header_index: int,
        ) -> None:
            btn = Gtk.Button(label=label)
            btn.add_css_class("flat")
            btn.add_css_class("diff-expand")
            btn.set_tooltip_text(tooltip)
            key = last_expanded_hunk_key(header_index, expansion_type)
            self.hunkExpansionRefs[key] = btn
            btn.connect(
                "clicked",
                lambda *_: self._on_expand_hunk_clicked(
                    expand_index, kind, expansion_type
                ),
            )
            box.append(btn)

        if expansion == DiffHunkExpansionType.UP:
            add_btn("▲", "Expand up", "up", hunk_index, DiffHunkExpansionType.UP, hunk_index)
        elif expansion == DiffHunkExpansionType.DOWN:
            add_btn(
                "▼",
                "Expand down",
                "down",
                hunk_index - 1,
                DiffHunkExpansionType.DOWN,
                hunk_index,
            )
        elif expansion == DiffHunkExpansionType.SHORT:
            add_btn(
                "↕", "Expand all", "up", hunk_index, DiffHunkExpansionType.SHORT, hunk_index
            )
        elif expansion == DiffHunkExpansionType.BOTH:
            add_btn(
                "▼",
                "Expand down",
                "down",
                hunk_index - 1,
                DiffHunkExpansionType.DOWN,
                hunk_index,
            )
            add_btn("▲", "Expand up", "up", hunk_index, DiffHunkExpansionType.UP, hunk_index)
        return box

    def _line_body(self, line: DiffLine) -> str:
        body = line.text[1:] if line.text[:1] in "+- " else line.text
        return body.replace("\t", " " * max(1, self._tab_size))

    def _markup(self, line: DiffLine, paired: DiffLine | None = None) -> str:
        old_map = getattr(self._diff, "old_line_markup", None) if self._diff is not None else None
        new_map = getattr(self._diff, "new_line_markup", None) if self._diff is not None else None
        markup = markup_for_diff_line(
            line,
            self._path,
            old_markup=old_map,
            new_markup=new_map,
            tab_size=self._tab_size,
        )
        if paired is None:
            return markup
        from ..changed_range import apply_inner_highlight, get_diff_tokens, inner_highlight_background

        before = self._line_body(line if line.kind == DiffLineType.DELETE else paired)
        after = self._line_body(line if line.kind == DiffLineType.ADD else paired)
        if line.kind not in {DiffLineType.ADD, DiffLineType.DELETE}:
            return markup
        if line.kind == DiffLineType.DELETE and paired.kind != DiffLineType.ADD:
            return markup
        if line.kind == DiffLineType.ADD and paired.kind != DiffLineType.DELETE:
            return markup
        delete_range, add_range = get_diff_tokens(before, after)
        span = add_range if line.kind == DiffLineType.ADD else delete_range
        return apply_inner_highlight(
            markup,
            span.location,
            span.length,
            inner_highlight_background(line.kind == DiffLineType.ADD),
        )

    def _newline_marker(self, line: DiffLine | None) -> Gtk.Widget | None:
        if line is None or not line.no_trailing_newline:
            return None
        mark = Gtk.Label(label="↵")
        mark.add_css_class("diff-no-newline")
        mark.set_tooltip_text("No newline at end of file")
        return mark

    def _can_select_lines(self) -> bool:
        return (
            self.interactive
            and self._show_checks
            and not getattr(self, "_hide_whitespace", False)
            and (self.on_line_toggle is not None or self.on_line_range_toggle is not None)
        )

    def _register_line_widget(self, index: int | None, widget: Gtk.Widget) -> None:
        if index is None:
            return
        widget._diff_line_index = index  # type: ignore[attr-defined]
        self._line_widgets.setdefault(index, []).append(widget)

    def _line_index_from_widget(self, widget: Gtk.Widget | None) -> int | None:
        current = widget
        while current is not None:
            index = getattr(current, "_diff_line_index", None)
            if isinstance(index, int):
                return index
            current = current.get_parent()
        return None

    def _start_gutter_selection(self, index: int, is_selected: bool) -> None:
        if not self._can_select_lines():
            if getattr(self, "_hide_whitespace", False):
                self._hint_box.set_visible(True)
            return
        self._hovered_hunk = None
        self._temporary_selection = {"from": index, "to": index, "is_selected": is_selected}
        self._refresh_gutter_css()

    def _update_gutter_selection(self, index: int) -> None:
        tmp = self._temporary_selection
        if tmp is None or tmp.get("to") == index:
            return
        tmp["to"] = index
        self._refresh_gutter_css()

    def _end_gutter_selection(self) -> None:
        tmp = self._temporary_selection
        if tmp is None:
            return
        self._temporary_selection = None
        self._clear_scroll_timer()
        self._refresh_gutter_css()
        from_index = int(tmp["from"])
        to_index = int(tmp["to"])
        included = bool(tmp["is_selected"])
        start = min(from_index, to_index)
        end = max(from_index, to_index)
        if self._is_loading_diff:
            return
        if self.on_line_range_toggle:
            self.on_line_range_toggle(self._path, start, end, included)
            return
        if self.on_line_toggle:
            for index in range(start, end + 1):
                self.on_line_toggle(self._path, index, included)

    def _on_gutter_motion(self, _controller, x: float, y: float) -> None:
        if self._temporary_selection is None:
            return
        ok, _sx, sy = (False, x, y)
        translated = self.translate_coordinates(self._scroll, x, y)
        if translated is not None:
            if isinstance(translated, tuple) and len(translated) == 3:
                ok, _sx, sy = translated
            elif isinstance(translated, tuple) and len(translated) == 2:
                ok, sy = True, translated[1]
        if ok:
            self._setup_mouse_scroll(sy)
        try:
            picked = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        except Exception:
            picked = None
        index = self._line_index_from_widget(picked)
        if index is not None:
            self._update_gutter_selection(index)

    def _setup_mouse_scroll(self, y_in_scroll: float) -> None:
        """Desktop `MouseScroller.setupMouseScroll` (vertical only)."""
        self._clear_scroll_timer()
        if self._scroll_vertically_on_mouse_near_edge(y_in_scroll):
            def tick(y=y_in_scroll) -> bool:
                self._scroll_timer_id = 0
                if self._temporary_selection is None:
                    return False
                self._setup_mouse_scroll(y)
                return False

            self._scroll_timer_id = GLib.timeout_add(30, tick)

    def _clear_scroll_timer(self) -> None:
        timer = getattr(self, "_scroll_timer_id", 0)
        if timer:
            GLib.source_remove(timer)
            self._scroll_timer_id = 0

    def _scroll_vertically_on_mouse_near_edge(self, y_in_scroll: float) -> bool:
        adj = self._scroll.get_vadjustment()
        height = self._scroll.get_allocated_height()
        if not height or adj is None:
            return False
        distance_from_bottom = height - y_in_scroll
        distance_from_top = y_in_scroll
        value = adj.get_value()
        lower = adj.get_lower()
        upper = adj.get_upper() - adj.get_page_size()
        if 0 < distance_from_bottom < DEFAULT_SCROLL_EDGE:
            if value >= upper:
                return False
            distance = max(distance_from_bottom, 1)
            adj.set_value(min(upper, value + SCROLL_SPEED * (DEFAULT_SCROLL_EDGE / distance)))
            return True
        if 0 < distance_from_top < DEFAULT_SCROLL_EDGE:
            if value <= lower:
                return False
            distance = max(distance_from_top, 1)
            adj.set_value(max(lower, value - SCROLL_SPEED * (DEFAULT_SCROLL_EDGE / distance)))
            return True
        return False

    def _refresh_gutter_css(self) -> None:
        hover_range: tuple[int, int] | None = None
        if (
            self._temporary_selection is None
            and self._hovered_hunk is not None
            and isinstance(self._diff, TextDiff)
        ):
            found = find_interactive_diff_range(self._diff.hunks, self._hovered_hunk)
            if found is not None:
                hover_range = (found.from_index, found.to_index)
        tmp = self._temporary_selection
        sel_range = None
        if tmp is not None:
            sel_range = (min(int(tmp["from"]), int(tmp["to"])), max(int(tmp["from"]), int(tmp["to"])))
        for index, widgets in self._line_widgets.items():
            selecting = sel_range is not None and sel_range[0] <= index <= sel_range[1]
            hovering = hover_range is not None and hover_range[0] <= index <= hover_range[1]
            for widget in widgets:
                if selecting:
                    widget.add_css_class("diff-gutter-selecting")
                else:
                    widget.remove_css_class("diff-gutter-selecting")
                if hovering and not selecting:
                    widget.add_css_class("diff-hunk-hover")
                else:
                    widget.remove_css_class("diff-hunk-hover")

    def _set_hovered_hunk(self, index: int | None) -> None:
        if self._temporary_selection is not None:
            return
        if self._hovered_hunk == index:
            return
        self._hovered_hunk = index
        self._refresh_gutter_css()

    def _attach_gutter_drag(self, widget: Gtk.Widget, index: int) -> None:
        widget.add_css_class("diff-gutter")
        self._register_line_widget(index, widget)
        click = Gtk.GestureClick()
        click.set_button(1)

        def on_pressed(_g, n_press, _x, _y, i=index) -> None:
            if n_press != 1:
                return
            currently = self._selection.is_selected(i) if self._selection else True
            self._start_gutter_selection(i, not currently)

        click.connect("pressed", on_pressed)
        widget.add_controller(click)
        drag = Gtk.GestureDrag()
        drag.set_button(1)

        def on_update(gesture, offset_x, offset_y, i=index) -> None:
            if self._temporary_selection is None:
                currently = self._selection.is_selected(i) if self._selection else True
                self._start_gutter_selection(i, not currently)
            origin = gesture.get_widget()
            start = gesture.get_start_point()
            if start is None:
                return
            if isinstance(start, tuple) and len(start) == 3:
                ok, sx, sy = start
                if not ok:
                    return
            elif isinstance(start, tuple) and len(start) == 2:
                sx, sy = start
            else:
                return
            if origin is None:
                return
            translated = origin.translate_coordinates(self, sx + offset_x, sy + offset_y)
            if translated is None:
                return
            if isinstance(translated, tuple) and len(translated) == 3:
                ok, vx, vy = translated
                if not ok:
                    return
            elif isinstance(translated, tuple) and len(translated) == 2:
                vx, vy = translated
            else:
                return
            try:
                picked = self.pick(vx, vy, Gtk.PickFlags.DEFAULT)
            except Exception:
                return
            found = self._line_index_from_widget(picked)
            if found is not None:
                self._update_gutter_selection(found)

        def on_end(_g, _ox, _oy) -> None:
            self._end_gutter_selection()

        drag.connect("drag-update", on_update)
        drag.connect("drag-end", on_end)
        widget.add_controller(drag)

    def _discard_line(self, index: int) -> None:
        if self._is_loading_diff:
            return
        if self.on_discard_range:
            self.on_discard_range(self._path, index, index)
        elif self.on_discard_selection:
            self.on_discard_selection(self._path)

    def _discard_range(self, start: int, end: int) -> None:
        if self._is_loading_diff:
            return
        if self.on_discard_range:
            self.on_discard_range(self._path, start, end)
        elif self.on_discard_selection:
            self.on_discard_selection(self._path)

    def _interactive_range(self, index: int):
        if not isinstance(self._diff, TextDiff):
            return None
        return find_interactive_original_diff_range(self._diff.hunks, index)

    def _range_line_numbers(self, found) -> tuple[int | None, int | None]:
        if not isinstance(self._diff, TextDiff):
            return found.from_index, found.to_index
        first = last = None
        for hunk in self._diff.hunks:
            for line in hunk.lines:
                number = line.diff_line_number
                if number is None:
                    continue
                if found.from_index <= number <= found.to_index and line.selectable:
                    displayed = line.new_line_number or line.old_line_number
                    if first is None:
                        first = displayed
                    last = displayed
        return first, last

    def _hunk_handle(self, index: int, selection: DiffSelection | None) -> Gtk.Widget | None:
        """Desktop overlay `.hunk-handle` check-all for groups of more than one line."""
        if not self.interactive or not self._show_checks or getattr(self, "_hide_whitespace", False):
            return None
        found = self._interactive_range(index)
        if is_only_one_check_in_row(found) or found is None:
            return None
        if index != found.from_index:
            return None
        check = Gtk.CheckButton()
        check.add_css_class("hunk-handle")
        included = True
        if selection is not None:
            selectable = [
                i
                for i in range(found.from_index, found.to_index + 1)
                if selection.is_selectable(i)
            ]
            included = bool(selectable) and all(selection.is_selected(i) for i in selectable)
            if selectable and not included and any(selection.is_selected(i) for i in selectable):
                check.set_inconsistent(True)
        check.set_active(included)
        first, last = self._range_line_numbers(found)
        check.set_tooltip_text(get_hunk_handle_label(found.type, first, last))
        check.set_valign(Gtk.Align.START)

        def on_toggled(btn, lo=found.from_index, hi=found.to_index) -> None:
            included = btn.get_active()
            if self._is_loading_diff:
                return
            if self.on_line_range_toggle:
                self.on_line_range_toggle(self._path, lo, hi, included)
            elif self.on_hunk_toggle:
                self.on_hunk_toggle(self._path, lo, hi - lo + 1, included)

        check.connect("toggled", on_toggled)
        return check

    def _configure_diff_text(self, label: Gtk.Label) -> None:
        """Desktop `_side-by-side-diff.scss` `.content`: `pre-wrap` + `break-all`."""
        label.set_use_markup(True)
        label.set_selectable(True)
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.CHAR)

    def _unified_line(
        self,
        line: DiffLine,
        index: int,
        selection: DiffSelection | None,
        paired: DiffLine | None = None,
    ) -> Gtk.Widget:
        row = Gtk.Box(spacing=8)
        row.add_css_class("diff-line")
        if line.kind == DiffLineType.ADD:
            row.add_css_class("diff-add")
        elif line.kind == DiffLineType.DELETE:
            row.add_css_class("diff-del")
        handle = self._hunk_handle(index, selection)
        if handle is not None:
            row.append(handle)
        if self.interactive and self._show_checks and line.selectable and not getattr(self, "_hide_whitespace", False):
            check = Gtk.CheckButton()
            active = selection.is_selected(index) if selection else True
            check.set_active(active)
            if not active:
                row.add_css_class("diff-excluded")
            check.connect(
                "toggled",
                lambda btn, i=index: self._if_ready(self.on_line_toggle, self._path, i, btn.get_active()),
            )
            row.append(check)
        old = Gtk.Label(label=str(line.old_line_number or ""))
        new = Gtk.Label(label=str(line.new_line_number or ""))
        old.add_css_class("diff-num")
        new.add_css_class("diff-num")
        text = Gtk.Label(xalign=0, hexpand=True)
        self._configure_diff_text(text)
        prefix = line.text[:1] if line.text[:1] in "+- " else " "
        text.set_markup(f"{prefix}{self._markup(line, paired)}")
        if paired is not None:
            text.add_css_class("diff-add-inner" if line.kind == DiffLineType.ADD else "diff-delete-inner")
        row.append(old)
        row.append(new)
        row.append(text)
        marker = self._newline_marker(line)
        if marker is not None:
            row.append(marker)
        self._register_line_widget(index, row)
        if line.selectable:
            hover = Gtk.EventControllerMotion()
            hover.connect("enter", lambda *_a, i=index: self._set_hovered_hunk(i))
            hover.connect("leave", lambda *_a: self._set_hovered_hunk(None))
            row.add_controller(hover)
            if self.interactive:
                self._attach_gutter_drag(old, index)
                self._attach_gutter_drag(new, index)
        attach_right_click(row, lambda *_ , i=index: self._line_menu(i, selection, line))
        return row

    def _split_row(self, spec: RowSpec, selection: DiffSelection | None) -> Gtk.Widget:
        row = Gtk.Box(spacing=0)
        row.add_css_class("diff-line")
        left_box = self._split_cell(spec.left, spec.left_i, selection, delete=True, paired=spec.right)
        right_box = self._split_cell(spec.right, spec.right_i, selection, delete=False, paired=spec.left)
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
        paired: DiffLine | None = None,
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
        if index is not None:
            handle = self._hunk_handle(index, selection)
            if handle is not None:
                box.append(handle)
        if self.interactive and self._show_checks and line.selectable and index is not None and not getattr(self, "_hide_whitespace", False):
            check = Gtk.CheckButton()
            active = selection.is_selected(index) if selection else True
            check.set_active(active)
            check.connect(
                "toggled",
                lambda btn, i=index: self._if_ready(self.on_line_toggle, self._path, i, btn.get_active()),
            )
            box.append(check)
        num = line.old_line_number if delete else line.new_line_number
        nlab = Gtk.Label(label=str(num or ""))
        nlab.add_css_class("diff-num")
        text = Gtk.Label(xalign=0, hexpand=True)
        self._configure_diff_text(text)
        text.set_markup(self._markup(line, paired))
        if paired is not None and line.kind in {DiffLineType.ADD, DiffLineType.DELETE}:
            text.add_css_class("diff-add-inner" if line.kind == DiffLineType.ADD else "diff-delete-inner")
        box.append(nlab)
        box.append(text)
        marker = self._newline_marker(line)
        if marker is not None:
            box.append(marker)
        if index is not None:
            self._register_line_widget(index, box)
            if line.selectable:
                hover = Gtk.EventControllerMotion()
                hover.connect("enter", lambda *_a, i=index: self._set_hovered_hunk(i))
                hover.connect("leave", lambda *_a: self._set_hovered_hunk(None))
                box.add_controller(hover)
                if self.interactive:
                    self._attach_gutter_drag(nlab, index)
            attach_right_click(box, lambda *_ , i=index, ln=line: self._line_menu(i, selection, ln))
        return box

    def _line_menu(self, index: int, selection: DiffSelection | None, line: DiffLine | None = None) -> None:
        """Desktop line-number discard menu plus `onContextMenuText` (Copy / Select all / expand)."""
        items: list[MenuItem] = []
        if self.interactive and selection is not None and not getattr(self, "_hide_whitespace", False):
            selected = selection.is_selected(index)
            items.append(
                (
                    "Exclude line" if selected else "Include line",
                    lambda: self._if_ready(self.on_line_toggle, self._path, index, not selected),
                    True,
                )
            )
            found = self._interactive_range(index)
            if found is not None and found.type is not None:
                items.append(
                    (
                        get_discard_label(found.type, 1, confirm=self._ask_discard_confirm),
                        lambda i=index: self._discard_line(i),
                        True,
                    )
                )
            items.append(None)
        copied = (line.text[1:] if line and line.text[:1] in "+- " else (line.text if line else ""))
        items.append(("Copy", lambda: copy_text(copied), bool(copied)))
        items.append(("Select all", self._select_all_text, True))
        expand = build_expand_menu_item(
            can_expand_diff=bool(self.on_expand_whole or self.on_collapse),
            is_expanded=bool(self._can_collapse),
            hunks=list(getattr(self._diff, "hunks", None) or []),
        )
        if expand is not None:
            label, enabled = expand
            items.append(None)
            if label == "Collapse expanded lines":
                items.append((label, lambda: self.on_collapse and self.on_collapse(), enabled))
            else:
                items.append((label, self._on_expand_whole_clicked, enabled))
        show_context_menu(self, items)

    def _select_all_text(self) -> None:
        """Desktop diff `onSelectAll` / `selectAllChildren` of the diff container."""
        def walk(node: Gtk.Widget) -> None:
            if isinstance(node, Gtk.Label):
                try:
                    if node.get_selectable():
                        node.select_region(0, -1)
                except Exception:
                    pass
            child = node.get_first_child() if hasattr(node, "get_first_child") else None
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(self)

    def _hunk_menu(
        self,
        start: int,
        length: int,
        selection: DiffSelection | None,
        hunk_index: int,
        expansion: DiffHunkExpansionType,
    ) -> None:
        """Desktop hunk-handle discard menu plus `onContextMenuExpandHunk`."""
        items: list[MenuItem] = []
        if self.interactive:
            items.append(("Include hunk", lambda: self._if_ready(self.on_hunk_toggle, self._path, start, length, True), True))
            items.append(("Exclude hunk", lambda: self._if_ready(self.on_hunk_toggle, self._path, start, length, False), True))
            probe = start + 1 if length > 1 else start
            found = self._interactive_range(probe)
            if found is not None and found.type is not None:
                count = found.to_index - found.from_index + 1
                items.append(
                    (
                        get_discard_label(found.type, count, confirm=self._ask_discard_confirm),
                        lambda lo=found.from_index, hi=found.to_index: self._discard_range(lo, hi),
                        True,
                    )
                )
        if expansion == DiffHunkExpansionType.UP:
            items.append(("Expand up", lambda: self._on_expand_hunk_clicked(hunk_index, "up"), True))
        elif expansion == DiffHunkExpansionType.DOWN:
            items.append(("Expand down", lambda: self._on_expand_hunk_clicked(hunk_index - 1, "down"), True))
        elif expansion == DiffHunkExpansionType.SHORT:
            items.append(("Expand all", lambda: self._on_expand_hunk_clicked(hunk_index, "up"), True))
        elif expansion == DiffHunkExpansionType.BOTH:
            items.append(("Expand up", lambda: self._on_expand_hunk_clicked(hunk_index, "up"), True))
            items.append(("Expand down", lambda: self._on_expand_hunk_clicked(hunk_index - 1, "down"), True))
        if self.on_expand_whole:
            items.append(("Expand whole file", self._on_expand_whole_clicked, True))
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
            btn.connect("toggled", lambda b, v=value: b.get_active() and self._if_ready(self.on_image_mode, v))
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
        elif prev_tex and cur_tex:
            self._inner.append(_two_up_images(prev_tex, cur_tex, diff.previous, diff.current))
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
    return format_bytes(n, 2, False)


def _image_dimensions_label(tex: Gdk.Texture | None, blob: bytes | None) -> str:
    parts: list[str] = []
    if tex is not None:
        parts.append(f"{tex.get_width()}×{tex.get_height()}")
    if blob:
        parts.append(_format_byte_size(len(blob)))
    return " · ".join(parts)


def _image_two_up_footer(tex: Gdk.Texture | None, blob: bytes | None) -> str:
    width = tex.get_width() if tex is not None else 0
    height = tex.get_height() if tex is not None else 0
    size = format_bytes(len(blob) if blob else 0, 2, False)
    return f"W: {width}px | H: {height}px | Size: {size}"


def _image_two_up_summary(previous: bytes | None, current: bytes | None) -> str:
    prev = len(previous or b"")
    cur = len(current or b"")
    diff_bytes = cur - prev
    if diff_bytes == 0:
        return "Diff: No size difference"
    sign = "+" if diff_bytes >= 0 else ""
    rendered = f"{sign}{format_bytes(diff_bytes, 2, False)}"
    if prev == 0:
        return f"Diff: {rendered}"
    percent = abs(round((cur / prev) * 100))
    return f"Diff: {rendered} ({percent}%)"


def _two_up_images(
    prev_tex: Gdk.Texture | None,
    cur_tex: Gdk.Texture | None,
    prev_blob: bytes | None,
    cur_blob: bytes | None,
) -> Gtk.Widget:
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box = Gtk.Box(spacing=12)
    for tex, blob, title, css in (
        (prev_tex, prev_blob, "Deleted", "image-diff-previous"),
        (cur_tex, cur_blob, "Added", "image-diff-current"),
    ):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        col.add_css_class(css)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("image-diff-header")
        col.append(heading)
        col.append(_picture(tex))
        footer = Gtk.Label(label=_image_two_up_footer(tex, blob), xalign=0)
        footer.add_css_class("image-diff-footer")
        footer.add_css_class("dim-label")
        col.append(footer)
        box.append(col)
    outer.append(box)
    summary = Gtk.Label(label=_image_two_up_summary(prev_blob, cur_blob), xalign=0)
    summary.add_css_class("image-diff-summary")
    outer.append(summary)
    return outer


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
        pix = loader.get_pixbuf()
        if pix is not None:
            return pix
    except Exception:
        pass
    if blob[:4] == b"DDS ":
        from .dds import pixbuf_from_dds

        return pixbuf_from_dds(blob)
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
    """Desktop `DifferenceBlend` using cairo `OPERATOR_DIFFERENCE` (CSS mix-blend-mode: difference)."""
    prev_pix = _pixbuf_from_bytes(previous)
    curr_pix = _pixbuf_from_bytes(current)
    if cairo is None or GdkPixbuf is None or prev_pix is None or curr_pix is None:
        box = Gtk.Box(spacing=12)
        box.append(_picture(_texture_from_bytes(previous)))
        box.append(_picture(_texture_from_bytes(current)))
        return box
    max_w = max(prev_pix.get_width(), curr_pix.get_width(), 1)
    max_h = max(prev_pix.get_height(), curr_pix.get_height(), 1)
    display_w = min(max_w, 480)
    display_h = max(1, int(round(max_h * (display_w / max_w))))
    if prev_pix.get_width() != display_w or prev_pix.get_height() != display_h:
        prev_pix = prev_pix.scale_simple(display_w, display_h, GdkPixbuf.InterpType.BILINEAR)
    if curr_pix.get_width() != display_w or curr_pix.get_height() != display_h:
        curr_pix = curr_pix.scale_simple(display_w, display_h, GdkPixbuf.InterpType.BILINEAR)
    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.add_css_class("image-diff-difference")
    area = Gtk.DrawingArea()
    area.set_content_width(display_w)
    area.set_content_height(display_h)
    area.add_css_class("image-diff-difference-canvas")

    def draw(_area, cr, width: int, height: int) -> None:
        Gdk.cairo_set_source_pixbuf(cr, prev_pix, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_DIFFERENCE)
        Gdk.cairo_set_source_pixbuf(cr, curr_pix, 0, 0)
        cr.paint()

    area.set_draw_func(draw)
    root.append(area)
    return root
