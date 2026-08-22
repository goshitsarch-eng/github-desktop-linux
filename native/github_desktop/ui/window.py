"""Main GitHub Desktop window (Adwaita)."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..features import should_render_application_menu
from ..models import (
    AppFileStatusKind,
    BannerType,
    BranchType,
    ChangesListFilter,
    CommitMessage,
    ComparisonMode,
    ComputedAction,
    DiffSelectionType,
    FoldoutType,
    ForcePushBranchState,
    HistoryTabMode,
    ManualConflictResolution,
    MultiCommitOperationKind,
    PopupType,
    PreferencesTab,
    PullRequestSuggestedNextAction,
    RepositorySectionTab,
    RepositorySettingsTab,
    StashedChangesLoadStates,
    TutorialStep,
    WelcomeStep,
    WorkingDirectoryFileChange,
    format_commit_attribution,
    get_conflicted_files,
    get_label_for_manual_resolution_option,
    get_untracked_files,
    has_conflicted_files,
    is_dotcom_endpoint,
    is_partially_committable_submodule,
    is_uncommittable_submodule,
    map_status,
    name_of,
    path_label,
    commit_summary_placeholder,
    submodule_include_tooltip,
    enable_commit_message_generation,
    is_valid_tutorial_step,
)
from ..clamp import clamp
from ..push_pull import (
    PUSH_PULL_BUTTON_STATE_ID,
    describe_push_pull,
    format_commit_relative_time,
    format_last_fetched,
    network_progress_chrome,
    HANG_ON,
)
from ..settings import (
    defaultBranchDropdownWidth,
    defaultCommitSummaryWidth,
    defaultPushPullButtonWidth,
    defaultSidebarWidth,
    defaultStashedFilesWidth,
)
from ..feature_flag import enable_resizing_toolbar_buttons
from ..shells import open_external, open_in_default_program
from ..menu_update import (
    apply_menu_state,
    file_quit_label,
    get_push_label,
    get_stashed_changes_label,
    go_to_summary_label,
    stash_all_changes_label,
    updateMenuState,
)
from ..store import AppStore
from ..text_tokens import MaxSummaryLength
from ..truncate import truncate_with_ellipsis
from ..fuzzy_find import filter_items
from ..version import APP_NAME
from .avatar import Avatar, AvatarStack, users_from_commit
from .author_input import AuthorInput, bind_store_exact_match
from .autocompletion import (
    TextViewCompleter,
    install_entry_completion,
    populate_completion_store,
    summary_length_hint,
    token_before_cursor,
)
from .branches import (
    BranchesFoldout,
    compare_placeholder_text,
    generate_branch_context_menu_items,
)
from .checks import present_checks_popover
from .dialogs import (
    present_popup,
    show_preferences,
    show_reorder_commits,
    _clear_listbox,
    _clone_list_empty_title,
    _clone_list_loading_title,
    _render_grouped_clone_list,
)
from .diff_view import DiffViewer
from .history import ExpandableCommitSummary
from .menus import (
    CopyFilePathLabel,
    CopyRelativeFilePathLabel,
    CopySelectedPathsLabel,
    CopySelectedRelativePathsLabel,
    GitIgnoreFileName,
    OpenWithDefaultProgramLabel,
    RevealInFileManagerLabel,
    alias_verb,
    apply_edit_menu_action,
    attach_paned_keyboard_resize,
    attach_paned_reset,
    attach_right_click,
    changes_list_context_menu_blocked,
    commit_message_shared_menu_specs,
    commit_spellcheck_menu_label,
    copy_tags_menu_label,
    delete_tags_menu_item,
    discard_changes_item_label,
    find_active_resizable,
    ignore_extension_globs,
    ignore_folder_labels,
    is_safe_file_extension,
    rebase_changed_file_menu_labels,
    resizable_limit,
    resize_active_resizable,
    wrap_toolbar_resizable,
    DefaultMaxWidth,
    clear_box,
    committed_file_context_items,
    copy_text,
    generate_repository_list_context_menu_specs,
    new_repository_button_menu_items,
    ADD_EXISTING_REPOSITORY_FROM_LOCAL_DRIVE,
    CLONE_REPOSITORY_FROM_INTERNET,
    CREATE_NEW_REPOSITORY_ON_LOCAL_DRIVE,
    REPOSITORY_TOOLBAR_DESCRIPTION,
    repository_toolbar_title,
    BRANCH_TOOLBAR_DESCRIPTION,
    branch_toolbar_chrome,
    open_in_editor_label,
    open_in_shell_label,
    is_external_editor_available,
    OPEN_THE_REPOSITORY_IN_YOUR_EXTERNAL_EDITOR,
    SELECT_YOUR_EDITOR_IN_OPTIONS,
    remove_repository_label,
    show_context_menu,
    unpushed_tags_for_commit,
    view_on_github_label,
    widget_is_or_inside,
    YOUR_ACCOUNT_EMAILS,
    UPDATE_EMAIL_LABEL,
    IGNORE_LABEL,
    LEARN_MORE_ABOUT_COMMIT_ATTRIBUTION,
    THIS_COMMIT_WILL_BE_MISATTRIBUTED,
    THIS_EMAIL_ADDRESS_IS_DISALLOWED,
    commit_message_avatar_aria_label,
    commit_message_avatar_choose_local_email_copy,
    commit_message_avatar_email_leading_text,
    commit_message_avatar_warning_type,
    committing_as_title,
    git_config_popover_copy,
    open_git_settings_label,
)
from .multi_commit import MERGE_OPTIONS, _their_branch, merge_cta_message, show_confirm_abort, show_conflicts_dialog
from .spellcheck import attach_spellcheck
from .stash import StashDiffViewer
from .tutorial import TutorialPanel


STATUS_CLASS = {
    AppFileStatusKind.NEW: "file-status-new",
    AppFileStatusKind.UNTRACKED: "file-status-new",
    AppFileStatusKind.MODIFIED: "file-status-modified",
    AppFileStatusKind.DELETED: "file-status-deleted",
    AppFileStatusKind.RENAMED: "file-status-renamed",
    AppFileStatusKind.COPIED: "file-status-renamed",
    AppFileStatusKind.CONFLICTED: "file-status-conflicted",
}

CONFLICT_BANNER_KINDS = {
    BannerType.MERGE_CONFLICTS_FOUND,
    BannerType.REBASE_CONFLICTS_FOUND,
    BannerType.CHERRY_PICK_CONFLICTS_FOUND,
    BannerType.CONFLICTS_FOUND,
}

SUCCESS_BANNER_KINDS = {
    BannerType.SUCCESSFUL_MERGE,
    BannerType.SUCCESSFUL_REBASE,
    BannerType.SUCCESSFUL_CHERRY_PICK,
    BannerType.SUCCESSFUL_SQUASH,
    BannerType.SUCCESSFUL_REORDER,
}


def _banner_noun(count: int) -> str:
    return "commit" if count == 1 else "commits"


def keyboard_reorder_intro_message(count: int) -> str:
    """Desktop commit-list aria live copy before an insertion point is chosen."""
    plural = "s" if count != 1 else ""
    return (
        f"Use the Up and Down arrow keys to choose a new location for the selected commit{plural}, "
        "then press Enter to confirm or Escape to cancel."
    )


def keyboard_reorder_insert_message(count: int, row: int, total: int) -> str:
    """Desktop `Press Enter to insert the selected commit(s) before commit N`."""
    plural = "s" if count != 1 else ""
    insertion_point = f"before commit {row + 1}" if row < total else f"after commit {row}"
    return (
        f"Press Enter to insert the selected commit{plural} {insertion_point} or Escape to cancel."
    )


def format_banner_text(kind: BannerType, banner) -> str:
    """Desktop success/conflict banner copy."""
    if kind == BannerType.SUCCESSFUL_MERGE:
        if banner.their_branch:
            return f"Successfully merged {banner.their_branch} into {banner.our_branch or ''}"
        return f"Successfully merged into {banner.our_branch or ''}"
    if kind == BannerType.SUCCESSFUL_REBASE:
        if banner.target_branch and banner.their_branch:
            return f"Successfully rebased {banner.target_branch} onto {banner.their_branch}"
        return f"Successfully rebased {banner.target_branch or ''}"
    if kind == BannerType.SUCCESSFUL_CHERRY_PICK:
        target = banner.target_branch or ""
        return f"Successfully copied {banner.count} {_banner_noun(banner.count)} to {target}."
    if kind == BannerType.SUCCESSFUL_SQUASH:
        return f"Successfully squashed {banner.count} {_banner_noun(banner.count)}."
    if kind == BannerType.SUCCESSFUL_REORDER:
        return f"Successfully reordered {banner.count} {_banner_noun(banner.count)}."
    if kind == BannerType.MERGE_CONFLICTS_FOUND:
        return f"Resolve conflicts and commit to merge into {banner.our_branch or ''}."
    if kind == BannerType.REBASE_CONFLICTS_FOUND:
        return f"Resolve conflicts to continue rebasing {banner.target_branch or ''}."
    if kind == BannerType.CHERRY_PICK_CONFLICTS_FOUND:
        return f"Resolve conflicts to continue cherry-picking onto {banner.target_branch or ''}."
    if kind == BannerType.CONFLICTS_FOUND:
        op = banner.operation_description or "the operation"
        if banner.target_branch:
            return f"Resolve conflicts to continue {op} {banner.target_branch}."
        return f"Resolve conflicts to continue {op}."
    if kind == BannerType.BRANCH_ALREADY_UP_TO_DATE:
        ours = banner.our_branch or ""
        if banner.their_branch:
            return f"{ours} is already up to date with {banner.their_branch}"
        return f"{ours} is already up to date"
    if kind == BannerType.CHERRY_PICK_UNDONE:
        target = banner.target_branch or ""
        return (
            f"Cherry-pick undone. Successfully removed the {banner.count} copied "
            f"{_banner_noun(banner.count)} from {target}."
        )
    if kind == BannerType.SQUASH_UNDONE:
        return f"Squash of {banner.count} {_banner_noun(banner.count)} undone."
    if kind == BannerType.REORDER_UNDONE:
        return f"Reorder of {banner.count} {_banner_noun(banner.count)} undone."
    mapping = {
        BannerType.OPEN_THANK_YOU_CARD: "The Desktop team would like to thank you for your contributions.",
        BannerType.DETACHED_HEAD: "You are in a detached HEAD state. Create a branch to keep your work.",
        BannerType.ACCESSIBILITY_SETTINGS: (
            "Check out the new accessibility settings to control the visibility of "
            "the link underlines and diff check marks."
        ),
        BannerType.OS_VERSION_NO_LONGER_SUPPORTED: (
            "This operating system is no longer supported. Software updates have been disabled."
        ),
    }
    return mapping.get(kind, kind.value)


class _AllocatedBox(Gtk.Box):
    """Gtk.Box that reports allocation changes (GTK 4 has no size-allocate signal)."""

    __gtype_name__ = "GitHubDesktopAllocatedBox"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._on_allocated = None
        self._last_size = (0, 0)

    def do_size_allocate(self, width: int, height: int, baseline: int) -> None:
        Gtk.Box.do_size_allocate(self, width, height, baseline)
        if width <= 0 or (width, height) == self._last_size:
            return
        self._last_size = (width, height)
        callback = self._on_allocated
        if callback is not None:
            callback(width, height)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: AppStore) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.store = store
        self.set_default_size(store.settings.window_width, store.settings.window_height)
        self._building = False
        self._applying_sidebar_width = False
        self._applying_constraints = False
        self._constraint_idle = 0
        self._branch_resize_limits = {"min": 160.0, "max": 720.0}
        self._push_resize_limits = {"min": 160.0, "max": 720.0}
        self._light_update = False
        self._keyboard_reorder = None
        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)
        self._overlay = Gtk.Overlay()
        self._toast.set_child(self._overlay)
        self._root = _AllocatedBox(orientation=Gtk.Orientation.VERTICAL)
        self._root._on_allocated = self._on_root_allocated
        self._overlay.set_child(self._root)
        self._window_info_box = Gtk.Box()
        self._window_info_box.add_css_class("toast-notification-container")
        self._window_info_box.set_halign(Gtk.Align.CENTER)
        self._window_info_box.set_valign(Gtk.Align.START)
        self._window_info_box.set_margin_top(28)
        self._window_info_box.set_visible(False)
        self._window_info = Gtk.Label()
        self._window_info.add_css_class("toast-notification")
        self._window_info.set_wrap(True)
        self._window_info_box.append(self._window_info)
        self._overlay.add_overlay(self._window_info_box)
        self._window_info_source = 0
        self._last_zoom = store.settings.zoom_factor
        self._banner = Adw.Banner()
        self._banner.set_revealed(False)
        self._banner.connect("button-clicked", self._on_banner_clicked)
        self._root.append(self._banner)
        self._stack = Gtk.Stack()
        self._stack.set_vexpand(True)
        self._root.append(self._stack)
        self._welcome = self._build_welcome()
        self._empty = self._build_empty()
        self._repo_page = self._build_repo_page()
        self._stack.add_named(self._welcome, "welcome")
        self._stack.add_named(self._empty, "empty")
        self._stack.add_named(self._repo_page, "repo")
        self._install_actions()
        self._install_shortcuts()
        self._install_global_keys()
        self._install_file_drop()
        self.store.subscribe(self._on_store)
        self.store.api_repositories.subscribe(self._on_api_repositories)
        self.connect("close-request", self._on_close)
        self.connect("notify::fullscreened", self._on_fullscreened)
        self.connect("notify::maximized", lambda *_: self._schedule_resizable_constraints())
        self.connect("map", lambda *_: GLib.idle_add(self._apply_resizable_constraints))
        self._apply_underline_links()
        self._on_store()

    def _on_close(self, *_args: object) -> bool:
        alloc = self.get_width(), self.get_height()
        if alloc[0] > 0:
            self.store.settings.window_width = alloc[0]
            self.store.settings.window_height = alloc[1]
            if hasattr(self, "_view_stack") and self._view_stack.get_visible_child_name() == "history":
                if hasattr(self, "_history_paned"):
                    pos = self._history_paned.get_position()
                    if pos > 0:
                        self.store.settings.sidebar_width = pos
            elif hasattr(self, "_changes_paned"):
                pos = self._changes_paned.get_position()
                if pos > 0:
                    self.store.settings.sidebar_width = pos
            if hasattr(self, "_hist_files_paned"):
                pos = self._hist_files_paned.get_position()
                if pos > 0:
                    self.store.settings.commit_summary_width = pos
            if hasattr(self, "_stash_viewer"):
                paned = getattr(self._stash_viewer, "_files_paned", None)
                if paned is not None:
                    pos = paned.get_position()
                    if pos > 0:
                        self.store.settings.stashed_files_width = pos
            if hasattr(self, "_branch_btn"):
                width = self._branch_btn.get_allocated_width()
                if width > 0:
                    self.store.set_branch_dropdown_width(width)
            if hasattr(self, "_push_box"):
                width = self._push_box.get_allocated_width()
                if width > 0:
                    self.store.set_push_pull_button_width(width)
            self.store.persist_settings()
        self._flush_commit_form()
        if getattr(self, "_window_info_source", 0):
            GLib.source_remove(self._window_info_source)
            self._window_info_source = 0
        return False

    def _toggle_fullscreen(self) -> None:
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_fullscreened(self, *_args: object) -> None:
        if self.is_fullscreen():
            self._show_window_info("Press F11 to exit fullscreen", hold_ms=3000, zoom=False)
        self._schedule_resizable_constraints()

    def _on_root_allocated(self, width: int, _height: int) -> None:
        if width <= 0:
            return
        self._schedule_resizable_constraints()

    def _schedule_resizable_constraints(self) -> None:
        if getattr(self, "_building", False) or getattr(self, "_constraint_idle", 0):
            return
        self._constraint_idle = GLib.idle_add(self._apply_resizable_constraints)

    def _apply_resizable_constraints(self) -> bool:
        self._constraint_idle = 0
        if getattr(self, "_building", False) or getattr(self, "_applying_constraints", False):
            return False
        width = self.get_width()
        if width <= 0:
            return False
        self.store.update_resizable_constraints(width)
        self._sync_resize_limits()
        self._applying_constraints = True
        self._applying_sidebar_width = True
        try:
            sidebar = int(clamp(self.store.sidebar_constraints))
            if hasattr(self, "_changes_paned") and abs(self._changes_paned.get_position() - sidebar) > 1:
                self._changes_paned.set_position(sidebar)
            if hasattr(self, "_history_paned") and abs(self._history_paned.get_position() - sidebar) > 1:
                self._history_paned.set_position(sidebar)
            files = int(clamp(self.store.commit_summary_constraints))
            if hasattr(self, "_hist_files_paned") and abs(self._hist_files_paned.get_position() - files) > 1:
                self._hist_files_paned.set_position(files)
            stash = int(clamp(self.store.stashed_files_constraints))
            paned = getattr(getattr(self, "_stash_viewer", None), "_files_paned", None)
            if paned is not None and abs(paned.get_position() - stash) > 1:
                paned.set_position(stash)
            branch = int(clamp(self.store.branch_dropdown_constraints))
            if hasattr(self, "_branch_btn"):
                self._branch_btn.set_size_request(max(1, branch), -1)
            push = int(clamp(self.store.push_pull_constraints))
            target = getattr(self, "_push_box", None)
            if target is not None:
                target.set_size_request(max(1, push), -1)
            self._sync_repository_foldout_width()
            self._sync_branch_foldout_width()
        finally:
            self._applying_constraints = False
            self._applying_sidebar_width = False
        return False

    def _sync_resize_limits(self) -> None:
        if hasattr(self, "_branch_resize_limits"):
            self._branch_resize_limits["min"] = self.store.branch_dropdown_constraints.min
            self._branch_resize_limits["max"] = self.store.branch_dropdown_constraints.max
        if hasattr(self, "_push_resize_limits"):
            self._push_resize_limits["min"] = self.store.push_pull_constraints.min
            self._push_resize_limits["max"] = self.store.push_pull_constraints.max

    def _show_zoom_info(self, factor: float) -> None:
        """Desktop `ZoomInfo` overlay when Ctrl+0/=/− changes the zoom factor."""
        percent = f"{round(factor * 100)}%"
        self._show_window_info(percent, hold_ms=750, zoom=True)

    def _show_window_info(self, text: str, *, hold_ms: int = 3000, zoom: bool = False) -> None:
        """Desktop `FullScreenInfo` / `ZoomInfo` overlay toast."""
        if not hasattr(self, "_window_info"):
            return
        self._window_info.set_text(text)
        if zoom:
            self._window_info.add_css_class("window-zoom-info")
        else:
            self._window_info.remove_css_class("window-zoom-info")
        self._window_info_box.set_visible(True)
        if self._window_info_source:
            GLib.source_remove(self._window_info_source)
        self._window_info_source = GLib.timeout_add(hold_ms, self._hide_window_info)

    def _hide_window_info(self) -> bool:
        if hasattr(self, "_window_info_box"):
            self._window_info_box.set_visible(False)
        self._window_info_source = 0
        return False

    def _on_store(self) -> None:
        if self._building:
            return
        popup = self.store.popup
        if self.store._progress_only_emit and not popup:
            self.store._progress_only_emit = False
            self._update_network_progress()
            self._sync_menu_state()
            return
        if self._light_update:
            return
        if self.store.welcome_step is not None:
            self._refresh_welcome()
            self._stack.set_visible_child_name("welcome")
        elif (not self.store.repositories and not self.store.cloning) or self.store.tutorial_step == TutorialStep.PAUSED:
            self._refresh_empty()
            self._stack.set_visible_child_name("empty")
        else:
            self._stack.set_visible_child_name("repo")
            self._refresh_repo()
        self._sync_foldouts()
        width = self.get_width()
        if width > 0:
            self.store.update_resizable_constraints(width)
            self._sync_resize_limits()
        if self.store.banner:
            kind = self.store.banner.type
            self._banner.set_title(format_banner_text(kind, self.store.banner))
            if kind == BannerType.OPEN_THANK_YOU_CARD:
                self._banner.set_button_label("Open Your Card")
            elif kind == BannerType.DETACHED_HEAD:
                self._banner.set_button_label("Create branch")
            elif kind == BannerType.ACCESSIBILITY_SETTINGS:
                self._banner.set_button_label("Open settings")
            elif kind == BannerType.OS_VERSION_NO_LONGER_SUPPORTED:
                self._banner.set_button_label("Support details")
            elif kind in CONFLICT_BANNER_KINDS:
                self._banner.set_button_label("View conflicts")
            elif kind in SUCCESS_BANNER_KINDS and self.store.banner.undo_sha:
                self._banner.set_button_label("Undo")
            else:
                self._banner.set_button_label("Dismiss")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)
        zoom = self.store.settings.zoom_factor
        if zoom != getattr(self, "_last_zoom", zoom):
            self._last_zoom = zoom
            self._show_zoom_info(zoom)
        popup = self.store.popup
        if popup or self.store.all_popups:
            for current in self.store.take_popups():
                present_popup(self, self.store, current.type, current.payload)
        self._apply_underline_links()
        self._sync_menu_state()
        if self.store.focus_commit_message:
            self._apply_commit_message_focus()

    def _apply_underline_links(self) -> None:
        if self.store.settings.underline_links:
            self.add_css_class("underline-links")
        else:
            self.remove_css_class("underline-links")

    def _banner_text(self, kind: BannerType, banner) -> str:
        return format_banner_text(kind, banner)

    def _on_banner_clicked(self, *_args: object) -> None:
        banner = self.store.banner
        if banner and banner.type == BannerType.OPEN_THANK_YOU_CARD:
            self.store.open_thank_you_card()
            return
        if banner and banner.type == BannerType.DETACHED_HEAD:
            self.store.show_popup(PopupType.CREATE_BRANCH)
            return
        if banner and banner.type == BannerType.ACCESSIBILITY_SETTINGS:
            self.store.dismiss_accessibility_banner()
            show_preferences(self, self.store, PreferencesTab.ACCESSIBILITY)
            return
        if banner and banner.type == BannerType.OS_VERSION_NO_LONGER_SUPPORTED:
            self.store.clear_banner()
            open_external(
                "https://docs.github.com/en/desktop/installing-and-configuring-github-desktop/overview/supported-operating-systems"
            )
            return
        if banner and banner.type in CONFLICT_BANNER_KINDS:
            kind = banner.operation_kind or {
                BannerType.MERGE_CONFLICTS_FOUND: MultiCommitOperationKind.MERGE.value,
                BannerType.REBASE_CONFLICTS_FOUND: MultiCommitOperationKind.REBASE.value,
                BannerType.CHERRY_PICK_CONFLICTS_FOUND: MultiCommitOperationKind.CHERRY_PICK.value,
            }.get(banner.type, MultiCommitOperationKind.MERGE.value)
            self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind=kind, step="conflicts")
            return
        if banner and banner.type in SUCCESS_BANNER_KINDS and banner.undo_sha:
            repo = self.store.selected_repository
            if repo:
                self.store.undo_multi_commit(repo)
            return
        self.store.clear_banner()

    def _install_actions(self) -> None:
        def add(name: str, callback) -> None:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda *_: callback())
            self.add_action(action)

        add("new-repository", lambda: self.store.show_popup(PopupType.CREATE_REPOSITORY))
        add("add-local-repository", lambda: self.store.show_popup(PopupType.ADD_REPOSITORY))
        add("clone-repository", lambda: self.store.show_popup(PopupType.CLONE_REPOSITORY))
        add("preferences", lambda: show_preferences(self, self.store))
        add("show-changes", lambda: self._show_changes(should_focus_changes=True))
        add("show-history", lambda: self._show_history(should_focus_history=True))
        add("choose-repository", self._toggle_repo_sidebar)
        add("show-branches", self._show_branches_foldout)
        add("go-to-commit-message", self._go_to_commit_message)
        add("push", self._push_from_menu)
        add("force-push", lambda: self._repo_op(self.store.confirm_or_force_push))
        add("pull", lambda: self._repo_op(self.store.pull_repo))
        add("fetch", lambda: self._repo_op(self.store.fetch_repo))
        add("remove-repository", lambda: self.store.show_popup(PopupType.REMOVE_REPOSITORY))
        add("view-on-github", lambda: self._repo_op(self.store.view_on_github))
        add("open-in-shell", lambda: self._repo_op(self.store.open_in_shell))
        add("open-working-directory", lambda: self._repo_op(self.store.open_working_directory))
        add("open-external-editor", lambda: self._repo_op(self.store.open_in_editor))
        add("create-issue", lambda: self._repo_op(self.store.create_issue))
        add("repository-settings", lambda: self.store.show_popup(PopupType.REPOSITORY_SETTINGS))
        add("create-branch", lambda: self.store.show_popup(PopupType.CREATE_BRANCH))
        add("rename-branch", lambda: self.store.show_popup(PopupType.RENAME_BRANCH))
        add("delete-branch", self._delete_branch)
        add("discard-all", lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, discarding_all=True))
        stash_all = Gio.SimpleAction.new("stash-all", None)
        stash_all.connect("activate", lambda *_: self._stash_all())
        self.add_action(stash_all)
        self._stash_all_action = stash_all
        add("merge-branch", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Merge"))
        add("squash-merge", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Squash"))
        add("rebase-branch", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Rebase"))
        add("compare-on-github", lambda: self._repo_op(self.store.compare_on_github))
        add("open-pull-request", lambda: self._repo_op(self.store.open_pull_request))
        add("preview-pull-request", lambda: self._repo_op(self.store.preview_pull_request))
        add("about", lambda: self.store.show_popup(PopupType.ABOUT))
        add("release-notes", lambda: self.store.show_popup(PopupType.RELEASE_NOTES))
        add("show-logs", self._show_logs)
        add("find", self._find)
        add("toggle-stash", lambda: self._repo_op(self.store.toggle_stash))
        add("undo-commit", self._undo)
        add("create-tag", lambda: self.store.show_popup(PopupType.CREATE_TAG))
        add("generate-commit-message", lambda: self._generate_commit_message())
        add("compare-to-branch", self._compare_to_branch)
        add("install-cli", self.store.install_cli)
        add("toggle-changes-filter", self.store.toggle_changes_filter)
        add("zoom-in", lambda: self.store.set_zoom(self.store.settings.zoom_factor + 0.1))
        add("zoom-out", lambda: self.store.set_zoom(self.store.settings.zoom_factor - 0.1))
        add("zoom-reset", lambda: self.store.set_zoom(1.0))
        add("update-from-default", lambda: self._repo_op(self.store.update_from_default_branch))
        add("branch-on-github", lambda: self._repo_op(self.store.view_branch_on_github))
        add("report-issue", lambda: open_external("https://github.com/goshitsarch-eng/github-desktop-linux/issues/new"))
        add("contact-support", lambda: open_external("https://github.com/contact?from_desktop_app=1"))
        add("show-guides", lambda: open_external("https://docs.github.com/en/desktop"))
        add("github-explore", lambda: self._repo_op(self.store.show_github_explore))
        add("cut", lambda: self._edit_action("cut"))
        add("copy", lambda: self._edit_action("copy"))
        add("paste", lambda: self._edit_action("paste"))
        add("select-all", lambda: self._edit_action("select-all"))
        add("edit-undo", lambda: self._edit_action("undo"))
        add("edit-redo", lambda: self._edit_action("redo"))
        add("increase-resizable", lambda: self._resize_active_resizable(True))
        add("decrease-resizable", lambda: self._resize_active_resizable(False))
        add("pr-suggested-preview", self._pr_suggested_preview)
        add("pr-suggested-create", self._pr_suggested_create)
        add("show-shortcuts", self._show_shortcuts)
        add("toggle-fullscreen", self._toggle_fullscreen)
        for name in ("increase-resizable", "decrease-resizable"):
            action = self.lookup_action(name)
            if action is not None:
                action.set_enabled(False)
        self.connect("notify::focus-widget", self._on_focus_widget)
        self.add_css_class("github-desktop-zoom")
        from .css import apply_zoom

        apply_zoom(self.store.settings.zoom_factor)

    def _install_shortcuts(self) -> None:
        ctrl = {
            "<Ctrl>n": "new-repository",
            "<Ctrl>o": "add-local-repository",
            "<Ctrl><Shift>o": "clone-repository",
            "<Ctrl>comma": "preferences",
            "<Ctrl>1": "show-changes",
            "<Ctrl>2": "show-history",
            "<Ctrl>t": "choose-repository",
            "<Ctrl>b": "show-branches",
            "<Ctrl>g": "go-to-commit-message",
            "<Ctrl>p": "push",
            "<Ctrl><Shift>p": "pull",
            "<Ctrl><Shift>t": "fetch",
            "<Ctrl>BackSpace": "remove-repository",
            "<Ctrl><Shift>g": "view-on-github",
            "<Ctrl>grave": "open-in-shell",
            "<Ctrl><Shift>f": "open-working-directory",
            "<Ctrl><Shift>a": "open-external-editor",
            "<Ctrl>i": "create-issue",
            "<Ctrl><Shift>n": "create-branch",
            "<Ctrl><Shift>r": "rename-branch",
            "<Ctrl><Shift>d": "delete-branch",
            "<Ctrl><Shift>BackSpace": "discard-all",
            "<Ctrl><Shift>s": "stash-all",
            "<Ctrl><Shift>m": "merge-branch",
            "<Ctrl><Shift>h": "squash-merge",
            "<Ctrl><Shift>e": "rebase-branch",
            "<Ctrl><Shift>c": "compare-on-github",
            "<Ctrl>r": "open-pull-request",
            "<Ctrl>f": "find",
            "<Ctrl>z": "edit-undo",
            "<Ctrl><Shift>z": "edit-redo",
            "<Ctrl>y": "edit-redo",
            "<Ctrl>9": "increase-resizable",
            "<Ctrl>8": "decrease-resizable",
            "<Alt>p": "preview-pull-request",
            "<Ctrl>h": "toggle-stash",
            "<Ctrl>l": "toggle-changes-filter",
            "<Ctrl>equal": "zoom-in",
            "<Ctrl>plus": "zoom-in",
            "<Ctrl>minus": "zoom-out",
            "<Ctrl>0": "zoom-reset",
            "<Ctrl><Shift>u": "update-from-default",
            "<Ctrl><Shift>b": "compare-to-branch",
            "<Ctrl><Alt>b": "branch-on-github",
        }
        for accel, name in ctrl.items():
            self.get_application().set_accels_for_action(f"win.{name}", [accel])
        self.get_application().set_accels_for_action("win.edit-redo", ["<Ctrl><Shift>z", "<Ctrl>y"])
        self.get_application().set_accels_for_action("win.zoom-in", ["<Ctrl>equal", "<Ctrl>plus"])
        self.get_application().set_accels_for_action("win.toggle-fullscreen", ["F11"])

    def _install_global_keys(self) -> None:
        """Desktop repository `onGlobalKeyDown` (Ctrl+Tab toggles Changes/History)."""
        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_global_key)
        self.add_controller(keys)

    def _on_global_key(self, _controller, keyval: int, _keycode: int, state) -> bool:
        """Desktop `onGlobalKeyDown`."""
        if keyval not in (Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab):
            return False
        if not (int(state) & int(Gdk.ModifierType.CONTROL_MASK)):
            return False
        if self.store.popup or self.store.all_popups:
            return False
        if self.store.foldout is not None:
            return False
        if hasattr(self, "_stack") and self._stack.get_visible_child_name() != "repo":
            return False
        self._change_tab()
        return True

    def _change_tab(self) -> None:
        """Desktop `changeTab`: toggle Changes/History (Ctrl+Tab)."""
        if self.store.selected_repository is None:
            return
        if self.store.section == RepositorySectionTab.HISTORY:
            self.store.set_section(RepositorySectionTab.CHANGES)
            if hasattr(self, "_view_stack"):
                self._view_stack.set_visible_child_name("changes")
        else:
            self.store.set_section(RepositorySectionTab.HISTORY)
            if hasattr(self, "_view_stack"):
                self._view_stack.set_visible_child_name("history")

    def _repo_op(self, fn) -> None:
        repo = self.store.selected_repository
        if repo:
            fn(repo)

    def _push_from_menu(self) -> None:
        """Desktop Push menu / Ctrl+P (`pushEventType`)."""
        repo = self.store.selected_repository
        if not repo:
            return
        if self.store.current_branch_force_push_state(repo) == ForcePushBranchState.RECOMMENDED:
            self.store.confirm_or_force_push(repo)
            return
        self.store.push_repo(repo)

    def _delete_branch(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        if state.current_pull_request:
            self.store.show_popup(PopupType.DELETE_PULL_REQUEST, pull_request=state.current_pull_request)
            return
        self.store.show_popup(PopupType.DELETE_BRANCH)

    def _delete_named_branch(self, branch) -> None:
        repo = self.store.selected_repository
        name = branch.name_without_remote if branch.type == BranchType.REMOTE else branch.name
        if repo:
            state = self.store.state_for(repo)
            pr = next((p for p in state.pull_requests if p.head_ref == name), state.current_pull_request if state.status and state.status.current_branch == name else None)
            if pr and branch.type != BranchType.REMOTE:
                self.store.show_popup(PopupType.DELETE_PULL_REQUEST, pull_request=pr, branch=name)
                return
        popup = PopupType.DELETE_REMOTE_BRANCH if branch.type == BranchType.REMOTE else PopupType.DELETE_BRANCH
        self.store.show_popup(popup, branch=name)

    def _show_logs(self) -> None:
        from ..paths import log_dir

        open_external(str(log_dir()))

    def _stash_all(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        wd = state.status.working_directory if state.status else None
        if wd is not None and has_conflicted_files(wd):
            return

        def run() -> None:
            self.store.stash_all_changes(repo)

        if not self.store.settings.confirm_stash_all_changes:
            run()
            return
        dialog = Adw.AlertDialog(
            heading="Stash all changes?",
            body="This will stash all changes on the current branch. You can restore them later from the Changes tab.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("ok", "Stash all changes")
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("ok")

        def done(d, result) -> None:
            try:
                response = d.choose_finish(result)
            except Exception:
                return
            if response == "ok":
                run()

        dialog.choose(self, None, done)

    def _toggle_stash(self) -> None:
        self._repo_op(self.store.toggle_stash)

    def _find(self) -> None:
        if hasattr(self, "_changes_stack") and self._changes_stack.get_visible_child_name() == "stash":
            self._stash_viewer.diff_view.start_search()
            return
        name = self._view_stack.get_visible_child_name() if hasattr(self, "_view_stack") else "changes"
        if name == "history" and hasattr(self, "_hist_diff_view"):
            self._hist_diff_view.start_search()
            return
        if hasattr(self, "_diff_view"):
            self._diff_view.start_search()

    def _compare_to_branch(self) -> None:
        """Desktop `showHistory(false, true)` — History tab with the compare branch list focused."""
        self._show_history(should_focus_history=False, show_branch_list=True)

    def _show_changes(self, *, should_focus_changes: bool = True) -> None:
        """Desktop `showChanges`."""
        if self.store.selected_repository is None:
            return
        self.store.close_current_foldout()
        self.store.set_section(RepositorySectionTab.CHANGES)
        if hasattr(self, "_view_stack"):
            self._view_stack.set_visible_child_name("changes")
        if should_focus_changes:
            self.set_focus_changes_needed()
            self._apply_changes_history_focus()

    def _show_history(self, *, should_focus_history: bool = True, show_branch_list: bool = False) -> None:
        """Desktop `showHistory`."""
        repo = self.store.selected_repository
        if repo is None:
            return
        self.store.close_current_foldout()
        self.store.initialize_compare(repo, HistoryTabMode.HISTORY)
        self.store.update_compare_form(repo, filter_text="", show_branch_list=show_branch_list)
        self.store.set_section(RepositorySectionTab.HISTORY)
        if hasattr(self, "_view_stack"):
            self._view_stack.set_visible_child_name("history")
        if hasattr(self, "_compare_search"):
            if self._compare_search.get_text():
                self._compare_search.set_text("")
            if show_branch_list:
                GLib.idle_add(self._compare_search.grab_focus)
        if should_focus_history:
            self.set_focus_history_needed()
            self._apply_changes_history_focus()

    def _go_to_commit_message(self) -> None:
        """Desktop `goToCommitMessage`."""
        self._show_changes(should_focus_changes=False)
        self.store.set_commit_message_focus(True)
        self._apply_commit_message_focus()

    def set_focus_changes_needed(self) -> None:
        """Desktop `setFocusChangesNeeded`."""
        self._focus_changes_needed = True

    def set_focus_history_needed(self) -> None:
        """Desktop `setFocusHistoryNeeded`."""
        self._focus_history_needed = True

    def _apply_changes_history_focus(self) -> None:
        if getattr(self, "_focus_changes_needed", False):
            self._focus_changes_needed = False
            if (
                self.store.settings.show_changes_filter
                and hasattr(self, "_filter")
                and getattr(self, "_filter_box", None) is not None
                and self._filter_box.get_visible()
            ):
                self._filter.grab_focus()
            elif hasattr(self, "_include_all"):
                self._include_all.grab_focus()
        if getattr(self, "_focus_history_needed", False):
            self._focus_history_needed = False
            if hasattr(self, "_commit_list"):
                self._commit_list.grab_focus()

    def _apply_commit_message_focus(self) -> None:
        """Desktop commit-message `focusSummary` / `onCommitMessageFocusSet`."""
        if not self.store.focus_commit_message or getattr(self, "_applying_commit_focus", False):
            return
        self._applying_commit_focus = True
        try:
            if hasattr(self, "_summary"):
                self._summary.grab_focus()
            self.store.set_commit_message_focus(False)
        finally:
            self._applying_commit_focus = False

    def _is_app_menu_focus(self, widget) -> bool:
        """Desktop `app-menu-bar` contains `document.activeElement`."""
        current = widget
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if current is getattr(self, "_menu_btn", None):
                return True
            current = current.get_parent() if hasattr(current, "get_parent") else None
        return False

    def is_resize_pane_active(self) -> bool:
        """Desktop `isResizePaneActive`."""
        focus = self.get_focus()
        if focus is None:
            return False
        if self._is_app_menu_focus(focus):
            return bool(self.store.resizable_pane_active)
        return find_active_resizable(focus) is not None

    def _on_focus_widget(self, *_args: object) -> None:
        self.store.app_focused_element_changed(self.is_resize_pane_active())
        self._sync_menu_state()

    def _sync_menu_state(self) -> None:
        """Desktop `updateMenuState` / `getMenuState`."""
        popup_open = bool(self.store.popup or self.store.all_popups)
        dialog = self.get_visible_dialog() if hasattr(self, "get_visible_dialog") else None
        if dialog is not None:
            popup_open = True
            if not getattr(dialog, "_menu_state_hooked", False):
                dialog._menu_state_hooked = True
                dialog.connect("closed", lambda *_: self._sync_menu_state())
        apply_menu_state(
            self.lookup_action,
            updateMenuState(self.store, window_open=True, current_popup=popup_open),
        )

    def _sync_resizable_menu(self) -> None:
        """Desktop `getAppMenuBuilder` (`resizablePaneActive`) via `updateMenuState`."""
        self._sync_menu_state()

    def _refresh_empty(self) -> None:
        if not hasattr(self, "_empty_tutorial_btn"):
            return
        signed_in = bool(self.store.accounts)
        paused = self.store.tutorial_step == TutorialStep.PAUSED
        self._empty_tutorial_btn.set_label(
            "Return to in progress tutorial" if paused else "Create a tutorial repository…"
        )
        self._empty_tutorial_btn.set_visible(signed_in)
        if hasattr(self, "_empty_clone_pane"):
            self._empty_clone_pane.set_visible(signed_in)
        self._refresh_empty_clone_list()

    def _on_api_repositories(self) -> None:
        if getattr(self, "_stack", None) is None:
            return
        if self._stack.get_visible_child_name() == "empty":
            self._refresh_empty_clone_list()

    def _empty_selected_account(self):
        accounts = list(self.store.accounts)
        if not accounts:
            return None
        drop = getattr(self, "_empty_account_drop", None)
        if drop is not None and drop.get_visible():
            idx = int(drop.get_selected())
            if 0 <= idx < len(accounts):
                return accounts[idx]
        return accounts[0]

    def _refresh_empty_clone_list(self) -> None:
        listbox = getattr(self, "_empty_clone_list", None)
        if listbox is None or getattr(self, "_empty_clone_refreshing", False):
            return
        self._empty_clone_refreshing = True
        try:
            self._refresh_empty_clone_list_inner(listbox)
        finally:
            self._empty_clone_refreshing = False

    def _refresh_empty_clone_list_inner(self, listbox: Gtk.ListBox) -> None:
        accounts = list(self.store.accounts)
        drop = getattr(self, "_empty_account_drop", None)
        if drop is not None:
            drop.set_visible(len(accounts) > 1)
            labels = [f"{item.login} ({item.friendly_endpoint})" for item in accounts]
            current = int(drop.get_selected()) if drop.get_visible() else 0
            drop.set_model(Gtk.StringList.new(labels or [""]))
            if labels:
                drop.set_selected(min(max(current, 0), len(labels) - 1))
        account = self._empty_selected_account()
        if not account:
            _clear_listbox(listbox)
            if hasattr(self, "_empty_clone_selected"):
                self._empty_clone_selected.set_visible(False)
            return
        state = self.store.api_repositories.get_account_state(account)
        if state is None:
            self.store.refresh_api_repositories(account)
            repos, loading = [], True
        else:
            repos, loading = list(state.repositories), state.loading
        needle = ""
        if hasattr(self, "_empty_clone_filter"):
            needle = self._empty_clone_filter.get_text().strip()
        if loading and not repos:
            _clear_listbox(listbox)
            listbox.append(Adw.ActionRow(title=_clone_list_loading_title(account)))
            return
        _render_grouped_clone_list(
            listbox,
            repos,
            account.login,
            needle,
            empty_title=_clone_list_empty_title(account, needle),
            on_pick=self._on_empty_clone_pick,
        )

    def _on_empty_clone_pick(self, gh) -> None:
        self._empty_selected_repo = gh
        btn = getattr(self, "_empty_clone_selected", None)
        if btn is not None:
            btn.set_label(f"Clone {gh.full_name}")
            btn.set_visible(True)

    def _on_empty_clone_selected(self, *_args: object) -> None:
        gh = getattr(self, "_empty_selected_repo", None)
        if gh is not None and gh.clone_url:
            self.store.show_popup(PopupType.CLONE_REPOSITORY, initial_url=gh.clone_url)

    def _on_empty_tutorial(self, *_args: object) -> None:
        if self.store.tutorial_step == TutorialStep.PAUSED:
            self.store.resume_tutorial()
            return
        self.store.show_popup(PopupType.CREATE_TUTORIAL_REPOSITORY)

    def _open_submodule(self, full_path: str) -> None:
        """Desktop `onOpenSubmodule`: metric then `openOrAddRepository`."""
        self.store.open_submodule_from_diff(full_path)

    def _is_showing_modal(self) -> bool:
        """Desktop `isShowingModal` (`currentPopup !== null`).

        Presented Adw.Dialogs drain `store.popup` via `take_popups()`, so a
        visible dialog also counts as modal — the on-screen equivalent of
        Electron's current popup.
        """
        if self.store.popup or self.store.all_popups:
            return True
        return bool(hasattr(self, "get_visible_dialog") and self.get_visible_dialog())

    def _install_file_drop(self) -> None:
        try:
            target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)

            def on_enter(_t, _x, _y) -> Gdk.DragAction:
                # Desktop `document.ondragover` sets `dropEffect` to `none`
                # while `isShowingModal`; Gtk has no Gdk.DragAction.NONE.
                if self._is_showing_modal():
                    return Gdk.DragAction(0)
                return Gdk.DragAction.COPY

            def on_drop(_t, value, _x, _y) -> bool:
                # Desktop `document.body.ondrop` returns when `isShowingModal`.
                if self._is_showing_modal():
                    return False
                files = value.get_files() if hasattr(value, "get_files") else []
                paths = [f.get_path() for f in files if f.get_path()]
                if paths:
                    self.store.add_dropped_paths(paths)
                    return True
                return False

            target.connect("enter", on_enter)
            target.connect("drop", on_drop)
            self.add_controller(target)
        except Exception:
            pass

    def _on_history_filter(self, entry: Gtk.SearchEntry) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.set_history_filter(repo, entry.get_text())

    def _on_history_edge(self, _scroller, pos) -> None:
        if pos != Gtk.PositionType.BOTTOM:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.load_next_commit_batch(repo)

    def _undo(self) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.undo_last_commit(repo)

    def _show_branches_foldout(self) -> None:
        self.store.show_foldout(FoldoutType.BRANCH)

    def _on_branch_toolbar_context_menu(self, widget: Gtk.Widget) -> None:
        """Desktop branch dropdown `onBranchToolbarButtonContextMenu`."""
        repo = self.store.selected_repository
        if repo is None:
            return
        state = self.store.state_for(repo)
        name = state.status.current_branch if state.status else None
        if not name:
            return
        branch = next((item for item in state.branches if item.name == name), None)
        is_local = branch is None or branch.type == BranchType.LOCAL
        pr = state.current_pull_request

        def rename(_name: str) -> None:
            self.store.show_popup(PopupType.RENAME_BRANCH, branch=name)

        def delete(_name: str) -> None:
            if branch is not None:
                self._delete_named_branch(branch)
            else:
                self.store.show_popup(PopupType.DELETE_BRANCH)

        items = generate_branch_context_menu_items(
            name,
            is_local=is_local,
            on_rename=rename,
            on_delete=delete,
            on_view_pull_request=(lambda: self.store.show_pull_request_by_pr(pr)) if pr else None,
        )
        show_context_menu(widget, items)

    def _sync_foldouts(self) -> None:
        if getattr(self, "_syncing_foldouts", False):
            return
        self._syncing_foldouts = True
        try:
            self._sync_repository_foldout()
            if hasattr(self, "_branches_foldout"):
                want_branch = self.store.foldout == FoldoutType.BRANCH
                if bool(self._branches_foldout.get_visible()) != want_branch:
                    if want_branch:
                        self._branches_foldout.popup_and_focus()
                    else:
                        self._branches_foldout.popdown()
            if hasattr(self, "_push_menu_btn") and self._push_menu_btn.get_visible():
                want_push = self.store.foldout == FoldoutType.PUSH_PULL
                active = bool(self._push_menu_btn.get_active())
                if active != want_push:
                    self._push_menu_btn.set_active(want_push)
        finally:
            self._syncing_foldouts = False

    def _on_branch_foldout_visible(self, popover, *_args: object) -> None:
        if getattr(self, "_syncing_foldouts", False):
            return
        if popover.get_visible():
            if self.store.foldout != FoldoutType.BRANCH:
                self.store.show_foldout(FoldoutType.BRANCH)
        elif self.store.foldout == FoldoutType.BRANCH:
            self.store.close_foldout(FoldoutType.BRANCH)

    def _on_push_menu_active(self, button, *_args: object) -> None:
        if getattr(self, "_syncing_foldouts", False) or getattr(self, "_updating_push_menu", False):
            return
        if button.get_active():
            if self.store.foldout != FoldoutType.PUSH_PULL:
                self.store.show_foldout(FoldoutType.PUSH_PULL)
        elif self.store.foldout == FoldoutType.PUSH_PULL:
            self.store.close_foldout(FoldoutType.PUSH_PULL)

    def _on_branch_button_drag_enter(self, *_args: object) -> None:
        """Desktop branch dropdown `onMouseEnter` during commit drag."""
        self.store.show_foldout(FoldoutType.BRANCH)

    def _on_branch_dropdown_resized(self, width: int) -> None:
        self.store.set_branch_dropdown_width(width)
        self._sync_branch_foldout_width()

    def _sync_branch_foldout_width(self) -> None:
        if hasattr(self, "_branches_foldout"):
            self._branches_foldout.set_foldout_width(int(clamp(self.store.branch_dropdown_constraints)))

    def _reset_branch_dropdown_width(self) -> None:
        self.store.reset_branch_dropdown_width()
        if hasattr(self, "_branch_btn"):
            self._branch_btn.set_size_request(max(160, defaultBranchDropdownWidth), -1)
        self._sync_branch_foldout_width()

    def _reset_push_pull_button_width(self) -> None:
        self.store.reset_push_pull_button_width()
        target = getattr(self, "_push_box", None) or getattr(self, "_push_btn", None)
        if target is not None:
            target.set_size_request(max(160, defaultPushPullButtonWidth), -1)

    def _toggle_repo_sidebar(self) -> None:
        """Desktop `onRepositoryDropdownStateChanged` — toggle FoldoutType.Repository."""
        if self.store.foldout == FoldoutType.REPOSITORY:
            self.store.close_foldout(FoldoutType.REPOSITORY)
        else:
            self.store.show_foldout(FoldoutType.REPOSITORY)

    def _sidebar_foldout_width(self) -> int:
        """Desktop `clamp(sidebarWidth)` with min 220."""
        return max(220, int(clamp(self.store.sidebar_constraints)))

    def _sync_repository_foldout_width(self) -> None:
        """Desktop `foldoutWidth = clamp(this.state.sidebarWidth)` for the repository list."""
        if not hasattr(self, "_split"):
            return
        width = self._sidebar_foldout_width()
        self._split.set_min_sidebar_width(width)
        self._split.set_max_sidebar_width(width)

    def _sync_repository_foldout(self) -> None:
        if not hasattr(self, "_split"):
            return
        want = self.store.foldout == FoldoutType.REPOSITORY
        if bool(self._split.get_show_sidebar()) != want:
            self._split.set_show_sidebar(want)
        self._sync_repository_foldout_width()

    def _on_split_show_sidebar(self, split, *_args: object) -> None:
        showing = bool(split.get_show_sidebar())
        if showing:
            if self.store.foldout != FoldoutType.REPOSITORY:
                self.store.show_foldout(FoldoutType.REPOSITORY)
        elif self.store.foldout == FoldoutType.REPOSITORY:
            self.store.close_foldout(FoldoutType.REPOSITORY)

    def _on_sidebar_paned_position(self, paned, *_args: object) -> None:
        """Desktop `setSidebarWidth` while dragging Changes/History."""
        if getattr(self, "_building", False) or getattr(self, "_applying_sidebar_width", False) or getattr(self, "_applying_constraints", False):
            return
        pos = paned.get_position()
        if pos <= 0:
            return
        visible = ""
        if hasattr(self, "_view_stack"):
            visible = self._view_stack.get_visible_child_name() or ""
        if paned is getattr(self, "_history_paned", None) and visible != "history":
            return
        if paned is getattr(self, "_changes_paned", None) and visible == "history":
            return
        self.store.set_sidebar_width(pos)
        self._sync_repository_foldout_width()

    def _build_welcome(self) -> Gtk.Widget:
        page = Adw.StatusPage()
        page.set_title("Welcome to GitHub Desktop")
        page.set_description(
            "GitHub Desktop is a seamless way to contribute to projects on "
            "GitHub and GitHub Enterprise. Sign in below to get started with "
            "your existing projects."
        )
        page.set_icon_name("folder-remote-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_halign(Gtk.Align.CENTER)
        self._welcome_redirect = Gtk.Label(
            label=(
                "Your browser will redirect you back to GitHub Desktop once you've signed in. "
                "If your browser asks for your permission to launch GitHub Desktop please allow it to."
            ),
            wrap=True,
            xalign=0,
        )
        self._welcome_redirect.set_visible(False)
        self._welcome_redirect.set_max_width_chars(48)
        sign = Gtk.Button(label="Sign in to GitHub.com")
        sign.add_css_class("suggested-action")
        sign.add_css_class("pill")
        sign.connect("clicked", lambda *_: self.store.begin_sign_in(False))
        ent = Gtk.Button(label="Sign in to GitHub Enterprise")
        ent.connect("clicked", lambda *_: self.store.begin_sign_in(True))
        create_row = Gtk.Box(spacing=4)
        create_row.set_halign(Gtk.Align.CENTER)
        create_row.append(Gtk.Label(label="New to GitHub?"))
        create = Gtk.LinkButton(
            uri="https://github.com/join?source=github-desktop",
            label="Create your free account.",
        )
        create_row.append(create)
        skip = Gtk.Button(label="Skip this step")
        skip.add_css_class("flat")
        skip.connect("clicked", lambda *_: self.store.skip_welcome_sign_in())
        terms = Gtk.Label(wrap=True, xalign=0, use_markup=True)
        terms.set_max_width_chars(52)
        terms.set_markup(
            "By creating an account, you agree to the "
            '<a href="https://github.com/site/terms">Terms of Service</a>. '
            "For more information about GitHub's privacy practices, see the "
            '<a href="https://github.com/site/privacy">GitHub Privacy Statement.</a>'
        )
        terms.connect("activate-link", lambda _l, uri: (open_external(uri), True)[1])
        metrics = Gtk.Label(wrap=True, xalign=0, use_markup=True)
        metrics.set_max_width_chars(52)
        metrics.set_markup(
            "GitHub Desktop sends usage metrics to improve the product and inform "
            "feature decisions. "
            '<a href="https://desktop.github.com/usage-data/">Learn more about user metrics.</a>'
        )
        metrics.connect("activate-link", lambda _l, uri: (open_external(uri), True)[1])
        box.append(self._welcome_redirect)
        box.append(sign)
        box.append(ent)
        box.append(create_row)
        box.append(skip)
        box.append(terms)
        box.append(metrics)
        self._welcome_extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._welcome_extra)
        page.set_child(box)
        return page

    def _refresh_welcome(self) -> None:
        child = self._welcome_extra.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._welcome_extra.remove(child)
            child = nxt
        signing = self.store.welcome_step in {WelcomeStep.SIGN_IN_DOTCOM, WelcomeStep.SIGN_IN_ENTERPRISE}
        if hasattr(self, "_welcome_redirect"):
            self._welcome_redirect.set_visible(signing)
        if self.store.welcome_step == WelcomeStep.CONFIGURE_GIT:
            # Desktop `ConfigureGit` / `ConfigureGitUser` with account email choices.
            from ..models import account_email_choices

            self.store.ensure_global_author_identity()
            name, email = self.store.author_identity()
            name_row = Adw.EntryRow(title="Name")
            name_row.set_text(name or "")
            email_choices: list[str] = []
            for account in self.store.accounts:
                for item in account_email_choices(account):
                    if item not in email_choices:
                        email_choices.append(item)
            if email and email not in email_choices:
                email_choices.insert(0, email)
            email_choices.append("Other")
            email_row = Adw.ComboRow(title="Email")
            email_row.set_model(Gtk.StringList.new(email_choices or ["Other"]))
            if email and email in email_choices:
                email_row.set_selected(email_choices.index(email))
            other_email = Adw.EntryRow(title="Other email")
            other_email.set_text(email or "")
            other_email.set_visible(False)

            def sync_other(*_a: object) -> None:
                idx = email_row.get_selected()
                other_email.set_visible(idx >= 0 and idx == len(email_choices) - 1)

            email_row.connect("notify::selected", sync_other)
            sync_other()
            finish = Gtk.Button(label="Finish")
            finish.add_css_class("suggested-action")

            def done(*_a: object) -> None:
                idx = email_row.get_selected()
                if idx < 0 or idx >= len(email_choices) - 1:
                    chosen = other_email.get_text().strip()
                else:
                    model = email_row.get_model()
                    chosen = model.get_string(idx) if model is not None else other_email.get_text().strip()
                def finished(exc: BaseException | None) -> None:
                    if exc:
                        self.store.show_popup(PopupType.ERROR, error=str(exc))
                        return
                    self.store.finish_welcome()

                self.store.save_git_user(name_row.get_text(), chosen, on_done=finished)

            finish.connect("clicked", done)
            self._welcome_extra.append(name_row)
            self._welcome_extra.append(email_row)
            self._welcome_extra.append(other_email)
            self._welcome_extra.append(finish)

    def _build_empty(self) -> Gtk.Widget:
        page = Adw.StatusPage(
            title="Let's get started!",
            description="Add a repository to GitHub Desktop to start collaborating",
        )
        page.set_icon_name("folder-symbolic")
        page.add_css_class("no-repositories")
        outer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        outer.set_halign(Gtk.Align.CENTER)
        outer.set_valign(Gtk.Align.START)

        clone_pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        clone_pane.set_hexpand(True)
        clone_pane.set_size_request(320, 280)
        self._empty_clone_pane = clone_pane
        self._empty_account_drop = Adw.ComboRow(title="Account")
        self._empty_account_drop.set_model(Gtk.StringList.new([""]))
        self._empty_account_drop.set_visible(False)
        self._empty_account_drop.connect("notify::selected", lambda *_: self._refresh_empty_clone_list())
        clone_pane.append(self._empty_account_drop)
        self._empty_clone_filter = Gtk.SearchEntry()
        self._empty_clone_filter.set_placeholder_text("Filter your repositories")
        self._empty_clone_filter.connect("search-changed", lambda *_: self._refresh_empty_clone_list())
        clone_pane.append(self._empty_clone_filter)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_min_content_height(220)
        self._empty_clone_list = Gtk.ListBox()
        self._empty_clone_list.add_css_class("boxed-list")
        scroller.set_child(self._empty_clone_list)
        clone_pane.append(scroller)
        self._empty_clone_selected = Gtk.Button(label="Clone selected")
        self._empty_clone_selected.add_css_class("suggested-action")
        self._empty_clone_selected.set_visible(False)
        self._empty_clone_selected.connect("clicked", self._on_empty_clone_selected)
        clone_pane.append(self._empty_clone_selected)
        self._empty_selected_repo = None
        outer.append(clone_pane)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.START)
        tutorial = Gtk.Button(label="Create a tutorial repository…")
        tutorial.connect("clicked", self._on_empty_tutorial)
        self._empty_tutorial_btn = tutorial
        box.append(tutorial)
        for label, action in [
            (CLONE_REPOSITORY_FROM_INTERNET, "win.clone-repository"),
            (CREATE_NEW_REPOSITORY_ON_LOCAL_DRIVE, "win.new-repository"),
            (ADD_EXISTING_REPOSITORY_FROM_LOCAL_DRIVE, "win.add-local-repository"),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_action_name(action)
            box.append(btn)
        protip = Gtk.Label(
            label="ProTip! You can drag & drop an existing repository folder here to add it to Desktop",
            wrap=True,
            xalign=0,
        )
        protip.add_css_class("protip")
        protip.add_css_class("dim-label")
        protip.set_halign(Gtk.Align.CENTER)
        protip.set_justify(Gtk.Justification.CENTER)
        box.append(protip)
        outer.append(box)
        page.set_child(outer)
        return page

    def _build_repo_page(self) -> Gtk.Widget:
        self._split = Adw.OverlaySplitView()
        self._split.set_sidebar(self._build_repo_list())
        # Desktop repository foldout width is clamp(sidebarWidth), min 220.
        # Pin min=max so the list is not independently resizable.
        self._sync_repository_foldout_width()
        self._split.set_show_sidebar(False)
        self._split.connect("notify::show-sidebar", self._on_split_show_sidebar)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._repo_btn = Gtk.Button()
        repo_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        repo_inner.set_halign(Gtk.Align.START)
        self._repo_title = Gtk.Label(label=repository_toolbar_title(), xalign=0)
        self._repo_desc = Gtk.Label(label=REPOSITORY_TOOLBAR_DESCRIPTION, xalign=0)
        self._repo_desc.add_css_class("dim-label")
        self._repo_desc.add_css_class("caption")
        repo_inner.append(self._repo_title)
        repo_inner.append(self._repo_desc)
        self._repo_btn.set_child(repo_inner)
        self._repo_btn.connect("clicked", lambda *_: self._toggle_repo_sidebar())
        attach_right_click(self._repo_btn, self._on_repository_toolbar_context_menu)
        header.pack_start(self._repo_btn)

        self._branch_btn = Gtk.MenuButton()
        self._branch_btn.set_always_show_arrow(True)
        self._branch_btn.set_size_request(max(160, int(self.store.settings.branch_dropdown_width or 230)), -1)
        branch_inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        branch_inner.set_halign(Gtk.Align.START)
        self._branch_title = Gtk.Label(label="", xalign=0)
        self._branch_desc = Gtk.Label(label=BRANCH_TOOLBAR_DESCRIPTION, xalign=0)
        self._branch_desc.add_css_class("dim-label")
        self._branch_desc.add_css_class("caption")
        branch_inner.append(self._branch_title)
        branch_inner.append(self._branch_desc)
        self._branch_btn.set_child(branch_inner)
        self._branches_foldout = BranchesFoldout(
            on_checkout=lambda b: self._repo_op(lambda r: self.store.checkout(r, b)),
            on_create=lambda: self.store.show_popup(PopupType.CREATE_BRANCH),
            on_create_pr=lambda: self._repo_op(self.store.open_pull_request),
            on_rename=lambda b: self.store.show_popup(PopupType.RENAME_BRANCH, branch=b.name),
            on_delete=lambda b: self._delete_named_branch(b),
            on_merge=lambda b: self._repo_op(lambda r: self.store.merge_branch(r, b.name)),
            on_pr=lambda pr: self._repo_op(lambda r: self.store.checkout_pull_request(r, pr)),
            on_view_github=lambda b: self._repo_op(lambda r: self.store.view_branch_on_github(r, b.name)),
            on_view_pr_github=lambda pr: self.store.show_pull_request_by_pr(pr),
            on_cherry_pick=lambda b, sha: self._repo_op(
                lambda r: self.store.cherry_pick_commits(r, [s for s in str(sha).split(",") if s], target_branch=b.name)
            ),
            on_cherry_pick_pr=lambda pr, sha: self._repo_op(
                lambda r: self.store.cherry_pick_onto_pull_request(r, pr, [s for s in str(sha).split(",") if s])
            ),
            on_cherry_pick_new_branch=lambda sha: self._repo_op(
                lambda r: self.store.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind=MultiCommitOperationKind.CHERRY_PICK,
                    shas=[s for s in str(sha).split(",") if s],
                    create_branch=True,
                )
            ),
            on_tab=lambda tab: self.store.change_branches_tab(tab),
        )
        self._branch_btn.set_popover(self._branches_foldout)
        self._branches_foldout.connect("notify::visible", self._on_branch_foldout_visible)
        attach_right_click(self._branch_btn, self._on_branch_toolbar_context_menu)
        try:
            drag_hover = Gtk.DropControllerMotion()
            drag_hover.connect("enter", self._on_branch_button_drag_enter)
            self._branch_btn.add_controller(drag_hover)
        except Exception:
            pass
        self._sync_branch_foldout_width()
        if enable_resizing_toolbar_buttons():
            header.pack_start(
                wrap_toolbar_resizable(
                    self._branch_btn,
                    self._on_branch_dropdown_resized,
                    self._reset_branch_dropdown_width,
                    width=int(clamp(self.store.branch_dropdown_constraints)),
                    description="Current branch dropdown button",
                    constraints=self._branch_resize_limits,
                )
            )
        else:
            header.pack_start(self._branch_btn)

        self._push_box = Gtk.Box()
        self._push_box.add_css_class("linked")
        self._push_btn = Gtk.Button()
        self._push_btn.add_css_class("push-pull-button")
        push_inner = Gtk.Box(spacing=8)
        push_inner.set_valign(Gtk.Align.CENTER)
        self._push_icon = Gtk.Image.new_from_icon_name("view-refresh-symbolic")
        self._push_icon.add_css_class("push-pull-icon")
        self._push_spinner = Gtk.Spinner()
        self._push_spinner.set_visible(False)
        push_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._push_action_label = Gtk.Label(label="Fetch origin", xalign=0)
        self._push_action_label.add_css_class("push-pull-label")
        self._push_fetched_label = Gtk.Label(label="Never fetched", xalign=0)
        self._push_fetched_label.add_css_class("dim-label")
        self._push_fetched_label.add_css_class("push-last-fetched")
        push_labels.append(self._push_action_label)
        push_labels.append(self._push_fetched_label)
        push_inner.append(self._push_icon)
        push_inner.append(self._push_spinner)
        push_inner.append(push_labels)
        self._ahead_label = Gtk.Label()
        self._ahead_label.add_css_class("ahead-behind")
        self._ahead_label.set_valign(Gtk.Align.CENTER)
        self._ahead_label.set_visible(False)
        push_inner.append(self._ahead_label)
        self._push_btn.set_child(push_inner)
        self._push_btn.connect("clicked", self._on_push_pull)
        self._push_live = Gtk.Label()
        self._push_live.set_name(PUSH_PULL_BUTTON_STATE_ID)
        self._push_live.set_visible(False)
        try:
            self._push_live.update_property(
                [Gtk.AccessibleProperty.LIVE],
                [Gtk.AccessibleLive.POLITE],
            )
        except Exception:
            pass
        push_inner.append(self._push_live)
        self._push_menu_btn = Gtk.MenuButton()
        self._push_menu_btn.set_icon_name("pan-down-symbolic")
        self._push_menu_btn.set_tooltip_text("Fetch and force push")
        self._push_menu_btn.set_visible(False)
        self._push_box.append(self._push_btn)
        self._push_box.append(self._push_menu_btn)
        self._push_menu_btn.connect("notify::active", self._on_push_menu_active)
        if enable_resizing_toolbar_buttons():
            header.pack_end(
                wrap_toolbar_resizable(
                    self._push_box,
                    self.store.set_push_pull_button_width,
                    self._reset_push_pull_button_width,
                    width=int(clamp(self.store.push_pull_constraints)),
                    description="Push pull button",
                    constraints=self._push_resize_limits,
                )
            )
        else:
            header.pack_end(self._push_box)

        self._checks_btn = Gtk.Button(icon_name="emblem-ok-symbolic")
        self._checks_btn.set_tooltip_text("Pull request checks")
        self._checks_btn.connect("clicked", self._on_checks)
        header.pack_end(self._checks_btn)

        pr_btn = Gtk.Button(icon_name="network-transmit-receive-symbolic")
        pr_btn.set_tooltip_text("Create or view pull request")
        pr_btn.set_action_name("win.open-pull-request")
        header.pack_end(pr_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(self._app_menu())
        menu_btn.set_visible(should_render_application_menu())
        self._menu_btn = menu_btn
        header.pack_end(menu_btn)

        switcher = Adw.ViewSwitcher()
        self._view_stack = Adw.ViewStack()
        switcher.set_stack(self._view_stack)
        header.set_title_widget(switcher)
        toolbar.add_top_bar(header)

        self._tutorial_banner = Adw.Banner()
        self._tutorial_banner.set_revealed(False)
        toolbar.add_top_bar(self._tutorial_banner)

        self._changes_page = self._build_changes()
        self._history_page = self._build_history()
        self._view_stack.add_titled_with_icon(self._changes_page, "changes", "Changes", "document-edit-symbolic")
        self._view_stack.add_titled_with_icon(self._history_page, "history", "History", "view-list-symbolic")
        self._view_stack.connect("notify::visible-child-name", self._on_view_changed)
        self._tutorial_panel = TutorialPanel(
            on_open_editor=lambda: self._repo_op(
                lambda r: self.store.open_in_editor(r, os.path.join(r.path, "README.md"))
            ),
            on_open_pr=lambda: self._repo_op(self.store.open_pull_request),
            on_skip_editor=self.store.complete_tutorial_editor_step,
            on_skip_pr=self.store.skip_tutorial_pull_request,
            on_preferences=lambda: show_preferences(self, self.store),
            on_exit=lambda: self.store.show_popup(PopupType.CONFIRM_EXIT_TUTORIAL),
            on_explore=lambda: self._repo_op(self.store.show_github_explore),
            on_create_repository=lambda: self.store.show_popup(PopupType.CREATE_REPOSITORY),
            on_add_repository=lambda: self.store.show_popup(PopupType.ADD_REPOSITORY),
            on_announced=self.store.mark_tutorial_completion_as_announced,
        )
        self._tutorial_panel.set_visible(False)
        self._work_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._view_stack.set_hexpand(True)
        self._work_area.append(self._view_stack)
        self._work_area.append(self._tutorial_panel)
        self._repo_content = Gtk.Stack()
        self._missing_page = self._build_missing()
        self._cloning_page = self._build_cloning()
        self._repo_content.add_named(self._work_area, "content")
        self._repo_content.add_named(self._missing_page, "missing")
        self._repo_content.add_named(self._cloning_page, "cloning")
        toolbar.set_content(self._repo_content)
        self._split.set_content(toolbar)
        return self._split

    def _build_missing(self) -> Gtk.Widget:
        page = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        page.set_title("Can't find this repository")
        self._missing_title = page
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        self._missing_path = Gtk.Label(xalign=0)
        self._missing_path.set_wrap(True)
        self._missing_path.add_css_class("dim-label")
        box.append(self._missing_path)
        locate = Gtk.Button(label="Locate…")
        locate.add_css_class("suggested-action")
        locate.add_css_class("pill")
        locate.connect("clicked", lambda *_: self._locate_repository())
        check = Gtk.Button(label="Check again")
        check.add_css_class("pill")
        check.connect("clicked", lambda *_: self._repo_op(self.store.check_repository_path))
        clone_again = Gtk.Button(label="Clone again")
        clone_again.add_css_class("pill")
        clone_again.connect("clicked", lambda *_: self._repo_op(self.store.clone_again))
        self._missing_clone_btn = clone_again
        trust = Gtk.Button(label="Trust repository")
        trust.add_css_class("pill")
        trust.connect("clicked", lambda *_: self._repo_op(self.store.trust_repository))
        self._missing_trust_btn = trust
        remove = Gtk.Button(label="Remove")
        remove.add_css_class("destructive-action")
        remove.add_css_class("pill")
        remove.connect("clicked", lambda *_: self.store.show_popup(PopupType.REMOVE_REPOSITORY))
        box.append(locate)
        box.append(check)
        box.append(clone_again)
        box.append(trust)
        box.append(remove)
        page.set_child(box)
        return page

    def _build_cloning(self) -> Gtk.Widget:
        """Desktop `CloningRepositoryView`: progress page for an in-flight clone."""
        page = Adw.StatusPage(icon_name="folder-download-symbolic")
        page.set_title("Cloning")
        page.add_css_class("cloning-repository-view")
        self._cloning_title = page
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_halign(Gtk.Align.CENTER)
        box.set_size_request(360, -1)
        self._cloning_bar = Gtk.ProgressBar()
        self._cloning_detail = Gtk.Label(wrap=True, xalign=0.5)
        self._cloning_detail.add_css_class("dim-label")
        box.append(self._cloning_bar)
        box.append(self._cloning_detail)
        page.set_child(box)
        return page

    def _show_cloning(self, cloning) -> None:
        title = f"Cloning {cloning.name}"
        self._cloning_title.set_title(title)
        fraction = float(cloning.progress or 0)
        if fraction > 0:
            self._cloning_bar.set_fraction(min(1.0, fraction))
        else:
            self._cloning_bar.pulse()
        self._cloning_detail.set_text(cloning.description or cloning.url)

    def _locate_repository(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        try:
            dialog = Gtk.FileDialog(title="Locate repository")

            def done(chooser, result) -> None:
                try:
                    folder = chooser.select_folder_finish(result)
                    path = folder.get_path() if folder else None
                    if path:
                        self.store.relocate_repository(repo, path)
                except Exception as exc:
                    self.store.show_popup(PopupType.ERROR, error=str(exc))

            dialog.select_folder(self, None, done)
        except Exception:
            from .dialogs import _text_dialog

            def submit(values: dict[str, str]) -> None:
                path = values.get("path", "").strip()
                if path:
                    try:
                        self.store.relocate_repository(repo, path)
                    except Exception as exc:
                        self.store.show_popup(PopupType.ERROR, error=str(exc))

            _text_dialog(self, "Locate repository", "Choose the folder that contains this repository.", [("path", "Path", repo.path)], submit, "Locate")

    def _open_binary_file(self, rel_path: str) -> None:
        repo = self.store.selected_repository
        if not repo or not rel_path:
            return
        open_in_default_program(os.path.join(repo.path, rel_path))

    def _app_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        file_m = Gio.Menu()
        file_m.append("New repository…", "win.new-repository")
        file_m.append("Add local repository…", "win.add-local-repository")
        file_m.append("Clone repository…", "win.clone-repository")
        file_m.append("Options…", "win.preferences")
        file_m.append("Install command line tool…", "win.install-cli")
        file_m.append(file_quit_label(), "app.quit")
        menu.append_submenu("File", file_m)
        edit = Gio.Menu()
        edit.append("Undo", "win.edit-undo")
        edit.append("Redo", "win.edit-redo")
        edit.append("Cut", "win.cut")
        edit.append("Copy", "win.copy")
        edit.append("Paste", "win.paste")
        edit.append("Select all", "win.select-all")
        edit.append("Find", "win.find")
        menu.append_submenu("Edit", edit)
        view = Gio.Menu()
        view.append("Changes", "win.show-changes")
        view.append("History", "win.show-history")
        view.append("Repository list", "win.choose-repository")
        view.append("Branches list", "win.show-branches")
        view.append(go_to_summary_label(), "win.go-to-commit-message")
        view.append(self._stash_menu_label(), "win.toggle-stash")
        view.append(self._changes_filter_menu_label(), "win.toggle-changes-filter")
        view.append("Toggle full screen", "win.toggle-fullscreen")
        view.append("Expand active resizable", "win.increase-resizable")
        view.append("Contract active resizable", "win.decrease-resizable")
        view.append("Reset zoom", "win.zoom-reset")
        view.append("Zoom in", "win.zoom-in")
        view.append("Zoom out", "win.zoom-out")
        menu.append_submenu("View", view)
        repo = Gio.Menu()
        repo.append(self._push_menu_label(), "win.push")
        repo.append("Pull", "win.pull")
        repo.append("Fetch", "win.fetch")
        repo.append(self._remove_repository_label(), "win.remove-repository")
        repo.append(self._view_on_github_menu_label(), "win.view-on-github")
        repo.append(self._open_in_shell_label(), "win.open-in-shell")
        repo.append(RevealInFileManagerLabel, "win.open-working-directory")
        repo.append(self._open_in_editor_label(), "win.open-external-editor")
        repo.append("Create issue on GitHub", "win.create-issue")
        repo.append("Repository settings…", "win.repository-settings")
        menu.append_submenu("Repository", repo)
        branch = Gio.Menu()
        branch.append("New branch…", "win.create-branch")
        branch.append("Rename…", "win.rename-branch")
        branch.append("Delete…", "win.delete-branch")
        branch.append("Discard all changes…", "win.discard-all")
        branch.append(stash_all_changes_label(self.store.settings.confirm_stash_all_changes), "win.stash-all")
        branch.append(self._update_from_default_label(), "win.update-from-default")
        branch.append("Compare to branch", "win.compare-to-branch")
        branch.append("Merge into current branch…", "win.merge-branch")
        branch.append("Squash and merge into current branch…", "win.squash-merge")
        branch.append("Rebase current branch…", "win.rebase-branch")
        branch.append("Compare on GitHub", "win.compare-on-github")
        branch.append("View branch on GitHub", "win.branch-on-github")
        branch.append("Preview pull request", "win.preview-pull-request")
        branch.append(self._pull_request_menu_label(), "win.open-pull-request")
        menu.append_submenu("Branch", branch)
        help_m = Gio.Menu()
        help_m.append("Report issue…", "win.report-issue")
        help_m.append("Contact GitHub support…", "win.contact-support")
        help_m.append("Show User Guides", "win.show-guides")
        help_m.append("Explore GitHub", "win.github-explore")
        help_m.append("Show keyboard shortcuts", "win.show-shortcuts")
        help_m.append("Show logs in your File Manager", "win.show-logs")
        help_m.append("Release notes", "win.release-notes")
        help_m.append("About GitHub Desktop", "win.about")
        menu.append_submenu("Help", help_m)
        return menu

    def _selected_state(self):
        repo = self.store.selected_repository
        return self.store.state_for(repo) if repo else None

    def _push_menu_label(self) -> str:
        force = self.store.current_branch_force_push_state() == ForcePushBranchState.RECOMMENDED
        confirm = self.store.settings.confirm_force_push or self.store.settings.ask_for_confirmation_on_force_push
        return get_push_label(force_push=force, ask_for_confirmation=confirm)

    def _pull_request_menu_label(self) -> str:
        state = self._selected_state()
        if state and state.current_pull_request:
            return "View pull request on GitHub"
        return "Create pull request"

    def _stash_menu_label(self) -> str:
        state = self._selected_state()
        return get_stashed_changes_label(bool(state and state.stashed_visible))

    def _changes_filter_menu_label(self) -> str:
        return "Hide changes filter" if self.store.settings.show_changes_filter else "Show changes filter"

    def _view_on_github_menu_label(self) -> str:
        repo = self.store.selected_repository
        enterprise = bool(repo and repo.github and not is_dotcom_endpoint(repo.github.endpoint))
        return view_on_github_label(enterprise=enterprise)

    def _update_from_default_label(self) -> str:
        repo = self.store.selected_repository
        if repo:
            target = self.store.contribution_target_default_branch(repo)
            name = target.name_without_remote if target else self.store.default_branch_name(repo)
        else:
            name = None
        return f"Update from {name or self.store.settings.default_branch or 'default branch'}"

    def _open_in_editor_label(self) -> str:
        return open_in_editor_label(self.store.settings.selected_external_editor)

    def _open_in_shell_label(self) -> str:
        return open_in_shell_label(self.store.settings.selected_shell)

    def _remove_repository_label(self) -> str:
        return remove_repository_label(self.store.settings.confirm_repository_removal)

    def _rebuild_app_menu(self) -> None:
        if not hasattr(self, "_menu_btn"):
            return
        state = self._selected_state()
        sig = (
            self._push_menu_label(),
            self._pull_request_menu_label(),
            self._stash_menu_label(),
            stash_all_changes_label(self.store.settings.confirm_stash_all_changes),
            self._changes_filter_menu_label(),
            self._update_from_default_label(),
            self._open_in_editor_label(),
            self._open_in_shell_label(),
            self._remove_repository_label(),
            self._view_on_github_menu_label(),
            bool(state and state.current_pull_request),
        )
        if getattr(self, "_menu_sig", None) == sig:
            return
        self._menu_sig = sig
        self._menu_btn.set_visible(should_render_application_menu())
        self._menu_btn.set_menu_model(self._app_menu())

    def _build_repo_list(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Filter")
        box.append(search)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._repo_list = Gtk.ListBox()
        self._repo_list.add_css_class("navigation-sidebar")
        scroller.set_child(self._repo_list)
        box.append(scroller)
        self._repo_filter = search
        search.connect("search-changed", self._on_repository_filter_text)
        add_btn = Gtk.Button()
        add_btn.add_css_class("new-repository-button")
        add_inner = Gtk.Box(spacing=4)
        add_inner.append(Gtk.Label(label="Add"))
        add_inner.append(Gtk.Image.new_from_icon_name("pan-down-symbolic"))
        add_btn.set_child(add_inner)
        add_btn.connect("clicked", self._on_new_repository_button_click)
        down = Gtk.EventControllerKey()
        down.connect("key-pressed", self._on_new_repository_button_key)
        add_btn.add_controller(down)
        self._new_repo_btn = add_btn
        box.append(add_btn)
        return box

    def _build_changes(self) -> Gtk.Widget:
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(220, -1)
        self._filter = Gtk.SearchEntry()
        self._filter.set_placeholder_text("Filter changed files")
        self._filter.connect("search-changed", self._on_changes_filter_text)
        chips = Gtk.Box(spacing=4)
        chips.add_css_class("filter-bar")
        self._filter_buttons: dict[str, Gtk.ToggleButton] = {}
        filter_group = None
        for value, label in (
            (ChangesListFilter.ALL.value, "All"),
            (ChangesListFilter.INCLUDED.value, "Included"),
            (ChangesListFilter.EXCLUDED.value, "Excluded"),
        ):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("filter-chip")
            if filter_group is None:
                filter_group = btn
            else:
                btn.set_group(filter_group)
            btn.set_active(value == ChangesListFilter.ALL.value)
            self._filter_buttons[value] = btn
            chips.append(btn)
            btn.connect("toggled", lambda b, v=value: b.get_active() and self._set_file_filter(v))
        self._kind_buttons: dict[str, Gtk.ToggleButton] = {}
        for value, label in (("new", "New"), ("modified", "Modified"), ("deleted", "Deleted")):
            btn = Gtk.ToggleButton(label=label)
            btn.add_css_class("filter-chip")
            btn.connect("toggled", lambda b, v=value: self._set_kind_filter(v, b.get_active()))
            self._kind_buttons[value] = btn
            chips.append(btn)
        self._filter_bar = chips
        self._filter_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._filter_box.append(self._filter)
        self._filter_box.append(chips)
        applied_row = Gtk.Box(spacing=8)
        applied_row.set_margin_start(4)
        applied_row.set_margin_end(4)
        self._filter_applied = Gtk.Label(xalign=0)
        self._filter_applied.add_css_class("dim-label")
        self._filter_applied.set_hexpand(True)
        self._filter_clear_bar = Gtk.Button(label="Clear filters")
        self._filter_clear_bar.add_css_class("clear-filters-button")
        self._filter_clear_bar.connect("clicked", lambda *_: self._clear_changes_filter())
        applied_row.append(self._filter_applied)
        applied_row.append(self._filter_clear_bar)
        self._filter_applied_row = applied_row
        self._filter_applied_row.set_visible(False)
        self._filter_box.append(applied_row)
        self._filter_box.set_visible(self.store.settings.show_changes_filter)
        left.append(self._filter_box)
        tools = Gtk.Box(spacing=6)
        self._include_all = Gtk.CheckButton(label="Include all")
        self._include_all.connect("toggled", self._on_include_all)
        tools.append(self._include_all)
        left.append(tools)
        self._changes_pages = Gtk.Stack()
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._file_list = Gtk.ListBox()
        self._file_list.add_css_class("boxed-list")
        self._file_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self._file_list.connect("row-selected", self._on_file_selected)
        attach_right_click(self._file_list, lambda *_: self._file_list_menu())
        scroller.set_child(self._file_list)
        self._suggested = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self._suggested.add_css_class("suggested-actions")
        self._suggested.set_margin_top(12)
        self._suggested.set_margin_start(12)
        self._suggested.set_margin_end(12)
        self._suggested.set_margin_bottom(12)
        suggested_scroll = Gtk.ScrolledWindow(vexpand=True)
        suggested_scroll.set_child(self._suggested)
        self._changes_pages.add_named(scroller, "files")
        self._changes_pages.add_named(suggested_scroll, "suggested")
        left.append(self._changes_pages)
        self._stash_bar = Gtk.Box()
        left.append(self._stash_bar)
        commit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        commit_box.add_css_class("commit-box")
        summary_row = Gtk.Box(spacing=6)
        self._author_btn = Gtk.MenuButton()
        self._author_btn.set_tooltip_text("This commit will be authored as the configured Git user")
        self._author_avatar_host = Gtk.Box()
        self._author_btn.set_child(self._author_avatar_host)
        self._author_popover = Gtk.Popover()
        self._author_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._author_popover_box.set_margin_top(8)
        self._author_popover_box.set_margin_bottom(8)
        self._author_popover_box.set_margin_start(8)
        self._author_popover_box.set_margin_end(8)
        self._author_popover.set_child(self._author_popover_box)
        self._author_btn.set_popover(self._author_popover)
        summary_row.append(self._author_btn)
        self._summary = Gtk.Entry()
        self._summary.set_placeholder_text("Summary (required)")
        self._summary.set_max_length(MaxSummaryLength)
        self._summary.set_hexpand(True)
        summary_row.append(self._summary)
        from ..github.repo_rules import (
            COMMIT_MSG_ERROR_BTN_ID,
            commit_message_rule_failures_header,
        )

        self._rule_failure_hint = Gtk.Button()
        self._rule_failure_hint.set_name(COMMIT_MSG_ERROR_BTN_ID)
        self._rule_failure_hint.add_css_class("commit-message-failure-hint")
        self._rule_failure_hint.add_css_class("flat")
        self._rule_failure_hint.add_css_class("circular")
        self._rule_failure_hint.set_visible(False)
        self._rule_failure_hint.connect("clicked", self._toggle_rule_failure_popover)
        summary_row.append(self._rule_failure_hint)
        self._rule_failure_popover_wanted = False
        self._suppress_rule_popover_closed = False
        self._rule_failure_popover = Gtk.Popover()
        self._rule_failure_popover.set_autohide(True)
        self._rule_failure_popover.connect("closed", self._on_rule_failure_popover_closed)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pop_box.set_margin_top(12)
        pop_box.set_margin_bottom(12)
        pop_box.set_margin_start(12)
        pop_box.set_margin_end(12)
        self._rule_failure_header = Gtk.Label(label=commit_message_rule_failures_header(), xalign=0)
        self._rule_failure_header.add_css_class("title-4")
        self._rule_failure_header.set_name("commit-message-rule-failure-popover-header")
        pop_box.append(self._rule_failure_header)
        self._rule_failure_list_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pop_box.append(self._rule_failure_list_host)
        self._rule_failure_popover.set_child(pop_box)
        self._rule_failure_popover.set_parent(self._summary)
        self._issue_store = install_entry_completion(self._summary)
        self._summary.connect("changed", self._on_summary_changed)
        self._summary_warn = Gtk.Label(xalign=0, wrap=True)
        self._summary_warn.add_css_class("warning")
        self._summary_warn.set_visible(False)
        self._author_warn = Gtk.Label(xalign=0, wrap=True)
        self._author_warn.add_css_class("warning")
        self._author_warn.set_visible(False)
        self._rules_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._rules_warn = Gtk.Label(wrap=True, xalign=0)
        self._rules_warn.add_css_class("repo-rules-warning")
        self._rules_link = Gtk.LinkButton(label="View repository rulesets for this branch")
        self._rules_link.add_css_class("repo-rulesets-for-branch-link")
        self._rules_link.set_visible(False)
        self._rules_box.append(self._rules_warn)
        self._rules_box.append(self._rules_link)
        self._rules_box.set_visible(False)
        self._description = Gtk.TextView()
        self._description.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._description.set_size_request(-1, 70)
        try:
            self._description.get_buffer().set_enable_undo(True)
        except Exception:
            pass
        self._desc_completer = TextViewCompleter(
            self._description,
            lambda: self.store.state_for(self.store.selected_repository) if self.store.selected_repository else None,
            on_hash=lambda: self.store.refresh_issues(),
            exclude_login=self._completion_exclude_login,
        )
        self._desc_complete = self._desc_completer.popover
        self._desc_list = self._desc_completer.listbox
        self._description.get_buffer().connect(
            "changed",
            lambda *_: (
                self._flush_commit_form(),
                self._update_commit_warnings(),
                None if getattr(self, "_applying_commit_form", False) else self._update_description_completion(),
            ),
        )
        co = Gtk.CheckButton(label="Co-authors")
        co.connect("toggled", self._on_coauthors)
        self._coauthor_check = co
        self._author_input = AuthorInput(
            on_changed=self._on_authors_changed,
            get_state=self._coauthor_state,
            exclude_login=self._completion_exclude_login,
            get_endpoint=self._coauthor_endpoint,
            exact_match=bind_store_exact_match(self.store),
        )
        self._author_input.set_visible(False)
        self._coauthor_entry = self._author_input.entry
        self._coauthor_store = self._author_input.store
        self._spell = attach_spellcheck(
            self._summary,
            self._description,
            enabled=self.store.settings.spellcheck_enabled,
        )
        btn_row = Gtk.Box(spacing=6)
        self._commit_btn = Gtk.Button(label="Commit to branch")
        self._commit_btn.add_css_class("suggested-action")
        self._commit_btn.connect("clicked", self._on_commit)
        gen = Gtk.Button(icon_name="emoji-objects-symbolic")
        gen.set_tooltip_text("Generate commit message with Copilot")
        gen.set_action_name("win.generate-commit-message")
        self._generate_btn = gen
        self._generate_new = Gtk.Label(label="New")
        self._generate_new.add_css_class("copilot-new")
        self._generate_new.set_visible(False)
        gen_box = Gtk.Box(spacing=4)
        gen_box.append(gen)
        gen_box.append(self._generate_new)
        gen_box.set_visible(False)
        self._generate_box = gen_box
        self._amend_btn = Gtk.Button(label="Amend")
        self._amend_btn.connect("clicked", self._on_amend)
        self._stop_amend_btn = Gtk.Button(label="Stop amending")
        self._stop_amend_btn.set_visible(False)
        self._stop_amend_btn.connect("clicked", self._on_stop_amend)
        btn_row.append(self._commit_btn)
        btn_row.append(gen_box)
        btn_row.append(self._amend_btn)
        btn_row.append(self._stop_amend_btn)
        self._commit_btn_row = btn_row
        self._undo_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._undo_card.add_css_class("undo-commit")
        self._undo_ago = Gtk.Label(xalign=0)
        self._undo_ago.add_css_class("dim-label")
        self._undo_summary = Gtk.Label(xalign=0, hexpand=True)
        self._undo_summary.set_ellipsize(Pango.EllipsizeMode.END)
        undo_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        undo_info.append(self._undo_ago)
        undo_info.append(self._undo_summary)
        self._undo_btn = Gtk.Button(label="Undo")
        self._undo_btn.set_action_name("win.undo-commit")
        self._undo_card.append(undo_info)
        self._undo_card.append(self._undo_btn)
        self._undo_card.set_visible(False)
        self._commit_form = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._commit_form.append(summary_row)
        self._copilot_hint = Gtk.Label(label="Generated by Copilot", xalign=0)
        self._copilot_hint.add_css_class("dim-label")
        self._copilot_hint.set_visible(False)
        self._commit_form.append(self._summary_warn)
        self._commit_form.append(self._author_warn)
        self._commit_form.append(self._rules_box)
        self._commit_form.append(self._copilot_hint)
        self._commit_form.append(self._description)
        self._commit_form.append(co)
        self._commit_form.append(self._author_input)
        self._commit_form.append(btn_row)
        self._attach_commit_message_context_menus()
        commit_box.append(self._undo_card)
        commit_box.append(self._commit_form)
        self._conflict_bar = Gtk.Box(spacing=6)
        commit_box.append(self._conflict_bar)
        left.append(commit_box)
        paned.set_start_child(left)
        self._changes_paned = paned
        try:
            paned.set_position(max(220, int(clamp(self.store.sidebar_constraints))))
        except Exception:
            pass
        attach_paned_reset(paned, self._reset_sidebar_width)
        attach_paned_keyboard_resize(
            paned,
            description="Repository sidebar",
            get_min=lambda: max(220, resizable_limit(self.store.sidebar_constraints.min, 220)),
            get_max=lambda: resizable_limit(self.store.sidebar_constraints.max, DefaultMaxWidth),
        )
        paned.connect("notify::position", self._on_sidebar_paned_position)
        self._diff_view = DiffViewer(
            interactive=True,
            on_line_toggle=self._on_line_toggle,
            on_line_range_toggle=self._on_line_range_toggle,
            on_hunk_toggle=self._on_hunk_toggle,
            on_discard_selection=self._on_discard_selection,
            on_discard_range=self._on_discard_range,
            on_expand_hunk=self._on_expand_hunk,
            on_expand_whole=self._on_expand_diff,
            on_collapse=self._on_collapse_diff,
            on_image_mode=self._on_image_mode,
            on_open_submodule=self._open_submodule,
            on_open_binary=self._open_binary_file,
            on_hide_whitespace_changed=self._set_hide_whitespace,
            on_side_by_side_changed=lambda enabled: self._set_side_by_side_value(enabled),
        )
        paned.set_end_child(self._diff_view)
        self._changes_stack = Gtk.Stack()
        self._stash_viewer = StashDiffViewer(
            on_restore=lambda: self._repo_op(self.store.restore_stash),
            on_discard=lambda: self._repo_op(lambda r: self.store.discard_stash(r)),
            on_close=lambda: self._repo_op(self.store.toggle_stash),
            on_select_file=lambda f: self._repo_op(lambda r: self.store.select_stashed_file(r, f)),
            on_expand_hunk=self._on_expand_hunk,
            on_expand_whole=self._on_expand_diff,
            on_collapse=self._on_collapse_diff,
            on_open_submodule=self._open_submodule,
            on_image_mode=self._on_image_mode,
            on_open_binary=self._open_binary_file,
            files_width=int(self.store.settings.stashed_files_width or defaultStashedFilesWidth),
            on_reset_width=self._reset_stashed_files_width,
            on_width_changed=lambda width: (
                None
                if getattr(self, "_applying_constraints", False)
                else self.store.set_stashed_files_width(width)
            ),
            get_min_width=lambda: max(100, resizable_limit(self.store.stashed_files_constraints.min, 100)),
            get_max_width=lambda: resizable_limit(self.store.stashed_files_constraints.max, DefaultMaxWidth),
        )
        self._changes_stack.add_named(paned, "working")
        self._changes_stack.add_named(self._stash_viewer, "stash")
        return self._changes_stack

    def _build_history(self) -> Gtk.Widget:
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(220, -1)
        compare_row = Gtk.Box(spacing=6)
        compare_row.append(Gtk.Label(label="Compare to"))
        compare_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        compare_col.set_hexpand(True)
        self._compare_search = Gtk.SearchEntry()
        self._compare_search.set_placeholder_text("Select branch to compare…")
        self._compare_search.set_hexpand(True)
        self._compare_search.connect("search-changed", lambda *_: self._refresh_compare_list())
        compare_col.append(self._compare_search)
        compare_scroll = Gtk.ScrolledWindow()
        compare_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        compare_scroll.set_min_content_height(120)
        compare_scroll.set_max_content_height(200)
        self._compare_list = Gtk.ListBox()
        self._compare_list.add_css_class("boxed-list")
        self._compare_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._compare_list.connect("row-activated", self._on_compare_row)
        compare_scroll.set_child(self._compare_list)
        compare_col.append(compare_scroll)
        compare_row.append(compare_col)
        left.append(compare_row)
        self._history_filter = Gtk.SearchEntry()
        self._history_filter.set_placeholder_text("Search commits…")
        self._history_filter.connect("search-changed", self._on_history_filter)
        left.append(self._history_filter)
        tabs = Gtk.Box(spacing=0)
        tabs.add_css_class("linked")
        self._ahead_tab = Gtk.ToggleButton(label="Ahead")
        self._behind_tab = Gtk.ToggleButton(label="Behind")
        self._behind_tab.set_group(self._ahead_tab)
        self._ahead_tab.set_active(True)
        self._ahead_tab.connect("toggled", lambda b: b.get_active() and self._set_compare_mode(ComparisonMode.AHEAD))
        self._behind_tab.connect("toggled", lambda b: b.get_active() and self._set_compare_mode(ComparisonMode.BEHIND))
        tabs.append(self._ahead_tab)
        tabs.append(self._behind_tab)
        self._compare_tabs = tabs
        self._compare_tabs.set_visible(False)
        left.append(self._compare_tabs)
        self._compare_cta = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self._compare_cta.add_css_class("compare-cta")
        left.append(self._compare_cta)
        self._reorder_hint = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._reorder_hint.add_css_class("reorder-commits-hint")
        reorder_title = Gtk.Label(label="Reorder commits", xalign=0)
        reorder_title.add_css_class("heading")
        self._reorder_hint.append(reorder_title)
        reorder_keys = Gtk.Label(label="Use ↑ ↓ to choose a new location.", xalign=0, wrap=True)
        self._reorder_hint.append(reorder_keys)
        reorder_enter = Gtk.Label(label="Press ⏎ to confirm.", xalign=0)
        self._reorder_hint.append(reorder_enter)
        self._reorder_status = Gtk.Label(xalign=0, wrap=True)
        self._reorder_status.add_css_class("dim-label")
        self._reorder_hint.append(self._reorder_status)
        self._reorder_hint.set_visible(False)
        left.append(self._reorder_hint)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.connect("edge-reached", self._on_history_edge)
        self._commit_list = Gtk.ListBox()
        self._commit_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self._commit_list.connect("row-selected", self._on_commit_selected)
        reorder_keys_ctl = Gtk.EventControllerKey()
        reorder_keys_ctl.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        reorder_keys_ctl.connect("key-pressed", self._on_keyboard_reorder_key)
        self._commit_list.add_controller(reorder_keys_ctl)
        window_reorder = Gtk.EventControllerKey()
        window_reorder.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        window_reorder.connect("key-pressed", self._on_keyboard_reorder_key)
        self.add_controller(window_reorder)
        scroller.set_child(self._commit_list)
        left.append(scroller)
        paned.set_start_child(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._hist_detail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._hist_detail.set_hexpand(True)
        self._hist_detail.set_vexpand(True)
        self._commit_summary = ExpandableCommitSummary()
        self._hist_detail.append(self._commit_summary)
        self._commit_header = self._commit_summary
        files_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        files_paned.set_resize_start_child(False)
        files_paned.add_css_class("commit-details")
        # Desktop Resizable description: "Selected commit file list"
        files_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        files_box.set_size_request(100, -1)
        self._hist_files_header = Gtk.Label(label="No files in commit", xalign=0)
        self._hist_files_header.add_css_class("file-list-header")
        self._hist_files_header.set_halign(Gtk.Align.START)
        files_box.append(self._hist_files_header)
        self._hist_files = Gtk.ListBox()
        self._hist_files.connect("row-activated", self._on_hist_file)
        files_scroll = Gtk.ScrolledWindow()
        files_scroll.set_vexpand(True)
        files_scroll.set_child(self._hist_files)
        self._hist_files_scroll = files_scroll
        files_box.append(files_scroll)
        files_paned.set_start_child(files_box)
        self._hist_diff_view = DiffViewer(
            interactive=False,
            on_expand_hunk=self._on_expand_hunk,
            on_expand_whole=self._on_expand_diff,
            on_collapse=self._on_collapse_diff,
            on_open_submodule=self._open_submodule,
            on_open_binary=self._open_binary_file,
            on_hide_whitespace_changed=self._set_history_hide_whitespace,
            on_side_by_side_changed=lambda enabled: self._set_side_by_side_value(enabled),
        )
        files_paned.set_end_child(self._hist_diff_view)
        try:
            files_paned.set_position(
                max(100, int(clamp(self.store.commit_summary_constraints)))
            )
        except Exception:
            pass
        attach_paned_reset(files_paned, self._reset_commit_summary_width)
        attach_paned_keyboard_resize(
            files_paned,
            description="Selected commit file list",
            get_min=lambda: max(100, resizable_limit(self.store.commit_summary_constraints.min, 100)),
            get_max=lambda: resizable_limit(self.store.commit_summary_constraints.max, DefaultMaxWidth),
        )
        files_paned.connect("notify::position", self._on_commit_summary_paned_position)
        self._hist_files_paned = files_paned
        self._hist_detail.append(files_paned)
        self._hist_blank = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._hist_blank.add_css_class("blankslate")
        self._hist_blank.set_valign(Gtk.Align.CENTER)
        self._hist_blank.set_halign(Gtk.Align.CENTER)
        blank_title = Gtk.Label(
            label="Unable to display diff when multiple non-consecutive selected.",
            wrap=True,
            xalign=0,
        )
        blank_title.add_css_class("heading")
        blank_hint = Gtk.Label(label="You can:", xalign=0)
        blank_list = Gtk.Label(
            label=(
                "• Select a single commit or a range of consecutive commits to view a diff.\n"
                "• Drag the commits to the branch menu to cherry-pick them.\n"
                "• Drag the commits to squash or reorder them.\n"
                "• Right click on multiple commits to see options."
            ),
            wrap=True,
            xalign=0,
        )
        self._hist_blank.append(blank_title)
        self._hist_blank.append(blank_hint)
        self._hist_blank.append(blank_list)
        self._hist_blank.set_visible(False)
        right.append(self._hist_detail)
        right.append(self._hist_blank)
        paned.set_end_child(right)
        self._history_paned = paned
        try:
            paned.set_position(max(220, int(clamp(self.store.sidebar_constraints))))
        except Exception:
            pass
        attach_paned_reset(paned, self._reset_sidebar_width)
        attach_paned_keyboard_resize(
            paned,
            description="Repository sidebar",
            get_min=lambda: max(220, resizable_limit(self.store.sidebar_constraints.min, 220)),
            get_max=lambda: resizable_limit(self.store.sidebar_constraints.max, DefaultMaxWidth),
        )
        paned.connect("notify::position", self._on_sidebar_paned_position)
        return paned

    def _on_view_changed(self, *_args: object) -> None:
        name = self._view_stack.get_visible_child_name()
        if name == "history":
            self.store.set_section(RepositorySectionTab.HISTORY)
        else:
            self.store.set_section(RepositorySectionTab.CHANGES)

    def _set_repo_toolbar_title(self, title: str) -> None:
        """Desktop repository toolbar title (description stays `Current repository`)."""
        if hasattr(self, "_repo_title"):
            self._repo_title.set_text(title)
        else:
            self._repo_btn.set_label(title)

    def _refresh_repo(self) -> None:
        cloning = self.store.selected_cloning
        if cloning is not None:
            self._set_repo_toolbar_title(repository_toolbar_title(cloning_name=cloning.name))
            self.set_title(f"Cloning {cloning.name} — {APP_NAME}")
            if hasattr(self, "_repo_content"):
                self._show_cloning(cloning)
                self._repo_content.set_visible_child_name("cloning")
            self._refresh_repo_list()
            return
        repo = self.store.selected_repository
        if repo is None:
            fallback = self.store.cloning[0] if self.store.cloning else None
            self._set_repo_toolbar_title(
                repository_toolbar_title(
                    cloning_name=fallback.name if fallback else None,
                    has_repositories=bool(self.store.repositories),
                )
            )
            return
        self._set_repo_toolbar_title(repository_toolbar_title(selected_name=repo.display_name))
        self.set_title(f"{repo.display_name} — {APP_NAME}")
        self._apply_commit_form(repo, self.store.state_for(repo))
        if hasattr(self, "_repo_content"):
            if repo.is_missing:
                self._show_missing(repo)
                self._repo_content.set_visible_child_name("missing")
                self._refresh_repo_list()
                return
            self._repo_content.set_visible_child_name("content")
        state = self.store.state_for(repo)
        self._refresh_branch_toolbar(state)
        default_branch = self.store.find_default_branch_for(repo)
        default_name = default_branch.name if default_branch else self.store.default_branch_name(repo)
        current_branch = state.status.current_branch if state.status else None
        self._branches_foldout.refresh(
            state.branches,
            state.pull_requests,
            current=current_branch,
            default_name=default_name,
            recent=list(state.recent_branches or self.store.settings.recent_branches.get(repo.path, [])),
            has_github=bool(repo.github),
            pr_checks=getattr(state, "pr_check_status", None) or {},
            repository_name=repo.display_name,
            is_on_default_branch=bool(
                current_branch and default_name and (current_branch == default_name or current_branch == self.store.default_branch_name(repo))
            ),
            prs_loading=bool(state.loading),
            enterprise=bool(repo.github and not is_dotcom_endpoint(repo.github.endpoint)),
            selected_tab=self.store.selected_branches_tab,
        )
        github_label = view_on_github_label(
            enterprise=bool(repo.github and not is_dotcom_endpoint(repo.github.endpoint))
        )
        if hasattr(self, "_diff_view"):
            self._diff_view.view_github_label = github_label
        if hasattr(self, "_hist_diff_view"):
            self._hist_diff_view.view_github_label = github_label
        if hasattr(self, "_filter_box"):
            self._filter_box.set_visible(self.store.settings.show_changes_filter)
        self._update_push_label(state)
        self._update_checks(state)
        self._update_tutorial_banner(repo, state)
        self._refresh_issue_completion(state)
        self._refresh_compare_list(state)
        self._refresh_repo_list()
        self._refresh_files()
        self._refresh_history()
        self._refresh_conflict_bar(state)
        self._refresh_stash_bar(state)
        self._refresh_stash_viewer(state)
        self._rebuild_app_menu()
        if hasattr(self, "_changes_stack"):
            self._changes_stack.set_visible_child_name(
                "stash" if state.stashed_visible and state.stashes else "working"
            )
        page = self._view_stack.get_page(self._changes_page)
        n = len(state.status.working_directory.files) if state.status else 0
        try:
            page.set_badge_number(n)
        except Exception:
            pass
        if self.store.section == RepositorySectionTab.HISTORY:
            self._view_stack.set_visible_child_name("history")
        else:
            self._view_stack.set_visible_child_name("changes")
        amending = state.commit_to_amend is not None
        if hasattr(self, "_commit_btn"):
            if amending and state.status:
                self._commit_btn.set_label(f"Amend {state.status.current_branch or 'last commit'}")
            elif state.status and state.status.current_branch:
                self._commit_btn.set_label(f"Commit to {state.status.current_branch}")
            else:
                self._commit_btn.set_label("Commit to branch")
        if hasattr(self, "_amend_btn"):
            self._amend_btn.set_visible(not amending)
        if hasattr(self, "_stop_amend_btn"):
            self._stop_amend_btn.set_visible(amending)
        if hasattr(self, "_coauthor_check"):
            self._coauthor_check.set_visible(bool(repo.github))
            if not repo.github:
                self._coauthor_check.set_active(False)
                self._author_input.set_visible(False)
            elif state.show_co_authors or state.co_authors:
                self._coauthor_check.set_active(True)
                self._author_input.set_visible(True)
                if state.co_authors:
                    self._author_input.set_authors(list(state.co_authors))
        if hasattr(self, "_spell"):
            self._spell.set_enabled(self.store.settings.spellcheck_enabled)
        self._refresh_author_avatar(repo)
        self._update_commit_warnings()
        self._apply_commit_busy(state)
        self._refresh_undo_card(repo, state)
        self._update_commit_placeholder(repo, state)
        self._update_rebase_commit_form(state)

    def _show_missing(self, repo) -> None:
        if repo.unsafe:
            self._missing_title.set_title(f"{repo.display_name} is potentially unsafe")
            self._missing_path.set_text(
                f"The Git repository at {repo.path} appears to be owned by another user. "
                "Trust the directory to add a safe.directory exception."
            )
            self._missing_trust_btn.set_visible(True)
            self._missing_clone_btn.set_visible(False)
        else:
            self._missing_title.set_title(f'Can\'t find "{repo.display_name}"')
            self._missing_path.set_text(f"It was last seen at {repo.path}.")
            self._missing_trust_btn.set_visible(False)
            self._missing_clone_btn.set_visible(bool(repo.github and repo.github.clone_url))

    def _update_network_progress(self) -> None:
        if not hasattr(self, "_push_btn"):
            return
        kind = self.store.progress_kind
        if kind == "checkout":
            self._refresh_branch_toolbar()
            return
        if hasattr(self, "_branch_btn") and not kind:
            self._refresh_branch_toolbar()
        if not kind:
            self._push_btn.set_sensitive(True)
            if hasattr(self, "_push_menu_btn"):
                self._push_menu_btn.set_sensitive(True)
            repo = self.store.selected_repository
            if repo:
                self._update_push_label(self.store.state_for(repo))
            cloning = self.store.selected_cloning or (self.store.cloning[0] if self.store.cloning else None)
            if cloning is not None:
                pct = int((cloning.progress or 0) * 100)
                self._set_repo_toolbar_title(
                    repository_toolbar_title(cloning_name=cloning.name, cloning_percent=pct or None)
                )
                if hasattr(self, "_cloning_title") and self.store.selected_cloning is not None:
                    self._show_cloning(cloning)
            return
        title = self.store.progress_title or kind.title()
        description = self.store.progress_description or HANG_ON
        if len(title) > 42:
            title = truncate_with_ellipsis(title, 39)
        label, subtitle, tooltip = network_progress_chrome(
            title=title,
            description=description,
            value=self.store.progress_value,
        )
        self._set_push_chrome(label, subtitle, sensitive=False, spinning=True)
        self._push_btn.set_tooltip_text(tooltip)
        if hasattr(self, "_push_menu_btn"):
            self._push_menu_btn.set_sensitive(False)
            self._push_menu_btn.set_visible(False)
        if kind == "clone":
            cloning = self.store.selected_cloning or (self.store.cloning[0] if self.store.cloning else None)
            if cloning is not None:
                pct = int(self.store.progress_value * 100)
                self._set_repo_toolbar_title(
                    repository_toolbar_title(cloning_name=cloning.name, cloning_percent=pct or None)
                )
                if hasattr(self, "_cloning_title") and self.store.selected_cloning is not None:
                    self._show_cloning(cloning)

    def _remote_name(self, state) -> str | None:
        status = state.status
        if status and status.current_upstream_branch:
            return status.current_upstream_branch.split("/", 1)[0]
        remotes = getattr(state, "remotes", None) or []
        if remotes:
            return remotes[0].name
        return None

    def _set_push_menu(self, items: tuple[str, ...] | list[str], remote: str | None) -> None:
        if not hasattr(self, "_push_menu_btn"):
            return
        name = remote or "origin"
        items_t = tuple(items)
        if getattr(self, "_push_menu_items", None) == items_t and getattr(self, "_push_menu_remote", None) == name:
            self._push_menu_btn.set_visible(bool(items_t))
            return
        self._push_menu_items = items_t
        self._push_menu_remote = name
        menu = Gio.Menu()
        for item in items_t:
            if item == "fetch":
                menu.append(f"Fetch {name}", "win.fetch")
            elif item == "force-push":
                menu.append(f"Force push {name}", "win.force-push")
        self._updating_push_menu = True
        try:
            self._push_menu_btn.set_menu_model(menu)
            self._push_menu_btn.set_visible(bool(items_t))
        finally:
            self._updating_push_menu = False

    def _set_push_chrome(
        self,
        label: str,
        subtitle: str | None,
        *,
        sensitive: bool = True,
        icon: str | None = None,
        spinning: bool = False,
        ahead_behind: str = "",
    ) -> None:
        if hasattr(self, "_push_action_label"):
            self._push_action_label.set_text(label)
        else:
            self._push_btn.set_label(label)
        if hasattr(self, "_push_fetched_label"):
            if subtitle:
                self._push_fetched_label.set_text(subtitle)
                self._push_fetched_label.set_visible(True)
            else:
                self._push_fetched_label.set_visible(False)
        if hasattr(self, "_ahead_label"):
            self._ahead_label.set_text(ahead_behind)
            self._ahead_label.set_visible(bool(ahead_behind) and not spinning)
        if hasattr(self, "_push_live"):
            live = f"{label} {subtitle or ''}".strip()
            self._push_live.set_text(live)
            try:
                self._push_live.update_property(
                    [Gtk.AccessibleProperty.LABEL],
                    [live],
                )
            except Exception:
                pass
        if hasattr(self, "_push_spinner") and hasattr(self, "_push_icon"):
            if spinning:
                self._push_icon.set_visible(False)
                self._push_spinner.set_visible(True)
                self._push_spinner.start()
            else:
                self._push_spinner.stop()
                self._push_spinner.set_visible(False)
                if icon:
                    self._push_icon.set_from_icon_name(icon)
                self._push_icon.set_visible(True)
        self._push_btn.set_sensitive(sensitive)

    def _set_branch_toolbar(self, title: str, description: str, tooltip: str, *, sensitive: bool = True) -> None:
        """Desktop `BranchDropdown` title + Linux `Current branch` subtitle."""
        if hasattr(self, "_branch_title"):
            self._branch_title.set_text(title)
        if hasattr(self, "_branch_desc"):
            self._branch_desc.set_text(description)
            self._branch_desc.set_visible(bool(description))
        if hasattr(self, "_branch_btn"):
            self._branch_btn.set_tooltip_text(tooltip)
            self._branch_btn.set_sensitive(sensitive)

    def _refresh_branch_toolbar(self, state=None) -> None:
        """Desktop `BranchDropdown.render` / `updateCheckoutProgress`."""
        if not hasattr(self, "_branch_btn"):
            return
        repo = self.store.selected_repository
        if state is None and repo is not None:
            state = self.store.state_for(repo)
        status = getattr(state, "status", None) if state is not None else None
        checkout = self.store.progress_kind == "checkout"
        rebasing = None
        if status and getattr(status, "rebase_internal_state", None) and not checkout:
            rebasing = status.rebase_internal_state.target_branch
        title, description, tooltip, sensitive = branch_toolbar_chrome(
            branch_name=status.current_branch if status else None,
            current_tip=status.current_tip if status else None,
            checkout=checkout,
            checkout_title=self.store.progress_title if checkout else "",
            checkout_value=self.store.progress_value if checkout else 0.0,
            checkout_target=self.store.progress_target if checkout else "",
            checkout_description=self.store.progress_description if checkout else "",
            rebasing_target=rebasing,
        )
        self._set_branch_toolbar(title, description, tooltip, sensitive=sensitive)

    def _update_checkout_progress(self) -> None:
        """Desktop `updateCheckoutProgress` on the branch dropdown."""
        self._refresh_branch_toolbar()

    def _update_push_label(self, state) -> None:
        if self.store.progress_kind == "checkout":
            self._refresh_branch_toolbar(state)
            return
        if self.store.progress_kind:
            self._update_network_progress()
            return
        status = state.status
        fetched = format_last_fetched(getattr(state, "last_fetched", None))
        repo = self.store.selected_repository
        if not status:
            self._set_push_chrome("Fetch origin", fetched, sensitive=True, icon="view-refresh-symbolic")
            self._push_btn.set_tooltip_text(fetched)
            if hasattr(self, "_push_menu_btn"):
                self._push_menu_btn.set_tooltip_text(fetched)
            self._set_push_menu((), "origin")
            return
        ab = status.branch_ahead_behind
        tags = getattr(state, "local_tags_to_push", None) or []
        presentation = describe_push_pull(
            remote_name=self._remote_name(state),
            current_branch=status.current_branch,
            current_tip=status.current_tip,
            has_upstream=bool(status.current_upstream_branch),
            ahead=ab.ahead if ab else 0,
            behind=ab.behind if ab else 0,
            tag_count=len(tags),
            force_push=self.store.current_branch_force_push_state(),
            pull_with_rebase=bool(getattr(state, "pull_with_rebase", False)),
            last_fetched=fetched,
            rebase_in_progress=bool(getattr(status, "rebase_internal_state", None)),
            is_github=bool(repo is not None and repo.github),
        )
        self._set_push_chrome(
            presentation.label,
            presentation.description,
            sensitive=presentation.sensitive,
            icon=presentation.icon,
            ahead_behind=presentation.ahead_behind,
        )
        self._push_btn.set_tooltip_text(presentation.description)
        if hasattr(self, "_push_menu_btn"):
            self._push_menu_btn.set_tooltip_text(presentation.description)
        self._set_push_menu(presentation.menu_items, presentation.remote_name)

    def _on_push_pull(self, *_args: object) -> None:
        if self.store.progress_kind:
            return
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        status = state.status
        if not status:
            self.store.fetch_repo(repo)
            return
        ab = status.branch_ahead_behind
        tags = state.local_tags_to_push
        presentation = describe_push_pull(
            remote_name=self._remote_name(state),
            current_branch=status.current_branch,
            current_tip=status.current_tip,
            has_upstream=bool(status.current_upstream_branch),
            ahead=ab.ahead if ab else 0,
            behind=ab.behind if ab else 0,
            tag_count=len(tags or []),
            force_push=self.store.current_branch_force_push_state(repo),
            pull_with_rebase=bool(getattr(state, "pull_with_rebase", False)),
        )
        if presentation.action == "force-push":
            self.store.confirm_or_force_push(repo)
        elif presentation.action == "push":
            self.store.push_repo(repo)
        elif presentation.action == "pull":
            self.store.pull_repo(repo)
        elif presentation.action == "fetch":
            self.store.fetch_repo(repo)

    def _branch_menu(self, state) -> Gio.Menu:
        menu = Gio.Menu()
        new = Gio.Menu()
        new.append("New branch…", "win.create-branch")
        menu.append_section(None, new)
        from gi.repository import Gio, GLib

        locals_m = Gio.Menu()
        remotes_m = Gio.Menu()
        for branch in state.branches:
            item = Gio.MenuItem.new(branch.name, None)
            item.set_action_and_target_value("app.checkout", GLib.Variant.new_string(branch.name))
            if branch.type == BranchType.LOCAL:
                locals_m.append_item(item)
            else:
                remotes_m.append_item(item)
        if locals_m.get_n_items():
            menu.append_section("Branches", locals_m)
        if remotes_m.get_n_items():
            menu.append_section("Remote", remotes_m)
        prs = Gio.Menu()
        for pr in state.pull_requests[:30]:
            item = Gio.MenuItem.new(f"#{pr.number} {pr.title}", None)
            item.set_action_and_target_value("app.open-pr", GLib.Variant.new_string(pr.html_url))
            prs.append_item(item)
        if prs.get_n_items():
            menu.append_section("Pull requests", prs)
        return menu

    def _refresh_repo_list(self) -> None:
        if hasattr(self, "_repo_filter"):
            needle = self._repo_filter.get_text()
            if needle != self.store.repository_filter_text:
                self.store.repository_filter_text = needle
        else:
            needle = self.store.repository_filter_text
        while True:
            row = self._repo_list.get_first_child()
            if row is None:
                break
            self._repo_list.remove(row)
        from ..group_repositories import group_repositories

        groups = group_repositories(self.store.repositories, self.store.settings.recent_repository_ids)
        disambiguation = {
            item.repository.id: item.needs_disambiguation
            for group in groups
            for item in group.items
        }
        shown = 0

        def _repo_keys(repo) -> list[str]:
            return [
                repo.display_name,
                repo.path,
                repo.github.full_name if repo.github else "",
            ]

        def add_group(title: str, repos) -> None:
            nonlocal shown
            if not repos:
                return
            shown += len(repos)
            header = Gtk.ListBoxRow()
            header.set_selectable(False)
            header.set_activatable(False)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("heading")
            header.set_child(label)
            self._repo_list.append(header)
            for repo in repos:
                title_text = repo.display_name
                if disambiguation.get(repo.id) and repo.github:
                    title_text = repo.github.full_name
                row = Adw.ActionRow(title=title_text, subtitle=repo.path)
                if repo.is_missing:
                    row.set_subtitle("Can't find this repository")
                ab = self.store.state_for(repo).ahead_behind
                extras: list[Gtk.Widget] = []
                if ab and self.store.settings.repository_indicators_enabled:
                    extra = []
                    if ab.ahead:
                        extra.append(f"↑{ab.ahead}")
                    if ab.behind:
                        extra.append(f"↓{ab.behind}")
                    if extra:
                        badge = Gtk.Label(label=" ".join(extra))
                        badge.add_css_class("ahead-behind")
                        extras.append(badge)
                changes = self.store.state_for(repo).changed_files_count
                if changes and self.store.settings.repository_indicators_enabled:
                    dot = Gtk.Label(label="●")
                    dot.add_css_class("repo-changes-dot")
                    dot.set_tooltip_text(f"{changes} uncommitted change(s)")
                    extras.append(dot)
                for widget in extras:
                    row.add_suffix(widget)
                if repo.github:
                    row.add_prefix(Gtk.Image.new_from_icon_name("user-bookmarks-symbolic"))
                row.set_activatable(True)
                row.connect("activated", lambda _r, rid=repo.id: self.store.select_repository(rid))
                attach_right_click(row, lambda *_ , r=row, repository=repo: self._repo_list_menu(r, repository))
                self._repo_list.append(row)

        for group in groups:
            repos = [item.repository for item in group.items]
            visible = filter_items(needle, repos, _repo_keys)
            add_group(group.label, visible)
        for cloning in self.store.cloning:
            pct = int((cloning.progress or 0) * 100)
            title = f"Cloning… {pct}%" if pct else "Cloning…"
            subtitle = cloning.description or cloning.url
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            row.set_activatable(True)
            row.connect("activated", lambda _r, cid=cloning.id: self.store.select_cloning(cid))
            cancel = Gtk.Button(label="Cancel clone")
            cancel.set_valign(Gtk.Align.CENTER)
            cancel.connect("clicked", lambda *_a, cid=cloning.id: self.store.abort_clone(cid))
            row.add_suffix(cancel)
            self._repo_list.append(row)
            shown += 1
        if needle and shown == 0:
            self._repo_list.append(self._repo_filter_empty_row())

    def _on_new_repository_button_click(self, widget: Gtk.Widget, *_args: object) -> None:
        """Desktop `onNewRepositoryButtonClick`."""
        show_context_menu(
            widget,
            new_repository_button_menu_items(
                on_clone=lambda: self.store.show_popup(PopupType.CLONE_REPOSITORY),
                on_create=lambda: self.store.show_popup(PopupType.CREATE_REPOSITORY),
                on_add=lambda: self.store.show_popup(PopupType.ADD_REPOSITORY),
            ),
        )

    def _on_new_repository_button_key(
        self, _controller, keyval: int, *_args: object
    ) -> bool:
        """Desktop `onNewRepositoryButtonKeyDown` (ArrowDown opens the menu)."""
        if keyval == Gdk.KEY_Down:
            self._on_new_repository_button_click(self._new_repo_btn)
            return True
        return False

    def _repo_filter_empty_row(self) -> Gtk.Widget:
        """Desktop `RepositoriesList.renderNoItems` filter blank slate."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("no-results-found")
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(12)
        box.set_margin_end(12)
        title = Gtk.Label(label="Sorry, I can't find that repository", wrap=True, xalign=0)
        title.add_css_class("title-4")
        box.append(title)
        protip = Gtk.Label(
            label=(
                "ProTip! Press Ctrl+O to quickly add a local repository, and "
                "Ctrl+Shift+O to clone from anywhere within the app"
            ),
            wrap=True,
            xalign=0,
        )
        protip.add_css_class("protip")
        box.append(protip)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_child(box)
        return row

    def _filtered_changes_empty_row(self, repo, filters) -> Gtk.Widget:
        """Desktop `FilterChangesList` empty filtered slate."""
        from ..filter_changes import get_no_results_message

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("no-changes-filtered")
        box.set_margin_top(16)
        box.set_margin_bottom(16)
        box.set_margin_start(12)
        box.set_margin_end(12)
        title = Gtk.Label(label="No files match your current filters", wrap=True, xalign=0)
        title.add_css_class("title-4")
        box.append(title)
        subtitle = get_no_results_message(filters)
        if subtitle:
            hint = Gtk.Label(label=subtitle, wrap=True, xalign=0)
            hint.add_css_class("dim-label")
            box.append(hint)
        clear_btn = Gtk.Button(label="Clear filters")
        clear_btn.add_css_class("clear-filters-button")
        clear_btn.set_halign(Gtk.Align.START)
        clear_btn.connect("clicked", lambda *_: self.store.clear_changes_filter(repo))
        box.append(clear_btn)
        row = Gtk.ListBoxRow()
        row.set_activatable(False)
        row.set_selectable(False)
        row.set_child(box)
        return row

    def _refresh_files(self) -> None:
        repo = self.store.selected_repository
        if not repo or not hasattr(self, "_file_list"):
            return
        state = self.store.state_for(repo)
        from ..filter_changes import (
            file_list_filter_state_from_view,
            filter_changed_files,
        )

        self._building = True
        if hasattr(self, "_filter") and self._filter.get_text() != (state.filter_text or ""):
            self._filter.set_text(state.filter_text or "")
        if hasattr(self, "_filter_buttons"):
            current = state.file_filter or ChangesListFilter.ALL.value
            for key, btn in self._filter_buttons.items():
                if btn.get_active() != (key == current):
                    btn.set_active(key == current)
        if hasattr(self, "_kind_buttons"):
            kinds = {
                "new": bool(state.filter_new),
                "modified": bool(state.filter_modified),
                "deleted": bool(state.filter_deleted),
            }
            for key, btn in self._kind_buttons.items():
                want = kinds.get(key, False)
                if btn.get_active() != want:
                    btn.set_active(want)
        all_files = list(state.status.working_directory.files) if state.status else []
        filters = file_list_filter_state_from_view(state)
        from ..filter_changes import count_active_filter_options, has_active_filters

        if self.store.settings.show_changes_filter:
            files = filter_changed_files(all_files, filters)
        else:
            files = all_files
        if hasattr(self, "_filter_applied_row"):
            active_count = count_active_filter_options(filters)
            active = has_active_filters(filters)
            if active_count:
                self._filter_applied.set_text(f"Filter Options ({active_count} applied)")
            elif filters.filter_text.strip():
                self._filter_applied.set_text("Filter Options")
            else:
                self._filter_applied.set_text("")
            self._filter_applied_row.set_visible(active)
            self._filter_clear_bar.set_visible(active)
        clear_box(self._file_list)
        if not all_files and hasattr(self, "_changes_pages"):
            self._changes_pages.set_visible_child_name("suggested")
            self._populate_suggested_actions(state)
        else:
            if hasattr(self, "_changes_pages"):
                self._changes_pages.set_visible_child_name("files")
            if not files:
                self._file_list.append(self._filtered_changes_empty_row(repo, filters))
            else:
                for file in files:
                    self._file_list.append(self._file_row(file))
        include_all = True
        if files:
            from ..models import WorkingDirectoryStatus

            include_all = WorkingDirectoryStatus.from_files(files).include_all
        elif all_files:
            include_all = False
        elif state.status:
            include_all = state.status.working_directory.include_all
        busy = bool(state.is_committing or state.is_generating_commit_message)
        self._include_all.set_sensitive(not busy and bool(files))
        self._include_all.set_inconsistent(include_all is None)
        self._include_all.set_active(bool(include_all))
        self._building = False
        self._render_working_diff(state)
        repo = self.store.selected_repository
        if repo:
            self._update_commit_placeholder(repo, state)
        self._update_copilot_button(state)

    def _on_repository_filter_text(self, *_args: object) -> None:
        """Desktop `onRepositoryFilterTextChanged` / `_setRepositoryFilterText`."""
        if hasattr(self, "_repo_filter"):
            self.store.set_repository_filter_text(self._repo_filter.get_text())
        self._refresh_repo_list()

    def _on_changes_filter_text(self, *_args: object) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.state_for(repo).filter_text = self._filter.get_text()
        self._refresh_files()

    def _populate_suggested_actions(self, state) -> None:
        if not hasattr(self, "_suggested"):
            return
        clear_box(self._suggested)
        repo = self.store.selected_repository
        if not repo:
            return
        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header.add_css_class("interstitial-header")
        title = Gtk.Label(label="No local changes", xalign=0)
        title.add_css_class("title-4")
        body = Gtk.Label(
            label=(
                "There are no uncommitted changes in this repository. Here are "
                "some friendly suggestions for what to do next."
            ),
            wrap=True,
            xalign=0,
        )
        body.add_css_class("dim-label")
        header.append(title)
        header.append(body)
        self._suggested.append(header)
        current = state.status.current_branch if state.status else None
        remotes = list(state.remotes or [])
        remote_name = remotes[0].name if remotes else "origin"
        is_github = bool(repo.github)
        ahead_behind = state.ahead_behind
        tags = list(state.local_tags_to_push or [])
        stashes = list(state.stashes or [])
        # Desktop NoChanges: stash card replaces the remote action, not stacks with it.
        if stashes:
            count = len(stashes[0].files) if stashes[0].files is not None else (state.stash_count or 1)
            noun = "change" if count == 1 else "changes"
            self._suggested.append(
                self._suggested_card(
                    "View your stashed changes",
                    f"You have {count} {noun} in progress that you have not yet committed.",
                    "View stash",
                    self._suggested_step("suggestedStepViewStash", lambda: self.store.toggle_stash(repo)),
                    primary=True,
                    discoverability="When a stash exists, access it at the bottom of the Changes tab to the left.",
                )
            )
        elif not remotes:
            self._suggested.append(
                self._suggested_card(
                    "Publish your repository to GitHub",
                    "This repository is currently only available on your local machine. By publishing it on GitHub you can share it, and collaborate with others.",
                    "Publish repository",
                    self._suggested_step(
                        "suggestedStepPublishRepository",
                        lambda: self.store.show_popup(PopupType.PUBLISH_REPOSITORY),
                    ),
                    primary=True,
                    discoverability="Always available in the toolbar for local repositories or Ctrl+P",
                )
            )
        elif ahead_behind is None:
            dest = "to GitHub " if is_github else ""
            pr = "open a pull request, " if is_github else ""
            self._suggested.append(
                self._suggested_card(
                    "Publish your branch",
                    (
                        f"The current branch ({current or 'HEAD'}) hasn't been published "
                        f"to the remote yet. By publishing it {dest}you can share it, "
                        f"{pr}and collaborate with others."
                    ),
                    "Publish branch",
                    self._suggested_step("suggestedStepPublishBranch", lambda: self.store.push_repo(repo)),
                    primary=True,
                    discoverability="Always available in the toolbar or Ctrl+P",
                )
            )
        elif self.store.current_branch_force_push_state(repo) == ForcePushBranchState.RECOMMENDED:
            # Desktop hides the remote suggested action after a rewrite that needs force-push.
            pass
        elif ahead_behind.behind > 0:
            behind = ahead_behind.behind
            commit_word = "a commit" if behind == 1 else "commits"
            verb = "does not" if behind == 1 else "do not"
            where = "GitHub" if is_github else "the remote"
            noun = "commit" if behind == 1 else "commits"
            self._suggested.append(
                self._suggested_card(
                    f"Pull {behind} {noun} from the {remote_name} remote",
                    (
                        f"The current branch ({current or 'HEAD'}) has {commit_word} on "
                        f"{where} that {verb} exist on your machine."
                    ),
                    f"Pull {remote_name}",
                    lambda: self.store.pull_repo(repo),
                    primary=True,
                    discoverability="Always available in the toolbar when there are remote changes or Ctrl+Shift+P",
                )
            )
        elif ahead_behind.ahead > 0 or tags:
            kinds: list[str] = []
            descriptions: list[str] = []
            if ahead_behind.ahead > 0:
                kinds.append("commits")
                descriptions.append(
                    "1 local commit" if ahead_behind.ahead == 1 else f"{ahead_behind.ahead} local commits"
                )
            if tags:
                kinds.append("tags")
                descriptions.append("1 tag" if len(tags) == 1 else f"{len(tags)} tags")
            dest = "GitHub" if is_github else "the remote"
            self._suggested.append(
                self._suggested_card(
                    f"Push {' and '.join(kinds)} to the {remote_name} remote",
                    f"You have {' and '.join(descriptions)} waiting to be pushed to {dest}.",
                    f"Push {remote_name}",
                    lambda: self.store.push_repo(repo),
                    primary=True,
                    discoverability="Always available in the toolbar when there are local commits waiting to be pushed or Ctrl+P",
                )
            )
        elif repo.github and not state.current_pull_request:
            default = self.store.default_branch_name(repo)
            if current and current != default:
                action = self.store.settings.pull_request_suggested_next_action
                if action == PullRequestSuggestedNextAction.PREVIEW_PULL_REQUEST.value:
                    self._suggested.append(
                        self._suggested_pr_card(
                            "Preview the Pull Request from your current branch",
                            f"The current branch ({current}) is already published to GitHub. Preview the changes this pull request will have before proposing your changes.",
                            "Preview Pull Request",
                            lambda: self.store.preview_pull_request(repo),
                        )
                    )
                else:
                    self._suggested.append(
                        self._suggested_pr_card(
                            "Create a Pull Request from your current branch",
                            f"The current branch ({current}) is already published to GitHub. Create a pull request to propose and collaborate on your changes.",
                            "Create Pull Request",
                            self._suggested_step(
                                "suggestedStepCreatePullRequest",
                                lambda: self.store.open_pull_request(repo),
                            ),
                        )
                    )
        if is_external_editor_available(
            use_custom_editor=self.store.settings.use_custom_editor,
            selected_external_editor=self.store.settings.selected_external_editor,
        ):
            self._suggested.append(
                self._suggested_card(
                    OPEN_THE_REPOSITORY_IN_YOUR_EXTERNAL_EDITOR,
                    self._no_changes_editor_description(),
                    self._open_in_editor_label(),
                    self._suggested_step(
                        "suggestedStepOpenInExternalEditor",
                        lambda: self.store.open_in_editor(repo),
                    ),
                    discoverability="Always available from the Repository menu or Ctrl+Shift+A",
                )
            )
        self._suggested.append(
            self._suggested_card(
                "View the files of your repository in your File Manager",
                "",
                RevealInFileManagerLabel,
                self._suggested_step(
                    "suggestedStepOpenWorkingDirectory",
                    lambda: self.store.open_working_directory(repo),
                ),
                discoverability="Always available from the Repository menu or Ctrl+Shift+F",
            )
        )
        if repo.github:
            self._suggested.append(
                self._suggested_card(
                    "Open the repository page on GitHub in your browser",
                    "",
                    view_on_github_label(enterprise=not is_dotcom_endpoint(repo.github.endpoint)),
                    self._suggested_step(
                        "suggestedStepViewOnGitHub",
                        lambda: self.store.view_on_github(repo),
                    ),
                    discoverability="Always available from the Repository menu or Ctrl+Shift+G",
                )
            )

    def _suggested_step(self, metric: str, action):
        """Desktop `dispatcher.incrementMetric` then the NoChanges suggested action."""
        def run() -> None:
            self.store.stats.increment(metric)
            action()

        return run

    def _no_changes_editor_description(self) -> Gtk.Widget:
        """Desktop Linux `renderOpenInExternalEditor` / `openIntegrationPreferences` Options link."""
        row = Gtk.Box(spacing=0)
        prefix = Gtk.Label(label="Select your editor in ", xalign=0)
        prefix.add_css_class("dim-label")
        link = Gtk.Button(label="Options")
        link.add_css_class("flat")
        link.add_css_class("link")
        link.set_tooltip_text(SELECT_YOUR_EDITOR_IN_OPTIONS)
        link.connect(
            "clicked",
            lambda *_: show_preferences(self, self.store, PreferencesTab.INTEGRATIONS),
        )
        row.append(prefix)
        row.append(link)
        return row

    def _suggested_card(
        self,
        title: str,
        description: str | Gtk.Widget,
        button: str,
        callback,
        *,
        primary: bool = False,
        discoverability: str | None = None,
    ) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("suggested-action-card")
        heading = Gtk.Label(label=title, xalign=0, wrap=True)
        heading.add_css_class("heading")
        box.append(heading)
        if description:
            if isinstance(description, Gtk.Widget):
                box.append(description)
            else:
                body = Gtk.Label(label=description, xalign=0, wrap=True)
                body.add_css_class("dim-label")
                box.append(body)
        btn = Gtk.Button(label=button, halign=Gtk.Align.START)
        if primary:
            btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: callback())
        box.append(btn)
        if discoverability:
            hint = Gtk.Label(label=discoverability, xalign=0, wrap=True)
            hint.add_css_class("dim-label")
            hint.add_css_class("suggested-action-discoverability")
            box.append(hint)
        return box

    def _suggested_pr_card(self, title: str, description: str, button: str, callback) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("suggested-action-card")
        heading = Gtk.Label(label=title, xalign=0, wrap=True)
        heading.add_css_class("heading")
        body = Gtk.Label(label=description, xalign=0, wrap=True)
        body.add_css_class("dim-label")
        row = Gtk.Box(spacing=0)
        row.add_css_class("linked")
        btn = Gtk.Button(label=button, hexpand=True)
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: callback())
        menu = Gio.Menu()
        menu.append("Preview pull request", "win.pr-suggested-preview")
        menu.append("Create pull request", "win.pr-suggested-create")
        drop = Gtk.MenuButton(icon_name="pan-down-symbolic")
        drop.set_menu_model(menu)
        drop.set_tooltip_text("Choose Preview or Create pull request")
        row.append(btn)
        row.append(drop)
        box.append(heading)
        box.append(body)
        box.append(row)
        return box

    def _file_row(self, file: WorkingDirectoryFileChange) -> Gtk.Widget:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=8)
        check = Gtk.CheckButton()
        kind = file.selection.get_selection_type()
        uncommittable = is_uncommittable_submodule(file)
        partial_sub = is_partially_committable_submodule(file)
        include = False if uncommittable else (kind != DiffSelectionType.NONE)
        check.set_active(include)
        check.set_inconsistent((kind == DiffSelectionType.PARTIAL) or (partial_sub and include))
        repo = self.store.selected_repository
        state = self.store.state_for(repo) if repo else None
        busy = bool(state and (state.is_committing or state.is_generating_commit_message))
        check.set_sensitive(not busy and not uncommittable)
        tooltip = submodule_include_tooltip(file)
        if tooltip:
            check.set_tooltip_text(tooltip)
            row.set_tooltip_text(tooltip)
        check.connect("toggled", lambda btn, p=file.path: self._toggle_file(p, btn.get_active()))
        label = Gtk.Label(label=path_label(file.path, file.status), xalign=0, hexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        badge = Gtk.Label(label=map_status(file.status))
        badge.add_css_class(STATUS_CLASS.get(file.status.kind, ""))
        box.append(check)
        box.append(label)
        box.append(badge)
        if file.status.is_conflicted:
            our = state.status.current_branch if state and state.status else None
            their = _their_branch(repo, state.status) if repo and state and state.status else None
            ours = Gtk.Button(label=get_label_for_manual_resolution_option(file.status.us, our))
            theirs = Gtk.Button(label=get_label_for_manual_resolution_option(file.status.them, their))
            ours.connect("clicked", lambda *_ , p=file.path: self._resolve(p, ManualConflictResolution.OURS))
            theirs.connect("clicked", lambda *_ , p=file.path: self._resolve(p, ManualConflictResolution.THEIRS))
            box.append(ours)
            box.append(theirs)
        row.set_child(box)
        row._file = file  # type: ignore[attr-defined]
        attach_right_click(row, lambda *_ , r=row: self._file_item_menu(r))
        return row

    def _toggle_file(self, path: str, included: bool) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if not repo:
            return
        self._light_update = True
        try:
            self.store.set_file_included(repo, path, included)
        finally:
            self._light_update = False

    def _on_include_all(self, btn: Gtk.CheckButton) -> None:
        """Desktop `onIncludeAllChanged`: toggle only the currently filtered files."""
        if self._building:
            return
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        from ..filter_changes import file_list_filter_state_from_view, filter_changed_files

        all_files = list(state.status.working_directory.files) if state.status else []
        filters = file_list_filter_state_from_view(state)
        files = filter_changed_files(all_files, filters) if self.store.settings.show_changes_filter else all_files
        if files and files != all_files:
            self.store.set_files_included(repo, [f.path for f in files], btn.get_active())
        else:
            self.store.set_include_all(repo, btn.get_active())

    def _on_hide_ws(self, btn: Gtk.CheckButton) -> None:
        if self._building:
            return
        self._set_hide_whitespace(btn.get_active())

    def _set_hide_whitespace(self, hidden: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        self.store.set_hide_whitespace_in_changes_diff(repo, hidden)

    def _set_history_hide_whitespace(self, hidden: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        path = getattr(self._hist_diff_view, "_path", "") or None
        self.store.set_hide_whitespace_in_history_diff(repo, hidden, path)

    def _set_side_by_side_value(self, enabled: bool) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.set_side_by_side(repo, enabled)

    def _on_side_by_side(self, btn: Gtk.CheckButton) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.set_side_by_side(repo, btn.get_active())

    def _on_file_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        repo = self.store.selected_repository
        if not repo or row is None:
            return
        file = getattr(row, "_file", None)
        if file:
            self.store.select_file(repo, file)

    def _on_coauthors(self, btn: Gtk.CheckButton) -> None:
        self._author_input.set_visible(btn.get_active())
        repo = self.store.selected_repository
        if repo:
            self.store.state_for(repo).show_co_authors = btn.get_active()

    def _toggle_coauthors_from_menu(self) -> None:
        """Desktop `onToggleCoAuthors` from `getAddRemoveCoAuthorsMenuItem`."""
        if not hasattr(self, "_coauthor_check"):
            return
        self._coauthor_check.set_active(not self._coauthor_check.get_active())

    def _commit_message_shared_menu_items(self) -> list:
        """Desktop `getAddRemoveCoAuthorsMenuItem` + optional `getGenerateCommitMessageMenuItem`."""
        repo = self.store.selected_repository
        state = self.store.state_for(repo) if repo else None
        showing = bool(hasattr(self, "_coauthor_check") and self._coauthor_check.get_active())
        files_selected = False
        if state and state.status:
            files_selected = any(item.include for item in state.status.working_directory.files)
        specs = commit_message_shared_menu_specs(
            showing_co_authors=showing,
            github_repository=bool(repo and repo.github),
            is_committing=bool(state and state.is_committing),
            accounts_can_generate=any(
                enable_commit_message_generation(account) for account in self.store.accounts
            ),
            is_generating=bool(state and state.is_generating_commit_message),
            commit_to_amend=bool(state and state.commit_to_amend),
            files_selected=files_selected,
        )
        items = []
        for label, enabled in specs:
            if label in {"Add co-authors", "Remove co-authors"}:
                callback = self._toggle_coauthors_from_menu
            else:
                callback = self._generate_commit_message
            items.append((label, callback, enabled))
        return items

    def _on_commit_form_context(self, _gesture, n_press: int, x: float, y: float) -> None:
        """Desktop commit-message `onContextMenu` (skip HTMLInputElement / HTMLTextAreaElement)."""
        if n_press != 1 or not hasattr(self, "_commit_form"):
            return
        target = None
        try:
            target = self._commit_form.pick(x, y, Gtk.PickFlags.DEFAULT)
        except Exception:
            target = None
        if self._commit_context_target_is_input(target):
            return
        show_context_menu(self._commit_form, self._commit_message_shared_menu_items())

    def _commit_context_target_is_input(self, target) -> bool:
        """Desktop: ignore chrome menu when `event.target` is HTMLInputElement or HTMLTextAreaElement."""
        if target is None:
            return False
        inputs = []
        if hasattr(self, "_summary"):
            inputs.append(self._summary)
        if hasattr(self, "_description"):
            inputs.append(self._description)
        if hasattr(self, "_author_input"):
            inputs.append(self._author_input)
        return any(widget_is_or_inside(target, widget) for widget in inputs)

    def _on_commit_input_context(self, widget: Gtk.Widget) -> None:
        """Desktop `onAutocompletingInputContextMenu` (shared items + `{ role: 'editMenu' }` + spellcheck)."""
        items = list(self._commit_message_shared_menu_items())
        items.append(None)
        items.extend(
            [
                ("Undo", lambda: self._edit_action("undo", widget), True),
                ("Redo", lambda: self._edit_action("redo", widget), True),
                ("Cut", lambda: self._edit_action("cut", widget), True),
                ("Copy", lambda: self._edit_action("copy", widget), True),
                ("Paste", lambda: self._edit_action("paste", widget), True),
                ("Select All", lambda: self._edit_action("select-all", widget), True),
            ]
        )
        items.append(None)
        enabled = bool(self.store.settings.spellcheck_enabled)
        items.append(
            (
                commit_spellcheck_menu_label(enabled=enabled),
                lambda: self.store.set_commit_spellcheck_enabled(not enabled),  # onCommitSpellcheckEnabledChanged
                True,
            )
        )
        show_context_menu(widget, items)

    def _attach_commit_message_context_menus(self) -> None:
        for field in (getattr(self, "_summary", None), getattr(self, "_description", None)):
            if field is None:
                continue
            gesture = Gtk.GestureClick()
            gesture.set_button(3)
            try:
                gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
            except Exception:
                pass

            def pressed(
                g: Gtk.GestureClick,
                n_press: int,
                _x: float,
                _y: float,
                widget: Gtk.Widget = field,
            ) -> None:
                if n_press != 1:
                    return
                self._on_commit_input_context(widget)
                try:
                    g.set_state(Gtk.EventSequenceState.CLAIMED)
                except Exception:
                    pass

            gesture.connect("pressed", pressed)
            field.add_controller(gesture)
        chrome = Gtk.GestureClick()
        chrome.set_button(3)
        chrome.connect("pressed", self._on_commit_form_context)
        self._commit_form.add_controller(chrome)

    def _on_authors_changed(self, authors) -> None:
        repo = self.store.selected_repository
        if not repo or getattr(self, "_applying_commit_form", False):
            return
        self.store.state_for(repo).co_authors = list(authors)

    def _on_commit(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        summary = self._summary.get_text().strip()
        start, end = self._description.get_buffer().get_bounds()
        description = self._description.get_buffer().get_text(start, end, True).strip()
        from .emoji import expand_shortcodes

        if not summary:
            placeholder = getattr(self, "_commit_placeholder", "") or self._summary.get_placeholder_text()
            if placeholder and placeholder != "Summary (required)":
                summary = placeholder
        summary = expand_shortcodes(summary)
        description = expand_shortcodes(description)
        if not summary:
            self._toast.add_toast(Adw.Toast(title="A commit summary is required"))
            return
        authors = []
        if self._coauthor_check.get_active():
            from ..models import parse_co_authors

            self._author_input.commit_pending()
            authors = self._author_input.get_authors()
            pending = parse_co_authors(self._author_input.get_pending_text())
            authors = authors + [a for a in pending if a not in authors]
        try:
            self.store.commit(repo, summary, description, co_authors=authors)
        except Exception as exc:
            self.store.show_popup(PopupType.ERROR, error=str(exc))

    def _refresh_history(self) -> None:
        repo = self.store.selected_repository
        if not repo or not hasattr(self, "_commit_list"):
            return
        state = self.store.state_for(repo)
        commits = state.compare_ahead if state.history_mode == HistoryTabMode.COMPARE else state.commits
        if state.history_mode == HistoryTabMode.COMPARE:
            if hasattr(self, "_compare_tabs"):
                self._compare_tabs.set_visible(True)
                self._building = True
                self._ahead_tab.set_label(f"Ahead ({len(state.compare_ahead)})")
                self._behind_tab.set_label(f"Behind ({len(state.compare_behind)})")
                if state.compare_mode == ComparisonMode.BEHIND:
                    self._behind_tab.set_active(True)
                    commits = state.compare_behind
                else:
                    self._ahead_tab.set_active(True)
                    commits = state.compare_ahead
                self._building = False
        elif hasattr(self, "_compare_tabs"):
            self._compare_tabs.set_visible(False)
        if state.history_mode == HistoryTabMode.COMPARE and not commits:
            commits = state.commits
        new_shas = [c.sha for c in commits]
        shown = getattr(self, "_history_shas", [])
        if shown and shown == new_shas[: len(shown)] and len(new_shas) > len(shown):
            for commit in commits[len(shown) :]:
                self._commit_list.append(self._commit_row(commit))
            self._history_shas = new_shas
            self._refresh_compare_cta(state)
            self._refresh_history_detail(state)
            self._sync_keyboard_reorder_chrome()
            return
        self._building = True
        clear_box(self._commit_list)
        for commit in commits:
            self._commit_list.append(self._commit_row(commit))
        self._history_shas = new_shas
        self._refresh_compare_cta(state)
        self._building = False
        self._refresh_history_detail(state)
        self._sync_keyboard_reorder_chrome()

    def _commit_row(self, commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("history-commit")
        box = Gtk.Box(spacing=8)
        repo = self.store.selected_repository
        github = repo.github if repo else None
        box.append(AvatarStack(users_from_commit(commit, github), size=28))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.set_hexpand(True)
        from .emoji import expand_shortcodes

        has_empty_summary = not (commit.summary or "").strip()
        summary_text = "Empty commit message" if has_empty_summary else expand_shortcodes(commit.summary)
        summary = Gtk.Label(label=summary_text, xalign=0)
        summary.add_css_class("commit-summary")
        summary.set_ellipsize(Pango.EllipsizeMode.END)
        summary.set_hexpand(True)
        if has_empty_summary:
            summary.add_css_class("empty-summary")
        attribution = format_commit_attribution(commit, github)
        relative = format_commit_relative_time(commit.author.date)
        byline = Gtk.Label(label=f"{attribution} • {relative}", xalign=0)
        byline.add_css_class("commit-sha")
        from ..format_date import format_date

        absolute = format_date(commit.author.date)
        byline.set_tooltip_text(absolute)
        summary.set_tooltip_text(commit.sha)
        texts.append(summary)
        texts.append(byline)
        box.append(texts)
        indicators = Gtk.Box(spacing=4)
        indicators.add_css_class("commit-indicators")
        if commit.tags:
            tag_box = Gtk.Box(spacing=4)
            tag_box.add_css_class("tag-indicator")
            first = Gtk.Label(label=commit.tags[0])
            first.add_css_class("tag-name")
            tag_box.append(first)
            if len(commit.tags) > 1:
                more = Gtk.Label(label="")
                more.add_css_class("tag-indicator-more")
                more.set_tooltip_text(", ".join(commit.tags[1:]))
                tag_box.append(more)
            indicators.append(tag_box)
        state = self.store.state_for(repo) if repo else None
        local_shas = set(getattr(state, "local_commit_shas", None) or [])
        tags_to_push = set(getattr(state, "local_tags_to_push", None) or [])
        unpushed_tags = [tag for tag in commit.tags if tag in tags_to_push]
        is_local = commit.sha in local_shas
        if is_local or unpushed_tags:
            arrow = Gtk.Image.new_from_icon_name("go-up-symbolic")
            arrow.add_css_class("unpushed-indicator")
            if is_local:
                arrow.set_tooltip_text("This commit has not been pushed to the remote repository")
            else:
                count = len(unpushed_tags)
                noun = "tag" if count == 1 else "tags"
                arrow.set_tooltip_text(f"This commit has {count} {noun} to push")
            indicators.append(arrow)
        if indicators.get_first_child() is not None:
            box.append(indicators)
        row.set_child(box)
        row._commit = commit  # type: ignore[attr-defined]
        row.set_tooltip_text(absolute)
        attach_right_click(row, lambda *_ , r=row: self._commit_item_menu(r))
        self._install_commit_dnd(row, commit)
        return row

    def _on_commit_selected(self, _l, row) -> None:
        if self._building or self._keyboard_reorder:
            return
        repo = self.store.selected_repository
        if not repo or row is None:
            return
        selected = []
        child = self._commit_list.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.ListBoxRow) and child.is_selected():
                c = getattr(child, "_commit", None)
                if c:
                    selected.append(c)
            child = child.get_next_sibling()
        commit = getattr(row, "_commit", None)
        if selected:
            self.store.select_commits(repo, selected)
        elif commit:
            self.store.select_commit(repo, commit)
        self._refresh_history_detail(self.store.state_for(repo))

    def _refresh_history_detail(self, state) -> None:
        if not hasattr(self, "_hist_files"):
            return
        non_contig = bool(getattr(state, "non_contiguous_selection", False))
        if hasattr(self, "_hist_blank"):
            self._hist_blank.set_visible(non_contig)
        if hasattr(self, "_hist_detail"):
            self._hist_detail.set_visible(not non_contig)
        if non_contig:
            if hasattr(self, "_hist_diff_view"):
                self._hist_diff_view.render(None)
            return
        repo = self.store.selected_repository
        commit = state.selected_commit
        if hasattr(self, "_commit_summary"):
            self._commit_summary.bind(
                list(state.selected_commits) or ([commit] if commit else []),
                state.changeset,
                expanded=state.commit_summary_expanded,
                shas_in_diff=list(state.shas_in_diff),
                on_unreachable=lambda: self.store.show_popup(PopupType.UNREACHABLE_COMMITS),
                on_highlight=self._highlight_history_shas,
                github=repo.github if repo else None,
            )
        clear_box(self._hist_files)
        files = list(state.selected_commit_files)
        if hasattr(self, "_hist_files_header"):
            count = len(files)
            if count == 0:
                self._hist_files_header.set_text("No files in commit")
            else:
                noun = "file" if count == 1 else "files"
                self._hist_files_header.set_text(f"{count} changed {noun}")
        for f in files:
            r = Adw.ActionRow(title=path_label(f.path, f.status), subtitle=map_status(f.status))
            r._file = f  # type: ignore[attr-defined]
            r.set_activatable(True)
            attach_right_click(r, lambda *_ , file=f, row=r: self._hist_file_menu(file, row))
            self._hist_files.append(r)
        self._render_history_diff(state)

    def _highlight_history_shas(self, shas: list[str]) -> None:
        if not hasattr(self, "_commit_list"):
            return
        wanted = set(shas)
        child = self._commit_list.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.ListBoxRow):
                commit = getattr(child, "_commit", None)
                if commit and commit.sha in wanted:
                    child.add_css_class("commit-highlight")
                else:
                    child.remove_css_class("commit-highlight")
            child = child.get_next_sibling()

    def _on_hist_file(self, _l, row) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        f = getattr(row, "_file", None)
        state = self.store.state_for(repo)
        if f and state.selected_commit:
            self.store.load_history_diff(repo, f.path, state.selected_commit.sha, f.status)
            self._render_history_diff(self.store.state_for(repo))

    def _on_compare(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Merge")

    def _refresh_conflict_bar(self, state) -> None:
        child = self._conflict_bar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._conflict_bar.remove(child)
            child = nxt
        repo = self.store.selected_repository
        status = state.status
        if not repo or not status:
            return
        unresolved = get_conflicted_files(status.working_directory)
        can_continue = not unresolved
        continue_tooltip = (
            "Continue rebase"
            if can_continue
            else "Resolve all conflicts before continuing"
        )
        has_untracked = bool(get_untracked_files(status.working_directory))
        squash_merge = bool(status.squash_msg_found) and not status.merge_head_found and not status.rebase_internal_state
        if status.merge_head_found or squash_merge:
            kind = MultiCommitOperationKind.SQUASH if squash_merge else MultiCommitOperationKind.MERGE
            self._conflict_bar.append(Gtk.Label(label="Merge in progress"))
            view = Gtk.Button(label="View conflicts")
            view.connect("clicked", lambda *_: show_conflicts_dialog(self, self.store, kind))
            cont = Gtk.Button(label="Commit merge")
            abort = Gtk.Button(label="Abort merge")
            cont.set_sensitive(can_continue)
            cont.set_tooltip_text(
                "Commit merge" if can_continue else "Resolve all conflicts before continuing"
            )
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, kind))
            abort.connect(
                "clicked",
                lambda *_: show_confirm_abort(
                    self,
                    "Merge",
                    lambda: self.store.abort_conflict_operation(repo, kind),
                ),
            )
            self._conflict_bar.append(view)
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)
            if has_untracked:
                warn = Gtk.Label(label="Untracked files will be excluded")
                warn.add_css_class("warning-untracked-files")
                self._conflict_bar.append(warn)
        elif status.rebase_internal_state:
            self._conflict_bar.append(Gtk.Label(label="Rebase in progress"))
            view = Gtk.Button(label="View conflicts")
            view.connect("clicked", lambda *_: show_conflicts_dialog(self, self.store, MultiCommitOperationKind.REBASE))
            cont = Gtk.Button(label="Rebasing" if state.is_committing else "Continue rebase")
            abort = Gtk.Button(label="Abort rebase")
            cont.set_sensitive(can_continue and not state.is_committing)
            cont.set_tooltip_text(continue_tooltip)
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.REBASE))
            abort.connect(
                "clicked",
                lambda *_: show_confirm_abort(
                    self,
                    "Rebase",
                    lambda: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.REBASE),
                ),
            )
            self._conflict_bar.append(view)
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)
            if has_untracked:
                warn = Gtk.Label(label="Untracked files will be excluded")
                warn.add_css_class("warning-untracked-files")
                self._conflict_bar.append(warn)
        elif status.is_cherry_picking_head_found:
            self._conflict_bar.append(Gtk.Label(label="Cherry-pick in progress"))
            view = Gtk.Button(label="View conflicts")
            view.connect("clicked", lambda *_: show_conflicts_dialog(self, self.store, MultiCommitOperationKind.CHERRY_PICK))
            cont = Gtk.Button(label="Continue")
            abort = Gtk.Button(label="Abort")
            cont.set_sensitive(can_continue)
            cont.set_tooltip_text(
                "Continue" if can_continue else "Resolve all conflicts before continuing"
            )
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.CHERRY_PICK))
            abort.connect(
                "clicked",
                lambda *_: show_confirm_abort(
                    self,
                    "Cherry-pick",
                    lambda: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.CHERRY_PICK),
                ),
            )
            self._conflict_bar.append(view)
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)
            if has_untracked:
                warn = Gtk.Label(label="Untracked files will be excluded")
                warn.add_css_class("warning-untracked-files")
                self._conflict_bar.append(warn)
        self._update_rebase_commit_form(state)

    def _update_rebase_commit_form(self, state) -> None:
        rebasing = bool(state.status and state.status.rebase_internal_state) if state and state.status else False
        if hasattr(self, "_commit_form"):
            self._commit_form.set_visible(not rebasing)

    def _update_commit_placeholder(self, repo, state) -> None:
        if not hasattr(self, "_summary"):
            return
        files = list(state.status.working_directory.files) if state and state.status else []
        placeholder = commit_summary_placeholder(files, tutorial=bool(repo and repo.tutorial))
        self._commit_placeholder = placeholder
        self._summary.set_placeholder_text(placeholder)

    def _refresh_undo_card(self, repo, state) -> None:
        if not hasattr(self, "_undo_card"):
            return
        rebasing = bool(state.status and state.status.rebase_internal_state)
        amending = state.commit_to_amend is not None
        local = set(state.local_commit_shas or [])
        commit = next((item for item in state.commits if item.sha in local), None)
        tagged = bool(commit and commit.tags)
        show = bool(commit) and not rebasing and not amending and not tagged
        self._undo_card.set_visible(show)
        if not show or commit is None:
            return
        self._undo_ago.set_text(f"Committed {format_commit_relative_time(commit.author.date)}")
        self._undo_summary.set_text(commit.summary or "Empty commit message")
        busy = bool(
            state.is_committing
            or self.store.progress_kind in {"push", "pull", "fetch", "checkout", "generic"}
        )
        self._undo_btn.set_sensitive(not busy)
        self._undo_btn.set_tooltip_text(
            "Undo is disabled while the repository is being updated" if busy else ""
        )

    def _refresh_stash_bar(self, state) -> None:
        child = self._stash_bar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._stash_bar.remove(child)
            child = nxt
        repo = self.store.selected_repository
        if not repo or not state.stashes:
            return
        btn = Gtk.Button()
        btn.add_css_class("stashed-changes-button")
        if state.stashed_visible:
            btn.add_css_class("selected")
        btn.set_hexpand(True)
        label = Gtk.Label(label="Stashed Changes", xalign=0)
        btn.set_child(label)
        btn.set_tooltip_text("View stashed changes")
        btn.connect("clicked", lambda *_: self.store.toggle_stash(repo))
        self._stash_bar.append(btn)

    def _refresh_stash_viewer(self, state) -> None:
        if not hasattr(self, "_stash_viewer"):
            return
        repo = self.store.selected_repository
        stash = state.stashes[0] if state.stashes else None
        self._stash_viewer.refresh(
            stash,
            list(state.stashed_files),
            state.selected_stashed_file,
            state.current_diff if state.stashed_visible else None,
            side_by_side=state.side_by_side or self.store.settings.show_side_by_side_diff,
            image_mode=state.image_diff_type or self.store.settings.image_diff_type,
            hide_whitespace=self.store._hide_ws_changes(state),
            can_collapse=state.original_diff is not None,
            tab_size=self.store.settings.tab_size,
            loading=state.stash_load_state == StashedChangesLoadStates.LOADING,
        )

    def _render_working_diff(self, state) -> None:
        if not hasattr(self, "_diff_view"):
            return
        file = state.selected_file
        self._diff_view.render(
            state.current_diff,
            path=file.path if file else "",
            selection=file.selection if file else None,
            side_by_side=state.side_by_side or self.store.settings.show_side_by_side_diff,
            image_mode=state.image_diff_type or self.store.settings.image_diff_type,
            show_checks=self.store.settings.show_diff_check_marks,
            hide_whitespace=self.store._hide_ws_changes(state),
            can_collapse=state.original_diff is not None,
            tab_size=self.store.settings.tab_size,
            comments=list(state.diff_comments),
            ask_discard_confirm=self.store.settings.confirm_discard_changes,
        )

    def _render_history_diff(self, state) -> None:
        if not hasattr(self, "_hist_diff_view"):
            return
        path = state.selected_commit_files[0].path if state.selected_commit_files else ""
        self._hist_diff_view.render(
            state.current_diff,
            path=path,
            side_by_side=state.side_by_side or self.store.settings.show_side_by_side_diff,
            image_mode=state.image_diff_type or self.store.settings.image_diff_type,
            show_checks=False,
            hide_whitespace=self.store._hide_ws_history(),
            can_collapse=state.original_diff is not None,
            tab_size=self.store.settings.tab_size,
            comments=list(state.diff_comments),
        )

    def _on_line_toggle(self, path: str, index: int, included: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        self._light_update = True
        try:
            self.store.set_line_included(repo, path, index, included)
        finally:
            self._light_update = False

    def _on_line_range_toggle(self, path: str, from_index: int, to_index: int, included: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        self.store.set_lines_included(repo, path, from_index, to_index, included)

    def _on_hunk_toggle(self, path: str, start: int, length: int, included: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        self._light_update = True
        try:
            self.store.set_hunk_included(repo, path, start, length, included)
        finally:
            self._light_update = False

    def _on_discard_selection(self, path: str) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        if self.store.settings.confirm_discard_changes:
            self.store.show_popup(
                PopupType.CONFIRM_DISCARD_SELECTION,
                path=path,
                on_discard=lambda: self.store.discard_selection(repo, path),
            )
        else:
            self.store.discard_selection(repo, path)

    def _on_discard_range(self, path: str, start: int, end: int) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        if self.store.settings.confirm_discard_changes:
            self.store.show_popup(
                PopupType.CONFIRM_DISCARD_SELECTION,
                path=path,
                on_discard=lambda: self.store.discard_line_range(repo, path, start, end),
            )
        else:
            self.store.discard_line_range(repo, path, start, end)

    def _on_expand_diff(self) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.expand_whole_diff(repo)

    def _on_expand_hunk(self, hunk_index: int, kind: str) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.expand_hunk(repo, hunk_index, kind)

    def _on_collapse_diff(self) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.collapse_expanded_diff(repo)

    def _set_kind_filter(self, kind: str, enabled: bool) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.set_filter_kind(repo, kind, enabled)

    def _on_image_mode(self, mode: str) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.set_image_diff_type(repo, mode)

    def _set_file_filter(self, value: str) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if not repo:
            return
        self.store.set_file_filter(repo, value)

    def _clear_changes_filter(self) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.clear_changes_filter(repo)

    def _selected_change_files(self) -> list[WorkingDirectoryFileChange]:
        files = []
        child = self._file_list.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.ListBoxRow) and child.is_selected():
                f = getattr(child, "_file", None)
                if f:
                    files.append(f)
            child = child.get_next_sibling()
        return files

    def _file_list_menu(self) -> None:
        """Desktop Changes list `onContextMenu` (blank area)."""
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        rebasing = bool(state.status and state.status.rebase_internal_state)
        if changes_list_context_menu_blocked(committing=state.is_committing, rebasing=rebasing):
            return
        has = bool(state.status and state.status.working_directory.files)
        has_conflicts = bool(state.status and has_conflicted_files(state.status.working_directory))
        branch = state.status.current_branch if state.status else None
        has_stash = self.store.desktop_stash_for_branch(repo, branch) is not None
        show_context_menu(
            self._file_list,
            [
                ("Discard all changes…", lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, discarding_all=True), has),
                (stash_all_changes_label(has_stash), self._stash_all, has and branch is not None and not has_conflicts),
            ],
        )

    def _file_item_menu(self, row: Gtk.ListBoxRow) -> None:
        """Desktop `onItemContextMenu` → `getDefaultContextMenu` / `getRebaseContextMenu`."""
        repo = self.store.selected_repository
        file = getattr(row, "_file", None)
        if not repo or file is None:
            return
        state = self.store.state_for(repo)
        rebasing = bool(state.status and state.status.rebase_internal_state)
        if state.is_committing:
            return
        if rebasing:
            self._rebase_file_item_menu(row, repo, file)
            return
        selected = self._selected_change_files() or [file]
        paths = [f.path for f in selected]
        confirm = self.store.settings.confirm_discard_changes
        discard_label = discard_changes_item_label(paths, confirm=confirm)
        items = [
            (discard_label, lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, files=selected), True),
            None,
        ]
        if len(paths) == 1:
            ignore_enabled = os.path.basename(file.path) != GitIgnoreFileName
            items.append(("Ignore file (add to .gitignore)", lambda: self.store.ignore_path(repo, file.path), ignore_enabled))
            folders = ignore_folder_labels(file.path)
            if folders:
                items.append(
                    (
                        "Ignore folder (add to .gitignore)",
                        [
                            (label, lambda folder=label: self.store.ignore_path(repo, folder), True)
                            for label in folders
                        ],
                        ignore_enabled,
                    )
                )
        else:
            ignorable = [p for p in paths if os.path.basename(p) != GitIgnoreFileName]
            items.append(
                (
                    f"Ignore {len(paths)} selected files (add to .gitignore)",
                    lambda: self.store.ignore_path(repo, ignorable),
                    bool(ignorable),
                )
            )
        for ext in ignore_extension_globs(paths):
            items.append(
                (
                    f"Ignore all {ext} files",
                    lambda pattern=f"*{ext}": self.store.ignore_pattern(repo, pattern),
                    True,
                )
            )
        if len(paths) > 1:
            items.extend(
                [
                    None,
                    ("Include selected files", lambda: self.store.set_files_included(repo, paths, True), True),
                    ("Exclude selected files", lambda: self.store.set_files_included(repo, paths, False), True),
                    None,
                    (CopySelectedPathsLabel, lambda: copy_text("\n".join(os.path.join(repo.path, p) for p in paths)), True),
                    (CopySelectedRelativePathsLabel, lambda: copy_text("\n".join(paths)), True),
                ]
            )
        else:
            items.extend(
                [
                    None,
                    (CopyFilePathLabel, lambda: copy_text(os.path.join(repo.path, file.path)), True),
                    (CopyRelativeFilePathLabel, lambda: copy_text(file.path), True),
                ]
            )
        exists = file.status.kind != AppFileStatusKind.DELETED
        items.extend(
            [
                None,
                (RevealInFileManagerLabel, lambda: self.store.reveal_in_file_manager(repo, file.path), exists),
                (self._open_in_editor_label(), lambda: self.store.open_in_editor(repo, os.path.join(repo.path, file.path)), exists),
                (
                    OpenWithDefaultProgramLabel,
                    lambda: self.store.open_file_default(repo, file.path),
                    exists and is_safe_file_extension(os.path.splitext(file.path)[1]),
                ),
            ]
        )
        if file.status.is_conflicted:
            items.extend(
                [
                    None,
                    ("Use ours", lambda: self._resolve(file.path, ManualConflictResolution.OURS), True),
                    ("Use theirs", lambda: self._resolve(file.path, ManualConflictResolution.THEIRS), True),
                ]
            )
        show_context_menu(row, items)

    def _rebase_file_item_menu(self, row: Gtk.ListBoxRow, repo, file) -> None:
        """Desktop `getRebaseContextMenu`."""
        confirm = self.store.settings.confirm_discard_changes
        exists = file.status.kind != AppFileStatusKind.DELETED
        items: list = []
        if file.status.kind is AppFileStatusKind.UNTRACKED:
            items.append(
                (
                    discard_changes_item_label([file.path], confirm=confirm),
                    lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, files=[file]),
                    True,
                )
            )
            items.append(None)
        items.extend(
            [
                (CopyFilePathLabel, lambda: copy_text(os.path.join(repo.path, file.path)), True),
                (CopyRelativeFilePathLabel, lambda: copy_text(file.path), True),
                None,
                (RevealInFileManagerLabel, lambda: self.store.reveal_in_file_manager(repo, file.path), exists),
                (self._open_in_editor_label(), lambda: self.store.open_in_editor(repo, os.path.join(repo.path, file.path)), exists),
                (
                    OpenWithDefaultProgramLabel,
                    lambda: self.store.open_file_default(repo, file.path),
                    exists and is_safe_file_extension(os.path.splitext(file.path)[1]),
                ),
            ]
        )
        show_context_menu(row, items)

    def _hist_file_menu(self, file, anchor: Gtk.Widget | None = None) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        full = os.path.join(repo.path, file.path)
        exists = os.path.exists(full)
        state = self.store.state_for(repo)
        selected = list(state.selected_commits) or ([state.selected_commit] if state.selected_commit else [])
        sha = selected[0].sha if selected else None
        local = set(state.local_commit_shas or [])
        enterprise = bool(repo.github and not is_dotcom_endpoint(repo.github.endpoint))
        view_enabled = bool(repo.github and len(selected) == 1 and sha and sha not in local)

        def view_on_github() -> None:
            if sha:
                self.store.view_commit_on_github(repo, sha, file.path)

        items = committed_file_context_items(
            full_path=full,
            relative_path=file.path,
            exists=exists,
            editor_label=self._open_in_editor_label(),
            on_reveal=lambda: self.store.reveal_in_file_manager(repo, file.path),
            on_open_editor=lambda: self.store.open_in_editor(repo, full),
            on_open_default=lambda: self.store.open_file_default(repo, file.path),
            view_github_label=view_on_github_label(enterprise=enterprise),
            on_view_github=view_on_github,
            view_github_enabled=view_enabled,
        )
        show_context_menu(anchor or self._hist_files, items)

    def _commit_item_menu(self, row: Gtk.ListBoxRow) -> None:
        if self._keyboard_reorder:
            return
        repo = self.store.selected_repository
        commit = getattr(row, "_commit", None)
        if not repo or commit is None:
            return
        state = self.store.state_for(repo)
        selected = list(state.selected_commits) or [commit]
        is_tip = bool(state.commits and state.commits[0].sha == commit.sha)
        local = commit.sha in set(state.local_commit_shas)
        rewrite = self._can_rewrite_history()
        items = []
        if len(selected) > 1:
            items.extend(
                [
                    (f"Cherry-pick {len(selected)} commits…", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Cherry-pick", shas=[c.sha for c in selected]), True),
                    (f"Squash {len(selected)} commits…", lambda: self._squash_selected(selected, commit), rewrite),
                    (f"Reorder {len(selected)} commits…", lambda: self._start_keyboard_reorder(selected), self._can_keyboard_reorder()),
                ]
            )
        else:
            if is_tip:
                items.append(("Amend commit…", self._on_amend, rewrite))
                items.append(("Undo commit…", self._undo, local and rewrite))
            tags = list(commit.tags or [])
            items.extend(
                [
                    ("Reset to commit…", lambda: self.store.reset_to_commit(repo, commit), (not is_tip) and local and rewrite),
                    ("Checkout commit", lambda: self.store.checkout_commit_sha(repo, commit.sha), not is_tip),
                    ("Reorder commit", lambda: self._start_keyboard_reorder([commit]), self._can_keyboard_reorder()),
                    ("Revert changes in commit", lambda: self.store.revert_commit(repo, commit), True),
                    None,
                    ("Create branch from commit", lambda: self.store.show_popup(PopupType.CREATE_BRANCH, start=commit.sha), True),
                    ("Create tag…", lambda: self.store.show_popup(PopupType.CREATE_TAG, sha=commit.sha), True),
                ]
            )
            delete_item = delete_tags_menu_item(
                tags,
                unpushed_tags_for_commit(tags, list(getattr(state, "local_tags_to_push", None) or [])),
                lambda name: self.store.show_popup(PopupType.DELETE_TAG, tag=name),
            )
            if delete_item is not None:
                items.append(None)
                items.append(delete_item)
            items.extend(
                [
                    ("Cherry-pick commit…", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Cherry-pick", shas=[commit.sha]), True),
                    None,
                    ("Copy SHA", lambda: copy_text(commit.sha), True),
                    (copy_tags_menu_label(tags), lambda: copy_text(" ".join(tags)), bool(tags)),
                    (view_on_github_label(enterprise=bool(repo.github and not is_dotcom_endpoint(repo.github.endpoint))), lambda: self.store.view_commit_on_github(repo, commit.sha), bool(repo.github) and not local),
                ]
            )
        show_context_menu(row, items)

    def _visible_history_commits(self) -> list:
        commits = []
        if not hasattr(self, "_commit_list"):
            return commits
        child = self._commit_list.get_first_child()
        while child is not None:
            if isinstance(child, Gtk.ListBoxRow):
                commit = getattr(child, "_commit", None)
                if commit is not None:
                    commits.append(commit)
            child = child.get_next_sibling()
        return commits

    def _can_keyboard_reorder(self) -> bool:
        return self._can_rewrite_history()

    def _can_rewrite_history(self) -> bool:
        repo = self.store.selected_repository
        if not repo:
            return False
        state = self.store.state_for(repo)
        if state.history_mode == HistoryTabMode.COMPARE:
            return False
        return True

    def _start_keyboard_reorder(self, commits: list) -> None:
        if not commits or not self._can_keyboard_reorder():
            return
        if not hasattr(self, "_commit_list"):
            show_reorder_commits(self, self.store, commits)
            return
        visible = self._visible_history_commits()
        shas = [c.sha for c in visible]
        first = next((shas.index(c.sha) for c in commits if c.sha in shas), 0)
        self._keyboard_reorder = {"commits": list(commits), "insert_index": first}
        if hasattr(self, "_commit_list"):
            self._commit_list.grab_focus()
        self._sync_keyboard_reorder_chrome()

    def _cancel_keyboard_reorder(self) -> None:
        if self._keyboard_reorder is None:
            return
        self._keyboard_reorder = None
        self._sync_keyboard_reorder_chrome()

    def _confirm_keyboard_reorder(self) -> None:
        data = self._keyboard_reorder
        repo = self.store.selected_repository
        if not data or not repo:
            self._cancel_keyboard_reorder()
            return
        visible = self._visible_history_commits()
        row = int(data["insert_index"])
        moving = list(data["commits"])
        moving_shas = {c.sha for c in moving}
        indexes = [i for i, c in enumerate(visible) if c.sha in moving_shas]
        base_index = None if row == 0 else row - 1
        if indexes and all(indexes[i] + 1 == indexes[i + 1] for i in range(len(indexes) - 1)):
            first = indexes[0]
            dropped_above = (base_index is None and first == 0) or base_index == first - 1
            dropped_within = base_index is not None and base_index in indexes
            if dropped_above or dropped_within:
                self._cancel_keyboard_reorder()
                return
        before = None if base_index is None or base_index >= len(visible) else visible[base_index]
        self._keyboard_reorder = None
        self._sync_keyboard_reorder_chrome()
        self.store.reorder_onto(repo, moving, before)

    def _on_keyboard_reorder_key(self, _c, keyval, _code, _mod) -> bool:
        if not self._keyboard_reorder:
            return False
        if keyval in (65307,):  # Escape
            self._cancel_keyboard_reorder()
            return True
        if keyval in (65293, 65421):  # Return / KP_Enter
            self._confirm_keyboard_reorder()
            return True
        if keyval in (65362, 65364):  # Up / Down
            visible = self._visible_history_commits()
            maximum = len(visible)
            current = int(self._keyboard_reorder["insert_index"])
            current = current - 1 if keyval == 65362 else current + 1
            self._keyboard_reorder["insert_index"] = max(0, min(maximum, current))
            self._sync_keyboard_reorder_chrome()
            return True
        return False

    def _sync_keyboard_reorder_chrome(self) -> None:
        data = self._keyboard_reorder
        if not hasattr(self, "_reorder_hint"):
            return
        active = data is not None
        self._reorder_hint.set_visible(active)
        visible = self._visible_history_commits()
        moving_shas = {c.sha for c in data["commits"]} if data else set()
        insert_index = int(data["insert_index"]) if data else 0
        if active and data is not None:
            count = len(data["commits"])
            self._reorder_status.set_text(
                keyboard_reorder_insert_message(count, insert_index, len(visible))
                if visible
                else keyboard_reorder_intro_message(count)
            )
        child = self._commit_list.get_first_child() if hasattr(self, "_commit_list") else None
        index = 0
        while child is not None:
            if isinstance(child, Gtk.ListBoxRow):
                commit = getattr(child, "_commit", None)
                child.remove_css_class("commit-reorder-insert")
                child.remove_css_class("commit-reorder-after")
                child.remove_css_class("commit-reorder-moving")
                if active and commit is not None and commit.sha in moving_shas:
                    child.add_css_class("commit-reorder-moving")
                if active and insert_index == index:
                    child.add_css_class("commit-reorder-insert")
                if active and insert_index == len(visible) and index == len(visible) - 1:
                    child.add_css_class("commit-reorder-after")
                index += 1
            child = child.get_next_sibling()

    def _squash_selected(self, selected, onto) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        others = [c for c in selected if c.sha != onto.sha]
        if not others:
            return
        from ..models import get_squashed_commit_description, get_unique_coauthors_as_authors

        all_commits = [*others, onto]
        co_authors = get_unique_coauthors_as_authors(all_commits)
        description = get_squashed_commit_description(others, onto)
        count = len(all_commits)
        title = f"Squash {count} Commits"

        def submit(summary: str, body: str, authors=()) -> None:
            self.store.squash_onto(
                repo,
                others,
                onto,
                summary=summary,
                description=body,
                co_authors=authors,
            )

        self.store.show_popup(
            PopupType.COMMIT_MESSAGE,
            title=title,
            summary=onto.summary,
            description=description,
            button=title,
            show_co_authors=bool(co_authors),
            co_authors=list(co_authors),
            on_submit=submit,
        )

    def _install_commit_dnd(self, row: Gtk.ListBoxRow, commit) -> None:
        try:
            from ..commit_dnd import commit_drop_kind, decode_commit_shas, encode_commit_shas

            drag = Gtk.DragSource()
            drag.set_actions(Gdk.DragAction.MOVE)

            def prepare(_src, _x, _y, sha=commit.sha):
                repo = self.store.selected_repository
                shas = [sha]
                if repo:
                    state = self.store.state_for(repo)
                    selected = [c.sha for c in (state.selected_commits or [])]
                    if sha in selected:
                        shas = selected
                return Gdk.ContentProvider.new_for_value(encode_commit_shas(shas))

            drag.connect("prepare", prepare)
            row.add_controller(drag)
            drop = Gtk.DropTarget.new(str, Gdk.DragAction.MOVE)

            def on_drop(_t, value, _x, y, target=commit, widget=row):
                from ..commit_dnd import clear_drop_kind_css, commit_drop_kind, decode_commit_shas

                clear_drop_kind_css(widget)
                repo = self.store.selected_repository
                if not repo or not value:
                    return False
                state = self.store.state_for(repo)
                shas = decode_commit_shas(value)
                moving = [c for c in state.commits if c.sha in shas]
                if not moving:
                    return False
                kind = commit_drop_kind(float(y or 0), float(widget.get_allocated_height() or 1))
                if kind == "squash":
                    if not self._can_rewrite_history():
                        return False
                    others = [c for c in moving if c.sha != target.sha]
                    if not others:
                        return False
                    self._squash_selected([*others, target], target)
                    return True
                if not self._can_rewrite_history():
                    return False
                idx = next((i for i, c in enumerate(state.commits) if c.sha == target.sha), None)
                if idx is None:
                    return False
                if kind == "reorder-before":
                    before = state.commits[idx - 1] if idx > 0 else None
                else:
                    before = target
                self.store.reorder_onto(repo, moving, before)
                return True

            drop.connect("drop", on_drop)

            def on_motion(_t, _x, y, widget=row):
                from ..commit_dnd import commit_drop_kind, drop_kind_css_class

                kind = commit_drop_kind(float(y or 0), float(widget.get_allocated_height() or 1))
                wanted = drop_kind_css_class(kind)
                for cls in ("commit-drop-squash", "commit-drop-before", "commit-drop-after"):
                    if cls == wanted:
                        widget.add_css_class(cls)
                    else:
                        widget.remove_css_class(cls)
                return Gdk.DragAction.MOVE

            def on_leave(_t, widget=row):
                from ..commit_dnd import clear_drop_kind_css

                clear_drop_kind_css(widget)

            drop.connect("motion", on_motion)
            drop.connect("leave", on_leave)
            row.add_controller(drop)
        except Exception:
            pass

    def _on_amend(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.start_amending(repo)

    def _on_stop_amend(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.stop_amending(repo)

    def _resolve(self, path: str, resolution: ManualConflictResolution) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.resolve_conflict(repo, path, resolution)

    def _update_checks(self, state) -> None:
        if not hasattr(self, "_checks_btn"):
            return
        runs = state.check_runs or []
        failed = [r for r in runs if r.conclusion in {"failure", "timed_out", "cancelled"}]
        pending = [r for r in runs if r.status != "completed"]
        if failed:
            self._checks_btn.set_icon_name("dialog-error-symbolic")
            self._checks_btn.add_css_class("checks-failure")
            self._checks_btn.set_tooltip_text(f"{len(failed)} check(s) failed")
        elif pending:
            self._checks_btn.set_icon_name("content-loading-symbolic")
            self._checks_btn.set_tooltip_text(f"{len(pending)} check(s) pending")
        elif runs:
            self._checks_btn.set_icon_name("emblem-ok-symbolic")
            self._checks_btn.set_tooltip_text(f"{len(runs)} check(s) passed")
        else:
            self._checks_btn.set_icon_name("emblem-system-symbolic")
            self._checks_btn.set_tooltip_text("No checks")

    def _on_checks(self, *_args: object) -> None:
        present_checks_popover(self._checks_btn, self.store)

    def _update_tutorial_banner(self, repo, state) -> None:
        if hasattr(self, "_tutorial_panel"):
            active = bool(repo.tutorial) and is_valid_tutorial_step(self.store.tutorial_step)
            self._tutorial_panel.set_visible(active)
            if active:
                editor = self.store.settings.selected_external_editor
                self._tutorial_panel.refresh(self.store.tutorial_step, editor)
        if not hasattr(self, "_tutorial_banner"):
            return
        # The side panel is the Desktop tutorial UI; keep the banner for the first editor nudge only
        # when the panel is unavailable.
        if hasattr(self, "_tutorial_panel"):
            self._tutorial_banner.set_revealed(False)
            return

    def _completion_exclude_login(self) -> str | None:
        repo = self.store.selected_repository
        account = self.store.account_for_repo(repo) if repo else None
        return account.login if account else None

    def _coauthor_state(self):
        repo = self.store.selected_repository
        return self.store.state_for(repo) if repo else None

    def _coauthor_endpoint(self) -> str:
        repo = self.store.selected_repository
        if repo is not None and repo.github is not None:
            return repo.github.endpoint
        return self.store.accounts[0].endpoint if self.store.accounts else ""

    def _refresh_issue_completion(self, state) -> None:
        if not hasattr(self, "_issue_store"):
            return
        if hasattr(self, "_author_input"):
            self._author_input.refresh_completion()
        self._update_summary_completion()

    def _token_before_cursor(self, entry: Gtk.Entry) -> str:
        return token_before_cursor(entry.get_text(), entry.get_position())

    def _update_summary_completion(self) -> None:
        if not hasattr(self, "_issue_store") or not hasattr(self, "_summary"):
            return
        repo = self.store.selected_repository
        state = self.store.state_for(repo) if repo else None
        token = self._token_before_cursor(self._summary)
        populate_completion_store(
            self._issue_store,
            state,
            token,
            exclude_login=self._completion_exclude_login(),
        )
        if token.startswith("#"):
            self.store.refresh_issues(repo)

    def _description_token(self) -> str:
        if not hasattr(self, "_desc_completer"):
            return ""
        return self._desc_completer.token()

    def _update_description_completion(self) -> None:
        if getattr(self, "_applying_commit_form", False):
            return
        if hasattr(self, "_desc_completer"):
            self._desc_completer.update()

    def _on_description_complete(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if hasattr(self, "_desc_completer"):
            self._desc_completer._on_row(_list, row)

    def _refresh_compare_list(self, state=None) -> None:
        if not hasattr(self, "_compare_list"):
            return
        repo = self.store.selected_repository
        if repo is None:
            return
        if state is None:
            state = self.store.state_for(repo)
        for cancel in getattr(self, "_compare_ab_cancels", []):
            cancel()
        self._compare_ab_cancels = []
        query = (self._compare_search.get_text() if hasattr(self, "_compare_search") else "").strip()
        current_tip = state.status.current_tip if state.status else None
        current_name = state.status.current_branch if state.status else None
        while (child := self._compare_list.get_first_child()) is not None:
            self._compare_list.remove(child)
        history = Gtk.ListBoxRow()
        history.set_child(Gtk.Label(label="History", xalign=0))
        history.branch_name = ""
        self._compare_list.append(history)
        comparable = [
            b
            for b in state.branches
            if b.name != current_name and not b.is_desktop_fork_remote_branch
        ]
        if hasattr(self, "_compare_search"):
            has_non_fork = any(not b.is_desktop_fork_remote_branch for b in state.branches)
            self._compare_search.set_placeholder_text(
                compare_placeholder_text(
                    has_non_fork_branch=has_non_fork,
                    comparing=state.history_mode == HistoryTabMode.COMPARE,
                )
            )
        ranked = filter_items(query, comparable, lambda b: [b.name, b.upstream or ""])
        shown = 0
        for branch in ranked:
            if shown >= 40:
                break
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.append(Gtk.Label(label=branch.name, xalign=0, hexpand=True))
            counts = Gtk.Label(label="")
            counts.add_css_class("ahead-behind")
            counts.set_visible(False)
            cached = self.store.try_get_ahead_behind(repo, current_tip, branch.tip_sha)
            if cached and (cached.ahead or cached.behind):
                counts.set_label(f"{cached.ahead} ahead · {cached.behind} behind")
                counts.set_visible(True)
            elif cached is None and current_tip and branch.tip_sha:
                def on_ab(ab, label=counts, expected=branch.tip_sha, item=row):
                    if getattr(item, "tip_sha", None) != expected:
                        return
                    if ab and (ab.ahead or ab.behind):
                        label.set_label(f"{ab.ahead} ahead · {ab.behind} behind")
                        label.set_visible(True)

                self._compare_ab_cancels.append(
                    self.store.request_ahead_behind(repo, current_tip, branch.tip_sha, on_ab)
                )
            box.append(counts)
            row.set_child(box)
            row.branch_name = branch.name
            row.tip_sha = branch.tip_sha
            self._compare_list.append(row)
            shown += 1

    def _on_compare_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        name = getattr(row, "branch_name", "") or ""
        if not name:
            self.store.compare_to_branch(repo, None)
        else:
            self.store.compare_to_branch(repo, name)
        self._refresh_history()

    def _set_compare_mode(self, mode: ComparisonMode) -> None:
        if self._building:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.set_compare_mode(repo, mode)

    def _on_compare_op_changed(self, drop: Gtk.DropDown, *_args) -> None:
        self._compare_op_index = int(drop.get_selected())
        repo = self.store.selected_repository
        if repo:
            self._refresh_compare_cta(self.store.state_for(repo))

    def _execute_compare_merge(self, *_args) -> None:
        repo = self.store.selected_repository
        if repo is None:
            return
        state = self.store.state_for(repo)
        if not state.compare_branch:
            return
        idx = getattr(self, "_compare_op_index", 0)
        if idx < 0 or idx >= len(MERGE_OPTIONS):
            idx = 0
        kind = MERGE_OPTIONS[idx][0]
        compare = state.compare_branch.name
        if kind == MultiCommitOperationKind.REBASE:
            self.store.rebase_branch(repo, compare)
        else:
            self.store.merge_branch(repo, compare, squash=(kind == MultiCommitOperationKind.SQUASH))
        self.store.compare_to_branch(repo, None)

    def _refresh_compare_cta(self, state) -> None:
        if not hasattr(self, "_compare_cta"):
            return
        clear_box(self._compare_cta)
        if state.history_mode != HistoryTabMode.COMPARE or not state.compare_branch:
            return
        repo = self.store.selected_repository
        ahead = len(state.compare_ahead)
        behind = len(state.compare_behind)
        self._compare_cta.append(Gtk.Label(label=f"{ahead} ahead · {behind} behind {state.compare_branch.name}"))
        current = state.status.current_branch if state.status else "current branch"
        compare = state.compare_branch.name
        merge_tree = state.merge_tree
        idx = getattr(self, "_compare_op_index", 0)
        if idx < 0 or idx >= len(MERGE_OPTIONS):
            idx = 0
        kind = MERGE_OPTIONS[idx][0]
        if kind == MultiCommitOperationKind.REBASE:
            commit_count = ahead
            action = ComputedAction.CLEAN
            if merge_tree is not None:
                if merge_tree.kind == ComputedAction.LOADING:
                    action = ComputedAction.LOADING
                elif merge_tree.kind == ComputedAction.INVALID:
                    action = ComputedAction.INVALID
            conflicted = 0
        else:
            commit_count = behind
            if merge_tree is None:
                action = ComputedAction.CLEAN if behind == 0 else ComputedAction.LOADING
                conflicted = 0
            else:
                action = merge_tree.kind
                conflicted = merge_tree.conflicted_files
        message, can_proceed = merge_cta_message(
            kind,
            current,
            compare,
            commit_count,
            action,
            conflicted,
        )
        if action == ComputedAction.CLEAN and kind != MultiCommitOperationKind.REBASE and behind:
            able = Gtk.Label(label="Able to merge automatically.", xalign=0)
            able.add_css_class("dim-label")
            self._compare_cta.append(able)
        if message:
            status = Gtk.Label(label=message, wrap=True, xalign=0)
            if action == ComputedAction.CONFLICTS or action == ComputedAction.INVALID:
                status.add_css_class("warning")
            self._compare_cta.append(status)
        ops = Gtk.Box(spacing=6)
        drop = Gtk.DropDown.new_from_strings([opt[1] for opt in MERGE_OPTIONS])
        drop.set_selected(idx)
        drop.connect("notify::selected", self._on_compare_op_changed)
        drop.set_sensitive(behind > 0 or kind == MultiCommitOperationKind.REBASE)
        action_btn = Gtk.Button(label=MERGE_OPTIONS[idx][1])
        action_btn.add_css_class("suggested-action")
        action_btn.set_sensitive(can_proceed)
        action_btn.connect("clicked", self._execute_compare_merge)
        ops.append(drop)
        ops.append(action_btn)
        self._compare_cta.append(ops)

    def _repo_list_menu(self, widget: Gtk.Widget, repo) -> None:
        """Desktop `generateRepositoryListContextMenu`."""
        missing = bool(repo.is_missing)
        github = bool(repo.github)
        specs = generate_repository_list_context_menu_specs(
            alias=repo.alias,
            missing=missing,
            github=github,
            shell_label=self._open_in_shell_label(),
            editor_label=self._open_in_editor_label(),
            confirm_remove=self.store.settings.confirm_repository_removal,
        )
        callbacks = {
            f"{alias_verb(repo.alias)} alias": lambda: (
                self.store.select_repository(repo.id),
                self.store.show_popup(PopupType.CHANGE_REPOSITORY_ALIAS),
            ),
            "Remove alias": lambda: self.store.remove_repository_alias(repo),
            "Copy repo name": lambda: copy_text(name_of(repo)),
            "Copy repo path": lambda: copy_text(repo.path),
            "View on GitHub": lambda: self.store.view_on_github(repo),
            self._open_in_shell_label(): lambda: self.store.open_in_shell(repo),
            RevealInFileManagerLabel: lambda: self.store.reveal_in_file_manager(repo, ""),
            self._open_in_editor_label(): lambda: self.store.open_in_editor(repo, repo.path),
            self._remove_repository_label(): lambda: (
                self.store.select_repository(repo.id),
                self.store.show_popup(PopupType.REMOVE_REPOSITORY),
            ),
        }
        items = []
        for label, enabled in specs:
            items.append((label, callbacks.get(label, lambda: None), enabled))
            if label in {"Copy repo path", self._open_in_editor_label()}:
                items.append(None)
        show_context_menu(widget, items)

    def _on_repository_toolbar_context_menu(self, widget: Gtk.Widget) -> None:
        """Desktop `onRepositoryToolbarButtonContextMenu`."""
        repo = self.store.selected_repository
        if repo is None:
            return
        self._repo_list_menu(widget, repo)

    def _refresh_author_avatar(self, repo) -> None:
        """Desktop `CommitMessageAvatar` (`renderWarningPopover` / `renderGitConfigPopover`)."""
        if not hasattr(self, "_author_avatar_host"):
            return
        from ..email import COMMIT_ATTRIBUTION_DOCS, is_attributable_email_for, lookup_preferred_email
        from ..git.ops import get_config_value
        from ..github.repo_rules import use_repo_rules_logic

        name, email = self.store.author_identity(repo)
        account = self.store.account_for_repo(repo)
        state = self.store.state_for(repo)
        email_failures = state.repo_rules.commit_author_email_patterns.get_failed_rules(email or "")
        emailRuleFailures = email_failures
        misattributed = bool(account and email and not is_attributable_email_for(account, email))
        repo_rules_enabled = use_repo_rules_logic(account, repo)
        warningType = commit_message_avatar_warning_type(
            email=email,
            repo_rules_enabled=repo_rules_enabled,
            email_failures_status=emailRuleFailures.status,
            misattributed=misattributed,
        )
        clear_box(self._author_avatar_host)
        avatar = Avatar(
            name or (account.login if account else "Git"),
            email or "",
            login=account.login if account else None,
            avatar_url=account.avatar_url if account else None,
            size=28,
            account=account,
            endpoint=account.endpoint if account else None,
        )
        self._author_avatar_host.append(avatar)
        self._author_btn.remove_css_class("author-warning")
        self._author_btn.remove_css_class("author-error")
        is_error = warningType == "disallowedEmail" and emailRuleFailures.status == "fail"
        if warningType != "none":
            self._author_btn.add_css_class("author-error" if is_error else "author-warning")
        if hasattr(self, "_author_warn"):
            self._author_warn.set_visible(False)
        aria = commit_message_avatar_aria_label(warningType)
        self._author_btn.set_tooltip_text(aria)
        try:
            self._author_btn.update_property([Gtk.AccessibleProperty.LABEL], [aria])
        except Exception:
            pass
        clear_box(self._author_popover_box)
        if warningType == "disallowedEmail":
            heading_text = THIS_EMAIL_ADDRESS_IS_DISALLOWED
        elif warningType == "misattribution":
            heading_text = THIS_COMMIT_WILL_BE_MISATTRIBUTED
        else:
            heading_text = committing_as_title(name=name, email=email)
        heading = Gtk.Label(label=heading_text, xalign=0)
        heading.add_css_class("heading")
        self._author_popover_box.append(heading)
        branch = state.status.current_branch if state.status else None
        if warningType == "disallowedEmail" and repo.github and branch:
            self._author_popover_box.append(
                self._repo_rules_failure_list(
                    commit_message_avatar_email_leading_text(email or ""),
                    emailRuleFailures,
                    repo.github,
                    branch,
                )
            )
        elif warningType == "misattribution":
            enterprise_suffix = " Enterprise" if account and account.is_enterprise else ""
            user_name = f" for {name}" if name else ""
            warn = Gtk.Label(
                label=(
                    f"The email in your global Git config ({email}) doesn't match your "
                    f"GitHub{enterprise_suffix} account{user_name}. "
                    "This email address doesn't match your GitHub account. "
                    "Commits may not be attributed to you."
                ),
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            self._author_popover_box.append(warn)
            learn = Gtk.LinkButton(uri=COMMIT_ATTRIBUTION_DOCS, label="Learn more")
            learn.set_tooltip_text(LEARN_MORE_ABOUT_COMMIT_ATTRIBUTION)
            learn.set_halign(Gtk.Align.START)
            self._author_popover_box.append(learn)
        else:
            if name and email:
                self._author_popover_box.append(Gtk.Label(label=f"Email: {email}", xalign=0, wrap=True))
            isGitConfigLocal = False
            try:
                isGitConfigLocal = bool(
                    get_config_value(repo.path, "user.name", local_only=True)
                    or get_config_value(repo.path, "user.email", local_only=True)
                )
            except Exception:
                isGitConfigLocal = False
            is_local = isGitConfigLocal
            self._author_popover_box.append(
                Gtk.Label(label=git_config_popover_copy(local=is_local), wrap=True, xalign=0)
            )
        emails = list(account.email_addresses) if account else []
        if account:
            preferred = lookup_preferred_email(account)
            if preferred not in emails:
                emails.insert(0, preferred)
        has_emails = bool(emails)
        if warningType != "none" and has_emails:
            emails_heading = Gtk.Label(label=YOUR_ACCOUNT_EMAILS, xalign=0)
            emails_heading.add_css_class("heading")
            self._author_popover_box.append(emails_heading)
            for item in emails:
                btn = Gtk.Button(label=item)
                btn.add_css_class("flat")
                btn.connect("clicked", lambda _b, addr=item: self._use_author_email(repo, addr))
                self._author_popover_box.append(btn)
        choose = Gtk.Label(
            label=commit_message_avatar_choose_local_email_copy(has_emails=has_emails),
            wrap=True,
            xalign=0,
        )
        choose.add_css_class("dim-label")
        self._author_popover_box.append(choose)
        row = Gtk.Box(spacing=6)
        ignore = Gtk.Button(label=IGNORE_LABEL)
        ignore.connect("clicked", lambda *_: self._author_popover.popdown())
        row.append(ignore)
        if warningType != "none" and has_emails:
            update = Gtk.Button(label=UPDATE_EMAIL_LABEL)
            update.add_css_class("suggested-action")
            update.connect("clicked", lambda *_: self._use_author_email(repo, emails[0]))
            row.append(update)
        elif warningType == "none":
            git_btn = Gtk.Button(label=open_git_settings_label())
            git_btn.add_css_class("suggested-action")
            git_btn.connect(
                "clicked",
                lambda *_: (self._author_popover.popdown(), show_preferences(self, self.store, PreferencesTab.GIT)),
            )
            row.append(git_btn)
        self._author_popover_box.append(row)
        repo_btn = Gtk.Button(label="repository settings")
        repo_btn.add_css_class("flat")
        repo_btn.connect(
            "clicked",
            lambda *_: (
                self._author_popover.popdown(),
                self.store.show_popup(PopupType.REPOSITORY_SETTINGS, tab=RepositorySettingsTab.GIT_CONFIG),
            ),
        )
        self._author_popover_box.append(repo_btn)

    def _use_author_email(self, repo, email: str) -> None:
        self.store.set_commit_author_email(repo, email)
        self._author_popover.popdown()
        self._refresh_author_avatar(repo)

    def _flush_commit_form(self) -> None:
        """Write the in-progress commit box back onto the repository that owns it."""
        if getattr(self, "_applying_commit_form", False) or not hasattr(self, "_summary"):
            return
        prev_id = getattr(self, "_form_repo_id", None)
        if prev_id is None:
            return
        prev = next((r for r in self.store.repositories if r.id == prev_id), None)
        if prev is None:
            return
        start, end = self._description.get_buffer().get_bounds()
        state = self.store.state_for(prev)
        summary = self._summary.get_text()
        description = self._description.get_buffer().get_text(start, end, True)
        generated = bool(getattr(state.commit_message, "generated_by_copilot", False))
        if summary != (state.commit_message.summary or "") or description != (state.commit_message.description or ""):
            generated = False
        state.commit_message = CommitMessage(
            summary=summary,
            description=description,
            timestamp=state.commit_message.timestamp,
            generated_by_copilot=generated,
        )
        if hasattr(self, "_copilot_hint"):
            self._copilot_hint.set_visible(generated)
        if hasattr(self, "_author_input") and hasattr(self, "_coauthor_check"):
            if self._coauthor_check.get_active():
                self._author_input.commit_pending()
                state.co_authors = self._author_input.get_authors()
                state.show_co_authors = True
            else:
                state.show_co_authors = False

    def _apply_commit_form(self, repo, state) -> None:
        if not hasattr(self, "_summary"):
            return
        switched = getattr(self, "_form_repo_id", None) != repo.id
        if switched:
            self._flush_commit_form()
        self._applying_commit_form = True
        try:
            if state.commit_to_amend is not None:
                self._summary.set_text(state.commit_message.summary or state.commit_to_amend.summary)
                self._description.get_buffer().set_text(state.commit_message.description or state.commit_to_amend.body)
            elif switched:
                self._summary.set_text(state.commit_message.summary)
                self._description.get_buffer().set_text(state.commit_message.description or "")
                self._applied_commit_message_ts = state.commit_message.timestamp
            else:
                msg = state.commit_message
                applied = getattr(self, "_applied_commit_message_ts", 0)
                if msg.timestamp and msg.timestamp > applied:
                    self._summary.set_text(msg.summary)
                    self._description.get_buffer().set_text(msg.description or "")
                    self._applied_commit_message_ts = msg.timestamp
            if switched and hasattr(self, "_author_input"):
                if state.co_authors:
                    self._coauthor_check.set_active(True)
                    self._author_input.set_visible(True)
                    self._author_input.set_authors(list(state.co_authors))
                else:
                    self._coauthor_check.set_active(False)
                    self._author_input.set_visible(False)
                    self._author_input.set_authors([])
        finally:
            self._applying_commit_form = False
            self._form_repo_id = repo.id
        if hasattr(self, "_copilot_hint"):
            self._copilot_hint.set_visible(bool(getattr(state.commit_message, "generated_by_copilot", False)))

    def _on_summary_changed(self, entry: Gtk.Entry) -> None:
        self._flush_commit_form()
        self._update_commit_warnings()
        self._update_summary_completion()

    def _update_commit_warnings(self) -> None:
        if not hasattr(self, "_summary_warn"):
            return
        text = self._summary.get_text() if hasattr(self, "_summary") else ""
        repo = self.store.selected_repository

        def hide_inline_rules() -> None:
            self._rules_warn.set_visible(False)
            if hasattr(self, "_rules_link"):
                self._rules_link.set_visible(False)
            if hasattr(self, "_rules_box"):
                self._rules_box.set_visible(False)
            self._clear_commit_warning_links()

        def hide_rules() -> None:
            hide_inline_rules()
            self._hide_rule_failure_hint()

        if not hasattr(self, "_rules_warn"):
            hint = summary_length_hint(text, self.store.settings.show_commit_length_warning)
            self._summary_warn.set_text(hint or "")
            self._summary_warn.set_visible(bool(hint))
            return
        if not repo:
            hint = summary_length_hint(text, self.store.settings.show_commit_length_warning)
            self._summary_warn.set_text(hint or "")
            self._summary_warn.set_visible(bool(hint))
            hide_rules()
            self._apply_commit_busy()
            return
        from ..github.repo_rules import (
            commit_rule_warnings,
            rulesets_url_for_branch,
            use_repo_rules_logic,
        )

        state = self.store.state_for(repo)
        start, end = self._description.get_buffer().get_bounds()
        description = self._description.get_buffer().get_text(start, end, True).strip()
        message = "\n\n".join(part for part in (text.strip(), description) if part)
        _name, email = self.store.author_identity(repo)
        unpublished = state.ahead_behind is None
        warnings: list[str] = []
        hard = False
        repo_rules_enabled = use_repo_rules_logic(self.store.account_for_repo(repo), repo)
        repoRulesEnabled = repo_rules_enabled
        if repoRulesEnabled:
            warnings, hard = commit_rule_warnings(
                state.repo_rules,
                message=message,
                author_email=email,
                branch=state.status.current_branch if state.status else None,
                ahead_behind=state.ahead_behind,
                unpublished=unpublished,
            )
        branch = state.status.current_branch if state.status else None
        msg_fail = state.repo_rules.commit_message_patterns.get_failed_rules(message)
        show_rule_hint = bool(
            repoRulesEnabled
            and branch
            and repo.github
            and msg_fail.status != "pass"
        )
        hint = None if show_rule_hint else summary_length_hint(
            text, self.store.settings.show_commit_length_warning
        )
        if hint:
            self._summary_warn.set_text(hint)
            self._summary_warn.set_visible(True)
        else:
            self._summary_warn.set_visible(False)
        self._update_rule_failure_hint(repo, branch, msg_fail, show_rule_hint)
        self._clear_commit_warning_links()
        action_rows: list[Gtk.Widget] = []
        if state.commit_to_amend is not None:
            warnings.insert(
                0,
                "Your changes will modify your most recent commit. Stop amending to make these changes as a new commit.",
            )
            action_rows.append(
                self._commit_warning_markup(
                    "Your changes will modify your <b>most recent commit</b>. "
                    '<a href="stop-amend">Stop amending</a> to make these changes as a new commit.'
                )
            )
        if repo.github and repo.github.permissions == "read":
            warnings.insert(0, f"You don't have write access to {repo.name}. Want to create a fork?")
            action_rows.append(
                self._commit_warning_markup(
                    f"You don't have write access to <b>{GLib.markup_escape_text(repo.name)}</b>. "
                    'Want to <a href="fork">create a fork</a>?'
                )
            )
        elif branch and state.current_branch_protected:
            warnings.insert(0, f"{branch} is a protected branch. Want to switch branches?")
            action_rows.append(
                self._commit_warning_markup(
                    f"<b>{GLib.markup_escape_text(branch)}</b> is a protected branch. "
                    'Want to <a href="switch">switch branches</a>?'
                )
            )
        if state.repo_rules.signed_commits_required is True:
            action_rows.append(
                self._commit_warning_markup(
                    f'<a href="rulesets">One or more rules</a> apply to the branch '
                    f"<b>{GLib.markup_escape_text(branch or '')}</b> that require signed commits. "
                    '<a href="https://docs.github.com/authentication/managing-commit-signature-verification/signing-commits">'
                    "Learn more about commit signing.</a>"
                )
            )
        elif state.repo_rules.basic_commit_warning is True and branch:
            action_rows.append(
                self._commit_warning_markup(
                    f'<a href="rulesets">One or more rules</a> apply to the branch '
                    f"<b>{GLib.markup_escape_text(branch)}</b> that will prevent pushing. "
                    'Want to <a href="switch">switch branches</a>?'
                )
            )
        if repo.github:
            if unpublished and branch:
                name_fail = state.repo_rules.branch_name_patterns.get_failed_rules(branch)
                if name_fail.status != "pass":
                    action_rows.append(
                        self._repo_rules_failure_list(f"The branch '{branch}'", name_fail, repo.github, branch)
                    )
        extra = [
            line
            for line in warnings
            if "Want to create a fork" not in line
            and "Want to switch branches" not in line
            and "Stop amending" not in line
            and "requires signed commits" not in line
            and "may prevent pushing" not in line
            and not line.startswith("The commit message ")
            and not line.startswith("The commit author email ")
        ]
        if extra or action_rows:
            self._rules_warn.set_text("\n".join(extra) if extra else "\n".join(warnings))
            self._rules_warn.set_visible(bool(extra))
            if hasattr(self, "_rules_box"):
                self._rules_box.set_visible(True)
                sibling = self._rules_warn
                for row in action_rows:
                    self._rules_box.insert_child_after(row, sibling)
                    sibling = row
            uri = rulesets_url_for_branch(repo.github, branch) if repo.github else None
            if hasattr(self, "_rules_link"):
                if uri:
                    self._rules_link.set_uri(uri)
                    self._rules_link.set_visible(True)
                else:
                    self._rules_link.set_visible(False)
        else:
            hide_inline_rules()
        if hasattr(self, "_commit_btn"):
            self._commit_btn.set_sensitive(not hard)
        self._apply_commit_busy(state)

    def _apply_commit_busy(self, state=None) -> None:
        repo = self.store.selected_repository
        state = state or (self.store.state_for(repo) if repo else None)
        busy = bool(state and (state.is_committing or state.is_generating_commit_message))
        generating = bool(state and state.is_generating_commit_message)
        if hasattr(self, "_summary"):
            self._summary.set_editable(not busy)
        if hasattr(self, "_description"):
            self._description.set_editable(not busy)
        if hasattr(self, "_generate_btn"):
            self._update_copilot_button(state)
        if hasattr(self, "_commit_btn") and busy:
            self._commit_btn.set_sensitive(False)
        if hasattr(self, "_copilot_hint"):
            if generating:
                self._copilot_hint.set_text("Generating commit details…")
                self._copilot_hint.set_visible(True)
            else:
                self._copilot_hint.set_text("Generated by Copilot")
                generated = bool(state and getattr(state.commit_message, "generated_by_copilot", False))
                self._copilot_hint.set_visible(generated)

    def _update_copilot_button(self, state=None) -> None:
        if not hasattr(self, "_generate_btn"):
            return
        entitled = any(enable_commit_message_generation(account) for account in self.store.accounts)
        self._generate_btn.set_visible(entitled)
        if hasattr(self, "_generate_box"):
            self._generate_box.set_visible(entitled)
        if hasattr(self, "_generate_new"):
            self._generate_new.set_visible(
                entitled and not self.store.settings.commit_message_generation_button_clicked
            )
        if not entitled:
            return
        files: list = []
        if state and state.status:
            files = [item for item in state.status.working_directory.files if item.include]
        amending = bool(state and state.commit_to_amend)
        no_changes = not amending and not files
        busy = bool(state and (state.is_committing or state.is_generating_commit_message))
        generating = bool(state and state.is_generating_commit_message)
        self._generate_btn.set_sensitive(not busy and not no_changes)
        tip = "Generate commit message with Copilot"
        if generating:
            tip = "Generating commit details…"
        elif no_changes:
            tip = "Generate commit message with Copilot. Files must be selected to generate a commit message."
        self._generate_btn.set_tooltip_text(tip)

    def _clear_commit_warning_links(self) -> None:
        if not hasattr(self, "_rules_box"):
            return
        child = self._rules_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            if child not in {self._rules_warn, getattr(self, "_rules_link", None)}:
                self._rules_box.remove(child)
            child = nxt

    def _hide_rule_failure_hint(self) -> None:
        if hasattr(self, "_rule_failure_hint"):
            self._rule_failure_hint.set_visible(False)
        self._hide_rule_failure_popover(keep_wanted=True)

    def _hide_rule_failure_popover(self, *, keep_wanted: bool) -> None:
        if not hasattr(self, "_rule_failure_popover"):
            return
        self._suppress_rule_popover_closed = True
        try:
            self._rule_failure_popover.popdown()
        finally:
            self._suppress_rule_popover_closed = False
        if not keep_wanted:
            self._rule_failure_popover_wanted = False

    def _update_rule_failure_hint(self, repo, branch, failures, show_hint: bool) -> None:
        """Desktop `renderRepoRuleCommitMessageFailureHint` + `renderRuleFailurePopover`."""
        from ..github.repo_rules import commit_message_failure_hint_aria_label

        if not hasattr(self, "_rule_failure_hint"):
            return
        if not show_hint:
            self._hide_rule_failure_hint()
            return
        can_bypass = failures.status == "bypass"
        aria = commit_message_failure_hint_aria_label(can_bypass=can_bypass)
        self._rule_failure_hint.set_icon_name(
            "dialog-warning-symbolic" if can_bypass else "dialog-error-symbolic"
        )
        self._rule_failure_hint.set_tooltip_text(aria)
        try:
            self._rule_failure_hint.update_property([Gtk.AccessibleProperty.LABEL], [aria])
        except Exception:
            pass
        self._rule_failure_hint.remove_css_class("warning-icon")
        self._rule_failure_hint.remove_css_class("error-icon")
        self._rule_failure_hint.add_css_class("warning-icon" if can_bypass else "error-icon")
        self._rule_failure_hint.set_visible(True)
        self._render_rule_failure_popover(repo, branch, failures)
        if self._rule_failure_popover_wanted:
            self._rule_failure_popover.popup()
        else:
            self._hide_rule_failure_popover(keep_wanted=True)

    def _render_rule_failure_popover(self, repo, branch, failures) -> None:
        """Desktop `renderRuleFailurePopover`."""
        if not hasattr(self, "_rule_failure_list_host") or not repo.github:
            return
        while (child := self._rule_failure_list_host.get_first_child()) is not None:
            self._rule_failure_list_host.remove(child)
        self._rule_failure_list_host.append(
            self._repo_rules_failure_list("This commit message", failures, repo.github, branch)
        )

    renderRuleFailurePopover = _render_rule_failure_popover
    renderRepoRuleCommitMessageFailureHint = _update_rule_failure_hint

    def _toggle_rule_failure_popover(self, *_args: object) -> None:
        """Desktop `toggleRuleFailurePopover`."""
        self._rule_failure_popover_wanted = not getattr(self, "_rule_failure_popover_wanted", False)
        if self._rule_failure_popover_wanted:
            if hasattr(self, "_rule_failure_popover"):
                self._rule_failure_popover.popup()
        else:
            self._hide_rule_failure_popover(keep_wanted=False)

    toggleRuleFailurePopover = _toggle_rule_failure_popover

    def _close_rule_failure_popover(self) -> None:
        """Desktop `closeRuleFailurePopover`."""
        self._hide_rule_failure_popover(keep_wanted=False)

    closeRuleFailurePopover = _close_rule_failure_popover

    def _on_rule_failure_popover_closed(self, *_args: object) -> None:
        if getattr(self, "_suppress_rule_popover_closed", False):
            return
        self._rule_failure_popover_wanted = False

    @property
    def is_rule_failure_popover_open(self) -> bool:
        """Desktop `isRuleFailurePopoverOpen`."""
        return bool(getattr(self, "_rule_failure_popover_wanted", False))

    isRuleFailurePopoverOpen = is_rule_failure_popover_open

    def _commit_warning_markup(self, markup: str) -> Gtk.Label:
        label = Gtk.Label(wrap=True, xalign=0, use_markup=True)
        label.set_markup(markup)
        label.add_css_class("repo-rules-warning")
        label.connect("activate-link", self._on_commit_warning_link)
        return label

    def _repo_rules_failure_list(self, leading: str, failures, repository, branch: str | None) -> Gtk.Widget:
        """Desktop `RepoRulesMetadataFailureList` with per-ruleset links."""
        from ..github.repo_rules import repo_rules_failure_heading, ruleset_url, rulesets_url_for_branch

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("repo-rules-failure-list-component")
        heading = repo_rules_failure_heading(leading, failures)
        view_all = rulesets_url_for_branch(repository, branch) if branch else None
        if view_all:
            escaped = GLib.markup_escape_text(heading)
            markup = f'{escaped} <a href="{GLib.markup_escape_text(view_all)}">View all rulesets for this branch.</a>'
            box.append(self._commit_warning_markup(markup))
        else:
            label = Gtk.Label(label=heading, wrap=True, xalign=0)
            label.add_css_class("repo-rules-warning")
            box.append(label)
        for group_name, items in (("Failed rules:", failures.failed), ("Bypassed rules:", failures.bypassed)):
            if not items:
                continue
            group = Gtk.Label(label=group_name, xalign=0)
            group.add_css_class("heading")
            box.append(group)
            for item in items:
                href = ruleset_url(repository, item.ruleset_id) or ""
                text = GLib.markup_escape_text(item.description)
                if href:
                    row = self._commit_warning_markup(f'<a href="{GLib.markup_escape_text(href)}">{text}</a>')
                    row.add_css_class("repo-ruleset-link")
                else:
                    row = Gtk.Label(label=item.description, wrap=True, xalign=0)
                    row.add_css_class("repo-rules-warning")
                box.append(row)
        return box

    def _on_commit_warning_link(self, _label: Gtk.Label, uri: str) -> bool:
        if uri == "fork":
            self.store.show_popup(PopupType.CREATE_FORK)
            return True
        if uri == "switch":
            if hasattr(self, "_branches_foldout"):
                self.store.show_foldout(FoldoutType.BRANCH)
            return True
        if uri == "stop-amend":
            repo = self.store.selected_repository
            if repo:
                self.store.stop_amending(repo)
            return True
        if uri == "rulesets":
            repo = self.store.selected_repository
            if repo and repo.github:
                from ..github.repo_rules import rulesets_url_for_branch

                branch = None
                state = self.store.state_for(repo)
                if state.status:
                    branch = state.status.current_branch
                href = rulesets_url_for_branch(repo.github, branch)
                if href:
                    open_external(href)
            return True
        if uri.startswith("http://") or uri.startswith("https://"):
            open_external(uri)
            return True
        return False

    def _generate_commit_message(self) -> None:
        """Desktop `onGenerateCommitMessage` from the Copilot button and context menu."""
        has_text = bool(self._summary.get_text().strip()) if hasattr(self, "_summary") else False
        if has_text and self.store.settings.confirm_commit_message_override:
            self.store.show_popup(PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE)
            return
        if self.store.should_show_copilot_disclaimer():
            self.store.show_popup(PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER)
            return
        repo = self.store.selected_repository
        if repo:
            self.store.generate_commit_message(repo)

    def _show_stash_diff(self, file, sha: str) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.select_stashed_file(repo, file)

    def _select_all_from_focus(self, widget) -> bool:
        """Desktop `selectAll` / `selectAllWindowContents` custom event: list rows, then diff text."""
        current = widget
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, Gtk.ListBox) and current.get_selection_mode() == Gtk.SelectionMode.MULTIPLE:
                self._select_all_list_box(current)
                return True
            try:
                if current.has_css_class("diff-view"):
                    self._select_all_diff_text(current)
                    return True
            except Exception:
                pass
            current = current.get_parent() if hasattr(current, "get_parent") else None
        if isinstance(widget, Gtk.Label):
            try:
                if widget.get_selectable():
                    widget.select_region(0, -1)
                    return True
            except Exception:
                pass
        return False

    def _select_all_list_box(self, box: Gtk.ListBox) -> None:
        """Desktop list `onSelectAll` for a multi-select `Gtk.ListBox`."""
        was_building = self._building
        self._building = True
        try:
            box.select_all()
        finally:
            self._building = was_building
        row = box.get_selected_row()
        if box is getattr(self, "_commit_list", None):
            self._on_commit_selected(box, row)
        elif box is getattr(self, "_file_list", None) and row is not None:
            self._on_file_selected(box, row)

    def _select_all_diff_text(self, viewer: Gtk.Widget) -> None:
        """Desktop diff `onSelectAll` / `selectAllChildren` of the diff container."""
        def walk(node: Gtk.Widget) -> None:
            if isinstance(node, Gtk.Label):
                try:
                    if node.get_selectable():
                        node.select_region(0, -1)
                except Exception:
                    pass
            elif isinstance(node, Gtk.TextView):
                buf = node.get_buffer()
                buf.select_range(buf.get_start_iter(), buf.get_end_iter())
            child = node.get_first_child() if hasattr(node, "get_first_child") else None
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(viewer)

    def _edit_action(self, action: str, widget=None) -> None:
        widget = widget if widget is not None else self.get_focus()
        if widget is None:
            return
        clipboard = self.get_clipboard()
        if apply_edit_menu_action(widget, action, clipboard=clipboard):
            return
        if action == "select-all":
            self._select_all_from_focus(widget)

    def _resize_active_resizable(self, increase: bool) -> None:
        """Desktop `resizeActiveResizable` (`increase-active-resizable-width` / `decrease-active-resizable-width`)."""
        resize_active_resizable(self.get_focus(), increase)

    def _reset_sidebar_width(self) -> None:
        self._applying_sidebar_width = True
        try:
            self.store.reset_sidebar_width()
            if hasattr(self, "_changes_paned"):
                self._changes_paned.set_position(max(220, defaultSidebarWidth))
            if hasattr(self, "_history_paned"):
                self._history_paned.set_position(max(220, defaultSidebarWidth))
            self._sync_repository_foldout_width()
        finally:
            self._applying_sidebar_width = False

    def _on_commit_summary_paned_position(self, paned, *_args: object) -> None:
        """Desktop `setCommitSummaryWidth` while dragging the selected-commit file list."""
        if getattr(self, "_building", False) or getattr(self, "_applying_constraints", False):
            return
        pos = paned.get_position()
        if pos > 0:
            self.store.set_commit_summary_width(pos)

    def _reset_commit_summary_width(self) -> None:
        """Desktop `onReset` for the selected-commit file list (`commitSummaryWidth`)."""
        self.store.reset_commit_summary_width()
        if hasattr(self, "_hist_files_paned"):
            self._hist_files_paned.set_position(max(100, defaultCommitSummaryWidth))

    def _reset_stashed_files_width(self) -> None:
        self.store.reset_stashed_files_width()
        paned = getattr(getattr(self, "_stash_viewer", None), "_files_paned", None)
        if paned is not None:
            paned.set_position(max(180, defaultStashedFilesWidth))

    def _pr_suggested_preview(self, *_args: object) -> None:
        self.store.set_pull_request_suggested_next_action(PullRequestSuggestedNextAction.PREVIEW_PULL_REQUEST.value)
        repo = self.store.selected_repository
        if repo:
            self.store.preview_pull_request(repo)

    def _pr_suggested_create(self, *_args: object) -> None:
        self.store.set_pull_request_suggested_next_action(PullRequestSuggestedNextAction.CREATE_PULL_REQUEST.value)
        repo = self.store.selected_repository
        if repo:
            self.store.open_pull_request(repo)

    def _show_shortcuts(self, *_args: object) -> None:
        try:
            win = Gtk.ShortcutsWindow()
            win.set_transient_for(self)
            win.set_modal(True)
            section = Gtk.ShortcutsSection()
            try:
                section.set_property("section-name", "main")
                section.set_property("title", "GitHub Desktop")
            except Exception:
                pass
            groups = [
                (
                    "File",
                    [
                        ("New repository", "<Control>n"),
                        ("Add local repository", "<Control>o"),
                        ("Clone repository", "<Control><Shift>o"),
                        ("Options", "<Control>comma"),
                    ],
                ),
                (
                    "Edit",
                    [
                        ("Undo", "<Control>z"),
                        ("Redo", "<Control><Shift>z"),
                        ("Find", "<Control>f"),
                    ],
                ),
                (
                    "View",
                    [
                        ("Changes", "<Control>1"),
                        ("History", "<Control>2"),
                        ("Repository list", "<Control>t"),
                        ("Branches", "<Control>b"),
                        ("Toggle full screen", "F11"),
                        ("Zoom in", "<Control>plus"),
                        ("Zoom out", "<Control>minus"),
                        ("Reset zoom", "<Control>0"),
                        ("Expand active resizable", "<Control>9"),
                        ("Contract active resizable", "<Control>8"),
                    ],
                ),
                (
                    "Repository",
                    [
                        ("Push", "<Control>p"),
                        ("Pull", "<Control><Shift>p"),
                        ("Fetch", "<Control><Shift>t"),
                        ("Open in shell", "<Control>grave"),
                        ("Show in your File Manager", "<Control><Shift>f"),
                        ("Open in editor", "<Control><Shift>a"),
                    ],
                ),
                (
                    "Branch",
                    [
                        ("Create pull request", "<Control>r"),
                        ("Preview pull request", "<Alt>p"),
                        ("Update from default branch", "<Control><Shift>u"),
                        ("Stashed changes", "<Control>h"),
                    ],
                ),
            ]
            for title, items in groups:
                group = Gtk.ShortcutsGroup()
                try:
                    group.set_property("title", title)
                except Exception:
                    pass
                for shortcut_title, accelerator in items:
                    sc = Gtk.ShortcutsShortcut()
                    sc.set_property("title", shortcut_title)
                    sc.set_property("accelerator", accelerator)
                    group.append(sc)
                section.append(group)
            win.set_child(section) if hasattr(win, "set_child") else win.add(section)
            win.present()
        except Exception:
            open_external(
                "https://docs.github.com/en/desktop/installing-and-configuring-github-desktop/overview/keyboard-shortcuts"
            )

