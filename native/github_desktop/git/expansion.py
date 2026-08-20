"""Hunk expansion matching GitHub Desktop's text-diff-expansion.ts."""

from __future__ import annotations

from ..models import (
    DiffHunk,
    DiffHunkExpansionType,
    DiffHunkHeader,
    DiffLine,
    DiffLineType,
    DiffSelection,
    DiffSelectionType,
    TextDiff,
)

DEFAULT_DIFF_EXPANSION_STEP = 20
MAX_DIFF_EXPANSION_CONTENT = 256 * 1024 - 1


def get_hunk_header_expansion_type(
    hunk_index: int,
    hunk_header: DiffHunkHeader,
    previous_hunk: DiffHunk | None,
) -> DiffHunkExpansionType:
    distance_to_previous = (
        float("inf")
        if previous_hunk is None
        else hunk_header.old_start_line
        - previous_hunk.header.old_start_line
        - previous_hunk.header.old_line_count
    )
    if hunk_index == 0:
        if hunk_header.old_start_line > 1 and hunk_header.new_start_line > 1:
            return DiffHunkExpansionType.UP
        return DiffHunkExpansionType.NONE
    if distance_to_previous <= DEFAULT_DIFF_EXPANSION_STEP:
        return DiffHunkExpansionType.SHORT
    return DiffHunkExpansionType.BOTH


def _copy_line(line: DiffLine) -> DiffLine:
    return DiffLine(
        line.text,
        line.kind,
        line.old_line_number,
        line.new_line_number,
        line.no_trailing_newline,
        line.diff_line_number,
    )


def _copy_hunk(hunk: DiffHunk, *, expansion_type: DiffHunkExpansionType | None = None) -> DiffHunk:
    header = DiffHunkHeader(
        hunk.header.old_start_line,
        hunk.header.old_line_count,
        hunk.header.new_start_line,
        hunk.header.new_line_count,
    )
    return DiffHunk(
        header,
        [_copy_line(line) for line in hunk.lines],
        hunk.unified_diff_start,
        hunk.unified_diff_end,
        hunk.expansion_type if expansion_type is None else expansion_type,
    )


def _diff_text_from_hunks(hunks: list[DiffHunk]) -> str:
    return "\n".join(line.text for hunk in hunks for line in hunk.lines)


def _renumber(diff: TextDiff) -> TextDiff:
    n = 0
    for hunk in diff.hunks:
        for line in hunk.lines:
            line.diff_line_number = n
            n += 1
        hunk.unified_diff_end = hunk.unified_diff_start + len(hunk.lines) - 1
    start = 0
    for hunk in diff.hunks:
        hunk.unified_diff_start = start
        hunk.unified_diff_end = start + len(hunk.lines) - 1
        start = hunk.unified_diff_end + 1
    diff.max_line_number = max(
        (ln for hunk in diff.hunks for line in hunk.lines for ln in (line.old_line_number, line.new_line_number) if ln),
        default=0,
    )
    return diff


def merge_diff_hunks(hunk1: DiffHunk, hunk2: DiffHunk) -> DiffHunk:
    header = DiffHunkHeader(
        hunk1.header.old_start_line,
        hunk1.header.old_line_count + hunk2.header.old_line_count,
        hunk1.header.new_start_line,
        hunk1.header.new_line_count + hunk2.header.new_line_count,
    )
    first = DiffLine(header.to_diff_line(), DiffLineType.HUNK, None, None)
    lines = [first, *[_copy_line(line) for line in hunk1.lines[1:]], *[_copy_line(line) for line in hunk2.lines[1:]]]
    return DiffHunk(
        header,
        lines,
        hunk1.unified_diff_start,
        hunk1.unified_diff_start + len(lines) - 1,
        hunk1.expansion_type,
    )


def apply_expansion_metadata(
    diff: TextDiff,
    *,
    old_line_count: int,
    new_line_count: int,
) -> TextDiff:
    hunks: list[DiffHunk] = []
    previous: DiffHunk | None = None
    for i, hunk in enumerate(diff.hunks):
        exp = get_hunk_header_expansion_type(i, hunk.header, previous)
        updated = _copy_hunk(hunk, expansion_type=exp)
        hunks.append(updated)
        previous = updated
    diff.hunks = hunks
    dummy = get_text_diff_with_bottom_dummy_hunk(diff, old_line_count, new_line_count)
    return _renumber(dummy or diff)


