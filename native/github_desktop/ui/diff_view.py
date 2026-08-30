"""Diff presentation: labels, hunk expansion rules, and rows for the QML view.

The view itself is ``ui/qml/DiffView.qml``; everything that decides *what* a
row says -- selection state, syntax markup, hunk headers, side-by-side pairing
-- is computed here so it stays testable without a running UI.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..git.progress import format_bytes
from .copy_button import copy_the_full_sha_label
from ..git.diff import DiffRangeType
from ..models import (
    DiffHunkExpansionType,
    DiffLine,
    DiffLineType,
    DiffType,
    FileDiff,
    TextDiff,
)

DIFF_OPTIONS_LABEL = "Diff Options"
# Desktop's image-diff composite mode; Qt has no OPERATOR_DIFFERENCE blend, so
# the Difference view is drawn by the image provider instead of the canvas.
OPERATOR_DIFFERENCE = "difference"
# .dds is a DirectDraw texture: decodable (see ui/dds.py) but nothing on Linux
# previews it natively, so Desktop's message applies here too.
DDS_UNSUPPORTED = "Can't preview .dds on Linux"
MULTIPLE_NON_CONSECUTIVE = "Unable to display diff when multiple non-consecutive selected."
SlowDiffLoadingThreshold = 150


def diff_search_no_results(query: str) -> str:
    """Desktop AriaLiveContainer `ariaLiveMessage`: `No results for "{searchQuery}"`."""
    return f'No results for "{query}"'


def diff_search_result_message(index: int, total: int, query: str) -> str:
    """Desktop AriaLiveContainer `ariaLiveMessage`: `Result N of M for "{searchQuery}"` (1-based)."""
    return f'Result {index} of {total} for "{query}"'


DIFF_EXPANDED_ARIA_LIVE = "Expanded"
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


VIRTUALIZE_AFTER = 400
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


def _format_byte_size(n: int) -> str:
    return format_bytes(n, 2, False)


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


# Desktop's TwoUp footer template: `W: {width}px | H: {height}px | Size: {size}`.
IMAGE_FOOTER_TEMPLATE = "W: {width}px | H: {height}px | Size: {size}"


def _image_two_up_footer(width: int, height: int, blob: bytes | None) -> str:
    """Desktop `TwoUp` per-image footer: dimensions and byte size."""
    return IMAGE_FOOTER_TEMPLATE.format(
        width=int(width), height=int(height), size=format_bytes(len(blob) if blob else 0, 2, False)
    )


def _flatten(diff: TextDiff, side_by_side: bool) -> list[RowSpec]:
    """One row per rendered diff line, mirroring Desktop's virtualized list."""
    from ..git.diff import hunk_line_span, side_by_side_rows

    rows: list[RowSpec] = []
    for hunk_index, hunk in enumerate(diff.hunks):
        start, length = hunk_line_span(diff, hunk_index)
        if side_by_side:
            for kind, left, right, left_i, right_i in side_by_side_rows(hunk):
                if kind == "hunk" and left is not None:
                    rows.append(
                        RowSpec("hunk", hunk_index, hunk.expansion_type, start, length, line=left)
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
            index = line.diff_line_number if line.diff_line_number is not None else start
            if line.kind == DiffLineType.HUNK:
                rows.append(RowSpec("hunk", hunk_index, hunk.expansion_type, start, length, line=line))
                continue
            paired = None
            if (
                line.kind == DiffLineType.DELETE
                and i + 1 < len(hunk.lines)
                and hunk.lines[i + 1].kind == DiffLineType.ADD
            ):
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
                    index=index,
                    paired=paired,
                )
            )
    return rows


def _line_row(
    line: DiffLine,
    *,
    kind: str,
    spec: RowSpec,
    path: str,
    diff: TextDiff,
    selection,
    tab_size: int,
    index: int | None,
) -> dict:
    from .syntax import markup_for_diff_line

    body = line.text[1:] if line.text[:1] in "+- " else line.text
    included = False
    selectable = index is not None and line.kind in (DiffLineType.ADD, DiffLineType.DELETE)
    if selectable and selection is not None:
        included = bool(selection.is_selected(index))
    return {
        "kind": kind,
        "text": body,
        "markup": markup_for_diff_line(
            line,
            path,
            old_markup=diff.old_line_markup,
            new_markup=diff.new_line_markup,
            tab_size=tab_size,
        ),
        "oldNumber": line.old_line_number or 0,
        "newNumber": line.new_line_number or 0,
        "lineType": str(line.kind),
        "included": included,
        "hunkIndex": spec.hunk_index,
        "diffIndex": index if index is not None else -1,
        "expansion": str(spec.expansion),
        "selectable": selectable,
    }


def gutter_selection_range(anchor: int, current: int) -> tuple[int, int]:
    """Desktop's gutter drag: the inclusive line range between two indices.

    ``_start_gutter_selection`` records the anchor when the drag begins and the
    rows in between become a ``temporary_selection`` until the button is
    released, so the diff can preview what a drag would include.
    """
    if anchor < 0 or current < 0:
        return (-1, -1)
    return (min(anchor, current), max(anchor, current))


