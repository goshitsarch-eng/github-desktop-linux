"""Remaining Desktop-parity helpers: forks, SAML, oversized, protocol, banners."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import overwritten_files_from_error, parse_saml_organization
from github_desktop.git.ops import ensure_upstream_remote, get_remotes
from github_desktop.models import (
    Banner,
    BannerType,
    ForkContributionTarget,
    GitHubRepository,
    PopupType,
    Repository,
    fork_contribution_target,
    github_for_contribution,
    github_from_dict,
    github_to_dict,
)
from github_desktop.protocol import OpenRepositoryAction, parse_app_url
from github_desktop.remote_parsing import parse_remote, sanitize_remote_url
from github_desktop.store import AppStore
from tests.conftest import run_git


SAMPLE_SAML = """
remote: The `acme-org' organization has enabled or enforced SAML SSO.
remote: To access this repository, you must re-authorize the OAuth Application.
fatal: Could not read from remote repository.
"""

SAMPLE_OVERWRITE = """
error: Your local changes to the following files would be overwritten by checkout:
	src/app.ts
	README.md
Please commit your changes or stash them before you switch branches.
Aborting
"""


def test_parse_saml_organization() -> None:
    assert parse_saml_organization(SAMPLE_SAML) == "acme-org"
    assert parse_saml_organization("unrelated") is None


def test_overwritten_files_from_error() -> None:
    assert overwritten_files_from_error(SAMPLE_OVERWRITE) == ["src/app.ts", "README.md"]


def test_github_dict_roundtrip_includes_parent() -> None:
    parent = GitHubRepository("upstream", "acme", "https://github.com/acme/upstream", "https://github.com/acme/upstream.git")
    fork = GitHubRepository(
        "upstream",
        "me",
        "https://github.com/me/upstream",
        "https://github.com/me/upstream.git",
        fork=True,
        parent=parent,
    )
    restored = github_from_dict(github_to_dict(fork))
    assert restored is not None
    assert restored.fork
    assert restored.parent is not None
    assert restored.parent.owner == "acme"


def test_fork_contribution_target_parent_by_default() -> None:
    parent = GitHubRepository("app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git")
    fork = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git", fork=True, parent=parent)
    repo = Repository(1, "/tmp/app", "app", github=fork)
    assert fork_contribution_target(repo) == ForkContributionTarget.PARENT
    assert github_for_contribution(repo) is parent
    repo.workflow_preferences["fork_target"] = ForkContributionTarget.SELF.value
    assert github_for_contribution(repo) is fork


def test_ensure_upstream_remote_adds_and_detects_mismatch(git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://github.com/me/app.git")
    action, remote = ensure_upstream_remote(git_repo.as_posix(), "https://github.com/acme/app.git")
    assert action == "added"
    assert remote is not None
    assert remote.name == "upstream"
    names = {r.name for r in get_remotes(git_repo.as_posix())}
    assert "upstream" in names
    action, existing = ensure_upstream_remote(git_repo.as_posix(), "https://github.com/other/app.git")
    assert action == "mismatch"
    assert existing is not None


def test_open_pull_request_gates_unpublished_branch(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = None
    store.open_pull_request(repo)
    assert store.popup is not None
    assert store.popup.type == PopupType.PUSH_BRANCH_COMMITS
    assert store.popup.payload.get("unpublished") is True


def test_sanitize_remote_url_strips_userinfo() -> None:
    assert (
        sanitize_remote_url("https://x-access-token:secret@github.com/acme/app.git")
        == "https://github.com/acme/app.git"
    )
    assert sanitize_remote_url("https://github.com/acme/app.git") == "https://github.com/acme/app.git"


def test_protocol_openrepo_keeps_pr_and_filepath() -> None:
    action = parse_app_url(
        "x-github-client://openRepo/https://github.com/desktop/desktop?pr=42&filepath=README.md"
    )
    assert isinstance(action, OpenRepositoryAction)
    assert action.pr == "42"
    assert action.filepath == "README.md"


def test_banner_undo_sha_roundtrip() -> None:
    banner = Banner(BannerType.SUCCESSFUL_MERGE, their_branch="main", undo_sha="abc123")
    assert banner.undo_sha == "abc123"


def test_convert_repository_to_fork_rewires_remotes(isolated_config, git_repo: Path) -> None:
    run_git(git_repo, "remote", "add", "origin", "https://github.com/acme/app.git")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    parent = GitHubRepository("app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git")
    repo.github = parent
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=parent,
    )
    store.convert_repository_to_fork(repo, fork)
    remotes = {r.name: r.url for r in get_remotes(str(git_repo))}
    from github_desktop.remote_parsing import parse_remote

    origin = parse_remote(remotes["origin"])
    upstream = parse_remote(remotes["upstream"])
    assert origin is not None and origin.owner == "me" and origin.name == "app"
    assert upstream is not None and upstream.owner == "acme" and upstream.name == "app"
    assert repo.github is fork
    assert store.popup is not None
    assert store.popup.type == PopupType.CHOOSE_FORK_SETTINGS


def test_force_push_recommended_after_rewrite(isolated_config, git_repo: Path) -> None:
    from github_desktop.git.ops import get_status
    from github_desktop.models import AheadBehind, ForcePushBranchState
    from github_desktop.store import AppStore

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    status = get_status(str(git_repo))
    state = store.state_for(repo)
    state.status = status
    state.ahead_behind = AheadBehind(ahead=2, behind=1)
    store.add_branch_to_force_push_list(repo, "not-the-current-tip")
    assert store.current_branch_force_push_state(repo) == ForcePushBranchState.RECOMMENDED
    store.drop_current_branch_from_force_push_list(repo)
    assert store.current_branch_force_push_state(repo) == ForcePushBranchState.AVAILABLE
    state.ahead_behind = AheadBehind(ahead=1, behind=0)
    assert store.current_branch_force_push_state(repo) == ForcePushBranchState.NOT_AVAILABLE


def test_default_branch_uses_contribution_target(isolated_config) -> None:
    store = AppStore()
    parent = GitHubRepository("app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git", default_branch="develop")
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=parent,
        default_branch="main",
    )
    repo = Repository(1, "/tmp/app", "app", github=fork)
    assert store.default_branch_name(repo) == "develop"
    repo.workflow_preferences["fork_target"] = ForkContributionTarget.SELF.value
    assert store.default_branch_name(repo) == "main"


def test_handle_cli_clone_seeds_default_directory(isolated_config) -> None:
    store = AppStore()
    store.settings.clone_default_directory = "/tmp/desktop-clones"
    store.handle_cli(["--cli-clone=https://github.com/desktop/desktop", "--cli-branch=dev"])
    assert store.popup and store.popup.type == PopupType.CLONE_REPOSITORY
    assert store.popup.payload.get("path") == "/tmp/desktop-clones/desktop"
    assert store.popup.payload.get("branch") == "dev"


def test_pause_and_resume_tutorial(isolated_config, git_repo: Path) -> None:
    from github_desktop.models import TutorialStep

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.tutorial = True
    store.tutorial_step = TutorialStep.CREATE_BRANCH
    store.pause_tutorial()
    assert store.tutorial_step == TutorialStep.PAUSED
    assert store.settings.tutorial_paused is True
    store.resume_tutorial()
    assert store.tutorial_step != TutorialStep.PAUSED
    assert store.settings.tutorial_paused is False


def test_attributable_email_matches_account_and_stealth() -> None:
    from github_desktop.email import is_attributable_email_for, lookup_preferred_email
    from github_desktop.models import Account

    account = Account(
        login="niik",
        endpoint="https://api.github.com",
        token="x",
        emails=["personal@gmail.com", "company@github.com", "niik@users.noreply.github.com"],
        id=123,
    )
    assert is_attributable_email_for(account, "personal@gmail.com")
    assert is_attributable_email_for(account, "123+niik@users.noreply.github.com")
    assert is_attributable_email_for(account, "niik@users.noreply.github.com")
    assert not is_attributable_email_for(account, "other@example.com")
    assert lookup_preferred_email(account).endswith("users.noreply.github.com")


def test_commit_drop_kind_squash_vs_reorder() -> None:
    from github_desktop.commit_dnd import commit_drop_kind, decode_commit_shas, encode_commit_shas

    assert commit_drop_kind(10, 100) == "reorder-before"
    assert commit_drop_kind(50, 100) == "squash"
    assert commit_drop_kind(90, 100) == "reorder-after"
    assert decode_commit_shas(encode_commit_shas(["aaa", "bbb"])) == ["aaa", "bbb"]


def test_emoji_catalog_covers_gemoji() -> None:
    from github_desktop.ui.emoji import EMOJI, matching_shortcodes

    assert len(EMOJI) >= 500
    assert "tada" in EMOJI
    assert ":tada:" in matching_shortcodes("tad")
    assert matching_shortcodes("") == []


def test_pull_honors_desktop_flags(git_repo: Path, monkeypatch) -> None:
    from github_desktop.git import ops as git_ops
    from github_desktop.git.runner import GitResult

    captured: list[list[str]] = []

    def fake_git(args, *a, **k):
        captured.append(list(args))
        return GitResult(stdout="", stderr="", exit_code=0, args=list(args))

    monkeypatch.setattr(git_ops, "git", fake_git)
    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: None)
    git_ops.pull(str(git_repo), "origin")
    args = captured[0]
    assert args[:3] == ["-c", "rebase.backend=merge", "pull"]
    assert "--ff" in args
    assert "--no-rebase" not in args
    assert "--recurse-submodules" in args
    captured.clear()
    monkeypatch.setattr(git_ops, "get_config_value", lambda repo, key: "true" if key == "pull.ff" else None)
    git_ops.pull(str(git_repo), "origin")
    assert "--ff" not in captured[0]
