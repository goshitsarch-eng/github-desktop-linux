"""Desktop credential-helper trampoline and isGitHubHost /meta probe."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from urllib.error import HTTPError
from urllib.request import Request

from github_desktop import secrets
from github_desktop.git.credential_helper import (
    createCredentialHelperTrampolineHandler,
    create_credential_helper_trampoline_handler,
    credential_helper_env,
    find_github_trampoline_account,
    get_credential,
    get_credential_url,
    get_endpoint_kind,
    store_credential,
    erase_credential,
    url_without_credentials,
)
from github_desktop.git.runner import env_for_remote
from github_desktop.models import Account
from github_desktop.remote_parsing import get_api_endpoint, is_github_host, probe_github_host
from github_desktop.store import AppStore


def test_url_without_credentials_strips_userinfo() -> None:
    assert url_without_credentials("https://alice@gitlab.example.com/org/repo.git") == (
        "https://gitlab.example.com/org/repo.git"
    )
    cred = {
        "protocol": "https",
        "host": "gitlab.example.com",
        "path": "org/repo.git",
        "username": "alice",
    }
    assert "alice@" in get_credential_url(cred)
    assert url_without_credentials(get_credential_url(cred)) == "https://gitlab.example.com/org/repo.git"


def test_get_api_endpoint_matches_desktop() -> None:
    assert get_api_endpoint("https://github.com/desktop/desktop.git") == "https://api.github.com"
    assert get_api_endpoint("https://acme.ghe.com/org/repo.git") == "https://api.acme.ghe.com"
    assert get_api_endpoint("https://github.mycompany.com/org/repo.git") == "https://github.mycompany.com/api/v3"


def test_is_github_host_skips_probe_by_default(isolated_config) -> None:
    from github_desktop import remote_parsing

    remote_parsing._endpoint_versions.clear()
    assert not is_github_host("https://ghe.internal.example/org/repo.git")
    assert is_github_host("https://github.com/desktop/desktop.git")
    assert not is_github_host("https://gitlab.com/org/repo.git")


def test_probe_github_host_meta_header(isolated_config, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_DESKTOP_ALLOW_META_PROBE", "1")
    seen: list[str] = []

    class Resp:
        headers = Message()

        def __init__(self) -> None:
            self.headers["x-github-request-id"] = "abc-123"
            self.headers["x-github-enterprise-version"] = "3.12.0"

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class Opener:
        def open(self, req: Request, timeout: float | None = None):
            seen.append(req.full_url)
            assert req.get_method() == "HEAD"
            assert timeout == 2.0
            return Resp()

    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: Opener())
    url = "https://ghe.internal.example/org/repo.git"
    assert probe_github_host(url) is True
    assert seen and "/meta?ghd=" in seen[0]
    assert is_github_host(url, probe=True) is True


def test_probe_github_host_http_error_still_checks_header(isolated_config, monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_DESKTOP_ALLOW_META_PROBE", "1")
    headers = Message()
    headers["X-GitHub-Request-Id"] = "from-error"

    class Opener:
        def open(self, req: Request, timeout: float | None = None):
            raise HTTPError(req.full_url, 404, "Not Found", headers, BytesIO(b""))

    monkeypatch.setattr("urllib.request.build_opener", lambda *_a, **_k: Opener())
    assert probe_github_host("https://mystery.example/a/b.git") is True


def test_github_account_get_credential() -> None:
    account = Account(login="octocat", endpoint="https://api.github.com", token="gho_secret")
    cred = {"protocol": "https", "host": "github.com", "path": "desktop/desktop.git"}
    assert find_github_trampoline_account([account], get_credential_url(cred)) is account
    filled = get_credential(cred, [account])
    assert filled is not None
    assert filled["username"] == "octocat"
    assert filled["password"] == "gho_secret"


def test_wwwauth_github_realm_prompts_sign_in() -> None:
    seen: list[str] = []
    account = Account(login="enterprise", endpoint="https://github.mycompany.com/api/v3", token="ent")
    cred = {
        "protocol": "https",
        "host": "github.mycompany.com",
        "path": "org/repo.git",
        "wwwauth[0]": 'Bearer realm="GitHub"',
    }
    assert get_endpoint_kind(cred, []) == "enterprise"
    filled = get_credential(cred, [], prompt_github=lambda url: seen.append(url) or account)
    assert seen
    assert filled is not None
    assert filled["password"] == "ent"


def test_gitlab_realm_is_generic(isolated_config) -> None:
    cred = {
        "protocol": "https",
        "host": "gitlab.example.com",
        "path": "org/repo.git",
        "wwwauth[0]": 'Basic realm="GitLab"',
        "username": "alice",
        "password": "s3cret",
    }
    assert get_endpoint_kind(cred, []) == "generic"
    store_credential(cred, [])
    user, password = secrets.get_generic("gitlab.example.com")
    assert user == "alice"
    assert password == "s3cret"
    erase_credential(cred, [])
    _user, gone = secrets.get_generic("gitlab.example.com")
    assert gone is None
    cred = {
        "protocol": "https",
        "host": "gitlab.example.com",
        "path": "org/repo.git",
        "wwwauth[0]": 'Basic realm="GitLab"',
        "username": "alice",
        "password": "s3cret",
    }
    assert get_endpoint_kind(cred, []) == "generic"
    store_credential(cred, [])
    user, password = secrets.get_generic("gitlab.example.com")
    assert user == "alice"
    assert password == "s3cret"
    erase_credential(cred, [])
    _user, gone = secrets.get_generic("gitlab.example.com")
    assert gone is None


def test_gist_is_generic() -> None:
    cred = {"protocol": "https", "host": "gist.github.com", "path": "abc123"}
    assert get_endpoint_kind(cred, []) == "generic"


def test_github_store_does_not_persist_generic(isolated_config) -> None:
    account = Account(login="octocat", endpoint="https://api.github.com", token="gho_secret")
    cred = {
        "protocol": "https",
        "host": "github.com",
        "path": "a/b.git",
        "username": "octocat",
        "password": "gho_secret",
    }
    store_credential(cred, [account])
    _user, password = secrets.get_generic("github.com")
    assert password is None


def test_background_skips_prompts() -> None:
    called: list[str] = []
    cred = {"protocol": "https", "host": "gitlab.com", "path": "a/b.git"}
    assert (
        get_credential(
            cred,
            [],
            background=True,
            prompt_generic=lambda *_a: called.append("generic") or {"login": "x", "token": "y"},
        )
        is None
    )
    assert called == []
    gh = {"protocol": "https", "host": "github.com", "path": "a/b.git"}
    assert (
        get_credential(
            gh,
            [],
            background=True,
            prompt_github=lambda url: called.append(url) or Account("n", "https://api.github.com", "t"),
        )
        is None
    )
    assert called == []


def test_create_credential_helper_trampoline_handler() -> None:
    account = Account(login="octocat", endpoint="https://api.github.com", token="gho_secret")
    assert createCredentialHelperTrampolineHandler is create_credential_helper_trampoline_handler
    handler = create_credential_helper_trampoline_handler([account])
    out = handler("get", "protocol=https\nhost=github.com\npath=desktop/desktop.git\n")
    assert out is not None
    assert "username=octocat" in out
    assert "password=gho_secret" in out
    assert handler("store", out) is None


def test_credential_helper_env_git_config_parameters(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    from github_desktop.paths import cache_dir

    sock = cache_dir() / "credential-helper.sock"
    sock.parent.mkdir(parents=True, exist_ok=True)
    sock.write_text("", encoding="utf-8")
    env = credential_helper_env(path="/tmp/repo", background=True)
    assert "GIT_CONFIG_PARAMETERS" in env
    assert "'credential.helper='" in env["GIT_CONFIG_PARAMETERS"]
    assert "credential.helper=" in env["GIT_CONFIG_PARAMETERS"]
    assert env["GITHUB_DESKTOP_BACKGROUND_TASK"] == "1"
    assert env["GITHUB_DESKTOP_TRAMPOLINE_PATH"] == "/tmp/repo"


def test_env_for_remote_keeps_helper_and_extra_header() -> None:
    extra = {"GIT_CONFIG_PARAMETERS": "'credential.helper=' 'credential.helper=/tmp/desktop'"}
    env = env_for_remote("https://github.com/a/b.git", token="t", extra=extra)
    assert env["GIT_CONFIG_PARAMETERS"] == extra["GIT_CONFIG_PARAMETERS"]
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert "AUTHORIZATION: basic " in env["GIT_CONFIG_VALUE_0"]


def test_app_store_handle_credential_github(isolated_config) -> None:
    store = AppStore()
    account = Account(login="octocat", endpoint="https://api.github.com", token="gho_secret")
    store.accounts = [account]
    filled = store.handle_credential(
        "get",
        {"protocol": "https", "host": "github.com", "path": "a/b.git"},
    )
    assert filled is not None
    assert filled["username"] == "octocat"
    assert filled["password"] == "gho_secret"


def test_generic_prompt_path(isolated_config) -> None:
    cred = {"protocol": "https", "host": "git.example.com", "path": "a/b.git"}
    filled = get_credential(
        cred,
        [],
        prompt_generic=lambda endpoint, username: {"login": "me", "token": "pw"},
    )
    assert filled is not None
    assert filled["username"] == "me"
    assert filled["password"] == "pw"
