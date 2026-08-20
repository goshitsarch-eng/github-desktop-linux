"""Unified diff parser matching GitHub Desktop's DiffParser."""

from __future__ import annotations

import re

from ..models import (
    DiffHunk,
    DiffHunkHeader,
    DiffLine,
    DiffLineType,
    MAX_CHARACTERS_PER_LINE,
    MAX_DIFF_BUFFER_SIZE,
    MAX_REASONABLE_DIFF_SIZE,
    TextDiff,
)

DIFF_HEADER_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
HIDDEN_BIDI_RE = re.compile(r"[\u202A-\u202E]|[\u2066-\u2069]")
LINE_ENDINGS_CHANGE_RE = re.compile(r"', (CRLF|CR|LF) will be replaced by (CRLF|CR|LF) the .")
LINE_ENDINGS_CHANGE_FALLBACK_RE = re.compile(r"(CRLF|CR|LF) will be replaced by (CRLF|CR|LF)")
PREFIX = {"+": DiffLineType.ADD, "-": DiffLineType.DELETE, " ": DiffLineType.CONTEXT}


def parse_line_endings_warning(stderr: str | bytes | None) -> tuple[str, str] | None:
    """Parse Git's working-copy line-ending warning the same way Desktop does."""
    if not stderr:
        return None
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    match = LINE_ENDINGS_CHANGE_RE.search(text) or LINE_ENDINGS_CHANGE_FALLBACK_RE.search(text)
    if not match:
        return None
    return match.group(1), match.group(2)


def is_valid_buffer(data: bytes) -> bool:
    return len(data) <= MAX_DIFF_BUFFER_SIZE


def is_buffer_too_large(data: bytes) -> bool:
    return len(data) >= MAX_REASONABLE_DIFF_SIZE


def is_diff_too_large(diff: TextDiff) -> bool:
    """Desktop `isDiffTooLarge`: any line longer than `MaxCharactersPerLine`."""
    return any(len(line.text) > MAX_CHARACTERS_PER_LINE for hunk in diff.hunks for line in hunk.lines)


def parse_unified_diff(text: str) -> TextDiff:
    lines = text.splitlines()
    hunks: list[DiffHunk] = []
    i = 0
    is_binary = False
    has_bidi = bool(HIDDEN_BIDI_RE.search(text))
    max_line = 0
    # Skip git headers until first hunk
    while i < len(lines):
        line = lines[i]
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            is_binary = True
            break
        if line.startswith("@@"):
            break
        i += 1

    while i < len(lines):
        line = lines[i]
        match = DIFF_HEADER_RE.match(line)
        if not match:
            i += 1
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        header = DiffHunkHeader(old_start, old_count, new_start, new_count)
        hunk_lines: list[DiffLine] = [
            DiffLine(line, DiffLineType.HUNK, None, None, diff_line_number=None)
        ]
        i += 1
        old_n = old_start
        new_n = new_start
        start_index = i - 1
        while i < len(lines):
            raw = lines[i]
            if raw.startswith("@@"):
                break
            if raw.startswith("diff --git") or raw.startswith("index "):
                break
            prefix = raw[:1] if raw else " "
            rest = raw[1:] if raw else ""
            no_nl = False
            if raw.startswith("\\"):
                # "\ No newline at end of file"
                if hunk_lines:
                    hunk_lines[-1].no_trailing_newline = True
                i += 1
                continue
            kind = PREFIX.get(prefix)
            if kind is None:
                # Some diffs include "diff --git" after hunks; stop.
                break
            old_num = old_n if kind in (DiffLineType.DELETE, DiffLineType.CONTEXT) else None
            new_num = new_n if kind in (DiffLineType.ADD, DiffLineType.CONTEXT) else None
            if kind in (DiffLineType.DELETE, DiffLineType.CONTEXT):
                old_n += 1
            if kind in (DiffLineType.ADD, DiffLineType.CONTEXT):
                new_n += 1
            if old_num:
                max_line = max(max_line, old_num)
            if new_num:
                max_line = max(max_line, new_num)
            hunk_lines.append(
                DiffLine(
                    raw if raw else prefix,
                    kind,
                    old_num,
                    new_num,
                    no_trailing_newline=no_nl,
                )
            )
            i += 1
        hunks.append(DiffHunk(header, hunk_lines, start_index, i))

    n = 0
    for hunk in hunks:
        for line in hunk.lines:
            line.diff_line_number = n
            n += 1

    return TextDiff(
        text=text,
        hunks=hunks,
        max_line_number=max_line,
        has_hidden_bidi_chars=has_bidi,
        is_binary=is_binary,
    )