def diff_rows_for_qml(state) -> list[dict]:
    """Rows for the QML diff view: hunk headers plus one row per line."""
    diff = getattr(state, "current_diff", None)
    if not isinstance(diff, TextDiff):
        return []
    file = getattr(state, "selected_file", None)
    path = getattr(file, "path", "") or ""
    selection = getattr(file, "selection", None)
    tab_size = 4
    rows: list[dict] = []
    for spec in _flatten(diff, bool(getattr(state, "side_by_side", False))):
        if spec.kind == "hunk" and spec.line is not None:
            rows.append(
                {
                    "kind": "hunk",
                    "text": spec.line.text,
                    "markup": "",
                    "oldNumber": 0,
                    "newNumber": 0,
                    "lineType": "Hunk",
                    "included": False,
                    "hunkIndex": spec.hunk_index,
                    "diffIndex": -1,
                    "expansion": str(spec.expansion),
                    "selectable": False,
                }
            )
            continue
        if spec.kind == "split":
            for side, line, side_index in (
                ("left", spec.left, spec.left_i),
                ("right", spec.right, spec.right_i),
            ):
                if line is None:
                    rows.append(
                        {
                            "kind": f"split-{side}-empty",
                            "text": "",
                            "markup": "",
                            "oldNumber": 0,
                            "newNumber": 0,
                            "lineType": "Context",
                            "included": False,
                            "hunkIndex": spec.hunk_index,
                            "diffIndex": -1,
                            "expansion": str(spec.expansion),
                            "selectable": False,
                        }
                    )
                    continue
                rows.append(
                    _line_row(
                        line,
                        kind=f"split-{side}",
                        spec=spec,
                        path=path,
                        diff=diff,
                        selection=selection,
                        tab_size=tab_size,
                        index=side_index,
                    )
                )
            continue
        if spec.line is None:
            continue
        rows.append(
            _line_row(
                spec.line,
                kind="line",
                spec=spec,
                path=path,
                diff=diff,
                selection=selection,
                tab_size=tab_size,
                index=spec.index,
            )
        )
    return rows


# Desktop `MaxDiffSize` -- past this the diff is collapsed behind "Show diff".
MAX_DIFF_SIZE = 268435441
LARGE_DIFF_MESSAGE = "The diff is too large to be displayed by default"


def diff_is_too_large(diff) -> bool:
    """Desktop `isDiffTooLarge`: over MaxDiffSize and not explicitly expanded."""
    if not isinstance(diff, TextDiff):
        return False
    return sum(len(line.text) + 1 for hunk in diff.hunks for line in hunk.lines) > MAX_DIFF_SIZE


def diff_summary_for_qml(state, store) -> dict:
    """Header state for the diff pane: which file, what kind, how big."""
    if state is None:
        return {"kind": "none", "message": NO_FILE_SELECTED}
    diff = getattr(state, "current_diff", None)
    file = getattr(state, "selected_file", None)
    path = getattr(file, "path", "") or ""
    tab_size = store.settings.tab_size if store is not None else 4
    if file is None:
        has_files = bool(getattr(state, "selected_commit_files", None)) or bool(
            getattr(getattr(state, "status", None), "working_directory", None)
        )
        return {"kind": "none", "message": diff_no_file_blankslate(has_files=has_files), "path": ""}
    if diff is None:
        return {"kind": "loading", "message": "Loading diff…", "path": path}
    kind = getattr(getattr(diff, "kind", None), "value", "") or str(getattr(diff, "kind", ""))
    commit = getattr(state, "selected_commit", None)
    sha = getattr(commit, "sha", "") or ""
    summary = {
        "kind": "text" if isinstance(diff, TextDiff) else str(kind).lower(),
        "path": path,
        "message": "",
        "tabSize": tab_size,
        "sideBySide": bool(getattr(state, "side_by_side", False)),
        "hideWhitespace": bool(getattr(state, "hide_whitespace", False)),
        "lineCount": 0,
        "added": 0,
        "removed": 0,
        "isBinary": False,
        "isImage": False,
        "isSubmodule": False,
        "sha": sha,
        "copyShaLabel": copy_the_full_sha_label(),
        "tooLarge": diff_is_too_large(diff) and not getattr(state, "show_large_diff", False),
        "discardLineLabel": get_discard_label(None, 1),
        "imageMode": str(getattr(state, "image_diff_type", "") or "TwoUp"),
        "imageMessage": DDS_UNSUPPORTED
        if path.lower().endswith(".dds")
        else "This image has changed.",
        "imageFooter": _image_two_up_footer(
            int(getattr(diff, "width", 0) or 0),
            int(getattr(diff, "height", 0) or 0),
            getattr(diff, "current_contents", None),
        ),
        "canExpandWholeFile": hunks_expand_whole_file_enabled(getattr(diff, "hunks", []) or []),
        # Desktop keeps focus on the hunk that was just expanded.
        "lastExpandedHunk": int(getattr(state, "last_expanded_hunk", -1) or -1),
    }
    if isinstance(diff, TextDiff):
        added = removed = lines = 0
        for hunk in diff.hunks:
            for line in hunk.lines:
                if line.kind == DiffLineType.ADD:
                    added += 1
                elif line.kind == DiffLineType.DELETE:
                    removed += 1
                lines += 1
        summary.update({"lineCount": lines, "added": added, "removed": removed})
        return summary
    if getattr(diff, "kind", None) == DiffType.BINARY:
        summary.update({"isBinary": True, "message": "This binary file has changed."})
    elif getattr(diff, "kind", None) == DiffType.IMAGE:
        summary["isImage"] = True
    elif getattr(diff, "kind", None) == DiffType.SUBMODULE:
        summary["isSubmodule"] = True
    return summary
