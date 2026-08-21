"""Desktop `lib/menu-update.ts` — repository-scoped menu enablement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import (
    Branch,
    BranchType,
    CloningRepository,
    IStatusResult,
    Repository,
    SelectionType,
    TipState,
    WorkingDirectoryStatus,
    has_conflicted_files,
    is_repository_with_github_repository,
)
from .tip import Tip

# Desktop `allMenuIds` in menu-update.ts.
allMenuIds: tuple[str, ...] = (
    "rename-branch",
    "delete-branch",
    "discard-all-changes",
    "stash-all-changes",
    "preferences",
    "update-branch-with-contribution-target-branch",
    "compare-to-branch",
    "merge-branch",
    "rebase-branch",
    "view-repository-on-github",
    "compare-on-github",
    "branch-on-github",
    "open-in-shell",
    "push",
    "pull",
    "branch",
    "repository",
    "go-to-commit-message",
    "create-branch",
    "show-changes",
    "show-history",
    "show-repository-list",
    "show-branches-list",
    "open-working-directory",
    "show-repository-settings",
    "open-external-editor",
    "remove-repository",
    "new-repository",
    "add-local-repository",
    "clone-repository",
    "about",
    "create-pull-request",
    "preview-pull-request",
    "squash-and-merge-branch",
)

# Desktop MenuIDs that have no Gio.SimpleAction (submenu containers).
_SUBMENU_IDS = {"branch", "repository"}

# Native window action names for Desktop menu ids.
MENU_ID_TO_ACTION: dict[str, str] = {
    "rename-branch": "rename-branch",
    "delete-branch": "delete-branch",
    "discard-all-changes": "discard-all",
    "stash-all-changes": "stash-all",
    "preferences": "preferences",
    "update-branch-with-contribution-target-branch": "update-from-default",
    "compare-to-branch": "compare-to-branch",
    "merge-branch": "merge-branch",
    "rebase-branch": "rebase-branch",
    "view-repository-on-github": "view-on-github",
    "compare-on-github": "compare-on-github",
    "branch-on-github": "branch-on-github",
    "open-in-shell": "open-in-shell",
    "push": "push",
    "pull": "pull",
    "go-to-commit-message": "go-to-commit-message",
    "create-branch": "create-branch",
    "show-changes": "show-changes",
    "show-history": "show-history",
    "show-repository-list": "choose-repository",
    "show-branches-list": "show-branches",
    "open-working-directory": "open-working-directory",
    "show-repository-settings": "repository-settings",
    "open-external-editor": "open-external-editor",
    "remove-repository": "remove-repository",
    "new-repository": "new-repository",
    "add-local-repository": "add-local-repository",
    "clone-repository": "clone-repository",
    "about": "about",
    "create-pull-request": "open-pull-request",
    "preview-pull-request": "preview-pull-request",
    "squash-and-merge-branch": "squash-merge",
    "toggle-changes-filter": "toggle-changes-filter",
    "create-issue-in-repository-on-github": "create-issue",
    "toggle-stashed-changes": "toggle-stash",
    "increase-active-resizable-width": "increase-resizable",
    "decrease-active-resizable-width": "decrease-resizable",
}

repositoryScopedIDs: tuple[str, ...] = (
    "branch",
    "repository",
    "remove-repository",
    "open-in-shell",
    "open-working-directory",
    "show-repository-settings",
    "go-to-commit-message",
    "show-changes",
    "show-history",
    "show-branches-list",
    "open-external-editor",
    "compare-to-branch",
    "toggle-changes-filter",
)

welcomeScopedIds: tuple[str, ...] = (
    "new-repository",
    "add-local-repository",
    "clone-repository",
    "preferences",
    "about",
)


@dataclass
class IMenuItemState:
    """Desktop `IMenuItemState`."""

    enabled: bool | None = None


class MenuStateBuilder:
    """Desktop `MenuStateBuilder`."""

    def __init__(self, state: dict[str, IMenuItemState] | None = None) -> None:
        self._state: dict[str, IMenuItemState] = dict(state or {})

    @property
    def state(self) -> dict[str, IMenuItemState]:
        return dict(self._state)

    def _update(self, menu_id: str, enabled: bool) -> None:
        current = self._state.get(menu_id) or IMenuItemState()
        self._state[menu_id] = IMenuItemState(enabled=enabled if enabled is not None else current.enabled)

    def enable(self, menu_id: str) -> "MenuStateBuilder":
        self._update(menu_id, True)
        return self

    def disable(self, menu_id: str) -> "MenuStateBuilder":
        self._update(menu_id, False)
        return self

    def set_enabled(self, menu_id: str, enabled: bool) -> "MenuStateBuilder":
        self._update(menu_id, enabled)
        return self

    def merge(self, other: "MenuStateBuilder") -> "MenuStateBuilder":
        merged = dict(self._state)
        merged.update(other._state)
        return MenuStateBuilder(merged)


@dataclass
class MenuSnapshot:
    """Subset of Desktop `IAppState` used by `getMenuState`."""

    current_popup: bool = False
    show_welcome_flow: bool = False
    window_open: bool = True
    resizable_pane_active: bool = False
    repository_count: int = 0
    selection_type: SelectionType | None = None
    repository: Repository | CloningRepository | None = None
    status: IStatusResult | None = None
    default_branch: Branch | None = None
    contribution_target: Branch | None = None
    tip_branch: Branch | None = None
    stash_entry: Any = None
    is_push_pull_fetch_in_progress: bool = False  # Desktop isPushPullFetchInProgress
    rebase_in_progress: bool = False


def is_repository_hosted_on_github(repository: Repository | CloningRepository | None) -> bool:
    """Desktop `isRepositoryHostedOnGitHub`."""
    if repository is None or isinstance(repository, CloningRepository):
        return False
    github = getattr(repository, "github", None)
    if github is None:
        return False
    return github.html_url is not None


def get_repo_issues_enabled(repository: Repository) -> bool:
    """Desktop `getRepoIssuesEnabled` (`issuesEnabled` / `isArchived`)."""
    if not is_repository_with_github_repository(repository):
        return False
    gh_repo = repository.github
    parent = gh_repo.parent if gh_repo is not None else None
    if parent is not None:
        return getattr(parent, "has_issues", True) is not False and getattr(parent, "archived", False) is not True
    return getattr(gh_repo, "has_issues", True) is not False and getattr(gh_repo, "archived", False) is not True


def tip_from_status(status: IStatusResult | None, tip_branch: Branch | None = None) -> Tip:
    """Map porcelain status to Desktop `Tip`."""
    if status is None or not status.exists:
        return Tip(kind=TipState.UNKNOWN)
    if status.current_branch and status.current_tip:
        branch = tip_branch or Branch(
            name=status.current_branch,
            upstream=status.current_upstream_branch,
            tip_sha=status.current_tip,
            type=BranchType.LOCAL,
        )
        return Tip(kind=TipState.VALID, branch=branch, current_sha=status.current_tip)
    if status.current_tip and not status.current_branch:
        return Tip(kind=TipState.DETACHED, current_sha=status.current_tip)
    return Tip(kind=TipState.UNBORN, ref=status.current_branch)


def _native_enabled(builder: MenuStateBuilder) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for menu_id, item in builder.state.items():
        if menu_id in _SUBMENU_IDS or item.enabled is None:
            continue
        action = MENU_ID_TO_ACTION.get(menu_id)
        if action is None:
            continue
        out[action] = bool(item.enabled)
    # Desktop `push` menu id swaps click to `force-push` via `pushEventType`.
    if "push" in out:
        out["force-push"] = out["push"]
    return out


def get_all_menus_disabled_builder() -> MenuStateBuilder:
    """Desktop `getAllMenusDisabledBuilder`."""
    builder = MenuStateBuilder()
    for menu_id in allMenuIds:
        builder.disable(menu_id)
    return builder


def get_all_menus_enabled_builder() -> MenuStateBuilder:
    """Desktop `getAllMenusEnabledBuilder`."""
    builder = MenuStateBuilder()
    for menu_id in allMenuIds:
        builder.enable(menu_id)
    return builder


def get_repository_menu_builder(snapshot: MenuSnapshot) -> MenuStateBuilder:
    """Desktop `getRepositoryMenuBuilder`."""
    selected = snapshot.repository
    is_hosted_on_github = is_repository_hosted_on_github(selected)

    repository_selected = False
    on_non_default_branch = False
    on_branch = False
    on_detached_head = False
    has_changed_files = False
    has_conflicts = False
    has_published_branch = False
    network_action_in_progress = False
    tip_state_is_unknown = False
    branch_is_unborn = False
    rebase_in_progress = False
    branch_has_stash_entry = False
    on_contribution_target_default_branch = False
    has_contribution_target_default_branch = False

    repo_issues_enabled = (
        snapshot.selection_type == SelectionType.REPOSITORY
        and isinstance(selected, Repository)
        and get_repo_issues_enabled(selected)
    )

    if snapshot.selection_type == SelectionType.REPOSITORY:
        repository_selected = True
        tip = tip_from_status(snapshot.status, snapshot.tip_branch)
        default_branch = snapshot.default_branch
        on_branch = tip.kind == TipState.VALID
        on_detached_head = tip.kind == TipState.DETACHED
        tip_state_is_unknown = tip.kind == TipState.UNKNOWN
        branch_is_unborn = tip.kind == TipState.UNBORN
        contribution_target = snapshot.contribution_target
        has_contribution_target_default_branch = contribution_target is not None
        on_contribution_target_default_branch = (
            tip.kind == TipState.VALID
            and contribution_target is not None
            and tip.branch is not None
            and contribution_target.name == tip.branch.name
        )
        if tip.kind == TipState.VALID and tip.branch is not None:
            if default_branch is not None:
                on_non_default_branch = tip.branch.name != default_branch.name
            else:
                on_non_default_branch = True
            has_published_branch = bool(tip.branch.upstream)
            branch_has_stash_entry = snapshot.stash_entry is not None
        else:
            on_non_default_branch = True

        network_action_in_progress = snapshot.is_push_pull_fetch_in_progress
        rebase_in_progress = snapshot.rebase_in_progress
        working_directory = (
            snapshot.status.working_directory if snapshot.status is not None else WorkingDirectoryStatus()
        )
        has_conflicts = snapshot.rebase_in_progress or (
            snapshot.status is not None
            and (
                snapshot.status.merge_head_found
                or snapshot.status.is_cherry_picking_head_found
                or snapshot.status.do_conflicted_files_exist
            )
        ) or has_conflicted_files(working_directory)
        has_changed_files = len(working_directory.files) > 0

    builder = MenuStateBuilder()
    window_open = snapshot.window_open
    in_welcome_flow = snapshot.show_welcome_flow
    repository_active = window_open and repository_selected and not in_welcome_flow

    if repository_active:
        for menu_id in repositoryScopedIDs:
            builder.enable(menu_id)
        builder.set_enabled(
            "rename-branch",
            (on_non_default_branch or not has_published_branch) and not branch_is_unborn and not on_detached_head,
        )
        builder.set_enabled(
            "delete-branch",
            on_non_default_branch and not branch_is_unborn and not on_detached_head,
        )
        builder.set_enabled(
            "update-branch-with-contribution-target-branch",
            on_branch and has_contribution_target_default_branch and not on_contribution_target_default_branch,
        )
        builder.set_enabled("merge-branch", on_branch)
        builder.set_enabled("squash-and-merge-branch", on_branch)
        builder.set_enabled("rebase-branch", on_branch)
        builder.set_enabled("compare-on-github", is_hosted_on_github and has_published_branch)
        builder.set_enabled("branch-on-github", is_hosted_on_github and has_published_branch)
        builder.set_enabled("view-repository-on-github", is_hosted_on_github)
        builder.set_enabled("create-issue-in-repository-on-github", repo_issues_enabled)
        builder.set_enabled(
            "create-pull-request",
            is_hosted_on_github and not branch_is_unborn and not on_detached_head,
        )
        builder.set_enabled(
            "preview-pull-request",
            not branch_is_unborn and not on_detached_head and is_hosted_on_github,
        )
        builder.set_enabled(
            "push",
            not branch_is_unborn and not on_detached_head and not network_action_in_progress,
        )
        builder.set_enabled("pull", has_published_branch and not network_action_in_progress)
        builder.set_enabled(
            "create-branch",
            not tip_state_is_unknown and not branch_is_unborn and not rebase_in_progress,
        )
        builder.set_enabled(
            "discard-all-changes",
            repository_active and has_changed_files and not rebase_in_progress,
        )
        builder.set_enabled(
            "stash-all-changes",
            has_changed_files and on_branch and not rebase_in_progress and not has_conflicts,
        )
        builder.set_enabled("compare-to-branch", not on_detached_head)
        builder.set_enabled("toggle-stashed-changes", branch_has_stash_entry)
        if snapshot.selection_type == SelectionType.MISSING:
            builder.disable("open-external-editor")
    else:
        for menu_id in repositoryScopedIDs:
            builder.disable(menu_id)
        builder.disable("view-repository-on-github")
        builder.disable("create-pull-request")
        builder.disable("preview-pull-request")
        builder.disable("create-issue-in-repository-on-github")
        if snapshot.selection_type == SelectionType.MISSING:
            github = getattr(selected, "github", None) if selected is not None else None
            if github is not None:
                builder.enable("view-repository-on-github")
            builder.enable("remove-repository")
        builder.disable("create-branch")
        builder.disable("rename-branch")
        builder.disable("delete-branch")
        builder.disable("discard-all-changes")
        builder.disable("stash-all-changes")
        builder.disable("update-branch-with-contribution-target-branch")
        builder.disable("merge-branch")
        builder.disable("squash-and-merge-branch")
        builder.disable("rebase-branch")
        builder.disable("push")
        builder.disable("pull")
        builder.disable("compare-to-branch")
        builder.disable("compare-on-github")
        builder.disable("branch-on-github")
        builder.disable("toggle-stashed-changes")
    return builder


def get_in_welcome_flow_builder(in_welcome_flow: bool) -> MenuStateBuilder:
    """Desktop `getInWelcomeFlowBuilder`."""
    builder = MenuStateBuilder()
    if in_welcome_flow:
        for menu_id in welcomeScopedIds:
            builder.disable(menu_id)
    else:
        for menu_id in welcomeScopedIds:
            builder.enable(menu_id)
    return builder


def get_no_repositories_builder(snapshot: MenuSnapshot) -> MenuStateBuilder:
    """Desktop `getNoRepositoriesBuilder`."""
    builder = MenuStateBuilder()
    if snapshot.repository_count == 0:
        builder.disable("show-repository-list")
    return builder


def get_app_menu_builder(snapshot: MenuSnapshot) -> MenuStateBuilder:
    """Desktop `getAppMenuBuilder` (`resizablePaneActive`)."""
    builder = MenuStateBuilder()
    enabled = snapshot.resizable_pane_active
    builder.set_enabled("increase-active-resizable-width", enabled)
    builder.set_enabled("decrease-active-resizable-width", enabled)
    return builder


def get_menu_state_builder(snapshot: MenuSnapshot) -> MenuStateBuilder:
    """Desktop `getMenuState` as a builder (Desktop ids)."""
    if snapshot.current_popup:
        return get_all_menus_disabled_builder()
    return (
        get_all_menus_enabled_builder()
        .merge(get_repository_menu_builder(snapshot))
        .merge(get_app_menu_builder(snapshot))
        .merge(get_in_welcome_flow_builder(snapshot.show_welcome_flow))
        .merge(get_no_repositories_builder(snapshot))
    )


def get_menu_state_from_snapshot(snapshot: MenuSnapshot) -> dict[str, bool]:
    """Native Gio action enablement from a `MenuSnapshot`."""
    return _native_enabled(get_menu_state_builder(snapshot))


def menu_snapshot_from_store(
    store: Any,
    *,
    window_open: bool = True,
    current_popup: bool | None = None,
) -> MenuSnapshot:
    """Build a `MenuSnapshot` from `AppStore` (GTK-free)."""
    if current_popup is None:
        current_popup = getattr(store, "popup", None) is not None
    cloning = getattr(store, "selected_cloning", None)
    repo = getattr(store, "selected_repository", None)
    selection_type: SelectionType | None = None
    status: IStatusResult | None = None
    default_branch: Branch | None = None
    contribution_target: Branch | None = None
    tip_branch: Branch | None = None
    stash_entry = None
    rebase = False
    network = False
    selected: Repository | CloningRepository | None
    if cloning is not None:
        selection_type = SelectionType.CLONING
        selected = cloning
        repo = None
    elif repo is not None and repo.is_missing:
        selection_type = SelectionType.MISSING
        selected = repo
    elif repo is not None:
        selection_type = SelectionType.REPOSITORY
        selected = repo
        state = store.state_for(repo)
        status = state.status
        finder = getattr(store, "find_default_branch_for", None)
        default_branch = finder(repo) if callable(finder) else None
        contrib = getattr(store, "contribution_target_default_branch", None)
        contribution_target = contrib(repo) if callable(contrib) else None
        if status is not None and status.current_branch:
            tip_branch = next(
                (item for item in state.branches if item.name == status.current_branch and item.is_local),
                None,
            )
            stash_fn = getattr(store, "desktop_stash_for_branch", None)
            stash_entry = stash_fn(repo, status.current_branch) if callable(stash_fn) else None
        rebase = bool(status is not None and status.rebase_internal_state)
        kind = getattr(store, "progress_kind", None)
        network = kind in {"push", "pull", "fetch"}
    else:
        selected = None
    repos = list(getattr(store, "repositories", []) or [])
    clones = list(getattr(store, "cloning", []) or [])
    return MenuSnapshot(
        current_popup=bool(current_popup),
        show_welcome_flow=getattr(store, "welcome_step", None) is not None,
        window_open=window_open,
        resizable_pane_active=bool(getattr(store, "resizable_pane_active", False)),
        repository_count=len(repos) + len(clones),
        selection_type=selection_type,
        repository=selected,
        status=status,
        default_branch=default_branch,
        contribution_target=contribution_target,
        tip_branch=tip_branch,
        stash_entry=stash_entry,
        is_push_pull_fetch_in_progress=network,
        rebase_in_progress=rebase,
    )


def get_menu_state(
    store: Any,
    *,
    window_open: bool = True,
    current_popup: bool | None = None,
) -> dict[str, bool]:
    """Desktop `getMenuState` keyed by native Gio.SimpleAction names."""
    return get_menu_state_from_snapshot(
        menu_snapshot_from_store(store, window_open=window_open, current_popup=current_popup)
    )


def update_menu_state(
    store: Any,
    *,
    window_open: bool = True,
    current_popup: bool | None = None,
) -> dict[str, bool]:
    """Desktop `updateMenuState` (native returns the batched enablement map)."""
    return get_menu_state(store, window_open=window_open, current_popup=current_popup)


def apply_menu_state(
    lookup_action: Callable[[str], Any],
    enabled_by_action: dict[str, bool],
) -> None:
    """Apply `getMenuState` to Gio actions (`set_enabled`)."""
    for name, enabled in enabled_by_action.items():
        action = lookup_action(name)
        if action is not None:
            action.set_enabled(enabled)


def get_push_label(*, force_push: bool, ask_for_confirmation: bool) -> str:
    """Desktop `getPushLabel` (Linux)."""
    if not force_push:
        return "Push"
    return "Force push…" if ask_for_confirmation else "Force push"


def stash_all_changes_label(confirm: bool) -> str:
    """Desktop `confirmStashAllChangesLabel` / `stashAllChangesLabel`."""
    return "Stash all changes…" if confirm else "Stash all changes"


def get_stashed_changes_label(visible: bool) -> str:
    """Desktop `getStashedChangesLabel` (Linux)."""
    return "Hide stashed changes" if visible else "Show stashed changes"


# Desktop `build-default-menu.ts` non-Darwin mnemonics (`E&xit`, `Go to &Summary`).
LINUX_FILE_QUIT_MNEMONIC = "E&xit"
LINUX_GO_TO_SUMMARY_MNEMONIC = "Go to &Summary"


def file_quit_label() -> str:
    """Desktop Linux File quit label (`E&xit` without the mnemonic ampersand)."""
    return "Exit"


def go_to_summary_label() -> str:
    """Desktop Linux View `Go to &Summary`."""
    return "Go to Summary"


# Desktop camelCase aliases for concatenated-source parity checks.
getMenuState = get_menu_state
getPushLabel = get_push_label
getStashedChangesLabel = get_stashed_changes_label
fileQuitLabel = file_quit_label
goToSummaryLabel = go_to_summary_label
confirmStashAllChangesLabel = "Stash all changes…"
stashAllChangesLabel = "Stash all changes"
getRepositoryMenuBuilder = get_repository_menu_builder
getAppMenuBuilder = get_app_menu_builder
getInWelcomeFlowBuilder = get_in_welcome_flow_builder
getNoRepositoriesBuilder = get_no_repositories_builder
getAllMenusDisabledBuilder = get_all_menus_disabled_builder
getAllMenusEnabledBuilder = get_all_menus_enabled_builder
getRepoIssuesEnabled = get_repo_issues_enabled
isRepositoryHostedOnGitHub = is_repository_hosted_on_github
updateMenuState = update_menu_state

__all__ = [
    "IMenuItemState",
    "MENU_ID_TO_ACTION",
    "MenuSnapshot",
    "MenuStateBuilder",
    "allMenuIds",
    "apply_menu_state",
    "getMenuState",
    "get_menu_state",
    "get_menu_state_from_snapshot",
    "get_repo_issues_enabled",
    "is_repository_hosted_on_github",
    "menu_snapshot_from_store",
    "repositoryScopedIDs",
    "tip_from_status",
    "updateMenuState",
    "update_menu_state",
    "welcomeScopedIds",
]
