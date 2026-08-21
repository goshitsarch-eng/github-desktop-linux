"""Remaining Desktop-parity helpers: forks, SAML, oversized, protocol, banners."""

from __future__ import annotations

from pathlib import Path

from github_desktop.errors import overwritten_files_from_error, parse_saml_organization
from github_desktop.git.ops import ensure_upstream_remote, get_remotes
from github_desktop.models import (
    AheadBehind,
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


def test_github_dict_roundtrip_includes_archived() -> None:
    repo = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        private=True,
        archived=True,
    )
    restored = github_from_dict(github_to_dict(repo))
    assert restored is not None
    assert restored.archived is True
    assert restored.private is True


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


def test_create_pull_request_opens_browser(isolated_config, git_repo: Path, monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr("github_desktop.store.open_external", lambda url: opened.append(url))
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = AheadBehind(ahead=0, behind=0)
    store.open_pull_request(repo)
    assert any("/pull/new/" in url for url in opened)
    assert store.popup is None


def test_preview_pull_request_stays_in_app(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = AheadBehind(ahead=0, behind=0)
    store.preview_pull_request(repo)
    assert store.popup is not None
    assert store.popup.type == PopupType.START_PULL_REQUEST


def test_push_branch_commits_payload_has_create_without_pushing(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).ahead_behind = AheadBehind(ahead=2, behind=0)
    store.open_pull_request(repo)
    assert store.popup is not None
    assert store.popup.type == PopupType.PUSH_BRANCH_COMMITS
    assert callable(store.popup.payload.get("on_skip"))


def test_retry_clone_action(isolated_config, monkeypatch) -> None:
    called: list[tuple] = []

    def fake_clone(self, url, path, branch=None, account=None, tutorial=False):
        called.append((url, path, branch, tutorial))

    monkeypatch.setattr(AppStore, "clone", fake_clone)
    store = AppStore()
    store._retry_action = {
        "kind": "clone",
        "url": "https://github.com/acme/app.git",
        "path": "/tmp/app",
        "branch": "dev",
        "tutorial": False,
    }
    store.retry_last_remote_action()
    assert called == [("https://github.com/acme/app.git", "/tmp/app", "dev", False)]


def test_ignore_path_escapes_gitignore_specials(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.ignore_path(repo, "[never]!gonna*give#you?_.up")
    text = (git_repo / ".gitignore").read_text(encoding="utf-8")
    assert "\\[never\\]\\!gonna\\*give\\#you\\?_.up" in text


def test_group_cloneable_repositories() -> None:
    from github_desktop.clone_groups import YOUR_REPOSITORIES, group_cloneable_repositories

    mine = GitHubRepository("mine", "octocat", "https://github.com/octocat/mine", "https://github.com/octocat/mine.git")
    org = GitHubRepository("lib", "acme", "https://github.com/acme/lib", "https://github.com/acme/lib.git")
    other = GitHubRepository("tools", "widgets", "https://github.com/widgets/tools", "https://github.com/widgets/tools.git")
    grouped = group_cloneable_repositories([org, mine, other], "octocat")
    assert [name for name, _items in grouped] == [YOUR_REPOSITORIES, "acme", "widgets"]
    assert grouped[0][1][0].name == "mine"


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


def test_default_branch_name_uses_refresh_cache(isolated_config, git_repo: Path, monkeypatch) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None

    def boom(*_a, **_k):
        raise AssertionError("default branch lookup must not spawn git")

    monkeypatch.setattr("github_desktop.store.get_remotes", boom)
    monkeypatch.setattr("github_desktop.store.get_remote_head", boom)
    monkeypatch.setattr("github_desktop.store.get_default_branch", boom)
    store.default_branch_name(repo)
    store.find_default_branch_for(repo)


def test_author_identity_uses_refresh_cache(isolated_config, git_repo: Path, monkeypatch) -> None:
    calls = {"n": 0}
    import github_desktop.store as store_module

    real = store_module.get_author_identity

    def wrapped(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(store_module, "get_author_identity", wrapped)
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    before = calls["n"]
    store.author_identity(repo)
    assert calls["n"] == before


def test_change_branches_tab_persists(isolated_config) -> None:
    from github_desktop.models import BranchesTab
    from github_desktop.settings import (
        branchDropdownWidthConfigKey,
        pushPullButtonWidthConfigKey,
        stashedFilesWidthConfigKey,
    )

    store = AppStore()
    store.change_branches_tab(BranchesTab.PULL_REQUESTS.value)
    assert store.selected_branches_tab == BranchesTab.PULL_REQUESTS.value
    assert store.settings.selected_branches_tab == BranchesTab.PULL_REQUESTS.value
    assert branchDropdownWidthConfigKey == "branch-dropdown-width"
    assert pushPullButtonWidthConfigKey == "push-pull-button-width"
    assert stashedFilesWidthConfigKey == "stashed-files-width"
    assert store.settings.branch_dropdown_width == 230
    assert store.settings.push_pull_button_width == 230
    assert store.settings.stashed_files_width == 250


def test_reset_sidebar_width_matches_desktop(isolated_config) -> None:
    from github_desktop.settings import (
        commitSummaryWidthConfigKey,
        defaultCommitSummaryWidth,
        defaultSidebarWidth,
        sidebarWidthConfigKey,
    )

    store = AppStore()
    assert sidebarWidthConfigKey == "sidebar-width"
    assert commitSummaryWidthConfigKey == "commit-summary-width"
    assert defaultSidebarWidth == 250
    assert defaultCommitSummaryWidth == 250
    assert store.settings.sidebar_width == 250
    assert store.settings.commit_summary_width == 250
    store.settings.sidebar_width = 400
    store.reset_sidebar_width()
    assert store.settings.sidebar_width == 250
    store.set_sidebar_width(400)
    assert store.settings.sidebar_width == 400
    store.set_sidebar_width(100)
    assert store.settings.sidebar_width == 220
    store.set_commit_summary_width(400)
    assert store.settings.commit_summary_width == 400
    store.set_commit_summary_width(50)
    assert store.settings.commit_summary_width == 100
    store.set_stashed_files_width(400)
    assert store.settings.stashed_files_width == 400
    store.set_stashed_files_width(50)
    assert store.settings.stashed_files_width == 100
    store.set_pull_request_file_list_width(400)
    assert store.settings.pull_request_file_list_width == 400
    store.set_pull_request_file_list_width(50)
    assert store.settings.pull_request_file_list_width == 100
    store.set_branch_dropdown_width(400)
    assert store.settings.branch_dropdown_width == 400
    store.set_branch_dropdown_width(100)
    assert store.settings.branch_dropdown_width == 160
    store.set_push_pull_button_width(400)
    assert store.settings.push_pull_button_width == 400
    store.set_push_pull_button_width(100)
    assert store.settings.push_pull_button_width == 160
    from github_desktop.feature_flag import enable_resizing_toolbar_buttons

    assert enable_resizing_toolbar_buttons() is True
    store.settings.commit_summary_width = 500
    store.reset_commit_summary_width()
    assert store.settings.commit_summary_width == 250
    store.settings.stashed_files_width = 400
    store.reset_stashed_files_width()
    assert store.settings.stashed_files_width == 250
    store.settings.pull_request_file_list_width = 400
    store.reset_pull_request_file_list_width()
    assert store.settings.pull_request_file_list_width == 250
    store.settings.branch_dropdown_width = 400
    store.reset_branch_dropdown_width()
    assert store.settings.branch_dropdown_width == 230
    store.settings.push_pull_button_width = 400
    store.reset_push_pull_button_width()
    assert store.settings.push_pull_button_width == 230


def test_update_resizable_constraints_matches_desktop(isolated_config) -> None:
    from github_desktop.clamp import clamp
    from github_desktop.models import TutorialStep
    from github_desktop.settings import defaultBranchDropdownWidth, defaultPushPullButtonWidth

    store = AppStore()
    store.tutorial_step = TutorialStep.NOT_APPLICABLE
    store.settings.sidebar_width = 250
    store.settings.branch_dropdown_width = 230
    store.settings.push_pull_button_width = 230
    store.update_resizable_constraints(1280)
    assert store.sidebar_constraints.min == 220
    assert store.sidebar_constraints.max == 1280 - (defaultBranchDropdownWidth + defaultPushPullButtonWidth)
    assert clamp(store.sidebar_constraints) == 250
    files_max = 1280 - 250 - 150
    assert store.commit_summary_constraints.max == files_max
    assert store.stashed_files_constraints.max == files_max
    assert store.branch_dropdown_constraints.min == defaultBranchDropdownWidth
    store.update_resizable_constraints(500)
    assert store.sidebar_constraints.max == 220
    assert clamp(store.sidebar_constraints) == 220
    store.tutorial_step = TutorialStep.PICK_EDITOR
    store.update_resizable_constraints(1280)
    assert store.sidebar_constraints.max == 1280 - 650
    store.update_pull_request_resizable_constraints()
    assert store.pull_request_file_list_constraints.min == 100
    assert store.pull_request_file_list_constraints.max == 850 - 20 - 150


def test_keyboard_resize_nudge_matches_desktop() -> None:
    from github_desktop.ui.menus import (
        DefaultMaxWidth,
        DefaultMinWidth,
        KEYBOARD_RESIZE_DELTA,
        nudge_resizable_width,
        resizable_limit,
        resize_percentage,
    )

    assert KEYBOARD_RESIZE_DELTA == 5
    assert DefaultMinWidth == 200
    assert DefaultMaxWidth == 350
    assert nudge_resizable_width(250, True, 220, 720) == 255
    assert nudge_resizable_width(250, False, 220, 720) == 245
    assert nudge_resizable_width(220, False, 220, 720) == 220
    assert nudge_resizable_width(720, True, 220, 720) == 720
    assert nudge_resizable_width(250, True, 220, 200) == 220
    assert resize_percentage(220, 220, 720) == 0
    assert resize_percentage(720, 220, 720) == 100
    assert resize_percentage(470, 220, 720) == 50
    assert resizable_limit(float("inf"), 350) == 350
    assert resizable_limit(float("-inf"), 220) == 220
    assert resizable_limit(680.0, 350) == 680


def test_change_clone_repositories_tab_persists(isolated_config) -> None:
    from github_desktop.models import CloneRepositoryTab
    from github_desktop.settings import defaultPullRequestFileListWidth, pullRequestFileListConfigKey

    store = AppStore()
    assert store.selected_clone_repository_tab == CloneRepositoryTab.DOTCOM.value
    assert CloneRepositoryTab.GENERIC is CloneRepositoryTab.URL
    store.change_clone_repositories_tab(CloneRepositoryTab.ENTERPRISE.value)
    assert store.selected_clone_repository_tab == CloneRepositoryTab.ENTERPRISE.value
    assert store.settings.selected_clone_repository_tab == CloneRepositoryTab.ENTERPRISE.value
    store.change_clone_repositories_tab("Generic")
    assert store.selected_clone_repository_tab == CloneRepositoryTab.URL.value
    assert pullRequestFileListConfigKey == "pull-request-files-width"
    assert defaultPullRequestFileListWidth == 250
    assert store.settings.pull_request_file_list_width == 250


def test_load_repositories_uses_persisted_missing(isolated_config, git_repo: Path, monkeypatch) -> None:
    import json
    from github_desktop.paths import repositories_path
    import github_desktop.store as store_module

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.is_missing = True
    repo.unsafe = True
    store._save_repositories()
    payload = json.loads(repositories_path().read_text(encoding="utf-8"))
    assert payload[0]["missing"] is True
    assert payload[0]["unsafe"] is True

    def boom(*_a, **_k):
        raise AssertionError("live getRepositoryType on GTK thread")

    monkeypatch.setattr(store_module, "get_repository_kind", boom)
    monkeypatch.setattr(AppStore, "_gtk_app_running", lambda self: True)
    monkeypatch.setattr(AppStore, "_run", lambda self, work, done: None)

    loaded = AppStore()
    assert loaded.repositories
    assert loaded.repositories[0].is_missing is True
    assert loaded.repositories[0].unsafe is True


def test_desktop_stash_for_branch_uses_refresh_cache(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.git.ops import get_status
    from github_desktop.models import StashEntry
    import github_desktop.store as store_module

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    status = get_status(str(git_repo))
    state = store.state_for(repo)
    state.status = status
    entry = StashEntry(
        name="stash@{0}",
        stash_sha="abc",
        branch_name=status.current_branch or "main",
        tree="t",
        parents=[],
    )
    state.stashes = [entry]

    def boom(*_a, **_k):
        raise AssertionError("live git stash list on GTK thread")

    monkeypatch.setattr(store_module, "get_last_desktop_stash_entry_for_branch", boom)
    monkeypatch.setattr(store_module, "get_stashes", boom)
    assert store.desktop_stash_for_branch(repo, status.current_branch) is entry
    assert store._has_existing_desktop_stash(repo) is True
    assert store.desktop_stash_for_branch(repo, "missing") is None


def test_handle_cli_clone_seeds_default_directory(isolated_config) -> None:
    store = AppStore()
    store.settings.clone_default_directory = "/tmp/desktop-clones"
    store.handle_cli(["--cli-clone=https://github.com/desktop/desktop", "--cli-branch=dev"])
    assert store.popup and store.popup.type == PopupType.CLONE_REPOSITORY
    assert store.popup.payload.get("path") == "/tmp/desktop-clones/desktop"
    assert store.popup.payload.get("branch") == "dev"
    assert store.selected_clone_repository_tab == "URL"


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
    assert encode_commit_shas(["aaa", "bbb"]) == "aaa,bbb"
    assert decode_commit_shas("aaa,bbb") == ["aaa", "bbb"]
    from github_desktop.commit_dnd import drop_kind_css_class

    assert drop_kind_css_class("squash") == "commit-drop-squash"
    assert drop_kind_css_class("reorder-before") == "commit-drop-before"


def test_push_pull_presentation_matches_desktop() -> None:
    from github_desktop.models import ForcePushBranchState
    from github_desktop.push_pull import describe_push_pull, format_last_fetched

    assert format_last_fetched(None) == "Never fetched"
    assert format_last_fetched(100.0, now=100.0) == "Last fetched just now"
    assert "minutes ago" in format_last_fetched(100.0, now=100.0 + 10 * 60)

    fetch = describe_push_pull(
        remote_name="origin",
        current_branch="main",
        current_tip="abc",
        has_upstream=True,
        ahead=0,
        behind=0,
        tag_count=0,
        force_push=ForcePushBranchState.NOT_AVAILABLE,
    )
    assert fetch.action == "fetch"
    assert fetch.menu_items == ()
    assert fetch.label == "Fetch origin"
    assert fetch.icon == "view-refresh-symbolic"

    pull = describe_push_pull(
        remote_name="origin",
        current_branch="main",
        current_tip="abc",
        has_upstream=True,
        ahead=2,
        behind=3,
        tag_count=0,
        force_push=ForcePushBranchState.AVAILABLE,
        pull_with_rebase=True,
    )
    assert pull.action == "pull"
    assert pull.label == "Pull 3 with rebase"
    assert pull.menu_items == ("fetch", "force-push")
    assert pull.icon == "go-down-symbolic"

    force = describe_push_pull(
        remote_name="origin",
        current_branch="main",
        current_tip="abc",
        has_upstream=True,
        ahead=1,
        behind=1,
        tag_count=0,
        force_push=ForcePushBranchState.RECOMMENDED,
    )
    assert force.action == "force-push"
    assert force.menu_items == ("fetch",)
    assert force.icon == "go-up-symbolic"

    publish = describe_push_pull(
        remote_name=None,
        current_branch="main",
        current_tip="abc",
        has_upstream=False,
        ahead=0,
        behind=0,
        tag_count=0,
        force_push=ForcePushBranchState.NOT_AVAILABLE,
    )
    assert publish.label == "Publish repository"
    assert publish.menu_items == ()
    assert publish.icon == "network-transmit-symbolic"


def test_last_fetched_and_merge_commit_preflight(git_repo: Path) -> None:
    from github_desktop.git.ops import do_merge_commits_exist_after_commit, get_last_fetched

    assert get_last_fetched(str(git_repo)) is None
    fetch_head = git_repo / ".git" / "FETCH_HEAD"
    fetch_head.write_text("deadbeef\t\tbranch 'main' of example\n", encoding="utf-8")
    assert get_last_fetched(str(git_repo)) is not None
    fetch_head.write_text("", encoding="utf-8")
    assert get_last_fetched(str(git_repo)) is None

    initial = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert do_merge_commits_exist_after_commit(str(git_repo), initial) is False
    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "t.txt").write_text("t\n", encoding="utf-8")
    run_git(git_repo, "add", "t.txt")
    run_git(git_repo, "commit", "-m", "topic")
    run_git(git_repo, "checkout", "main")
    run_git(git_repo, "merge", "--no-ff", "topic", "-m", "merge topic")
    assert do_merge_commits_exist_after_commit(str(git_repo), initial) is True
    merge_sha = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    assert do_merge_commits_exist_after_commit(str(git_repo), merge_sha) is False


def test_undo_last_commit_restores_message(isolated_config, git_repo: Path) -> None:
    from github_desktop.git.ops import get_commits, get_status

    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    (git_repo / "x.txt").write_text("x\n", encoding="utf-8")
    run_git(git_repo, "add", "x.txt")
    run_git(git_repo, "commit", "-m", "add x\n\nbody here")
    state = store.state_for(repo)
    state.status = get_status(str(git_repo))
    state.commits = get_commits(str(git_repo), limit=5)
    store.undo_last_commit(repo, show_confirmation=False)
    assert state.commit_message.summary == "add x"
    assert "body here" in (state.commit_message.description or "")


def test_squash_blocked_when_merge_commits_exist(isolated_config, git_repo: Path) -> None:
    from github_desktop.git.ops import get_commits
    from github_desktop.models import PopupType

    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "t.txt").write_text("t\n", encoding="utf-8")
    run_git(git_repo, "add", "t.txt")
    run_git(git_repo, "commit", "-m", "topic")
    run_git(git_repo, "checkout", "main")
    run_git(git_repo, "merge", "--no-ff", "topic", "-m", "merge topic")
    (git_repo / "after.txt").write_text("a\n", encoding="utf-8")
    run_git(git_repo, "add", "after.txt")
    run_git(git_repo, "commit", "-m", "after merge")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    commits = get_commits(str(git_repo), limit=10)
    onto = commits[1]
    store.squash_onto(repo, [commits[0]], onto, "squashed")
    assert store.popup is not None
    assert store.popup.type == PopupType.ERROR
    assert "Unable to squash" in str(store.popup.payload.get("error") or "")


def test_emoji_catalog_covers_gemoji() -> None:
    from github_desktop.ui.emoji import EMOJI, matching_shortcodes

    assert len(EMOJI) >= 500
    assert "tada" in EMOJI
    assert ":tada:" in matching_shortcodes("tad")
    assert matching_shortcodes("") == []
    assert matching_shortcodes(":")


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


def test_ctrl_z_is_text_undo_not_git_undo() -> None:
    from github_desktop.ui.window import MainWindow

    src = open(MainWindow.__init__.__code__.co_filename, encoding="utf-8").read()
    assert '"<Ctrl>z": "edit-undo"' in src
    assert '"<Ctrl>z": "undo-commit"' not in src
    assert "win.edit-undo" in src
    assert "Hide stashed changes" in src
    assert "View pull request on GitHub" in src


def test_should_background_fetch_respects_minimum_interval(isolated_config, git_repo: Path) -> None:
    import time

    from github_desktop.models import GitHubRepository
    from github_desktop.store import BACKGROUND_FETCH_MINIMUM_INTERVAL, AppStore

    assert BACKGROUND_FETCH_MINIMUM_INTERVAL == 30 * 60
    store = AppStore()
    assert store.should_background_fetch() is False
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).last_fetched = time.time()
    assert store.should_background_fetch(repo) is False
    store.state_for(repo).last_fetched = time.time() - BACKGROUND_FETCH_MINIMUM_INTERVAL - 1
    assert store.should_background_fetch(repo) is True
    store.progress_kind = "push"
    assert store.should_background_fetch(repo) is False


def test_should_background_fetch_uses_refresh_cache(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.models import GitHubRepository
    import github_desktop.store as store_module

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    store.state_for(repo).last_fetched = None

    def boom(*_a, **_k):
        raise AssertionError("live FETCH_HEAD on GTK thread")

    monkeypatch.setattr(store_module, "get_last_fetched", boom)
    assert store.should_background_fetch(repo) is True


def test_refresh_repo_indicators_counts_changes(isolated_config, git_repo: Path) -> None:
    from github_desktop.store import AppStore

    (git_repo / "indicator.txt").write_text("changed\n", encoding="utf-8")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.refresh_repo_indicators()
    assert store.state_for(repo).changed_files_count >= 1


def test_pull_request_suggested_next_action_defaults_to_preview(isolated_config) -> None:
    from github_desktop.models import PullRequestSuggestedNextAction
    from github_desktop.store import AppStore

    store = AppStore()
    assert store.settings.pull_request_suggested_next_action == PullRequestSuggestedNextAction.PREVIEW_PULL_REQUEST.value
    store.set_pull_request_suggested_next_action(PullRequestSuggestedNextAction.CREATE_PULL_REQUEST.value)
    assert store.settings.pull_request_suggested_next_action == PullRequestSuggestedNextAction.CREATE_PULL_REQUEST.value


def test_fetch_poll_interval_helper_exists() -> None:
    from github_desktop.github.api import GitHubAPI

    assert callable(GitHubAPI.get_fetch_poll_interval)


def test_add_repositories_uses_toplevel(isolated_config, git_repo: Path) -> None:
    import os

    nested = git_repo / "nested"
    nested.mkdir()
    store = AppStore()
    repos = store.add_repositories([str(nested)])
    assert repos
    assert os.path.abspath(repos[0].path) == os.path.abspath(str(git_repo))


def test_add_repositories_unsafe_is_missing(isolated_config, git_repo: Path, monkeypatch) -> None:
    import github_desktop.store as store_module

    store = AppStore()

    def fake_type(path: str) -> dict[str, str]:
        return {"kind": "unsafe", "path": path}

    monkeypatch.setattr(store_module, "get_repository_type", fake_type)
    repos = store.add_repositories([str(git_repo)])
    assert repos
    assert repos[0].is_missing is True
    assert repos[0].unsafe is True
    assert store.popup is None


def test_add_repositories_invalid_paths_message(isolated_config, git_repo: Path, monkeypatch) -> None:
    import github_desktop.store as store_module
    from github_desktop.models import PopupType

    store = AppStore()

    def fake_type(_path: str) -> dict[str, str]:
        return {"kind": "missing"}

    monkeypatch.setattr(store_module, "get_repository_type", fake_type)
    added = store.add_repositories([str(git_repo)])
    assert added == []
    assert store.popup is not None
    assert store.popup.type == PopupType.ERROR
    assert "isn't a Git repository." in str(store.popup.payload.get("error") or "")


def test_add_repositories_probes_off_thread(isolated_config, git_repo: Path, monkeypatch) -> None:
    import github_desktop.store as store_module

    store = AppStore()

    def boom(*_a, **_k):
        raise AssertionError("live getRepositoryType on GTK thread")

    monkeypatch.setattr(store_module, "get_repository_type", boom)
    monkeypatch.setattr(AppStore, "_gtk_app_running", lambda self: True)
    monkeypatch.setattr(AppStore, "_run", lambda self, work, done: None)

    added = store.add_repositories([str(git_repo)])
    assert added == []


def test_invalid_repo_paths_message_lists_paths() -> None:
    from github_desktop.store import AppStore, MaxInvalidFoldersToDisplay

    store = AppStore()
    single = store._invalid_repo_paths_message(["/tmp/one"])
    assert single == "/tmp/one isn't a Git repository."
    many = store._invalid_repo_paths_message(["/a", "/b", "/c", "/d"])
    assert "The following paths aren't Git repositories:" in many
    assert "- /a" in many
    assert "- /c" in many
    assert "/d" not in many
    assert "(and 1 more)" in many
    assert MaxInvalidFoldersToDisplay == 3


def test_load_repository_git_config_off_thread(isolated_config, git_repo: Path, monkeypatch) -> None:
    import github_desktop.store as store_module

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None

    def boom(*_a, **_k):
        raise AssertionError("live git config on GTK thread")

    monkeypatch.setattr(store_module, "get_config_value", boom)
    monkeypatch.setattr(store_module, "get_global_config_value", boom)
    monkeypatch.setattr(store_module, "read_gitignore", boom)
    monkeypatch.setattr(store_module, "get_remotes", boom)
    monkeypatch.setattr(AppStore, "_gtk_app_running", lambda self: True)
    monkeypatch.setattr(AppStore, "_run", lambda self, work, done: None)

    called = {"n": 0}

    def on_done(*_a, **_k) -> None:
        called["n"] += 1

    store.load_repository_git_config(repo, on_done)
    assert called["n"] == 0


def test_load_global_git_preferences_off_thread(isolated_config, monkeypatch) -> None:
    import github_desktop.store as store_module

    store = AppStore()

    def boom(*_a, **_k):
        raise AssertionError("live git config on GTK thread")

    monkeypatch.setattr(store_module, "get_global_config_value", boom)
    monkeypatch.setattr(store_module, "get_default_branch", boom)
    monkeypatch.setattr(AppStore, "_gtk_app_running", lambda self: True)
    monkeypatch.setattr(AppStore, "_run", lambda self, work, done: None)

    called = {"n": 0}

    def on_done(*_a, **_k) -> None:
        called["n"] += 1

    store.load_global_git_preferences(on_done)
    assert called["n"] == 0


def test_relocate_repository_skips_git_probe(isolated_config, git_repo: Path, tmp_path: Path) -> None:
    from tests.conftest import run_git

    other = tmp_path / "relocated"
    other.mkdir()
    run_git(other, "init")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    store.relocate_repository(repo, str(other))
    assert repo.path == str(other)
    assert repo.name == "relocated"
    assert not repo.is_missing


def test_handle_remote_error_auth_uses_cached_remotes(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.errors import GitError
    from github_desktop.models import PopupType, Remote
    import github_desktop.store as store_module

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).remotes = [Remote(name="origin", url="https://example.com/me/app.git")]

    def boom(*_a, **_k):
        raise AssertionError("live getRemotes on GTK thread")

    monkeypatch.setattr(store_module, "get_remotes", boom)
    store._handle_remote_error(repo, GitError("denied", stderr="authentication failed"))
    assert store.popup is not None
    assert store.popup.type == PopupType.GENERIC_GIT_AUTHENTICATION
    assert store.popup.payload.get("remote_url") == "https://example.com/me/app.git"


def test_load_repository_git_config_includes_remotes(isolated_config, git_repo: Path) -> None:
    from tests.conftest import run_git

    run_git(git_repo, "remote", "add", "origin", "https://github.com/me/app.git")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    captured: dict = {}

    def on_done(payload, *_exc) -> None:
        captured.update(payload)

    store.load_repository_git_config(repo, on_done)
    remotes = list(captured.get("remotes") or [])
    assert remotes
    assert remotes[0].name == "origin"


def test_show_foldout_matches_desktop(isolated_config, git_repo: Path, monkeypatch) -> None:
    from github_desktop.models import FoldoutType

    store = AppStore()
    store.add_repositories([str(git_repo)])
    called: list[bool] = []
    monkeypatch.setattr(store, "refresh_repo_indicators", lambda **_k: called.append(True))
    store.show_foldout(FoldoutType.REPOSITORY)
    assert store.foldout == FoldoutType.REPOSITORY
    assert called == [True]
    store.show_foldout(FoldoutType.REPOSITORY)
    assert called == [True]
    store.close_foldout(FoldoutType.BRANCH)
    assert store.foldout == FoldoutType.REPOSITORY
    store.close_foldout(FoldoutType.REPOSITORY)
    assert store.foldout is None
    store.show_foldout(FoldoutType.BRANCH)
    assert store.foldout == FoldoutType.BRANCH
    store.show_foldout(FoldoutType.PUSH_PULL)
    assert store.foldout == FoldoutType.PUSH_PULL
    store.close_current_foldout()
    assert store.foldout is None
    store.show_foldout(FoldoutType.REPOSITORY)
    repo = store.selected_repository
    assert repo is not None
    store.select_repository(repo.id)
    assert store.foldout is None
    store.settings.repository_indicators_enabled = False
    store.show_foldout(FoldoutType.REPOSITORY)
    assert called == [True, True]


def test_commit_message_focus_and_resizable_pane_active(isolated_config) -> None:
    store = AppStore()
    assert store.focus_commit_message is False
    assert store.resizable_pane_active is False
    store.set_commit_message_focus(True)
    assert store.focus_commit_message is True
    store.set_commit_message_focus(True)
    store.set_commit_message_focus(False)
    assert store.focus_commit_message is False
    store.app_focused_element_changed(True)
    assert store.resizable_pane_active is True
    store.app_focused_element_changed(True)
    store.app_focused_element_changed(False)
    assert store.resizable_pane_active is False


def test_initialize_compare_resets_history_mode(isolated_config, git_repo) -> None:
    from github_desktop.models import HistoryTabMode

    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    state = store.state_for(repo)
    state.history_mode = HistoryTabMode.COMPARE
    state.compare_filter_text = "topic"
    state.show_branch_list = True
    store.initialize_compare(repo, HistoryTabMode.HISTORY)
    store.update_compare_form(repo, filter_text="", show_branch_list=False)
    latest = store.state_for(repo)
    assert latest.history_mode == HistoryTabMode.HISTORY
    assert latest.compare_branch is None
    assert latest.compare_filter_text == ""
    assert latest.show_branch_list is False


def test_generate_branch_context_menu_items_matches_desktop() -> None:
    from github_desktop.ui.branches import generate_branch_context_menu_items

    renamed: list[str] = []
    deleted: list[str] = []
    viewed: list[bool] = []
    items = generate_branch_context_menu_items(
        "topic",
        is_local=True,
        on_rename=renamed.append,
        on_delete=deleted.append,
    )
    labels = [item[0] if item else None for item in items]
    assert labels == ["Rename…", "Copy branch name", None, "Delete…"]
    assert items[0][2] is True
    items[0][1]()
    items[-1][1]()
    assert renamed == ["topic"]
    assert deleted == ["topic"]
    remote_items = generate_branch_context_menu_items(
        "origin/topic",
        is_local=False,
        on_rename=renamed.append,
        on_delete=deleted.append,
        on_view_pull_request=lambda: viewed.append(True),
    )
    remote_labels = [item[0] if item else None for item in remote_items]
    assert remote_labels == [
        "Rename…",
        "Copy branch name",
        "View Pull Request on GitHub",
        None,
        "Delete…",
    ]
    assert remote_items[0][2] is False
    remote_items[2][1]()
    assert viewed == [True]


def test_show_pull_request_by_pr_opens_html_url(isolated_config, monkeypatch) -> None:
    from github_desktop.models import PullRequest

    opened: list[str] = []
    monkeypatch.setattr("github_desktop.store.open_external", lambda url: opened.append(url))
    store = AppStore()
    pr = PullRequest(
        number=42,
        title="Hi",
        body="",
        created_at="",
        author="octocat",
        draft=False,
        head_ref="topic",
        head_sha="abc",
        base_ref="main",
        html_url="https://github.com/octocat/hello/pull/42",
    )
    store.show_pull_request_by_pr(pr)
    assert opened == ["https://github.com/octocat/hello/pull/42"]


def test_set_repository_filter_text_matches_desktop(isolated_config) -> None:
    store = AppStore()
    assert store.repository_filter_text == ""
    store.set_repository_filter_text("desktop")
    assert store.repository_filter_text == "desktop"


def test_network_remote_uses_cached_remotes(isolated_config, git_repo: Path, monkeypatch) -> None:
    import github_desktop.store as store_module
    from github_desktop.models import Remote

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    store.state_for(repo).remotes = []

    def boom(*_a, **_k):
        raise AssertionError("live get_remotes on GTK thread")

    monkeypatch.setattr(store_module, "get_remotes", boom)
    assert store._network_remote(repo) is None
    origin = Remote(name="origin", url="https://github.com/me/app.git")
    assert store._network_remote(repo, [origin]) is origin
    store.state_for(repo).remotes = [origin]
    assert store.env_for_repo(repo) is not None


def test_get_git_description_is_file_only(git_repo: Path, monkeypatch) -> None:
    from github_desktop.git import ops as git_ops

    def boom(*_a, **_k):
        raise AssertionError("live git for getGitDescription")

    monkeypatch.setattr(git_ops, "git", boom)
    git_ops.write_git_description(str(git_repo), "Publish me")
    assert git_ops.get_git_description(str(git_repo)) == "Publish me"
    git_ops.write_git_description(str(git_repo), git_ops.DEFAULT_GIT_DESCRIPTION)
    assert git_ops.get_git_description(str(git_repo)) == ""


def test_load_git_description_matches_desktop(isolated_config, git_repo: Path) -> None:
    from github_desktop.git.ops import write_git_description

    write_git_description(str(git_repo), "A published app")
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    captured: list[str] = []
    store.load_git_description(repo, lambda text, *_exc: captured.append(text))
    assert captured == ["A published app"]


def _menu_file(path: str = "README.md"):
    from github_desktop.models import AppFileStatusKind, FileStatus, WorkingDirectoryFileChange

    return WorkingDirectoryFileChange(path, FileStatus(AppFileStatusKind.MODIFIED))


def _valid_status(*, branch: str = "main", tip: str = "abc123", upstream: str | None = None, files=None, rebase=False):
    from github_desktop.models import IStatusResult, RebaseInternalState, WorkingDirectoryStatus

    wd = WorkingDirectoryStatus.from_files(files or [])
    rebase_state = RebaseInternalState("topic", "base", "orig") if rebase else None
    return IStatusResult(
        current_branch=branch,
        current_upstream_branch=upstream,
        current_tip=tip,
        working_directory=wd,
        rebase_internal_state=rebase_state,
    )


def test_menu_update_popup_disables_all_menu_ids() -> None:
    from github_desktop.menu_update import MENU_ID_TO_ACTION, MenuSnapshot, allMenuIds, get_menu_state_from_snapshot

    enabled = get_menu_state_from_snapshot(MenuSnapshot(current_popup=True, repository_count=1))
    for menu_id in allMenuIds:
        action = MENU_ID_TO_ACTION.get(menu_id)
        if action is None:
            continue
        assert enabled[action] is False
    assert "increase-resizable" not in enabled
    assert "create-issue" not in enabled


def test_menu_update_welcome_and_no_repositories() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot

    welcome = get_menu_state_from_snapshot(MenuSnapshot(show_welcome_flow=True, repository_count=0))
    assert welcome["new-repository"] is False
    assert welcome["add-local-repository"] is False
    assert welcome["clone-repository"] is False
    assert welcome["preferences"] is False
    assert welcome["about"] is False
    assert welcome["choose-repository"] is False
    assert welcome["push"] is False

    empty = get_menu_state_from_snapshot(MenuSnapshot(repository_count=0))
    assert empty["new-repository"] is True
    assert empty["choose-repository"] is False
    assert empty["show-changes"] is False

    listed = get_menu_state_from_snapshot(MenuSnapshot(repository_count=1))
    assert listed["choose-repository"] is True


def test_menu_update_missing_repository_keeps_remove_and_github() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot
    from github_desktop.models import GitHubRepository, Repository, SelectionType

    repo = Repository(1, "/tmp/missing", "app", is_missing=True)
    missing = get_menu_state_from_snapshot(
        MenuSnapshot(selection_type=SelectionType.MISSING, repository=repo, repository_count=1)
    )
    assert missing["remove-repository"] is True
    assert missing["open-external-editor"] is False
    assert missing["view-on-github"] is False
    assert missing["push"] is False
    repo.github = GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git")
    hosted = get_menu_state_from_snapshot(
        MenuSnapshot(selection_type=SelectionType.MISSING, repository=repo, repository_count=1)
    )
    assert hosted["view-on-github"] is True
    assert hosted["remove-repository"] is True


def test_menu_update_valid_branch_unpublished_on_default() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot
    from github_desktop.models import Branch, BranchType, Repository, SelectionType

    repo = Repository(1, "/tmp/app", "app")
    default = Branch("main", None, "abc123", BranchType.LOCAL)
    enabled = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(files=[_menu_file()]),
            default_branch=default,
            tip_branch=default,
        )
    )
    assert enabled["show-changes"] is True
    assert enabled["push"] is True
    assert enabled["pull"] is False
    assert enabled["rename-branch"] is True
    assert enabled["delete-branch"] is False
    assert enabled["create-branch"] is True
    assert enabled["discard-all"] is True
    assert enabled["stash-all"] is True
    assert enabled["merge-branch"] is True
    assert enabled["open-pull-request"] is False
    assert enabled["view-on-github"] is False
    assert enabled["toggle-stash"] is False
    assert enabled["update-from-default"] is False


def test_menu_update_feature_branch_published_and_github() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot
    from github_desktop.models import Branch, BranchType, GitHubRepository, Repository, SelectionType, StashEntry

    repo = Repository(
        1,
        "/tmp/app",
        "app",
        github=GitHubRepository("app", "me", "https://github.com/me/app", "https://github.com/me/app.git"),
    )
    default = Branch("main", "origin/main", "aaa", BranchType.LOCAL)
    topic = Branch("topic", "origin/topic", "bbb", BranchType.LOCAL)
    stash = StashEntry("stash@{0}", "def", "topic", "tree", [])
    enabled = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(branch="topic", tip="bbb", upstream="origin/topic"),
            default_branch=default,
            contribution_target=default,
            tip_branch=topic,
            stash_entry=stash,
        )
    )
    assert enabled["delete-branch"] is True
    assert enabled["pull"] is True
    assert enabled["update-from-default"] is True
    assert enabled["view-on-github"] is True
    assert enabled["compare-on-github"] is True
    assert enabled["branch-on-github"] is True
    assert enabled["open-pull-request"] is True
    assert enabled["preview-pull-request"] is True
    assert enabled["create-issue"] is True
    assert enabled["toggle-stash"] is True
    on_default = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(upstream="origin/main"),
            default_branch=default,
            contribution_target=default,
            tip_branch=default,
        )
    )
    assert on_default["update-from-default"] is False
    assert on_default["delete-branch"] is False


