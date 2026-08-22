"""Git progress parser tests matching Desktop's unit cases."""

from __future__ import annotations

import pytest

from github_desktop.git.progress import GitProgressParser, ProgressStep, parse_git_progress_line


def test_parser_requires_a_step() -> None:
    with pytest.raises(ValueError):
        GitProgressParser([])


def test_parses_progress_with_one_step() -> None:
    parser = GitProgressParser([ProgressStep("remote: Compressing objects", 1)])
    result = parser.parse("remote: Compressing objects:  72% (16/22)")
    assert result.percent == 16 / 22


def test_parses_progress_with_several_steps() -> None:
    parser = GitProgressParser(
        [
            ProgressStep("remote: Compressing objects", 0.5),
            ProgressStep("Receiving objects", 0.5),
        ]
    )
    result = parser.parse("remote: Compressing objects:  72% (16/22)")
    assert result.kind == "progress"
    assert result.percent == 16 / 22 / 2
    result = parser.parse("Receiving objects:  99% (166741/167587), 267.24 MiB | 2.40 MiB/s")
    assert result.kind == "progress"
    assert result.percent == 0.5 + 166741 / 167587 / 2


def test_enforces_ordering_of_steps() -> None:
    parser = GitProgressParser(
        [
            ProgressStep("remote: Compressing objects", 0.5),
            ProgressStep("Receiving objects", 0.5),
        ]
    )
    parser.parse("remote: Compressing objects:  72% (16/22)")
    parser.parse("Receiving objects:  99% (166741/167587), 267.24 MiB | 2.40 MiB/s")
    result = parser.parse("remote: Compressing objects:  72% (16/22)")
    assert result.kind == "context"


def test_parses_progress_with_no_total() -> None:
    result = parse_git_progress_line("remote: Counting objects: 167587")
    assert result is not None
    assert result.title == "remote: Counting objects"
    assert result.value == 167587
    assert result.done is False
    assert result.percent is None
    assert result.total is None


def test_parses_final_progress_with_no_total() -> None:
    result = parse_git_progress_line("remote: Counting objects: 167587, done.")
    assert result is not None
    assert result.value == 167587
    assert result.done is True


def test_parses_progress_with_total() -> None:
    result = parse_git_progress_line("remote: Compressing objects:  72% (16/22)")
    assert result is not None
    assert result.title == "remote: Compressing objects"
    assert result.value == 16
    assert result.percent == 72
    assert result.total == 22
    assert result.done is False


def test_parses_final_with_total() -> None:
    result = parse_git_progress_line("remote: Compressing objects: 100% (22/22), done.")
    assert result is not None
    assert result.value == 22
    assert result.done is True
    assert result.percent == 100
    assert result.total == 22


def test_parses_with_total_and_throughput() -> None:
    result = parse_git_progress_line(
        "Receiving objects:  99% (166741/167587), 267.24 MiB | 2.40 MiB/s"
    )
    assert result is not None
    assert result.title == "Receiving objects"
    assert result.value == 166741
    assert result.percent == 99
    assert result.total == 167587
    assert result.done is False


def test_format_rebase_value() -> None:
    from github_desktop.git.progress import format_rebase_value

    assert format_rebase_value(0.333) == 0.33
    assert format_rebase_value(-1) == 0
    assert format_rebase_value(2) == 1
    assert format_rebase_value(0.5) == 0.5


def test_rebase_parser() -> None:
    from github_desktop.git.progress import GitRebaseParser
    from github_desktop.models import CommitOneLine

    parser = GitRebaseParser([CommitOneLine("aaa", "first"), CommitOneLine("bbb", "second")])
    assert parser.parse("Applying: first") is None
    event = parser.parse("Rebasing (1/2)")
    assert event is not None
    assert event.position == 1
    assert event.total == 2
    assert event.current_commit_summary == "first"
    assert event.value == 0.5
    event = parser.parse("Rebasing (2/2)")
    assert event is not None
    assert event.position == 2
    assert event.current_commit_summary == "second"
    assert event.value == 1.0