def get_text_diff_with_bottom_dummy_hunk(
    diff: TextDiff,
    old_line_count: int,
    new_line_count: int,
) -> TextDiff | None:
    if not diff.hunks:
        return None
    last = diff.hunks[-1]
    last_new = last.header.new_start_line + last.header.new_line_count
    if last_new >= new_line_count:
        return None
    dummy_old = last.header.old_start_line + last.header.old_line_count
    dummy_new = last.header.new_start_line + last.header.new_line_count
    header = DiffHunkHeader(
        dummy_old,
        max(old_line_count - dummy_old + 1, 0),
        dummy_new,
        max(new_line_count - dummy_new + 1, 0),
    )
    dummy = DiffHunk(
        header,
        [DiffLine("", DiffLineType.HUNK, None, None)],
        last.unified_diff_end + 1,
        last.unified_diff_end + 1,
        DiffHunkExpansionType.DOWN,
    )
    diff.hunks = [*diff.hunks, dummy]
    diff.text = _diff_text_from_hunks(diff.hunks)
    return diff


def expand_text_diff_hunk(
    diff: TextDiff,
    hunk_index: int,
    kind: str,
    new_content_lines: list[str],
    step: int = DEFAULT_DIFF_EXPANSION_STEP,
) -> TextDiff | None:
    if hunk_index < 0 or hunk_index >= len(diff.hunks):
        return None
    hunk = diff.hunks[hunk_index]
    is_up = kind == "up"
    adjacent_index: int | None
    if is_up and hunk_index > 0:
        adjacent_index = hunk_index - 1
    elif not is_up and hunk_index < len(diff.hunks) - 1:
        adjacent_index = hunk_index + 1
    else:
        adjacent_index = None
    adjacent = diff.hunks[adjacent_index] if adjacent_index is not None else None
    is_adjacent_dummy = (
        adjacent is not None
        and not is_up
        and len(adjacent.lines) == 1
        and adjacent.lines[0].kind == DiffLineType.HUNK
        and adjacent_index == len(diff.hunks) - 1
    )
    new_line_number = hunk.header.new_start_line
    old_line_number = hunk.header.old_start_line
    if is_up:
        from_n, to_n = new_line_number - step, new_line_number
    else:
        start = new_line_number + hunk.header.new_line_count
        from_n, to_n = start, start + step
    should_merge = False
    if adjacent is not None:
        if is_up:
            up_limit = adjacent.header.new_start_line + adjacent.header.new_line_count
            from_n = max(from_n, up_limit)
            should_merge = from_n == up_limit
        elif not is_adjacent_dummy:
            down_limit = adjacent.header.new_start_line
            to_n = min(to_n, down_limit)
            should_merge = to_n == down_limit
    new_lines = new_content_lines[max(from_n - 1, 0) : min(to_n - 1, len(new_content_lines))]
    if not new_lines:
        return None
    added = len(new_lines)
    new_line_diffs = []
    for index, line in enumerate(new_lines):
        if is_up:
            new_new = new_line_number - (added - index)
            new_old = old_line_number - (added - index)
        else:
            new_new = new_line_number + hunk.header.new_line_count + index
            new_old = old_line_number + hunk.header.old_line_count + index
        new_line_diffs.append(DiffLine(" " + line, DiffLineType.CONTEXT, new_old, new_new))
    new_header = DiffHunkHeader(
        hunk.header.old_start_line - added if is_up else hunk.header.old_start_line,
        hunk.header.old_line_count + added,
        hunk.header.new_start_line - added if is_up else hunk.header.new_start_line,
        hunk.header.new_line_count + added,
    )
    first = hunk.lines[0]
    header_line = DiffLine(
        new_header.to_diff_line(),
        DiffLineType.HUNK,
        first.old_line_number,
        first.new_line_number,
        first.no_trailing_newline,
    )
    rest = [_copy_line(line) for line in hunk.lines[1:]]
    updated_lines = [header_line, *new_line_diffs, *rest] if is_up else [header_line, *rest, *new_line_diffs]
    number_of_new = len(updated_lines) - len(hunk.lines)
    previous = None if hunk_index == 0 else diff.hunks[hunk_index - 1]
    expansion_type = get_hunk_header_expansion_type(hunk_index, new_header, previous)
    updated = DiffHunk(new_header, updated_lines, hunk.unified_diff_start, hunk.unified_diff_end + number_of_new, expansion_type)
    if should_merge and adjacent is not None:
        if is_up:
            updated = merge_diff_hunks(adjacent, updated)
            previous_end = hunk_index - 1
            following_start = hunk_index + 1
        else:
            previous_end = hunk_index
            following_start = hunk_index + 2
            updated = merge_diff_hunks(updated, adjacent)
        number_of_new -= 1
    else:
        previous_end = hunk_index
        following_start = hunk_index + 1
    previous_hunks = diff.hunks[:previous_end]
    new_last = new_header.new_start_line + new_header.new_line_count - 1
    if new_last >= len(new_content_lines):
        following: list[DiffHunk] = []
    else:
        following = []
        for i, remain in enumerate(diff.hunks[following_start:]):
            absolute = i + following_start
            is_last_dummy = (
                absolute == len(diff.hunks) - 1
                and len(remain.lines) == 1
                and remain.lines[0].kind == DiffLineType.HUNK
            )
            exp = remain.expansion_type
            if i == 0 and not is_last_dummy:
                exp = get_hunk_header_expansion_type(following_start, remain.header, updated)
            following.append(
                DiffHunk(
                    DiffHunkHeader(
                        remain.header.old_start_line,
                        remain.header.old_line_count,
                        remain.header.new_start_line,
                        remain.header.new_line_count,
                    ),
                    [_copy_line(line) for line in remain.lines],
                    remain.unified_diff_start + number_of_new,
                    remain.unified_diff_end + number_of_new,
                    exp,
                )
            )
    new_hunks = [*previous_hunks, updated, *following]
    result = TextDiff(
        text=_diff_text_from_hunks(new_hunks),
        hunks=new_hunks,
        line_endings_change=diff.line_endings_change,
        has_hidden_bidi_chars=diff.has_hidden_bidi_chars,
        is_binary=diff.is_binary,
    )
    return _renumber(result)


