"""Desktop `formatCommitMessage` whitespace and interpret-trailers parity."""

from __future__ import annotations

from pathlib import Path

from github_desktop.format_commit_message import format_commit_message
from github_desktop.git.ops import merge_trailers


def test_always_adds_trailing_newline() -> None:
    assert format_commit_message("test", None) == "test\n"
    assert format_commit_message("test", "test") == "test\n\ntest\n"


def test_omits_description_when_null_or_empty() -> None:
    assert format_commit_message("test", None) == "test\n"
    assert format_commit_message("test", "") == "test\n"
    assert format_commit_message("test", "   ") == "test\n"


def test_adds_two_newlines_between_summary_and_description() -> None:
    assert format_commit_message("foo", "bar") == "foo\n\nbar\n"


def test_preserves_leading_summary_whitespace() -> None:
    assert format_commit_message("  foo", "bar") == "  foo\n\nbar\n"


def test_appends_trailers_without_repo() -> None:
    trailers = [
        ("Co-Authored-By", "Markus Olsson <niik@github.com>"),
        ("Signed-Off-By", "nerdneha <nerdneha@github.com>"),
    ]
    assert format_commit_message("foo", None, trailers) == (
        "foo\n\n"
        "Co-Authored-By: Markus Olsson <niik@github.com>\n"
        "Signed-Off-By: nerdneha <nerdneha@github.com>\n"
    )
    assert format_commit_message("foo", "bar", trailers) == (
        "foo\n\nbar\n\n"
        "Co-Authored-By: Markus Olsson <niik@github.com>\n"
        "Signed-Off-By: nerdneha <nerdneha@github.com>\n"
    )


def test_merges_duplicate_trailers(git_repo: Path) -> None:
    trailers = [
        ("Co-Authored-By", "Markus Olsson <niik@github.com>"),
        ("Signed-Off-By", "nerdneha <nerdneha@github.com>"),
    ]
    assert format_commit_message(
        "foo",
        "Co-Authored-By: Markus Olsson <niik@github.com>",
        trailers,
        repo=str(git_repo),
    ) == (
        "foo\n\n"
        "Co-Authored-By: Markus Olsson <niik@github.com>\n"
        "Signed-Off-By: nerdneha <nerdneha@github.com>\n"
    )


def test_fixes_malformed_trailers_when_trailers_are_given(git_repo: Path) -> None:
    trailers = [("Signed-Off-By", "nerdneha <nerdneha@github.com>")]
    assert format_commit_message(
        "foo",
        "Co-Authored-By:Markus Olsson <niik@github.com>",
        trailers,
        repo=str(git_repo),
    ) == (
        "foo\n\n"
        "Co-Authored-By: Markus Olsson <niik@github.com>\n"
        "Signed-Off-By: nerdneha <nerdneha@github.com>\n"
    )


def test_does_not_treat_divider_as_end_of_commit_message(git_repo: Path) -> None:
    trailers = [("Signed-Off-By", "nerdneha <nerdneha@github.com>")]
    description = "hello\n---\nworld\n\nCo-Authored-By: Markus Olsson <niik@github.com>"
    assert format_commit_message("foo", description, trailers, repo=str(git_repo)) == (
        "foo\n\nhello\n---\nworld\n\n"
        "Co-Authored-By: Markus Olsson <niik@github.com>\n"
        "Signed-Off-By: nerdneha <nerdneha@github.com>\n"
    )


def test_merge_trailers_uses_no_divider(git_repo: Path) -> None:
    message = "foo\n\nhello\n---\nworld\n"
    merged = merge_trailers(
        str(git_repo),
        message,
        [("Signed-Off-By", "nerdneha <nerdneha@github.com>")],
    )
    assert "---" in merged
    assert "Signed-Off-By: nerdneha <nerdneha@github.com>" in merged
