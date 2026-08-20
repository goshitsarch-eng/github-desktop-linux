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


def test_diff_line_numbers_are_sequential() -> None:
    diff = parse_unified_diff(SAMPLE)
    numbers = [line.diff_line_number for hunk in diff.hunks for line in hunk.lines]
    assert numbers == list(range(len(numbers)))


def test_side_by_side_pairs_delete_and_add() -> None:
    from github_desktop.git.diff import side_by_side_rows

    diff = parse_unified_diff(SAMPLE)
    rows = side_by_side_rows(diff.hunks[0])
    kinds = [r[0] for r in rows]
    assert "hunk" in kinds
    assert "change" in kinds
    change = next(r for r in rows if r[0] == "change")
    assert change[1] is not None or change[2] is not None


def test_discard_patch_reverses_selected_addition() -> None:
    from github_desktop.git.diff import format_discard_patch

    diff = parse_unified_diff(SAMPLE)
    selectable = selectable_line_indices(diff)
    keep = {selectable[-1]}

    patch = format_discard_patch("file.txt", diff, lambda idx: idx in keep)
    assert patch is not None
    assert patch.startswith("--- a/file.txt\n+++ b/file.txt\n")
    assert "-line4" in patch
    assert "line2 changed" not in patch or "+line2 changed" not in patch


def test_find_interactive_diff_range_groups_contiguous_changes() -> None:
    from github_desktop.git.diff import DiffRangeType, find_interactive_diff_range, selectable_line_indices

    diff = parse_unified_diff(SAMPLE)
    selectable = selectable_line_indices(diff)
    delete_idx, first_add, last_add = selectable
    mixed = find_interactive_diff_range(diff.hunks, delete_idx)
    assert mixed is not None
    assert mixed.type == DiffRangeType.MIXED
    assert mixed.from_index == delete_idx
    assert mixed.to_index == first_add
    added = find_interactive_diff_range(diff.hunks, last_add)
    assert added is not None
    assert added.type == DiffRangeType.ADDITIONS
    assert added.from_index == last_add
    assert added.to_index == last_add
