"""Unified diff parser and partial-patch generation."""

from __future__ import annotations

from github_desktop.git.diff import format_partial_patch, parse_unified_diff, selectable_line_indices
from github_desktop.models import DiffLineType


SAMPLE = """diff --git a/file.txt b/file.txt
index 111..222 100644
--- a/file.txt
+++ b/file.txt
@@ -1,3 +1,4 @@
 line1
-line2
+line2 changed
 line3
+line4
"""


def test_parse_hunks_and_line_kinds() -> None:
    diff = parse_unified_diff(SAMPLE)
    assert len(diff.hunks) == 1
    kinds = [line.kind for line in diff.hunks[0].lines]
    assert DiffLineType.HUNK in kinds
    assert DiffLineType.DELETE in kinds
    assert DiffLineType.ADD in kinds
    assert DiffLineType.CONTEXT in kinds
    selectable = selectable_line_indices(diff)
    assert selectable  # add/delete lines


def test_partial_patch_includes_only_selected_additions() -> None:
    diff = parse_unified_diff(SAMPLE)
    selectable = selectable_line_indices(diff)
    keep = set(selectable[:2])

    def is_selected(idx: int) -> bool:
        return idx in keep

    patch = format_partial_patch(diff, "file.txt", "file.txt", is_selected)
    assert patch.startswith("--- a/file.txt\n+++ b/file.txt\n")
    assert "line2 changed" in patch
    assert "+line4" not in patch


def test_binary_marker() -> None:
    text = "diff --git a/x.bin b/x.bin\nBinary files a/x.bin and b/x.bin differ\n"
    diff = parse_unified_diff(text)
    assert diff.is_binary
