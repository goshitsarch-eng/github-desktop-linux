"""Desktop `lib/stats/stats-store.ts` — opt-in usage reporting for Linux."""

from __future__ import annotations

import json
import os
import platform
import threading
import time
import urllib.error
import urllib.request
import uuid
from copy import deepcopy
from typing import Any, Callable, Mapping, Sequence

from .linux import get_architecture, get_os
from .local_storage import (
    get_boolean,
    get_item,
    get_number,
    get_number_array,
    remove_item,
    set_boolean,
    set_item,
    set_number,
    set_number_array,
)
from .logging import get_logger
from .models import Account, Repository
from .paths import config_dir
from .settings import (
    Settings,
    showChangesFilterDefault,
    showChangesFilterKey,
    showDiffCheckMarksDefault,
    showDiffCheckMarksKey,
    underlineLinksDefault,
    underlineLinksKey,
    useCustomEditorKey,
    useCustomShellKey,
)
from .version import APP_NAME, __version__
from .welcome import has_shown_welcome_flow

log = get_logger()

StatsEndpoint = "https://central.github.com/api/usage/desktop"
SamplesURL = "https://desktop.github.com/usage-data/"

LastDailyStatsReportKey = "last-daily-stats-report"
StatsOptOutKey = "stats-opt-out"
HasSentOptInPingKey = "has-sent-stats-opt-in-ping"
StatsGUIDKey = "stats-guid"

WelcomeWizardInitiatedAtKey = "welcome-wizard-initiated-at"
WelcomeWizardCompletedAtKey = "welcome-wizard-terminated-at"
FirstRepositoryAddedAtKey = "first-repository-added-at"
FirstRepositoryClonedAtKey = "first-repository-cloned-at"
FirstRepositoryCreatedAtKey = "first-repository-created-at"
FirstCommitCreatedAtKey = "first-commit-created-at"
FirstPushToGitHubAtKey = "first-push-to-github-at"
FirstNonDefaultBranchCheckoutAtKey = "first-non-default-branch-checkout-at"

RepositoriesCommittedInWithoutWriteAccessKey = "repositories-committed-in-without-write-access"

DailyStatsReportInterval = 1000 * 60 * 60 * 24
SendStatsInterval = 4 * 60 * 60