def test_menu_update_detached_unborn_unknown_rebase_conflicts() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot
    from github_desktop.models import (
        AppFileStatusKind,
        Branch,
        BranchType,
        FileStatus,
        IStatusResult,
        Repository,
        SelectionType,
        WorkingDirectoryFileChange,
        WorkingDirectoryStatus,
    )

    repo = Repository(1, "/tmp/app", "app")
    topic = Branch("topic", None, "abc", BranchType.LOCAL)
    detached = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=IStatusResult(current_tip="abc123"),
        )
    )
    assert detached["push"] is False
    assert detached["delete-branch"] is False
    assert detached["rename-branch"] is False
    assert detached["compare-to-branch"] is False
    assert detached["create-branch"] is True
    assert detached["open-pull-request"] is False

    unborn = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=IStatusResult(current_branch="main"),
        )
    )
    assert unborn["create-branch"] is False
    assert unborn["push"] is False
    assert unborn["rename-branch"] is False

    unknown = get_menu_state_from_snapshot(
        MenuSnapshot(selection_type=SelectionType.REPOSITORY, repository=repo, repository_count=1)
    )
    assert unknown["create-branch"] is False

    conflicted = WorkingDirectoryFileChange("a.txt", FileStatus(AppFileStatusKind.CONFLICTED))
    rebase = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(files=[conflicted], rebase=True),
            rebase_in_progress=True,
            tip_branch=topic,
        )
    )
    assert rebase["create-branch"] is False
    assert rebase["discard-all"] is False
    assert rebase["stash-all"] is False

    merge_conflicts = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=IStatusResult(
                current_branch="topic",
                current_tip="abc",
                working_directory=WorkingDirectoryStatus.from_files([conflicted]),
                merge_head_found=True,
            ),
            tip_branch=topic,
        )
    )
    assert merge_conflicts["stash-all"] is False
    assert merge_conflicts["discard-all"] is True