def selectable_line_indices(diff: TextDiff) -> list[int]:
    indices: list[int] = []
    n = 0
    for hunk in diff.hunks:
        for line in hunk.lines:
            if line.kind in (DiffLineType.ADD, DiffLineType.DELETE):
                indices.append(n)
            n += 1
    return indices


def format_patch_header(from_path: str | None, to_path: str | None) -> str:
    from_s = f"a/{from_path}" if from_path else "/dev/null"
    to_s = f"b/{to_path}" if to_path else "/dev/null"
    return f"--- {from_s}\n+++ {to_s}\n"


def format_hunk_header(header: DiffHunkHeader) -> str:
    old = f"{header.old_start_line},{header.old_line_count}"
    new = f"{header.new_start_line},{header.new_line_count}"
    return f"@@ -{old} +{new} @@\n"


def format_partial_patch(
    diff: TextDiff,
    from_path: str | None,
    to_path: str | None,
    is_selected,
) -> str:
    """Build a GNU unified patch containing only selected add/delete lines.

    `is_selected(diff_line_index) -> bool` is called for each add/delete line
    using a running index across all hunk lines (including hunk headers).
    """
    parts = [format_patch_header(from_path, to_path)]
    line_index = 0
    for hunk in diff.hunks:
        selected_lines: list[DiffLine] = []
        old_count = 0
        new_count = 0
        # Consume the hunk header line in the running index
        line_index += 1  # header
        context_and_selected: list[tuple[DiffLine, bool]] = []
        for line in hunk.lines[1:]:
            if line.kind == DiffLineType.HUNK:
                line_index += 1
                continue
            include = True
            if line.kind in (DiffLineType.ADD, DiffLineType.DELETE):
                include = bool(is_selected(line_index))
            context_and_selected.append((line, include))
            line_index += 1

        # Count resulting hunk
        resulting: list[DiffLine] = []
        for line, include in context_and_selected:
            if line.kind == DiffLineType.CONTEXT:
                resulting.append(line)
                old_count += 1
                new_count += 1
            elif line.kind == DiffLineType.DELETE:
                if include:
                    resulting.append(line)
                    old_count += 1
                else:
                    # Unselected deletion stays in the file: treat as context
                    resulting.append(
                        DiffLine(" " + line.text[1:], DiffLineType.CONTEXT, line.old_line_number, line.old_line_number)
                    )
                    old_count += 1
                    new_count += 1
            elif line.kind == DiffLineType.ADD:
                if include:
                    resulting.append(line)
                    new_count += 1
                # Unselected addition is omitted from the patch
        if not any(l.kind in (DiffLineType.ADD, DiffLineType.DELETE) for l in resulting):
            continue
        new_header = DiffHunkHeader(
            hunk.header.old_start_line,
            old_count,
            hunk.header.new_start_line,
            new_count,
        )
        parts.append(format_hunk_header(new_header))
        for line in resulting:
            text = line.text if line.text.endswith("\n") else line.text + "\n"
            # DiffLine.text already includes the prefix character
            if not text.startswith(("+", "-", " ", "\\")):
                prefix = {
                    DiffLineType.ADD: "+",
                    DiffLineType.DELETE: "-",
                    DiffLineType.CONTEXT: " ",
                }.get(line.kind, " ")
                text = prefix + text
            parts.append(text if text.endswith("\n") else text + "\n")
            if line.no_trailing_newline:
                parts.append("\\ No newline at end of file\n")
    return "".join(parts)