DefaultDailyMeasures: dict[str, Any] = {
    "commits": 0,
    "partialCommits": 0,
    "openShellCount": 0,
    "coAuthoredCommits": 0,
    "commitsUndoneWithChanges": 0,
    "commitsUndoneWithoutChanges": 0,
    "branchComparisons": 0,
    "defaultBranchComparisons": 0,
    "mergesInitiatedFromComparison": 0,
    "updateFromDefaultBranchMenuCount": 0,
    "mergeIntoCurrentBranchMenuCount": 0,
    "prBranchCheckouts": 0,
    "repoWithIndicatorClicked": 0,
    "repoWithoutIndicatorClicked": 0,
    "dotcomPushCount": 0,
    "dotcomForcePushCount": 0,
    "enterprisePushCount": 0,
    "enterpriseForcePushCount": 0,
    "externalPushCount": 0,
    "externalForcePushCount": 0,
    "active": False,
    "mergeConflictFromPullCount": 0,
    "mergeConflictFromExplicitMergeCount": 0,
    "mergedWithLoadingHintCount": 0,
    "mergedWithCleanMergeHintCount": 0,
    "mergedWithConflictWarningHintCount": 0,
    "mergeSuccessAfterConflictsCount": 0,
    "mergeAbortedAfterConflictsCount": 0,
    "unattributedCommits": 0,
    "enterpriseCommits": 0,
    "dotcomCommits": 0,
    "mergeConflictsDialogDismissalCount": 0,
    "anyConflictsLeftOnMergeConflictsDialogDismissalCount": 0,
    "mergeConflictsDialogReopenedCount": 0,
    "guidedConflictedMergeCompletionCount": 0,
    "unguidedConflictedMergeCompletionCount": 0,
    "createPullRequestCount": 0,
    "createPullRequestFromPreviewCount": 0,
    "rebaseConflictsDialogDismissalCount": 0,
    "rebaseConflictsDialogReopenedCount": 0,
    "rebaseAbortedAfterConflictsCount": 0,
    "rebaseSuccessAfterConflictsCount": 0,
    "rebaseSuccessWithoutConflictsCount": 0,
    "rebaseWithBranchAlreadyUpToDateCount": 0,
    "pullWithRebaseCount": 0,
    "pullWithDefaultSettingCount": 0,
    "stashEntriesCreatedOutsideDesktop": 0,
    "errorWhenSwitchingBranchesWithUncommmittedChanges": 0,
    "rebaseCurrentBranchMenuCount": 0,
    "stashViewedAfterCheckoutCount": 0,
    "stashCreatedOnCurrentBranchCount": 0,
    "stashNotViewedAfterCheckoutCount": 0,
    "changesTakenToNewBranchCount": 0,
    "stashRestoreCount": 0,
    "stashDiscardCount": 0,
    "stashViewCount": 0,
    "noActionTakenOnStashCount": 0,
    "suggestedStepOpenInExternalEditor": 0,
    "suggestedStepOpenWorkingDirectory": 0,
    "suggestedStepViewOnGitHub": 0,
    "suggestedStepPublishRepository": 0,
    "suggestedStepPublishBranch": 0,
    "suggestedStepCreatePullRequest": 0,
    "suggestedStepViewStash": 0,
    "commitsToProtectedBranch": 0,
    "commitsToRepositoryWithBranchProtections": 0,
    "tutorialStarted": False,
    "tutorialRepoCreated": False,
    "tutorialEditorInstalled": False,
    "tutorialBranchCreated": False,
    "tutorialFileEdited": False,
    "tutorialCommitCreated": False,
    "tutorialBranchPushed": False,
    "tutorialPrCreated": False,
    "tutorialCompleted": False,
    "highestTutorialStepCompleted": -1,
    "commitsToRepositoryWithoutWriteAccess": 0,
    "forksCreated": 0,
    "issueCreationWebpageOpenedCount": 0,
    "tagsCreatedInDesktop": 0,
    "tagsCreated": 0,
    "tagsDeleted": 0,
    "diffModeChangeCount": 0,
    "diffOptionsViewedCount": 0,
    "repositoryViewChangeCount": 0,
    "unhandledRejectionCount": 0,
    "cherryPickSuccessfulCount": 0,
    "cherryPickViaDragAndDropCount": 0,
    "cherryPickViaContextMenuCount": 0,
    "dragStartedAndCanceledCount": 0,
    "cherryPickConflictsEncounteredCount": 0,
    "cherryPickSuccessfulWithConflictsCount": 0,
    "cherryPickMultipleCommitsCount": 0,
    "cherryPickUndoneCount": 0,
    "cherryPickBranchCreatedCount": 0,
    "amendCommitStartedCount": 0,
    "amendCommitSuccessfulWithFileChangesCount": 0,
    "amendCommitSuccessfulWithoutFileChangesCount": 0,
    "reorderSuccessfulCount": 0,
    "reorderStartedCount": 0,
    "reorderConflictsEncounteredCount": 0,
    "reorderSuccessfulWithConflictsCount": 0,
    "reorderMultipleCommitsCount": 0,
    "reorderUndoneCount": 0,
    "squashConflictsEncounteredCount": 0,
    "squashMultipleCommitsInvokedCount": 0,
    "squashSuccessfulCount": 0,
    "squashSuccessfulWithConflictsCount": 0,
    "squashViaContextMenuInvokedCount": 0,
    "squashViaDragAndDropInvokedCount": 0,
    "squashUndoneCount": 0,
    "squashMergeIntoCurrentBranchMenuCount": 0,
    "squashMergeSuccessfulWithConflictsCount": 0,
    "squashMergeSuccessfulCount": 0,
    "squashMergeInvokedCount": 0,
    "resetToCommitCount": 0,
    "opensCheckRunsPopover": 0,
    "viewsCheckOnline": 0,
    "viewsCheckJobStepOnline": 0,
    "rerunsChecks": 0,
    "checksFailedNotificationCount": 0,
    "checksFailedNotificationFromRecentRepoCount": 0,
    "checksFailedNotificationFromNonRecentRepoCount": 0,
    "checksFailedNotificationClicked": 0,
    "checksFailedDialogOpenCount": 0,
    "checksFailedDialogSwitchToPullRequestCount": 0,
    "checksFailedDialogRerunChecksCount": 0,
    "pullRequestReviewNotificationFromRecentRepoCount": 0,
    "pullRequestReviewNotificationFromNonRecentRepoCount": 0,
    "pullRequestReviewApprovedNotificationCount": 0,
    "pullRequestReviewApprovedNotificationClicked": 0,
    "pullRequestReviewApprovedDialogSwitchToPullRequestCount": 0,
    "pullRequestReviewCommentedNotificationCount": 0,
    "pullRequestReviewCommentedNotificationClicked": 0,
    "pullRequestReviewCommentedDialogSwitchToPullRequestCount": 0,
    "pullRequestReviewChangesRequestedNotificationCount": 0,
    "pullRequestReviewChangesRequestedNotificationClicked": 0,
    "pullRequestReviewChangesRequestedDialogSwitchToPullRequestCount": 0,
    "pullRequestCommentNotificationCount": 0,
    "pullRequestCommentNotificationClicked": 0,
    "pullRequestCommentNotificationFromNonRecentRepoCount": 0,
    "pullRequestCommentNotificationFromRecentRepoCount": 0,
    "pullRequestCommentDialogSwitchToPullRequestCount": 0,
    "multiCommitDiffWithUnreachableCommitWarningCount": 0,
    "multiCommitDiffFromHistoryCount": 0,
    "multiCommitDiffFromCompareCount": 0,
    "multiCommitDiffUnreachableCommitsDialogOpenedCount": 0,
    "submoduleDiffViewedFromChangesListCount": 0,
    "submoduleDiffViewedFromHistoryCount": 0,
    "openSubmoduleFromDiffCount": 0,
    "previewedPullRequestCount": 0,
    "typedInChangesFilterCount": 0,
    "appliesIncludedInCommitFilterCount": 0,
    "appliesExcludedFromCommitFilterCount": 0,
    "appliesNewFilesChangesFilterCount": 0,
    "appliesModifiedFilesChangesFilterCount": 0,
    "appliesDeletedFilesChangesFilterCount": 0,
    "appliesClearAllChangesListFilterCount": 0,
    "adjustedFiltersForHiddenChangesCount": 0,
    "enterpriseAccountCount": 0,
    "generateCommitMessageButtonClickCount": 0,
    "generateCommitMessageCount": 0,
    "generateCommitMessageUsedVerbatimCount": 0,
    "pushBlockedBySecretScanningCount": 0,
    "secretsDetectedOnPushCount": 0,
    "secretsDetectedOnPushBypassedCount": 0,
    "secretsDetectedOnPushBypassedAsFalsePositiveCount": 0,
    "secretsDetectedOnPushBypassedAsUsedInTestCount": 0,
    "secretsDetectedOnPushBypassedAsWillFixLaterCount": 0,
    "secretsDetectedOnPushDelegatedBypassLinkClickedCount": 0,
    "secretRemediationInstructionsLinkClickedCount": 0,
}

