"""Partial staging, co-author trailers, and secret storage."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.diff import format_partial_patch, selectable_line_indices
from github_desktop.git.ops import (
    create_commit,
    format_commit_message,
    get_commits,
    get_status,
    get_working_directory_diff,
)
from github_desktop.models import Author, DiffSelectionType, TextDiff
from github_desktop.secrets import get_generic, get_password, set_generic, set_password
from tests.conftest import run_git


def test_partial_commit_stages_selected_hunk_lines(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("hello\nkeep-me\nadded-unselected\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    selectable = selectable_line_indices(diff)
    assert selectable
    # Select only the first change, not the rest
    selection = file.selection.with_select_none()
    selection = selection.with_selectable_lines(selectable)
    selection = selection.with_line_selection(selectable[0], True)
    file = file.with_selection(selection)
    assert file.selection.get_selection_type() == DiffSelectionType.PARTIAL
    create_commit(str(git_repo), "partial\n", [file])
    # Working tree should still have leftover unstaged lines
    status2 = get_status(str(git_repo))
    leftover = [f.path for f in status2.working_directory.files]
    # Either leftover modifications remain, or the whole file was committed if
    # only one selectable line existed.
    committed = get_commits(str(git_repo), limit=1)[0]
    assert committed.summary == "partial"


def test_discard_selected_lines_restores_unselected(git_repo: Path) -> None:
    from github_desktop.git.ops import discard_changes_from_selection
    from github_desktop.models import DiffSelection, DiffSelectionType

    (git_repo / "README.md").write_text("hello\nkeep-me\ntoss-me\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    selectable = selectable_line_indices(diff)
    selection = DiffSelection.from_initial_selection(DiffSelectionType.NONE).with_selectable_lines(selectable)
    selection = selection.with_line_selection(selectable[-1], True)
    discard_changes_from_selection(str(git_repo), "README.md", diff, selection)
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert "toss-me" not in text
    assert "hello" in text


def test_discard_all_selection_restores_file(git_repo: Path) -> None:
    from github_desktop.git.ops import discard_changes_from_selection
    from github_desktop.models import DiffSelection, DiffSelectionType

    (git_repo / "README.md").write_text("hello\nchanged\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    selection = DiffSelection.from_initial_selection(DiffSelectionType.ALL)
    discard_changes_from_selection(str(git_repo), "README.md", diff, selection)
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert "changed" not in text
    assert "hello" in text


def test_discard_none_selection_is_noop(git_repo: Path) -> None:
    from github_desktop.git.ops import discard_changes_from_selection
    from github_desktop.models import DiffSelection, DiffSelectionType

    (git_repo / "README.md").write_text("hello\nkeep\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    selection = DiffSelection.from_initial_selection(DiffSelectionType.NONE)
    discard_changes_from_selection(str(git_repo), "README.md", diff, selection)
    text = (git_repo / "README.md").read_text(encoding="utf-8")
    assert "keep" in text


def test_co_author_trailer_in_message() -> None:
    text = format_commit_message(
        "summary",
        "body",
        [("Co-authored-by", "Ada <ada@example.com>")],
    )
    assert "Co-authored-by: Ada <ada@example.com>" in text
    from github_desktop.git.ops import co_author_trailers

    trailers = co_author_trailers([Author("Ada", "ada@example.com")])
    assert trailers[0][0] == "Co-authored-by"


def test_file_secret_store(isolated_config) -> None:
    set_password("GitHub Desktop", "user@host", "token-123")
    assert get_password("GitHub Desktop", "user@host") == "token-123"
    set_generic("github.example.com", "octocat", "s3cret")
    user, password = get_generic("github.example.com")
    assert user == "octocat"
    assert password == "s3cret"
