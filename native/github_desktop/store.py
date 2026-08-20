"""Application store: repositories, accounts, git state, and actions."""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from . import secrets
from .editors import Editor, find_editor, get_available_editors, open_in_editor
from .errors import APIError, CopilotError, GitError, GitNotFoundError, NotARepositoryError, ValidationError
from .git import (
    abort_cherry_pick,
    abort_merge,
    abort_rebase,
    add_remote,
    append_ignore_rule,
    checkout_branch,
    checkout_commit,
    cherry_pick,
    clone_repository,
    co_author_trailers,
    continue_cherry_pick,
    continue_rebase,
    create_branch,
    create_commit,
    create_merge_commit,
    create_tag,
    delete_local_branch,
    delete_remote_branch,
    delete_tag,
    discard_paths,
    env_for_remote,
    fetch,
    format_commit_message,
    get_ahead_behind,
    get_all_tags,
    get_author_identity,
    get_branches,
    get_changed_files,
    get_commit,
    get_commit_diff,
    get_commits,
    get_config_value,
    get_default_branch,
    get_remotes,
    get_stashes,
    get_status,
    get_working_directory_diff,
    git_path_is_repository,
    init_repository,
    merge,
    pull,
    push,
    read_gitignore,
    rebase,
    remove_remote,
    rename_branch,
    reorder_commits,
    reset,
    revert,
    set_config_value,
    set_default_branch,
    set_remote_url,
    squash_commits,
    stash_drop,
    stash_pop,
    stash_push,
    undo_commit,
    write_gitignore,
)
from .git.runner import find_git, resolve_repository_root
from .github.api import GitHubAPI
from .github.oauth import (
    dotcom_endpoint,
    enterprise_endpoint_from_url,
    exchange_code_for_account,
    get_oauth_authorization_url,
    new_oauth_state,
)
from .logging import get_logger
from .models import (
    OVERSIZED_FILE_BYTES,
    Account,
    AheadBehind,
    AppFileStatusKind,
    ApplicationTheme,
    Author,
    Banner,
    BannerType,
    Branch,
    BranchType,
    CherryPickResult,
    CloningRepository,
    Commit,
    CommitMessage,
    CommittedFileChange,
    DiffSelectionType,
    FetchType,
    FileDiff,
    FoldoutType,
    HistoryTabMode,
    IStatusResult,
    ManualConflictResolution,
    MergeResult,
    MultiCommitOperationKind,
    Popup,
    PopupType,
    PullRequest,
    RebaseResult,
    Remote,
    Repository,
    RepositorySectionTab,
    SignInStep,
    StashEntry,
    TutorialStep,
    UncommittedChangesStrategy,
    WelcomeStep,
    WorkingDirectoryFileChange,
    git_author_name_is_valid,
    html_url_from_endpoint,
    sanitize_ref_name,
)
from .notifications import show_notification
from .paths import accounts_path, repositories_path
from .protocol import OAuthAction, OpenRepositoryAction, URLAction, parse_app_url
from .remote_parsing import account_for_remote, github_from_remote, parse_remote
from .settings import Settings, load_settings, save_settings
from .shells import find_shell, get_available_shells, open_external, open_file_manager, open_shell

log = get_logger()
Listener = Callable[[], None]


@dataclass
class RepositoryViewState:
    status: IStatusResult | None = None
    commits: list[Commit] = field(default_factory=list)
    branches: list[Branch] = field(default_factory=list)
    remotes: list[Remote] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    stashes: list[StashEntry] = field(default_factory=list)
    stash_count: int = 0
    pull_requests: list[PullRequest] = field(default_factory=list)
    issues: list[tuple[int, str]] = field(default_factory=list)
    selected_file: WorkingDirectoryFileChange | None = None
    selected_commit: Commit | None = None
    selected_commit_files: list[CommittedFileChange] = field(default_factory=list)
    current_diff: FileDiff | None = None
    commit_message: CommitMessage = field(default_factory=CommitMessage)
    show_co_authors: bool = False
    co_authors: list[Author] = field(default_factory=list)
    compare_branch: Branch | None = None
    history_mode: HistoryTabMode = HistoryTabMode.HISTORY
    stashed_visible: bool = False
    local_tags_to_push: list[str] = field(default_factory=list)
    loading: bool = False
    error: str | None = None
    ahead_behind: AheadBehind | None = None
    current_pull_request: PullRequest | None = None
    filter_text: str = ""
    hide_whitespace: bool = False
    side_by_side: bool = False


