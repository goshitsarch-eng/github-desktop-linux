"""Porcelain status parser tests (parity with Desktop's status-parser)."""

from __future__ import annotations

from github_desktop.git.status import convert_to_app_status, parse_porcelain_status, parse_status_headers
from github_desktop.models import AppFileStatusKind


def test_parse_headers_and_modified_entry() -> None:
    raw = (
        b"# branch.oid abcdef0123456789abcdef0123456789abcdef01\0"
        b"# branch.head main\0"
        b"# branch.upstream origin/main\0"
        b"# branch.ab +2 -1\0"
        b"1 M. N... 100644 100644 100644 "
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb README.md\0"
    )
    items = parse_porcelain_status(raw)
    headers = [i for i in items if hasattr(i, "value")]
    entries = [i for i in items if hasattr(i, "path")]
    info = parse_status_headers(headers)
    assert info["current_branch"] == "main"
    assert info["current_upstream_branch"] == "origin/main"
    assert info["current_tip"] == "abcdef0123456789abcdef0123456789abcdef01"
    assert info["ahead_behind"] == (2, 1)
    assert entries[0].path == "README.md"
    assert entries[0].status_code == "M."
    status = convert_to_app_status(entries[0])
    assert status.kind == AppFileStatusKind.MODIFIED


def test_parse_untracked_and_rename() -> None:
    raw = (
        b"1 A. N... 000000 100644 100644 "
        b"0000000000000000000000000000000000000000 "
        b"cccccccccccccccccccccccccccccccccccccccc new.txt\0"
        b"? untracked.txt\0"
        b"2 R. N... 100644 100644 100644 "
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb R100 dest.txt\0"
        b"src.txt\0"
    )
    items = parse_porcelain_status(raw)
    entries = [i for i in items if hasattr(i, "path")]
    kinds = {e.path: convert_to_app_status(e).kind for e in entries}
    assert kinds["new.txt"] == AppFileStatusKind.NEW
    assert kinds["untracked.txt"] == AppFileStatusKind.UNTRACKED
    renamed = next(e for e in entries if e.path == "dest.txt")
    status = convert_to_app_status(renamed)
    assert status.kind == AppFileStatusKind.RENAMED
    assert status.old_path == "src.txt"


def test_parse_conflicts() -> None:
    raw = (
        b"u UU N... 100644 100644 100644 100644 "
        b"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa "
        b"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "
        b"cccccccccccccccccccccccccccccccccccccccc conflict.txt\0"
    )
    items = parse_porcelain_status(raw)
    entry = [i for i in items if hasattr(i, "path")][0]
    status = convert_to_app_status(entry)
    assert status.kind == AppFileStatusKind.CONFLICTED


def test_detached_head_header() -> None:
    raw = b"# branch.oid deadbeef\0# branch.head (detached)\0"
    items = parse_porcelain_status(raw)
    info = parse_status_headers([i for i in items if hasattr(i, "value")])
    assert info["current_branch"] is None
    assert info["current_tip"] == "deadbeef"
