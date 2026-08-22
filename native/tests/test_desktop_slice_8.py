"""RetryAction, LCO, fork-on-push, publish tabs, cloning view, accessibility banner."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import GitError
from github_desktop.git.ops import get_commits, get_status
from github_desktop.models import (
    Account,
    AppFileStatusKind,
    BannerType,
    CloningRepository,
    FileStatus,
    GitHubRepository,
    PopupType,
    PublishTab,
    RebaseResult,
    RetryAction,
    RetryActionType,
    SelectionType,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
    accounts_for_publish_tab,
    default_publish_tab,
    retry_action_from_legacy,
    retry_action_name,
)
from github_desktop.store import AppStore
from tests.conftest import run_git


def _dirty_status(repo_path: Path):
    status = get_status(str(repo_path))
    assert status is not None
    status.working_directory = WorkingDirectoryStatus.from_files(
        [WorkingDirectoryFileChange("dirty.txt", FileStatus(AppFileStatusKind.MODIFIED))]
    )
    return status


def test_retry_action_name_and_legacy_clone() -> None:
    assert retry_action_name(RetryActionType.CHECKOUT) == "checkout"
    assert retry_action_name(RetryActionType.CREATE_BRANCH_FOR_CHERRY_PICK) == "cherry-pick"
    assert retry_action_name(RetryActionType.DISCARD_CHANGES) == "discard changes"
    assert retry_action_name("clone") == "clone"
    action = retry_action_from_legacy(
        {
            "kind": "clone",
            "url": "https://github.com/acme/app.git",
            "path": "/tmp/app",
            "branch": "dev",
            "tutorial": True,
        }
    )
    assert action.type == RetryActionType.CLONE
    assert action.url == "https://github.com/acme/app.git"
    assert action.path == "/tmp/app"
    assert action.branch == "dev"
    assert action.tutorial is True


def test_check_for_uncommitted_changes_shows_lco(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = _dirty_status(git_repo)
    retry = RetryAction(type=RetryActionType.SQUASH, repo_id=repo.id)
    assert store.check_for_uncommitted_changes(repo, retry) is True
    assert store.popup is not None
    assert store.popup.type == PopupType.LOCAL_CHANGES_OVERWRITTEN
    assert store.popup.payload["retry_kind"] == "squash"
    assert store.popup.payload["retry_action"] is retry


def test_squash_and_cherry_pick_skip_when_dirty(isolated_config, git_repo: Path, monkeypatch) -> None:
    (git_repo / "a.txt").write_text("a\n", encoding="utf-8")
    run_git(git_repo, "add", "a.txt")
    run_git(git_repo, "commit", "-m", "second")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = _dirty_status(git_repo)
    commits = get_commits(str(git_repo), limit=5)
    ran: list[str] = []
    monkeypatch.setattr(
        "github_desktop.store.squash_commits",
        lambda *a, **k: ran.append("squash") or RebaseResult.COMPLETED_WITHOUT_ERROR,
    )
    monkeypatch.setattr(store, "_run", lambda work, done: ran.append("cherry"))
    store.squash_onto(repo, [commits[0]], commits[1], "squashed")
    assert ran == []
    assert store.popup is not None and store.popup.type == PopupType.LOCAL_CHANGES_OVERWRITTEN
    store.close_popup()
    store.cherry_pick_commits(repo, [commits[0].sha], target_branch="other")
    assert ran == []
    assert store.popup is not None and store.popup.type == PopupType.LOCAL_CHANGES_OVERWRITTEN


def test_squash_conflicts_open_multi_commit_dialog(isolated_config, git_repo: Path, monkeypatch) -> None:
    (git_repo / "a.txt").write_text("a\n", encoding="utf-8")
    run_git(git_repo, "add", "a.txt")
    run_git(git_repo, "commit", "-m", "second")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = get_status(str(git_repo))
    commits = get_commits(str(git_repo), limit=5)
    monkeypatch.setattr(
        "github_desktop.store.squash_commits",
        lambda *a, **k: RebaseResult.CONFLICTS_ENCOUNTERED,
    )
    store.squash_onto(repo, [commits[0]], commits[1], "squashed")
    assert store.popup is not None
    assert store.popup.type == PopupType.MULTI_COMMIT_OPERATION
    assert store.popup.payload.get("step") == "conflicts"


def test_push_auth_without_write_permission_creates_fork(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository(
        "app",
        "acme",
        "https://github.com/acme/app",
        "https://github.com/acme/app.git",
        permissions="read",
    )
    store._retry_action = RetryAction(type=RetryActionType.PUSH, repo_id=repo.id)
    store._handle_remote_error(repo, GitError("denied", stderr="authentication failed"))
    assert store.popup is not None
    assert store.popup.type == PopupType.CREATE_FORK


def test_push_auth_with_write_permission_does_not_fork(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository(
        "app",
        "acme",
        "https://github.com/acme/app",
        "https://github.com/acme/app.git",
        permissions="write",
    )
    store._retry_action = RetryAction(type=RetryActionType.PUSH, repo_id=repo.id)
    store._handle_remote_error(repo, GitError("denied", stderr="authentication failed"))
    assert store.popup is None or store.popup.type != PopupType.CREATE_FORK


def test_perform_retry_accepts_legacy_clone_dict(isolated_config, monkeypatch) -> None:
    called: list[tuple] = []

    def fake_clone(self, url, path, branch=None, account=None, tutorial=False):
        called.append((url, path, branch, tutorial))

    monkeypatch.setattr(AppStore, "clone", fake_clone)
    store = AppStore()
    store.perform_retry(
        {
            "kind": "clone",
            "url": "https://github.com/acme/app.git",
            "path": "/tmp/app",
            "branch": "dev",
            "tutorial": False,
        }
    )
    assert called == [("https://github.com/acme/app.git", "/tmp/app", "dev", False)]


def test_clone_selects_cloning_repository_view(isolated_config, monkeypatch) -> None:
    monkeypatch.setattr(AppStore, "_run", lambda self, work, done: None)
    store = AppStore()
    store.clone("https://github.com/acme/app.git", "/tmp/app")
    cloning = store.selected_cloning
    assert cloning is not None
    assert cloning.name == "app"
    assert store.selected_state_type == SelectionType.CLONING
    store.abort_clone(cloning.id)
    assert store.selected_cloning is None
    assert store.cloning == []
    assert store.selected_state_type is None


def test_selected_state_type_none_without_repository(isolated_config) -> None:
    store = AppStore()
    store.welcome_step = None
    assert store.selected_repository is None
    assert store.selected_state_type is None


def test_cloning_repository_name() -> None:
    item = CloningRepository(id=-1, path="/tmp/desktop", url="https://github.com/desktop/desktop.git")
    assert item.name == "desktop"


def test_publish_tabs_split_dotcom_and_enterprise() -> None:
    dotcom = Account(login="octocat", endpoint="https://api.github.com", token="t")
    enterprise = Account(login="ada", endpoint="https://github.example.com/api/v3", token="t")
    assert accounts_for_publish_tab([dotcom, enterprise], PublishTab.DOTCOM) == [dotcom]
    assert accounts_for_publish_tab([dotcom, enterprise], PublishTab.ENTERPRISE) == [enterprise]
    assert default_publish_tab([enterprise]) == PublishTab.ENTERPRISE
    assert default_publish_tab([dotcom]) == PublishTab.DOTCOM
    assert enterprise.is_enterprise
    assert not dotcom.is_enterprise


def test_accessibility_banner_after_welcome(isolated_config) -> None:
    store = AppStore()
    assert store.banner is None
    store.finish_welcome()
    assert store.banner is not None
    assert store.banner.type == BannerType.ACCESSIBILITY_SETTINGS
    store.dismiss_accessibility_banner()
    assert store.banner is None
    assert store.settings.accessibility_banner_dismissed is True
    store._maybe_show_accessibility_banner()
    assert store.banner is None


def test_env_for_url_uses_generic_https_secrets(isolated_config) -> None:
    from github_desktop import secrets

    secrets.set_generic("example.com", "alice", "s3cret")
    store = AppStore()
    env = store.env_for_url("https://example.com/org/repo.git")
    assert env["GIT_CONFIG_KEY_0"] == "http.extraHeader"
    assert "AUTHORIZATION: basic " in env["GIT_CONFIG_VALUE_0"]


def test_clone_auth_without_account_starts_credential_helper_sign_in(isolated_config) -> None:
    store = AppStore()
    store._show_clone_error(
        GitError("denied", stderr="authentication failed"),
        "https://github.com/acme/app.git",
        "/tmp/app",
    )
    assert store.popup is not None
    assert store.popup.type == PopupType.SIGN_IN
    assert store.sign_in_credential_helper_url == "https://github.com/acme/app.git"
    assert store._retry_action is not None
    assert store._retry_action.type == RetryActionType.CLONE


def test_uncommitted_changes_strategy_labels() -> None:
    from github_desktop.models import uncommitted_changes_strategy_choices

    labels = [label for _kind, label in uncommitted_changes_strategy_choices()]
    assert "Ask me where I want the changes to go" in labels
    assert "Always bring my changes to my new branch" in labels
    assert "Always stash and leave my changes on the current branch" in labels


def test_create_fork_reports_progress_via_on_done(isolated_config, git_repo: Path, monkeypatch) -> None:
    import threading

    store = AppStore()
    store.accounts = [Account(login="me", endpoint="https://api.github.com", token="t")]
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository(
        "app",
        "acme",
        "https://github.com/acme/app",
        "https://github.com/acme/app.git",
        permissions="read",
    )
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=repo.github,
    )

    class FakeAPI:
        def fork_repository(self, owner: str, name: str):
            assert owner == "acme"
            assert name == "app"
            return fork

    monkeypatch.setattr("github_desktop.store.GitHubAPI.from_account", lambda _account: FakeAPI())
    seen: list[tuple] = []
    event = threading.Event()

    def on_done(exc, result) -> None:
        seen.append((exc, result))
        event.set()

    store.create_fork(repo, on_done=on_done)
    assert event.wait(timeout=5)
    assert seen[0][0] is None
    assert seen[0][1] is fork
    assert store.popup is None or store.popup.type != PopupType.CHOOSE_FORK_SETTINGS
    from github_desktop.models import uncommitted_changes_strategy_choices

    labels = [label for _kind, label in uncommitted_changes_strategy_choices()]
    assert "Ask me where I want the changes to go" in labels
    assert "Always bring my changes to my new branch" in labels
    assert "Always stash and leave my changes on the current branch" in labels
