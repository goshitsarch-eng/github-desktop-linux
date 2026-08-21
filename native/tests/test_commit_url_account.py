"""Desktop createCommitURL, findAccountForRemoteURL, endpointSatisfies, git parsers."""

from __future__ import annotations

import hashlib

from packaging.version import Version

from github_desktop.commit_url import create_commit_url
from github_desktop.endpoint_capabilities import (
    assumedGHESVersion,
    endpoint_satisfies,
    supports_avatars_api,
    supports_repo_rules,
    supports_rerunning_checks,
    supports_rerunning_individual_or_failed_checks,
)
from github_desktop.find_account import find_account_for_remote_url
from github_desktop.git.delimiter import (
    create_for_each_ref_parser,
    create_log_parser,
    split_buffer,
)
from github_desktop.models import Account, GitHubRepository
from github_desktop.remote_parsing import get_api_endpoint
from github_desktop.store import AppStore


def _dotcom(login: str, token: str = "deadbeef", account_id: int = 1) -> Account:
    return Account(
        login=login,
        endpoint="https://api.github.com",
        token=token,
        id=account_id,
        name="GitHub",
        plan="free",
    )


def _can_access(account: Account, owner: str, name: str) -> bool:
    if account.endpoint == "https://api.github.com" and account.login == "joan" and owner == "desktop" and name == "repo-fixture":
        return True
    if account.endpoint == "https://api.github.com" and owner == "inkscape" and name == "inkscape":
        return True
    return False


def test_create_commit_url_hashes_file_path() -> None:
    gh = GitHubRepository(
        name="r",
        owner="o",
        html_url="https://github.com/o/r",
        clone_url="https://github.com/o/r.git",
    )
    assert create_commit_url(gh, "abc123") == "https://github.com/o/r/commit/abc123"
    digest = hashlib.sha256(b"src/app.ts").hexdigest()
    assert create_commit_url(gh, "abc123", "src/app.ts") == f"https://github.com/o/r/commit/abc123#diff-{digest}"
    assert create_commit_url(None, "abc") is None
    empty = GitHubRepository(name="r", owner="o", html_url="", clone_url="")
    assert create_commit_url(empty, "abc") is None


def test_find_account_for_remote_url_matches_desktop() -> None:
    accounts = [
        _dotcom("joan"),
        Account(
            login="joel",
            endpoint=get_api_endpoint("https://github.mycompany.com"),
            token="deadbeef",
            id=2,
            name="My Company",
            plan="free",
        ),
    ]
    assert find_account_for_remote_url("https://gitlab.com/inkscape/inkscape.git", accounts, _can_access) is None
    assert find_account_for_remote_url("desktop/nonexistent-repo-fixture", accounts, _can_access) is None
    anon = find_account_for_remote_url("inkscape/inkscape", [], _can_access)
    assert anon == Account.anonymous()
    anon_url = find_account_for_remote_url("https://github.com/inkscape/inkscape", [], _can_access)
    assert anon_url == Account.anonymous()
    found = find_account_for_remote_url("inkscape/inkscape", accounts, _can_access)
    assert found is not None and found.login == "joan"
    github = find_account_for_remote_url("https://github.com/inkscape/inkscape.git", accounts, _can_access)
    assert github is not None and github.login == "joan"
    enterprise = find_account_for_remote_url(
        "https://github.mycompany.com/inkscape/inkscape.git", accounts, _can_access
    )
    assert enterprise is not None and enterprise.login == "joel"
    private = find_account_for_remote_url("desktop/repo-fixture", accounts, _can_access)
    assert private is not None and private.login == "joan"
    assert find_account_for_remote_url("desktop/repo-fixture", [], _can_access) is None


def _endpoint(endpoint: str, constraint: dict, version: str | None = None) -> bool:
    parsed = Version(version) if version else None
    return endpoint_satisfies(constraint, lambda _ep: parsed)(endpoint)