def hunk_line_span(diff: TextDiff, hunk_index: int) -> tuple[int, int]:
    n = 0
    for i, hunk in enumerate(diff.hunks):
        if i == hunk_index:
            return n, len(hunk.lines)
        n += len(hunk.lines)
    return 0, 0


def format_discard_patch(file_path: str, diff: TextDiff, is_selected) -> str | None:
    """Build a reverse patch that discards selected working-directory lines.

    Indexing matches `format_partial_patch` / `selectable_line_indices`.
    """
    chunks: list[str] = []
    line_index = 0
    for hunk in diff.hunks:
        hunk_buf: list[str] = []
        old_count = 0
        new_count = 0
        any_change = False
        line_index += 1  # hunk header
        for line in hunk.lines[1:]:
            idx = line_index
            line_index += 1
            if line.kind == DiffLineType.HUNK:
                continue
            body = line.text[1:] if line.text[:1] in "+- " else line.text
            selected = bool(is_selected(idx))
            if line.kind == DiffLineType.CONTEXT:
                hunk_buf.append(f" {body}\n")
                old_count += 1
                new_count += 1
            elif selected:
                any_change = True
                if line.kind == DiffLineType.ADD:
                    hunk_buf.append(f"-{body}\n")
                    new_count += 1
                elif line.kind == DiffLineType.DELETE:
                    hunk_buf.append(f"+{body}\n")
                    old_count += 1
            elif line.kind == DiffLineType.ADD:
                hunk_buf.append(f" {body}\n")
                old_count += 1
                new_count += 1
            if line.no_trailing_newline:
                hunk_buf.append("\\ No newline at end of file\n")
        if not any_change:
            continue
        reversed_header = DiffHunkHeader(
            hunk.header.new_start_line,
            new_count,
            hunk.header.old_start_line,
            old_count,
        )
        chunks.append(format_hunk_header(reversed_header))
        chunks.extend(hunk_buf)
    if not chunks:
        return None
    return format_patch_header(file_path, file_path) + "".join(chunks)


def side_by_side_rows(hunk: DiffHunk) -> list[tuple[str, DiffLine | None, DiffLine | None, int | None, int | None]]:
    """Pair hunk lines into unified-to-split rows.

    Each tuple is (kind, left, right, left_index, right_index) where kind is
    ``hunk``, ``context``, or ``change``.
    """
    rows: list[tuple[str, DiffLine | None, DiffLine | None, int | None, int | None]] = []
    lines = hunk.lines
    i = 0
    while i < len(lines):
        line = lines[i]
        idx = line.diff_line_number
        if line.kind == DiffLineType.HUNK:
            rows.append(("hunk", line, None, idx, None))
            i += 1
            continue
        if line.kind == DiffLineType.CONTEXT:
            rows.append(("context", line, line, idx, idx))
            i += 1
            continue
        deletes: list[DiffLine] = []
        while i < len(lines) and lines[i].kind == DiffLineType.DELETE:
            deletes.append(lines[i])
            i += 1
        adds: list[DiffLine] = []
        while i < len(lines) and lines[i].kind == DiffLineType.ADD:
            adds.append(lines[i])
            i += 1
        for j in range(max(len(deletes), len(adds), 1 if not deletes and not adds else 0)):
            left = deletes[j] if j < len(deletes) else None
            right = adds[j] if j < len(adds) else None
            rows.append(
                (
                    "change",
                    left,
                    right,
                    left.diff_line_number if left else None,
                    right.diff_line_number if right else None,
                )
            )
        if not deletes and not adds:
            i += 1
    return rows
