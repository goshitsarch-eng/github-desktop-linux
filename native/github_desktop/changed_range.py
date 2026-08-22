"""Intra-line (word-level) diff ranges matching Desktop `ui/diff/changed-range.ts`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextRange:
    """Desktop `IRange`: `location` plus `length` in the source string."""

    location: int
    length: int


def range_max(span: TextRange) -> int:
    return span.location + span.length


def common_length(
    string_a: str,
    range_a: TextRange,
    string_b: str,
    range_b: TextRange,
    reverse: bool,
) -> int:
    """Get the length of the common substring between the two strings."""
    max_len = min(range_a.length, range_b.length)
    start_a = range_max(range_a) - 1 if reverse else range_a.location
    start_b = range_max(range_b) - 1 if reverse else range_b.location
    stride = -1 if reverse else 1
    length = 0
    while abs(length) < max_len:
        if string_a[start_a + length] != string_b[start_b + length]:
            break
        length += stride
    return abs(length)


def relative_changes(string_a: str, string_b: str) -> tuple[TextRange, TextRange]:
    """Desktop `relativeChanges`: changed span in each line after shared prefix/suffix."""
    b_range = TextRange(0, len(string_b))
    a_range = TextRange(0, len(string_a))
    prefix_length = common_length(string_b, b_range, string_a, a_range, False)
    b_range = TextRange(b_range.location + prefix_length, b_range.length - prefix_length)
    a_range = TextRange(a_range.location + prefix_length, a_range.length - prefix_length)
    suffix_length = common_length(string_b, b_range, string_a, a_range, True)
    b_range = TextRange(b_range.location, b_range.length - suffix_length)
    a_range = TextRange(a_range.location, a_range.length - suffix_length)
    return a_range, b_range


def get_diff_tokens(line_before: str, line_after: str) -> tuple[TextRange, TextRange]:
    """Desktop `getDiffTokens`: inner ranges for `diff-delete-inner` / `diff-add-inner`."""
    return relative_changes(line_before, line_after)


def wrap_pango_visible_range(
    markup: str,
    start: int,
    length: int,
    open_tag: str,
    close_tag: str,
) -> str:
    """Wrap `[start, start+length)` of visible Pango characters, skipping tags/entities."""
    if length <= 0 or start < 0 or not markup:
        return markup
    end = start + length
    out: list[str] = []
    index = 0
    visible = 0
    opened = False
    closed = False
    total = len(markup)
    while index < total:
        if not opened and visible == start:
            out.append(open_tag)
            opened = True
        if not closed and visible == end:
            out.append(close_tag)
            closed = True
        char = markup[index]
        if char == "<":
            close = markup.find(">", index)
            if close < 0:
                out.append(markup[index:])
                break
            out.append(markup[index : close + 1])
            index = close + 1
            continue
        if char == "&":
            close = markup.find(";", index)
            if close < 0:
                out.append(markup[index:])
                break
            out.append(markup[index : close + 1])
            visible += 1
            index = close + 1
            continue
        out.append(char)
        visible += 1
        index += 1
    if opened and not closed:
        out.append(close_tag)
    return "".join(out)


def apply_inner_highlight(markup: str, start: int, length: int, background: str) -> str:
    if length <= 0 or not background:
        return markup
    return wrap_pango_visible_range(
        markup,
        start,
        length,
        f'<span background="{background}">',
        "</span>",
    )


def inner_highlight_background(added: bool) -> str:
    try:
        from .theme import is_dark

        dark = is_dark()
    except Exception:
        dark = False
    if added:
        return "#26a269" if dark else "#8ff0a4"
    return "#c01c28" if dark else "#f66151"