def test_endpoint_satisfies_matches_desktop() -> None:
    assert _endpoint("https://api.github.com", {"dotcom": True, "ghe": False, "es": False}) is True
    assert _endpoint("https://api.github.com", {"dotcom": False, "ghe": False, "es": False}) is False
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": False}) is False
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": True}) is True
    assert _endpoint("https://corp.ghe.com", {"dotcom": False, "ghe": False, "es": False}) is False
    assert _endpoint("https://corp.ghe.com", {"dotcom": False, "ghe": True, "es": False}) is True
    assert assumedGHESVersion == Version("3.1.0")
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": ">= 3.1.1"}) is False
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": ">= 3.1.0"}) is True
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": ">= 1"}, "1.0.0") is True
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": "> 1.0.0"}, "1.0.0") is False
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": "> 0.9.9"}, "1.0.0") is True
    assert _endpoint("https://api.github.com", {"dotcom": True, "ghe": False, "es": ">= 3.0.0"}) is True
    assert _endpoint("https://ghe.io", {"dotcom": False, "ghe": False, "es": ">= 3.1.0"}, "3.1.0") is True
    assert supports_repo_rules("https://api.github.com") is True
    assert supports_repo_rules("https://ghe.io") is False
    assert supports_repo_rules("https://corp.ghe.com") is True
    assert supports_rerunning_individual_or_failed_checks("https://api.github.com") is True
    assert supports_rerunning_individual_or_failed_checks("https://ghe.io") is False
    assert supports_rerunning_checks("https://ghe.io") is False
    assert supports_avatars_api("https://ghe.io") is True


def test_split_buffer_and_git_format_parsers() -> None:
    assert split_buffer(b"a\0b\0c", "\0") == [b"a", b"b", b"c"]
    assert split_buffer(b"a\0", "\0") == [b"a", b""]
    log = create_log_parser({"sha": "%H", "summary": "%s"})
    assert log.format_args == ("-z", "--format=%H%x00%s")
    # git log -z emits a trailing NUL, which Desktop's loop (`i < length - keys`) requires.
    parsed = log.parse("abc\0hello\0def\0world\0")
    assert parsed == [{"sha": "abc", "summary": "hello"}, {"sha": "def", "summary": "world"}]
    refs = create_for_each_ref_parser(
        {
            "refname": "%(refname)",
            "short": "%(refname:short)",
            "sha": "%(objectname)",
        }
    )
    raw = "\0refs/heads/main\0main\0aaa\0\n\0refs/heads/topic\0topic\0bbb\0\n"
    entries = refs.parse(raw)
    assert [item["short"] for item in entries] == ["main", "topic"]
    assert entries[0]["sha"] == "aaa"


