"""Token invalidation, push flags, GCM helper, auth routing, Start PR, hide-whitespace."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from github_desktop.errors import APIError, GitError
from github_desktop.git.ops import push
from github_desktop.git.runner import GitResult, env_for_remote
from github_desktop.github.api import GitHubAPI, emit_token_invalidated, on_token_invalidated
from github_desktop.models import Account, AheadBehind, GitHubRepository, PopupType
from github_desktop.store import AppStore
from tests.conftest import run_git


def test_push_set_upstream_and_force_with_lease_are_exclusive(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_git(args, repo, **kwargs):
        seen.append(list(args))
        return GitResult(stdout="", stderr="", exit_code=0, args=list(args))

    monkeypatch.setattr("github_desktop.git.ops.git", fake_git)
    push("/tmp", "origin", "main", None, set_upstream=True, force_with_lease=True)
    assert "--set-upstream" in seen[0]
    assert "--force-with-lease" not in seen[0]
    seen.clear()
    push("/tmp", "origin", "main", "main", force_with_lease=True)
    assert "--force-with-lease" in seen[0]
    assert "--set-upstream" not in seen[0]
    seen.clear()
    push("/tmp", "origin", "main", "main", set_upstream=True, force_with_lease=True)
    assert "--force-with-lease" in seen[0]
    assert "--set-upstream" not in seen[0]


def test_env_for_remote_gcm_interactive() -> None:
    never = env_for_remote("https://github.com/a/b.git", token="t")
    assert never["GCM_INTERACTIVE"] == "Never"
    assert "GitHub Desktop/" in never["GIT_USER_AGENT"]
    assert never["GIT_USER_AGENT"].startswith("git/")
    auto = env_for_remote(
        "https://github.com/a/b.git", token="t", use_external_credential_helper=True
    )
    assert auto["GCM_INTERACTIVE"] == "Auto"


def test_env_for_repo_passes_external_credential_helper(isolated_config, git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://gitlab.com/acme/app.git")
    store = AppStore()
    store.settings.use_external_credential_helper = True
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    env = store.env_for_repo(repo)
    assert env is not None
    assert env["GCM_INTERACTIVE"] == "Auto"
    store.settings.use_external_credential_helper = False
    env = store.env_for_repo(repo)
    assert env is not None
    assert env["GCM_INTERACTIVE"] == "Never"


def test_api_401_emits_token_invalidated(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    on_token_invalidated(lambda endpoint, token: seen.append((endpoint, token)))
    headers = Message()
    headers["X-GitHub-Request-Id"] = "req-1"

    def fake_urlopen(*_a, **_k):
        raise HTTPError(
            "https://api.github.com/user",
            401,
            "Unauthorized",
            headers,
            BytesIO(b'{"message":"Bad credentials"}'),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    api = GitHubAPI("https://api.github.com", "dead-token")
    with pytest.raises(APIError) as err:
        api.get("/user")
    assert err.value.status == 401
    assert seen == [("https://api.github.com", "dead-token")]


def test_api_401_with_otp_does_not_emit(monkeypatch) -> None:
    seen: list[tuple[str, str]] = []
    on_token_invalidated(lambda endpoint, token: seen.append((endpoint, token)))
    headers = Message()
    headers["X-GitHub-Request-Id"] = "req-1"
    headers["X-GitHub-OTP"] = "required"

    def fake_urlopen(*_a, **_k):
        raise HTTPError(
            "https://api.github.com/user",
            401,
            "Unauthorized",
            headers,
            BytesIO(b"otp"),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(APIError):
        GitHubAPI("https://api.github.com", "tok").get("/user")
    assert seen == []


def test_token_invalidated_signs_out_and_shows_popup(isolated_config) -> None:
    store = AppStore()
    account = Account(login="octocat", endpoint="https://api.github.com", token="tok")
    store.accounts = [account]
    emit_token_invalidated("https://api.github.com", "tok")
    assert store.accounts == []
    assert store.popup is not None
    assert store.popup.type == PopupType.INVALIDATED_TOKEN


def test_token_mismatch_does_not_sign_out(isolated_config) -> None:
    store = AppStore()
    account = Account(login="octocat", endpoint="https://api.github.com", token="current")
    store.accounts = [account]
    store._on_token_invalidated("https://api.github.com", "stale")
    assert store.accounts == [account]
    assert store.popup is None


def test_token_invalidated_matches_account_by_token(isolated_config) -> None:
    store = AppStore()
    first = Account(login="one", endpoint="https://api.github.com", token="aaa")
    second = Account(login="two", endpoint="https://api.github.com", token="bbb")
    store.accounts = [first, second]
    store._on_token_invalidated("https://api.github.com", "bbb")
    assert [a.login for a in store.accounts] == ["one"]
    assert store.popup is not None
    assert store.popup.type == PopupType.INVALIDATED_TOKEN


def test_stash_overwrite_prompts_before_dropping(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.git.ops import get_status
    from github_desktop.models import Branch, BranchType, StashEntry

    store = AppStore()
    store.settings.uncommitted_changes_strategy = "StashOnCurrentBranch"
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    (git_repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    status = get_status(str(git_repo))
    state = store.state_for(repo)
    state.status = status
    state.stashes = [
        StashEntry(
            name="stash@{0}",
            stash_sha="abc",
            branch_name=status.current_branch or "main",
            tree="t",
            parents=[],
        )
    ]

    def boom(*_a, **_k):
        raise AssertionError("live git stash list on GTK thread")

    monkeypatch.setattr("github_desktop.store.get_last_desktop_stash_entry_for_branch", boom)
    store.checkout(repo, Branch("topic", None, "deadbeef", BranchType.LOCAL))
    assert store.popup is not None
    assert store.popup.type == PopupType.CONFIRM_OVERWRITE_STASH


def test_protected_branch_checkout_brings_changes(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.git.ops import get_status
    from github_desktop.models import Branch, BranchType

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    (git_repo / "dirty.txt").write_text("x\n", encoding="utf-8")
    state = store.state_for(repo)
    state.status = get_status(str(git_repo))
    state.current_branch_protected = True
    called: list[str] = []
    monkeypatch.setattr(store, "checkout_and_bring_changes", lambda r, b: called.append(b.name))
    store.checkout(repo, Branch("topic", None, "deadbeef", BranchType.LOCAL))
    assert called == ["topic"]
    assert store.popup is None


def test_begin_sign_in_for_endpoint_skips_empty_ghe_prompt(isolated_config) -> None:
    store = AppStore()
    store.begin_sign_in_for_endpoint("https://github.example.com/api/v3")
    assert store.sign_in_endpoint == "https://github.example.com/api/v3"
    assert store.popup is not None
    assert store.popup.type == PopupType.SIGN_IN
    assert store.popup.payload.get("enterprise") is True


def test_pr_base_branches_filters_to_contribution_remote() -> None:
    from github_desktop.models import Branch, BranchType, pr_base_branches

    origin_local = Branch("main", "origin/main", "a", BranchType.LOCAL, remote=None)
    origin_remote = Branch("origin/topic", "origin/topic", "b", BranchType.REMOTE, remote="origin")
    local_only = Branch("wip", None, "c", BranchType.LOCAL)
    names = pr_base_branches([origin_local, origin_remote, local_only], remote="origin", current="feature")
    assert "main" in names
    assert "topic" in names
    assert "wip" not in names


def test_github_auth_failure_without_account_opens_sign_in(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store._handle_remote_error(
        repo, GitError("auth", git_error="HTTPSAuthenticationFailed", stderr="Authentication failed")
    )
    assert store.popup is not None
    assert store.popup.type == PopupType.SIGN_IN


def test_github_auth_failure_with_account_invalidates_token(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    account = Account(login="me", endpoint="https://api.github.com", token="tok")
    store.accounts = [account]
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store._handle_remote_error(
        repo, GitError("auth", git_error="HTTPSAuthenticationFailed", stderr="Authentication failed")
    )
    assert store.accounts == []
    assert store.popup is not None
    assert store.popup.type == PopupType.INVALIDATED_TOKEN


def test_generic_auth_failure_opens_generic_dialog(isolated_config, git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://gitlab.com/acme/app.git")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store._handle_remote_error(
        repo, GitError("auth", git_error="HTTPSAuthenticationFailed", stderr="Authentication failed")
    )
    assert store.popup is not None
    assert store.popup.type == PopupType.GENERIC_GIT_AUTHENTICATION


def test_create_pr_from_preview_opens_browser_with_base(isolated_config, git_repo: Path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("github_desktop.store.open_external", lambda url: opened.append(url))
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = AheadBehind(ahead=0, behind=0)
    store.create_pull_request_from_preview(repo, "develop")
    assert any("/pull/new/" in url and "develop" in url for url in opened)


def test_hide_whitespace_settings_are_split(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.set_hide_whitespace_in_changes_diff(repo, True)
    store.set_hide_whitespace_in_history_diff(repo, True)
    store.set_hide_whitespace_in_pull_request_diff(repo, True)
    assert store.settings.hide_whitespace_in_diffs is True
    assert store.settings.hide_whitespace_in_history_diff is True
    assert store.settings.hide_whitespace_in_pull_request_diff is True
    assert store._hide_ws_changes(store.state_for(repo)) is True
    assert store._hide_ws_history() is True
    assert store._hide_ws_pr() is True
    store.set_hide_whitespace_in_history_diff(repo, False)
    assert store._hide_ws_history() is False
    assert store._hide_ws_changes(store.state_for(repo)) is True


def test_set_commit_author_email_uses_local_when_present(isolated_config, git_repo: Path) -> None:
    from github_desktop.git.ops import get_config_value

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.set_commit_author_email(repo, "local-new@example.com")
    assert get_config_value(str(git_repo), "user.email", local_only=True) == "local-new@example.com"


def test_set_commit_author_email_writes_global_without_local(
    isolated_config, git_repo: Path, tmp_path: Path, monkeypatch
) -> None:
    from github_desktop.git.ops import get_config_value

    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "global.gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    run_git(git_repo, "config", "--local", "--unset-all", "user.email")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.set_commit_author_email(repo, "global-new@example.com")
    assert get_config_value(str(git_repo), "user.email", local_only=True) is None
    assert get_config_value(None, "user.email", global_only=True) == "global-new@example.com"
