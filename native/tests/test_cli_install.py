"""CLI helper install path used by File → Install command line tool."""

from __future__ import annotations

from pathlib import Path

from github_desktop.install_cli import cli_is_installed, install_cli
from github_desktop.models import Branch, BranchType, parse_name_email
from github_desktop.ui.emoji import expand_shortcodes, matching_shortcodes


def test_install_cli_writes_executable(tmp_path: Path) -> None:
    dest = tmp_path / "bin" / "github"
    path = install_cli(dest)
    assert path == dest
    assert dest.is_file()
    assert cli_is_installed(dest)
    text = dest.read_text(encoding="utf-8")
    assert "github_desktop.cli" in text
    assert dest.stat().st_mode & 0o111


def test_parse_mention_coauthor() -> None:
    name, email = parse_name_email("@octocat")
    assert name == "octocat"
    assert email == "octocat@users.noreply.github.com"


def test_emoji_shortcodes() -> None:
    assert "🚀" in expand_shortcodes("ship it :rocket:")
    assert ":sparkles:" in matching_shortcodes("spa")


def test_group_branches_default_recent_other() -> None:
    from github_desktop.ui.branches import group_branches

    default = Branch("main", None, "aaa", BranchType.LOCAL)
    topic = Branch("topic", None, "bbb", BranchType.LOCAL)
    extra = Branch("extra", None, "ccc", BranchType.LOCAL)
    groups = group_branches(
        [default, topic, extra],
        current="topic",
        default_name="main",
        recent_names=["topic"],
    )
    titles = [title for title, _ in groups]
    assert titles[0] == "Default"
    assert "Recent" in titles
    assert groups[0][1][0].name == "main"