def test_ahead_behind_cache_is_lru(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repo = store.add_repositories([str(git_repo)])[0]
    calls: list[tuple[str, str]] = []

    def fake_range(path: str, spec: str):
        calls.append((path, spec))
        from github_desktop.models import AheadBehind

        return AheadBehind(ahead=1, behind=0)

    monkeypatch.setattr("github_desktop.store.get_ahead_behind_range", fake_range)
    first = store.ahead_behind_between(repo, "aaa", "bbb")
    second = store.ahead_behind_between(repo, "aaa", "bbb")
    assert first == second
    assert len(calls) == 1
    assert len(store._ahead_behind_cache) == 1


def test_get_account_for_endpoint_and_repository() -> None:
    from github_desktop.get_account import get_account_for_endpoint, get_account_for_repository
    from github_desktop.git_error_context import error_dialog_title
    from github_desktop.models import RetryAction, RetryActionType

    joan = _dotcom("joan")
    repo = __import__("github_desktop.models", fromlist=["Repository", "GitHubRepository"])
    gh = repo.GitHubRepository(
        name="hello",
        owner="octocat",
        html_url="https://github.com/octocat/hello",
        clone_url="https://github.com/octocat/hello.git",
        endpoint="https://api.github.com",
    )
    repository = repo.Repository(id=1, path="/tmp/hello", name="hello", github=gh)
    assert get_account_for_endpoint([joan], "https://api.github.com") is joan
    assert get_account_for_endpoint([joan], "https://ghe.io/api/v3") is None
    assert get_account_for_repository([joan], repository) is joan
    assert error_dialog_title(git_context={"kind": "create-repository"}) == "Failed creating repository"
    assert error_dialog_title(retry_action=RetryAction(type=RetryActionType.PUSH, repo_id=1)) == "Failed to push"
    assert error_dialog_title(retry_clone=True) == "Clone failed"
    assert error_dialog_title(git_error="PushWithFileSizeExceedingLimit") == "File size limit exceeded"
    assert error_dialog_title(copilot_quota=True) == "Quota exceeded"


def test_get_commits_truncates_like_desktop(git_repo) -> None:
    from github_desktop.git.ops import COMMIT_MESSAGE_MAX_BYTES, get_commits

    commits = get_commits(str(git_repo), limit=1)
    assert commits
    assert commits[0].summary
    assert commits[0].sha
    assert COMMIT_MESSAGE_MAX_BYTES == 100 * 1024


def test_shorten_github_autolinks() -> None:
    from github_desktop.ui.markdown import markdown_to_pango, shorten_github_autolink

    repo = "https://github.com/octo/hello"
    assert shorten_github_autolink("https://github.com/octo/hello/issues/42", repo) == "#42"
    assert shorten_github_autolink("https://github.com/octo/hello/pull/9#discussioncomment-1", repo) == "#9 (comment)"
    assert shorten_github_autolink("https://github.com/octo/hello/pull/9/files", repo) is None
    assert shorten_github_autolink("https://github.com/other/repo/issues/1", repo) is None
    long_sha = "6fd794543af171c35cc9c325f570f9553128ffc9"
    assert "<tt>6fd7945</tt>" in (shorten_github_autolink(f"https://github.com/octo/hello/commit/{long_sha}", repo) or "")
    other = shorten_github_autolink(f"https://github.com/desktop/desktop/commit/{long_sha}", repo)
    assert other is not None and other.startswith("desktop/desktop@")
    markup = markdown_to_pango(
        "See https://github.com/octo/hello/issues/42 please",
        repo_html_url=repo,
    )
    assert ">#42</a>" in markup
    assert "href=\"https://github.com/octo/hello/issues/42\"" in markup


def test_commit_mention_owner_repo_and_range() -> None:
    from github_desktop.ui.markdown import markdown_to_pango, resolve_owner_repo

    repo = "https://github.com/octo/hello"
    assert resolve_owner_repo("desktop/desktop", ("octo", "hello")) == ["desktop", "desktop"]
    assert resolve_owner_repo("octo/hello", ("octo", "hello")) == []
    assert resolve_owner_repo("octo", ("octo", "hello")) == []
    assert resolve_owner_repo("other", ("octo", "hello")) is None
    owned = markdown_to_pango("See desktop/desktop@1234567 for context", repo_html_url=repo)
    assert "desktop/desktop@" in owned
    assert "<tt>1234567</tt>" in owned
    assert 'href="https://github.com/desktop/desktop/commit/1234567"' in owned
    same = markdown_to_pango("See octo/hello@abcdef1 here", repo_html_url=repo)
    assert "octo/hello@" not in same
    assert 'href="https://github.com/octo/hello/commit/abcdef1"' in same
    ranged = markdown_to_pango("Compare abcdef1...1234567", repo_html_url=repo)
    assert "compare/abcdef1...1234567" in ranged
    invalid = markdown_to_pango("See otheruser@abcdef1 please", repo_html_url=repo)
    assert "commit/abcdef1" not in invalid


def test_get_os_default_dir_and_git_on_path(tmp_path, monkeypatch) -> None:
    import platform

    from github_desktop.features import should_render_application_menu
    from github_desktop.git.runner import find_git_on_path, is_git_on_path
    from github_desktop.linux import get_os
    from github_desktop.settings import LAST_CLONE_LOCATION_KEY, Settings, get_default_dir, set_default_dir

    assert get_os() == f"{platform.system()} {platform.release()}"
    assert is_git_on_path() is True
    assert find_git_on_path()
    assert LAST_CLONE_LOCATION_KEY == "last-clone-location"
    settings = Settings()
    assert get_default_dir(settings).endswith("Documents/GitHub")
    set_default_dir(settings, str(tmp_path))
    assert get_default_dir(settings) == str(tmp_path)
    monkeypatch.delenv("GITHUB_DESKTOP_FEATURE_SHOULD_RENDER_APPLICATION_MENU", raising=False)
    assert should_render_application_menu() is True
    monkeypatch.setenv("GITHUB_DESKTOP_FEATURE_SHOULD_RENDER_APPLICATION_MENU", "0")
    assert should_render_application_menu() is False
