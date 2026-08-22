"""Protocol URL parsing (parity with parse-app-url)."""

from github_desktop.protocol import OAuthAction, OpenRepositoryAction, UnknownAction, parse_app_url


def test_oauth_url() -> None:
    action = parse_app_url(
        "x-github-client://oauth?code=18142422&state=e4cd2dea-1567-46aa-8eb2-c7f56e943187"
    )
    assert isinstance(action, OAuthAction)
    assert action.code == "18142422"
    assert action.state == "e4cd2dea-1567-46aa-8eb2-c7f56e943187"


def test_openrepo_url() -> None:
    action = parse_app_url("x-github-client://openRepo/https://github.com/desktop/desktop?branch=main")
    assert isinstance(action, OpenRepositoryAction)
    assert "github.com/desktop/desktop" in action.url
    assert action.branch == "main"


def test_invalid_pr_rejected() -> None:
    action = parse_app_url("x-github-client://openRepo/https://github.com/desktop/desktop?pr=notanumber")
    assert isinstance(action, UnknownAction)


def test_oauth_missing_state() -> None:
    action = parse_app_url("x-github-client://oauth?code=abc")
    assert isinstance(action, UnknownAction)
