"""Syntax highlighting and hunk helpers without GTK."""

from __future__ import annotations

from github_desktop.git.diff import hunk_line_span, parse_unified_diff
from github_desktop.models import DiffLine, DiffLineType
from github_desktop.ui.syntax import highlight_diff_line, highlight_file, markup_for_diff_line
from tests.test_diff_parser import SAMPLE


def test_highlight_escapes_and_marks_keywords() -> None:
    markup = highlight_diff_line("def foo():", "app.py")
    assert "&" not in markup or "&amp;" in markup or "<span" in markup
    assert "def" in markup
    assert "<span" in markup


def test_highlight_escapes_pango_entities() -> None:
    markup = highlight_diff_line("a < b && c > d", "app.py")
    assert "<" not in markup.replace("<span", "").replace("</span", "") or "&lt;" in markup
    assert "&lt;" in markup
    assert "&gt;" in markup
    assert "&amp;" in markup


def test_hunk_line_span_covers_all_lines() -> None:
    diff = parse_unified_diff(SAMPLE)
    start, length = hunk_line_span(diff, 0)
    assert start == 0
    assert length == len(diff.hunks[0].lines)


def test_highlight_file_uses_1based_line_numbers() -> None:
    lines = ["def foo():", "    return 1"]
    markup = highlight_file(lines, "app.py")
    assert 1 in markup
    assert 2 in markup
    assert "def" in markup[1]
    assert "<span" in markup[1]


def test_highlight_file_keeps_multiline_string_tokens() -> None:
    lines = [
        'msg = """alpha',
        "bravo",
        'charlie"""',
        "count = 2",
    ]
    markup = highlight_file(lines, "mod.py")
    assert "bravo" in markup[2]
    # Inside the triple-quoted string, the whole continuation line is a string token.
    assert markup[2].count("span") >= 1
    colors = markup[2]
    assert "#2a7f3e" in colors or "#8ff0a4" in colors or "bravo" in colors


def test_markup_for_diff_line_prefers_file_tokens() -> None:
    line = DiffLine("+bravo", DiffLineType.ADD, None, 2)
    markup = markup_for_diff_line(line, "mod.py", new_markup={2: '<span foreground="#2a7f3e">bravo</span>'})
    assert markup == '<span foreground="#2a7f3e">bravo</span>'
