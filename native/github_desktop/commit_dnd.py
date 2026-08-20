"""Commit list drag-and-drop hit testing (Desktop squash vs reorder)."""

from __future__ import annotations


def commit_drop_kind(y: float, height: float) -> str:
    """Map a drop Y coordinate onto a history row.

    Desktop drops *onto* a commit to squash and *between* commits to reorder.
    GTK only gives us a drop on the row, so the outer 25% of the row is treated
    as an insertion point and the middle as squash-onto.
    """
    if height <= 0:
        return "squash"
    ratio = y / height
    if ratio < 0.25:
        return "reorder-before"
    if ratio > 0.75:
        return "reorder-after"
    return "squash"


def encode_commit_shas(shas: list[str]) -> str:
    return ",".join(s for s in shas if s)


def decode_commit_shas(value: object) -> list[str]:
    text = str(value or "")
    return [part for part in text.split(",") if part]
