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
PREFIX = {"+": DiffLineType.ADD, "-": DiffLineType.DELETE, " ": DiffLineType.CONTEXT}


def is_valid_buffer(data: bytes) -> bool:
    return len(data) <= MAX_DIFF_BUFFER_SIZE


def is_buffer_too_large(data: bytes) -> bool:
    return len(data) >= MAX_REASONABLE_DIFF_SIZE


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

    too_wide = any(
        len(line.text) > MAX_CHARACTERS_PER_LINE for hunk in hunks for line in hunk.lines
    )
    diff = TextDiff(
        text=text,
        hunks=hunks,
        max_line_number=max_line,
        has_hidden_bidi_chars=has_bidi,
        is_binary=is_binary,
    )
    if too_wide:
        diff.has_hidden_bidi_chars = has_bidi
    return diff


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
