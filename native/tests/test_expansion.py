"""File-based hunk expansion matching GitHub Desktop."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.diff import parse_unified_diff, selectable_line_indices
from github_desktop.git.expansion import (
    apply_expansion_metadata,
    can_expand_diff,
    copy_text_diff,
    expand_text_diff_hunk,
    expand_whole_text_diff,
    remap_selection,
)
from github_desktop.git.ops import get_status, get_working_directory_diff, get_working_directory_lines
from github_desktop.models import DiffHunkExpansionType, DiffLineType, DiffSelection, DiffSelectionType, TextDiff
from github_desktop.store import AppStore
from tests.conftest import run_git


def _long_file() -> str:
    return "\n".join(f"line {i}" for i in range(1, 81)) + "\n"


def test_expansion_metadata_and_dummy_hunk(git_repo: Path) -> None:
    (git_repo / "long.txt").write_text(_long_file(), encoding="utf-8")
    run_git(git_repo, "add", "long.txt")
    run_git(git_repo, "commit", "-m", "add long")
    lines = _long_file().splitlines()
    lines[39] = "line 40 changed"
    (git_repo / "long.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "long.txt")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    new_lines = get_working_directory_lines(str(git_repo), "long.txt")
    prepared = apply_expansion_metadata(diff, old_line_count=80, new_line_count=len(new_lines))
    assert can_expand_diff(prepared)
    assert prepared.hunks[0].expansion_type == DiffHunkExpansionType.UP
    assert prepared.hunks[-1].expansion_type == DiffHunkExpansionType.DOWN
    assert any(not line.text and line.kind == DiffLineType.HUNK for hunk in prepared.hunks for line in hunk.lines)


def test_expand_up_down_and_whole_file(git_repo: Path) -> None:
    (git_repo / "long.txt").write_text(_long_file(), encoding="utf-8")
    run_git(git_repo, "add", "long.txt")
    run_git(git_repo, "commit", "-m", "add long")
    lines = _long_file().splitlines()
    lines[39] = "line 40 changed"
    (git_repo / "long.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "long.txt")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    new_lines = get_working_directory_lines(str(git_repo), "long.txt")
    prepared = apply_expansion_metadata(diff, old_line_count=80, new_line_count=len(new_lines))
    original_hunks = len(prepared.hunks)
    original_lines = sum(len(h.lines) for h in prepared.hunks)
    up = expand_text_diff_hunk(prepared, 0, "up", new_lines)
    assert up is not None
    assert sum(len(h.lines) for h in up.hunks) > original_lines
    dummy_index = len(up.hunks) - 1
    down = expand_text_diff_hunk(up, dummy_index - 1, "down", new_lines)
    assert down is not None
    whole = expand_whole_text_diff(copy_text_diff(prepared), new_lines)
    assert whole is not None
    assert any("line 1" in line.text for hunk in whole.hunks for line in hunk.lines)
    assert any("line 80" in line.text for hunk in whole.hunks for line in hunk.lines)
    assert original_hunks >= 1


def test_remap_partial_selection_after_expand() -> None:
    text = "@@ -10,3 +10,4 @@\n line10\n-line11\n+line11 changed\n line12\n"
    diff = parse_unified_diff(text)
    prepared = apply_expansion_metadata(diff, old_line_count=40, new_line_count=40)
    selectable = selectable_line_indices(prepared)
    assert selectable
    selection = DiffSelection.from_initial_selection(DiffSelectionType.ALL).with_selectable_lines(selectable)
    selection = selection.with_line_selection(selectable[0], False)
    new_lines = [f"line {i}" for i in range(1, 41)]
    new_lines[10] = "line11 changed"
    expanded = expand_text_diff_hunk(prepared, 0, "up", new_lines)
    assert expanded is not None
    remapped = remap_selection(prepared, expanded, selection)
    assert remapped.get_selection_type() == DiffSelectionType.PARTIAL


def test_store_expand_hunk(isolated_config, git_repo: Path) -> None:
    (git_repo / "long.txt").write_text(_long_file(), encoding="utf-8")
    run_git(git_repo, "add", "long.txt")
    run_git(git_repo, "commit", "-m", "add long")
    lines = _long_file().splitlines()
    lines[39] = "line 40 changed"
    (git_repo / "long.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    status = get_status(str(git_repo))
    store.state_for(repo).status = status
    file = next(f for f in status.working_directory.files if f.path == "long.txt")
    store.select_file(repo, file)
    diff = store.state_for(repo).current_diff
    assert isinstance(diff, TextDiff)
    before = sum(len(h.lines) for h in diff.hunks)
    store.expand_hunk(repo, 0, "up")
    after = store.state_for(repo).current_diff
    assert isinstance(after, TextDiff)
    assert sum(len(h.lines) for h in after.hunks) >= before
    store.expand_whole_diff(repo)
    store.collapse_expanded_diff(repo)
    collapsed = store.state_for(repo).current_diff
    assert isinstance(collapsed, TextDiff)
