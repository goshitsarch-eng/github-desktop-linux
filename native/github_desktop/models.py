"""Domain models matching GitHub Desktop's TypeScript models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum, IntEnum, StrEnum
from math import ceil
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
from uuid import uuid4

from .fatal_error import fatal_error


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


class IndexStatus(IntEnum):
    """Statuses from `git diff-index --cached --name-status --no-renames`."""

    UNKNOWN = 0
    ADDED = 1
    COPIED = 2
    DELETED = 3
    MODIFIED = 4
    RENAMED = 5
    TYPE_CHANGED = 6
    UNMERGED = 7


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


class StartPoint(StrEnum):
    """Desktop `StartPoint` for Create Branch."""

    CURRENT_BRANCH = "CurrentBranch"
    DEFAULT_BRANCH = "DefaultBranch"
    HEAD = "Head"
    UPSTREAM_DEFAULT_BRANCH = "UpstreamDefaultBranch"


class RepositorySectionTab(StrEnum):
    CHANGES = "Changes"
    HISTORY = "History"


class HistoryTabMode(StrEnum):
    HISTORY = "History"
    COMPARE = "Compare"


class ComparisonMode(StrEnum):
    AHEAD = "Ahead"
    BEHIND = "Behind"


class FoldoutType(StrEnum):
    REPOSITORY = "Repository"
    BRANCH = "Branch"
    APP_MENU = "AppMenu"
    ADD_MENU = "AddMenu"
    PUSH_PULL = "PushPull"


class BranchesTab(StrEnum):
    """Desktop `BranchesTab` / `selectedBranchesTab`."""

    BRANCHES = "Branches"
    PULL_REQUESTS = "PullRequests"


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
    OPEN_THANK_YOU_CARD = "OpenThankYouCard"
    DETACHED_HEAD = "DetachedHead"
    ACCESSIBILITY_SETTINGS = "AccessibilitySettings"


class ForcePushBranchState(StrEnum):
    NOT_AVAILABLE = "NotAvailable"
    AVAILABLE = "Available"
    RECOMMENDED = "Recommended"


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
    """Desktop `CloneRepositoryTab`: DotCom, Enterprise, Generic (URL)."""

    DOTCOM = "DotCom"
    ENTERPRISE = "Enterprise"
    URL = "URL"
    GENERIC = "URL"


class PublishTab(StrEnum):
    """Desktop `PublishTab` for the Publish repository dialog."""

    DOTCOM = "DotCom"
    ENTERPRISE = "Enterprise"


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
    ALL_DONE = "AllDone"
    ALL_COMPLETE = "AllDone"
    PAUSED = "Paused"
    ANNOUNCED = "Announced"


def is_valid_tutorial_step(step: TutorialStep) -> bool:
    """Desktop `isValidTutorialStep`: exclude NotApplicable and Paused."""
    return step not in {TutorialStep.NOT_APPLICABLE, TutorialStep.PAUSED}


ORDERED_TUTORIAL_STEPS: tuple[TutorialStep, ...] = (
    TutorialStep.PICK_EDITOR,
    TutorialStep.CREATE_BRANCH,
    TutorialStep.EDIT_FILE,
    TutorialStep.MAKE_COMMIT,
    TutorialStep.PUSH_BRANCH,
    TutorialStep.OPEN_PULL_REQUEST,
    TutorialStep.ALL_DONE,
    TutorialStep.ANNOUNCED,
)
"""Desktop `orderedTutorialSteps`."""


class FetchType(StrEnum):
    BACKGROUND_TASK = "BackgroundTask"
    USER_INITIATED = "UserInitiatedTask"


class PullRequestSuggestedNextAction(StrEnum):
    """Empty-Changes card: Preview vs Create pull request (Desktop `PullRequestSuggestedNextAction`)."""

    PREVIEW_PULL_REQUEST = "PreviewPullRequest"
    CREATE_PULL_REQUEST = "CreatePullRequest"


DEFAULT_PULL_REQUEST_SUGGESTED_NEXT_ACTION = PullRequestSuggestedNextAction.PREVIEW_PULL_REQUEST


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


class ComputedAction(StrEnum):
    LOADING = "loading"
    CLEAN = "clean"
    CONFLICTS = "conflicts"
    INVALID = "invalid"


@dataclass
class MergeTreeResult:
    kind: ComputedAction
    conflicted_files: int = 0


@dataclass
class RebasePreview:
    kind: ComputedAction
    commits_ahead: int = 0
    commits_behind: int = 0


class ManualConflictResolution(StrEnum):
    OURS = "ours"
    THEIRS = "theirs"


class ForkContributionTarget(StrEnum):
    PARENT = "Parent"
    SELF = "Self"


UPSTREAM_REMOTE_NAME = "upstream"
ORIGIN_REMOTE_NAME = "origin"


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


def is_conflict_with_markers(status: FileStatus) -> bool:
    """Desktop `isConflictWithMarkers`."""
    return status.is_conflicted and status.conflict_marker_count is not None


def is_conflicted_file(status: FileStatus) -> bool:
    """Desktop `isConflictedFile`."""
    return status.is_conflicted


def map_status(status: FileStatus) -> str:
    """Desktop `mapStatus`: human-readable file status for lists."""
    if status.kind in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
        return "New"
    if status.kind == AppFileStatusKind.CONFLICTED:
        if is_conflict_with_markers(status):
            return "Conflicted" if (status.conflict_marker_count or 0) > 0 else "Resolved"
        return "Conflicted"
    return status.kind.value


def path_label(path: str, status: FileStatus | None) -> str:
    """Desktop `PathLabel`: `old → new` for renamed/copied files."""
    if status is not None and status.kind in (AppFileStatusKind.RENAMED, AppFileStatusKind.COPIED) and status.old_path:
        return f"{status.old_path} → {path}"
    return path


def is_manual_conflict(status: FileStatus) -> bool:
    """Desktop `isManualConflict` (added/deleted by us/them, no markers)."""
    return status.is_conflicted and status.conflict_marker_count is None


def has_unresolved_conflicts(
    status: FileStatus, manual_resolution: ManualConflictResolution | None = None
) -> bool:
    """Desktop `hasUnresolvedConflicts`. Manual resolutions count as resolved."""
    if not status.is_conflicted:
        return False
    if is_manual_conflict(status):
        return manual_resolution is None
    return (status.conflict_marker_count or 0) > 0


def _working_directory_files(
    status_or_files: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
) -> Sequence[WorkingDirectoryFileChange]:
    return getattr(status_or_files, "files", status_or_files)


def has_conflicted_files(
    working_directory_status: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
) -> bool:
    """Desktop `hasConflictedFiles`."""
    return any(is_conflicted_file(file.status) for file in _working_directory_files(working_directory_status))


def get_unmerged_files(
    status: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
) -> list[WorkingDirectoryFileChange]:
    """Desktop `getUnmergedFiles`: conflicted or resolved unmerged paths."""
    return [file for file in _working_directory_files(status) if is_conflicted_file(file.status)]


def get_untracked_files(
    working_directory_status: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
) -> list[WorkingDirectoryFileChange]:
    """Desktop `getUntrackedFiles`."""
    return [
        file
        for file in _working_directory_files(working_directory_status)
        if file.status.kind == AppFileStatusKind.UNTRACKED
    ]


def get_resolved_files(
    status: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
    manual_resolutions: Mapping[str, ManualConflictResolution] | None = None,
) -> list[WorkingDirectoryFileChange]:
    """Desktop `getResolvedFiles`."""
    resolutions = manual_resolutions or {}
    return [
        file
        for file in _working_directory_files(status)
        if is_conflicted_file(file.status)
        and not has_unresolved_conflicts(file.status, resolutions.get(file.path))
    ]


def get_conflicted_files(
    files: WorkingDirectoryStatus | Sequence[WorkingDirectoryFileChange],
    manual_resolutions: Mapping[str, ManualConflictResolution] | None = None,
) -> list[WorkingDirectoryFileChange]:
    """Desktop `getConflictedFiles`: still-unresolved conflicted paths."""
    resolutions = manual_resolutions or {}
    return [
        file
        for file in _working_directory_files(files)
        if is_conflicted_file(file.status)
        and has_unresolved_conflicts(file.status, resolutions.get(file.path))
    ]


def get_unmerged_status_entry_description(entry: GitStatusEntry | None, branch: str | None = None) -> str:
    """Desktop `getUnmergedStatusEntryDescription`."""
    suffix = f" from {branch}" if branch else ""
    if entry == GitStatusEntry.ADDED:
        return f"Using the added file{suffix}"
    if entry == GitStatusEntry.UPDATED_BUT_UNMERGED:
        return f"Using the modified file{suffix}"
    if entry == GitStatusEntry.DELETED:
        return f"Using the deleted file{suffix}"
    return f"Using ours{suffix}" if not branch else f"Using {branch}"


DEFAULT_CONFLICTS_RESOLVED_MESSAGE = "No conflicts remaining"


def calculate_conflicts(conflict_markers: int) -> int:
    """Desktop `calculateConflicts`: marker count / 3, rounded up."""
    return ceil(conflict_markers / 3)


def get_resolved_file_status_summary(
    status: FileStatus,
    manual_resolution: ManualConflictResolution | None = None,
    branch: str | None = None,
) -> str:
    """Desktop `getResolvedFileStatusSummary` / `resolvedFileStatusString`."""
    if is_conflict_with_markers(status) and (status.conflict_marker_count or 0) == 0:
        return DEFAULT_CONFLICTS_RESOLVED_MESSAGE
    if manual_resolution == ManualConflictResolution.OURS:
        return get_unmerged_status_entry_description(status.us, branch)
    if manual_resolution == ManualConflictResolution.THEIRS:
        return get_unmerged_status_entry_description(status.them, branch)
    return DEFAULT_CONFLICTS_RESOLVED_MESSAGE


def get_branch_for_resolution(
    manual_resolution: ManualConflictResolution | None,
    our_branch: str | None = None,
    their_branch: str | None = None,
) -> str | None:
    """Desktop `getBranchForResolution`."""
    if manual_resolution == ManualConflictResolution.OURS:
        return our_branch
    if manual_resolution == ManualConflictResolution.THEIRS:
        return their_branch
    return None


def get_label_for_manual_resolution_option(entry: GitStatusEntry | None, branch: str | None = None) -> str:
    """Desktop `getLabelForManualResolutionOption`."""
    suffix = f" from {branch}" if branch else ""
    if entry == GitStatusEntry.ADDED:
        return f"Use the added file{suffix}"
    if entry == GitStatusEntry.DELETED:
        delete_suffix = f" on {branch}" if branch else ""
        return f"Do not include this file{delete_suffix}"
    if entry == GitStatusEntry.UPDATED_BUT_UNMERGED:
        return f"Use the modified file{suffix}"
    return f"Use ours{suffix}" if not branch else f"Use {branch}"


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

    def is_included_in_commit(self) -> bool:
        """Desktop `isIncludedInCommit` (fully selected)."""
        return self.selection.get_selection_type() == DiffSelectionType.ALL

    def is_excluded_from_commit(self) -> bool:
        """Desktop `isExcludedFromCommit`."""
        return self.selection.get_selection_type() == DiffSelectionType.NONE

    def is_new(self) -> bool:
        return self.status.kind == AppFileStatusKind.NEW

    def is_untracked(self) -> bool:
        return self.status.kind == AppFileStatusKind.UNTRACKED

    def is_modified(self) -> bool:
        return self.status.kind == AppFileStatusKind.MODIFIED

    def is_deleted(self) -> bool:
        return self.status.kind == AppFileStatusKind.DELETED

    def with_include(self, include: bool) -> "WorkingDirectoryFileChange":
        selection = self.selection.with_select_all() if include else self.selection.with_select_none()
        return replace(self, selection=selection)

    def with_selection(self, selection: DiffSelection) -> "WorkingDirectoryFileChange":
        return replace(self, selection=selection)


UNCOMMITTABLE_SUBMODULE_TOOLTIP = (
    "This submodule change cannot be added to a commit in this repository because it contains changes that have not been committed."
)
PARTIALLY_COMMITTABLE_SUBMODULE_TOOLTIP = (
    "Only changes that have been committed within the submodule will be added to this repository. You need to commit any other modified or untracked changes in the submodule before including them in this repository."
)


def is_uncommittable_submodule(file: WorkingDirectoryFileChange) -> bool:
    """Desktop `isUncommittableSubmodule`: modified submodule without a commit change."""
    status = file.status.submodule_status
    return (
        status is not None
        and file.status.kind == AppFileStatusKind.MODIFIED
        and not status.commit_changed
    )


def is_partially_committable_submodule(file: WorkingDirectoryFileChange) -> bool:
    """Desktop `isPartiallyCommittableSubmodule`: committed submodule still has WD changes."""
    status = file.status.submodule_status
    if status is None:
        return False
    return (status.commit_changed or file.status.kind == AppFileStatusKind.NEW) and (
        status.modified_changes or status.untracked_changes
    )


def submodule_include_tooltip(file: WorkingDirectoryFileChange) -> str | None:
    if is_uncommittable_submodule(file):
        return UNCOMMITTABLE_SUBMODULE_TOOLTIP
    if is_partially_committable_submodule(file):
        return PARTIALLY_COMMITTABLE_SUBMODULE_TOOLTIP
    return None


def commit_summary_placeholder(
    files: Sequence[WorkingDirectoryFileChange],
    *,
    tutorial: bool = False,
) -> str:
    """Desktop `getPlaceholderMessage`: Create/Delete/Update {file} when one path is included."""
    if tutorial:
        return "Summary (required)"
    included = [
        item
        for item in files
        if item.selection.get_selection_type() != DiffSelectionType.NONE
        and not is_uncommittable_submodule(item)
    ]
    if len(included) != 1:
        return "Summary (required)"
    name = Path(included[0].path).name
    kind = included[0].status.kind
    if kind in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
        return f"Create {name}"
    if kind == AppFileStatusKind.DELETED:
        return f"Delete {name}"
    return f"Update {name}"


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
        files = []
        for item in self.files:
            if is_uncommittable_submodule(item):
                files.append(item.with_include(False))
            else:
                files.append(item.with_include(include_all))
        return WorkingDirectoryStatus.from_files(files)

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


def shorten_sha(sha: str) -> str:
    """Desktop `shortenSHA`."""
    return sha[:7]


def submodule_repository_link(url: str | None) -> tuple[str, str] | None:
    """Desktop `renderSubmoduleInfo` https URI and `owner/name` caption."""
    if not url:
        return None
    from .remote_parsing import parse_repository_identifier

    ident = parse_repository_identifier(url)
    if ident is None:
        return None
    hostname = ident.hostname or "github.com"
    suffix = "" if hostname == "github.com" else f" ({hostname})"
    uri = f"https://{hostname}/{ident.owner}/{ident.name}"
    return uri, f"{ident.owner}/{ident.name}{suffix}"


def submodule_commit_change_copy(
    old_sha: str | None,
    new_sha: str | None,
    *,
    read_only: bool,
) -> str | None:
    """Desktop `renderCommitChangeInfo` (short SHAs inlined)."""
    verb = "was" if read_only else "has been"
    suffix = "" if read_only else " This change can be committed to the parent repository."
    if old_sha and new_sha:
        return (
            f"This submodule changed its commit from {shorten_sha(old_sha)} to "
            f"{shorten_sha(new_sha)}.{suffix}"
        )
    if not old_sha and new_sha:
        return f"This submodule {verb} added pointing at commit {shorten_sha(new_sha)}.{suffix}"
    if old_sha and not new_sha:
        return (
            f"This submodule {verb} removed while it was pointing at commit "
            f"{shorten_sha(old_sha)}.{suffix}"
        )
    return None


def submodule_working_changes_copy(status: SubmoduleStatus | None) -> str | None:
    """Desktop `renderSubmodulesChangesInfo`."""
    if status is None or not (status.untracked_changes or status.modified_changes):
        return None
    if status.untracked_changes and status.modified_changes:
        changes = "modified and untracked"
    elif status.untracked_changes:
        changes = "untracked"
    else:
        changes = "modified"
    return (
        f"This submodule has {changes} changes. Those changes must be committed inside of the submodule before they can be part of the parent repository."
    )


@dataclass
class LargeTextDiff:
    kind: DiffType = DiffType.LARGE_TEXT
    text: str = ""
    hunks: list[DiffHunk] = field(default_factory=list)
    line_endings_change: tuple[str, str] | None = None
    max_line_number: int = 0
    has_hidden_bidi_chars: bool = False


@dataclass
class UnrenderableDiff:
    kind: DiffType = DiffType.UNRENDERABLE


FileDiff = TextDiff | ImageDiff | BinaryDiff | SubmoduleDiff | LargeTextDiff | UnrenderableDiff


# Desktop `CommitIdentity.parseIdentity` / git ident.c fmt_ident:
# "NAME <EMAIL> UNIX_TS TZ" e.g. Markus Olsson <j.markus.olsson@gmail.com> 1475670580 +0200
_GIT_IDENT_RE = re.compile(r"^(.*?) <(.*?)> (\d+) (\+|-)?(\d{2})(\d{2})")


@dataclass
class CommitIdentity:
    name: str
    email: str
    date: datetime
    tz_offset: int = 0

    @classmethod
    def parse_identity(cls, identity: str) -> "CommitIdentity":
        """Desktop `CommitIdentity.parseIdentity`. Raises if the ident string is invalid."""
        match = _GIT_IDENT_RE.match(identity.strip())
        if not match:
            raise ValueError(f"Couldn't parse identity {identity}")
        name, email, ts_raw, tz_sign, tz_hh, tz_mm = match.groups()
        try:
            ts = int(ts_raw)
        except ValueError as exc:
            raise ValueError(f"Couldn't parse identity {identity}, invalid date") from exc
        sign = -1 if tz_sign == "-" else 1
        offset = sign * (int(tz_hh) * 60 + int(tz_mm))
        return cls(name, email, datetime.fromtimestamp(ts, tz=timezone.utc), offset)

    @classmethod
    def parse_raw(cls, raw: str) -> "CommitIdentity":
        # "Name <email> unix timestamp tz"
        # author: '%an <%ae> %ad' with --date=raw -> "Name <email> 1234567890 +0000"
        try:
            return cls.parse_identity(raw)
        except ValueError:
            return cls(raw, "", datetime.fromtimestamp(0, tz=timezone.utc), 0)


@dataclass
class Author:
    name: str
    email: str
    username: str | None = None
    unknown: bool = False
    # Desktop `UnknownAuthor.state`: searching | error
    state: str | None = None


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

    @property
    def body_no_co_authors(self) -> str:
        """Desktop `Commit.bodyNoCoAuthors` / `trimCoAuthorsTrailers`."""
        trimmed = self.body
        for token, value in self.trailers:
            if token.lower() == "co-authored-by":
                trimmed = trimmed.replace(f"{token}: {value}", "")
        return trimmed

    @property
    def is_merge_commit(self) -> bool:
        return len(self.parent_shas) > 1


def is_web_flow_committer(commit: Commit, github: GitHubRepository | None) -> bool:
    """Desktop `isWebFlowCommitter` (GitHub / GitHub Enterprise merge committers)."""
    if github is None:
        return False
    name = commit.committer.name
    email = commit.committer.email
    if is_dotcom_endpoint(github.endpoint) and name == "GitHub" and email == "noreply@github.com":
        return True
    if not is_dotcom_endpoint(github.endpoint) and name == "GitHub Enterprise":
        return True
    return False


def format_commit_attribution(commit: Commit, github: GitHubRepository | None = None) -> str:
    """Desktop `CommitAttribution` for a single commit (author, committer, co-authors)."""
    names: list[str] = []

    def add(name: str) -> None:
        if name and name not in names:
            names.append(name)

    add(commit.author.name)
    if not commit.authored_by_committer and not is_web_flow_committer(commit, github):
        add(commit.committer.name)
    for author in commit.co_authors:
        add(author.name)
    if len(names) <= 1:
        return names[0] if names else ""
    if len(names) == 2:
        return f"{names[0]}, {names[1]}"
    return f"{len(names)} people"


def get_unique_coauthors_as_authors(commits: Sequence[Commit]) -> list[Author]:
    """Desktop `getUniqueCoauthorsAsAuthors`."""
    unique: list[Author] = []
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        for author in commit.co_authors:
            key = (author.name, author.email)
            if key in seen:
                continue
            seen.add(key)
            unique.append(Author(name=author.name, email=author.email, username=None))
    return unique


def get_squashed_commit_description(commits: Sequence[Commit], squash_onto: Commit) -> str:
    """Desktop `getSquashedCommitDescription`."""
    commit_messages = [f"{commit.summary.strip()}\n\n{commit.body_no_co_authors.strip()}" for commit in commits]
    descriptions = [squash_onto.body_no_co_authors.strip(), *commit_messages]
    return "\n\n".join(item for item in descriptions if item.strip() != "")


def get_old_path_or_default(
    file: object | None = None,
    *,
    path: str | None = None,
    status: FileStatus | None = None,
) -> str:
    """Desktop `getOldPathOrDefault`: renamed/copied `oldPath`, else `file.path`."""
    resolved_path = path if path is not None else str(getattr(file, "path", "") or "")
    resolved_status = status if status is not None else getattr(file, "status", None)
    kind = getattr(resolved_status, "kind", None)
    old = getattr(resolved_status, "old_path", None)
    if kind in (AppFileStatusKind.RENAMED, AppFileStatusKind.COPIED) and old:
        return old
    return resolved_path


@dataclass
class CommitOneLine:
    sha: str
    summary: str


@dataclass
class CommitMessage:
    summary: str = ""
    description: str = ""
    timestamp: int = 0
    # Desktop `generatedByCopilot` — Copilot origin, cleared when the user edits.
    generated_by_copilot: bool = False

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

    def __post_init__(self) -> None:
        if self.upstream_without_remote is None and self.upstream:
            from .remove_remote_prefix import remove_remote_prefix

            self.upstream_without_remote = remove_remote_prefix(self.upstream)

    @property
    def name_without_remote(self) -> str:
        if self.type == BranchType.LOCAL:
            return self.name
        from .remove_remote_prefix import remove_remote_prefix

        return remove_remote_prefix(self.name) or self.name

    @property
    def is_local(self) -> bool:
        return self.type == BranchType.LOCAL

    @property
    def upstream_remote_name(self) -> str | None:
        if self.upstream and "/" in self.upstream:
            return self.upstream.split("/", 1)[0]
        return self.remote if self.type == BranchType.REMOTE else None

    @property
    def is_desktop_fork_remote_branch(self) -> bool:
        """Desktop `isDesktopForkRemoteBranch` (hidden `github-desktop-` fork remotes)."""
        return self.type == BranchType.REMOTE and self.name.startswith(FORKED_REMOTE_PREFIX)

    isDesktopForkRemoteBranch = is_desktop_fork_remote_branch


def pr_base_branches(
    branches: Sequence,
    *,
    remote: str | None,
    current: str | None,
) -> list[str]:
    """Desktop `prBaseBranches`: only branches that exist on the contribution remote."""
    names: list[str] = []
    seen: set[str] = set()
    for branch in branches:
        if not remote:
            continue
        if branch.upstream_remote_name != remote and getattr(branch, "remote", None) != remote:
            continue
        name = branch.name_without_remote
        if not name or name == current or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def group_pr_base_branches(
    branch_names: Sequence[str],
    recent_names: Sequence[str],
    *,
    current: str | None,
    default: str | None,
) -> tuple[list[str], list[str]]:
    """Split Start PR bases into Desktop `prRecentBaseBranches` and the rest."""
    names = [name for name in branch_names if name and name != current]
    if default and default != current and default not in names:
        names.insert(0, default)
    recent: list[str] = []
    seen: set[str] = set()
    for name in recent_names:
        if name in names and name not in seen:
            recent.append(name)
            seen.add(name)
    others = [name for name in names if name not in seen]
    return recent, others


@dataclass
class TrackingBranch:
    """Local branch whose tip differs from its upstream (Desktop ITrackingBranch)."""

    ref: str
    sha: str
    upstream_ref: str
    upstream_sha: str


FORKED_REMOTE_PREFIX = "github-desktop-"


def fork_pull_request_remote_name(owner: str) -> str:
    return f"{FORKED_REMOTE_PREFIX}{owner}"


def format_as_local_ref(name: str) -> str:
    """Desktop `formatAsLocalRef`."""
    if name.startswith("heads/"):
        return f"refs/{name}"
    if not name.startswith("refs/heads/"):
        return f"refs/heads/{name}"
    return name


RESERVED_BRANCH_REFS = (
    "HEAD",
    "refs/heads/main",
    "refs/heads/master",
    "refs/heads/gh-pages",
    "refs/heads/develop",
    "refs/heads/dev",
    "refs/heads/development",
    "refs/heads/trunk",
    "refs/heads/devel",
    "refs/heads/release",
)


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
    archived: bool = False

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


def is_repository_with_github_repository(repository: Repository) -> bool:
    """Desktop `isRepositoryWithGitHubRepository`."""
    return repository.github is not None


def is_repository_with_forked_github_repository(repository: Repository) -> bool:
    """Desktop `isRepositoryWithForkedGitHubRepository`."""
    return repository.github is not None and repository.github.parent is not None


def assert_is_repository_with_github_repository(repository: Repository) -> None:
    """Desktop `assertIsRepositoryWithGitHubRepository`."""
    if not is_repository_with_github_repository(repository):
        fatal_error("Repository must be GitHub repository")


def name_of(repository: Repository) -> str:
    """Desktop `nameOf`: owner/name when GitHub-associated, otherwise the folder name."""
    if repository.github is not None:
        return repository.github.full_name
    return repository.name


def fork_contribution_target(repo: Repository) -> ForkContributionTarget:
    raw = (repo.workflow_preferences or {}).get("fork_target")
    if raw in (ForkContributionTarget.SELF, ForkContributionTarget.SELF.value):
        return ForkContributionTarget.SELF
    return ForkContributionTarget.PARENT


def get_fork_contribution_target(repository: Repository) -> ForkContributionTarget:
    """Desktop `getForkContributionTarget`."""
    return fork_contribution_target(repository)


def is_forked_repository_contributing_to_parent(repository: Repository) -> bool:
    """Desktop `isForkedRepositoryContributingToParent`."""
    return (
        is_repository_with_forked_github_repository(repository)
        and fork_contribution_target(repository) == ForkContributionTarget.PARENT
    )


def get_non_fork_github_repository(repository: Repository) -> GitHubRepository:
    """Desktop `getNonForkGitHubRepository`: honor fork contribution target."""
    assert_is_repository_with_github_repository(repository)
    github = repository.github
    if github is None:
        return fatal_error("Repository must be GitHub repository")
    if not is_repository_with_forked_github_repository(repository):
        return github
    target = fork_contribution_target(repository)
    if target == ForkContributionTarget.SELF:
        return github
    if target == ForkContributionTarget.PARENT:
        parent = github.parent
        if parent is None:
            return fatal_error("Invalid fork contribution target")
        return parent
    return fatal_error("Invalid fork contribution target")


def get_github_html_url(repository: Repository) -> str | None:
    """Desktop `getGitHubHtmlUrl`: parent HTML URL when contributing to the upstream."""
    if not is_repository_with_github_repository(repository):
        return None
    url = get_non_fork_github_repository(repository).html_url
    return url or None


def github_for_contribution(repo: Repository) -> GitHubRepository | None:
    if not is_repository_with_github_repository(repo):
        return None
    return get_non_fork_github_repository(repo)


def github_to_dict(gh: GitHubRepository | None) -> dict[str, Any] | None:
    if gh is None:
        return None
    return {
        "name": gh.name,
        "owner": gh.owner,
        "html_url": gh.html_url,
        "clone_url": gh.clone_url,
        "ssh_url": gh.ssh_url,
        "default_branch": gh.default_branch,
        "private": gh.private,
        "fork": gh.fork,
        "endpoint": gh.endpoint,
        "permissions": gh.permissions,
        "has_issues": gh.has_issues,
        "archived": gh.archived,
        "parent": github_to_dict(gh.parent),
    }


def github_from_dict(data: dict[str, Any] | None) -> GitHubRepository | None:
    if not data:
        return None
    return GitHubRepository(
        name=data.get("name") or "",
        owner=data.get("owner") or "",
        html_url=data.get("html_url") or "",
        clone_url=data.get("clone_url") or "",
        ssh_url=data.get("ssh_url") or "",
        default_branch=data.get("default_branch") or "main",
        private=bool(data.get("private")),
        fork=bool(data.get("fork")),
        parent=github_from_dict(data.get("parent") if isinstance(data.get("parent"), dict) else None),
        endpoint=data.get("endpoint") or "https://api.github.com",
        permissions=data.get("permissions"),
        has_issues=bool(data.get("has_issues", True)),
        archived=bool(data.get("archived")),
    )


@dataclass
class CloningRepository:
    id: int
    path: str
    url: str
    progress: float = 0.0
    description: str = ""

    @property
    def name(self) -> str:
        url_name = Path(str(self.url).rstrip("/")).name
        if url_name.endswith(".git"):
            url_name = url_name[:-4]
        return url_name or Path(self.path).name


@dataclass
class AccountEmail:
    """Desktop `IAPIEmail` fields used for preferred / attributable commit emails."""

    email: str
    primary: bool = False
    verified: bool = True
    visibility: str | None = None

    def __str__(self) -> str:
        return self.email

    def to_dict(self) -> dict[str, Any]:
        return {
            "email": self.email,
            "primary": self.primary,
            "verified": self.verified,
            "visibility": self.visibility,
        }

    @classmethod
    def coerce(cls, value: Any) -> "AccountEmail":
        if isinstance(value, AccountEmail):
            return value
        if isinstance(value, str):
            return cls(email=value)
        if isinstance(value, dict):
            return cls(
                email=str(value.get("email") or ""),
                primary=bool(value.get("primary")),
                verified=bool(value.get("verified", True)),
                visibility=value.get("visibility"),
            )
        return cls(email=str(value) if value else "")


@dataclass
class Account:
    login: str
    endpoint: str
    token: str
    emails: list[AccountEmail] = field(default_factory=list)
    avatar_url: str = ""
    name: str = ""
    id: int = 0
    plan: str | None = None
    copilot_endpoint: str | None = None
    copilot_token: str | None = None
    is_copilot_desktop_enabled: bool = False
    features: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        normalized: list[AccountEmail] = []
        for item in self.emails or []:
            email = AccountEmail.coerce(item)
            if email.email:
                normalized.append(email)
        object.__setattr__(self, "emails", normalized)

    @property
    def email_addresses(self) -> list[str]:
        return [item.email for item in self.emails]

    @property
    def is_dotcom(self) -> bool:
        return "api.github.com" in self.endpoint

    @property
    def is_enterprise(self) -> bool:
        """Desktop `isEnterpriseAccount`: any account that is not GitHub.com."""
        return not self.is_dotcom

    @property
    def friendly_endpoint(self) -> str:
        return friendly_endpoint_name(self)

    @classmethod
    def anonymous(cls) -> "Account":
        """Desktop `Account.anonymous()` for unauthenticated public API access."""
        return cls(login="", endpoint="https://api.github.com", token="", id=-1, plan="free")


def account_equals(left: Account, right: Account) -> bool:
    """Desktop `accountEquals`: same API endpoint and GitHub user id."""
    return left.endpoint == right.endpoint and left.id == right.id


def friendly_endpoint_name(account: Account) -> str:
    """Desktop `friendlyEndpointName`.

    GitHub.com accounts return ``GitHub.com``; Enterprise accounts return the
    hostname without protocol or path.
    """
    from urllib.parse import urlparse

    if account.is_dotcom:
        return "GitHub.com"
    return urlparse(account.endpoint).hostname or account.endpoint


def enable_commit_message_generation(account: Account | None) -> bool:
    """Desktop `enableCommitMessageGeneration`: feature flag + Copilot Desktop entitlement."""
    if account is None:
        return False
    features = list(account.features or [])
    return "desktop_copilot_generate_commit_message" in features and bool(
        account.is_copilot_desktop_enabled
    )


def uncommitted_changes_strategy_choices() -> list[tuple[UncommittedChangesStrategy, str]]:
    """Desktop Prompts copy for `UncommittedChangesStrategy`."""
    return [
        (UncommittedChangesStrategy.ASK_FOR_CONFIRMATION, "Ask me where I want the changes to go"),
        (UncommittedChangesStrategy.MOVE_TO_NEW_BRANCH, "Always bring my changes to my new branch"),
        (UncommittedChangesStrategy.STASH_ON_CURRENT_BRANCH, "Always stash and leave my changes on the current branch"),
    ]


def accounts_for_publish_tab(accounts: Sequence[Account], tab: PublishTab | str) -> list[Account]:
    """Accounts shown on a Desktop Publish `GitHub.com` / `GitHub Enterprise` tab."""
    enterprise = tab in {PublishTab.ENTERPRISE, PublishTab.ENTERPRISE.value, "enterprise"}
    if enterprise:
        return [item for item in accounts if item.is_enterprise]
    return [item for item in accounts if item.is_dotcom]


def default_publish_tab(accounts: Sequence[Account]) -> PublishTab:
    if not accounts_for_publish_tab(accounts, PublishTab.DOTCOM) and accounts_for_publish_tab(
        accounts, PublishTab.ENTERPRISE
    ):
        return PublishTab.ENTERPRISE
    return PublishTab.DOTCOM


def stealth_email_for_account(account: Account) -> str:
    """Desktop `getStealthEmailForAccount` (`{id}+{login}@users.noreply.github.com`)."""
    from .email import legacy_stealth_email_for_user, stealth_email_for_user

    if account.id:
        return stealth_email_for_user(account.id, account.login, account.endpoint)
    return legacy_stealth_email_for_user(account.login, account.endpoint)


def account_email_choices(account: Account) -> list[str]:
    """Desktop `GitConfigUserForm` verified emails, plus stealth on GitHub.com."""
    emails: list[str] = []
    seen: set[str] = set()
    for item in account.emails:
        email = AccountEmail.coerce(item)
        if not email.email or not email.verified:
            continue
        key = email.email.lower()
        if key in seen:
            continue
        seen.add(key)
        emails.append(email.email)
    if account.is_dotcom:
        stealth = stealth_email_for_account(account)
        if stealth.lower() not in seen:
            emails.append(stealth)
    return emails


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
    updated_at: str = ""


@dataclass
class Issue:
    number: int
    title: str
    state: str = "open"
    updated_at: str = ""


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
class CheckAnnotation:
    path: str
    message: str
    annotation_level: str = "warning"
    start_line: int | None = None
    end_line: int | None = None
    title: str = ""


@dataclass
class ActionsWorkflow:
    id: int
    name: str
    event: str = ""
    check_suite_id: int | None = None
    html_url: str | None = None


@dataclass
class CheckSuite:
    id: int
    rerequestable: bool = False
    status: str = ""
    created_at: str = ""


@dataclass
class CheckStep:
    name: str
    number: int = 0
    status: str = ""
    conclusion: str | None = None
    html_url: str | None = None
    started_at: str | None = None
    completed_at: str | None = None


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
    started_at: str | None = None
    completed_at: str | None = None
    has_pull_requests: bool = False
    actions_workflow: ActionsWorkflow | None = None
    steps: list[CheckStep] = field(default_factory=list)
    annotations: list[CheckAnnotation] = field(default_factory=list)
    logs: str | None = None


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
    friendly_name: str = ""
    contributions: list[str] = field(default_factory=list)
    latest_version: str | None = None
    undo_sha: str | None = None
    operation_kind: str | None = None


@dataclass
class Popup:
    type: PopupType
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid4().hex)


class RetryActionType(StrEnum):
    """Desktop `RetryActionType`."""

    PUSH = "Push"
    PULL = "Pull"
    FETCH = "Fetch"
    CLONE = "Clone"
    CHECKOUT = "Checkout"
    MERGE = "Merge"
    REBASE = "Rebase"
    CHERRY_PICK = "CherryPick"
    CREATE_BRANCH_FOR_CHERRY_PICK = "CreateBranchForCherryPick"
    SQUASH = "Squash"
    REORDER = "Reorder"
    DISCARD_CHANGES = "DiscardChanges"


@dataclass
class RetryAction:
    """Desktop `RetryAction` payload for LCO / error Retry / `performRetry`."""

    type: RetryActionType
    repo_id: int | None = None
    branch: str | None = None
    url: str | None = None
    path: str | None = None
    force: bool = False
    tutorial: bool = False
    squash: bool = False
    create_branch: bool = False
    their_branch: str | None = None
    base_branch: str | None = None
    target_branch: str | None = None
    onto_sha: str | None = None
    before_sha: str | None = None
    last_retained: str | None = None
    message: str = ""
    shas: list[str] = field(default_factory=list)
    to_squash_shas: list[str] = field(default_factory=list)
    to_move_shas: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


def retry_action_name(action: RetryAction | RetryActionType | str | None) -> str:
    """Desktop `LocalChangesOverwritten.getRetryActionName`."""
    kind = action.type if isinstance(action, RetryAction) else action
    mapping = {
        RetryActionType.CHECKOUT: "checkout",
        RetryActionType.PULL: "pull",
        RetryActionType.MERGE: "merge",
        RetryActionType.REBASE: "rebase",
        RetryActionType.CLONE: "clone",
        RetryActionType.FETCH: "fetch",
        RetryActionType.PUSH: "push",
        RetryActionType.CHERRY_PICK: "cherry-pick",
        RetryActionType.CREATE_BRANCH_FOR_CHERRY_PICK: "cherry-pick",
        RetryActionType.SQUASH: "squash",
        RetryActionType.REORDER: "reorder",
        RetryActionType.DISCARD_CHANGES: "discard changes",
    }
    if isinstance(kind, RetryActionType):
        return mapping.get(kind, kind.value.lower())
    text = str(kind or "checkout")
    aliases = {item.value.lower(): name for item, name in mapping.items()}
    aliases.update({item.name.lower(): name for item, name in mapping.items()})
    return aliases.get(text.lower(), text)


def retry_action_from_legacy(payload: Mapping[str, Any]) -> RetryAction:
    kind = str(payload.get("kind") or payload.get("type") or "Checkout")
    try:
        action_type = RetryActionType(kind)
    except ValueError:
        by_name = {item.name.lower(): item for item in RetryActionType}
        by_label = {retry_action_name(item): item for item in RetryActionType}
        action_type = by_name.get(kind.lower()) or by_label.get(kind.lower()) or RetryActionType.CHECKOUT
    return RetryAction(
        type=action_type,
        repo_id=payload.get("repo_id"),
        branch=payload.get("branch"),
        url=payload.get("url"),
        path=payload.get("path"),
        force=bool(payload.get("force")),
        tutorial=bool(payload.get("tutorial")),
        squash=bool(payload.get("squash")),
        create_branch=bool(payload.get("create_branch")),
        their_branch=payload.get("their_branch"),
        base_branch=payload.get("base_branch"),
        target_branch=payload.get("target_branch"),
        onto_sha=payload.get("onto_sha"),
        before_sha=payload.get("before_sha"),
        last_retained=payload.get("last_retained"),
        message=str(payload.get("message") or ""),
        shas=list(payload.get("shas") or []),
        to_squash_shas=list(payload.get("to_squash_shas") or []),
        to_move_shas=list(payload.get("to_move_shas") or []),
        files=list(payload.get("files") or []),
    )


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


def is_dotcom_endpoint(endpoint: str | None) -> bool:
    text = (endpoint or "").rstrip("/")
    return "api.github.com" in text or text in {"https://github.com", "http://github.com"}


def is_ghe_endpoint(endpoint: str | None) -> bool:
    """Desktop `isGHE`: hostname ends with `.ghe.com`."""
    from urllib.parse import urlparse

    host = urlparse(endpoint or "").hostname or ""
    return host.endswith(".ghe.com")


def is_ghes_endpoint(endpoint: str | None) -> bool:
    """Desktop `isGHES`: not github.com and not ghe.com."""
    return bool(endpoint) and not is_dotcom_endpoint(endpoint) and not is_ghe_endpoint(endpoint)


def has_write_permission(github: GitHubRepository | None) -> bool:
    """Desktop `hasWritePermission`: unknown permissions are treated as writable."""
    if github is None:
        return True
    return github.permissions is None or github.permissions != "read"


def html_url_from_endpoint(endpoint: str) -> str:
    if endpoint.rstrip("/") == "https://api.github.com":
        return "https://github.com"
    if is_ghe_endpoint(endpoint):
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        if host.startswith("api."):
            host = host[len("api.") :]
        return urlunparse((parsed.scheme or "https", host, "/", "", "", "")).rstrip("/")
    return endpoint.replace("/api/v3", "").rstrip("/")


def api_endpoint_from_html(url: str) -> str:
    url = url.rstrip("/")
    if url in ("https://github.com", "http://github.com"):
        return "https://api.github.com"
    if url.endswith("/api/v3"):
        return url
    return f"{url}/api/v3"


# Git ident.c "crud" characters: ASCII 0–32 plus ., : ; < > " \ '
# Desktop `gitAuthorNameIsValid` rejects names that consist only of these.
_GIT_AUTHOR_CRUD = frozenset(chr(i) for i in range(33)) | frozenset('.,:;<>"\\\'')


def git_author_name_is_valid(name: str) -> bool:
    """Desktop `gitAuthorNameIsValid`. Empty is valid; all-crud names are not."""
    return not name or not all(ch in _GIT_AUTHOR_CRUD for ch in name)


INVALID_GIT_AUTHOR_NAME_MESSAGE = "Name is invalid, it consists only of disallowed characters."


def highlight_text_runs(text: str, highlight: Sequence[int]) -> list[tuple[str, bool]]:
    """Desktop `HighlightText`: group characters into `(chunk, matched)` runs."""
    matched = set(highlight)
    runs: list[tuple[str, bool]] = []
    buf: list[str] = []
    state: bool | None = None
    for index, ch in enumerate(text):
        is_match = index in matched
        if state is None:
            state = is_match
            buf = [ch]
        elif is_match == state:
            buf.append(ch)
        else:
            runs.append(("".join(buf), state))
            buf = [ch]
            state = is_match
    if state is not None:
        runs.append(("".join(buf), state))
    return runs


MaxTagNameLength = 245


def create_tag_error(name: str, local_tags: Mapping[str, str] | None = None) -> str | None:
    """Desktop `CreateTag.getCurrentError` copy."""
    if len(name) > MaxTagNameLength:
        return f"The tag name cannot be longer than {MaxTagNameLength} characters"
    if local_tags is not None and name in local_tags:
        return f"A tag named {name} already exists"
    return None


# Desktop `sanitize-ref-name.ts` / git-check-ref-format: ASCII control and space,
# DEL, ~ ^ : ? * [ \ | " < >, the magic sequence @{, consecutive dots, leading
# and trailing dot, ref ending in .lock, trailing slash.
_INVALID_REF_NAME_RE = re.compile(
    r"[\x00-\x20\x7F~^:?*\[\\|\"<>]+|@\{|\.\.+|^\.|\.$|\.lock$|/$"
)


def sanitize_ref_name(name: str) -> str:
    """Desktop `sanitizedRefName`: replace illegal characters with hyphens."""
    return _INVALID_REF_NAME_RE.sub("-", name).lstrip("-+")


def sanitized_ref_name(name: str) -> str:
    """Desktop `sanitizedRefName` alias."""
    return sanitize_ref_name(name)


def test_for_invalid_chars(name: str) -> bool:
    """Desktop `testForInvalidChars`."""
    return _INVALID_REF_NAME_RE.search(name) is not None
