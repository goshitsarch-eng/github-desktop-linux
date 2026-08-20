"""Settings, models, OAuth URL, remote parsing, identity validation."""

from __future__ import annotations

from github_desktop.github.oauth import get_oauth_authorization_url, oauth_client_id
from github_desktop.models import (
    ApplicationTheme,
    DiffSelection,
    DiffSelectionType,
    git_author_name_is_valid,
    html_url_from_endpoint,
    sanitize_ref_name,
)
from github_desktop.remote_parsing import parse_remote
from github_desktop.settings import Settings, load_settings, save_settings
from github_desktop.version import OAUTH_SCOPES


def test_theme_values() -> None:
    assert ApplicationTheme.LIGHT.value == "light"
    assert ApplicationTheme.DARK.value == "dark"
    assert ApplicationTheme.SYSTEM.value == "system"


def test_diff_selection_toggle() -> None:
    sel = DiffSelection.from_initial_selection(DiffSelectionType.ALL)
    assert sel.get_selection_type() == DiffSelectionType.ALL
    sel = sel.with_line_selection(3, False)
    assert sel.get_selection_type() == DiffSelectionType.PARTIAL
    assert not sel.is_selected(3)
    assert sel.is_selected(2)
    none = sel.with_select_none()
    assert none.get_selection_type() == DiffSelectionType.NONE
    ranged = DiffSelection.from_initial_selection(DiffSelectionType.ALL).with_range_selection(2, 3, False)
    assert not ranged.is_selected(2)
    assert not ranged.is_selected(4)
    assert ranged.is_selected(1)
    assert ranged.is_selected(5)


def test_author_name_validation() -> None:
    # Desktop `identifier-rules-test.ts` / `gitAuthorNameIsValid`
    assert git_author_name_is_valid("Ada Lovelace")
    assert git_author_name_is_valid("this is great")
    assert git_author_name_is_valid("")
    assert git_author_name_is_valid("bad:name")
    assert git_author_name_is_valid("this is great")
    assert not git_author_name_is_valid(".")
    assert not git_author_name_is_valid(",")
    assert not git_author_name_is_valid(":")
    assert not git_author_name_is_valid(";")
    assert not git_author_name_is_valid("<")
    assert not git_author_name_is_valid(">")
    assert not git_author_name_is_valid('"')
    assert not git_author_name_is_valid("\\")
    assert not git_author_name_is_valid("'")
    assert not git_author_name_is_valid(" ")
    assert not git_author_name_is_valid(".;:<>")
    for code in range(33):
        assert not git_author_name_is_valid(chr(code))
    assert git_author_name_is_valid(chr(33))
    assert git_author_name_is_valid(f";hi. there;{chr(31)}")


def test_highlight_text_runs() -> None:
    from github_desktop.models import highlight_text_runs

    runs = highlight_text_runs("hello", [0, 1, 4])
    assert runs == [("he", True), ("ll", False), ("o", True)]


def test_sanitize_ref() -> None:
    assert ".." not in sanitize_ref_name("foo..bar")
    assert " " not in sanitize_ref_name("my branch")


def test_html_url() -> None:
    assert html_url_from_endpoint("https://api.github.com") == "https://github.com"
    assert html_url_from_endpoint("https://github.example.com/api/v3") == "https://github.example.com"
    assert html_url_from_endpoint("https://api.acme.ghe.com") == "https://acme.ghe.com"


def test_parse_remotes() -> None:
    ssh = parse_remote("git@github.com:desktop/desktop.git")
    assert ssh and ssh.owner == "desktop" and ssh.name == "desktop"
    https = parse_remote("https://github.com/desktop/desktop")
    assert https and https.hostname == "github.com"


def test_is_github_host() -> None:
    from github_desktop.remote_parsing import get_api_endpoint, is_github_host

    assert is_github_host("https://github.com/desktop/desktop.git")
    assert is_github_host("git@github.com:desktop/desktop.git")
    assert is_github_host("https://acme.ghe.com/org/repo.git")
    assert not is_github_host("https://gitlab.com/org/repo.git")
    assert not is_github_host("https://bitbucket.org/org/repo.git")
    assert get_api_endpoint("https://github.com/a/b.git") == "https://api.github.com"


def test_oauth_url_contains_scopes_and_state() -> None:
    url = get_oauth_authorization_url("https://api.github.com", "abc-state")
    assert "client_id=" in url
    assert oauth_client_id() in url
    assert "state=abc-state" in url
    for scope in OAUTH_SCOPES:
        assert scope in url


def test_settings_roundtrip(isolated_config, tmp_path) -> None:
    path = tmp_path / "settings.json"
    s = Settings(theme="dark", tab_size=2, confirm_force_push=False)
    save_settings(s, path)
    loaded = load_settings(path)
    assert loaded.theme == "dark"
    assert loaded.tab_size == 2
    assert loaded.confirm_force_push is False
