"""Application store: repositories, accounts, git state, and actions."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from . import secrets
from .custom_integration import command_for_custom_integration
from .editors import Editor, find_editor, get_available_editors, open_in_editor
from .errors import APIError, CopilotError, DiscardChangesError, GitError, GitNotFoundError, NotARepositoryError, ValidationError, extract_secret_scanning_results, overwritten_files_from_error, parse_saml_organization
from .git import (
    abort_cherry_pick,
    abort_merge,
    abort_rebase,
    add_remote,
    add_safe_directory,
    append_ignore_file,
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
    create_desktop_stash_entry,
    create_merge_commit,
    create_tag,
    delete_local_branch,
    delete_remote_branch,
    delete_tag,
    determine_mergeability,
    do_merge_commits_exist_after_commit,
    discard_changes_from_selection,
    discard_paths,
    discard_working_files,
    drop_desktop_stash_entry,
    env_for_remote,
    ensure_upstream_remote,
    fast_forward_branches,
    fetch,
    fetch_tags_to_push,
    format_commit_message,
    get_ahead_behind,
    get_ahead_behind_range,
    get_all_tags,
    get_author_identity,
    get_branch_merge_base_changed_files,
    get_branch_merge_base_diff,
    get_branches,
    get_branches_differing_from_upstream,
    get_branches_pointed_at,
    get_changeset_data,
    get_commit,
    get_commit_diff,
    get_commit_range_changed_files,
    get_commit_range_diff,
    get_commits,
    get_commits_between,
    get_cherry_pick_snapshot,
    get_boolean_config_value,
    get_config_value,
    get_default_branch,
    get_files_diff_text,
    get_global_config_path,
    get_last_desktop_stash_entry_for_branch,
    get_last_fetched,
    get_rebase_snapshot,
    get_remotes,
    get_remote_head,
    get_repository_kind,
    get_recent_branches,
    get_rebase_internal_state,
    get_stashes,
    get_stashed_files,
    get_status,
    get_partial_blob_lines,
    get_working_directory_diff,
    is_using_lfs,
    get_working_directory_lines,
    git_path_is_repository,
    init_repository,
    merge,
    move_stash_entry,
    prune_forked_remotes,
    prune_merged_branches,
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
    update_remote_head,
    write_gitignore,
)
from .git.askpass import askpass_env, set_prompt_callback, start_askpass_server
from .git.runner import find_git, resolve_repository_root
from .github.api import GitHubAPI
from .github.ci_checks import (
    attach_workflow_jobs_to_checks,
    failing_checks,
    is_failure,
    split_rerunnable_checks,
    summarize_check_runs,
)
from .github.repo_rules import RepoRulesInfo, parse_repo_rules, use_repo_rules_logic
from .github.notifications import classify_notification, is_high_signal_notification, pull_request_from_payload
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
    CommitOneLine,
    CommittedFileChange,
    ComparisonMode,
    ComputedAction,
    DiffComment,
    DiffSelectionType,
    FetchType,
    FileDiff,
    FoldoutType,
    ForcePushBranchState,
    ForkContributionTarget,
    GitHubRepository,
    HistoryTabMode,
    ImageDiffType,
    IStatusResult,
    ManualConflictResolution,
    MergeResult,
    MergeTreeResult,
    MultiCommitOperationKind,
    Popup,
    PopupType,
    PullRequest,
    PullRequestSuggestedNextAction,
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
    fork_contribution_target,
    fork_pull_request_remote_name,
    git_author_name_is_valid,
    github_for_contribution,
    github_from_dict,
    github_to_dict,
    html_url_from_endpoint,
    sanitize_ref_name,
)
from .notifications import show_notification
from .paths import accounts_path, repositories_path
from .protocol import OAuthAction, OpenRepositoryAction, URLAction, parse_app_url
from .remote_parsing import account_for_remote, github_from_remote, parse_remote, sanitize_remote_url, url_matches_remote
from .settings import Settings, load_settings, save_settings
from .shells import find_shell, get_available_shells, open_custom_shell, open_external, open_file_manager, open_shell
from .thank_you import (
    current_app_version,
    get_user_contributions,
    has_user_already_been_checked_or_thanked,
)

log = get_logger()
Listener = Callable[[], None]

# Desktop BackgroundFetchMinimumInterval (30 minutes) and BackgroundFetcher intervals.
BACKGROUND_FETCH_MINIMUM_INTERVAL = 30 * 60
BACKGROUND_FETCH_DEFAULT_INTERVAL = 60 * 60
BACKGROUND_FETCH_SERVER_MINIMUM = 5 * 60
INDICATOR_REFRESH_INTERVAL = 15 * 60


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
    pr_check_status: dict[int, str] = field(default_factory=dict)
    selected_commits: list[Commit] = field(default_factory=list)
    compare_ahead: list[Commit] = field(default_factory=list)
    compare_behind: list[Commit] = field(default_factory=list)
    compare_mode: ComparisonMode = ComparisonMode.AHEAD
    merge_tree: MergeTreeResult | None = None
    mentions: list[str] = field(default_factory=list)
    mentionables: list[dict] = field(default_factory=list)
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
    recent_branches: list[str] = field(default_factory=list)
    undo_sha: str | None = None
    undo_branch: str | None = None
    pending_pr: int | None = None
    pending_filepath: str | None = None
    force_push_with_lease_on: dict[str, str] = field(default_factory=dict)
    pending_force_push_before: str | None = None
    pull_with_rebase: bool = False
    last_fetched: float | None = None
    changed_files_count: int = 0


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
        self.sign_in_existing: Account | None = None
        self.oauth_state: str | None = None
        self.cloning: list[CloningRepository] = []
        self._clone_processes: dict[int, list] = {}
        self._clone_cancels: dict[int, threading.Event] = {}
        self.repo_state: dict[int, RepositoryViewState] = {}
        self.tutorial_step = TutorialStep.PAUSED if self.settings.tutorial_paused else TutorialStep.NOT_APPLICABLE
        self.progress_kind: str | None = None
        self.progress_title: str = ""
        self.progress_value: float = 0.0
        self._progress_only_emit: bool = False
        self._last_progress_emit: float = 0.0
        self._seen_notifications: set[str] = set()
        self._notification_payloads: dict[str, tuple[PopupType, dict]] = {}
        self._shown_upstream_popup: set[str] = set()
        self._retry_action: dict[str, Any] | None = None
        self._pending_open_action: OpenRepositoryAction | None = None
        self._listeners: list[Listener] = []
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="desktop")
        self._next_id = 1
        self._background_fetch_interval = BACKGROUND_FETCH_DEFAULT_INTERVAL
        self._background_fetch_in_flight = False
        self._ahead_behind_cache: dict[tuple[str, str, str], AheadBehind | None] = {}
        self._load_accounts()
        self._load_repositories()
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            start_askpass_server()
            set_prompt_callback(self.handle_askpass)

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
                github = github_from_dict(gh)
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
            payload.append(
                {
                    "id": repo.id,
                    "path": repo.path,
                    "name": repo.name,
                    "alias": repo.alias,
                    "tutorial": repo.tutorial,
                    "github": github_to_dict(repo.github),
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

    def _set_network_progress(self, kind: str | None, title: str = "", value: float = 0.0) -> None:
        self.progress_kind = kind
        self.progress_title = title
        self.progress_value = value
        if kind is None:
            self._progress_only_emit = False
            return
        now = time.monotonic()
        if now - self._last_progress_emit < 0.12:
            self.progress_kind = kind
            return
        self._last_progress_emit = now
        self._progress_only_emit = True

        def tick() -> bool:
            self.emit()
            return False

        try:
            from gi.repository import Gio, GLib

            if Gio.Application.get_default() is not None:
                GLib.idle_add(tick)
                return
        except Exception:
            pass
        self.emit()

    def _clear_network_progress(self) -> None:
        self.progress_kind = None
        self.progress_title = ""
        self.progress_value = 0.0
        self._progress_only_emit = False

    def _network_progress_cb(self, kind: str, title: str) -> Callable[[str, float], None]:
        def cb(text: str, percent: float) -> None:
            self._set_network_progress(kind, text or title, percent)

        return cb

    def _clone_progress_cb(self, cloning: CloningRepository) -> Callable[[str, float], None]:
        def cb(text: str, percent: float) -> None:
            cloning.progress = percent
            cloning.description = text
            self._set_network_progress("clone", text, percent)

        return cb

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
            for repo in added:
                try:
                    if is_using_lfs(repo.path):
                        self.show_popup(PopupType.INITIALIZE_LFS, paths=[repo.path])
                        break
                except GitError:
                    continue
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
        holder: list = []
        cancel = threading.Event()
        self._clone_processes[clone_id] = holder
        self._clone_cancels[clone_id] = cancel

        def work() -> None:
            clone_repository(
                url,
                dest,
                default_branch=get_default_branch(),
                env=env,
                progress=self._clone_progress_cb(cloning),
                process_holder=holder,
                cancel_event=cancel,
            )

        def done(exc: BaseException | None) -> None:
            self._clear_network_progress()
            self.cloning = [c for c in self.cloning if c.id != clone_id]
            cancelled = cancel.is_set()
            self._clone_processes.pop(clone_id, None)
            self._clone_cancels.pop(clone_id, None)
            if cancelled:
                self.emit()
                return
            if exc:
                self._show_clone_error(exc, url, dest)
            else:
                repo.is_missing = False
                repo.unsafe = False
                self._save_repositories()
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def create_repository(
        self,
        path: str,
        description: str = "",
        default_branch: str | None = None,
        *,
        name: str | None = None,
        create_readme: bool = False,
        gitignore: str | None = None,
        license_name: str | None = None,
        update_default_directory: bool = True,
    ) -> Repository:
        from .create_repo import (
            NO_GITIGNORE,
            NO_LICENSE,
            license_templates,
            write_default_readme,
            write_git_attributes,
            write_license,
            write_named_gitignore,
        )

        os.makedirs(path, exist_ok=True)
        folder_name = os.path.basename(os.path.abspath(path))
        display_name = name or folder_name
        branch = default_branch or get_default_branch()
        init_repository(path, branch)
        repos = self.add_repositories([path])
        if create_readme:
            try:
                write_default_readme(path, display_name, description)
            except OSError as exc:
                log.debug("createRepository: unable to write README at %s: %s", path, exc)
        if gitignore and gitignore != NO_GITIGNORE:
            try:
                write_named_gitignore(path, gitignore)
            except (OSError, ValueError) as exc:
                log.debug("createRepository: unable to write .gitignore at %s: %s", path, exc)
        if description:
            from .git.ops import write_description

            try:
                write_description(path, description)
            except OSError as exc:
                log.debug("createRepository: unable to write .git/description at %s: %s", path, exc)
        if license_name and license_name != NO_LICENSE:
            template = next((item for item in license_templates() if item.name == license_name), None)
            if template is not None:
                try:
                    author_name, author_email = get_author_identity(path)
                    write_license(
                        path,
                        template,
                        fullname=author_name or "",
                        email=author_email or "",
                        project=display_name,
                        description=description,
                    )
                except OSError as exc:
                    log.debug("createRepository: unable to write LICENSE at %s: %s", path, exc)
        try:
            write_git_attributes(path)
        except OSError as exc:
            log.debug("createRepository: unable to write .gitattributes at %s: %s", path, exc)
        status = get_status(path)
        files = list(status.working_directory.files) if status else []
        if files:
            try:
                create_commit(path, "Initial commit", files)
            except GitError as exc:
                log.debug("createRepository: initial commit failed at %s: %s", path, exc)
        if update_default_directory:
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                self.settings.clone_default_directory = parent
                self.persist_settings()
        if repos:
            self.refresh_repository(repos[0])
        return repos[0]

    def abort_clone(self, clone_id: int) -> None:
        """Cancel an in-flight `git clone` and drop it from the cloning list."""
        from .git.runner import abort_git_process

        event = self._clone_cancels.get(clone_id)
        if event is not None:
            event.set()
        for proc in list(self._clone_processes.get(clone_id) or []):
            abort_git_process(proc)
        self.cloning = [item for item in self.cloning if item.id != clone_id]
        self.emit()

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
        holder: list = []
        cancel = threading.Event()
        self._clone_processes[clone_id] = holder
        self._clone_cancels[clone_id] = cancel

        def work() -> None:
            clone_repository(
                url,
                path,
                branch=branch,
                default_branch=get_default_branch(),
                env=env,
                progress=self._clone_progress_cb(cloning),
                process_holder=holder,
                cancel_event=cancel,
            )

        def done(exc: BaseException | None) -> None:
            self._clear_network_progress()
            self.cloning = [c for c in self.cloning if c.id != clone_id]
            cancelled = cancel.is_set()
            self._clone_processes.pop(clone_id, None)
            self._clone_cancels.pop(clone_id, None)
            if cancelled:
                self.emit()
                return
            if exc:
                self._show_clone_error(exc, url, path, branch=branch, tutorial=tutorial)
            else:
                repos = self.add_repositories([path])
                for item in repos:
                    item.is_missing = False
                    item.unsafe = False
                if tutorial and repos:
                    repos[0].tutorial = True
                    self.settings.tutorial_paused = False
                    self.tutorial_step = TutorialStep.PICK_EDITOR
                    self._save_repositories()
                elif repos:
                    self._save_repositories()
            self.emit()

        self._run(work, done)

    def _show_clone_error(
        self,
        exc: BaseException,
        url: str,
        path: str,
        branch: str | None = None,
        tutorial: bool = False,
    ) -> None:
        self._retry_action = {"kind": "clone", "url": url, "path": path, "branch": branch, "tutorial": tutorial}
        self.show_popup(
            PopupType.ERROR,
            error=str(exc),
            title="Clone failed",
            retry_clone=True,
            name=os.path.basename(path.rstrip("/")) or path,
            retry=self.retry_last_remote_action,
        )

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
            upstream_mismatch = None
            parent = repo.github.parent if repo.github else None
            if parent and parent.clone_url and not self.settings.ignored_upstream_remotes.get(repo.path):
                try:
                    action, existing = ensure_upstream_remote(repo.path, parent.clone_url)
                    remotes = get_remotes(repo.path)
                    if action == "mismatch" and existing is not None:
                        upstream_mismatch = {"existing_url": existing.url, "parent_url": parent.clone_url}
                except GitError as exc:
                    log.debug("ensure upstream remote failed: %s", exc)
            tags = get_all_tags(repo.path)
            stashes, stash_count = get_stashes(repo.path)
            default_name = None
            if repo.github and repo.github.default_branch:
                default_name = repo.github.default_branch
            try:
                reflog_recent = get_recent_branches(repo.path, 6)
            except GitError:
                reflog_recent = []
            recent: list[str] = []
            for name in [*reflog_recent, *self.settings.recent_branches.get(repo.path, [])]:
                if name == default_name or name in recent:
                    continue
                recent.append(name)
                if len(recent) >= 5:
                    break
            payload: dict = {
                "status": status,
                "commits": commits,
                "has_more_commits": len(commits) == limit,
                "branches": branches,
                "remotes": remotes,
                "tags": tags,
                "stashes": stashes,
                "stash_count": stash_count,
                "recent_branches": recent,
                "ahead_behind": status.branch_ahead_behind if status else None,
                "pull_requests": [],
                "current_pull_request": None,
                "issues": [],
                "check_runs": [],
                "mentions": [],
                "local_commit_shas": [],
                "upstream_mismatch": None,
                "pull_with_rebase": bool(get_boolean_config_value(repo.path, "pull.rebase") or False),
                "last_fetched": get_last_fetched(repo.path),
            }
            payload["upstream_mismatch"] = upstream_mismatch
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
                        try:
                            fetched = api.fetch_repository(repo.github.owner, repo.github.name)
                            payload["github"] = fetched
                        except APIError as exc:
                            log.debug("repository metadata fetch failed: %s", exc)
                            fetched = repo.github
                        else:
                            fetched = payload.get("github") or repo.github
                        if fetched and fetched.fork and fetched.parent and fork_contribution_target(repo) == ForkContributionTarget.PARENT:
                            gh = fetched.parent
                        else:
                            gh = fetched or repo.github
                        prs = api.fetch_pull_requests(gh.owner, gh.name)
                        payload["pull_requests"] = prs
                        current = status.current_branch if status else None
                        payload["current_pull_request"] = next((pr for pr in prs if pr.head_ref == current), None)
                        pr = payload["current_pull_request"]
                        if pr:
                            try:
                                raw_comments = api.fetch_pull_request_comments(
                                    gh.owner, gh.name, pr.number
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
                            payload["issues"] = [(i.number, i.title) for i in api.fetch_issues(gh.owner, gh.name)[:80]]
                        except APIError:
                            pass
                        ref = (status.current_tip if status else None) or "HEAD"
                        try:
                            payload["check_runs"] = api.fetch_check_runs(repo.github.owner, repo.github.name, ref)
                        except APIError:
                            pass
                        try:
                            mentionables = api.fetch_mentionables(gh.owner, gh.name)
                            payload["mentionables"] = mentionables
                            payload["mentions"] = [item["login"] for item in mentionables if item.get("login")] or api.fetch_mentions(gh.owner, gh.name)
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
            prs = payload.get("pull_requests") or []
            try:
                pruned = prune_forked_remotes(repo.path, prs, branches)
                if pruned:
                    payload["remotes"] = get_remotes(repo.path)
                    payload["branches"] = get_branches(repo.path)
                    remotes = payload["remotes"]
                    branches = payload["branches"]
            except GitError as exc:
                log.debug("fork remote prune failed: %s", exc)
            if status and status.merge_head_found:
                pointed = get_branches_pointed_at(repo.path, "MERGE_HEAD")
                if pointed:
                    payload["merge_head_branch"] = next(
                        (name for name in pointed if name != status.current_branch), pointed[0]
                    )
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
            state.recent_branches = list(data.get("recent_branches") or [])
            if state.recent_branches:
                self.settings.recent_branches[repo.path] = list(state.recent_branches)
            state.ahead_behind = data.get("ahead_behind")
            state.pull_requests = data.get("pull_requests") or []
            state.current_pull_request = data.get("current_pull_request")
            state.diff_comments = data.get("diff_comments") or []
            state.issues = data.get("issues") or []
            state.check_runs = data.get("check_runs") or []
            state.mentions = data.get("mentions") or []
            state.mentionables = data.get("mentionables") or []
            state.local_commit_shas = data.get("local_commit_shas") or []
            if "local_tags_to_push" in data:
                state.local_tags_to_push = list(data.get("local_tags_to_push") or [])
            if "repo_rules" in data:
                state.repo_rules = data["repo_rules"]
            if "protected_branches" in data:
                state.protected_branches = list(data.get("protected_branches") or [])
            if "pull_with_rebase" in data:
                state.pull_with_rebase = bool(data.get("pull_with_rebase"))
            if "last_fetched" in data:
                state.last_fetched = data.get("last_fetched")
            if status:
                state.changed_files_count = len(status.working_directory.files)
            pending_rewrite = state.pending_force_push_before
            if pending_rewrite:
                state.pending_force_push_before = None
                self.add_branch_to_force_push_list(repo, pending_rewrite)
            if data.get("github"):
                repo.github = data["github"]
                self._save_repositories()
            mismatch = data.get("upstream_mismatch")
            if mismatch and repo.path not in self._shown_upstream_popup:
                self._shown_upstream_popup.add(repo.path)
                self.show_popup(PopupType.UPSTREAM_ALREADY_EXISTS, **mismatch)
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
            self._finish_pending_open(repo)
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
            new_lines = get_partial_blob_lines(repo.path, commitish, path)
            old_lines = get_partial_blob_lines(repo.path, f"{commitish}^", path)
        else:
            new_lines = get_working_directory_lines(repo.path, path)
            old_lines = get_partial_blob_lines(repo.path, "HEAD", path)
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
        if self.tutorial_step == TutorialStep.PAUSED:
            return
        if self.tutorial_step == TutorialStep.NOT_APPLICABLE:
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

    def pause_tutorial(self) -> None:
        self.tutorial_step = TutorialStep.PAUSED
        self.settings.tutorial_paused = True
        self.persist_settings()
        self.emit()

    def resume_tutorial(self) -> None:
        self.settings.tutorial_paused = False
        self.persist_settings()
        repo = next((r for r in self.repositories if r.tutorial), self.selected_repository)
        if repo:
            self.tutorial_step = TutorialStep.PICK_EDITOR
            self.select_repository(repo.id)
            self._advance_tutorial(repo, self.state_for(repo))
        else:
            self.tutorial_step = TutorialStep.NOT_APPLICABLE
        self.emit()

    def exit_tutorial(self) -> None:
        self.pause_tutorial()

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
        extra = askpass_env()
        if account:
            return env_for_remote(url, token=account.token, extra=extra or None)
        host = (parse_remote(url).hostname if parse_remote(url) else None)
        if host:
            user, password = secrets.get_generic(host)
            if user and password:
                return env_for_remote(url, username=user, password=password, extra=extra or None)
        return env_for_remote(url, extra=extra or None)

    def handle_askpass(self, prompt: str) -> str:
        """Show Desktop SSH dialogs on the GTK thread and return the answer."""
        from .git.askpass import auto_answer, parse_askpass_prompt

        parsed = parse_askpass_prompt(prompt)
        auto = auto_answer(parsed)
        if auto is not None:
            return auto
        event = threading.Event()
        box: dict[str, str] = {"value": ""}

        def show() -> bool:
            def finish(value: str | None, store_secret: bool = False) -> None:
                box["value"] = value or ""
                if store_secret and value:
                    account = parsed.key_path or parsed.username
                    if account:
                        secrets.set_password("GitHub Desktop SSH", account, value)
                event.set()

            if parsed.kind == "host":
                self.show_popup(
                    PopupType.ADD_SSH_HOST,
                    host=parsed.host,
                    ip=parsed.ip,
                    key_type=parsed.key_type,
                    fingerprint=parsed.fingerprint,
                    on_submit=lambda ok: finish("yes" if ok else "no"),
                )
            elif parsed.kind == "key":
                self.show_popup(
                    PopupType.SSH_KEY_PASSPHRASE,
                    key_path=parsed.key_path,
                    on_submit=lambda secret, remember=True: finish(secret, remember),
                )
            else:
                self.show_popup(
                    PopupType.SSH_USER_PASSWORD,
                    username=parsed.username or parsed.prompt,
                    on_submit=lambda secret, remember=True: finish(secret, remember),
                )
            return False

        try:
            from gi.repository import Gio, GLib

            if Gio.Application.get_default() is None:
                return ""
            GLib.idle_add(show)
        except Exception:
            return ""
        event.wait(timeout=300)
        return box["value"]

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
        from .filter_changes import (
            file_list_filter_state_from_view,
            filter_changed_files,
            is_committing_file_hidden_by_filter,
        )

        all_files = list(state.status.working_directory.files)
        filters = file_list_filter_state_from_view(state)
        visible = filter_changed_files(all_files, filters)
        if (
            self.settings.confirm_commit_filtered_changes
            and not amend
            and is_committing_file_hidden_by_filter(
                [f.path for f in files],
                [f.path for f in visible],
                len(all_files),
                filters,
            )
        ):
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
                    authors=unknown,
                    on_commit=lambda: self._commit_now(repo, summary, description, amend=amend, co_authors=resolved),
                )
                return
            co_authors = resolved
        self._commit_now(repo, summary, description, amend=amend, co_authors=co_authors)

    def resolve_co_authors(self, authors: Sequence[Author]) -> tuple[list[Author], list[Author]]:
        resolved: list[Author] = []
        unknown: list[Author] = []
        repo = self.selected_repository
        account = self.account_for_repo(repo) if repo else (self.accounts[0] if self.accounts else None)
        api = GitHubAPI.from_account(account) if account else None
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
        ignore_oversized: bool = False,
        ignore_conflicted: bool = False,
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
        if oversized and not ignore_oversized:
            self.show_popup(
                PopupType.OVERSIZED_FILES,
                files=oversized,
                on_commit=lambda: self._commit_now(
                    repo, summary, description, amend=amend, co_authors=co_authors, ignore_oversized=True
                ),
            )
            return
        conflicted = [f.path for f in files if f.status.kind == AppFileStatusKind.CONFLICTED]
        if conflicted and not ignore_conflicted:
            self.show_popup(
                PopupType.COMMIT_CONFLICTS_WARNING,
                files=conflicted,
                on_commit=lambda: self._commit_now(
                    repo,
                    summary,
                    description,
                    amend=amend,
                    co_authors=co_authors,
                    ignore_oversized=ignore_oversized,
                    ignore_conflicted=True,
                ),
            )
            return
        trailers = co_author_trailers(co_authors)
        message = format_commit_message(summary, description, trailers, repo=repo.path)

        def work() -> None:
            create_commit(repo.path, message, files, amend=amend)

        amended_sha = state.commit_to_amend.sha if amend and state.commit_to_amend else None

        def done(exc: BaseException | None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            else:
                state.commit_message = CommitMessage()
                state.commit_to_amend = None
                if amended_sha:
                    state.pending_force_push_before = amended_sha
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
            path = install_cli()
        except OSError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return
        self.show_popup(PopupType.CLI_INSTALLED, path=str(path))

    def remember_branch(self, repo: Repository, name: str) -> None:
        recents = [name, *[b for b in self.settings.recent_branches.get(repo.path, []) if b != name]]
        self.settings.recent_branches[repo.path] = recents[:5]
        self.persist_settings()

    def default_branch_name(self, repo: Repository) -> str | None:
        gh = github_for_contribution(repo) or repo.github
        if gh and gh.default_branch:
            return gh.default_branch
        try:
            remotes = get_remotes(repo.path)
            origin = next((remote for remote in remotes if remote.name == "origin"), remotes[0] if remotes else None)
            if origin:
                head = get_remote_head(repo.path, origin.name)
                if head:
                    return head
        except GitError:
            pass
        try:
            return get_default_branch()
        except GitError:
            return "main"

    def update_from_default_branch(self, repo: Repository) -> None:
        name = self.default_branch_name(repo)
        if not name:
            return
        state = self.state_for(repo)
        candidates: list[str] = []
        if repo.is_fork and fork_contribution_target(repo) == ForkContributionTarget.PARENT:
            candidates.extend([f"upstream/{name}", f"origin/{name}"])
        candidates.append(name)
        target = None
        for candidate in candidates:
            target = next((b.name for b in state.branches if b.name == candidate), None)
            if target:
                break
        if target is None:
            target = next((b.name for b in state.branches if b.name.endswith("/" + name)), name)
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
        def work() -> Branch | None:
            return self._find_pull_request_branch(repo, pr)

        def done(exc: BaseException | None, branch: Branch | None = None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
                return
            if branch:
                self.checkout(repo, branch)
                return
            self.show_popup(
                PopupType.ERROR,
                error=(
                    f"Couldn't find branch '{pr.head_ref}' in the pull request remote. "
                    "A common reason is that the PR author deleted their branch or fork."
                ),
            )

        self._run(work, done)

    def _find_pull_request_branch(self, repo: Repository, pr: PullRequest) -> Branch | None:
        remotes = get_remotes(repo.path)
        remote = None
        if pr.head_clone_url:
            remote = next((r for r in remotes if url_matches_remote(pr.head_clone_url, r)), None)
        if remote is None and pr.head_clone_url and pr.head_owner:
            name = fork_pull_request_remote_name(pr.head_owner)
            try:
                add_remote(repo.path, name, pr.head_clone_url)
            except GitError:
                pass
            remotes = get_remotes(repo.path)
            remote = next((r for r in remotes if r.name == name), None)
        state = self.state_for(repo)
        branches = get_branches(repo.path) or state.branches
        if remote is None:
            return next((b for b in branches if b.name == pr.head_ref or b.name.endswith("/" + pr.head_ref)), None)
        remote_ref = f"{remote.name}/{pr.head_ref}"
        existing = next(
            (b for b in branches if b.type == BranchType.LOCAL and b.upstream == remote_ref),
            None,
        )
        if existing:
            return existing
        existing = next((b for b in branches if b.type == BranchType.REMOTE and b.name == remote_ref), None)
        if existing is None:
            try:
                env = self.env_for_repo(repo, remote.url)
                fetch(repo.path, remote.name, env=env)
                branches = get_branches(repo.path)
                existing = next((b for b in branches if b.type == BranchType.REMOTE and b.name == remote_ref), None)
            except GitError as exc:
                log.error("Failed fetching remote %s: %s", remote.name, exc)
        if existing is None:
            return None
        default_names = {r.name for r in remotes if r.name in {"origin", "upstream"}}
        is_fork_remote = remote.name not in default_names
        if is_fork_remote:
            local_name = f"pr/{pr.number}"
            existing_local = next((b for b in branches if b.name == local_name and b.type == BranchType.LOCAL), None)
            if existing_local:
                return existing_local
            try:
                create_branch(repo.path, local_name, remote_ref)
            except GitError:
                branches = get_branches(repo.path)
                return next((b for b in branches if b.name == local_name), existing)
            return Branch(local_name, remote_ref, existing.tip_sha, BranchType.LOCAL, remote=remote.name, ref=f"refs/heads/{local_name}")
        return existing

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
        state.compare_mode = ComparisonMode.AHEAD
        state.commits = state.compare_ahead
        state.merge_tree = None
        ours = state.status.current_tip if state.status else None
        theirs = branch.tip_sha if branch else None
        if ours and theirs:
            try:
                state.merge_tree = determine_mergeability(repo.path, ours, theirs)
            except GitError:
                state.merge_tree = MergeTreeResult(kind=ComputedAction.INVALID)
        self.emit()

    def ahead_behind_between(self, repo: Repository, from_sha: str | None, to_sha: str | None) -> AheadBehind | None:
        """Desktop `aheadBehindStore.tryGetAheadBehind` cache keyed by commit SHAs."""
        if not from_sha or not to_sha:
            return None
        if from_sha == to_sha:
            return AheadBehind(ahead=0, behind=0)
        key = (repo.path, from_sha, to_sha)
        if key in self._ahead_behind_cache:
            return self._ahead_behind_cache[key]
        result = get_ahead_behind_range(repo.path, f"{from_sha}...{to_sha}")
        self._ahead_behind_cache[key] = result
        return result

    def set_compare_mode(self, repo: Repository, mode: ComparisonMode) -> None:
        state = self.state_for(repo)
        if state.compare_mode == mode:
            return
        state.compare_mode = mode
        if mode == ComparisonMode.BEHIND:
            state.commits = state.compare_behind
        else:
            state.commits = state.compare_ahead
        self.emit()

    def load_next_commit_batch(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if state.history_mode != HistoryTabMode.COMPARE and not state.has_more_commits:
            return
        skip = len(state.commits)
        extra: list[str] = []
        if state.history_filter.strip():
            extra = ["--grep", state.history_filter.strip(), "--regexp-ignore-case"]
        revision = None
        target = "ahead"
        if state.history_mode == HistoryTabMode.COMPARE and state.compare_branch:
            if state.compare_mode == ComparisonMode.BEHIND:
                revision = f"HEAD..{state.compare_branch.name}"
                skip = len(state.compare_behind)
                target = "behind"
            else:
                revision = f"{state.compare_branch.name}..HEAD"
                skip = len(state.compare_ahead)
        batch = get_commits(repo.path, revision, limit=COMMIT_BATCH_SIZE, skip=skip, extra=extra)
        if target == "behind":
            state.compare_behind.extend(batch)
            state.commits = state.compare_behind
        else:
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
            files = get_stashed_files(repo.path, stash.stash_sha)
        except GitError:
            files = []
        state.stashed_files = files
        stash.files = files
        if state.selected_stashed_file:
            state.selected_stashed_file = next(
                (f for f in files if f.path == state.selected_stashed_file.path),
                files[0] if files else None,
            )
        else:
            state.selected_stashed_file = files[0] if files else None
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
        latest = state.pr_commits[0].sha if state.pr_commits else (state.status.current_tip if state.status else "HEAD")
        try:
            changeset = get_branch_merge_base_changed_files(repo.path, base_name, current, latest)
        except GitError:
            changeset = None
        if changeset is None and state.pr_commits:
            oldest = state.pr_commits[-1].sha
            newest = state.pr_commits[0].sha
            try:
                changeset = get_commit_range_changed_files(repo.path, oldest, newest)
            except GitError:
                changeset = ChangesetData()
        state.pr_changeset = changeset or ChangesetData()
        state.pr_files = list(state.pr_changeset.files)
        self.emit()

    def load_pr_preview_diff(self, repo: Repository, file: CommittedFileChange) -> FileDiff | None:
        state = self.state_for(repo)
        base_name = state.pr_base_branch or self.default_branch_name(repo) or "main"
        current = state.status.current_branch if state.status else None
        latest = state.pr_commits[0].sha if state.pr_commits else (state.status.current_tip if state.status else "HEAD")
        try:
            if current:
                diff = get_branch_merge_base_diff(
                    repo.path,
                    file.path,
                    base_name,
                    current,
                    file.status,
                    state.hide_whitespace,
                    state.diff_context,
                    latest,
                )
            elif state.pr_commits:
                oldest = state.pr_commits[-1].sha
                newest = state.pr_commits[0].sha
                diff = get_commit_range_diff(
                    repo.path, file.path, oldest, newest, file.status, state.hide_whitespace, state.diff_context
                )
            else:
                return None
        except GitError:
            return None
        return self._prepare_text_diff(repo, file.path, diff, commitish=latest)

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
        if self._merge_commits_block_rewrite(repo, last_retained, "squash"):
            return
        undo_sha = self._capture_undo(repo)
        result = squash_commits(repo.path, list(to_squash), onto, last_retained, message)
        if result == RebaseResult.COMPLETED_WITHOUT_ERROR:
            self.state_for(repo).pending_force_push_before = undo_sha
            self.show_banner(Banner(BannerType.SUCCESSFUL_SQUASH, count=len(to_squash) + 1, undo_sha=undo_sha))
        elif result == RebaseResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.CONFLICTS_FOUND, operation_description="Squash", operation_kind=MultiCommitOperationKind.SQUASH.value))
        self.refresh_repository(repo)

    def reorder_onto(self, repo: Repository, to_move: Sequence[Commit], before: Commit | None) -> None:
        last_retained = None
        if before and before.parent_shas:
            last_retained = before.parent_shas[0]
        elif to_move:
            last_retained = to_move[-1].parent_shas[0] if to_move[-1].parent_shas else None
        if self._merge_commits_block_rewrite(repo, last_retained, "reorder"):
            return
        undo_sha = self._capture_undo(repo)
        result = reorder_commits(repo.path, list(to_move), before, last_retained)
        if result == RebaseResult.COMPLETED_WITHOUT_ERROR:
            self.state_for(repo).pending_force_push_before = undo_sha
            self.show_banner(Banner(BannerType.SUCCESSFUL_REORDER, count=len(to_move), undo_sha=undo_sha))
        elif result == RebaseResult.CONFLICTS_ENCOUNTERED:
            self.show_banner(Banner(BannerType.CONFLICTS_FOUND, operation_description="Reorder", operation_kind=MultiCommitOperationKind.REORDER.value))
        self.refresh_repository(repo)

    def _merge_commits_block_rewrite(self, repo: Repository, last_retained: str | None, operation: str) -> bool:
        try:
            exists = do_merge_commits_exist_after_commit(repo.path, last_retained)
        except GitError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return True
        if not exists:
            return False
        if operation == "squash":
            message = (
                "Unable to squash. Squashing replays all commits up to the last one required "
                "for the squash. A merge commit cannot exist among those commits."
            )
        else:
            message = (
                "Unable to reorder. Reordering replays all commits up to the last one required "
                "for the reorder. A merge commit cannot exist among those commits."
            )
        self.show_popup(PopupType.ERROR, error=message)
        return True

    def revert_commit(self, repo: Repository, commit: Commit) -> None:
        revert(repo.path, commit.sha)
        self.refresh_repository(repo)

    def reset_to_commit(self, repo: Repository, commit: Commit, *, show_confirmation: bool = True) -> None:
        state = self.state_for(repo)
        dirty = bool(state.status and state.status.working_directory.files)
        if show_confirmation and dirty:
            self.show_popup(PopupType.WARNING_BEFORE_RESET, commit=commit, sha=commit.sha)
            return
        self.set_section(RepositorySectionTab.CHANGES)
        reset(repo.path, commit.sha, "mixed")
        self.refresh_repository(repo)

    def undo_last_commit(self, repo: Repository, *, show_confirmation: bool = True) -> None:
        state = self.state_for(repo)
        commit = state.commits[0] if state.commits else None
        if commit is None:
            return
        dirty = bool(state.status and state.status.working_directory.files)
        if show_confirmation and ((self.settings.confirm_undo_commit and dirty) or commit.is_merge_commit):
            self.show_popup(
                PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO,
                commit=commit,
                is_working_directory_clean=not dirty,
            )
            return
        self.set_section(RepositorySectionTab.CHANGES)
        undo_commit(repo.path, commit.parent_shas)
        self._restore_commit_form(repo, commit)
        self.refresh_repository(repo)

    def _restore_commit_form(self, repo: Repository, commit: Commit) -> None:
        """Put the undone commit's summary/body/co-authors back in the commit box."""
        state = self.state_for(repo)
        authors = list(commit.co_authors)
        body = commit.body or ""
        if authors:
            lines = [ln for ln in body.splitlines() if not ln.lower().startswith("co-authored-by")]
            body = "\n".join(lines).strip()
            state.co_authors = authors
            state.show_co_authors = True
        state.commit_message = CommitMessage(
            summary=commit.summary,
            description=body,
            timestamp=int(time.time() * 1000),
        )

    def clear_changes_filter(self, repo: Repository) -> None:
        state = self.state_for(repo)
        state.file_filter = ChangesListFilter.ALL.value
        state.filter_text = ""
        state.filter_new = False
        state.filter_modified = False
        state.filter_deleted = False
        self.emit()

    def should_show_copilot_disclaimer(self) -> bool:
        seen = self.settings.commit_message_generation_disclaimer_last_seen
        if not seen:
            return True
        thirty_days_ms = 30 * 24 * 60 * 60 * 1000
        return (time.time() * 1000) - seen > thirty_days_ms

    def mark_copilot_disclaimer_seen(self) -> None:
        self.settings.commit_message_generation_disclaimer_last_seen = int(time.time() * 1000)
        self.persist_settings()

    def edit_global_git_config(self) -> None:
        try:
            path = get_global_config_path()
        except GitError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return
        repo = self.selected_repository
        if repo:
            self.open_in_editor(repo, path)
            return
        from .editors import find_editor, open_in_editor as launch

        editor = find_editor(self.settings.selected_external_editor)
        if not editor:
            self.show_popup(PopupType.EXTERNAL_EDITOR_FAILED, message="No external editor found")
            return
        launch(editor, path)

    def checkout_commit_sha(self, repo: Repository, sha: str, *, confirmed: bool = False) -> None:
        if self.settings.confirm_checkout_commit and not confirmed:
            self.show_popup(PopupType.CONFIRM_CHECKOUT_COMMIT, sha=sha)
            return
        checkout_commit(repo.path, sha)
        self.show_banner(Banner(BannerType.DETACHED_HEAD))
        self.refresh_repository(repo)

    def set_commit_author_email(self, repo: Repository, email: str, *, local: bool = True) -> None:
        if local:
            set_config_value(repo.path, "user.email", email)
        else:
            set_config_value(None, "user.email", email, global_only=True)
        self.emit()

    def add_branch_to_force_push_list(self, repo: Repository, before_sha: str | None) -> None:
        state = self.state_for(repo)
        branch = state.status.current_branch if state.status else None
        tip = (state.status.current_tip if state.status else None) or (state.commits[0].sha if state.commits else None)
        if not branch or not tip or tip == before_sha:
            return
        state.force_push_with_lease_on[branch] = tip

    def drop_current_branch_from_force_push_list(self, repo: Repository) -> None:
        state = self.state_for(repo)
        branch = state.status.current_branch if state.status else None
        if branch:
            state.force_push_with_lease_on.pop(branch, None)

    def current_branch_force_push_state(self, repo: Repository | None = None) -> ForcePushBranchState:
        repo = repo or self.selected_repository
        if repo is None:
            return ForcePushBranchState.NOT_AVAILABLE
        state = self.state_for(repo)
        ab = state.ahead_behind or (state.status.branch_ahead_behind if state.status else None)
        if ab is None or ab.behind == 0 or ab.ahead == 0:
            return ForcePushBranchState.NOT_AVAILABLE
        branch = state.status.current_branch if state.status else None
        tip = (state.status.current_tip if state.status else None) or (state.commits[0].sha if state.commits else None)
        if branch and tip and state.force_push_with_lease_on.get(branch) == tip:
            return ForcePushBranchState.RECOMMENDED
        return ForcePushBranchState.AVAILABLE

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
        state.commit_message = CommitMessage(
            summary=commit.summary,
            description=commit.body,
            timestamp=int(time.time() * 1000),
        )
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
        append_ignore_file(repo.path, path)
        self.refresh_repository(repo)

    def resolve_conflict(self, repo: Repository, path: str, resolution: ManualConflictResolution) -> None:
        from .git.ops import stage_manual_resolution

        state = self.state_for(repo)
        file = next((f for f in (state.status.working_directory.files if state.status else []) if f.path == path), None)
        if file is not None:
            stage_manual_resolution(repo.path, file, resolution)
        else:
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

    def discard_files(
        self,
        repo: Repository,
        files: Sequence[WorkingDirectoryFileChange],
        *,
        move_to_trash: bool = True,
    ) -> None:
        try:
            discard_working_files(
                repo.path,
                files,
                move_to_trash=move_to_trash,
                ask_permanent=self.settings.confirm_discard_changes_permanently,
            )
        except DiscardChangesError:
            self.show_popup(
                PopupType.DISCARD_CHANGES_RETRY,
                files=list(files),
                retry=lambda: self.discard_files(repo, files, move_to_trash=False),
            )
            return
        self.refresh_repository(repo)

    def _network_remote(self, repo: Repository, remotes: Sequence[Remote] | None = None, *, prefer_upstream: bool = False) -> Remote | None:
        remotes = list(remotes) if remotes is not None else get_remotes(repo.path)
        origin = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        if prefer_upstream and repo.is_fork and fork_contribution_target(repo) == ForkContributionTarget.PARENT:
            upstream = next((r for r in remotes if r.name == "upstream"), None)
            if upstream:
                return upstream
        return origin

    def push_repo(self, repo: Repository, force: bool = False, on_success: Callable[[], None] | None = None) -> None:
        state = self.state_for(repo)
        status = state.status or get_status(repo.path)
        if not status or not status.current_branch:
            return
        remotes = state.remotes or get_remotes(repo.path)
        remote = self._network_remote(repo, remotes)
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
                progress=self._network_progress_cb("push", f"Pushing to {remote.name}"),
            )

        def done(exc: BaseException | None) -> None:
            self._clear_network_progress()
            if exc:
                self._retry_action = {"kind": "push", "repo_id": repo.id, "force": force}
                self._handle_remote_error(repo, exc)
            else:
                if force:
                    self.drop_current_branch_from_force_push_list(repo)
                state.local_tags_to_push = []
                self.refresh_repository(repo)
                show_notification("Push complete", f"Pushed {status.current_branch}", enabled=self.settings.notifications_enabled)
                if on_success:
                    on_success()
            self.emit()

        self._run(work, done)

    def pull_repo(self, repo: Repository) -> None:
        remotes = get_remotes(repo.path)
        remote = self._network_remote(repo, remotes, prefer_upstream=True)
        if not remote:
            return
        env = self.env_for_repo(repo, remote.url)

        def work() -> list[str]:
            pull(repo.path, remote.name, env=env, progress=self._network_progress_cb("pull", f"Pulling {remote.name}"))
            try:
                eligible = get_branches_differing_from_upstream(repo.path)
                fast_forward_branches(repo.path, eligible)
            except GitError as exc:
                log.debug("Branch fast-forwarding failed: %s", exc)
            return self._tags_to_push(repo, remote)

        def done(exc: BaseException | None, tags: list[str] | None = None) -> None:
            self._clear_network_progress()
            if exc:
                self._retry_action = {"kind": "pull", "repo_id": repo.id}
                self._handle_remote_error(repo, exc)
            else:
                if tags is not None:
                    self.state_for(repo).local_tags_to_push = list(tags)
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def should_background_fetch(self, repo: Repository | None = None) -> bool:
        """Desktop `shouldBackgroundFetch`: GitHub repos whose last fetch is at least 30 minutes ago."""
        repo = repo or self.selected_repository
        if repo is None or repo.github is None or repo.is_missing:
            return False
        if self.progress_kind:
            return False
        last = self.state_for(repo).last_fetched
        if last is None:
            try:
                last = get_last_fetched(repo.path)
            except Exception:
                last = None
        if last is None:
            return True
        return (time.time() - last) >= BACKGROUND_FETCH_MINIMUM_INTERVAL

    @property
    def background_fetch_interval(self) -> int:
        """Seconds between background fetch attempts (Desktop DefaultFetchInterval plus server poll)."""
        return int(self._background_fetch_interval)

    def set_pull_request_suggested_next_action(self, value: str) -> None:
        allowed = {item.value for item in PullRequestSuggestedNextAction}
        if value not in allowed:
            return
        self.settings.pull_request_suggested_next_action = value
        self.persist_settings()
        self.emit()

    def refresh_repo_indicators(self, *, fetch_remotes: bool = True) -> None:
        """Populate ahead/behind and uncommitted counts for every registered repository.

        Matches Desktop `updateSidebarIndicator` / `RepositoryIndicatorUpdater`. Unselected
        GitHub remotes are fetched quietly when `should_background_fetch` is true.
        """
        if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE"):
            fetch_remotes = False
        repos = list(self.repositories)
        selected_id = self.selected_repository_id

        def work() -> dict[int, tuple[object, int, float | None]]:
            results: dict[int, tuple[object, int, float | None]] = {}
            for repo in repos:
                if repo.is_missing or not os.path.isdir(repo.path):
                    continue
                try:
                    status = get_status(repo.path)
                    last = get_last_fetched(repo.path)
                    if (
                        fetch_remotes
                        and repo.github
                        and repo.id != selected_id
                        and self.should_background_fetch(repo)
                    ):
                        try:
                            remotes = get_remotes(repo.path)
                            remote = self._network_remote(repo, remotes, prefer_upstream=True)
                            if remote:
                                fetch(repo.path, remote.name, env=self.env_for_repo(repo, remote.url))
                                status = get_status(repo.path)
                                last = get_last_fetched(repo.path)
                        except GitError as exc:
                            log.debug("indicator fetch failed for %s: %s", repo.path, exc)
                    count = len(status.working_directory.files) if status else 0
                    ab = status.branch_ahead_behind if status else None
                    results[repo.id] = (ab, count, last)
                except Exception as exc:
                    log.debug("indicator refresh failed for %s: %s", repo.path, exc)
            return results

        def apply(results: dict[int, tuple[object, int, float | None]]) -> None:
            for repo in self.repositories:
                payload = results.get(repo.id)
                if payload is None:
                    continue
                ahead_behind, count, last = payload
                state = self.state_for(repo)
                state.ahead_behind = ahead_behind  # type: ignore[assignment]
                state.changed_files_count = count
                state.last_fetched = last
            self.emit()

        def done(exc: BaseException | None, results: dict[int, tuple[object, int, float | None]] | None = None) -> None:
            if exc:
                log.debug("refresh_repo_indicators failed: %s", exc)
                return
            apply(results or {})

        try:
            from gi.repository import Gio

            if Gio.Application.get_default() is not None:
                self._run(work, done)
                return
        except Exception:
            pass
        apply(work())

    def fetch_repo(self, repo: Repository, fetch_type: FetchType = FetchType.USER_INITIATED) -> None:
        quiet = fetch_type == FetchType.BACKGROUND_TASK
        if quiet:
            if self._background_fetch_in_flight or self.progress_kind:
                return
            if not self.should_background_fetch(repo):
                return
            self._background_fetch_in_flight = True
        remotes = get_remotes(repo.path)
        remote = self._network_remote(repo, remotes, prefer_upstream=True)
        if not remote:
            if quiet:
                self._background_fetch_in_flight = False
            return
        env = self.env_for_repo(repo, remote.url)
        extra = [r for r in remotes if r.name == "upstream" and r.name != remote.name]
        progress = None if quiet else self._network_progress_cb("fetch", f"Fetching {remote.name}")

        def work() -> list[str]:
            fetch(repo.path, remote.name, env=env, progress=progress)
            try:
                update_remote_head(repo.path, remote.name, env=env)
            except GitError as exc:
                log.debug("update remote HEAD failed: %s", exc)
            for other in extra:
                try:
                    fetch(repo.path, other.name, env=self.env_for_repo(repo, other.url))
                except GitError as exc:
                    log.debug("upstream fetch failed: %s", exc)
            try:
                eligible = get_branches_differing_from_upstream(repo.path)
                fast_forward_branches(repo.path, eligible)
            except GitError as exc:
                log.debug("Branch fast-forwarding failed: %s", exc)
            self._prune_merged_branches(repo)
            if quiet and repo.github:
                self._update_background_fetch_interval(repo)
            return self._tags_to_push(repo, remote)

        def done(exc: BaseException | None, tags: list[str] | None = None) -> None:
            if quiet:
                self._background_fetch_in_flight = False
            else:
                self._clear_network_progress()
            if exc:
                if quiet:
                    log.debug("background fetch failed: %s", exc)
                else:
                    self._retry_action = {"kind": "fetch", "repo_id": repo.id}
                    self._handle_remote_error(repo, exc)
            else:
                if tags is not None:
                    self.state_for(repo).local_tags_to_push = list(tags)
                self.refresh_repository(repo)
            self.emit()

        self._run(work, done)

    def _update_background_fetch_interval(self, repo: Repository) -> None:
        interval = BACKGROUND_FETCH_DEFAULT_INTERVAL
        account = self.account_for_repo(repo)
        github = repo.github
        if account and github:
            try:
                poll = GitHubAPI.from_account(account).get_fetch_poll_interval(github.owner, github.name)
                if poll is not None:
                    # Desktop Math.max(parsedHeader, MinimumInterval) with both in milliseconds.
                    interval = max(int(poll / 1000), BACKGROUND_FETCH_SERVER_MINIMUM)
            except Exception as exc:
                log.debug("fetch poll interval failed: %s", exc)
        self._background_fetch_interval = interval

    def _tags_to_push(self, repo: Repository, remote: Remote) -> list[str]:
        status = self.state_for(repo).status or get_status(repo.path)
        if not status or not status.current_branch:
            return []
        try:
            return fetch_tags_to_push(
                repo.path, remote.name, status.current_branch, env=self.env_for_repo(repo, remote.url)
            )
        except GitError as exc:
            log.debug("fetch tags to push failed: %s", exc)
            return list(self.state_for(repo).local_tags_to_push)

    def _prune_merged_branches(self, repo: Repository) -> None:
        if not repo.github:
            return
        last = float(self.settings.last_prune_dates.get(repo.path) or 0)
        if last and time.time() - last < 24 * 60 * 60:
            return
        self.settings.last_prune_dates[repo.path] = time.time()
        self.persist_settings()
        default = self.default_branch_name(repo) or "main"
        try:
            prune_merged_branches(repo.path, default, get_branches(repo.path))
        except GitError as exc:
            log.debug("merged branch prune failed: %s", exc)

    def _handle_remote_error(self, repo: Repository, exc: BaseException) -> None:
        if isinstance(exc, GitError):
            if exc.is_push_protection:
                secrets = extract_secret_scanning_results(f"{exc.stderr}\n{exc.stdout}\n{exc}")
                self.show_popup(PopupType.PUSH_PROTECTION_ERROR, error=str(exc), secrets=secrets)
                return
            if exc.is_saml_reauth:
                org = parse_saml_organization(f"{exc.stderr}\n{exc.stdout}\n{exc}") or (
                    repo.github.owner if repo.github else ""
                )
                endpoint = repo.github.endpoint if repo.github else ""
                self.show_popup(
                    PopupType.SAML_REAUTH_REQUIRED,
                    error=str(exc),
                    organization=org,
                    endpoint=endpoint,
                )
                return
            if exc.is_local_changes_overwritten:
                files = overwritten_files_from_error(f"{exc.stderr}\n{exc.stdout}")
                self.show_popup(
                    PopupType.LOCAL_CHANGES_OVERWRITTEN,
                    files=files,
                    retry_kind=self.progress_kind or "checkout",
                    repo_id=repo.id,
                    has_existing_stash=self._has_existing_desktop_stash(repo),
                )
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
        name = branch.name_without_remote if branch.type == BranchType.REMOTE else branch.name
        if has_changes and strategy == UncommittedChangesStrategy.STASH_ON_CURRENT_BRANCH:
            current = status.current_branch if status else "unknown"
            self.stash_and_drop_previous(repo, current or "unknown")
        if has_changes and strategy == UncommittedChangesStrategy.MOVE_TO_NEW_BRANCH:
            self.checkout_and_bring_changes(repo, branch)
            return
        try:
            checkout_branch(repo.path, name)
        except GitError as exc:
            if exc.is_local_changes_overwritten:
                self.show_popup(
                    PopupType.LOCAL_CHANGES_OVERWRITTEN,
                    files=overwritten_files_from_error(f"{exc.stderr}\n{exc.stdout}"),
                    retry_kind="checkout",
                    branch=name,
                    repo_id=repo.id,
                    has_existing_stash=self._has_existing_desktop_stash(repo),
                )
                return
            raise
        self.remember_branch(repo, name)
        self.refresh_repository(repo)

    def stash_and_drop_previous(self, repo: Repository, branch_name: str) -> bool:
        previous = get_last_desktop_stash_entry_for_branch(repo.path, branch_name)
        status = self.state_for(repo).status
        untracked = [
            f for f in (status.working_directory.files if status else []) if f.status.kind == AppFileStatusKind.UNTRACKED
        ]
        created = create_desktop_stash_entry(repo.path, branch_name, untracked_files=untracked)
        if created and previous is not None:
            drop_desktop_stash_entry(repo.path, previous.stash_sha)
        return created

    def _has_existing_desktop_stash(self, repo: Repository) -> bool:
        state = self.state_for(repo)
        branch = state.status.current_branch if state.status else None
        if not branch:
            return False
        return get_last_desktop_stash_entry_for_branch(repo.path, branch) is not None

    def checkout_and_bring_changes(self, repo: Repository, branch: Branch) -> None:
        name = branch.name_without_remote if branch.type == BranchType.REMOTE else branch.name
        try:
            checkout_branch(repo.path, name)
        except GitError as exc:
            if not exc.is_local_changes_overwritten:
                raise
            current = self.state_for(repo).status.current_branch if self.state_for(repo).status else name
            if not self.stash_and_drop_previous(repo, name):
                self.show_popup(
                    PopupType.LOCAL_CHANGES_OVERWRITTEN,
                    files=overwritten_files_from_error(str(exc)),
                    retry_kind="checkout",
                    branch=name,
                    repo_id=repo.id,
                    has_existing_stash=self._has_existing_desktop_stash(repo),
                )
                return
            checkout_branch(repo.path, name)
            entry = get_last_desktop_stash_entry_for_branch(repo.path, name)
            if entry:
                stash_pop(repo.path, entry.name)
        self.remember_branch(repo, name)
        self.refresh_repository(repo)

    def rename_current_branch(self, repo: Repository, old: str, new: str) -> None:
        new = sanitize_ref_name(new)
        rename_branch(repo.path, old, new)
        entry = get_last_desktop_stash_entry_for_branch(repo.path, old)
        if entry:
            move_stash_entry(repo.path, entry, new)
        self.remember_branch(repo, new)
        self.refresh_repository(repo)

    def create_branch_and_checkout(self, repo: Repository, name: str, start_point: str | None = None) -> None:
        name = sanitize_ref_name(name)
        create_branch(repo.path, name, start_point)
        checkout_branch(repo.path, name)
        self.remember_branch(repo, name)
        self.refresh_repository(repo)

    def _capture_undo(self, repo: Repository) -> str | None:
        status = self.state_for(repo).status
        sha = status.current_tip if status else None
        state = self.state_for(repo)
        state.undo_sha = sha
        state.undo_branch = status.current_branch if status else None
        return sha

    def undo_multi_commit(self, repo: Repository) -> None:
        state = self.state_for(repo)
        sha = (self.banner.undo_sha if self.banner else None) or state.undo_sha
        banner_type = self.banner.type if self.banner else None
        if not sha:
            return
        try:
            reset(repo.path, sha, "hard")
        except GitError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return
        undone = {
            BannerType.SUCCESSFUL_CHERRY_PICK: BannerType.CHERRY_PICK_UNDONE,
            BannerType.SUCCESSFUL_SQUASH: BannerType.SQUASH_UNDONE,
            BannerType.SUCCESSFUL_REORDER: BannerType.REORDER_UNDONE,
        }.get(banner_type or BannerType.SUCCESSFUL_MERGE)
        if undone:
            self.show_banner(Banner(undone))
        else:
            self.clear_banner()
        state.undo_sha = None
        self.refresh_repository(repo)

    def merge_branch(self, repo: Repository, branch: str, squash: bool = False, on_done: Callable[..., None] | None = None) -> None:
        undo_sha = self._capture_undo(repo)

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
                kind = MultiCommitOperationKind.SQUASH if squash else MultiCommitOperationKind.MERGE
                self.show_banner(Banner(BannerType.MERGE_CONFLICTS_FOUND, our_branch=self.state_for(repo).status.current_branch if self.state_for(repo).status else None, their_branch=branch, operation_kind=kind.value))
                self.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind=kind,
                    step="conflicts",
                )
            elif merge_result == MergeResult.ALREADY_UP_TO_DATE:
                self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=branch))
            else:
                self.show_banner(Banner(BannerType.SUCCESSFUL_MERGE, their_branch=branch, undo_sha=undo_sha))
            self.refresh_repository(repo)

        self._run(work, done)

    def rebase_branch(self, repo: Repository, base: str, on_done: Callable[..., None] | None = None, on_progress: Callable[..., None] | None = None) -> None:
        undo_sha = self._capture_undo(repo)

        def work() -> tuple:
            commits = get_commits_between(repo.path, base, "HEAD") or []
            progress = self._multi_progress(on_progress)
            return rebase(repo.path, base, progress=progress, commits=commits), get_status(repo.path)

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
                self.show_banner(Banner(BannerType.REBASE_CONFLICTS_FOUND, target_branch=base, operation_kind=MultiCommitOperationKind.REBASE.value))
                self.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind=MultiCommitOperationKind.REBASE, step="conflicts")
            elif rebase_result == RebaseResult.ALREADY_UP_TO_DATE:
                self.show_banner(Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, their_branch=base))
            elif rebase_result == RebaseResult.COMPLETED_WITHOUT_ERROR:
                self.state_for(repo).pending_force_push_before = undo_sha
                self.show_banner(Banner(BannerType.SUCCESSFUL_REBASE, target_branch=base, undo_sha=undo_sha))
            self.refresh_repository(repo)

        self._run(work, done)

    def continue_conflict_operation(
        self,
        repo: Repository,
        kind: MultiCommitOperationKind,
        on_done: Callable[..., None] | None = None,
        on_progress: Callable[..., None] | None = None,
    ) -> None:
        def work() -> tuple:
            progress = self._multi_progress(on_progress)
            if kind == MultiCommitOperationKind.REBASE:
                state = get_rebase_snapshot(repo.path) or {}
                commits = list(state.get("commits") or [])
                if not commits:
                    internal = get_rebase_internal_state(repo.path)
                    if internal:
                        commits = get_commits_between(repo.path, internal.base_branch_tip, internal.original_branch_tip) or []
                return continue_rebase(repo.path, progress=progress, commits=commits), get_status(repo.path)
            if kind == MultiCommitOperationKind.CHERRY_PICK:
                snapshot = get_cherry_pick_snapshot(repo.path)
                commits = list(snapshot["commits"]) if snapshot else []
                return continue_cherry_pick(repo.path, progress=progress, commits=commits), get_status(repo.path)
            files = self.state_for(repo).status.working_directory.files if self.state_for(repo).status else []
            create_merge_commit(repo.path, files)
            return None, get_status(repo.path)

        def done(exc: BaseException | None, result: tuple | None = None) -> None:
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
            elif isinstance(result, tuple) and result[1] is not None:
                self.state_for(repo).status = result[1]
                if kind in {MultiCommitOperationKind.REBASE, MultiCommitOperationKind.SQUASH, MultiCommitOperationKind.REORDER}:
                    self.state_for(repo).pending_force_push_before = self.state_for(repo).undo_sha
            self.refresh_repository(repo)

        self._run(work, done)

    def abort_conflict_operation(self, repo: Repository, kind: MultiCommitOperationKind) -> None:
        if kind == MultiCommitOperationKind.REBASE:
            abort_rebase(repo.path)
        elif kind == MultiCommitOperationKind.CHERRY_PICK:
            abort_cherry_pick(repo.path)
        elif kind == MultiCommitOperationKind.MERGE:
            abort_merge(repo.path)
        self.refresh_repository(repo)

    def cherry_pick_commits(self, repo: Repository, shas: Sequence[str], target_branch: str | None = None, on_done: Callable[..., None] | None = None, on_progress: Callable[..., None] | None = None) -> None:
        undo_sha = self._capture_undo(repo)

        def work() -> tuple:
            if target_branch:
                checkout_branch(repo.path, target_branch)
            commits: list[object] = []
            for sha in shas:
                found = get_commit(repo.path, sha)
                if found is not None:
                    commits.append(found)
                else:
                    commits.append(CommitOneLine(sha=sha, summary=""))
            progress = self._multi_progress(on_progress)
            return cherry_pick(repo.path, shas, progress=progress, commits=commits), get_status(repo.path)

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
                self.show_banner(Banner(BannerType.CHERRY_PICK_CONFLICTS_FOUND, target_branch=target_branch, operation_kind=MultiCommitOperationKind.CHERRY_PICK.value))
                self.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind=MultiCommitOperationKind.CHERRY_PICK, step="conflicts")
            elif cherry_result == CherryPickResult.COMPLETED_WITHOUT_ERROR:
                self.show_banner(Banner(BannerType.SUCCESSFUL_CHERRY_PICK, count=len(shas), target_branch=target_branch, undo_sha=undo_sha))
            self.refresh_repository(repo)

        self._run(work, done)

    def cherry_pick_onto_pull_request(self, repo: Repository, pr: PullRequest, shas: Sequence[str]) -> None:
        """Desktop `startCherryPickWithPullRequest`: drop commits onto a PR row."""
        state = self.state_for(repo)
        current = state.current_pull_request
        if current is not None and current.number == pr.number:
            return

        def work() -> Branch | None:
            return self._find_pull_request_branch(repo, pr)

        def done(exc: BaseException | None, branch: Branch | None = None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
                return
            if branch is None:
                self.show_popup(
                    PopupType.ERROR,
                    error=f"Couldn't find branch '{pr.head_ref}' in the pull request remote.",
                )
                return
            self.cherry_pick_commits(repo, shas, target_branch=branch.name)

        self._run(work, done)

    def set_fork_contribution_target(self, repo: Repository, target: ForkContributionTarget | str) -> None:
        value = target.value if isinstance(target, ForkContributionTarget) else target
        repo.workflow_preferences["fork_target"] = value
        self._save_repositories()
        self.emit()

    def update_existing_upstream_remote(self, repo: Repository, parent_url: str) -> None:
        try:
            set_remote_url(repo.path, "upstream", parent_url)
        except GitError as exc:
            self.show_popup(PopupType.ERROR, error=str(exc))
            return
        self.settings.ignored_upstream_remotes.pop(repo.path, None)
        self.persist_settings()
        self.refresh_repository(repo)

    def ignore_existing_upstream_remote(self, repo: Repository) -> None:
        self.settings.ignored_upstream_remotes[repo.path] = True
        self.persist_settings()

    def convert_repository_to_fork(self, repo: Repository, fork: GitHubRepository) -> None:
        remotes = get_remotes(repo.path)
        origin = next((r for r in remotes if r.name == "origin"), remotes[0] if remotes else None)
        old_url = sanitize_remote_url(origin.url) if origin else (repo.github.clone_url if repo.github else "")
        fork_url = sanitize_remote_url(fork.clone_url)
        if origin:
            set_remote_url(repo.path, origin.name, fork_url)
        else:
            add_remote(repo.path, "origin", fork_url)
        if old_url:
            try:
                add_remote(repo.path, "upstream", old_url)
            except GitError:
                try:
                    set_remote_url(repo.path, "upstream", old_url)
                except GitError as exc:
                    log.debug("could not set upstream after fork: %s", exc)
        if fork.parent is None and repo.github:
            fork.parent = repo.github
        repo.github = fork
        self._save_repositories()
        self.show_popup(PopupType.CHOOSE_FORK_SETTINGS)
        self.refresh_repository(repo)

    def create_fork(self, repo: Repository) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            return

        def work() -> GitHubRepository:
            return GitHubAPI.from_account(account).fork_repository(repo.github.owner, repo.github.name)

        def done(exc: BaseException | None, fork: GitHubRepository | None = None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
                return
            if fork:
                self.convert_repository_to_fork(repo, fork)

        self._run(work, done)

    def retry_last_remote_action(self) -> None:
        action = self._retry_action
        self._retry_action = None
        if not action:
            return
        kind = action.get("kind")
        if kind == "clone":
            self.clone(
                str(action.get("url") or ""),
                str(action.get("path") or ""),
                branch=action.get("branch"),
                tutorial=bool(action.get("tutorial")),
            )
            return
        repo = next((r for r in self.repositories if r.id == action.get("repo_id")), None)
        if not repo:
            return
        if kind == "push":
            self.push_repo(repo, force=bool(action.get("force")))
        elif kind == "pull":
            self.pull_repo(repo)
        else:
            self.fetch_repo(repo)

    def open_stored_notification(self, ident: str) -> None:
        stored = self._notification_payloads.get(ident)
        if not stored:
            return
        popup, payload = stored
        self.show_popup(popup, **payload)

    def begin_sign_in(self, enterprise: bool = False) -> None:
        self.sign_in_error = None
        self.sign_in_existing = None
        if enterprise:
            self.sign_in_step = SignInStep.ENDPOINT_ENTRY
            self.sign_in_endpoint = ""
        else:
            self.sign_in_endpoint = dotcom_endpoint()
            existing = next((a for a in self.accounts if a.is_dotcom), None)
            if existing:
                self.sign_in_step = SignInStep.EXISTING_ACCOUNT_WARNING
                self.sign_in_existing = existing
            else:
                self.sign_in_step = SignInStep.AUTHENTICATION
        self.show_popup(PopupType.SIGN_IN, enterprise=enterprise)

    def continue_existing_account_warning(self) -> None:
        """Leave `ExistingAccountWarning` and continue to browser authentication."""
        self.sign_in_step = SignInStep.AUTHENTICATION
        self.sign_in_error = None

    def set_sign_in_endpoint(self, url: str) -> None:
        try:
            self.sign_in_endpoint = enterprise_endpoint_from_url(url)
            existing = next((a for a in self.accounts if a.endpoint == self.sign_in_endpoint), None)
            if existing:
                self.sign_in_step = SignInStep.EXISTING_ACCOUNT_WARNING
                self.sign_in_existing = existing
            else:
                self.sign_in_step = SignInStep.AUTHENTICATION
                self.sign_in_existing = None
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
                    self.retry_last_remote_action()
            except Exception as exc:
                self.sign_in_error = str(exc)
            self.emit()

        threading.Thread(target=thread, daemon=True).start()

    def _add_account(self, account: Account) -> None:
        if self.sign_in_existing and self.sign_in_existing.endpoint == account.endpoint:
            self.sign_out(self.sign_in_existing)
            self.sign_in_existing = None
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
                self._pending_open_action = action
                self.select_repository(existing.id)
                if not existing.is_missing:
                    # refresh is kicked off by select_repository; finish in _finish_pending_open
                    pass
                return
        default_dir = self.settings.clone_default_directory or str(Path.home() / "Documents" / "GitHub")
        name = parsed.name if parsed else "repository"
        self.show_popup(PopupType.CLONE_REPOSITORY, initial_url=url, path=os.path.join(default_dir, name), branch=action.branch)

    def _finish_pending_open(self, repo: Repository) -> None:
        action = self._pending_open_action
        if action is None:
            state = self.state_for(repo)
            if state.pending_pr:
                action = OpenRepositoryAction(url="", pr=str(state.pending_pr), filepath=state.pending_filepath)
                state.pending_pr = None
            elif state.pending_filepath:
                action = OpenRepositoryAction(url="", filepath=state.pending_filepath)
            else:
                return
        self._pending_open_action = None
        state = self.state_for(repo)
        state.pending_filepath = None
        state.pending_pr = None
        if action.pr:
            try:
                number = int(action.pr)
            except (TypeError, ValueError):
                number = 0
            pr = next((p for p in state.pull_requests if p.number == number), None)
            if pr is None and repo.github:
                account = self.account_for_repo(repo)
                if account:
                    try:
                        pr = GitHubAPI.from_account(account).fetch_pull_request(repo.github.owner, repo.github.name, number)
                    except APIError:
                        pr = None
            if pr:
                self.checkout_pull_request(repo, pr)
            elif action.branch:
                try:
                    checkout_branch(repo.path, action.branch)
                    self.refresh_repository(repo)
                except GitError:
                    pass
        elif action.branch:
            try:
                checkout_branch(repo.path, action.branch)
                self.refresh_repository(repo)
            except GitError:
                pass
        if action.filepath:
            self.set_section(RepositorySectionTab.CHANGES)
            full = os.path.normpath(os.path.join(repo.path, action.filepath))
            if not full.startswith(os.path.normpath(repo.path)):
                return
            file = None
            if state.status:
                file = next((f for f in state.status.working_directory.files if f.path == action.filepath), None)
            if file:
                self.select_file(repo, file)
            elif os.path.exists(full):
                self.open_in_editor(repo, full)

    def open_in_shell(self, repo: Repository) -> None:
        if self.settings.use_custom_shell and self.settings.custom_shell_path:
            argv = command_for_custom_integration(
                self.settings.custom_shell_path,
                self.settings.custom_shell_args,
                repo.path,
            )
            try:
                open_custom_shell(argv[0], argv[1:], repo.path)
            except OSError as exc:
                self.show_popup(PopupType.OPEN_SHELL_FAILED, message=str(exc))
            return
        shell = find_shell(self.settings.selected_shell)
        if not shell:
            self.show_popup(PopupType.OPEN_SHELL_FAILED, message="No terminal emulator found")
            return
        open_shell(shell, repo.path)

    def open_in_editor(self, repo: Repository, path: str | None = None) -> None:
        target = path or repo.path
        if self.settings.use_custom_editor and self.settings.custom_editor_path:
            argv = command_for_custom_integration(
                self.settings.custom_editor_path,
                self.settings.custom_editor_args,
                target,
            )
            editor = Editor("Custom", argv[0], tuple(argv[1:]))
            open_in_editor(editor, target, append_path=False)
            return
        editor = find_editor(self.settings.selected_external_editor)
        if not editor:
            self.show_popup(PopupType.EXTERNAL_EDITOR_FAILED, message="No external editor found")
            return
        open_in_editor(editor, target)

    def open_working_directory(self, repo: Repository) -> None:
        open_file_manager(repo.path)

    def show_github_explore(self, repo: Repository | None = None) -> None:
        repo = repo or self.selected_repository
        if repo and repo.github and repo.github.html_url:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(repo.github.html_url)
            open_external(urlunparse((parsed.scheme, parsed.netloc, "/explore", "", "", "")))
            return
        open_external("https://github.com/explore")

    def view_on_github(self, repo: Repository) -> None:
        gh = github_for_contribution(repo) or repo.github
        if gh:
            open_external(gh.html_url)

    def create_issue(self, repo: Repository) -> None:
        gh = github_for_contribution(repo) or repo.github
        if gh:
            open_external(gh.html_url + "/issues/new")

    def compare_on_github(self, repo: Repository) -> None:
        state = self.state_for(repo)
        branch = state.status.current_branch if state.status else None
        gh = github_for_contribution(repo) or repo.github
        if gh and branch:
            open_external(f"{gh.html_url}/compare/{branch}")

    def open_pull_request(self, repo: Repository) -> None:
        state = self.state_for(repo)
        if state.current_pull_request:
            open_external(state.current_pull_request.html_url)
            return
        self._create_pull_request_flow(repo, preview=False)

    def preview_pull_request(self, repo: Repository) -> None:
        self._create_pull_request_flow(repo, preview=True)

    def open_create_pull_request_in_browser(self, repo: Repository, base_branch: str | None = None) -> None:
        """Desktop `_openCreatePullRequestInBrowser`: open `{htmlURL}/pull/new/{compare}`."""
        from urllib.parse import quote

        gh = repo.github
        if not gh:
            return
        state = self.state_for(repo)
        compare_branch = (state.status.current_branch if state.status else None) or ""
        parent = gh.parent
        is_fork_parent = bool(repo.is_fork and parent and fork_contribution_target(repo) == ForkContributionTarget.PARENT)
        base_fork_preface = f"{parent.owner}:{parent.name}:" if is_fork_parent and parent else ""
        encoded_base = ""
        if base_branch:
            encoded_base = base_fork_preface + quote(base_branch, safe="") + "..."
        compare_fork_preface = f"{gh.owner}:{gh.name}:" if is_fork_parent else ""
        encoded_compare = compare_fork_preface + quote(compare_branch, safe="")
        open_external(f"{gh.html_url}/pull/new/{encoded_base}{encoded_compare}")

    def _after_push_for_pull_request(self, repo: Repository, preview: bool) -> None:
        if preview:
            self.show_popup(PopupType.START_PULL_REQUEST)
        else:
            self.open_create_pull_request_in_browser(repo)

    def _create_pull_request_flow(self, repo: Repository, preview: bool = False) -> None:
        state = self.state_for(repo)
        ahead_behind = state.ahead_behind
        continue_pr = lambda: self._after_push_for_pull_request(repo, preview)
        if ahead_behind is None:
            self.show_popup(
                PopupType.PUSH_BRANCH_COMMITS,
                unpublished=True,
                on_confirm=lambda: self.push_repo(repo, on_success=continue_pr),
            )
            return
        if ahead_behind.ahead > 0:
            self.show_popup(
                PopupType.PUSH_BRANCH_COMMITS,
                unpublished=False,
                unpushed=ahead_behind.ahead,
                on_confirm=lambda: self.push_repo(repo, on_success=continue_pr),
                on_skip=continue_pr,
            )
            return
        continue_pr()

    def create_pull_request(self, repo: Repository, title: str, base: str, body: str = "", draft: bool = False) -> None:
        account = self.account_for_repo(repo)
        if not account or not repo.github:
            return
        state = self.state_for(repo)
        head = state.status.current_branch if state.status else None
        if not head:
            return
        target = github_for_contribution(repo) or repo.github
        if target.owner != repo.github.owner:
            head = f"{repo.github.owner}:{head}"
        api = GitHubAPI.from_account(account)
        pr = api.create_pull_request(target.owner, target.name, title, head, base, body, draft)
        open_external(pr.html_url)
        self.refresh_repository(repo)

    def generate_commit_message(self, repo: Repository) -> None:
        def work() -> tuple[str, str]:
            account = self.account_for_repo(repo)
            if not account:
                raise CopilotError("Sign in to GitHub to generate a commit message")
            state = self.state_for(repo)
            files = [f for f in (state.status.working_directory.files if state.status else []) if f.include]
            commitish = None
            if state.commit_to_amend:
                commitish = f"{state.commit_to_amend.sha}^"
            diff_text = get_files_diff_text(repo.path, files, commitish)
            api = GitHubAPI.from_account(account)
            return api.generate_commit_message(diff_text, [f.path for f in files])

        def done(exc: BaseException | None, result: tuple[str, str] | None = None) -> None:
            if exc:
                self.show_popup(PopupType.ERROR, error=str(exc))
                return
            if result:
                self.state_for(repo).commit_message = CommitMessage(
                    summary=result[0],
                    description=result[1],
                    timestamp=int(time.time() * 1000),
                    generated_by_copilot=True,
                )
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

    def _multi_progress(self, callback: Callable[..., None] | None):
        if callback is None:
            return None

        def on_event(event: object) -> None:
            def go() -> bool:
                try:
                    callback(event)
                except Exception:
                    pass
                return False

            invoked = False
            try:
                from gi.repository import Gio, GLib

                if Gio.Application.get_default() is not None:
                    GLib.idle_add(go)
                    invoked = True
            except Exception:
                invoked = False
            if not invoked:
                go()

        return on_event

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

    def poll_commit_status(self, repo: Repository | None = None) -> None:
        """Desktop `subscribeToCommitStatus` / `CIStatus`: refresh tip and open PR heads."""
        repo = repo or self.selected_repository
        if not repo or not repo.github:
            return
        account = self.account_for_repo(repo)
        if not account:
            return
        state = self.state_for(repo)
        sha = (state.status.current_tip if state.status else None) or (state.commits[0].sha if state.commits else None)
        if not sha:
            return
        owner, name = repo.github.owner, repo.github.name
        prs = [pr for pr in state.pull_requests if pr.head_sha][:15]

        def work() -> dict:
            api = GitHubAPI.from_account(account)
            runs_by_ref: dict[str, list] = {}
            runs_by_ref[sha] = api.fetch_check_runs(owner, name, sha)
            pr_status: dict[int, str] = {}
            for pr in prs:
                ref = pr.head_sha
                if ref not in runs_by_ref:
                    try:
                        runs_by_ref[ref] = api.fetch_check_runs(owner, name, ref)
                    except Exception:
                        runs_by_ref[ref] = []
                pr_status[pr.number] = summarize_check_runs(runs_by_ref.get(ref) or [])
            return {"tip": sha, "runs": runs_by_ref, "pr_status": pr_status}

        def done(exc: BaseException | None, payload: dict | None = None) -> None:
            if exc or not payload:
                return
            view = self.state_for(repo)
            view.check_runs = payload["runs"].get(payload["tip"]) or []
            view.pr_check_status = payload.get("pr_status") or {}
            self.emit()

        self._run(work, done)

    def poll_notifications(self) -> None:
        if not self.settings.notifications_enabled or not self.accounts:
            return
        repo = self.selected_repository
        selected_full = repo.github.full_name if repo and repo.github else None
        if not selected_full:
            return
        account = self.account_for_repo(repo) if repo else None
        if account is None:
            account = self.accounts[0]

        def work() -> list:
            api = GitHubAPI.from_account(account)
            try:
                api.get_alive_websocket_url()
            except Exception:
                pass
            notes = api.fetch_notifications()
            enriched: list[tuple[dict, dict | None]] = []
            for note in notes[:20]:
                if not is_high_signal_notification(note, selected_full):
                    continue
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
            for note, payload in result:
                ident = str(note.get("id") or "")
                if not ident or ident in self._seen_notifications:
                    continue
                self._seen_notifications.add(ident)
                action = classify_notification(note, payload)
                nid = ident
                if action.popup:
                    self._notification_payloads[nid] = (action.popup, dict(action.payload))
                show_notification(action.title, action.body, enabled=True, notification_id=nid)
                # Desktop opens popups from notification clicks, not automatically.

        self._run(work, done)

    def check_thank_you(self) -> None:
        account = next((a for a in self.accounts if a.is_dotcom), None)
        if account is None:
            return
        login = account.login
        version = current_app_version()
        if has_user_already_been_checked_or_thanked(
            self.settings.last_thank_you_version,
            list(self.settings.last_thank_you_users),
            login,
            version,
        ):
            return
        contributions = get_user_contributions(login)
        if not contributions:
            self._remember_thank_you(login, version)
            return
        already = login in self.settings.last_thank_you_users
        self.show_banner(
            Banner(
                BannerType.OPEN_THANK_YOU_CARD,
                friendly_name=account.name or login,
                contributions=contributions,
                latest_version=version if already else None,
            )
        )

    def open_thank_you_card(self) -> None:
        banner = self.banner
        name = banner.friendly_name if banner else ""
        contributions = list(banner.contributions) if banner else []
        latest = banner.latest_version if banner else None
        self.clear_banner()
        login = self.accounts[0].login if self.accounts else ""
        self._remember_thank_you(login, current_app_version())
        self.show_popup(
            PopupType.THANK_YOU,
            friendly_name=name or login,
            contributions=contributions,
            latest_version=latest,
        )

    def _remember_thank_you(self, login: str, version: str) -> None:
        if self.settings.last_thank_you_version != version:
            self.settings.last_thank_you_users = []
        self.settings.last_thank_you_version = version
        if login and login not in self.settings.last_thank_you_users:
            self.settings.last_thank_you_users.append(login)
        self.persist_settings()

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
            parsed = parse_remote(clone_url)
            default_dir = self.settings.clone_default_directory or str(Path.home() / "Documents" / "GitHub")
            name = parsed.name if parsed else "repository"
            self.show_popup(
                PopupType.CLONE_REPOSITORY,
                initial_url=clone_url,
                branch=clone_branch,
                path=os.path.join(default_dir, name),
            )


def _commits_are_contiguous(selected_newest_first: Sequence[Commit], history_newest_first: Sequence[Commit]) -> bool:
    if len(selected_newest_first) <= 1:
        return True
    sha_set = {c.sha for c in selected_newest_first}
    indexes = [i for i, commit in enumerate(history_newest_first) if commit.sha in sha_set]
    if len(indexes) != len(selected_newest_first):
        return False
    return indexes[-1] - indexes[0] + 1 == len(indexes)
