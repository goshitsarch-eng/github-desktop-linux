"""Parse `git status --porcelain=2 -z --branch` output (GitHub Desktop format)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from ..models import (
    AppFileStatusKind,
    FileStatus,
    GitStatusEntry,
    SubmoduleStatus,
    UnmergedEntrySummary,
)

CONFLICT_STATUS_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}

CHANGED_RE = re.compile(
    r"^1 ([MADRCUTX?!.]{2}) (N\.\.\.|S[C.][M.][U.]) (\d+) (\d+) (\d+) "
    r"([a-f0-9]+) ([a-f0-9]+) ([\s\S]*?)$"
)
RENAMED_RE = re.compile(
    r"^2 ([MADRCUTX?!.]{2}) (N\.\.\.|S[C.][M.][U.]) (\d+) (\d+) (\d+) "
    r"([a-f0-9]+) ([a-f0-9]+) ([RC]\d+) ([\s\S]*?)$"
)
UNMERGED_RE = re.compile(
    r"^u ([DAU]{2}) (N\.\.\.|S[C.][M.][U.]) (\d+) (\d+) (\d+) (\d+) "
    r"([a-f0-9]+) ([a-f0-9]+) ([a-f0-9]+) ([\s\S]*?)$"
)
OID_RE = re.compile(r"^branch\.oid ([a-f0-9]+)$")
HEAD_RE = re.compile(r"^branch\.head (.*)$")
UPSTREAM_RE = re.compile(r"^branch\.upstream (.*)$")
AB_RE = re.compile(r"^branch\.ab \+(\d+) -(\d+)$")


@dataclass
class StatusHeader:
    value: str


@dataclass
class StatusEntry:
    path: str
    status_code: str
    submodule_status_code: str
    old_path: str | None = None
    rename_or_copy_score: int | None = None


StatusItem = StatusHeader | StatusEntry


def parse_porcelain_status(output: bytes | str) -> list[StatusItem]:
    if isinstance(output, str):
        raw = output.encode("utf-8", errors="replace")
    else:
        raw = output
    tokens = raw.split(b"\0")
    entries: list[StatusItem] = []
    i = 0
    while i < len(tokens):
        field = tokens[i].decode("utf-8", errors="replace")
        i += 1
        if not field:
            continue
        if field.startswith("# ") and len(field) > 2:
            entries.append(StatusHeader(field[2:]))
            continue
        kind = field[:1]
        if kind == "1":
            entries.append(_parse_changed(field))
        elif kind == "2":
            old = tokens[i].decode("utf-8", errors="replace") if i < len(tokens) else ""
            i += 1
            entries.append(_parse_renamed(field, old))
        elif kind == "u":
            entries.append(_parse_unmerged(field))
        elif kind == "?":
            entries.append(
                StatusEntry(
                    path=field[2:],
                    status_code="??",
                    submodule_status_code="????",
                )
            )
        elif kind == "!":
            continue
    return entries


def _parse_changed(field: str) -> StatusEntry:
    match = CHANGED_RE.match(field)
    if not match:
        raise ValueError(f"Failed to parse status line for changed entry: {field!r}")
    return StatusEntry(
        status_code=match.group(1),
        submodule_status_code=match.group(2),
        path=match.group(8),
    )


def _parse_renamed(field: str, old_path: str) -> StatusEntry:
    match = RENAMED_RE.match(field)
    if not match:
        raise ValueError(f"Failed to parse renamed/copied entry: {field!r}")
    if not old_path:
        raise ValueError("Failed to parse renamed or copied entry, missing old path")
    return StatusEntry(
        status_code=match.group(1),
        submodule_status_code=match.group(2),
        rename_or_copy_score=int(match.group(8)[1:]),
        path=match.group(9),
        old_path=old_path,
    )


def _parse_unmerged(field: str) -> StatusEntry:
    match = UNMERGED_RE.match(field)
    if not match:
        raise ValueError(f"Failed to parse unmerged entry: {field!r}")
    return StatusEntry(
        status_code=match.group(1),
        submodule_status_code=match.group(2),
        path=match.group(10),
    )


def map_submodule_status(code: str) -> SubmoduleStatus | None:
    if not code.startswith("S"):
        return None
    padded = (code + "....")[:4]
    return SubmoduleStatus(
        commit_changed=padded[1] == "C",
        modified_changes=padded[2] == "M",
        untracked_changes=padded[3] == "U",
    )


def convert_to_app_status(entry: StatusEntry) -> FileStatus:
    code = entry.status_code
    sub = map_submodule_status(entry.submodule_status_code)

    if code == "??":
        return FileStatus(AppFileStatusKind.UNTRACKED, submodule_status=sub)

    conflict_map: dict[str, UnmergedEntrySummary] = {
        "DD": UnmergedEntrySummary.BOTH_DELETED,
        "AU": UnmergedEntrySummary.ADDED_BY_US,
        "UD": UnmergedEntrySummary.DELETED_BY_THEM,
        "UA": UnmergedEntrySummary.ADDED_BY_THEM,
        "DU": UnmergedEntrySummary.DELETED_BY_US,
        "AA": UnmergedEntrySummary.BOTH_ADDED,
        "UU": UnmergedEntrySummary.BOTH_MODIFIED,
    }
    if code in conflict_map:
        us, them = _us_them(code)
        return FileStatus(
            AppFileStatusKind.CONFLICTED,
            unmerged_action=conflict_map[code],
            us=us,
            them=them,
            submodule_status=sub,
        )

    if "R" in code:
        return FileStatus(
            AppFileStatusKind.RENAMED,
            old_path=entry.old_path,
            rename_includes_modifications=(
                "M" in code
                or (entry.rename_or_copy_score is not None and entry.rename_or_copy_score < 100)
            ),
            submodule_status=sub,
        )
    if "C" in code:
        return FileStatus(
            AppFileStatusKind.COPIED,
            old_path=entry.old_path,
            submodule_status=sub,
        )
    if "A" in code:
        return FileStatus(AppFileStatusKind.NEW, submodule_status=sub)
    if "D" in code:
        return FileStatus(AppFileStatusKind.DELETED, submodule_status=sub)
    return FileStatus(AppFileStatusKind.MODIFIED, submodule_status=sub)


def _us_them(code: str) -> tuple[GitStatusEntry, GitStatusEntry]:
    mapping = {
        "D": GitStatusEntry.DELETED,
        "A": GitStatusEntry.ADDED,
        "U": GitStatusEntry.UPDATED_BUT_UNMERGED,
        "M": GitStatusEntry.MODIFIED,
    }
    return mapping.get(code[0], GitStatusEntry.MODIFIED), mapping.get(
        code[1], GitStatusEntry.MODIFIED
    )


def parse_status_headers(
    headers: Iterator[StatusHeader] | list[StatusHeader],
) -> dict[str, object]:
    current_branch = None
    current_upstream = None
    current_tip = None
    ahead_behind = None
    for header in headers:
        value = header.value
        if m := OID_RE.match(value):
            current_tip = m.group(1)
        elif m := HEAD_RE.match(value):
            if m.group(1) != "(detached)":
                current_branch = m.group(1)
        elif m := UPSTREAM_RE.match(value):
            current_upstream = m.group(1)
        elif m := AB_RE.match(value):
            ahead_behind = (int(m.group(1)), int(m.group(2)))
    return {
        "current_branch": current_branch,
        "current_upstream_branch": current_upstream,
        "current_tip": current_tip,
        "ahead_behind": ahead_behind,
    }


def should_skip_entry(entry: StatusEntry) -> bool:
    # Added in index then deleted in worktree — won't be part of the commit
    return entry.status_code == "AD"
