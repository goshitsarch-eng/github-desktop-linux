"""The object QML binds to.

:class:`AppBridge` is the single context property the QML tree sees. It reads
:class:`~github_desktop.store.AppStore` and re-emits its coarse ``emit()`` as
one ``changed`` signal; every declarative property below is a plain getter, so
QML re-evaluates whatever it displays and nothing else. Actions travel the
other way as slots.

Rows for list views live in :mod:`github_desktop.ui.models`, which snapshots
and diffs them so a refresh does not throw away selection or scroll position.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from PySide6.QtCore import QObject, Property, Signal, Slot

from ..models import (
    AppFileStatusKind,
    BannerType,
    BranchType,
    ChangesListFilter,
    DiffSelectionType,
    MultiCommitOperationKind,
    PopupType,
    PreferencesTab,
    RepositorySectionTab,
    TutorialStep,
    enable_commit_message_generation,
)
from ..push_pull import describe_push_pull, format_commit_relative_time, format_last_fetched
from ..text_tokens import summary_completeness
from ..shells import open_external
from ..version import APP_NAME, __version__
from .icons import icon_name
from .window import NO_HISTORY
from .menus import (
    GENERATE_COMMIT_MESSAGE_WITH_COPILOT,
    GENERATING_COMMIT_DETAILS,
    NO_FILES_SELECTED_FOR_GENERATION,
)
from .models import make_model

CONFLICT_BANNERS = {
    BannerType.MERGE_CONFLICTS_FOUND,
    BannerType.REBASE_CONFLICTS_FOUND,
    BannerType.CHERRY_PICK_CONFLICTS_FOUND,
}
SUCCESS_BANNERS = {
    BannerType.SUCCESSFUL_MERGE,
    BannerType.SUCCESSFUL_REBASE,
    BannerType.SUCCESSFUL_CHERRY_PICK,
    BannerType.SUCCESSFUL_SQUASH,
}

# Breeze status colors for the changed-file badges, matching Kate's diff view.
STATUS_COLORS = {
    AppFileStatusKind.NEW.value: "positive",
    AppFileStatusKind.MODIFIED.value: "neutral",
    AppFileStatusKind.DELETED.value: "negative",
    AppFileStatusKind.RENAMED.value: "neutral",
    AppFileStatusKind.COPIED.value: "neutral",
    AppFileStatusKind.CONFLICTED.value: "negative",
    AppFileStatusKind.UNTRACKED.value: "positive",
}
STATUS_LETTERS = {
    AppFileStatusKind.NEW.value: "A",
    AppFileStatusKind.MODIFIED.value: "M",
    AppFileStatusKind.DELETED.value: "D",
    AppFileStatusKind.RENAMED.value: "R",
    AppFileStatusKind.COPIED.value: "C",
    AppFileStatusKind.CONFLICTED.value: "!",
    AppFileStatusKind.UNTRACKED.value: "U",
}


def _relative(when: Any) -> str:
    """Relative time for a timestamp that may be missing (an unfetched tip)."""
    if when is None:
        return ""
    try:
        return format_commit_relative_time(when)
    except Exception:
        return ""


def _is_conflicted(file: Any) -> bool:
    kind = getattr(getattr(file, "status", None), "kind", None)
    return getattr(kind, "value", kind) == AppFileStatusKind.CONFLICTED.value


def _selection_state(file: Any) -> int:
    """0 unchecked, 1 checked, 2 partial -- the tri-state a CheckBox wants."""
    selection = getattr(file, "selection", None)
    if selection is None:
        return 1
    kind = selection.kind if hasattr(selection, "kind") else None
    if kind == DiffSelectionType.ALL:
        return 1
    if kind == DiffSelectionType.NONE:
        return 0
    return 2


class AppBridge(QObject):
    """Root context object exposed to QML as ``app``."""

    changed = Signal()
    popupRequested = Signal(str, "QVariant")
    toast = Signal(str)
    windowInfo = Signal(str, int)
    commitMessageFocusRequested = Signal()
    #: Desktop `setFocusChangesNeeded` / `setFocusHistoryNeeded`.
    focusRequested = Signal(str)

    def __init__(self, store, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._suppress = False
        self._last_zoom = store.settings.zoom_factor
        self._active_resizable = ""
        self._modal_open = False
        self._dragging_commit = False
        self._build_models()
        store.subscribe(self._on_store_changed)
        store.api_repositories.subscribe(self._on_store_changed)

    # -- store plumbing ----------------------------------------------------

    def _on_store_changed(self) -> None:
        if self._suppress:
            return
        self._refresh_models()
        self.changed.emit()
        zoom = self.store.settings.zoom_factor
        if zoom != self._last_zoom:
            self._last_zoom = zoom
            self.windowInfo.emit(f"{round(zoom * 100)}%", 750)
        for popup in self.store.take_popups():
            self.popupRequested.emit(str(popup.type), dict(popup.payload or {}))
        if self.store.focus_commit_message:
            self.commitMessageFocusRequested.emit()

    def _repo(self):
        return self.store.selected_repository

    def _state(self):
        repo = self._repo()
        return self.store.state_for(repo) if repo else None

    def _with_repo(self, action: Callable[[Any], Any]) -> None:
        repo = self._repo()
        if repo is None:
            return
        try:
            action(repo)
        except Exception as exc:
            self.store.show_popup(PopupType.ERROR, error=str(exc))

    # -- models ------------------------------------------------------------

    def _build_models(self) -> None:
        self._repositories = make_model(
            (
                "repoId",
                "name",
                "path",
                "owner",
                "group",
                "isMissing",
                "isCloning",
                "hasChanges",
                "aheadBehind",
                "icon",
                "tooltip",
            ),
            self._repository_rows,
        )
        self._changed_files = make_model(
            (
                "path",
                "name",
                "directory",
                "statusKind",
                "statusLetter",
                "statusColor",
                "included",
                "isConflicted",
                "isSubmodule",
                "isSelected",
                "fileId",
            ),
            self._changed_file_rows,
        )
        self._commits = make_model(
            (
                "sha",
                "shortSha",
                "summary",
                "body",
                "author",
                "authorEmail",
                "avatarUrl",
                "relativeTime",
                "isLocal",
                "isSelected",
                "tags",
                "isMergeCommit",
            ),
            self._commit_rows,
        )
        self._commit_files = make_model(
            ("path", "name", "directory", "statusKind", "statusLetter", "statusColor", "isSelected"),
            self._commit_file_rows,
        )
        self._branches = make_model(
            ("name", "kind", "group", "isCurrent", "relativeTime", "upstream", "sha"),
            self._branch_rows,
        )
        self._pull_requests = make_model(
            ("number", "title", "author", "branch", "relativeTime", "checkState", "draft"),
            self._pull_request_rows,
        )
        self._diff_rows = make_model(
            (
                "kind",
                "text",
                "markup",
                "oldNumber",
                "newNumber",
                "lineType",
                "included",
                "hunkIndex",
                "diffIndex",
                "expansion",
                "selectable",
            ),
            self._diff_row_list,
        )
        self._stashes = make_model(("name", "branch", "sha", "relativeTime"), self._stash_rows)
        self._stashed_files = make_model(
            ("path", "name", "directory", "statusKind", "statusLetter", "statusColor", "isSelected"),
            self._stashed_file_rows,
        )
        self._check_runs = make_model(
            ("name", "description", "state", "icon", "url", "checkId"), self._check_run_rows
        )
        self._co_authors = make_model(("name", "email", "username"), self._co_author_rows)
        self._models = (
            self._repositories,
            self._changed_files,
            self._commits,
            self._commit_files,
            self._branches,
            self._pull_requests,
            self._diff_rows,
            self._stashes,
            self._stashed_files,
            self._check_runs,
            self._co_authors,
        )
        self._refresh_models()

    def _refresh_models(self) -> None:
        for model in self._models:
            model.refresh()

    # -- row builders ------------------------------------------------------

    def _repository_rows(self) -> list[dict]:
        from ..group_repositories import group_repositories

        rows: list[dict] = []
        needle = self.store.repository_filter_text
        for cloning in self.store.cloning:
            rows.append(
                {
                    "repoId": -1,
                    "name": cloning.name,
                    "path": cloning.path,
                    "owner": "",
                    "group": "Cloning",
                    "isMissing": False,
                    "isCloning": True,
                    "hasChanges": False,
                    "aheadBehind": "",
                    "icon": icon_name("clone"),
                    "tooltip": cloning.url,
                }
            )
        indicators = self.store.settings.repository_indicators_enabled
        for group in group_repositories(
            self.store.repositories, self.store.settings.recent_repository_ids
        ):
            for item in group.items:
                repo = item.repository
                if needle and not _matches_repository(repo, needle):
                    continue
                github = getattr(repo, "github", None)
                # Desktop disambiguates same-named repos by showing owner/name.
                name = repo.display_name
                if item.needs_disambiguation and github:
                    name = github.full_name
                state = self.store.state_for(repo)
                ahead_behind = state.ahead_behind if indicators else None
                badge = ""
                if ahead_behind:
                    parts = []
                    if ahead_behind.ahead:
                        parts.append(f"\u2191{ahead_behind.ahead}")
                    if ahead_behind.behind:
                        parts.append(f"\u2193{ahead_behind.behind}")
                    badge = " ".join(parts)
                has_changes = bool(
                    indicators
                    and state.status
                    and state.status.working_directory.files
                )
                rows.append(
                    {
                        "repoId": repo.id,
                        "name": name,
                        "path": repo.path,
                        "owner": getattr(getattr(github, "owner", None), "login", "") or "",
                        "group": group.label,
                        "isMissing": bool(repo.is_missing),
                        "isCloning": False,
                        "hasChanges": has_changes,
                        "aheadBehind": badge,
                        "icon": icon_name("repository-remote" if github else "repository"),
                        "tooltip": "Can\u2019t find this repository" if repo.is_missing else repo.path,
                    }
                )
        return rows

    def _file_row(self, file: Any, *, selected_ids: list[str]) -> dict:
        status = getattr(file, "status", None)
        kind = getattr(getattr(status, "kind", None), "value", "") or ""
        path = file.path
        directory, _, name = path.rpartition("/")
        return {
            "path": path,
            "name": name or path,
            "directory": directory,
            "statusKind": kind,
            "statusLetter": STATUS_LETTERS.get(kind, "?"),
            "statusColor": STATUS_COLORS.get(kind, "neutral"),
            "included": _selection_state(file),
            "isConflicted": kind == AppFileStatusKind.CONFLICTED.value,
            "isSubmodule": getattr(status, "submodule_status", None) is not None,
            "isSelected": getattr(file, "id", path) in selected_ids,
            "fileId": getattr(file, "id", path),
        }

    def _changed_file_rows(self) -> list[dict]:
        state = self._state()
        if state is None or state.status is None:
            return []
        from ..filter_changes import file_list_filter_state_from_view, filter_changed_files

        files = filter_changed_files(
            list(state.status.working_directory.files),
            file_list_filter_state_from_view(state),
        )
        selected = list(state.selected_file_ids)
        return [self._file_row(f, selected_ids=selected) for f in files]

    def _commit_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        selected = {c.sha for c in (state.selected_commits or [])}
        local = set(state.local_commit_shas or [])
        rows = []
        for commit in state.commits:
            author = commit.author
            rows.append(
                {
                    "sha": commit.sha,
                    "shortSha": commit.short_sha,
                    "summary": commit.summary,
                    "body": commit.body,
                    "author": getattr(author, "name", "") or "",
                    "authorEmail": getattr(author, "email", "") or "",
                    "avatarUrl": self._avatar_url(getattr(author, "email", "")),
                    "relativeTime": _relative(getattr(author, "date", None)),
                    "isLocal": commit.sha in local,
                    "isSelected": commit.sha in selected,
                    "tags": list(getattr(commit, "tags", []) or []),
                    "isMergeCommit": len(getattr(commit, "parent_shas", []) or []) > 1,
                }
            )
        return rows

    def _commit_file_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        selected = getattr(state.selected_file, "path", None)
        return [
            {
                **{
                    key: value
                    for key, value in self._file_row(f, selected_ids=[]).items()
                    if key in {"path", "name", "directory", "statusKind", "statusLetter", "statusColor"}
                },
                "isSelected": f.path == selected,
            }
            for f in state.selected_commit_files
        ]

    def _branch_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        from .branches import group_branches

        repo = self._repo()
        current = state.status.current_branch if state.status else None
        recent = list(state.recent_branches or [])
        default_branch = self.store.find_default_branch_for(repo) if repo else None
        default_name = default_branch.name if default_branch else None
        rows = []
        for group_name, branches in group_branches(
            state.branches,
            current=current,
            default_name=default_name,
            recent_names=recent,
        ):
            for branch in branches:
                tip = getattr(branch, "tip", None)
                rows.append(
                    {
                        "name": branch.name,
                        "kind": "remote" if branch.type == BranchType.REMOTE else "local",
                        "group": group_name,
                        "isCurrent": branch.name == current,
                        "relativeTime": _relative(getattr(tip, "author_date", None)),
                        "upstream": getattr(branch, "upstream", "") or "",
                        "sha": getattr(tip, "sha", "") or "",
                    }
                )
        return rows

    def _pull_request_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        checks = state.pr_check_status or {}
        rows = []
        for pr in state.pull_requests:
            rows.append(
                {
                    "number": pr.number,
                    "title": pr.title,
                    "author": getattr(pr, "author", "") or "",
                    "branch": getattr(pr, "head_ref_name", "") or "",
                    "relativeTime": _relative(getattr(pr, "created_at", None)),
                    "checkState": checks.get(pr.number, ""),
                    "draft": bool(getattr(pr, "draft", False)),
                }
            )
        return rows

    def _diff_row_list(self) -> list[dict]:
        from .diff_view import diff_rows_for_qml

        state = self._state()
        if state is None:
            return []
        return diff_rows_for_qml(state)

    def _stash_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        return [
            {
                "name": entry.name,
                "branch": entry.branch_name,
                "sha": entry.stash_sha,
                "relativeTime": _relative(getattr(entry, "created_at", None)),
            }
            for entry in state.stashes
        ]

    def _stashed_file_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        selected = getattr(state.selected_stashed_file, "path", None)
        rows = []
        for f in state.stashed_files:
            row = self._file_row(f, selected_ids=[])
            rows.append(
                {
                    key: row[key]
                    for key in ("path", "name", "directory", "statusKind", "statusLetter", "statusColor")
                }
                | {"isSelected": f.path == selected}
            )
        return rows

    def _check_run_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        rows = []
        for run in state.check_runs:
            status = str(getattr(run, "conclusion", "") or getattr(run, "status", "") or "")
            rows.append(
                {
                    "name": getattr(run, "name", "") or "",
                    "description": getattr(run, "description", "") or "",
                    "state": status,
                    "icon": icon_name(
                        "checks-ok"
                        if status == "success"
                        else "checks-failed"
                        if status in {"failure", "timed_out", "action_required"}
                        else "checks-pending"
                    ),
                    "url": getattr(run, "html_url", "") or "",
                    "checkId": int(getattr(run, "id", 0) or 0),
                }
            )
        return rows

    def _co_author_rows(self) -> list[dict]:
        state = self._state()
        if state is None:
            return []
        return [
            {
                "name": getattr(a, "name", "") or "",
                "email": getattr(a, "email", "") or "",
                "username": getattr(a, "username", "") or "",
            }
            for a in (state.co_authors or [])
        ]

    def _avatar_url(self, email: str, *, login: str | None = None) -> str:
        """First avatar candidate for an author; QML falls back to initials."""
        from ..avatars import avatar_urls

        repo = self._repo()
        github = getattr(repo, "github", None) if repo else None
        try:
            candidates = avatar_urls(
                email=email or "",
                login=login,
                endpoint=getattr(github, "endpoint", None),
            )
        except Exception:
            return ""
        return candidates[0] if candidates else ""

    # -- exposed models ----------------------------------------------------

    @Property(QObject, constant=True)
    def repositories(self) -> QObject:
        return self._repositories

    @Property(QObject, constant=True)
    def changedFiles(self) -> QObject:  # noqa: N802 - QML style
        return self._changed_files

    @Property(QObject, constant=True)
    def commits(self) -> QObject:
        return self._commits

    @Property(QObject, constant=True)
    def commitFiles(self) -> QObject:  # noqa: N802 - QML style
        return self._commit_files

    @Property(QObject, constant=True)
    def branches(self) -> QObject:
        return self._branches

    @Property(QObject, constant=True)
    def pullRequests(self) -> QObject:  # noqa: N802 - QML style
        return self._pull_requests

    @Property(QObject, constant=True)
    def diffRows(self) -> QObject:  # noqa: N802 - QML style
        return self._diff_rows

    @Property(QObject, constant=True)
    def stashes(self) -> QObject:
        return self._stashes

    @Property(QObject, constant=True)
    def stashedFiles(self) -> QObject:  # noqa: N802 - QML style
        return self._stashed_files

    @Property(QObject, constant=True)
    def checkRuns(self) -> QObject:  # noqa: N802 - QML style
        return self._check_runs

    @Property(QObject, constant=True)
    def coAuthors(self) -> QObject:  # noqa: N802 - QML style
        return self._co_authors

    @Property("QVariant", notify=changed)
    def checks(self) -> dict:
        """Toolbar badge and sheet header for the current branch's CI."""
        from ..github.ci_checks import get_combined_status_summary, split_rerunnable_checks

        state = self._state()
        runs = list(state.check_runs) if state else []
        summary = get_combined_status_summary(runs, "check") if runs else ""
        conclusions = {str(getattr(r, "conclusion", "") or "") for r in runs}
        if not runs:
            icon = "checks-pending"
        elif conclusions & {"failure", "timed_out", "action_required", "cancelled"}:
            icon = "checks-failed"
        elif conclusions <= {"success", "neutral", "skipped"}:
            icon = "checks-ok"
        else:
            icon = "checks-pending"
        try:
            rerunnable, _ = split_rerunnable_checks(runs)
        except Exception:
            rerunnable = []
        steps = [step for run in runs for step in (getattr(run, "steps", None) or [])]
        return {
            "summary": summary,
            "stepSummary": get_combined_status_summary(steps, "step") if steps else "",
            "icon": icon_name(icon),
            "loading": bool(state.pr_preview_loading) if state else False,
            "canRerun": bool(rerunnable),
            "failing": icon == "checks-failed",
        }

    @Slot()
    def noteChecksOpened(self) -> None:  # noqa: N802 - QML style
        """Desktop records opening the popover, so keep the same stat."""
        try:
            self.store.stats.increment("opensCheckRunsPopover")
        except Exception:
            pass
        self._with_repo(self.store.load_rerunnable_checks)

    # -- top-level shell ---------------------------------------------------

    @Property(str, constant=True)
    def appName(self) -> str:  # noqa: N802 - QML style
        return APP_NAME

    @Property(str, constant=True)
    def version(self) -> str:
        return __version__

    @Property(str, notify=changed)
    def viewMode(self) -> str:  # noqa: N802 - QML style
        """``welcome``, ``empty`` or ``repository``."""
        if self.store.welcome_step is not None:
            return "welcome"
        if (not self.store.repositories and not self.store.cloning) or self.store.tutorial_step == TutorialStep.PAUSED:
            return "empty"
        return "repository"

    @Property(str, notify=changed)
    def repositoryState(self) -> str:  # noqa: N802 - QML style
        """``none``, ``cloning``, ``missing`` or ``ready``."""
        if self.store.selected_cloning is not None:
            return "cloning"
        repo = self._repo()
        if repo is None:
            return "none"
        if repo.is_missing:
            return "missing"
        return "ready"

    @Property(str, notify=changed)
    def windowTitle(self) -> str:  # noqa: N802 - QML style
        cloning = self.store.selected_cloning
        if cloning is not None:
            return f"Cloning {cloning.name} — {APP_NAME}"
        repo = self._repo()
        if repo is None:
            return APP_NAME
        return f"{repo.display_name} — {APP_NAME}"

    @Property(str, notify=changed)
    def welcomeStep(self) -> str:  # noqa: N802 - QML style
        step = self.store.welcome_step
        return str(step) if step is not None else ""

    @Property(str, notify=changed)
    def section(self) -> str:
        return "history" if self.store.section == RepositorySectionTab.HISTORY else "changes"

    @Slot(str)
    def setSection(self, value: str) -> None:  # noqa: N802 - QML style
        """Desktop `changeTab`: Changes and History are one control."""
        self.store.set_section(
            RepositorySectionTab.HISTORY if value == "history" else RepositorySectionTab.CHANGES
        )

    @Slot()
    def goToCommitMessage(self) -> None:  # noqa: N802 - QML style
        """Desktop `goToCommitMessage`: switch to Changes and focus the summary."""
        self.store.set_section(RepositorySectionTab.CHANGES)
        self.store.set_commit_message_focus(True)

    @Slot(str)
    def focusSection(self, value: str) -> None:  # noqa: N802 - QML style
        """Desktop `setFocusChangesNeeded` / `setFocusHistoryNeeded`."""
        self.setSection(value)
        self.focusRequested.emit(value)

    @Slot()
    def selectAllVisible(self) -> None:  # noqa: N802 - QML style
        """Desktop `selectAllWindowContents`: Ctrl+A selects the visible list.

        In the Changes tab that means including every changed file in the
        commit (`selectAllChildren` over the file list); in History it selects
        every listed commit.
        """
        repo = self._repo()
        state = self._state()
        if repo is None or state is None:
            return
        if self.store.section == RepositorySectionTab.HISTORY:
            self.store.select_commits(repo, list(state.commits))
            return
        self.store.set_include_all(repo, True)

    @Slot(bool)
    def setModalOpen(self, open_: bool) -> None:  # noqa: N802 - QML style
        """Desktop `isShowingModal`: global keys stand down while a dialog is up."""
        self._modal_open = bool(open_)
        self.changed.emit()

    @Property(bool, notify=changed)
    def modalOpen(self) -> bool:  # noqa: N802 - QML style
        return getattr(self, "_modal_open", False)

    # -- repository chrome -------------------------------------------------

    @Property(str, notify=changed)
    def repositoryTitle(self) -> str:  # noqa: N802 - QML style
        from .menus import repository_toolbar_title

        cloning = self.store.selected_cloning
        if cloning is not None:
            return repository_toolbar_title(cloning_name=cloning.name)
        repo = self._repo()
        if repo is not None:
            return repository_toolbar_title(selected_name=repo.display_name)
        fallback = self.store.cloning[0] if self.store.cloning else None
        return repository_toolbar_title(
            cloning_name=fallback.name if fallback else None,
            has_repositories=bool(self.store.repositories),
        )

    @Property(str, notify=changed)
    def repositoryPath(self) -> str:  # noqa: N802 - QML style
        repo = self._repo()
        return repo.path if repo else ""

    @Property(bool, notify=changed)
    def hasGitHubRepository(self) -> bool:  # noqa: N802 - QML style
        repo = self._repo()
        return bool(repo and repo.github)

    @Property(str, notify=changed)
    def currentBranch(self) -> str:  # noqa: N802 - QML style
        state = self._state()
        if state is None or state.status is None:
            return ""
        return state.status.current_branch or ""

    @Property(int, notify=changed)
    def changedFileCount(self) -> int:  # noqa: N802 - QML style
        state = self._state()
        if state is None or state.status is None:
            return 0
        return len(state.status.working_directory.files)

    # -- push / pull control ----------------------------------------------

    def _presentation(self):
        state = self._state()
        repo = self._repo()
        if state is None or state.status is None:
            return None
        status = state.status
        ahead_behind = status.branch_ahead_behind
        return describe_push_pull(
            remote_name=state.default_remote_name or "origin",
            current_branch=status.current_branch,
            current_tip=status.current_tip,
            has_upstream=bool(status.current_upstream_branch),
            ahead=ahead_behind.ahead if ahead_behind else 0,
            behind=ahead_behind.behind if ahead_behind else 0,
            tag_count=len(state.local_tags_to_push or []),
            force_push=self.store.current_branch_force_push_state(),
            pull_with_rebase=bool(state.pull_with_rebase),
            last_fetched=format_last_fetched(state.last_fetched),
            rebase_in_progress=bool(getattr(status, "rebase_internal_state", None)),
            is_github=bool(repo is not None and repo.github),
        )

    @Property("QVariant", notify=changed)
    def pushPull(self) -> dict:  # noqa: N802 - QML style
        """Everything the toolbar's push/pull control renders."""
        if self.store.progress_kind:
            return {
                "label": self.store.progress_title or "Working…",
                "description": self.store.progress_description or "",
                "icon": icon_name("loading"),
                "enabled": False,
                "busy": True,
                "progress": float(self.store.progress_value or 0.0),
                "aheadBehind": "",
                "menuItems": [],
                "action": "none",
            }
        presentation = self._presentation()
        if presentation is None:
            state = self._state()
            fetched = format_last_fetched(getattr(state, "last_fetched", None) if state else None)
            return {
                "label": "Fetch origin",
                "description": fetched,
                "icon": icon_name("fetch"),
                "enabled": True,
                "busy": False,
                "progress": 0.0,
                "aheadBehind": "",
                "menuItems": [],
                "action": "fetch",
            }
        return {
            "label": presentation.label,
            "description": presentation.description,
            "icon": self._presentation_icon(presentation),
            "enabled": bool(presentation.sensitive),
            "busy": False,
            "progress": 0.0,
            "aheadBehind": presentation.ahead_behind,
            "menuItems": list(presentation.menu_items),
            "action": presentation.action,
        }

    @staticmethod
    def _presentation_icon(presentation) -> str:
        from ..push_pull import ICON_FETCH, ICON_PUBLISH, ICON_PULL, ICON_PUSH

        return icon_name(
            {
                ICON_PUBLISH: "publish",
                ICON_PUSH: "push",
                ICON_PULL: "pull",
                ICON_FETCH: "fetch",
            }.get(presentation.icon, "fetch")
        )

    @Slot()
    def runPushPull(self) -> None:  # noqa: N802 - QML style
        if self.store.progress_kind:
            return
        repo = self._repo()
        if repo is None:
            return
        presentation = self._presentation()
        action = presentation.action if presentation else "fetch"
        if action == "force-push":
            self.store.confirm_or_force_push(repo)
        elif action == "push":
            self.store.push_repo(repo)
        elif action == "pull":
            self.store.pull_repo(repo)
        else:
            self.store.fetch_repo(repo)

    # -- banner ------------------------------------------------------------

    @Property("QVariant", notify=changed)
    def banner(self) -> dict:
        from .window import format_banner_text

        banner = self.store.banner
        if banner is None:
            return {"visible": False, "text": "", "actionLabel": "", "kind": ""}
        kind = banner.type
        if kind == BannerType.OPEN_THANK_YOU_CARD:
            label = "Open Your Card"
        elif kind == BannerType.DETACHED_HEAD:
            label = "Create branch"
        elif kind == BannerType.ACCESSIBILITY_SETTINGS:
            label = "Open settings"
        elif kind == BannerType.OS_VERSION_NO_LONGER_SUPPORTED:
            label = "Support details"
        elif kind in CONFLICT_BANNERS:
            label = "View conflicts"
        elif kind in SUCCESS_BANNERS and banner.undo_sha:
            label = "Undo"
        else:
            label = "Dismiss"
        severity = "warning" if kind in CONFLICT_BANNERS else "positive" if kind in SUCCESS_BANNERS else "information"
        return {
            "visible": True,
            "text": format_banner_text(kind, banner),
            "actionLabel": label,
            "kind": str(kind),
            "severity": severity,
        }

    @Slot()
    def activateBanner(self) -> None:  # noqa: N802 - QML style
        banner = self.store.banner
        if banner is None:
            return
        kind = banner.type
        if kind == BannerType.OPEN_THANK_YOU_CARD:
            self.store.open_thank_you_card()
        elif kind == BannerType.DETACHED_HEAD:
            self.store.show_popup(PopupType.CREATE_BRANCH)
        elif kind == BannerType.ACCESSIBILITY_SETTINGS:
            self.store.dismiss_accessibility_banner()
            self.store.show_popup(PopupType.PREFERENCES, tab=PreferencesTab.ACCESSIBILITY.value)
        elif kind == BannerType.OS_VERSION_NO_LONGER_SUPPORTED:
            self.store.clear_banner()
            open_external(
                "https://docs.github.com/en/desktop/installing-and-configuring-github-desktop/"
                "overview/supported-operating-systems"
            )
        elif kind in CONFLICT_BANNERS:
            mapping = {
                BannerType.MERGE_CONFLICTS_FOUND: MultiCommitOperationKind.MERGE.value,
                BannerType.REBASE_CONFLICTS_FOUND: MultiCommitOperationKind.REBASE.value,
                BannerType.CHERRY_PICK_CONFLICTS_FOUND: MultiCommitOperationKind.CHERRY_PICK.value,
            }
            self.store.show_popup(
                PopupType.MULTI_COMMIT_OPERATION,
                kind=banner.operation_kind or mapping.get(kind, MultiCommitOperationKind.MERGE.value),
                step="conflicts",
            )
        elif kind in SUCCESS_BANNERS and banner.undo_sha:
            self._with_repo(self.store.undo_multi_commit)
        else:
            self.store.clear_banner()

    @Slot()
    def dismissBanner(self) -> None:  # noqa: N802 - QML style
        self.store.clear_banner()

    # -- commit form -------------------------------------------------------

    @Property("QVariant", notify=changed)
    def commitForm(self) -> dict:  # noqa: N802 - QML style
        from .length_hint import summary_length_hint

        state = self._state()
        repo = self._repo()
        if state is None or repo is None:
            return {"visible": False}
        message = state.commit_message
        status = state.status
        branch = status.current_branch if status else ""
        amending = state.commit_to_amend is not None
        if amending:
            button = f"Amend {branch or 'last commit'}"
        elif branch:
            button = f"Commit to {branch}"
        else:
            button = "Commit to branch"
        included = 0
        if status:
            included = sum(
                1 for f in status.working_directory.files if _selection_state(f) != 0
            )
        return {
            "visible": True,
            "summary": message.summary,
            "description": message.description or "",
            "buttonLabel": button,
            "canCommit": included > 0 and bool(message.summary.strip()) and not state.is_committing,
            "isCommitting": bool(state.is_committing),
            "isGenerating": bool(state.is_generating_commit_message),
            "amending": amending,
            "lengthHint": summary_length_hint(
                message.summary, self.store.settings.show_commit_length_warning
            )
            or "",
            "showCoAuthors": bool(state.show_co_authors or state.co_authors),
            "coAuthorsAvailable": bool(repo.github),
            "authorName": state.author_name or "",
            "authorEmail": state.author_email or "",
            "avatarUrl": self._avatar_url(state.author_email or ""),
            "includedCount": included,
            "spellcheck": bool(self.store.settings.spellcheck_enabled),
            "canGenerate": self._can_generate_commit_message(state),
            "generateLabel": GENERATE_COMMIT_MESSAGE_WITH_COPILOT,
            "generateDisabledReason": ""
            if self._can_generate_commit_message(state)
            else NO_FILES_SELECTED_FOR_GENERATION,
            "generatingLabel": GENERATING_COMMIT_DETAILS,
            "warnings": self._commit_warnings(state),
            "completeness": summary_completeness(message.summary),
        }

    @Slot(str, str)
    def setCommitMessage(self, summary: str, description: str) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        if repo is None:
            return
        state = self.store.state_for(repo)
        # Typing must not re-enter the whole refresh: update in place and let
        # the next store emit carry it.
        self._suppress = True
        try:
            state.commit_message.summary = summary
            state.commit_message.description = description
        finally:
            self._suppress = False

    def _can_generate_commit_message(self, state) -> bool:
        from .menus import generate_commit_message_menu_item_enabled

        repo = self._repo()
        account = self.store.account_for_repo(repo) if repo else None
        if not enable_commit_message_generation(account):
            return False
        included = 0
        if state.status:
            included = sum(1 for f in state.status.working_directory.files if _selection_state(f) != 0)
        return generate_commit_message_menu_item_enabled(
            is_committing=bool(state.is_committing),
            is_generating=bool(state.is_generating_commit_message),
            no_changes_available=included == 0,
        )

    def _commit_warnings(self, state) -> list[dict]:
        """Desktop's CommitWarning strip: write access, protected branch, rules."""
        from .autocompletion import branch_protections_repo_rules_commit_warning_markups

        repo = self._repo()
        if repo is None:
            return []
        try:
            markups = branch_protections_repo_rules_commit_warning_markups(repo, state)
        except Exception:
            return []
        return [{"markup": markup, "kind": "warning"} for markup in markups if markup]

    @Slot()
    def generateCommitMessage(self) -> None:  # noqa: N802 - QML style
        """Ask Copilot for a summary and description of the staged change."""
        self._with_repo(self.store.generate_commit_message)

    @Slot()
    def commit(self) -> None:
        repo = self._repo()
        if repo is None:
            return
        state = self.store.state_for(repo)
        message = state.commit_message
        if state.commit_to_amend is not None:
            self.store.amend_last(repo, message.summary, message.description or "")
            return
        self.store.commit(repo, message.summary, message.description or "")

    @Slot(bool)
    def setShowCoAuthors(self, enabled: bool) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        if repo is None:
            return
        self.store.state_for(repo).show_co_authors = bool(enabled)
        self.store.emit()

    @Slot()
    def stopAmending(self) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        if repo is None:
            return
        self.store.state_for(repo).commit_to_amend = None
        self.store.emit()

    # -- selection ---------------------------------------------------------

    @Slot()
    def finishWelcome(self) -> None:  # noqa: N802 - QML style
        """Leave the first-run flow without signing in."""
        self.store.finish_welcome()

    @Slot(str)
    def relocateRepository(self, path: str) -> None:  # noqa: N802 - QML style
        """Point a missing repository at the folder the user just found."""
        repo = self._repo()
        if repo is None or not path:
            return
        try:
            self.store.relocate_repository(repo, path)
        except Exception as exc:
            self.store.show_popup(PopupType.ERROR, error=str(exc))

    @Slot(int)
    def selectRepository(self, repo_id: int) -> None:  # noqa: N802 - QML style
        self.store.select_repository(repo_id)

    @Slot(str)
    def setRepositoryFilter(self, text: str) -> None:  # noqa: N802 - QML style
        self.store.set_repository_filter_text(text)

    @Slot(str)
    def selectFile(self, path: str) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        state = self._state()
        if repo is None or state is None or state.status is None:
            return
        for file in state.status.working_directory.files:
            if file.path == path:
                self.store.select_file(repo, file)
                return

    @Slot(str, bool)
    def setFileIncluded(self, path: str, included: bool) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.set_file_included(repo, path, included))

    @Slot(bool)
    def setAllIncluded(self, included: bool) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.set_include_all(repo, included))

    @Slot(str)
    def selectCommit(self, sha: str) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        state = self._state()
        if repo is None or state is None:
            return
        for commit in state.commits:
            if commit.sha == sha:
                self.store.select_commit(repo, commit)
                return

    @Slot(str)
    def selectCommitFile(self, path: str) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        state = self._state()
        if repo is None or state is None:
            return
        for file in state.selected_commit_files:
            if file.path != path:
                continue
            state.selected_file = file
            sha = getattr(file, "commitish", None) or (
                state.selected_commit.sha if state.selected_commit else ""
            )
            self.store.load_history_diff(repo, file.path, sha, file.status)
            self.store.emit()
            return

    @Slot(str)
    def setHistoryFilter(self, text: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.set_history_filter(repo, text))

    @Slot(str)
    def setChangesFilter(self, text: str) -> None:  # noqa: N802 - QML style
        """Filter the changed-files list (Desktop's changes list filter)."""
        state = self._state()
        if state is None:
            return
        state.filter_text = text
        self.store.emit()

    @Slot(str)
    def setFileFilter(self, kind: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.set_file_filter(repo, kind))

    @Property("QVariant", notify=changed)
    def changesFilter(self) -> dict:  # noqa: N802 - QML style
        """What the changed-files filter is hiding, and how to say it."""
        from ..filter_changes import (
            count_active_filter_options,
            file_list_filter_state_from_view,
            has_active_filters,
            hidden_changes_adjust_filters_label,
            hidden_changes_warning_tooltip,
        )
        from .menus import hidden_changes_menu_label

        state = self._state()
        if state is None or state.status is None:
            return {"filtering": False, "hiddenCount": 0, "hiddenWarning": "", "tooltip": ""}
        filters = file_list_filter_state_from_view(state)
        total = len(state.status.working_directory.files)
        hidden = max(0, total - self._changed_files.count)
        return {
            "filtering": has_active_filters(filters),
            "activeOptions": count_active_filter_options(filters),
            "hiddenCount": hidden,
            "hiddenWarning": hidden_changes_adjust_filters_label(hidden) if hidden else "",
            "hiddenLabel": hidden_changes_menu_label(hidden) if hidden else "",
            "tooltip": hidden_changes_warning_tooltip() if hidden else "",
        }

    @Slot()
    def clearChangesFilters(self) -> None:  # noqa: N802 - QML style
        """Reset the text and the New/Modified/Deleted toggles at once."""
        state = self._state()
        if state is None:
            return
        state.filter_text = ""
        state.filter_new = False
        state.filter_modified = False
        state.filter_deleted = False
        state.file_filter = ChangesListFilter.ALL.value
        self.store.emit()

    @Slot()
    def loadMoreCommits(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.load_next_commit_batch)

    @Property("QVariant", notify=changed)
    def history(self) -> dict:
        """Header state for the History tab: what it is listing, and of what."""
        from .window import commit_list_empty_message

        state = self._state()
        if state is None:
            return {
                "emptyMessage": NO_HISTORY,
                "showingChangesFrom": "",
                "hasSelection": False,
                "canUndo": False,
            }
        compare_branch = getattr(state.compare_branch, "name", "") or ""
        showing = f"Showing changes from {compare_branch}" if compare_branch else ""
        # Desktop only offers Undo for the tip commit, and not mid-operation.
        tip = state.commits[0] if state.commits else None
        selected = state.selected_commit
        can_undo = (
            tip is not None
            and selected is not None
            and selected.sha == tip.sha
            and not self.store.progress_kind
            and not state.is_committing
        )
        return {
            "emptyMessage": commit_list_empty_message(
                history_mode=state.history_mode,
                comparison_mode=state.compare_mode,
                branch_name=compare_branch or None,
            ),
            "showingChangesFrom": showing,
            "hasSelection": selected is not None,
            "canUndo": bool(can_undo),
        }

    @Property(str, constant=True)
    def copyShaLabel(self) -> str:  # noqa: N802 - QML style
        from .copy_button import copy_the_full_sha_label

        return copy_the_full_sha_label()

    @Slot("QVariant", result=str)
    def tagSummary(self, tags: Any) -> str:  # noqa: N802 - QML style
        """`1 tag` / `3 tags` for the history row's tag indicator."""
        from .menus import copy_tags_menu_label

        names = list(tags or [])
        if not names:
            return ""
        if len(names) == 1:
            return "1 tag"
        return f"{len(names)} tags"

    @Property(str, notify=changed)
    def previousTagsLabel(self) -> str:  # noqa: N802 - QML style
        """Desktop's disabled "Previous tags" heading above the tag actions."""
        return "Previous tags"

    @Property(int, notify=changed)
    def selectedCommitCount(self) -> int:  # noqa: N802 - QML style
        state = self._state()
        return len(state.selected_commits) if state else 0

    @Property(str, notify=changed)
    def squashLabel(self) -> str:  # noqa: N802 - QML style
        """`Squash 3 Commits` -- Desktop capitalizes the noun in this menu."""
        count = self.selectedCommitCount
        return f"Squash {count} Commits" if count != 1 else "Squash 1 Commit"

    @Slot(int)
    def revealCheckLogs(self, check_id: int) -> None:  # noqa: N802 - QML style
        """Show the downloaded job logs in the file manager."""
        from ..paths import cache_dir
        from ..shells import reveal_in_file_manager

        repo = self._repo()
        if repo is None:
            return
        reveal_in_file_manager(repo, str(cache_dir() / "check-logs" / str(check_id)))

    @Slot()
    def undoCommit(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.undo_last_commit)

    @Slot(str)
    def revertCommit(self, sha: str) -> None:  # noqa: N802 - QML style
        state = self._state()
        if state is None:
            return
        for commit in state.commits:
            if commit.sha == sha:
                self._with_repo(lambda repo, c=commit: self.store.revert_commit(repo, c))
                return

    @Slot(str)
    def viewCommitOnGitHub(self, sha: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.view_commit_on_github(repo, sha))

    # -- diff --------------------------------------------------------------

    @Property("QVariant", notify=changed)
    def diff(self) -> dict:
        from .diff_view import diff_summary_for_qml

        return diff_summary_for_qml(self._state(), self.store)

    @Slot(bool)
    def setSideBySide(self, enabled: bool) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.set_side_by_side(repo, enabled))

    @Slot(str)
    def setImageDiffType(self, kind: str) -> None:  # noqa: N802 - QML style
        """Two-up, swipe, onion skin or difference, as Desktop offers."""
        self._with_repo(lambda repo: self.store.set_image_diff_type(repo, kind))

    @Slot()
    def refreshRepositories(self) -> None:  # noqa: N802 - QML style
        self.store.refresh_repo_indicators()

    @Slot(bool)
    def setHideWhitespace(self, hidden: bool) -> None:  # noqa: N802 - QML style
        def apply(repo):
            if self.store.section == RepositorySectionTab.HISTORY:
                self.store.set_hide_whitespace_in_history_diff(repo, hidden)
            else:
                self.store.set_hide_whitespace_in_changes_diff(repo, hidden)

        self._with_repo(apply)

    @Slot(int, int, bool)
    def setHunkIncluded(self, start: int, length: int, included: bool) -> None:  # noqa: N802 - QML style
        state = self._state()
        path = getattr(getattr(state, "selected_file", None), "path", None)
        if not path:
            return
        self._with_repo(lambda repo: self.store.set_hunk_included(repo, path, start, length, included))

    @Slot(int, bool)
    def setLineIncluded(self, diff_index: int, included: bool) -> None:  # noqa: N802 - QML style
        state = self._state()
        path = getattr(getattr(state, "selected_file", None), "path", None)
        if not path:
            return
        self._with_repo(lambda repo: self.store.set_line_included(repo, path, diff_index, included))

    @Slot(int, str)
    def expandHunk(self, hunk_index: int, direction: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.expand_hunk(repo, hunk_index, direction))

    @Slot()
    def expandWholeFile(self) -> None:  # noqa: N802 - QML style
        """Desktop's expand-whole-file: show every line, not just the hunks."""
        self._with_repo(lambda repo: self.store.expand_hunk(repo, 0, "whole"))

    @Slot()
    def showLargeDiff(self) -> None:  # noqa: N802 - QML style
        """Render a diff we collapsed for being over Desktop's size limit."""
        state = self._state()
        if state is None:
            return
        state.show_large_diff = True
        self.store.emit()

    @Slot(str)
    def openSubmodule(self, path: str) -> None:  # noqa: N802 - QML style
        """Open this submodule on GitHub Desktop as its own repository."""
        self._with_repo(lambda repo: self.store.open_submodule_from_diff(repo, path))

    # -- repository actions ------------------------------------------------

    @Slot()
    def fetch(self) -> None:
        self._with_repo(self.store.fetch_repo)

    @Slot()
    def push(self) -> None:
        self._with_repo(self.store.push_repo)

    @Slot()
    def forcePush(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.confirm_or_force_push)

    @Slot()
    def pull(self) -> None:
        self._with_repo(self.store.pull_repo)

    @Slot(str)
    def checkoutBranch(self, name: str) -> None:  # noqa: N802 - QML style
        state = self._state()
        if state is None:
            return
        for branch in state.branches:
            if branch.name == name:
                self._with_repo(lambda repo, b=branch: self.store.checkout(repo, b))
                return

    @Slot(str)
    def mergeBranch(self, name: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.merge_branch(repo, name))

    @Slot(str)
    def squashMergeBranch(self, name: str) -> None:  # noqa: N802 - QML style
        """Squash and merge into current branch (Desktop's squash merge)."""
        self._with_repo(lambda repo: self.store.merge_branch(repo, name, squash=True))

    @Slot(str)
    def viewBranchOnGitHub(self, name: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.view_branch_on_github(repo, name))

    @Slot(int)
    def viewPullRequestOnGitHub(self, number: int) -> None:  # noqa: N802 - QML style
        pr = self._pull_request(number)
        if pr is not None:
            self.store.show_pull_request_by_pr(pr)

    @Slot(int)
    def copyPullRequestUrl(self, number: int) -> None:  # noqa: N802 - QML style
        pr = self._pull_request(number)
        url = getattr(pr, "html_url", "") if pr else ""
        if url:
            self.copyToClipboard(url)

    def _pull_request(self, number: int):
        state = self._state()
        if state is None:
            return None
        return next((pr for pr in state.pull_requests if pr.number == number), None)

    @Slot(int)
    def checkoutPullRequest(self, number: int) -> None:  # noqa: N802 - QML style
        state = self._state()
        if state is None:
            return
        for pr in state.pull_requests:
            if pr.number == number:
                self._with_repo(lambda repo, p=pr: self.store.checkout_pull_request(repo, p))
                return

    @Slot()
    def openInEditor(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.open_in_editor)

    @Slot()
    def openInShell(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.open_in_shell)

    @Slot()
    def openWorkingDirectory(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.open_working_directory)

    @Slot()
    def viewOnGitHub(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.view_on_github)

    @Slot()
    def openPullRequest(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.open_pull_request)

    @Slot(str)
    def openPath(self, path: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.open_in_editor(repo, path))

    @Slot(str)
    def openFileDefault(self, path: str) -> None:  # noqa: N802 - QML style
        """Hand the file to whatever the desktop has registered for its type."""
        self._with_repo(lambda repo: self.store.open_file_default(repo, path))

    @Slot(str)
    def revealPath(self, path: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.reveal_in_file_manager(repo, path))

    @Slot(str, bool)
    def ignorePath(self, path: str, folder: bool) -> None:  # noqa: N802 - QML style
        """Add a path -- or the folder containing it -- to .gitignore."""
        target = path.rsplit("/", 1)[0] + "/" if folder and "/" in path else path
        self._with_repo(lambda repo: self.store.ignore_path(repo, target))

    def _selected_paths(self, fallback: str = "") -> list[str]:
        """Paths the changed-files list currently has selected."""
        state = self._state()
        if state is None or state.status is None:
            return [fallback] if fallback else []
        ids = set(state.selected_file_ids or ())
        paths = [f.path for f in state.status.working_directory.files if f.id in ids]
        return paths or ([fallback] if fallback else [])

    @Property(str, notify=changed)
    def ignoreSelectedLabel(self) -> str:  # noqa: N802 - QML style
        from .menus import ignore_selected_files_label

        return ignore_selected_files_label(self._selected_paths())

    @Slot(str)
    def ignoreSelectedPaths(self, fallback: str = "") -> None:  # noqa: N802 - QML style
        paths = self._selected_paths(fallback)
        if paths:
            self._with_repo(lambda repo: self.store.ignore_path(repo, paths))

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:  # noqa: N802 - QML style
        from PySide6.QtGui import QGuiApplication

        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802 - QML style
        from .markdown import link_is_safe

        if link_is_safe(url):
            open_external(url)

    @Slot()
    def stashChanges(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.stash_all_changes)

    @Slot()
    def toggleStash(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.toggle_stash)

    @Property(bool, notify=changed)
    def stashVisible(self) -> bool:  # noqa: N802 - QML style
        state = self._state()
        return bool(state and state.stashed_visible and state.stashes)

    @Slot()
    def restoreStash(self) -> None:  # noqa: N802 - QML style
        """Pop the stash back into the working directory."""
        self._with_repo(self.store.restore_stash)

    @Slot()
    def cancelClone(self) -> None:  # noqa: N802 - QML style
        """Stop watching an in-flight clone and go back to the repository list.

        Git keeps running in its worker; what the user is asking for here is
        the view back, which is what Desktop's Cancel clone does too.
        """
        cloning = self.store.selected_cloning
        if cloning is None:
            return
        try:
            self.store.cloning.remove(cloning)
        except ValueError:
            pass
        self.store.select_cloning(None)
        self.store.emit()

    @Slot(str)
    def addDroppedPath(self, url: str) -> None:  # noqa: N802 - QML style
        """A folder dropped on the window; resolve it the same way the picker does."""
        from .filepicker import resolve_picked_url

        picked = resolve_picked_url(url)
        if picked.ok:
            self.store.add_dropped_paths([picked.path])
            return
        if picked.error:
            self.store.show_popup(
                PopupType.ERROR,
                error=f"{picked.error} {picked.help_text}".strip(),
            )

    @Slot(str)
    def selectStashedFile(self, path: str) -> None:  # noqa: N802 - QML style
        repo = self._repo()
        state = self._state()
        if repo is None or state is None:
            return
        for file in state.stashed_files:
            if file.path == path:
                self.store.select_stashed_file(repo, file)
                return

    # -- popups ------------------------------------------------------------

    @Slot(str)
    @Slot(str, "QVariant")
    def showPopup(self, popup_type: str, payload: Any = None) -> None:  # noqa: N802 - QML style
        from .popups import as_dict

        try:
            kind = PopupType(popup_type)
        except ValueError:
            return
        self.store.show_popup(kind, **as_dict(payload))

    @Slot()
    def closePopup(self) -> None:  # noqa: N802 - QML style
        self.store.close_popup()

    @Slot(str)
    def showError(self, message: str) -> None:  # noqa: N802 - QML style
        self.store.show_popup(PopupType.ERROR, error=message)

    # -- settings ----------------------------------------------------------

    @Property("QVariant", notify=changed)
    def repoRules(self) -> dict:  # noqa: N802 - QML style
        """Repository rules that would block this commit, for the popover.

        Desktop's `warningType` decides how loudly to say it: rules that only
        the branch protections cover are a nudge, an email pattern failure is
        a hard stop.
        """
        from ..github.repo_rules import rulesets_url_for_branch

        state = self._state()
        repo = self._repo()
        if state is None or repo is None:
            return {"title": "", "rules": [], "rulesetsUrl": "", "warningType": "none"}
        rules = state.repo_rules
        branch = state.status.current_branch if state.status else None
        descriptions: list[str] = []
        for group_name in (
            "commit_message_patterns",
            "commit_author_email_patterns",
            "committer_email_patterns",
            "branch_name_patterns",
        ):
            group = getattr(rules, group_name, None)
            for rule in getattr(group, "rules", []) or []:
                description = getattr(rule, "human_description", "")
                if description:
                    descriptions.append(description)
        # Desktop `emailRuleFailures`: an email rule that fails blocks the push.
        email_failures = bool(
            getattr(getattr(rules, "commit_author_email_patterns", None), "rules", None)
            or getattr(getattr(rules, "committer_email_patterns", None), "rules", None)
        )
        if getattr(rules, "signed_commits_required", False):
            descriptions.append("Commits must be signed.")
        if getattr(rules, "pull_request_required", False):
            descriptions.append("Changes must go through a pull request.")
        warning = "error" if email_failures else "warning" if descriptions else "none"
        return {
            "title": "Repository rules",
            "rules": descriptions,
            "rulesetsUrl": rulesets_url_for_branch(repo.github, branch) or "",
            "warningType": warning,
            "emailRuleFailures": email_failures,
        }

    @Slot(int, result=str)
    def pullRequestBody(self, number: int) -> str:  # noqa: N802 - QML style
        """Rendered PR body for the quick view popup."""
        from .markdown import sandboxed_markdown

        pr = self._pull_request(number)
        if pr is None:
            return ""
        return sandboxed_markdown(getattr(pr, "body", "") or "", repository=self._repo())

    @Property("QVariant", notify=changed)
    def conflicts(self) -> dict:
        """Conflicted files, and the manual resolutions available for each."""
        from ..models import (
            ManualConflictResolution,
            get_conflicted_files,
            get_label_for_manual_resolution_option,
        )
        from .multi_commit import manual_conflict_status_copy

        state = self._state()
        if state is None or state.status is None:
            return {"summary": "", "files": [], "resolvedCount": 0, "remaining": 0}
        resolutions = state.manual_resolutions or {}
        all_conflicted = [
            f for f in state.status.working_directory.files if _is_conflicted(f)
        ]
        try:
            unresolved = {f.path for f in get_conflicted_files(state.status.working_directory, resolutions)}
        except Exception:
            unresolved = {f.path for f in all_conflicted}
        our_branch = state.status.current_branch if state.status else None
        their_branch = getattr(state, "pr_base_branch", None)
        files = []
        for entry in all_conflicted:
            resolution = resolutions.get(entry.path)
            files.append(
                {
                    "path": entry.path,
                    "resolved": entry.path not in unresolved,
                    "manualResolution": getattr(resolution, "value", "") or "",
                    "status": manual_conflict_status_copy(
                        entry.status, our_branch=our_branch, their_branch=their_branch
                    ),
                    # Desktop labels each side by what that side did to the
                    # file (added / deleted / modified), not by "ours/theirs".
                    "manualOptions": [
                        {
                            "value": ManualConflictResolution.OURS.value,
                            "label": get_label_for_manual_resolution_option(
                                getattr(entry.status, "us", None), our_branch
                            ),
                        },
                        {
                            "value": ManualConflictResolution.THEIRS.value,
                            "label": get_label_for_manual_resolution_option(
                                getattr(entry.status, "them", None), their_branch
                            ),
                        },
                    ],
                }
            )
        remaining = len(unresolved)
        resolved = len(files) - remaining
        noun = "conflict" if len(files) == 1 else "conflicts"
        return {
            "summary": f"{remaining} of {len(files)} {noun} remaining" if files else "",
            "files": files,
            "resolvedCount": resolved,
            "remaining": remaining,
        }

    @Slot(str, str)
    def resolveConflict(self, path: str, resolution: str) -> None:  # noqa: N802 - QML style
        """Record (or clear) a manual resolution for one conflicted file."""
        from ..models import ManualConflictResolution

        chosen = None
        if resolution:
            try:
                chosen = ManualConflictResolution(resolution)
            except ValueError:
                return
        self._with_repo(
            lambda repo: self.store.update_manual_conflict_resolution(repo, path, chosen)
        )

    @Property("QVariant", notify=changed)
    def tutorial(self) -> dict:
        """State for the Get started panel: which step, and whether to nudge."""
        from ..models import is_valid_tutorial_step
        from .tutorial import TUTORIAL_DONE_SUMMARY, TUTORIAL_HEADING, tutorial_steps

        step = self.store.tutorial_step
        active = bool(step) and is_valid_tutorial_step(step)
        done = step == TutorialStep.ALL_DONE
        return {
            "active": active or done,
            "done": done,
            "step": str(step) if step else "",
            "summary": TUTORIAL_DONE_SUMMARY if done else TUTORIAL_HEADING,
            "steps": tutorial_steps(step),
        }

    @Slot()
    def exploreGitHub(self) -> None:  # noqa: N802 - QML style
        self._with_repo(self.store.show_github_explore)

    @Property("QVariant", notify=changed)
    def settings(self) -> dict:
        settings = self.store.settings
        return {
            "theme": settings.theme,
            "tabSize": settings.tab_size,
            "showChangesFilter": settings.show_changes_filter,
            "stashButtonWhenExists": settings.stash_button_when_exists,
            "useExternalCredentialHelper": settings.use_external_credential_helper,
            "optOutOfUsageTracking": settings.opt_out_of_usage_tracking,
            "showSideBySideDiff": settings.show_side_by_side_diff,
            "hideWhitespaceInDiffs": settings.hide_whitespace_in_diffs,
            "underlineLinks": settings.underline_links,
            "showDiffCheckMarks": settings.show_diff_check_marks,
            "spellcheckEnabled": settings.spellcheck_enabled,
            "notificationsEnabled": settings.notifications_enabled,
            "showCommitLengthWarning": settings.show_commit_length_warning,
            "confirmRepositoryRemoval": settings.confirm_repository_removal,
            "confirmDiscardChanges": settings.confirm_discard_changes,
            "confirmForcePush": settings.confirm_force_push,
            "zoomFactor": settings.zoom_factor,
            "windowWidth": settings.window_width,
            "windowHeight": settings.window_height,
            "sidebarWidth": settings.sidebar_width,
            "commitSummaryWidth": settings.commit_summary_width,
        }

    @Property("QVariant", notify=changed)
    def gitConfig(self) -> dict:  # noqa: N802 - QML style
        """Git identity for this repository, and whether it is local or global."""
        from ..email import stealth_email_for_user

        state = self._state()
        repo = self._repo()
        account = self.store.account_for_repo(repo) if repo else None
        name = (state.author_name if state else "") or ""
        email = (state.author_email if state else "") or ""
        known: set[str] = set()
        if account is not None:
            known = {str(e).lower() for e in (getattr(account, "emails", None) or [])}
            known.add(stealth_email_for_user(account.id, account.login, account.endpoint).lower())
        return {
            "name": name,
            "email": email,
            "isGitConfigLocal": bool(getattr(state, "git_config_local", False)) if state else False,
            "scopeSummary": "For this repository I wish to",
            "emailMismatch": bool(account is not None and email and email.lower() not in known),
            "lineEndings": 0,
        }

    @Slot(bool)
    def setGitConfigLocal(self, local: bool) -> None:  # noqa: N802 - QML style
        state = self._state()
        if state is None:
            return
        state.git_config_local = bool(local)
        self.store.emit()

    @Slot(str, str)
    def setGitIdentity(self, name: str, email: str) -> None:  # noqa: N802 - QML style
        self._with_repo(lambda repo: self.store.save_local_git_config(repo, name, email))

    @Slot()
    def openGlobalGitConfig(self) -> None:  # noqa: N802 - QML style
        """Open ~/.gitconfig in the configured editor."""
        import os

        self._with_repo(
            lambda repo: self.store.open_in_editor(repo, os.path.expanduser("~/.gitconfig"))
        )

    @Slot(int)
    def setLineEndings(self, index: int) -> None:  # noqa: N802 - QML style
        """core.autocrlf: the platform default, or leave files untouched."""
        from ..git.ops import set_config_value

        value = "input" if index == 0 else "false"
        self._with_repo(lambda repo: set_config_value(repo.path, "core.autocrlf", value))

    @Property("QVariant", notify=changed)
    def integrations(self) -> dict:
        """External editor and shell choices for the Integrations tab."""
        from ..editors import SUGGESTED_EXTERNAL_EDITOR, SUGGESTED_EXTERNAL_EDITOR_URL, get_available_editors
        from ..shells import get_available_shells

        settings = self.store.settings
        editors = [getattr(e, "name", str(e)) for e in get_available_editors()]
        shells = [getattr(s, "name", str(s)) for s in get_available_shells()]
        return {
            "editors": editors,
            "editorIndex": editors.index(settings.selected_external_editor)
            if settings.selected_external_editor in editors
            else 0,
            "shells": shells,
            "shellIndex": shells.index(settings.selected_shell)
            if settings.selected_shell in shells
            else 0,
            "suggestedEditor": SUGGESTED_EXTERNAL_EDITOR,
            "suggestedEditorUrl": SUGGESTED_EXTERNAL_EDITOR_URL,
            "useCustomEditor": bool(settings.use_custom_editor),
            "customEditorPath": settings.custom_editor_path,
        }

    @Slot(str)
    def setEditor(self, name: str) -> None:  # noqa: N802 - QML style
        self.updateSetting("selected_external_editor", name)

    @Slot(str)
    def setShell(self, name: str) -> None:  # noqa: N802 - QML style
        self.updateSetting("selected_shell", name)

    @Slot(str, "QVariant")
    def updateSetting(self, key: str, value: Any) -> None:  # noqa: N802 - QML style
        """Set one persisted preference by its snake_case attribute name."""
        settings = self.store.settings
        if not hasattr(settings, key):
            return
        setattr(settings, key, value)
        self.store.persist_settings()
        self.store.emit()

    @Slot(int, int)
    def saveWindowSize(self, width: int, height: int) -> None:  # noqa: N802 - QML style
        if width > 0 and height > 0:
            self.store.settings.window_width = width
            self.store.settings.window_height = height
            self.store.persist_settings()

    @Property(int, notify=changed)
    def foldoutWidth(self) -> int:  # noqa: N802 - QML style
        from .menus import foldout_width

        settings = self.store.settings
        return foldout_width(settings.window_width, settings.sidebar_width)

    @Slot(int)
    def saveSidebarWidth(self, width: int) -> None:  # noqa: N802 - QML style
        if width > 0:
            self.store.set_sidebar_width(width)

    # -- resizable toolbar controls ---------------------------------------

    def _resizable(self, kind: str):
        if kind == "push":
            return (
                self.store.push_pull_constraints,
                self.store.settings.push_pull_button_width,
                self.store.set_push_pull_button_width,
                self.store.reset_push_pull_button_width,
                "Push pull button",
            )
        return (
            self.store.branch_dropdown_constraints,
            self.store.settings.branch_dropdown_width,
            self.store.set_branch_dropdown_width,
            self.store.reset_branch_dropdown_width,
            "Current branch dropdown button",
        )

    @Slot(str, result="QVariant")
    def resizableLimits(self, kind: str) -> dict:  # noqa: N802 - QML style
        """Min/max/current width for a resizable toolbar control."""
        from .menus import resizable_limit

        constraints, width, _set, _reset, description = self._resizable(kind)
        minimum = resizable_limit(getattr(constraints, "min", 0), 160)
        maximum = resizable_limit(getattr(constraints, "max", 0), 720)
        return {
            "min": minimum,
            "max": maximum,
            "width": int(width or minimum),
            "description": description,
        }

    @Slot(str, float)
    def setResizableWidth(self, kind: str, width: float) -> None:  # noqa: N802 - QML style
        limits = self.resizableLimits(kind)
        clamped = int(max(limits["min"], min(limits["max"], width)))
        self._resizable(kind)[2](clamped)

    @Slot(str)
    def resetResizableWidth(self, kind: str) -> None:  # noqa: N802 - QML style
        self._resizable(kind)[3]()

    @Slot(str, int, result=str)
    def nudgeResizable(self, kind: str, direction: int) -> str:  # noqa: N802 - QML style
        """Ctrl+9 / Ctrl+8. Returns the announcement to read out."""
        from .menus import nudge_resizable_width, resize_announcement

        limits = self.resizableLimits(kind)
        increase = direction > 0
        width = nudge_resizable_width(limits["width"], increase, limits["min"], limits["max"])
        self._resizable(kind)[2](width)
        return resize_announcement(
            limits["description"], width, limits["min"], limits["max"], increase=increase
        )

    @Slot(str, bool)
    def setResizeActive(self, kind: str, active: bool) -> None:  # noqa: N802 - QML style
        """Desktop `isResizePaneActive`: which control the keyboard resizes."""
        self._active_resizable = kind if active else ""
        self.changed.emit()

    @Property(str, notify=changed)
    def activeResizable(self) -> str:  # noqa: N802 - QML style
        """Desktop `resizeActiveResizable`: which control Ctrl+9/8 resizes."""
        return getattr(self, "_active_resizable", "")

    @Property(bool, notify=changed)
    def draggingCommit(self) -> bool:  # noqa: N802 - QML style
        """True while a commit is being dragged, so drop targets can light up."""
        return getattr(self, "_dragging_commit", False)

    @Slot(bool)
    def setDraggingCommit(self, dragging: bool) -> None:  # noqa: N802 - QML style
        self._dragging_commit = bool(dragging)
        self.changed.emit()

    @Slot(str)
    def announce(self, message: str) -> None:
        """Send text to the screen reader (and the passive notification area)."""
        if message:
            self.toast.emit(message)

    @Slot(str)
    def setTheme(self, value: str) -> None:  # noqa: N802 - QML style
        self.store.set_theme(value)

    @Slot(float)
    def setZoom(self, factor: float) -> None:  # noqa: N802 - QML style
        self.store.set_zoom(factor)

    @Slot(str, result=str)
    def iconFor(self, key: str) -> str:  # noqa: N802 - QML style
        return icon_name(key)

    # -- autocompletion ----------------------------------------------------

    @Slot(str, int, result="QVariant")
    def completionsFor(self, text: str, cursor: int) -> list[dict]:  # noqa: N802 - QML style
        """Candidates for the token under the cursor: @user, #issue or :emoji:."""
        from .autocompletion import completion_matches, token_before_cursor

        state = self._state()
        if state is None:
            return []
        token = token_before_cursor(text or "", int(cursor))
        if not token:
            return []
        account = self.store.accounts[0] if self.store.accounts else None
        return [
            {"value": match, "label": match}
            for match in completion_matches(
                state, token, exclude_login=getattr(account, "login", None)
            )
        ]

    @Slot(str, int, str, result=str)
    def applyCompletion(self, text: str, cursor: int, value: str) -> str:  # noqa: N802 - QML style
        """Replace the token under the cursor with the chosen completion."""
        from .autocompletion import completion_insert_text, token_before_cursor

        token = token_before_cursor(text or "", int(cursor))
        if not token:
            return text
        insert = completion_insert_text(value)
        start = int(cursor) - len(token)
        return text[:start] + insert + text[int(cursor):]

    # -- shutdown ----------------------------------------------------------

    @Slot()
    def flush(self) -> None:
        """Persist everything before the window closes."""
        try:
            self.store.persist_settings()
        except Exception:
            from ..logging import get_logger

            get_logger().exception("could not persist settings on close")
