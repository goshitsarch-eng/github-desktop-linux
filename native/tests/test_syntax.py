"""Syntax highlighting and hunk helpers without GTK."""

from __future__ import annotations

from github_desktop.git.diff import hunk_line_span, parse_unified_diff
from github_desktop.ui.syntax import highlight_diff_line
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
