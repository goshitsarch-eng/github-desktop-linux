"""LFS initialize hooks, squash-merge abort, clone info, commit busy, tutorial README."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import APIError
from github_desktop.git.ops import abort_squash_merge, get_status, is_squash_msg_set, merge
from github_desktop.github.api import GitHubAPI
from github_desktop.models import (
    Account,
    AppFileStatusKind,
    GitHubRepository,
    MergeResult,
    MultiCommitOperationKind,
    PopupType,
    RebaseInternalState,
)
from github_desktop.store import AppStore, TUTORIAL_README
from tests.conftest import run_git


def test_merge_squash_commits_and_conflict(git_repo: Path) -> None:
    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "topic.txt").write_text("topic\n", encoding="utf-8")
    run_git(git_repo, "add", "topic.txt")
    run_git(git_repo, "commit", "-m", "topic")
    run_git(git_repo, "checkout", "main")
    before = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert merge(str(git_repo), "topic", squash=True) == MergeResult.SUCCESS
    after = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert after != before
    assert (git_repo / "topic.txt").read_text(encoding="utf-8") == "topic\n"
    assert not is_squash_msg_set(str(git_repo))

    run_git(git_repo, "checkout", "-b", "left")
    (git_repo / "README.md").write_text("left\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "left")
    run_git(git_repo, "checkout", "-b", "right", "main")
    (git_repo / "README.md").write_text("right\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "right")
    result = merge(str(git_repo), "left", squash=True)
    assert result == MergeResult.FAILED
    assert is_squash_msg_set(str(git_repo))
    status = get_status(str(git_repo))
    assert status and status.squash_msg_found
    assert any(f.status.kind == AppFileStatusKind.CONFLICTED for f in status.working_directory.files)
    tip = status.current_tip
    abort_squash_merge(str(git_repo))
    assert not is_squash_msg_set(str(git_repo))
    assert run_git(git_repo, "rev-parse", "HEAD").stdout.strip() == tip


def test_abort_conflict_uses_squash_merge_backend(isolated_config, git_repo: Path, monkeypatch) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = get_status(str(git_repo))
    assert store._conflict_backend(repo, MultiCommitOperationKind.MERGE) == "merge"
    store.state_for(repo).status.squash_msg_found = True
    store.state_for(repo).status.merge_head_found = False
    assert store._conflict_backend(repo, MultiCommitOperationKind.SQUASH) == "squash-merge"
    called: list[str] = []
    monkeypatch.setattr("github_desktop.store.abort_squash_merge", lambda path: called.append(path))
    monkeypatch.setattr(store, "refresh_repository", lambda *_: None)
    store.abort_conflict_operation(repo, MultiCommitOperationKind.SQUASH)
    assert called == [str(git_repo)]


def test_history_squash_conflicts_use_rebase_backend(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    status = get_status(str(git_repo))
    assert status is not None
    status.rebase_internal_state = RebaseInternalState("topic", "aaa", "bbb")
    status.squash_msg_found = False
    store.state_for(repo).status = status
    assert store._conflict_backend(repo, MultiCommitOperationKind.SQUASH) == "rebase"


def test_install_lfs_hooks_force(isolated_config, git_repo: Path, monkeypatch) -> None:
    seen: list[tuple[str, bool]] = []

    def fake_install(path: str, force: bool = False) -> None:
        seen.append((path, force))

    monkeypatch.setattr("github_desktop.store.git_install_lfs_hooks", fake_install)
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.install_lfs_hooks(repositories=[repo])
    assert seen == [(str(git_repo), True)]


def test_add_repositories_shows_initialize_lfs(isolated_config, git_repo: Path, monkeypatch) -> None:
    monkeypatch.setattr("github_desktop.store.is_using_lfs", lambda path: True)
    store = AppStore()
    store.add_repositories([str(git_repo)])
    assert store.popup is not None
    assert store.popup.type == PopupType.INITIALIZE_LFS
    repos = store.popup.payload.get("repositories") or []
    assert repos and repos[0].path == str(git_repo)


def test_oversized_skips_lfs_tracked_files(isolated_config, git_repo: Path, monkeypatch) -> None:
    (git_repo / "movie.mp4").write_bytes(b"x" * 10)
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = get_status(str(git_repo))
    monkeypatch.setattr("github_desktop.store.OVERSIZED_FILE_BYTES", 1)
    monkeypatch.setattr("github_desktop.store.files_not_tracked_by_lfs", lambda path, files: [])
    store._commit_now(repo, "add movie")
    assert store.popup is None or store.popup.type != PopupType.OVERSIZED_FILES


def test_commit_sets_is_committing(isolated_config, git_repo: Path, monkeypatch) -> None:
    (git_repo / "a.txt").write_text("a\n", encoding="utf-8")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).status = get_status(str(git_repo))
    flags: list[bool] = []
    import github_desktop.store as store_module

    real = store_module.create_commit

    def fake_create(*args, **kwargs):
        flags.append(store.state_for(repo).is_committing)
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module, "create_commit", fake_create)
    monkeypatch.setattr(store, "refresh_repository", lambda *_: None)
    store._commit_now(repo, "add a")
    assert flags == [True]
    assert store.state_for(repo).is_committing is False


def test_generate_commit_message_busy_flag(isolated_config, git_repo: Path, monkeypatch) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.accounts = [
        Account(
            login="octocat",
            endpoint="https://api.github.com",
            token="t",
            is_copilot_desktop_enabled=True,
            features=["desktop_copilot_generate_commit_message"],
        )
    ]
    monkeypatch.setattr(store, "account_for_repo", lambda *_: store.accounts[0])
    store.state_for(repo).commit_to_amend = type("Commit", (), {"sha": "abc123"})()
    monkeypatch.setattr("github_desktop.store.get_files_diff_text", lambda *_a, **_k: "diff")
    monkeypatch.setattr(
        GitHubAPI,
        "generate_commit_message",
        lambda self, diff, files: ("summary", "body"),
    )
    seen: list[bool] = []

    def fake_run(work, done) -> None:
        seen.append(store.state_for(repo).is_generating_commit_message)
        done(None, work())

    monkeypatch.setattr(store, "_run", fake_run)
    store.generate_commit_message(repo)
    assert seen == [True]
    state = store.state_for(repo)
    assert state.is_generating_commit_message is False
    assert state.commit_message.summary == "summary"
    assert state.commit_message.generated_by_copilot is True


def test_generate_commit_message_requires_entitlement(isolated_config, git_repo: Path, monkeypatch) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.accounts = [Account(login="octocat", endpoint="https://api.github.com", token="t")]
    monkeypatch.setattr(store, "account_for_repo", lambda *_: store.accounts[0])
    called = []
    monkeypatch.setattr(store, "_run", lambda work, done: called.append(True))
    store.generate_commit_message(repo)
    assert called == []
    assert store.state_for(repo).is_generating_commit_message is False


def test_fetch_repository_clone_info_protocol_and_404(monkeypatch) -> None:
    api = GitHubAPI("https://api.github.com", "token")

    def fake_get(self, path, **kwargs):
        assert kwargs.get("extra_headers", {}).get("Cache-Control") == "no-cache"
        return {
            "clone_url": "https://github.com/new/name.git",
            "ssh_url": "git@github.com:new/name.git",
            "default_branch": "main",
        }

    monkeypatch.setattr(GitHubAPI, "get", fake_get)
    https = api.fetch_repository_clone_info("old", "name", "https")
    assert https == {"url": "https://github.com/new/name.git", "default_branch": "main"}
    ssh = api.fetch_repository_clone_info("old", "name", "ssh")
    assert ssh == {"url": "git@github.com:new/name.git", "default_branch": "main"}

    def missing(self, path, **kwargs):
        raise APIError("missing", status=404)

    monkeypatch.setattr(GitHubAPI, "get", missing)
    assert api.fetch_repository_clone_info("no", "repo") is None


def test_clone_resolves_renamed_url(isolated_config, tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "cloned"
    store = AppStore()
    store.accounts = [Account(login="octocat", endpoint="https://api.github.com", token="t")]
    seen: list[str] = []

    def fake_info(self, owner, name, protocol=None):
        return {"url": "https://github.com/acme/renamed.git", "default_branch": "main"}

    def fake_clone(url, path, **kwargs):
        seen.append(url)

    monkeypatch.setattr(GitHubAPI, "fetch_repository_clone_info", fake_info)
    monkeypatch.setattr("github_desktop.store.clone_repository", fake_clone)
    monkeypatch.setattr(store, "_run", lambda work, done: (work(), done(None)))
    monkeypatch.setattr(store, "add_repositories", lambda paths, **_kwargs: [])
    store.clone("https://github.com/acme/old.git", str(dest))
    assert seen == ["https://github.com/acme/renamed.git"]


def test_create_tutorial_repository_writes_readme(isolated_config, tmp_path: Path, monkeypatch) -> None:
    dest = tmp_path / "desktop-tutorial"
    store = AppStore()
    account = Account(login="octocat", endpoint="https://api.github.com", token="t")
    created = GitHubRepository(
        name="desktop-tutorial",
        owner="octocat",
        html_url="https://github.com/octocat/desktop-tutorial",
        clone_url="https://github.com/octocat/desktop-tutorial.git",
        default_branch="main",
    )
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test User")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    monkeypatch.setattr(GitHubAPI, "create_repository", lambda self, *a, **k: created)
    pushed: list[str] = []
    monkeypatch.setattr("github_desktop.store.push", lambda *a, **k: pushed.append("ok"))
    monkeypatch.setattr(store, "_run", lambda work, done: (work(), done(None)))
    store.create_tutorial_repository(account, str(dest))
    assert dest.is_dir()
    readme = (dest / "README.md").read_text(encoding="utf-8")
    assert "Welcome to GitHub Desktop!" in readme
    assert "Write your name on line 6" in readme
    assert readme == TUTORIAL_README
    assert pushed == ["ok"]
    assert any(repo.tutorial for repo in store.repositories)


def test_tutorial_readme_constant() -> None:
    assert TUTORIAL_README.startswith("# Welcome to GitHub Desktop!")
    lines = TUTORIAL_README.splitlines()
    assert "Write your name on line 6" in lines[4]
