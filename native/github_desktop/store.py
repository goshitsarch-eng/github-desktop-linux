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
from .errors import APIError, CopilotError, GitError, GitNotFoundError, NotARepositoryError, ValidationError, extract_secret_scanning_results
from .git import (
    abort_cherry_pick,
    abort_merge,
    abort_rebase,
    add_remote,
    add_safe_directory,
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
    discard_changes_from_selection,
    discard_paths,
    env_for_remote,
    fetch,
    format_commit_message,
    get_ahead_behind,
    get_all_tags,
    get_author_identity,
    get_branches,
    get_changeset_data,
    get_commit,
    get_commit_diff,
    get_commit_range_changed_files,
    get_commit_range_diff,
    get_commits,
    get_boolean_config_value,
    get_config_value,
    get_default_branch,
    get_remotes,
    get_repository_kind,
    get_stashes,
    get_status,
    get_blob_lines,
    get_working_directory_diff,
    get_working_directory_lines,
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
from .github.ci_checks import attach_workflow_jobs_to_checks, failing_checks, is_failure, split_rerunnable_checks
from .github.repo_rules import RepoRulesInfo, parse_repo_rules, use_repo_rules_logic
from .github.notifications import classify_notification, pull_request_from_payload
from .github.oauth import (
    dotcom_endpoint,
    enterprise_endpoint_from_url,
    exchange_code_for_account,
    get_oauth_authorization_url,
    new_oauth_state,
)
from .logging import get_logger
from .models import (
    COMMIT_BATCH_SIZE,
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
    ChangesListFilter,
    ChangesetData,
    CherryPickResult,
    CloningRepository,
    Commit,
    CommitMessage,
    CommittedFileChange,
    DiffComment,
    DiffSelectionType,
    FetchType,
    FileDiff,
    FoldoutType,
    HistoryTabMode,
    ImageDiffType,
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
    TextDiff,
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
    image_diff_type: str = ImageDiffType.TWO_UP.value
    file_filter: str = ChangesListFilter.ALL.value
    check_runs: list = field(default_factory=list)
    selected_commits: list[Commit] = field(default_factory=list)
    compare_ahead: list[Commit] = field(default_factory=list)
    compare_behind: list[Commit] = field(default_factory=list)
    mentions: list[str] = field(default_factory=list)
    diff_context: int | None = None
    local_commit_shas: list[str] = field(default_factory=list)
    diff_new_content: list[str] | None = None
    original_diff: TextDiff | None = None
    filter_new: bool = False
    filter_modified: bool = False
    filter_deleted: bool = False
    has_more_commits: bool = True
    history_filter: str = ""
    changeset: ChangesetData | None = None
    stashed_files: list[CommittedFileChange] = field(default_factory=list)
    selected_stashed_file: CommittedFileChange | None = None
    pr_base_branch: str | None = None
    pr_commits: list[Commit] = field(default_factory=list)
    pr_files: list[CommittedFileChange] = field(default_factory=list)
    pr_changeset: ChangesetData | None = None
    shas_in_diff: list[str] = field(default_factory=list)
    commit_summary_expanded: bool = False
    diff_comments: list = field(default_factory=list)
    repo_rules: RepoRulesInfo = field(default_factory=RepoRulesInfo)
    protected_branches: list[str] = field(default_factory=list)
    commit_to_amend: Commit | None = None


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
        self.cached_repo_rulesets: dict[int, dict] = {}
        self.welcome_step: WelcomeStep | None = None if self.settings.welcome_shown else WelcomeStep.START
        self.sign_in_step: SignInStep | None = None
        self.sign_in_endpoint: str = dotcom_endpoint()
        self.sign_in_error: str | None = None
        self.oauth_state: str | None = None
        self.cloning: list[CloningRepository] = []
        self.repo_state: dict[int, RepositoryViewState] = {}
        self.tutorial_step = TutorialStep.NOT_APPLICABLE
        self._seen_notifications: set[str] = set()
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
            kind = get_repository_kind(path_str)
            missing = kind != "regular"
            self.repositories.append(
                Repository(
                    id=repo_id,
                    path=path_str,
                    name=item.get("name") or os.path.basename(path_str),
                    is_missing=missing,
                    unsafe=kind == "unsafe",
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
        if repo:
            kind = get_repository_kind(repo.path)
            repo.is_missing = kind != "regular"
            repo.unsafe = kind == "unsafe"
            if not repo.is_missing:
                self.refresh_repository(repo)
            else:
                self.emit()

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

    def relocate_repository(self, repo: Repository, new_path: str) -> None:
        path = os.path.abspath(os.path.expanduser(new_path))
        if not git_path_is_repository(path):
            root = resolve_repository_root(path)
            if not root:
                raise NotARepositoryError(f"{path} isn't a Git repository.")
            path = root
        repo.path = path
        repo.name = os.path.basename(path)
        repo.is_missing = False
        repo.unsafe = False
        self._save_repositories()
        self.refresh_repository(repo)
        self.emit()

    def check_repository_path(self, repo: Repository) -> None:
        kind = get_repository_kind(repo.path)
        repo.is_missing = kind != "regular"
        repo.unsafe = kind == "unsafe"
        if not repo.is_missing:
            self.refresh_repository(repo)
        self.emit()

    def trust_repository(self, repo: Repository) -> None:
        add_safe_directory(repo.path)
        self.check_repository_path(repo)

    def clone_again(self, repo: Repository) -> None:
        url = repo.github.clone_url if repo.github else ""
        if not url:
            self.show_popup(PopupType.ERROR, error="This repository has no GitHub clone URL.")
            return
        dest = repo.path
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        if os.path.isdir(dest) and os.listdir(dest):
            self.show_popup(
                PopupType.ERROR,
                error="The original folder exists and is not empty. Locate the repository instead.",
            )
            return
        clone_id = -abs(int(uuid.uuid4().int % 10_000_000) or 1)
        cloning = CloningRepository(id=clone_id, path=dest, url=url)
        self.cloning.append(cloning)
        self.emit()
        account = account_for_remote(self.accounts, url)
        env = env_for_remote(url, token=account.token) if account else None

        def work() -> None:
            try:
                clone_repository(url, dest, default_branch=get_default_branch(), env=env)
            finally:
                self.cloning = [c for c in self.cloning if c.id != clone_id]

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                repo.is_missing = False
                repo.unsafe = False
                self._save_repositories()
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

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
        tutorial: bool = False,
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
                repos = self.add_repositories([path])
                if tutorial and repos:
                    repos[0].tutorial = True
                    self.tutorial_step = TutorialStep.PICK_EDITOR
                    self._save_repositories()
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
        if not repo:
            return
        kind = get_repository_kind(repo.path)
        repo.is_missing = kind != "regular"
        repo.unsafe = kind == "unsafe"
        if repo.is_missing:
            self.emit()
            return
        state = self.state_for(repo)
        previous_files = list(state.status.working_directory.files) if state.status else []
        previous_selected = state.selected_file.path if state.selected_file else None
        previous_commit = state.selected_commit.sha if state.selected_commit else None
        state.loading = True
        self.emit()

        def work() -> dict:
            status = get_status(repo.path)
            limit = max(COMMIT_BATCH_SIZE, len(state.commits) or COMMIT_BATCH_SIZE)
            grep = []
            if state.history_filter.strip():
                grep = ["--grep", state.history_filter.strip(), "--regexp-ignore-case"]
            commits = get_commits(repo.path, limit=limit, extra=grep)
            branches = get_branches(repo.path)
            remotes = get_remotes(repo.path)
            tags = get_all_tags(repo.path)
            stashes, stash_count = get_stashes(repo.path)
            payload: dict = {
                "status": status,
                "commits": commits,
                "has_more_commits": len(commits) == limit,
                "branches": branches,
                "remotes": remotes,
                "tags": tags,
                "stashes": stashes,
                "stash_count": stash_count,
                "ahead_behind": status.branch_ahead_behind if status else None,
                "pull_requests": [],
                "current_pull_request": None,
                "issues": [],
                "check_runs": [],
                "mentions": [],
                "local_commit_shas": [],
            }
            if status and status.current_branch and status.current_upstream_branch:
                payload["local_commit_shas"] = [
                    c.sha for c in get_commits(repo.path, f"{status.current_upstream_branch}..HEAD", limit=200)
                ]
            elif commits:
                payload["local_commit_shas"] = [commits[0].sha]
            if repo.github and self.accounts:
                account = self.account_for_repo(repo)
                if account:
                    try:
                        api = GitHubAPI.from_account(account)
                        prs = api.fetch_pull_requests(repo.github.owner, repo.github.name)
                        payload["pull_requests"] = prs
                        current = status.current_branch if status else None
                        payload["current_pull_request"] = next((pr for pr in prs if pr.head_ref == current), None)
                        pr = payload["current_pull_request"]
                        if pr:
                            try:
                                raw_comments = api.fetch_pull_request_comments(
                                    repo.github.owner, repo.github.name, pr.number
                                )
                                payload["diff_comments"] = [
                                    DiffComment(
                                        path=item.get("path") or "",
                                        body=item.get("body") or "",
                                        user=((item.get("user") or {}).get("login") or ""),
                                        html_url=item.get("html_url") or "",
                                        line=item.get("line"),
                                        original_line=item.get("original_line"),
                                        side=item.get("side") or "RIGHT",
                                        diff_hunk=item.get("diff_hunk") or "",
                                    )
                                    for item in raw_comments
                                ]
                            except APIError:
                                payload["diff_comments"] = []
                        try:
                            payload["issues"] = [(i.number, i.title) for i in api.fetch_issues(repo.github.owner, repo.github.name)[:80]]
                        except APIError:
                            pass
                        ref = (status.current_tip if status else None) or "HEAD"
                        try:
                            payload["check_runs"] = api.fetch_check_runs(repo.github.owner, repo.github.name, ref)
                        except APIError:
                            pass
                        try:
                            payload["mentions"] = api.fetch_mentions(repo.github.owner, repo.github.name)
                        except APIError:
                            pass
                        try:
                            payload["protected_branches"] = api.fetch_protected_branches(repo.github.owner, repo.github.name)
                        except APIError:
                            payload["protected_branches"] = []
                        try:
                            payload["repo_rules"] = self._load_repo_rules(api, repo, status)
                        except Exception as exc:
                            log.debug("repo rules fetch failed: %s", exc)
                    except APIError as exc:
                        log.debug("GitHub metadata fetch failed: %s", exc)
            return payload

        def done(exc: BaseException | None, result: dict | None = None) -> None:
            state.loading = False
            if exc:
                state.error = str(exc)
                self.emit()
                return
            data = result or {}
            status = data.get("status")
            if status and previous_files:
                old_sel = {f.path: f.selection for f in previous_files}
                from .models import WorkingDirectoryStatus

                merged = []
                for f in status.working_directory.files:
                    if f.path in old_sel:
                        merged.append(f.with_selection(old_sel[f.path]))
                    else:
                        merged.append(f)
                status.working_directory = WorkingDirectoryStatus.from_files(merged)
            state.status = status
            state.commits = data.get("commits") or []
            state.has_more_commits = bool(data.get("has_more_commits"))
            state.branches = data.get("branches") or []
            state.remotes = data.get("remotes") or []
            state.tags = data.get("tags") or {}
            state.stashes = data.get("stashes") or []
            state.stash_count = data.get("stash_count") or 0
            state.ahead_behind = data.get("ahead_behind")
            state.pull_requests = data.get("pull_requests") or []
            state.current_pull_request = data.get("current_pull_request")
            state.diff_comments = data.get("diff_comments") or []
            state.issues = data.get("issues") or []
            state.check_runs = data.get("check_runs") or []
            state.mentions = data.get("mentions") or []
            state.local_commit_shas = data.get("local_commit_shas") or []
            if "repo_rules" in data:
                state.repo_rules = data["repo_rules"]
            if "protected_branches" in data:
                state.protected_branches = list(data.get("protected_branches") or [])
            if previous_selected and status:
                state.selected_file = next((f for f in status.working_directory.files if f.path == previous_selected), None)
            if state.selected_file is None and status and status.working_directory.files:
                state.selected_file = status.working_directory.files[0]
            if previous_commit:
                state.selected_commit = next((c for c in state.commits if c.sha == previous_commit), None)
            if state.stashed_visible and state.stashes:
                self._advance_tutorial(repo, state)
                self.load_stash_files(repo)
                return
            if state.selected_file and self.section == RepositorySectionTab.CHANGES:
                self._load_working_diff(repo, state)
            self._advance_tutorial(repo, state)
            self.emit()

        self._run(work, done)

    def _load_working_diff(self, repo: Repository, state: RepositoryViewState) -> None:
        file = state.selected_file
        if not file:
            state.current_diff = None
            return
        try:
            diff = get_working_directory_diff(repo.path, file, state.hide_whitespace, state.diff_context)
            diff = self._prepare_text_diff(repo, file.path, diff)
            state.current_diff = diff
            if isinstance(diff, TextDiff):
                from .git.diff import selectable_line_indices

                selectable = set(selectable_line_indices(diff))
                updated = file.with_selection(file.selection.with_selectable_lines(selectable))
                if state.status:
                    files = [updated if f.path == file.path else f for f in state.status.working_directory.files]
                    from .models import WorkingDirectoryStatus

                    state.status.working_directory = WorkingDirectoryStatus.from_files(files)
                state.selected_file = updated
        except GitError as exc:
            state.error = str(exc)

    def _prepare_text_diff(self, repo: Repository, path: str, diff: FileDiff, commitish: str | None = None) -> FileDiff:
        if not isinstance(diff, TextDiff) or not diff.hunks:
            return diff
        from .git.expansion import apply_expansion_metadata

        state = self.state_for(repo)
        if commitish:
            new_lines = get_blob_lines(repo.path, commitish, path)
            old_lines = get_blob_lines(repo.path, f"{commitish}^", path)
        else:
            new_lines = get_working_directory_lines(repo.path, path)
            old_lines = get_blob_lines(repo.path, "HEAD", path)
        state.diff_new_content = new_lines
        state.original_diff = None
        prepared = apply_expansion_metadata(diff, old_line_count=len(old_lines), new_line_count=len(new_lines))
        if isinstance(prepared, TextDiff):
            from .ui.syntax import MAX_HIGHLIGHT_CONTENT, highlight_file

            tab = self.settings.tab_size
            old_bytes = sum(len(line) + 1 for line in old_lines)
            new_bytes = sum(len(line) + 1 for line in new_lines)
            if old_bytes <= MAX_HIGHLIGHT_CONTENT:
                prepared.old_line_markup = highlight_file(old_lines, path, tab_size=tab)
            if new_bytes <= MAX_HIGHLIGHT_CONTENT:
                prepared.new_line_markup = highlight_file(new_lines, path, tab_size=tab)
        return prepared

    def expand_hunk(self, repo: Repository, hunk_index: int, kind: str) -> None:
        from .git.diff import selectable_line_indices
        from .git.expansion import copy_text_diff, expand_text_diff_hunk, remap_selection

        state = self.state_for(repo)
        diff = state.current_diff
        lines = state.diff_new_content
        if not isinstance(diff, TextDiff) or not lines or hunk_index < 0:
            return
        before = copy_text_diff(diff)
        if state.original_diff is None:
            state.original_diff = before
        updated = expand_text_diff_hunk(diff, hunk_index, kind, lines)
        if updated is None:
            return
        file = state.selected_file
        if file is not None:
            remapped = remap_selection(before, updated, file.selection)
            remapped = remapped.with_selectable_lines(selectable_line_indices(updated))
            updated_file = file.with_selection(remapped)
            if state.status:
                from .models import WorkingDirectoryStatus

                files = [updated_file if f.path == file.path else f for f in state.status.working_directory.files]
                state.status.working_directory = WorkingDirectoryStatus.from_files(files)
            state.selected_file = updated_file
        state.current_diff = updated
        self.emit()

    def expand_whole_diff(self, repo: Repository) -> None:
        from .git.diff import selectable_line_indices
        from .git.expansion import copy_text_diff, expand_whole_text_diff, remap_selection

        state = self.state_for(repo)
        diff = state.current_diff
        lines = state.diff_new_content
        if not isinstance(diff, TextDiff) or not lines:
            return
        before = copy_text_diff(diff)
        if state.original_diff is None:
            state.original_diff = before
        updated = expand_whole_text_diff(diff, lines)
        if updated is None:
            return
        file = state.selected_file
        if file is not None:
            remapped = remap_selection(before, updated, file.selection)
            remapped = remapped.with_selectable_lines(selectable_line_indices(updated))
            updated_file = file.with_selection(remapped)
            if state.status:
                from .models import WorkingDirectoryStatus

                files = [updated_file if f.path == file.path else f for f in state.status.working_directory.files]
                state.status.working_directory = WorkingDirectoryStatus.from_files(files)
            state.selected_file = updated_file
        state.current_diff = updated
        self.emit()

    def collapse_expanded_diff(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if state.original_diff is None:
            return
        from .git.diff import selectable_line_indices

        restored = state.original_diff
        state.original_diff = None
        state.current_diff = restored
        file = state.selected_file
        if file is not None and isinstance(restored, TextDiff):
            state.selected_file = file.with_selection(file.selection.with_selectable_lines(selectable_line_indices(restored)))
        self.emit()

    def _advance_tutorial(self, repo: Repository, state: RepositoryViewState) -> None:
        if not repo.tutorial:
            return
        if self.tutorial_step in (TutorialStep.NOT_APPLICABLE, TutorialStep.PAUSED):
            self.tutorial_step = TutorialStep.PICK_EDITOR
        locals_ = [b for b in state.branches if b.type == BranchType.LOCAL]
        if self.tutorial_step == TutorialStep.PICK_EDITOR:
            return
        if self.tutorial_step == TutorialStep.CREATE_BRANCH and len(locals_) > 1:
            self.tutorial_step = TutorialStep.EDIT_FILE
        elif self.tutorial_step == TutorialStep.EDIT_FILE and state.status and state.status.working_directory.files:
            self.tutorial_step = TutorialStep.MAKE_COMMIT
        elif self.tutorial_step == TutorialStep.MAKE_COMMIT and len(state.commits) > 1:
            self.tutorial_step = TutorialStep.PUSH_BRANCH
        elif self.tutorial_step == TutorialStep.PUSH_BRANCH and state.status and state.status.current_upstream_branch:
            self.tutorial_step = TutorialStep.OPEN_PULL_REQUEST
        elif self.tutorial_step == TutorialStep.OPEN_PULL_REQUEST and state.current_pull_request:
            self.tutorial_step = TutorialStep.ALL_COMPLETE

    def complete_tutorial_editor_step(self) -> None:
        if self.tutorial_step == TutorialStep.PICK_EDITOR:
            self.tutorial_step = TutorialStep.CREATE_BRANCH
            self.emit()

    def skip_tutorial_pull_request(self) -> None:
        if self.tutorial_step == TutorialStep.OPEN_PULL_REQUEST:
            self.tutorial_step = TutorialStep.ALL_COMPLETE
            self.emit()

    def exit_tutorial(self) -> None:
        repo = self.selected_repository
        if repo:
            repo.tutorial = False
            self._save_repositories()
        self.tutorial_step = TutorialStep.NOT_APPLICABLE
        self.emit()

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
        amend = amend or state.commit_to_amend is not None
        files = [f for f in state.status.working_directory.files if f.include]
        if not files and not amend:
            raise ValidationError("No files selected for commit")
        filtered = (
            state.file_filter != ChangesListFilter.ALL.value
            or state.filter_new
            or state.filter_modified
            or state.filter_deleted
            or bool(state.filter_text)
        )
        if filtered and self.settings.confirm_commit_filtered_changes and not amend:
            self.show_popup(
                PopupType.CONFIRM_COMMIT_FILTERED_CHANGES,
                on_commit=lambda: self._commit_now(repo, summary, description, amend=amend, co_authors=co_authors),
            )
            return
        if co_authors:
            resolved, unknown = self.resolve_co_authors(list(co_authors))
            if unknown:
                self.show_popup(
                    PopupType.UNKNOWN_AUTHORS,
                    on_commit=lambda: self._commit_now(repo, summary, description, amend=amend, co_authors=resolved),
                )
                return
            co_authors = resolved
        self._commit_now(repo, summary, description, amend=amend, co_authors=co_authors)

    def resolve_co_authors(self, authors: Sequence[Author]) -> tuple[list[Author], list[Author]]:
        resolved: list[Author] = []
        unknown: list[Author] = []
        api = GitHubAPI.from_account(self.accounts[0]) if self.accounts else None
        for author in authors:
            login = author.username
            if login and api is not None:
                user = api.fetch_user_by_login(login)
                if user and user.get("login"):
                    handle = str(user["login"])
                    resolved.append(
                        Author(
                            name=str(user.get("name") or handle),
                            email=str(user.get("email") or f"{handle}@users.noreply.github.com"),
                            username=handle,
                        )
                    )
                    continue
            if not author.email:
                unknown.append(author)
                continue
            resolved.append(author)
        return resolved, unknown

    def _commit_now(
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
        amend = amend or state.commit_to_amend is not None
        files = [f for f in state.status.working_directory.files if f.include]
        if not files and not amend:
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
                state.commit_to_amend = None
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

    def set_line_included(self, repo: Repository, path: str, index: int, included: bool) -> None:
        state = self.state_for(repo)
        if not state.status:
            return
        files = []
        for f in state.status.working_directory.files:
            if f.path == path:
                files.append(f.with_selection(f.selection.with_line_selection(index, included)))
            else:
                files.append(f)
        from .models import WorkingDirectoryStatus

        state.status.working_directory = WorkingDirectoryStatus.from_files(files)
        state.selected_file = next((f for f in files if f.path == path), state.selected_file)
        self.emit()

    def set_hunk_included(self, repo: Repository, path: str, start: int, length: int, included: bool) -> None:
        state = self.state_for(repo)
        if not state.status:
            return
        files = []
        for f in state.status.working_directory.files:
            if f.path == path:
                files.append(f.with_selection(f.selection.with_range_selection(start, length, included)))
            else:
                files.append(f)
        from .models import WorkingDirectoryStatus

        state.status.working_directory = WorkingDirectoryStatus.from_files(files)
        state.selected_file = next((f for f in files if f.path == path), state.selected_file)
        self.emit()

    def set_files_included(self, repo: Repository, paths: Sequence[str], included: bool) -> None:
        wanted = set(paths)
        state = self.state_for(repo)
        if not state.status:
            return
        files = [f.with_include(included) if f.path in wanted else f for f in state.status.working_directory.files]
        from .models import WorkingDirectoryStatus

        state.status.working_directory = WorkingDirectoryStatus.from_files(files)
        self.emit()

    def set_file_filter(self, repo: Repository, value: str) -> None:
        self.state_for(repo).file_filter = value
        self.emit()

    def set_side_by_side(self, repo: Repository, enabled: bool) -> None:
        state = self.state_for(repo)
        state.side_by_side = enabled
        self.settings.show_side_by_side_diff = enabled
        self.persist_settings()
        self.emit()

    def set_image_diff_type(self, repo: Repository, kind: str) -> None:
        self.state_for(repo).image_diff_type = kind
        self.settings.image_diff_type = kind
        self.persist_settings()
        self.emit()

    def expand_diff_context(self, repo: Repository) -> None:
        self.expand_whole_diff(repo)

    def set_filter_kind(self, repo: Repository, kind: str, enabled: bool) -> None:
        state = self.state_for(repo)
        if kind == "new":
            state.filter_new = enabled
        elif kind == "modified":
            state.filter_modified = enabled
        elif kind == "deleted":
            state.filter_deleted = enabled
        self.emit()

    def toggle_changes_filter(self) -> None:
        self.settings.show_changes_filter = not self.settings.show_changes_filter
        self.persist_settings()
        self.emit()

    def set_zoom(self, factor: float) -> None:
        self.settings.zoom_factor = min(3.0, max(0.7, factor))
        self.persist_settings()
        from .ui.css import apply_zoom

        apply_zoom(self.settings.zoom_factor)
        self.emit()

    def install_cli(self) -> None:
        from .install_cli import install_cli

        try:
            install_cli()
        except OSError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return
        self.show_popup(PopupType.CLI_INSTALLED)

    def remember_branch(self, repo: Repository, name: str) -> None:
        recents = [name, *[b for b in self.settings.recent_branches.get(repo.path, []) if b != name]]
        self.settings.recent_branches[repo.path] = recents[:8]
        self.persist_settings()

    def default_branch_name(self, repo: Repository) -> str | None:
        if repo.github and repo.github.default_branch:
            return repo.github.default_branch
        try:
            return get_default_branch()
        except GitError:
            return "main"

    def update_from_default_branch(self, repo: Repository) -> None:
        name = self.default_branch_name(repo)
        if not name:
            return
        state = self.state_for(repo)
        target = next((b.name for b in state.branches if b.name == name or b.name.endswith("/" + name)), name)
        self.merge_branch(repo, target)

    def view_branch_on_github(self, repo: Repository, branch: str | None = None) -> None:
        if not repo.github:
            return
        from urllib.parse import quote

        state = self.state_for(repo)
        name = branch or (state.status.current_branch if state.status else None)
        if not name:
            return
        open_external(f"{repo.github.html_url}/tree/{quote(name)}")

    def checkout_pull_request(self, repo: Repository, pr: PullRequest) -> None:
        state = self.state_for(repo)
        branch = next((b for b in state.branches if b.name == pr.head_ref or b.name.endswith("/" + pr.head_ref)), None)
        if branch:
            self.checkout(repo, branch)
            return
        open_external(pr.html_url)

    def switch_to_pull_request(self, payload: dict[str, Any]) -> None:
        full_name = str(payload.get("repository") or payload.get("full_name") or "")
        repo = self.selected_repository
        if full_name:
            match = next(
                (
                    candidate
                    for candidate in self.repositories
                    if candidate.github and candidate.github.full_name.lower() == full_name.lower()
                ),
                None,
            )
            if match:
                self.select_repository(match.id)
                repo = match
        pr = pull_request_from_payload(
            payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else payload
        )
        if repo and pr:
            self.checkout_pull_request(repo, pr)

    def discard_selection(self, repo: Repository, path: str) -> None:
        state = self.state_for(repo)
        file = next((f for f in (state.status.working_directory.files if state.status else []) if f.path == path), None)
        diff = state.current_diff
        if file is None or not isinstance(diff, TextDiff):
            return
        discard_changes_from_selection(repo.path, path, diff, file.selection)
        self.refresh_repository(repo)

    def ignore_pattern(self, repo: Repository, pattern: str) -> None:
        append_ignore_rule(repo.path, pattern)
        self.refresh_repository(repo)

    def compare_to_branch(self, repo: Repository, branch_name: str | None) -> None:
        state = self.state_for(repo)
        if not branch_name:
            state.compare_branch = None
            state.history_mode = HistoryTabMode.HISTORY
            state.compare_ahead = []
            state.compare_behind = []
            self.refresh_repository(repo)
            return
        branch = next((b for b in state.branches if b.name == branch_name), None)
        state.compare_branch = branch
        state.history_mode = HistoryTabMode.COMPARE
        state.compare_ahead = get_commits(repo.path, f"{branch_name}..HEAD", limit=max(COMMIT_BATCH_SIZE, 100))
        state.compare_behind = get_commits(repo.path, f"HEAD..{branch_name}", limit=max(COMMIT_BATCH_SIZE, 100))
        state.commits = state.compare_ahead
        self.emit()

    def load_next_commit_batch(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if not state.has_more_commits:
            return
        skip = len(state.commits)
        extra: list[str] = []
        if state.history_filter.strip():
            extra = ["--grep", state.history_filter.strip(), "--regexp-ignore-case"]
        revision = None
        if state.history_mode == HistoryTabMode.COMPARE and state.compare_branch:
            revision = f"{state.compare_branch.name}..HEAD"
        batch = get_commits(repo.path, revision, limit=COMMIT_BATCH_SIZE, skip=skip, extra=extra)
        state.commits.extend(batch)
        if state.history_mode == HistoryTabMode.COMPARE:
            state.compare_ahead = state.commits
        state.has_more_commits = len(batch) == COMMIT_BATCH_SIZE
        self.emit()

    def set_history_filter(self, repo: Repository, text: str) -> None:
        state = self.state_for(repo)
        if state.history_filter == text:
            return
        state.history_filter = text
        extra = ["--grep", text.strip(), "--regexp-ignore-case"] if text.strip() else []
        revision = None
        if state.history_mode == HistoryTabMode.COMPARE and state.compare_branch:
            revision = f"{state.compare_branch.name}..HEAD"
        state.commits = get_commits(repo.path, revision, limit=COMMIT_BATCH_SIZE, extra=extra)
        state.has_more_commits = len(state.commits) == COMMIT_BATCH_SIZE
        self.emit()

    def toggle_stash(self, repo: Repository) -> None:
        state = self.state_for(repo)
        state.stashed_visible = not state.stashed_visible
        if state.stashed_visible:
            self.load_stash_files(repo)
        else:
            if state.selected_file:
                self._load_working_diff(repo, state)
            self.emit()

    def load_stash_files(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if not state.stashes:
            state.stashed_files = []
            state.selected_stashed_file = None
            state.stashed_visible = False
            self.emit()
            return
        stash = state.stashes[0]
        try:
            data = get_changeset_data(repo.path, stash.stash_sha)
        except GitError:
            data = ChangesetData()
        state.stashed_files = data.files
        stash.files = data.files
        if state.selected_stashed_file:
            state.selected_stashed_file = next(
                (f for f in data.files if f.path == state.selected_stashed_file.path),
                data.files[0] if data.files else None,
            )
        else:
            state.selected_stashed_file = data.files[0] if data.files else None
        if state.selected_stashed_file:
            self.select_stashed_file(repo, state.selected_stashed_file)
        else:
            state.current_diff = None
            self.emit()

    def select_stashed_file(self, repo: Repository, file: CommittedFileChange | None) -> None:
        state = self.state_for(repo)
        state.selected_stashed_file = file
        if file and state.stashes:
            try:
                state.current_diff = self._prepare_text_diff(
                    repo,
                    file.path,
                    get_commit_diff(
                        repo.path, file.path, file.commitish, file.status, state.hide_whitespace, state.diff_context
                    ),
                    commitish=file.commitish,
                )
            except GitError:
                state.current_diff = None
        else:
            state.current_diff = None
        self.emit()

    def restore_stash(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if not state.stashes:
            return
        stash_pop(repo.path, state.stashes[0].name)
        state.stashed_visible = False
        self.refresh_repository(repo)

    def discard_stash(self, repo: Repository, confirmed: bool = False) -> None:
        state = self.state_for(repo)
        if not state.stashes:
            return
        if self.settings.confirm_discard_stash and not confirmed:
            self.show_popup(PopupType.CONFIRM_DISCARD_STASH, stash=state.stashes[0].name)
            return
        stash_drop(repo.path, state.stashes[0].name)
        state.stashed_visible = False
        self.refresh_repository(repo)

    def load_pr_preview(self, repo: Repository, base: str | None = None) -> None:
        state = self.state_for(repo)
        base_name = base or state.pr_base_branch or self.default_branch_name(repo) or "main"
        state.pr_base_branch = base_name
        current = state.status.current_branch if state.status else None
        if not current or current == base_name:
            state.pr_commits = []
            state.pr_files = []
            state.pr_changeset = ChangesetData()
            self.emit()
            return
        state.pr_commits = get_commits(repo.path, f"{base_name}..HEAD", limit=200)
        if state.pr_commits:
            oldest = state.pr_commits[-1].sha
            newest = state.pr_commits[0].sha
            try:
                state.pr_changeset = get_commit_range_changed_files(repo.path, oldest, newest)
            except GitError:
                state.pr_changeset = ChangesetData()
            state.pr_files = list(state.pr_changeset.files)
        else:
            state.pr_changeset = ChangesetData()
            state.pr_files = []
        self.emit()

    def load_pr_preview_diff(self, repo: Repository, file: CommittedFileChange) -> FileDiff | None:
        state = self.state_for(repo)
        if not state.pr_commits:
            return None
        oldest = state.pr_commits[-1].sha
        newest = state.pr_commits[0].sha
        try:
            diff = get_commit_range_diff(
                repo.path, file.path, oldest, newest, file.status, state.hide_whitespace, state.diff_context
            )
        except GitError:
            return None
        return self._prepare_text_diff(repo, file.path, diff, commitish=newest)

    def add_dropped_paths(self, paths: Sequence[str]) -> None:
        dirs = []
        for raw in paths:
            path = os.path.abspath(os.path.expanduser(raw))
            if os.path.isfile(path):
                path = os.path.dirname(path)
            if os.path.isdir(path):
                dirs.append(path)
        if not dirs:
            return
        try:
            self.add_repositories(dirs)
        except (NotARepositoryError, OSError) as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))

    def select_commits(self, repo: Repository, commits: Sequence[Commit]) -> None:
        state = self.state_for(repo)
        state.selected_commits = list(commits)
        if not commits:
            state.selected_commit = None
            state.selected_commit_files = []
            state.changeset = None
            self.emit()
            return
        if len(commits) == 1:
            self.select_commit(repo, commits[0])
            return
        history = state.compare_ahead if state.history_mode == HistoryTabMode.COMPARE and state.compare_ahead else state.commits
        sha_set = {c.sha for c in commits}
        ordered_newest_first = [c for c in history if c.sha in sha_set]
        contiguous = _commits_are_contiguous(ordered_newest_first, history)
        state.selected_commit = ordered_newest_first[0] if ordered_newest_first else commits[0]
        if contiguous and len(ordered_newest_first) >= 2:
            newest = ordered_newest_first[0]
            oldest = ordered_newest_first[-1]
            state.shas_in_diff = [c.sha for c in ordered_newest_first]
            try:
                state.changeset = get_commit_range_changed_files(repo.path, oldest.sha, newest.sha)
            except GitError:
                state.changeset = ChangesetData()
            state.selected_commit_files = list(state.changeset.files)
            if state.selected_commit_files:
                f = state.selected_commit_files[0]
                try:
                    diff = get_commit_range_diff(
                        repo.path, f.path, oldest.sha, newest.sha, f.status, state.hide_whitespace, state.diff_context
                    )
                    state.current_diff = self._prepare_text_diff(repo, f.path, diff, commitish=newest.sha)
                except GitError:
                    state.current_diff = None
        else:
            self.select_commit(repo, state.selected_commit)
            state.shas_in_diff = [state.selected_commit.sha] if state.selected_commit else []
            self.emit()
            return
        self.emit()

    def squash_onto(self, repo: Repository, to_squash: Sequence[Commit], onto: Commit, message: str) -> None:
        last_retained = onto.parent_shas[0] if onto.parent_shas else None
        result = squash_commits(repo.path, list(to_squash), onto, last_retained, message)
        if result == RebaseResult.COMPLETED_WITHOUT_ERROR:
            self.show_banner(Banner(BannerType.SUCCESSFUL_SQUASH, count=len(to_squash) + 1))
        elif result == RebaseResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.CONFLICTS_FOUND, operation_description="Squash"))
        self.refresh_repository(repo)

    def reorder_onto(self, repo: Repository, to_move: Sequence[Commit], before: Commit | None) -> None:
        last_retained = None
        if before and before.parent_shas:
            last_retained = before.parent_shas[0]
        elif to_move:
            last_retained = to_move[-1].parent_shas[0] if to_move[-1].parent_shas else None
        result = reorder_commits(repo.path, list(to_move), before, last_retained)
        if result == RebaseResult.COMPLETED_WITHOUT_ERROR:
            self.show_banner(Banner(BannerType.SUCCESSFUL_REORDER, count=len(to_move)))
        elif result == RebaseResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.CONFLICTS_FOUND, operation_description="Reorder"))
        self.refresh_repository(repo)

    def revert_commit(self, repo: Repository, commit: Commit) -> None:
        revert(repo.path, commit.sha)
        self.refresh_repository(repo)

    def reset_to_commit(self, repo: Repository, commit: Commit) -> None:
        reset(repo.path, commit.sha, "mixed")
        self.refresh_repository(repo)

    def checkout_commit_sha(self, repo: Repository, sha: str) -> None:
        if self.settings.confirm_checkout_commit:
            self.show_popup(PopupType.CONFIRM_CHECKOUT_COMMIT, sha=sha)
            return
        checkout_commit(repo.path, sha)
        self.refresh_repository(repo)

    def amend_last(self, repo: Repository, summary: str, description: str = "") -> None:
        self.commit(repo, summary, description, amend=True)

    def start_amending(self, repo: Repository, *, continue_with_force_push: bool = False) -> None:
        state = self.state_for(repo)
        if not state.commits:
            return
        commit = state.commits[0]
        has_upstream = bool(state.status and state.status.current_upstream_branch)
        local = (not has_upstream) or commit.sha in (state.local_commit_shas or [])
        if (
            not continue_with_force_push
            and not local
            and (self.settings.confirm_force_push or self.settings.ask_for_confirmation_on_force_push)
        ):
            self.show_popup(
                PopupType.WARN_FORCE_PUSH,
                operation="Amend",
                on_begin=lambda: self.start_amending(repo, continue_with_force_push=True),
            )
            return
        state.commit_to_amend = commit
        state.commit_message = CommitMessage(summary=commit.summary, description=commit.body)
        self.set_section(RepositorySectionTab.CHANGES)
        self.emit()

    def stop_amending(self, repo: Repository) -> None:
        self.state_for(repo).commit_to_amend = None
        self.emit()

    def view_commit_on_github(self, repo: Repository, sha: str) -> None:
        if repo.github:
            open_external(f"{repo.github.html_url}/commit/{sha}")

    def reveal_in_file_manager(self, repo: Repository, relpath: str) -> None:
        full = os.path.join(repo.path, relpath)
        open_file_manager(full if os.path.exists(full) else repo.path)

    def open_file_default(self, repo: Repository, relpath: str) -> None:
        full = os.path.join(repo.path, relpath)
        if os.path.exists(full):
            open_external(full)

    def ignore_path(self, repo: Repository, path: str) -> None:
        append_ignore_rule(repo.path, "/" + path.lstrip("/"))
        self.refresh_repository(repo)

    def resolve_conflict(self, repo: Repository, path: str, resolution: ManualConflictResolution) -> None:
        from .git.ops import stage_manual_resolution

        stage_manual_resolution(repo.path, path, resolution)
        self.refresh_repository(repo)

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
            self._load_working_diff(repo, state)
        else:
            state.current_diff = None
        self.emit()

    def select_commit(self, repo: Repository, commit: Commit | None) -> None:
        state = self.state_for(repo)
        state.selected_commit = commit
        if commit and commit not in state.selected_commits:
            state.selected_commits = [commit]
        if commit:
            state.shas_in_diff = [commit.sha]
            try:
                state.changeset = get_changeset_data(repo.path, commit.sha)
            except GitError:
                state.changeset = ChangesetData()
            state.selected_commit_files = list(state.changeset.files)
            if state.selected_commit_files:
                f = state.selected_commit_files[0]
                state.current_diff = self._prepare_text_diff(
                    repo,
                    f.path,
                    get_commit_diff(
                        repo.path, f.path, commit.sha, f.status, state.hide_whitespace, state.diff_context
                    ),
                    commitish=commit.sha,
                )
            else:
                state.current_diff = None
        else:
            state.changeset = None
            state.selected_commit_files = []
            state.current_diff = None
            state.shas_in_diff = []
        self.emit()

    def load_history_diff(self, repo: Repository, path: str, sha: str, status) -> FileDiff:
        state = self.state_for(repo)
        selected = list(state.selected_commits)
        history = state.compare_ahead if state.history_mode == HistoryTabMode.COMPARE and state.compare_ahead else state.commits
        sha_set = {c.sha for c in selected}
        ordered = [c for c in history if c.sha in sha_set]
        if len(ordered) >= 2 and _commits_are_contiguous(ordered, history):
            newest, oldest = ordered[0], ordered[-1]
            diff = get_commit_range_diff(
                repo.path, path, oldest.sha, newest.sha, status, state.hide_whitespace, state.diff_context
            )
            prepared = self._prepare_text_diff(repo, path, diff, commitish=newest.sha)
        else:
            diff = get_commit_diff(repo.path, path, sha, status, state.hide_whitespace, state.diff_context)
            prepared = self._prepare_text_diff(repo, path, diff, commitish=sha)
        state.current_diff = prepared
        return prepared

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
                secrets = extract_secret_scanning_results(f"{exc.stderr}\n{exc.stdout}\n{exc}")
                self.show_popup(PopupType.PUSH_PROTECTION_ERROR, error=str(exc), secrets=secrets)
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
        name = branch.name_without_remote if branch.type == BranchType.REMOTE else branch.name
        checkout_branch(repo.path, name)
        self.remember_branch(repo, name)
        self.refresh_repository(repo)

    def create_branch_and_checkout(self, repo: Repository, name: str, start_point: str | None = None) -> None:
        name = sanitize_ref_name(name)
        create_branch(repo.path, name, start_point)
        checkout_branch(repo.path, name)
        self.remember_branch(repo, name)
        self.refresh_repository(repo)

    def merge_branch(self, repo: Repository, branch: str, squash: bool = False, on_done: Callable[..., None] | None = None) -> None:
        def work() -> tuple:
            return merge(repo.path, branch, squash=squash), get_status(repo.path)

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            merge_result = None
            status = None
            if isinstance(result, tuple) and len(result) == 2:
                merge_result, status = result
            if status is not None:
                self.state_for(repo).status = status
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            elif merge_result == MergeResult.FAILED:
                self.show_banner(Banner(BannerType.MERGE_CONFLICTS_FOUND, our_branch=self.state_for(repo).status.current_branch if self.state_for(repo).status else None, their_branch=branch))
                self.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind=MultiCommitOperationKind.SQUASH if squash else MultiCommitOperationKind.MERGE,
                    step="conflicts",
                )
            elif merge_result == MergeResult.ALREADY_UP_TO_DATE:
                self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=branch))
            else:
                self.show_banner(Banner(BannerType.SUCCESSFUL_MERGE, their_branch=branch))
            self.refresh_repository(repo)

        self._run(work, done)

    def rebase_branch(self, repo: Repository, base: str, on_done: Callable[..., None] | None = None) -> None:
        def work() -> tuple:
            return rebase(repo.path, base), get_status(repo.path)

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            rebase_result = None
            status = None
            if isinstance(result, tuple) and len(result) == 2:
                rebase_result, status = result
            if status is not None:
                self.state_for(repo).status = status
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            elif rebase_result == RebaseResult.CONFLICTS_ENCOUNTERED:
                self.show_banner(Banner(BannerType.REBASE_CONFLICTS_FOUND, target_branch=base))
                self.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind=MultiCommitOperationKind.REBASE, step="conflicts")
            elif rebase_result == RebaseResult.ALREADY_UP_TO_DATE:
                self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=base))
            elif rebase_result == RebaseResult.COMPLETED_WITHOUT_ERROR:
                self.show_banner(Banner(BannerType.SUCCESSFUL_REBASE, target_branch=base))
            self.refresh_repository(repo)

        self._run(work, done)

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

    def cherry_pick_commits(self, repo: Repository, shas: Sequence[str], target_branch: str | None = None, on_done: Callable[..., None] | None = None) -> None:
        def work() -> tuple:
            if target_branch:
                checkout_branch(repo.path, target_branch)
            return cherry_pick(repo.path, shas), get_status(repo.path)

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            cherry_result = None
            status = None
            if isinstance(result, tuple) and len(result) == 2:
                cherry_result, status = result
            if status is not None:
                self.state_for(repo).status = status
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            elif cherry_result == CherryPickResult.CONFLICTS_ENCOUNTERED:
                self.show_banner(Banner(BannerType.CHERRY_PICK_CONFLICTS_FOUND, target_branch=target_branch))
                self.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind=MultiCommitOperationKind.CHERRY_PICK, step="conflicts")
            elif cherry_result == CherryPickResult.COMPLETED_WITHOUT_ERROR:
                self.show_banner(Banner(BannerType.SUCCESSFUL_CHERRY_PICK, count=len(shas), target_branch=target_branch))
            self.refresh_repository(repo)

        self._run(work, done)

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
        def work() -> tuple[str, str]:
            account = self.account_for_repo(repo)
            if not account:
                raise CopilotError("Sign in to GitHub to generate a commit message")
            state = self.state_for(repo)
            files = [f for f in (state.status.working_directory.files if state.status else []) if f.include]
            diffs = []
            for f in files[:20]:
                try:
                    diff = get_working_directory_diff(repo.path, f)
                    if isinstance(diff, TextDiff):
                        diffs.append(diff.text)
                except GitError:
                    pass
            api = GitHubAPI.from_account(account)
            return api.generate_commit_message("\n".join(diffs), [f.path for f in files])

        def done(exc: BaseException | None, result: tuple[str, str] | None = None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
                return
            if result:
                self.state_for(repo).commit_message = CommitMessage(summary=result[0], description=result[1])
                self.emit()

        self._run(work, done)

    def _load_repo_rules(self, api: GitHubAPI, repo: Repository, status: IStatusResult | None) -> RepoRulesInfo:
        if not repo.github or not use_repo_rules_logic(self.account_for_repo(repo), repo):
            return RepoRulesInfo()
        branch = status.current_branch if status else None
        if not branch:
            return RepoRulesInfo()
        rules = api.fetch_repo_rules_for_branch(repo.github.owner, repo.github.name, branch)
        if not rules:
            return RepoRulesInfo()
        needed: dict[int, dict] = {}
        for rule in rules:
            rid = int(rule.get("ruleset_id") or 0)
            if not rid:
                continue
            cached = self.cached_repo_rulesets.get(rid)
            if cached is None:
                fetched = api.fetch_repo_ruleset(repo.github.owner, repo.github.name, rid)
                if fetched:
                    self.cached_repo_rulesets[rid] = fetched
                    cached = fetched
            if cached is not None:
                needed[rid] = cached
        gpg = get_boolean_config_value(repo.path, "commit.gpgsign") or False
        return parse_repo_rules(rules, needed, gpg_sign_enabled=gpg)

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

    def _run(self, work: Callable[[], Any], done: Callable[..., None]) -> None:
        def runner() -> None:
            err: BaseException | None = None
            result: Any = None
            try:
                result = work()
            except BaseException as exc:
                err = exc
                log.debug("background work failed: %s", exc)

            def finish() -> bool:
                try:
                    done(err, result)
                except TypeError:
                    done(err)
                return False

            invoked = False
            try:
                from gi.repository import Gio, GLib

                if Gio.Application.get_default() is not None:
                    GLib.idle_add(finish)
                    invoked = True
            except Exception:
                invoked = False
            if not invoked:
                finish()

        self._pool.submit(runner)

    def rerun_failed_checks(self, repo: Repository) -> None:
        self.rerun_checks(repo, failed_only=True)

    def rerun_checks(
        self,
        repo: Repository,
        check_runs: Sequence | None = None,
        *,
        failed_only: bool = True,
    ) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            return
        state = self.state_for(repo)
        runs = list(check_runs if check_runs is not None else (state.check_runs or []))
        if failed_only:
            runs = failing_checks(runs)
        if not runs:
            return
        api = GitHubAPI.from_account(account)
        owner, name = repo.github.owner, repo.github.name

        def work() -> None:
            if len(runs) == 1 and runs[0].actions_workflow is not None:
                try:
                    api.rerun_job(owner, name, runs[0].id)
                except APIError:
                    api.rerequest_check_run(owner, name, runs[0].id)
                return
            workflow_ids: set[int] = set()
            suite_ids: set[int] = set()
            for run in runs:
                if failed_only and run.actions_workflow is not None:
                    workflow_ids.add(run.actions_workflow.id)
                    continue
                if run.check_suite_id:
                    suite_ids.add(run.check_suite_id)
            for workflow_id in workflow_ids:
                try:
                    api.rerun_failed_jobs(owner, name, workflow_id)
                except APIError:
                    continue
            for suite_id in suite_ids:
                try:
                    api.rerequest_check_suite(owner, name, suite_id)
                except APIError:
                    continue

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def load_check_steps(self, repo: Repository, on_done: Callable[[], None] | None = None) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            if on_done:
                on_done()
            return
        state = self.state_for(repo)
        sha = (state.status.current_tip if state.status else None) or (state.commits[0].sha if state.commits else None)
        if not sha:
            if on_done:
                on_done()
            return
        api = GitHubAPI.from_account(account)
        owner, name = repo.github.owner, repo.github.name
        failed = [run for run in (state.check_runs or []) if is_failure(run) or run.conclusion in {"failure", "timed_out", "cancelled"}]

        def work() -> tuple[list, dict[int, list]]:
            jobs = api.fetch_workflow_jobs_for_sha(owner, name, sha)
            annotations: dict[int, list] = {}
            for run in failed[:8]:
                try:
                    annotations[run.id] = api.fetch_check_run_annotations(owner, name, run.id)
                except APIError:
                    continue
            return jobs, annotations

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            if not exc and result:
                jobs, annotations = result
                attach_workflow_jobs_to_checks(state.check_runs, jobs)
                for run in state.check_runs:
                    notes = annotations.get(run.id)
                    if notes:
                        run.annotations = notes
                self.emit()
            if on_done:
                on_done()

        self._run(work, done)

    def fetch_check_suites(self, repo: Repository, check_runs: Sequence) -> dict[int, Any]:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            return {}
        api = GitHubAPI.from_account(account)
        suites: dict[int, Any] = {}
        seen: set[int] = set()
        for run in check_runs:
            suite_id = getattr(run, "check_suite_id", None)
            if not suite_id or suite_id in seen:
                continue
            seen.add(suite_id)
            suite = api.fetch_check_suite(repo.github.owner, repo.github.name, suite_id)
            if suite:
                suites[suite_id] = suite
        return suites

    def load_rerunnable_checks(
        self,
        repo: Repository,
        check_runs: Sequence,
        *,
        failed_only: bool = True,
        on_done: Callable[[list, list], None] | None = None,
    ) -> None:
        def work() -> tuple[list, list]:
            suites = self.fetch_check_suites(repo, check_runs)
            return split_rerunnable_checks(check_runs, suites, failed_only=failed_only)

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            rerunnable, skipped = result if result else ([], list(check_runs))
            if on_done:
                on_done(rerunnable, skipped)

        self._run(work, done)

    def fetch_job_logs(self, repo: Repository, job_id: int, on_done: Callable[[str], None] | None = None) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            if on_done:
                on_done("")
            return
        api = GitHubAPI.from_account(account)
        owner, name = repo.github.owner, repo.github.name

        def work() -> str:
            return api.fetch_job_logs(owner, name, job_id)

        def done(exc: BaseException | None, result: str | None = None) -> None:
            text = "" if exc else (result or "")
            if on_done:
                on_done(text)

        self._run(work, done)

    def poll_notifications(self) -> None:
        if not self.settings.notifications_enabled or not self.accounts:
            return
        account = self.accounts[0]

        def work() -> list:
            api = GitHubAPI.from_account(account)
            notes = api.fetch_notifications()
            enriched: list[tuple[dict, dict | None]] = []
            for note in notes[:8]:
                subject = note.get("subject") or {}
                latest = subject.get("latest_comment_url") or subject.get("url")
                payload = None
                if latest:
                    try:
                        fetched = api.get("", raw_url=str(latest))
                        payload = fetched if isinstance(fetched, dict) else None
                    except Exception:
                        payload = None
                enriched.append((note, payload))
            return enriched

        def done(exc: BaseException | None, result: list | None = None) -> None:
            if exc or not result:
                return
            shown_popup = False
            for note, payload in result:
                ident = str(note.get("id") or "")
                if not ident or ident in self._seen_notifications:
                    continue
                self._seen_notifications.add(ident)
                action = classify_notification(note, payload)
                show_notification(action.title, action.body, enabled=True)
                if action.popup and not shown_popup:
                    shown_popup = True
                    self.show_popup(action.popup, **action.payload)

        self._run(work, done)

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


def _commits_are_contiguous(selected_newest_first: Sequence[Commit], history_newest_first: Sequence[Commit]) -> bool:
    if len(selected_newest_first) <= 1:
        return True
    sha_set = {c.sha for c in selected_newest_first}
    indexes = [i for i, commit in enumerate(history_newest_first) if commit.sha in sha_set]
    if len(indexes) != len(selected_newest_first):
        return False
    return indexes[-1] - indexes[0] + 1 == len(indexes)