NUMERIC_MEASURES = {key for key, value in DefaultDailyMeasures.items() if isinstance(value, (int, float)) and not isinstance(value, bool)}

_guid_cache: dict[str, str] = {}


class StatsResponse:
    """Stand-in for `fetch` Response used by Desktop `defaultPostImplementation`."""

    def __init__(self, status: int, status_text: str = "") -> None:
        self.status = status
        self.statusText = status_text
        self.ok = 200 <= status < 300


def env_skips_stats_network() -> bool:
    """Desktop `__DEV__` / `TEST_ENV` plus native pytest and offline guards."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if os.environ.get("TEST_ENV"):
        return True
    if os.environ.get("GITHUB_DESKTOP_DEV"):
        return True
    if os.environ.get("GITHUB_DESKTOP_OFFLINE"):
        return True
    return False


def get_has_opted_out_of_stats() -> bool | None:
    """Desktop `getHasOptedOutOfStats`."""
    return get_boolean(StatsOptOutKey)


def get_renderer_guid() -> str:
    """Desktop `getRendererGUID` — persist a stable install id in localStorage."""
    path_key = str(config_dir() / "local-storage.json")
    cached = _guid_cache.get(path_key)
    if cached:
        return cached
    guid = get_item(StatsGUIDKey)
    if not guid:
        guid = str(uuid.uuid4())
        set_item(StatsGUIDKey, guid)
    _guid_cache[path_key] = guid
    return guid


def create_local_storage_timestamp(key: str) -> None:
    """Store Date.now() once for an onboarding metric."""
    if get_item(key) is None:
        set_number(key, int(time.time() * 1000))


def get_local_storage_timestamp(key: str) -> int | None:
    return get_number(key)


def time_to(key: str) -> int | None:
    """Seconds from welcome-wizard start to `key`, or -1 if the action has not happened."""
    start_time = get_local_storage_timestamp(WelcomeWizardInitiatedAtKey)
    if start_time is None:
        return None
    end_time = get_local_storage_timestamp(key)
    if end_time is None or end_time <= start_time:
        return -1
    return round((end_time - start_time) / 1000)


def _user_agent() -> str:
    from .github.api import USER_AGENT

    return USER_AGENT


def default_post_implementation(body: Mapping[str, Any]) -> StatsResponse:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        StatsEndpoint,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "User-Agent": _user_agent(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return StatsResponse(getattr(resp, "status", 200) or 200, getattr(resp, "reason", "") or "")
    except urllib.error.HTTPError as exc:
        return StatsResponse(exc.code, exc.reason or "")


def _stats_db_path():
    return config_dir() / "stats-database.json"


class StatsDatabase:
    """JSON stand-in for Desktop `StatsDatabase` (Dexie launches + dailyMeasures)."""

    def __init__(self) -> None:
        self.launches: list[dict[str, float]] = []
        self.daily_measures: dict[str, Any] = deepcopy(DefaultDailyMeasures)
        self._load()

    def _load(self) -> None:
        path = _stats_db_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        if not isinstance(raw, dict):
            return
        launches = raw.get("launches")
        if isinstance(launches, list):
            self.launches = [item for item in launches if isinstance(item, dict)]
        measures = raw.get("dailyMeasures")
        if isinstance(measures, dict):
            merged = deepcopy(DefaultDailyMeasures)
            merged.update(measures)
            merged.pop("id", None)
            self.daily_measures = merged

    def save(self) -> None:
        path = _stats_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"launches": self.launches, "dailyMeasures": {k: v for k, v in self.daily_measures.items() if k != "id"}}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def clear(self) -> None:
        self.launches = []
        self.daily_measures = deepcopy(DefaultDailyMeasures)
        self.save()


class StatsStore:
    """Desktop `StatsStore`. Native default is opted **out** until the user opts in."""

    def __init__(
        self,
        post: Callable[[Mapping[str, Any]], StatsResponse] | None = None,
        *,
        default_opt_out: bool = True,
    ) -> None:
        self.db = StatsDatabase()
        self._post = post or default_post_implementation
        self._custom_post = post is not None
        self._lock = threading.Lock()
        self._activity_armed = True
        stored = get_has_opted_out_of_stats()
        self.opt_out = stored if stored is not None else bool(default_opt_out)
        # Native default is opted out. Don't ping Central until localStorage
        # `stats-opt-out` is set (prefs / setOptOut), unlike Desktop's opted-in default.
        if (
            stored is not None
            and not get_boolean(HasSentOptInPingKey, False)
            and not env_skips_stats_network()
        ):
            self.send_opt_in_status_ping(self.opt_out, stored)

    def get_opt_out(self) -> bool:
        return self.opt_out

    def _skip_network(self) -> bool:
        if self._custom_post:
            return False
        return env_skips_stats_network()

    def should_report_daily_stats(self) -> bool:
        last_date = get_number(LastDailyStatsReportKey, 0) or 0
        now = int(time.time() * 1000)
        return now - last_date > DailyStatsReportInterval

    def report_stats(
        self,
        accounts: Sequence[Account],
        repositories: Sequence[Repository],
        settings: Settings | None = None,
    ) -> None:
        """Desktop `reportStats`."""
        if self.opt_out:
            return
        if self._skip_network():
            return
        if not has_shown_welcome_flow(settings.welcome_shown if settings is not None else False):
            return
        if not self.should_report_daily_stats():
            return
        now = int(time.time() * 1000)
        payload = self.get_daily_stats(accounts, repositories, settings)
        try:
            response = self._post(payload)
            if not response.ok:
                raise RuntimeError(f"Unexpected status: {response.statusText} ({response.status})")
            log.info("Stats reported.")
            self.clear_daily_stats()
            set_number(LastDailyStatsReportKey, now)
        except Exception as exc:
            log.error("Error reporting stats: %s", exc)

    def record_launch_stats(self, stats: Mapping[str, float]) -> None:
        with self._lock:
            self.db.launches.append(
                {
                    "mainReadyTime": float(stats.get("mainReadyTime", -1)),
                    "loadTime": float(stats.get("loadTime", -1)),
                    "rendererReadyTime": float(stats.get("rendererReadyTime", -1)),
                }
            )
            self.db.save()

    def clear_daily_stats(self) -> None:
        with self._lock:
            self.db.clear()
        remove_item(RepositoriesCommittedInWithoutWriteAccessKey)
        self._activity_armed = True

    def note_ui_activity(self) -> None:
        if not self._activity_armed:
            return
        self._activity_armed = False
        self.update_daily_measures(lambda _m: {"active": True})

    def get_daily_measures(self) -> dict[str, Any]:
        with self._lock:
            measures = deepcopy(DefaultDailyMeasures)
            measures.update(self.db.daily_measures)
            measures.pop("id", None)
            return measures

    def update_daily_measures(self, fn: Callable[[dict[str, Any]], Mapping[str, Any]]) -> None:
        with self._lock:
            current = deepcopy(DefaultDailyMeasures)
            current.update(self.db.daily_measures)
            current.pop("id", None)
            current.update(dict(fn(current)))
            self.db.daily_measures = current
            self.db.save()

    def increment(self, key: str, n: int = 1) -> None:
        if key not in NUMERIC_MEASURES:
            return
        self.update_daily_measures(lambda m: {key: int(m.get(key) or 0) + n})

    incrementMetric = increment

    def get_average_launch_stats(self) -> dict[str, float]:
        with self._lock:
            launches = list(self.db.launches)
        if not launches:
            return {"mainReadyTime": -1, "loadTime": -1, "rendererReadyTime": -1}
        count = len(launches)
        return {
            "mainReadyTime": sum(float(item.get("mainReadyTime") or 0) for item in launches) / count,
            "loadTime": sum(float(item.get("loadTime") or 0) for item in launches) / count,
            "rendererReadyTime": sum(float(item.get("rendererReadyTime") or 0) for item in launches) / count,
        }

    def categorized_repository_counts(self, repositories: Sequence[Repository]) -> dict[str, int]:
        return {
            "repositoryCount": len(repositories),
            "gitHubRepositoryCount": sum(1 for repo in repositories if repo.github),
        }

    def determine_user_type(self, accounts: Sequence[Account]) -> dict[str, Any]:
        return {
            "dotComAccount": any(account.is_dotcom for account in accounts),
            "enterpriseAccount": any(account.is_enterprise for account in accounts),
            "enterpriseAccountCount": sum(1 for account in accounts if account.is_enterprise),
        }

    def get_onboarding_stats(self) -> dict[str, int]:
        if get_local_storage_timestamp(WelcomeWizardInitiatedAtKey) is None:
            return {}
        stats: dict[str, int] = {}
        mapping = {
            "timeToWelcomeWizardTerminated": WelcomeWizardCompletedAtKey,
            "timeToFirstAddedRepository": FirstRepositoryAddedAtKey,
            "timeToFirstClonedRepository": FirstRepositoryClonedAtKey,
            "timeToFirstCreatedRepository": FirstRepositoryCreatedAtKey,
            "timeToFirstCommit": FirstCommitCreatedAtKey,
            "timeToFirstGitHubPush": FirstPushToGitHubAtKey,
            "timeToFirstNonDefaultBranchCheckout": FirstNonDefaultBranchCheckoutAtKey,
        }
        for field, key in mapping.items():
            value = time_to(key)
            if value is not None:
                stats[field] = value
        return stats

    def get_daily_stats(
        self,
        accounts: Sequence[Account],
        repositories: Sequence[Repository],
        settings: Settings | None = None,
    ) -> dict[str, Any]:
        s = settings if settings is not None else Settings()
        use_custom_shell = bool(s.use_custom_shell) if settings is not None else bool(get_boolean(useCustomShellKey, False))
        use_custom_editor = bool(s.use_custom_editor) if settings is not None else bool(get_boolean(useCustomEditorKey, False))
        selected_terminal = "custom" if use_custom_shell else (s.selected_shell or "none")
        selected_editor = "custom" if use_custom_editor else (s.selected_external_editor or "none")
        payload: dict[str, Any] = {
            "eventType": "usage",
            "version": __version__,
            "osVersion": get_os(),
            "platform": sys_platform(),
            "architecture": get_architecture(),
            "theme": s.theme,
            "selectedTerminalEmulator": selected_terminal,
            "selectedTextEditor": selected_editor,
            "notificationsEnabled": s.notifications_enabled,
            **self.get_average_launch_stats(),
            **self.get_daily_measures(),
            **self.determine_user_type(accounts),
            **self.get_onboarding_stats(),
            "guid": get_renderer_guid(),
            **self.categorized_repository_counts(repositories),
            "repositoriesCommittedInWithoutWriteAccess": len(get_number_array(RepositoriesCommittedInWithoutWriteAccessKey)),
            "diffMode": "split" if s.show_side_by_side_diff else "unified",
            "launchedFromApplicationsFolder": None,
            "linkUnderlinesVisible": s.underline_links if settings is not None else bool(get_boolean(underlineLinksKey, underlineLinksDefault)),
            "diffCheckMarksVisible": s.show_diff_check_marks if settings is not None else bool(get_boolean(showDiffCheckMarksKey, showDiffCheckMarksDefault)),
            "useExternalCredentialHelper": s.use_external_credential_helper,
            "filteringChangesEnabled": s.show_changes_filter if settings is not None else bool(get_boolean(showChangesFilterKey, showChangesFilterDefault)),
        }
        payload.pop("id", None)
        return payload

    def set_opt_out(self, opt_out: bool, user_viewed_prompt: bool = False) -> None:
        """Desktop `setOptOut`."""
        changed = self.opt_out != opt_out
        self.opt_out = opt_out
        previous_value = get_boolean(StatsOptOutKey)
        set_boolean(StatsOptOutKey, opt_out)
        if changed or user_viewed_prompt:
            self.send_opt_in_status_ping(opt_out, previous_value)

    def send_opt_in_status_ping(self, opt_out: bool, previous_value: bool | None) -> None:
        if self._skip_network():
            return
        opt_in = not opt_out
        previous_opt_in = None if previous_value is None else (not previous_value)
        direction = "in" if opt_in else "out"
        try:
            response = self._post(
                {
                    "eventType": "ping",
                    "optIn": opt_in,
                    "previousOptInValue": previous_opt_in,
                }
            )
            if not response.ok:
                raise RuntimeError(f"Unexpected status: {response.statusText} ({response.status})")
            set_boolean(HasSentOptInPingKey, True)
            log.info("Opt %s reported.", direction)
        except Exception as exc:
            log.error("Error reporting opt %s: %s", direction, exc)

    def record_commit(self) -> None:
        self.increment("commits")
        create_local_storage_timestamp(FirstCommitCreatedAtKey)

    def record_commit_undone(self, clean_working_directory: bool) -> None:
        self.increment("commitsUndoneWithoutChanges" if clean_working_directory else "commitsUndoneWithChanges")

    def record_amend_commit_successful(self, with_file_changes: bool) -> None:
        self.increment(
            "amendCommitSuccessfulWithFileChangesCount" if with_file_changes else "amendCommitSuccessfulWithoutFileChangesCount"
        )

    def record_push(self, account: Account | None, *, force_with_lease: bool = False) -> None:
        if account is None:
            self.increment("externalForcePushCount" if force_with_lease else "externalPushCount")
            return
        if account.is_dotcom:
            self.increment("dotcomForcePushCount" if force_with_lease else "dotcomPushCount")
        else:
            self.increment("enterpriseForcePushCount" if force_with_lease else "enterprisePushCount")
        create_local_storage_timestamp(FirstPushToGitHubAtKey)

    def record_welcome_wizard_initiated(self) -> None:
        set_number(WelcomeWizardInitiatedAtKey, int(time.time() * 1000))
        remove_item(WelcomeWizardCompletedAtKey)

    def record_welcome_wizard_terminated(self) -> None:
        set_number(WelcomeWizardCompletedAtKey, int(time.time() * 1000))

    def record_add_existing_repository(self) -> None:
        create_local_storage_timestamp(FirstRepositoryAddedAtKey)

    def record_clone_repository(self) -> None:
        create_local_storage_timestamp(FirstRepositoryClonedAtKey)

    def record_create_repository(self) -> None:
        create_local_storage_timestamp(FirstRepositoryCreatedAtKey)

    def record_non_default_branch_checkout(self) -> None:
        create_local_storage_timestamp(FirstNonDefaultBranchCheckoutAtKey)

    def record_repository_committed_in_without_write_access(self, github_repository_db_id: int) -> None:
        ids = [int(item) for item in get_number_array(RepositoriesCommittedInWithoutWriteAccessKey)]
        if github_repository_db_id not in ids:
            set_number_array(RepositoriesCommittedInWithoutWriteAccessKey, [*ids, github_repository_db_id])


def sys_platform() -> str:
    """Electron `process.platform` equivalent (`linux` / `darwin` / `win32`)."""
    name = platform.system().lower()
    if name == "darwin":
        return "darwin"
    if name == "windows":
        return "win32"
    return "linux"


# Keep Desktop's product name in the payload User-Agent path for grep/parity.
_APP_USER_AGENT_NAME = APP_NAME