def expand_whole_text_diff(diff: TextDiff, new_content_lines: list[str]) -> TextDiff | None:
    result = diff
    while result.hunks and (
        len(result.hunks) > 1
        or (len(result.hunks) == 1 and result.hunks[0].expansion_type == DiffHunkExpansionType.UP)
    ):
        first = result.hunks[0]
        kind = "up" if first.expansion_type == DiffHunkExpansionType.UP else "down"
        partial = expand_text_diff_hunk(result, 0, kind, new_content_lines, len(new_content_lines))
        if partial is None:
            return result
        result = partial
    return result


def copy_text_diff(diff: TextDiff) -> TextDiff:
    hunks: list[DiffHunk] = []
    for hunk in diff.hunks:
        header = DiffHunkHeader(
            hunk.header.old_start_line,
            hunk.header.old_line_count,
            hunk.header.new_start_line,
            hunk.header.new_line_count,
        )
        lines = [
            DiffLine(
                line.text,
                line.kind,
                line.old_line_number,
                line.new_line_number,
                line.no_trailing_newline,
                line.diff_line_number,
            )
            for line in hunk.lines
        ]
        hunks.append(
            DiffHunk(header, lines, hunk.unified_diff_start, hunk.unified_diff_end, hunk.expansion_type)
        )
    return TextDiff(
        text=diff.text,
        hunks=hunks,
        line_endings_change=diff.line_endings_change,
        max_line_number=diff.max_line_number,
        has_hidden_bidi_chars=diff.has_hidden_bidi_chars,
        is_binary=diff.is_binary,
    )


def line_identity(line: DiffLine) -> tuple:
    return (line.kind, line.old_line_number, line.new_line_number, line.text)


def remap_selection(old: TextDiff, new: TextDiff, selection: DiffSelection) -> DiffSelection:
    """Keep include/exclude choices after hunk expansion shifts sequential indices."""
    from .diff import selectable_line_indices

    selectable = set(selectable_line_indices(new))
    kind = selection.get_selection_type()
    if kind == DiffSelectionType.ALL:
        return DiffSelection(DiffSelectionType.ALL, None, selectable)
    if kind == DiffSelectionType.NONE:
        return DiffSelection(DiffSelectionType.NONE, None, selectable)
    unselected: set[tuple] = set()
    for hunk in old.hunks:
        for line in hunk.lines:
            if not line.selectable:
                continue
            idx = line.diff_line_number
            if idx is None or selection.is_selected(idx):
                continue
            unselected.add(line_identity(line))
    diverging: set[int] = set()
    for hunk in new.hunks:
        for line in hunk.lines:
            if not line.selectable or line.diff_line_number is None:
                continue
            if line_identity(line) in unselected:
                diverging.add(line.diff_line_number)
    return DiffSelection(DiffSelectionType.ALL, diverging, selectable)


def can_expand_diff(diff: TextDiff) -> bool:
    return any(hunk.expansion_type != DiffHunkExpansionType.NONE for hunk in diff.hunks)