class AppStore:
    def __init__(self) -> None:
        self.settings = load_settings()
        self.repositories: list[Repository] = []
        self.accounts: list[Account] = []
        self.selected_repository_id: int | None = self.settings.selected_repository_id
        self.section = RepositorySectionTab(self.settings.repository_section) if self.settings.repository_section in RepositorySectionTab._value2member_map_ else RepositorySectionTab.CHANGES
        self.foldout: FoldoutType | None = None
        self.popup: Popup | None = None
        self.banner: Banner | None = None
        self.welcome_step: WelcomeStep | None = None if self.settings.welcome_shown else WelcomeStep.START
        self.sign_in_step: SignInStep | None = None
        self.sign_in_endpoint: str = dotcom_endpoint()
        self.sign_in_error: str | None = None
        self.oauth_state: str | None = None
        self.cloning: list[CloningRepository] = []
        self.repo_state: dict[int, RepositoryViewState] = {}
        self.tutorial_step = TutorialStep.NOT_APPLICABLE
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="desktop")
        self._next_id = 1
        self._load_accounts()
        self._load_repositories()

    # --- persistence ---
    def _load_accounts(self) -> None:
        path = accounts_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        for item in raw:
            key = f"{item.get('endpoint')}|{item.get('login')}"
            token = secrets.get_token(key) or ""
            self.accounts.append(
                Account(
                    login=item.get("login", ""),
                    endpoint=item.get("endpoint", dotcom_endpoint()),
                    token=token,
                    emails=item.get("emails") or [],
                    avatar_url=item.get("avatar_url", ""),
                    name=item.get("name", ""),
                    id=int(item.get("id") or 0),
                    plan=item.get("plan"),
                    copilot_endpoint=item.get("copilot_endpoint"),
                )
            )

    def _save_accounts(self) -> None:
        payload = []
        for account in self.accounts:
            key = f"{account.endpoint}|{account.login}"
            if account.token:
                secrets.set_token(key, account.token)
            payload.append(
                {
                    "login": account.login,
                    "endpoint": account.endpoint,
                    "emails": account.emails,
                    "avatar_url": account.avatar_url,
                    "name": account.name,
                    "id": account.id,
                    "plan": account.plan,
                    "copilot_endpoint": account.copilot_endpoint,
                }
            )
        accounts_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_repositories(self) -> None:
        path = repositories_path()
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        max_id = 0
        for item in raw:
            repo_id = int(item.get("id") or 0)
            max_id = max(max_id, repo_id)
            github = None
            gh = item.get("github")
            if gh:
                from .models import GitHubRepository

                github = GitHubRepository(
                    name=gh.get("name", ""),
                    owner=gh.get("owner", ""),
                    html_url=gh.get("html_url", ""),
                    clone_url=gh.get("clone_url", ""),
                    ssh_url=gh.get("ssh_url", ""),
                    default_branch=gh.get("default_branch", "main"),
                    private=bool(gh.get("private")),
                    fork=bool(gh.get("fork")),
                    endpoint=gh.get("endpoint", dotcom_endpoint()),
                )
            path_str = item.get("path", "")
            missing = not os.path.isdir(path_str)
            self.repositories.append(
                Repository(
                    id=repo_id,
                    path=path_str,
                    name=item.get("name") or os.path.basename(path_str),
                    is_missing=missing,
                    alias=item.get("alias"),
                    github=github,
                    tutorial=bool(item.get("tutorial")),
                    workflow_preferences=item.get("workflow_preferences") or {},
                )
            )
            self.repo_state[repo_id] = RepositoryViewState()
        self._next_id = max_id + 1

    def _save_repositories(self) -> None:
        payload = []
        for repo in self.repositories:
            gh = None
            if repo.github:
                gh = {
                    "name": repo.github.name,
                    "owner": repo.github.owner,
                    "html_url": repo.github.html_url,
                    "clone_url": repo.github.clone_url,
                    "ssh_url": repo.github.ssh_url,
                    "default_branch": repo.github.default_branch,
                    "private": repo.github.private,
                    "fork": repo.github.fork,
                    "endpoint": repo.github.endpoint,
                }
            payload.append(
                {
                    "id": repo.id,
                    "path": repo.path,
                    "name": repo.name,
                    "alias": repo.alias,
                    "tutorial": repo.tutorial,
                    "github": gh,
                    "workflow_preferences": repo.workflow_preferences,
                }
            )
        repositories_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                log.exception("listener failed")

    def persist_settings(self) -> None:
        self.settings.selected_repository_id = self.selected_repository_id
        self.settings.repository_section = self.section.value
        save_settings(self.settings)

    @property
    def selected_repository(self) -> Repository | None:
        if self.selected_repository_id is None:
            return None
        for repo in self.repositories:
            if repo.id == self.selected_repository_id:
                return repo
        return None

    def state_for(self, repo: Repository | None = None) -> RepositoryViewState:
        repo = repo or self.selected_repository
        if repo is None:
            return RepositoryViewState()
        return self.repo_state.setdefault(repo.id, RepositoryViewState())

    def show_popup(self, popup_type: PopupType, **payload: Any) -> None:
        self.popup = Popup(popup_type, payload)
        self.emit()

    def close_popup(self) -> None:
        self.popup = None
        self.emit()

    def show_banner(self, banner: Banner) -> None:
        self.banner = banner
        self.emit()

    def clear_banner(self) -> None:
        self.banner = None
        self.emit()

    def set_section(self, section: RepositorySectionTab) -> None:
        self.section = section
        self.persist_settings()
        self.emit()

    def select_repository(self, repo_id: int | None) -> None:
        self.selected_repository_id = repo_id
        self.foldout = None
        self.persist_settings()
        self.emit()
        repo = self.selected_repository
        if repo and not repo.is_missing:
            self.refresh_repository(repo)

    def add_repositories(self, paths: Sequence[str]) -> list[Repository]:
        added: list[Repository] = []
        for raw in paths:
            path = os.path.abspath(os.path.expanduser(raw))
            if not git_path_is_repository(path):
                root = resolve_repository_root(path)
                if not root:
                    raise NotARepositoryError(f"{path} isn't a Git repository.")
                path = root
            existing = None
            for candidate in self.repositories:
                try:
                    same = os.path.isdir(candidate.path) and os.path.isdir(path) and os.path.samefile(candidate.path, path)
                except OSError:
                    same = candidate.path == path
                if same:
                    existing = candidate
                    break
            if existing:
                added.append(existing)
                continue
            name = os.path.basename(path)
            repo = Repository(id=self._next_id, path=path, name=name)
            self._next_id += 1
            self._associate_github(repo)
            self.repositories.append(repo)
            self.repo_state[repo.id] = RepositoryViewState()
            added.append(repo)
        if added:
            self._save_repositories()
            self.select_repository(added[-1].id)
        return added

    def _associate_github(self, repo: Repository) -> None:
        try:
            remotes = get_remotes(repo.path)
        except GitError:
            return
        origin = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        if not origin:
            return
        account = account_for_remote(self.accounts, origin.url)
        endpoint = account.endpoint if account else dotcom_endpoint()
        parsed = parse_remote(origin.url)
        if parsed and parsed.hostname in ("github.com", "www.github.com") or account:
            repo.github = github_from_remote(origin.url, endpoint)

    def remove_repository(self, repo: Repository, delete_files: bool = False) -> None:
        self.repositories = [r for r in self.repositories if r.id != repo.id]
        self.repo_state.pop(repo.id, None)
        if self.selected_repository_id == repo.id:
            self.selected_repository_id = self.repositories[0].id if self.repositories else None
        if delete_files:
            import shutil

            try:
                shutil.rmtree(repo.path)
            except OSError as exc:
                log.warning("Failed to delete %s: %s", repo.path, exc)
        self._save_repositories()
        self.emit()

    def create_repository(self, path: str, description: str = "", default_branch: str | None = None) -> Repository:
        os.makedirs(path, exist_ok=True)
        if os.listdir(path):
            # Desktop allows existing files; just init
            pass
        branch = default_branch or get_default_branch()
        init_repository(path, branch)
        if description:
            from .git.ops import write_description

            write_description(path, description)
        repos = self.add_repositories([path])
        return repos[0]

    def clone(
        self,
        url: str,
        path: str,
        branch: str | None = None,
        account: Account | None = None,
    ) -> None:
        clone_id = -abs(int(uuid.uuid4().int % 10_000_000) or 1)
        cloning = CloningRepository(id=clone_id, path=path, url=url)
        self.cloning.append(cloning)
        self.emit()
        env = None
        account = account or account_for_remote(self.accounts, url)
        if account:
            env = env_for_remote(url, token=account.token)

        def work() -> None:
            try:
                clone_repository(url, path, branch=branch, default_branch=get_default_branch(), env=env)
            finally:
                self.cloning = [c for c in self.cloning if c.id != clone_id]

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                self.add_repositories([path])
            self.emit()

        self._run(work, done)

    def publish_repository(
        self,
        repo: Repository,
        name: str,
        description: str,
        private: bool,
        org: str | None,
        account: Account,
    ) -> None:
        api = GitHubAPI.from_account(account)

        def work() -> Repository:
            created = api.create_repository(name, description=description, private=private, org=org)
            remotes = get_remotes(repo.path)
            if any(r.name == "origin" for r in remotes):
                set_remote_url(repo.path, "origin", created.clone_url)
            else:
                add_remote(repo.path, "origin", created.clone_url)
            env = env_for_remote(created.clone_url, token=account.token)
            status = get_status(repo.path)
            branch = (status.current_branch if status else None) or get_default_branch()
            try:
                push(repo.path, "origin", branch, None, set_upstream=True, env=env)
            except GitError:
                # empty repo is ok
                pass
            repo.github = created
            self._save_repositories()
            return repo

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def refresh_repository(self, repo: Repository | None = None) -> None:
        repo = repo or self.selected_repository
        if not repo or repo.is_missing:
            return
        state = self.state_for(repo)
        state.loading = True
        self.emit()

        def work() -> RepositoryViewState:
            status = get_status(repo.path)
            commits = get_commits(repo.path, limit=100)
            branches = get_branches(repo.path)
            remotes = get_remotes(repo.path)
            tags = get_all_tags(repo.path)
            stashes, stash_count = get_stashes(repo.path)
            state.status = status
            state.commits = commits
            state.branches = branches
            state.remotes = remotes
            state.tags = tags
            state.stashes = stashes
            state.stash_count = stash_count
            state.ahead_behind = status.branch_ahead_behind if status else None
            state.loading = False
            if state.selected_file is None and status and status.working_directory.files:
                state.selected_file = status.working_directory.files[0]
            if state.selected_file:
                try:
                    state.current_diff = get_working_directory_diff(
                        repo.path, state.selected_file, state.hide_whitespace
                    )
                except GitError as exc:
                    log.debug("diff failed: %s", exc)
            if repo.github and self.accounts:
                account = self.account_for_repo(repo)
                if account:
                    try:
                        api = GitHubAPI.from_account(account)
                        state.pull_requests = api.fetch_pull_requests(repo.github.owner, repo.github.name)
                        current = status.current_branch if status else None
                        state.current_pull_request = next(
                            (pr for pr in state.pull_requests if pr.head_ref == current), None
                        )
                    except APIError as exc:
                        log.debug("PR fetch failed: %s", exc)
            return state

        def done(exc: BaseException | None) -> None:
            state.loading = False
            if exc:
                state.error = str(exc)
            self.emit()

        self._run(work, done)

    def account_for_repo(self, repo: Repository) -> Account | None:
        if repo.github:
            for account in self.accounts:
                if account.endpoint == repo.github.endpoint:
                    return account
        try:
            remotes = get_remotes(repo.path)
        except GitError:
            return None
        if remotes:
            return account_for_remote(self.accounts, remotes[0].url)
        return self.accounts[0] if self.accounts else None

    def env_for_repo(self, repo: Repository, url: str | None = None) -> dict[str, str] | None:
        if not url:
            try:
                remotes = get_remotes(repo.path)
                url = remotes[0].url if remotes else None
            except GitError:
                url = None
        if not url:
            return None
        account = account_for_remote(self.accounts, url) or self.account_for_repo(repo)
        if account:
            return env_for_remote(url, token=account.token)
        host = (parse_remote(url).hostname if parse_remote(url) else None)
        if host:
            user, password = secrets.get_generic(host)
            if user and password:
                return env_for_remote(url, username=user, password=password)
        return env_for_remote(url)

    def commit(
        self,
        repo: Repository,
        summary: str,
        description: str = "",
        *,
        amend: bool = False,
        co_authors: Sequence[Author] = (),
    ) -> None:
        state = self.state_for(repo)
        if not state.status:
            return
        files = [f for f in state.status.working_directory.files if f.include]
        if not files:
            raise ValidationError("No files selected for commit")
        oversized = []
        for file in files:
            full = os.path.join(repo.path, file.path)
            try:
                if os.path.isfile(full) and os.path.getsize(full) >= OVERSIZED_FILE_BYTES:
                    oversized.append(file.path)
            except OSError:
                pass
        if oversized:
            self.show_popup(PopupType.OVERSIZED_FILES, files=oversized)
            return
        if any(f.status.kind == AppFileStatusKind.CONFLICTED for f in files):
            self.show_popup(PopupType.COMMIT_CONFLICTS_WARNING)
            return
        trailers = co_author_trailers(co_authors)
        message = format_commit_message(summary, description, trailers)

        def work() -> None:
            create_commit(repo.path, message, files, amend=amend)

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                state.commit_message = CommitMessage()
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def set_file_included(self, repo: Repository, path: str, included: bool) -> None:
        state = self.state_for(repo)
        if not state.status:
            return
        files = []
        for f in state.status.working_directory.files:
            if f.path == path:
                files.append(f.with_include(included))
            else:
                files.append(f)
        from .models import WorkingDirectoryStatus

        state.status.working_directory = WorkingDirectoryStatus.from_files(files)
        self.emit()

    def set_include_all(self, repo: Repository, included: bool) -> None:
        state = self.state_for(repo)
        if not state.status:
            return
        state.status.working_directory = state.status.working_directory.with_include_all_files(included)
        self.emit()

    def select_file(self, repo: Repository, file: WorkingDirectoryFileChange | None) -> None:
        state = self.state_for(repo)
        state.selected_file = file
        if file:
            try:
                state.current_diff = get_working_directory_diff(repo.path, file, state.hide_whitespace)
            except GitError as exc:
                state.error = str(exc)
        else:
            state.current_diff = None
        self.emit()

    def select_commit(self, repo: Repository, commit: Commit | None) -> None:
        state = self.state_for(repo)
        state.selected_commit = commit
        if commit:
            state.selected_commit_files = get_changed_files(repo.path, commit.sha)
            if state.selected_commit_files:
                f = state.selected_commit_files[0]
                state.current_diff = get_commit_diff(repo.path, f.path, commit.sha, f.status, state.hide_whitespace)
        self.emit()

    def discard_files(self, repo: Repository, files: Sequence[WorkingDirectoryFileChange]) -> None:
        discard_paths(repo.path, [f.path for f in files])
        self.refresh_repository(repo)

    def push_repo(self, repo: Repository, force: bool = False) -> None:
        state = self.state_for(repo)
        status = state.status or get_status(repo.path)
        if not status or not status.current_branch:
            return
        remotes = state.remotes or get_remotes(repo.path)
        remote = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        if not remote:
            self.show_popup(PopupType.PUBLISH_REPOSITORY)
            return
        if status.branch_ahead_behind and status.branch_ahead_behind.behind > 0 and not force:
            self.show_popup(PopupType.PUSH_NEEDS_PULL)
            return
        env = self.env_for_repo(repo, remote.url)

        def work() -> None:
            push(
                repo.path,
                remote.name,
                status.current_branch,
                status.current_upstream_branch.split("/", 1)[-1] if status.current_upstream_branch else None,
                tags=state.local_tags_to_push or None,
                force_with_lease=force,
                set_upstream=not status.current_upstream_branch,
                env=env,
            )

        def done(exc: BaseException | None) -> None:
            if exc:
                self._handle_remote_error(repo, exc)
            else:
                state.local_tags_to_push = []
                self.refresh_repository(repo)
                show_notification("Push complete", f"Pushed {status.current_branch}", enabled=self.settings.notifications_enabled)
            self.emit()

        self._run(work, done)

    def pull_repo(self, repo: Repository) -> None:
        remotes = get_remotes(repo.path)
        remote = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        if not remote:
            return
        env = self.env_for_repo(repo, remote.url)

        def work() -> None:
            pull(repo.path, remote.name, env=env)

        def done(exc: BaseException | None) -> None:
            if exc:
                self._handle_remote_error(repo, exc)
            else:
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def fetch_repo(self, repo: Repository, fetch_type: FetchType = FetchType.USER_INITIATED) -> None:
        remotes = get_remotes(repo.path)
        remote = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        if not remote:
            return
        env = self.env_for_repo(repo, remote.url)

        def work() -> None:
            fetch(repo.path, remote.name, env=env)

        def done(exc: BaseException | None) -> None:
            if exc:
                self._handle_remote_error(repo, exc)
            else:
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def _handle_remote_error(self, repo: Repository, exc: BaseException) -> None:
        if isinstance(exc, GitError):
            if exc.is_push_protection:
                self.show_popup(PopupType.PUSH_PROTECTION_ERROR, error=str(exc))
                return
            if exc.is_saml_reauth:
                self.show_popup(PopupType.SAML_REAUTH_REQUIRED, error=str(exc))
                return
            if exc.is_workflow_scope:
                self.show_popup(PopupType.PUSH_REJECTED_WORKFLOW_SCOPE, error=str(exc))
                return
            if exc.is_auth_failure:
                url = ""
                try:
                    remotes = get_remotes(repo.path)
                    url = remotes[0].url if remotes else ""
                except GitError:
                    pass
                self.show_popup(PopupType.GENERIC_GIT_AUTHENTICATION, remote_url=url)
                return
            if exc.is_force_needed:
                self.show_popup(PopupType.CONFIRM_FORCE_PUSH)
                return
        self.show_popup(PopupType.ERROR, error=str(exc))

    def checkout(self, repo: Repository, branch: Branch) -> None:
        state = self.state_for(repo)
        status = state.status
        has_changes = bool(status and status.working_directory.files)
        strategy = UncommittedChangesStrategy(self.settings.uncommitted_changes_strategy)
        if has_changes and strategy == UncommittedChangesStrategy.ASK_FOR_CONFIRMATION:
            self.show_popup(PopupType.STASH_AND_SWITCH_BRANCH, branch=branch.name)
            return
        if has_changes and strategy == UncommittedChangesStrategy.STASH_ON_CURRENT_BRANCH:
            current = status.current_branch if status else "unknown"
            stash_push(repo.path, current or "unknown")
        checkout_branch(repo.path, branch.name_without_remote if branch.type == BranchType.REMOTE else branch.name)
        self.refresh_repository(repo)

    def create_branch_and_checkout(self, repo: Repository, name: str, start_point: str | None = None) -> None:
        name = sanitize_ref_name(name)
        create_branch(repo.path, name, start_point)
        checkout_branch(repo.path, name)
        self.refresh_repository(repo)

    def merge_branch(self, repo: Repository, branch: str, squash: bool = False) -> None:
        result = merge(repo.path, branch, squash=squash)
        if result == MergeResult.FAILED:
            self.show_banner(Banner(BannerType.MERGE_CONFLICTS_FOUND, our_branch=self.state_for(repo).status.current_branch if self.state_for(repo).status else None, their_branch=branch))
        elif result == MergeResult.ALREADY_UP_TO_DATE:
            self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=branch))
        else:
            self.show_banner(Banner(BannerType.SUCCESSFUL_MERGE, their_branch=branch))
        self.refresh_repository(repo)

    def rebase_branch(self, repo: Repository, base: str) -> None:
        result = rebase(repo.path, base)
        if result == RebaseResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.REBASE_CONFLICTS_FOUND, target_branch=base))
        elif result == RebaseResult.ALREADY_UP_TO_DATE:
            self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=base))
        elif result == RebaseResult.COMPLETED_WITHOUT_ERROR:
            self.show_banner(Banner(BannerType.SUCCESSFUL_REBASE, target_branch=base))
        self.refresh_repository(repo)

    def continue_conflict_operation(self, repo: Repository, kind: MultiCommitOperationKind) -> None:
        if kind == MultiCommitOperationKind.REBASE:
            continue_rebase(repo.path)
        elif kind == MultiCommitOperationKind.CHERRY_PICK:
            continue_cherry_pick(repo.path)
        elif kind == MultiCommitOperationKind.MERGE:
            state = self.state_for(repo)
            files = state.status.working_directory.files if state.status else []
            create_merge_commit(repo.path, files)
        self.refresh_repository(repo)

    def abort_conflict_operation(self, repo: Repository, kind: MultiCommitOperationKind) -> None:
        if kind == MultiCommitOperationKind.REBASE:
            abort_rebase(repo.path)
        elif kind == MultiCommitOperationKind.CHERRY_PICK:
            abort_cherry_pick(repo.path)
        elif kind == MultiCommitOperationKind.MERGE:
            abort_merge(repo.path)
        self.refresh_repository(repo)

    def cherry_pick_commits(self, repo: Repository, shas: Sequence[str], target_branch: str | None = None) -> None:
        if target_branch:
            checkout_branch(repo.path, target_branch)
        result = cherry_pick(repo.path, shas)
        if result == CherryPickResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.CHERRY_PICK_CONFLICTS_FOUND, target_branch=target_branch))
        elif result == CherryPickResult.COMPLETED_WITHOUT_ERROR:
            self.show_banner(Banner(BannerType.SUCCESSFUL_CHERRY_PICK, count=len(shas), target_branch=target_branch))
        self.refresh_repository(repo)

    def begin_sign_in(self, enterprise: bool = False) -> None:
        if enterprise:
            self.sign_in_step = SignInStep.ENDPOINT_ENTRY
            self.sign_in_endpoint = ""
        else:
            self.sign_in_step = SignInStep.AUTHENTICATION
            self.sign_in_endpoint = dotcom_endpoint()
        self.sign_in_error = None
        self.show_popup(PopupType.SIGN_IN, enterprise=enterprise)

    def set_sign_in_endpoint(self, url: str) -> None:
        try:
            self.sign_in_endpoint = enterprise_endpoint_from_url(url)
            self.sign_in_step = SignInStep.AUTHENTICATION
            self.sign_in_error = None
        except Exception as exc:
            self.sign_in_error = str(exc)
        self.emit()

    def request_browser_auth(self) -> str:
        self.oauth_state = new_oauth_state()
        url = get_oauth_authorization_url(self.sign_in_endpoint or dotcom_endpoint(), self.oauth_state)
        open_external(url)
        self.emit()
        return url

    def handle_url_action(self, action: URLAction | str) -> None:
        if isinstance(action, str):
            action = parse_app_url(action)
        if isinstance(action, OAuthAction):
            self.complete_oauth(action.code, action.state)
        elif isinstance(action, OpenRepositoryAction):
            self._open_from_url(action)

    def complete_oauth(self, code: str, state: str) -> None:
        if self.oauth_state and state != self.oauth_state:
            self.sign_in_error = "OAuth state mismatch"
            self.emit()
            return
        endpoint = self.sign_in_endpoint or dotcom_endpoint()

        def work() -> Account | None:
            return exchange_code_for_account(endpoint, code)

        def done(exc: BaseException | None, result: Account | None = None) -> None:
            # _run doesn't pass result; use a holder
            pass

        def thread() -> None:
            try:
                account = exchange_code_for_account(endpoint, code)
                if account is None:
                    self.sign_in_error = "Failed to exchange OAuth code"
                else:
                    self._add_account(account)
                    self.sign_in_step = SignInStep.SUCCESS
                    self.close_popup()
                    if self.welcome_step is not None:
                        self.welcome_step = WelcomeStep.CONFIGURE_GIT
            except Exception as exc:
                self.sign_in_error = str(exc)
            self.emit()

        threading.Thread(target=thread, daemon=True).start()

    def _add_account(self, account: Account) -> None:
        self.accounts = [a for a in self.accounts if not (a.endpoint == account.endpoint and a.login == account.login)]
        self.accounts.insert(0, account)
        self._save_accounts()

    def sign_out(self, account: Account) -> None:
        secrets.delete_token(f"{account.endpoint}|{account.login}")
        self.accounts = [a for a in self.accounts if a is not account and not (a.endpoint == account.endpoint and a.login == account.login)]
        self._save_accounts()
        self.emit()

    def finish_welcome(self) -> None:
        self.settings.welcome_shown = True
        self.welcome_step = None
        self.persist_settings()
        self.emit()

    def skip_welcome_sign_in(self) -> None:
        self.welcome_step = WelcomeStep.CONFIGURE_GIT
        self.emit()

    def _open_from_url(self, action: OpenRepositoryAction) -> None:
        url = action.url
        if url.startswith("github.com/") or not url.startswith("http"):
            if "://" not in url:
                url = "https://" + url if url.startswith("github.com") else f"https://github.com/{url}"
        parsed = parse_remote(url)
        if parsed:
            existing = next(
                (
                    r
                    for r in self.repositories
                    if r.github and r.github.owner == parsed.owner and r.github.name == parsed.name
                ),
                None,
            )
            if existing:
                self.select_repository(existing.id)
                if action.branch:
                    try:
                        checkout_branch(existing.path, action.branch)
                        self.refresh_repository(existing)
                    except GitError:
                        pass
                return
        default_dir = self.settings.clone_default_directory or str(Path.home() / "Documents" / "GitHub")
        name = parsed.name if parsed else "repository"
        self.show_popup(PopupType.CLONE_REPOSITORY, initial_url=url, path=os.path.join(default_dir, name), branch=action.branch)

    def open_in_shell(self, repo: Repository) -> None:
        shell = find_shell(self.settings.selected_shell)
        if not shell:
            self.show_popup(PopupType.OPEN_SHELL_FAILED, message="No terminal emulator found")
            return
        open_shell(shell, repo.path)

    def open_in_editor(self, repo: Repository, path: str | None = None) -> None:
        editor = find_editor(self.settings.selected_external_editor)
        if self.settings.use_custom_editor and self.settings.custom_editor_path:
            from .editors import Editor

            editor = Editor("Custom", self.settings.custom_editor_path, tuple(self.settings.custom_editor_args.split()))
        if not editor:
            self.show_popup(PopupType.EXTERNAL_EDITOR_FAILED, message="No external editor found")
            return
        open_in_editor(editor, path or repo.path)

    def open_working_directory(self, repo: Repository) -> None:
        open_file_manager(repo.path)

    def view_on_github(self, repo: Repository) -> None:
        if repo.github:
            open_external(repo.github.html_url)

    def create_issue(self, repo: Repository) -> None:
        if repo.github:
            open_external(repo.github.html_url + "/issues/new")

    def compare_on_github(self, repo: Repository) -> None:
        state = self.state_for(repo)
        branch = state.status.current_branch if state.status else None
        if repo.github and branch:
            open_external(f"{repo.github.html_url}/compare/{branch}")

    def open_pull_request(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if state.current_pull_request:
            open_external(state.current_pull_request.html_url)
            return
        self.show_popup(PopupType.START_PULL_REQUEST)

    def create_pull_request(self, repo: Repository, title: str, base: str, body: str = "", draft: bool = False) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            return
        state = self.state_for(repo)
        head = state.status.current_branch if state.status else None
        if not head:
            return
        api = GitHubAPI.from_account(account)
        pr = api.create_pull_request(repo.github.owner, repo.github.name, title, head, base, body, draft)
        open_external(pr.html_url)
        self.refresh_repository(repo)

    def generate_commit_message(self, repo: Repository) -> None:
        account = self.account_for_repo(repo)
        if not account:
            raise CopilotError("Sign in to GitHub to generate a commit message")
        state = self.state_for(repo)
        files = [f for f in (state.status.working_directory.files if state.status else []) if f.include]
        diffs = []
        for f in files[:20]:
            try:
                diff = get_working_directory_diff(repo.path, f)
                from .models import TextDiff

                if isinstance(diff, TextDiff):
                    diffs.append(diff.text)
            except GitError:
                pass
        api = GitHubAPI.from_account(account)
        summary, description = api.generate_commit_message("\n".join(diffs), [f.path for f in files])
        state.commit_message = CommitMessage(summary=summary, description=description)
        self.emit()

    def apply_theme(self) -> None:
        from .theme import apply_theme

        apply_theme(self.settings.theme)

    def set_theme(self, theme: str) -> None:
        self.settings.theme = theme
        self.persist_settings()
        self.apply_theme()
        self.emit()

    def save_git_user(self, name: str, email: str, default_branch: str | None = None) -> None:
        if not git_author_name_is_valid(name):
            raise ValidationError("Name can't contain a colon.")
        set_config_value(None, "user.name", name, global_only=True)
        set_config_value(None, "user.email", email, global_only=True)
        if default_branch:
            set_default_branch(default_branch)
            self.settings.default_branch = default_branch
            self.persist_settings()

    def _run(self, work: Callable[[], Any], done: Callable[[BaseException | None], None]) -> None:
        def runner() -> None:
            err: BaseException | None = None
            try:
                work()
            except BaseException as exc:
                err = exc
                log.debug("background work failed: %s", exc)
            try:
                from gi.repository import GLib

                GLib.idle_add(lambda: (done(err), False)[1])
            except Exception:
                done(err)

        self._pool.submit(runner)

    def handle_cli(self, argv: Sequence[str]) -> None:
        clone_url = None
        clone_branch = None
        for arg in argv:
            if arg.startswith("--cli-open="):
                path = arg.split("=", 1)[1]
                if git_path_is_repository(path) or resolve_repository_root(path):
                    repos = self.add_repositories([path])
                    if repos:
                        self.select_repository(repos[0].id)
                else:
                    self.show_popup(PopupType.ADD_REPOSITORY, path=path)
            elif arg.startswith("--cli-clone="):
                clone_url = arg.split("=", 1)[1]
            elif arg.startswith("--cli-branch="):
                clone_branch = arg.split("=", 1)[1]
            elif "://" in arg:
                self.handle_url_action(arg)
        if clone_url:
            self.show_popup(PopupType.CLONE_REPOSITORY, initial_url=clone_url, branch=clone_branch)