def test_menu_update_archived_parent_disables_issues() -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state_from_snapshot, get_repo_issues_enabled
    from github_desktop.models import GitHubRepository, Repository, SelectionType

    parent = GitHubRepository(
        "app", "acme", "https://github.com/acme/app", "https://github.com/acme/app.git", archived=True
    )
    fork = GitHubRepository(
        "app",
        "me",
        "https://github.com/me/app",
        "https://github.com/me/app.git",
        fork=True,
        parent=parent,
    )
    repo = Repository(1, "/tmp/app", "app", github=fork)
    assert get_repo_issues_enabled(repo) is False
    enabled = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(),
        )
    )
    assert enabled["create-issue"] is False
    parent.archived = False
    parent.has_issues = False
    assert get_repo_issues_enabled(repo) is False
    parent.has_issues = True
    assert get_repo_issues_enabled(repo) is True


def test_menu_update_network_resizable_hidden_window_cloning(isolated_config, git_repo: Path) -> None:
    from github_desktop.menu_update import MenuSnapshot, get_menu_state, get_menu_state_from_snapshot
    from github_desktop.models import (
        CloningRepository,
        IStatusResult,
        PopupType,
        Repository,
        SelectionType,
        WelcomeStep,
        WorkingDirectoryStatus,
    )

    repo = Repository(1, str(git_repo), "repo")
    busy = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(upstream="origin/main"),
            is_push_pull_fetch_in_progress=True,
            resizable_pane_active=True,
        )
    )
    assert busy["push"] is False
    assert busy["pull"] is False
    assert busy["increase-resizable"] is True
    assert busy["decrease-resizable"] is True

    hidden = get_menu_state_from_snapshot(
        MenuSnapshot(
            window_open=False,
            selection_type=SelectionType.REPOSITORY,
            repository=repo,
            repository_count=1,
            status=_valid_status(),
        )
    )
    assert hidden["push"] is False
    assert hidden["show-changes"] is False

    cloning = get_menu_state_from_snapshot(
        MenuSnapshot(
            selection_type=SelectionType.CLONING,
            repository=CloningRepository(id=1, path="/tmp/c", url="https://github.com/me/app.git"),
            repository_count=1,
        )
    )
    assert cloning["push"] is False
    assert cloning["choose-repository"] is True

    store = AppStore()
    store.welcome_step = None
    store.add_repositories([str(git_repo)])
    selected = store.selected_repository
    assert selected is not None
    store.state_for(selected).status = IStatusResult(
        current_branch="main",
        current_tip="abc",
        working_directory=WorkingDirectoryStatus.from_files([_menu_file()]),
    )
    store.progress_kind = "push"
    enabled = get_menu_state(store)
    assert enabled["push"] is False
    store.progress_kind = None
    store.show_popup(PopupType.ABOUT)
    assert get_menu_state(store)["new-repository"] is False
    store.welcome_step = WelcomeStep.START
    store._popups.clear()
    assert get_menu_state(store)["preferences"] is False


