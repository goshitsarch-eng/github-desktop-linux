"""Domain models matching GitHub Desktop's TypeScript models."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, IntEnum, StrEnum
from typing import Any, Iterable, Iterator, Sequence


class AppFileStatusKind(StrEnum):
    NEW = "New"
    MODIFIED = "Modified"
    DELETED = "Deleted"
    COPIED = "Copied"
    RENAMED = "Renamed"
    CONFLICTED = "Conflicted"
    UNTRACKED = "Untracked"


class GitStatusEntry(StrEnum):
    MODIFIED = "M"
    ADDED = "A"
    DELETED = "D"
    RENAMED = "R"
    COPIED = "C"
    UNCHANGED = "."
    UNTRACKED = "?"
    IGNORED = "!"
    UPDATED_BUT_UNMERGED = "U"


class UnmergedEntrySummary(StrEnum):
    BOTH_ADDED = "BothAdded"
    BOTH_MODIFIED = "BothModified"
    BOTH_DELETED = "BothDeleted"
    ADDED_BY_US = "AddedByUs"
    ADDED_BY_THEM = "AddedByThem"
    DELETED_BY_US = "DeletedByUs"
    DELETED_BY_THEM = "DeletedByThem"


class DiffSelectionType(StrEnum):
    ALL = "All"
    PARTIAL = "Partial"
    NONE = "None"


class DiffType(StrEnum):
    TEXT = "Text"
    IMAGE = "Image"
    BINARY = "Binary"
    SUBMODULE = "Submodule"
    LARGE_TEXT = "LargeText"
    UNRENDERABLE = "Unrenderable"


class DiffLineType(StrEnum):
    ADD = "Add"
    DELETE = "Delete"
    CONTEXT = "Context"
    HUNK = "Hunk"


class ImageDiffType(StrEnum):
    TWO_UP = "TwoUp"
    SWIPE = "Swipe"
    ONION = "OnionSkin"
    DIFFERENCE = "Difference"


class ChangesListFilter(StrEnum):
    ALL = "All"
    INCLUDED = "Included"
    EXCLUDED = "Excluded"


class TipState(StrEnum):
    UNKNOWN = "Unknown"
    UNBORN = "Unborn"
    DETACHED = "Detached"
    VALID = "Valid"


class BranchType(StrEnum):
    LOCAL = "Local"
    REMOTE = "Remote"


class RepositorySectionTab(StrEnum):
    CHANGES = "Changes"
    HISTORY = "History"


class HistoryTabMode(StrEnum):
    HISTORY = "History"
    COMPARE = "Compare"


class FoldoutType(StrEnum):
    REPOSITORY = "Repository"
    BRANCH = "Branch"
    APP_MENU = "AppMenu"
    ADD_MENU = "AddMenu"
    PUSH_PULL = "PushPull"


class SelectionType(StrEnum):
    REPOSITORY = "Repository"
    CLONING = "CloningRepository"
    MISSING = "MissingRepository"


class PopupType(StrEnum):
    RENAME_BRANCH = "RenameBranch"
    DELETE_BRANCH = "DeleteBranch"
    DELETE_REMOTE_BRANCH = "DeleteRemoteBranch"
    CONFIRM_DISCARD_CHANGES = "ConfirmDiscardChanges"
    PREFERENCES = "Preferences"
    REPOSITORY_SETTINGS = "RepositorySettings"
    ADD_REPOSITORY = "AddRepository"
    CREATE_REPOSITORY = "CreateRepository"
    CLONE_REPOSITORY = "CloneRepository"
    CREATE_BRANCH = "CreateBranch"
    SIGN_IN = "SignIn"
    ABOUT = "About"
    INSTALL_GIT = "InstallGit"
    PUBLISH_REPOSITORY = "PublishRepository"
    ACKNOWLEDGEMENTS = "Acknowledgements"
    UNTRUSTED_CERTIFICATE = "UntrustedCertificate"
    REMOVE_REPOSITORY = "RemoveRepository"
    TERMS_AND_CONDITIONS = "TermsAndConditions"
    PUSH_BRANCH_COMMITS = "PushBranchCommits"
    CLI_INSTALLED = "CLIInstalled"
    GENERIC_GIT_AUTHENTICATION = "GenericGitAuthentication"
    EXTERNAL_EDITOR_FAILED = "ExternalEditorFailed"
    OPEN_SHELL_FAILED = "OpenShellFailed"
    INITIALIZE_LFS = "InitializeLFS"
    LFS_ATTRIBUTE_MISMATCH = "LFSAttributeMismatch"
    UPSTREAM_ALREADY_EXISTS = "UpstreamAlreadyExists"
    RELEASE_NOTES = "ReleaseNotes"
    DELETE_PULL_REQUEST = "DeletePullRequest"
    OVERSIZED_FILES = "OversizedFiles"
    COMMIT_CONFLICTS_WARNING = "CommitConflictsWarning"
    PUSH_NEEDS_PULL = "PushNeedsPull"
    CONFIRM_FORCE_PUSH = "ConfirmForcePush"
    STASH_AND_SWITCH_BRANCH = "StashAndSwitchBranch"
    CONFIRM_OVERWRITE_STASH = "ConfirmOverwriteStash"
    CONFIRM_DISCARD_STASH = "ConfirmDiscardStash"
    CONFIRM_CHECKOUT_COMMIT = "ConfirmCheckoutCommit"
    CREATE_TUTORIAL_REPOSITORY = "CreateTutorialRepository"
    CONFIRM_EXIT_TUTORIAL = "ConfirmExitTutorial"
    PUSH_REJECTED_WORKFLOW_SCOPE = "PushRejectedDueToMissingWorkflowScope"
    SAML_REAUTH_REQUIRED = "SAMLReauthRequired"
    CREATE_FORK = "CreateFork"
    CREATE_TAG = "CreateTag"
    DELETE_TAG = "DeleteTag"
    LOCAL_CHANGES_OVERWRITTEN = "LocalChangesOverwritten"
    CHOOSE_FORK_SETTINGS = "ChooseForkSettings"
    CONFIRM_DISCARD_SELECTION = "ConfirmDiscardSelection"
    CHANGE_REPOSITORY_ALIAS = "ChangeRepositoryAlias"
    THANK_YOU = "ThankYou"
    COMMIT_MESSAGE = "CommitMessage"
    MULTI_COMMIT_OPERATION = "MultiCommitOperation"
    WARN_LOCAL_CHANGES_BEFORE_UNDO = "WarnLocalChangesBeforeUndo"
    WARNING_BEFORE_RESET = "WarningBeforeReset"
    INVALIDATED_TOKEN = "InvalidatedToken"
    ADD_SSH_HOST = "AddSSHHost"
    SSH_KEY_PASSPHRASE = "SSHKeyPassphrase"
    SSH_USER_PASSWORD = "SSHUserPassword"
    PULL_REQUEST_CHECKS_FAILED = "PullRequestChecksFailed"
    CI_CHECK_RUN_RERUN = "CICheckRunRerun"
    WARN_FORCE_PUSH = "WarnForcePush"
    DISCARD_CHANGES_RETRY = "DiscardChangesRetry"
    PULL_REQUEST_REVIEW = "PullRequestReview"
    UNREACHABLE_COMMITS = "UnreachableCommits"
    START_PULL_REQUEST = "StartPullRequest"
    ERROR = "Error"
    INSTALLING_UPDATE = "InstallingUpdate"
    PULL_REQUEST_COMMENT = "PullRequestComment"
    UNKNOWN_AUTHORS = "UnknownAuthors"
    CONFIRM_COMMIT_FILTERED_CHANGES = "ConfirmCommitFilteredChanges"
    PUSH_PROTECTION_ERROR = "PushProtectionError"
    BYPASS_PUSH_PROTECTION = "BypassPushProtection"
    GENERATE_COMMIT_MESSAGE_OVERRIDE = "GenerateCommitMessageOverrideWarning"
    GENERATE_COMMIT_MESSAGE_DISCLAIMER = "GenerateCommitMessageDisclaimer"


class BannerType(StrEnum):
    SUCCESSFUL_MERGE = "SuccessfulMerge"
    MERGE_CONFLICTS_FOUND = "MergeConflictsFound"
    SUCCESSFUL_REBASE = "SuccessfulRebase"
    REBASE_CONFLICTS_FOUND = "RebaseConflictsFound"
    BRANCH_ALREADY_UP_TO_DATE = "BranchAlreadyUpToDate"
    SUCCESSFUL_CHERRY_PICK = "SuccessfulCherryPick"
    CHERRY_PICK_CONFLICTS_FOUND = "CherryPickConflictsFound"
    CHERRY_PICK_UNDONE = "CherryPickUndone"
    SQUASH_UNDONE = "SquashUndone"
    REORDER_UNDONE = "ReorderUndone"
    SUCCESSFUL_SQUASH = "SuccessfulSquash"
    SUCCESSFUL_REORDER = "SuccessfulReorder"
    CONFLICTS_FOUND = "ConflictsFound"
    OS_VERSION_NO_LONGER_SUPPORTED = "OSVersionNoLongerSupported"


class MultiCommitOperationKind(StrEnum):
    REBASE = "Rebase"
    CHERRY_PICK = "Cherry-pick"
    SQUASH = "Squash"
    MERGE = "Merge"
    REORDER = "Reorder"


class MergeMethod(StrEnum):
    MERGE = "merge"
    SQUASH = "squash"
    REBASE = "rebase"


class UncommittedChangesStrategy(StrEnum):
    ASK_FOR_CONFIRMATION = "AskForConfirmation"
    STASH_ON_CURRENT_BRANCH = "StashOnCurrentBranch"
    MOVE_TO_NEW_BRANCH = "MoveToNewBranch"


class ApplicationTheme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


class PreferencesTab(StrEnum):
    ACCOUNTS = "Accounts"
    INTEGRATIONS = "Integrations"
    GIT = "Git"
    APPEARANCE = "Appearance"
    NOTIFICATIONS = "Notifications"
    PROMPTS = "Prompts"
    ADVANCED = "Advanced"
    ACCESSIBILITY = "Accessibility"


class RepositorySettingsTab(StrEnum):
    REMOTE = "Remote"
    IGNORED_FILES = "IgnoredFiles"
    GIT_CONFIG = "GitConfig"
    FORK_SETTINGS = "ForkSettings"


class CloneRepositoryTab(StrEnum):
    DOTCOM = "DotCom"
    ENTERPRISE = "Enterprise"
    URL = "URL"


class SignInStep(StrEnum):
    ENDPOINT_ENTRY = "EndpointEntry"
    EXISTING_ACCOUNT_WARNING = "ExistingAccountWarning"
    AUTHENTICATION = "Authentication"
    SUCCESS = "Success"


class WelcomeStep(StrEnum):
    START = "Start"
    SIGN_IN_DOTCOM = "SignInToDotComWithBrowser"
    SIGN_IN_ENTERPRISE = "SignInToEnterprise"
    CONFIGURE_GIT = "ConfigureGit"


class TutorialStep(StrEnum):
    NOT_APPLICABLE = "NotApplicable"
    PICK_EDITOR = "PickEditor"
    CREATE_BRANCH = "CreateBranch"
    EDIT_FILE = "EditFile"
    MAKE_COMMIT = "MakeCommit"
    PUSH_BRANCH = "PushBranch"
    OPEN_PULL_REQUEST = "OpenPullRequest"
    ALL_COMPLETE = "AllComplete"
    PAUSED = "Paused"


class FetchType(StrEnum):
    BACKGROUND_TASK = "BackgroundTask"
    USER_INITIATED = "UserInitiatedTask"


class RebaseResult(StrEnum):
    COMPLETED_WITHOUT_ERROR = "CompletedWithoutError"
    ALREADY_UP_TO_DATE = "AlreadyUpToDate"
    CONFLICTS_ENCOUNTERED = "ConflictsEncountered"
    OUTSTANDING_FILES_NOT_STAGED = "OutstandingFilesNotStaged"
    ERROR = "Error"
    ABORTED = "Aborted"


class CherryPickResult(StrEnum):
    COMPLETED_WITHOUT_ERROR = "CompletedWithoutError"
    CONFLICTS_ENCOUNTERED = "ConflictsEncountered"
    OUTSTANDING_FILES_NOT_STAGED = "OutstandingFilesNotStaged"
    ABORTED = "Aborted"
    UNABLE_TO_START = "UnableToStart"
    ERROR = "Error"


class MergeResult(StrEnum):
    SUCCESS = "Success"
    ALREADY_UP_TO_DATE = "AlreadyUpToDate"
    FAILED = "Failed"


class ManualConflictResolution(StrEnum):
    OURS = "ours"
    THEIRS = "theirs"


class ForkContributionTarget(StrEnum):
    PARENT = "Parent"
    SELF = "Self"


class BypassReason(StrEnum):
    FALSE_POSITIVE = "false_positive"
    USED_IN_TESTS = "used_in_tests"
    WILL_FIX_LATER = "will_fix_later"


class DragType(StrEnum):
    COMMIT = "Commit"
    STASH = "Stash"
    INSERTION_POINT = "InsertionPoint"


class StashedChangesLoadStates(StrEnum):
    NOT_LOADED = "NotLoaded"
    LOADING = "Loading"
    LOADED = "Loaded"


class CheckStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PENDING = "pending"
    NEUTRAL = "neutral"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"


DEFAULT_UNCOMMITTED_STRATEGY = UncommittedChangesStrategy.ASK_FOR_CONFIRMATION
DEFAULT_BRANCH_NAME = "main"
MAX_DIFF_BUFFER_SIZE = 70_000_000
MAX_REASONABLE_DIFF_SIZE = MAX_DIFF_BUFFER_SIZE // 16
MAX_CHARACTERS_PER_LINE = 5000
OVERSIZED_FILE_BYTES = 100 * 1024 * 1024
DESKTOP_STASH_MARKER = "!!GitHub_Desktop"
IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".bmp",
    ".avif",
    ".dds",
}


class DiffSelection:
    """Line-level include/exclude selection for a working-directory file."""

    def __init__(
        self,
        default_selection: DiffSelectionType = DiffSelectionType.ALL,
        diverging: set[int] | None = None,
        selectable: set[int] | None = None,
    ) -> None:
        self.default_selection_type = default_selection
        self._diverging = set(diverging or ())
        self._selectable = set(selectable) if selectable is not None else None

    @classmethod
    def from_initial_selection(cls, selection: DiffSelectionType) -> "DiffSelection":
        if selection == DiffSelectionType.PARTIAL:
            raise ValueError("Partial is not a valid initial selection")
        return cls(selection)

    def get_selection_type(self) -> DiffSelectionType:
        if not self._diverging:
            return self.default_selection_type
        if self._selectable is not None and self._diverging == self._selectable:
            return (
                DiffSelectionType.ALL
                if self.default_selection_type == DiffSelectionType.NONE
                else DiffSelectionType.NONE
            )
        return DiffSelectionType.PARTIAL

    def is_selectable(self, index: int) -> bool:
        return self._selectable is None or index in self._selectable

    def is_selected(self, index: int) -> bool:
        selected_by_default = self.default_selection_type == DiffSelectionType.ALL
        diverging = index in self._diverging
        return selected_by_default != diverging

    def with_line_selection(self, index: int, selected: bool) -> "DiffSelection":
        currently = self.is_selected(index)
        if currently == selected or not self.is_selectable(index):
            return self
        diverging = set(self._diverging)
        if index in diverging:
            diverging.remove(index)
        else:
            diverging.add(index)
        return DiffSelection(self.default_selection_type, diverging, self._selectable)

    def with_range_selection(self, from_index: int, length: int, selected: bool) -> "DiffSelection":
        current = self
        for i in range(from_index, from_index + length):
            current = current.with_line_selection(i, selected)
        return current

    def with_select_all(self) -> "DiffSelection":
        return DiffSelection(DiffSelectionType.ALL, None, self._selectable)

    def with_select_none(self) -> "DiffSelection":
        return DiffSelection(DiffSelectionType.NONE, None, self._selectable)

    def with_selectable_lines(self, selectable: Iterable[int]) -> "DiffSelection":
        return DiffSelection(self.default_selection_type, set(self._diverging), set(selectable))

    def selected_lines(self, line_count: int) -> list[int]:
        return [i for i in range(line_count) if self.is_selected(i)]


@dataclass(frozen=True)
class SubmoduleStatus:
    commit_changed: bool = False
    modified_changes: bool = False
    untracked_changes: bool = False


@dataclass
class FileStatus:
    kind: AppFileStatusKind
    old_path: str | None = None
    rename_includes_modifications: bool = False
    conflict_marker_count: int | None = None
    unmerged_action: UnmergedEntrySummary | None = None
    us: GitStatusEntry | None = None
    them: GitStatusEntry | None = None
    submodule_status: SubmoduleStatus | None = None

    @property
    def is_conflicted(self) -> bool:
        return self.kind == AppFileStatusKind.CONFLICTED

    @property
    def has_conflict_markers(self) -> bool:
        return self.is_conflicted and self.conflict_marker_count is not None


@dataclass
class WorkingDirectoryFileChange:
    path: str
    status: FileStatus
    selection: DiffSelection = field(
        default_factory=lambda: DiffSelection.from_initial_selection(DiffSelectionType.ALL)
    )

    def __post_init__(self) -> None:
        if isinstance(self.selection, DiffSelectionType):
            object.__setattr__(
                self, "selection", DiffSelection.from_initial_selection(self.selection)
            )

    @property
    def include(self) -> bool:
        return self.selection.get_selection_type() != DiffSelectionType.NONE

    def with_include(self, include: bool) -> "WorkingDirectoryFileChange":
        selection = self.selection.with_select_all() if include else self.selection.with_select_none()
        return replace(self, selection=selection)

    def with_selection(self, selection: DiffSelection) -> "WorkingDirectoryFileChange":
        return replace(self, selection=selection)


@dataclass
class CommittedFileChange:
    path: str
    status: FileStatus
    commitish: str
    parent_commitish: str | None = None


COMMIT_BATCH_SIZE = 100
NULL_TREE_SHA = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


@dataclass
class ChangesetData:
    """Files and line stats for a commit or commit range (Desktop IChangesetData)."""

    files: list[CommittedFileChange] = field(default_factory=list)
    lines_added: int = 0
    lines_deleted: int = 0


@dataclass
class WorkingDirectoryStatus:
    files: list[WorkingDirectoryFileChange] = field(default_factory=list)
    include_all: bool | None = True

    @classmethod
    def from_files(cls, files: Sequence[WorkingDirectoryFileChange]) -> "WorkingDirectoryStatus":
        include_all: bool | None = True
        if not files:
            include_all = True
        elif all(f.selection.get_selection_type() == DiffSelectionType.ALL for f in files):
            include_all = True
        elif all(f.selection.get_selection_type() == DiffSelectionType.NONE for f in files):
            include_all = False
        else:
            include_all = None
        return cls(list(files), include_all)

    def with_include_all_files(self, include_all: bool) -> "WorkingDirectoryStatus":
        files = [f.with_include(include_all) for f in self.files]
        return WorkingDirectoryStatus(files, include_all)

    def find_file(self, path: str) -> WorkingDirectoryFileChange | None:
        for f in self.files:
            if f.path == path:
                return f
        return None


@dataclass
class AheadBehind:
    ahead: int = 0
    behind: int = 0


@dataclass
class IStatusResult:
    exists: bool = True
    current_branch: str | None = None
    current_upstream_branch: str | None = None
    current_tip: str | None = None
    branch_ahead_behind: AheadBehind | None = None
    working_directory: WorkingDirectoryStatus = field(default_factory=WorkingDirectoryStatus)
    merge_head_found: bool = False
    squash_msg_found: bool = False
    rebase_internal_state: RebaseInternalState | None = None
    is_cherry_picking_head_found: bool = False
    do_conflicted_files_exist: bool = False


@dataclass
class RebaseInternalState:
    target_branch: str
    base_branch_tip: str
    original_branch_tip: str


class DiffHunkExpansionType(StrEnum):
    NONE = "None"
    UP = "Up"
    DOWN = "Down"
    SHORT = "Short"
    BOTH = "Both"


@dataclass
class DiffHunkHeader:
    old_start_line: int
    old_line_count: int
    new_start_line: int
    new_line_count: int

    def to_diff_line(self) -> str:
        return f"@@ -{self.old_start_line},{self.old_line_count} +{self.new_start_line},{self.new_line_count} @@"


@dataclass
class DiffLine:
    text: str
    kind: DiffLineType
    old_line_number: int | None
    new_line_number: int | None
    no_trailing_newline: bool = False
    diff_line_number: int | None = None

    @property
    def selectable(self) -> bool:
        return self.kind in (DiffLineType.ADD, DiffLineType.DELETE)


@dataclass
class DiffHunk:
    header: DiffHunkHeader
    lines: list[DiffLine]
    unified_diff_start: int
    unified_diff_end: int
    expansion_type: DiffHunkExpansionType = DiffHunkExpansionType.NONE


@dataclass
class TextDiff:
    kind: DiffType = DiffType.TEXT
    text: str = ""
    hunks: list[DiffHunk] = field(default_factory=list)
    line_endings_change: tuple[str, str] | None = None
    max_line_number: int = 0
    has_hidden_bidi_chars: bool = False
    is_binary: bool = False
    # 1-based line number → Pango markup from the full old/new file (Desktop highlightContents)
    old_line_markup: dict[int, str] = field(default_factory=dict)
    new_line_markup: dict[int, str] = field(default_factory=dict)


@dataclass
class ImageDiff:
    kind: DiffType = DiffType.IMAGE
    previous: bytes | None = None
    current: bytes | None = None
    previous_media_type: str | None = None
    current_media_type: str | None = None


@dataclass
class BinaryDiff:
    kind: DiffType = DiffType.BINARY


@dataclass
class SubmoduleDiff:
    kind: DiffType = DiffType.SUBMODULE
    full_path: str = ""
    path: str = ""
    status: SubmoduleStatus | None = None
    old_sha: str | None = None
    new_sha: str | None = None
    url: str | None = None


@dataclass
class LargeTextDiff:
    kind: DiffType = DiffType.LARGE_TEXT
    text: str = ""


@dataclass
class UnrenderableDiff:
    kind: DiffType = DiffType.UNRENDERABLE


FileDiff = TextDiff | ImageDiff | BinaryDiff | SubmoduleDiff | LargeTextDiff | UnrenderableDiff


@dataclass
class CommitIdentity:
    name: str
    email: str
    date: datetime
    tz_offset: int = 0

    @classmethod
    def parse_raw(cls, raw: str) -> "CommitIdentity":
        # "Name <email> unix timestamp tz"
        # author: '%an <%ae> %ad' with --date=raw -> "Name <email> 1234567890 +0000"
        try:
            left, rest = raw.rsplit(">", 1)
            name_email = left + ">"
            name, email = name_email.rsplit("<", 1)
            email = email.rstrip(">")
            parts = rest.strip().split()
            ts = int(parts[0]) if parts else 0
            tz = parts[1] if len(parts) > 1 else "+0000"
            sign = 1 if tz.startswith("+") else -1
            hours = int(tz[1:3] or 0)
            minutes = int(tz[3:5] or 0)
            offset = sign * (hours * 60 + minutes)
            return cls(name.strip(), email.strip(), datetime.fromtimestamp(ts, tz=timezone.utc), offset)
        except (ValueError, IndexError):
            return cls(raw, "", datetime.fromtimestamp(0, tz=timezone.utc), 0)


@dataclass
class Author:
    name: str
    email: str
    username: str | None = None
    unknown: bool = False


@dataclass
class Commit:
    sha: str
    short_sha: str
    summary: str
    body: str
    author: CommitIdentity
    committer: CommitIdentity
    parent_shas: list[str] = field(default_factory=list)
    trailers: list[tuple[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)

    @property
    def authored_by_committer(self) -> bool:
        return (
            self.author.name == self.committer.name
            and self.author.email == self.committer.email
        )

    @property
    def co_authors(self) -> list[Author]:
        authors = []
        for token, value in self.trailers:
            if token.lower() == "co-authored-by":
                name, email = parse_name_email(value)
                authors.append(Author(name, email))
        return authors


@dataclass
class CommitOneLine:
    sha: str
    summary: str


@dataclass
class CommitMessage:
    summary: str = ""
    description: str = ""
    timestamp: int = 0

    def as_text(self) -> str:
        summary = self.summary.strip()
        description = self.description.strip()
        if description:
            return f"{summary}\n\n{description}\n"
        return f"{summary}\n"


@dataclass
class Branch:
    name: str
    upstream: str | None
    tip_sha: str
    type: BranchType
    remote: str | None = None
    upstream_without_remote: str | None = None
    ref: str = ""

    @property
    def name_without_remote(self) -> str:
        if self.type == BranchType.LOCAL:
            return self.name
        if self.remote and self.name.startswith(f"{self.remote}/"):
            return self.name[len(self.remote) + 1 :]
        if "/" in self.name:
            return self.name.split("/", 1)[1]
        return self.name

    @property
    def is_local(self) -> bool:
        return self.type == BranchType.LOCAL


@dataclass
class Remote:
    name: str
    url: str


@dataclass
class GitHubRepository:
    name: str
    owner: str
    html_url: str
    clone_url: str
    ssh_url: str = ""
    default_branch: str = "main"
    private: bool = False
    fork: bool = False
    parent: "GitHubRepository | None" = None
    endpoint: str = "https://api.github.com"
    db_id: int | None = None
    permissions: str | None = None
    has_issues: bool = True

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"


@dataclass
class Repository:
    id: int
    path: str
    name: str
    is_missing: bool = False
    unsafe: bool = False
    alias: str | None = None
    github: GitHubRepository | None = None
    workflow_preferences: dict[str, Any] = field(default_factory=dict)
    tutorial: bool = False

    @property
    def display_name(self) -> str:
        return self.alias or self.name

    @property
    def has_github(self) -> bool:
        return self.github is not None

    @property
    def is_fork(self) -> bool:
        return bool(self.github and self.github.fork and self.github.parent)


@dataclass
class CloningRepository:
    id: int
    path: str
    url: str
    progress: float = 0.0
    description: str = ""


@dataclass
class Account:
    login: str
    endpoint: str
    token: str
    emails: list[str] = field(default_factory=list)
    avatar_url: str = ""
    name: str = ""
    id: int = 0
    plan: str | None = None
    copilot_endpoint: str | None = None
    copilot_token: str | None = None

    @property
    def is_dotcom(self) -> bool:
        return "api.github.com" in self.endpoint

    @property
    def friendly_endpoint(self) -> str:
        if self.is_dotcom:
            return "GitHub.com"
        return html_url_from_endpoint(self.endpoint)


@dataclass
class PullRequest:
    number: int
    title: str
    body: str
    created_at: str
    author: str
    draft: bool
    head_ref: str
    head_sha: str
    base_ref: str
    html_url: str
    state: str = "open"
    head_clone_url: str | None = None
    head_owner: str | None = None


@dataclass
class Issue:
    number: int
    title: str
    state: str = "open"


@dataclass
class DiffComment:
    path: str
    body: str
    user: str = ""
    html_url: str = ""
    line: int | None = None
    original_line: int | None = None
    side: str = "RIGHT"
    diff_hunk: str = ""


@dataclass
class CheckStep:
    name: str
    number: int = 0
    status: str = ""
    conclusion: str | None = None
    html_url: str | None = None


@dataclass
class RefCheck:
    id: int
    name: str
    description: str
    status: str
    conclusion: str | None
    html_url: str | None = None
    app_name: str | None = None
    check_suite_id: int | None = None
    steps: list[CheckStep] = field(default_factory=list)


@dataclass
class StashEntry:
    name: str
    stash_sha: str
    branch_name: str
    tree: str
    parents: list[str]
    files: list[CommittedFileChange] | None = None


@dataclass
class Banner:
    type: BannerType
    our_branch: str | None = None
    their_branch: str | None = None
    count: int = 0
    operation_description: str = ""
    target_branch: str | None = None


@dataclass
class Popup:
    type: PopupType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SecretLocation:
    commit_sha: str
    path: str
    line_number: int = 0


@dataclass
class SecretScanResult:
    secret_type: str = ""
    path: str = ""
    line: int | None = None
    bypass_url: str | None = None
    description: str = ""
    id: str = ""
    locations: list[SecretLocation] = field(default_factory=list)
    requires_approval: bool = False


@dataclass
class Progress:
    kind: str
    title: str
    description: str = ""
    value: float = 0.0


def parse_name_email(value: str) -> tuple[str, str]:
    value = value.strip()
    if value.startswith("@") and "<" not in value and " " not in value.strip():
        login = value[1:].strip()
        if login:
            return login, f"{login}@users.noreply.github.com"
    if "<" in value and ">" in value:
        name, rest = value.split("<", 1)
        email = rest.split(">", 1)[0]
        return name.strip(), email.strip()
    return value, ""


def parse_co_authors(text: str) -> list[Author]:
    """Parse comma/newline-separated co-authors (`Name <email>` or `@login`)."""
    import re

    authors: list[Author] = []
    for raw in re.split(r"[,;\n]+", text or ""):
        token = raw.strip()
        if not token:
            continue
        handle = token.startswith("@") and "<" not in token
        name, email = parse_name_email(token)
        authors.append(
            Author(
                name=name,
                email=email,
                username=token[1:].strip() if handle else None,
                unknown=not bool(email),
            )
        )
    return authors


def html_url_from_endpoint(endpoint: str) -> str:
    if endpoint.rstrip("/") == "https://api.github.com":
        return "https://github.com"
    return endpoint.replace("/api/v3", "").rstrip("/")


def api_endpoint_from_html(url: str) -> str:
    url = url.rstrip("/")
    if url in ("https://github.com", "http://github.com"):
        return "https://api.github.com"
    if url.endswith("/api/v3"):
        return url
    return f"{url}/api/v3"


def git_author_name_is_valid(name: str) -> bool:
    if not name or not name.strip():
        return False
    # Git rejects names containing ":" (used in ident strings)
    return ":" not in name


INVALID_GIT_AUTHOR_NAME_MESSAGE = (
    "Name can't contain a colon or be all ASCII control characters."
)


def sanitize_ref_name(name: str) -> str:
    cleaned = []
    for ch in name.strip().replace(" ", "-"):
        if ch in '~^:?*[\\ ':
            continue
        if ord(ch) < 32 or ch == "\x7f":
            continue
        cleaned.append(ch)
    result = "".join(cleaned)
    while ".." in result:
        result = result.replace("..", ".")
    result = result.strip(".")
    result = result.replace("@{", "").replace("//", "/")
    return result.strip("/")


def test_for_invalid_chars(name: str) -> bool:
    if not name:
        return True
    forbidden = set("~^:?*[\\ ")
    if any(c in forbidden or ord(c) < 32 for c in name):
        return True
    if ".." in name or name.endswith(".") or name.endswith("/") or "@{" in name:
        return True
    return False