def test_cherry_pick_parser() -> None:
    from github_desktop.git.progress import GitCherryPickParser
    from github_desktop.models import CommitOneLine

    parser = GitCherryPickParser([CommitOneLine("aaa", "pick me"), CommitOneLine("bbb", "and me")])
    assert parser.parse("Date: whenever") is None
    event = parser.parse("[main abcdef0] pick me")
    assert event is not None
    assert event.position == 1
    assert event.total == 2
    assert event.current_commit_summary == "pick me"
    assert event.value == 0.5
    event = parser.parse("[main 1234567] and me")
    assert event is not None
    assert event.position == 2
    assert event.value == 1.0


def test_parse_carriage_return_matches_desktop() -> None:
    from github_desktop.git.progress import parse_carriage_return

    clone_output = (
        "Cloning into '/Users/markus/Documents/GitHub/delete-branch-test'...\n"
        "remote: Enumerating objects: 8, done.        \n"
        "remote: Counting objects:  12% (1/8)        \r"
        "remote: Counting objects:  25% (2/8)        \r"
        "remote: Counting objects:  37% (3/8)        \r"
        "remote: Counting objects:  50% (4/8)        \r"
        "remote: Counting objects:  62% (5/8)        \r"
        "remote: Counting objects:  75% (6/8)        \r"
        "remote: Counting objects:  87% (7/8)        \r"
        "remote: Counting objects: 100% (8/8)        \r"
        "remote: Counting objects: 100% (8/8), done.        \n"
        "remote: Compressing objects:  16% (1/6)        \r"
        "remote: Compressing objects:  33% (2/6)        \r"
        "remote: Compressing objects:  50% (3/6)        \r"
        "remote: Compressing objects:  66% (4/6)        \r"
        "remote: Compressing objects:  83% (5/6)        \r"
        "remote: Compressing objects: 100% (6/6)        \r"
        "remote: Compressing objects: 100% (6/6), done.        \n"
        "remote: Total 8 (delta 1), reused 7 (delta 0), pack-reused 0        \n"
        "\r"
        "                                                                                \r"
        "Receiving objects:  12% (1/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  25% (2/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  37% (3/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  50% (4/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  62% (5/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  75% (6/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects:  87% (7/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects: 100% (8/8)\r"
        "\r"
        "                                                                                \r"
        "Receiving objects: 100% (8/8), done.\n"
        "\r"
        "                                                                                \r"
        "Resolving deltas:   0% (0/1)\r"
        "\r"
        "                                                                                \r"
        "Resolving deltas: 100% (1/1)\r"
        "\r"
        "                                                                                \r"
        "Resolving deltas: 100% (1/1), done.\n"
        "fatal: multiple updates for ref 'refs/remotes/origin/pr/1' not allowed\n"
    )
    expected = (
        "Cloning into '/Users/markus/Documents/GitHub/delete-branch-test'...\n"
        "remote: Enumerating objects: 8, done.        \n"
        "remote: Counting objects: 100% (8/8), done.        \n"
        "remote: Compressing objects: 100% (6/6), done.        \n"
        "remote: Total 8 (delta 1), reused 7 (delta 0), pack-reused 0        \n"
        "Receiving objects: 100% (8/8), done.                                            \n"
        "Resolving deltas: 100% (1/1), done.                                             \n"
        "fatal: multiple updates for ref 'refs/remotes/origin/pr/1' not allowed\n"
    )
    assert parse_carriage_return(clone_output) == expected
    assert parse_carriage_return("foo") == "foo"
    assert parse_carriage_return("foo\nbar") == "foo\nbar"
    assert parse_carriage_return("foo\r") == "foo"
    assert parse_carriage_return("foo\nbar\r") == "foo\nbar"
    assert parse_carriage_return("foo\rbar") == "bar"
    assert parse_carriage_return("foo\r\r\r\r\rbar") == "bar"
    assert parse_carriage_return("foo\rfoo\u2028bar\u2029foo") == "foo\u2028bar\u2029foo"
    assert parse_carriage_return("foobar\rfooba\rfoob\rfoo\r\fo\rF\r") == "Foobar"
    assert parse_carriage_return("A\r\nB\r\nC\r\nD\r\n") == "A\nB\nC\nD\n"
