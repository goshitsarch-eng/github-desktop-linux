"""Main GitHub Desktop window (Adwaita)."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..models import (
    AppFileStatusKind,
    BannerType,
    BranchType,
    ChangesListFilter,
    CommitMessage,
    ComparisonMode,
    ComputedAction,
    DiffSelectionType,
    ForcePushBranchState,
    HistoryTabMode,
    ManualConflictResolution,
    MultiCommitOperationKind,
    PopupType,
    PullRequestSuggestedNextAction,
    RepositorySectionTab,
    TutorialStep,
    WelcomeStep,
    WorkingDirectoryFileChange,
    format_commit_attribution,
    get_conflicted_files,
)
from ..push_pull import describe_push_pull, format_commit_relative_time, format_last_fetched
from ..shells import open_external, open_in_default_program
from ..store import AppStore
from ..version import APP_NAME
from .avatar import Avatar, AvatarStack, users_from_commit
from .author_input import AuthorInput
from .branches import BranchesFoldout
from .checks import present_checks_popover
from .dialogs import present_popup, show_preferences, show_reorder_commits
from .diff_view import DiffViewer
from .emoji import matching_shortcodes
from .history import ExpandableCommitSummary
from .menus import attach_right_click, clear_box, copy_text, show_context_menu
from .multi_commit import show_confirm_abort, show_conflicts_dialog
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


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: AppStore) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.store = store
        self.set_default_size(store.settings.window_width, store.settings.window_height)
        self._building = False
        self._light_update = False
        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast.set_child(self._root)
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
        self._install_file_drop()
        self.store.subscribe(self._on_store)
        self.connect("close-request", self._on_close)
        self._apply_underline_links()
        self._on_store()

    def _on_close(self, *_args: object) -> bool:
        alloc = self.get_width(), self.get_height()
        if alloc[0] > 0:
            self.store.settings.window_width = alloc[0]
            self.store.settings.window_height = alloc[1]
            if hasattr(self, "_changes_paned"):
                pos = self._changes_paned.get_position()
                if pos > 0:
                    self.store.settings.sidebar_width = pos
            if hasattr(self, "_history_paned"):
                pos = self._history_paned.get_position()
                if pos > 0:
                    self.store.settings.commit_summary_width = pos
            self.store.persist_settings()
        self._flush_commit_form()
        return False

    def _on_store(self) -> None:
        if self._building:
            return
        popup = self.store.popup
        if self.store._progress_only_emit and not popup:
            self.store._progress_only_emit = False
            self._update_network_progress()
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
        if self.store.banner:
            kind = self.store.banner.type
            self._banner.set_title(self._banner_text(kind, self.store.banner))
            if kind == BannerType.OPEN_THANK_YOU_CARD:
                self._banner.set_button_label("Open Your Card")
            elif kind == BannerType.DETACHED_HEAD:
                self._banner.set_button_label("Create branch")
            elif kind in CONFLICT_BANNER_KINDS:
                self._banner.set_button_label("View conflicts")
            elif kind in SUCCESS_BANNER_KINDS and self.store.banner.undo_sha:
                self._banner.set_button_label("Undo")
            else:
                self._banner.set_button_label("Dismiss")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)
        popup = self.store.popup
        if popup:
            current = popup
            self.store.popup = None
            present_popup(self, self.store, current.type, current.payload)
        self._apply_underline_links()

    def _apply_underline_links(self) -> None:
        if self.store.settings.underline_links:
            self.add_css_class("underline-links")
        else:
            self.remove_css_class("underline-links")

    def _banner_text(self, kind: BannerType, banner) -> str:
        mapping = {
            BannerType.SUCCESSFUL_MERGE: f"Successfully merged {banner.their_branch or ''}",
            BannerType.MERGE_CONFLICTS_FOUND: "Merge conflicts need to be resolved",
            BannerType.SUCCESSFUL_REBASE: f"Successfully rebased onto {banner.target_branch or ''}",
            BannerType.REBASE_CONFLICTS_FOUND: "Rebase conflicts need to be resolved",
            BannerType.BRANCH_ALREADY_UP_TO_DATE: "Branch is already up to date",
            BannerType.SUCCESSFUL_CHERRY_PICK: f"Cherry-picked {banner.count} commit(s)",
            BannerType.CHERRY_PICK_CONFLICTS_FOUND: "Cherry-pick conflicts need to be resolved",
            BannerType.CHERRY_PICK_UNDONE: "Cherry-pick undone",
            BannerType.SUCCESSFUL_SQUASH: f"Squashed {banner.count} commit(s)",
            BannerType.SQUASH_UNDONE: "Squash undone",
            BannerType.SUCCESSFUL_REORDER: f"Reordered {banner.count} commit(s)",
            BannerType.REORDER_UNDONE: "Reorder undone",
            BannerType.CONFLICTS_FOUND: banner.operation_description or "Conflicts found",
            BannerType.OPEN_THANK_YOU_CARD: "The Desktop team would like to thank you for your contributions.",
            BannerType.DETACHED_HEAD: "You are in a detached HEAD state. Create a branch to keep your work.",
        }
        return mapping.get(kind, kind.value)

    def _on_banner_clicked(self, *_args: object) -> None:
        banner = self.store.banner
        if banner and banner.type == BannerType.OPEN_THANK_YOU_CARD:
            self.store.open_thank_you_card()
            return
        if banner and banner.type == BannerType.DETACHED_HEAD:
            self.store.show_popup(PopupType.CREATE_BRANCH)
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
        add("show-changes", lambda: self.store.set_section(RepositorySectionTab.CHANGES))
        add("show-history", lambda: self.store.set_section(RepositorySectionTab.HISTORY))
        add("choose-repository", self._toggle_repo_sidebar)
        add("show-branches", lambda: self._branches_foldout.popup_and_focus() if hasattr(self, "_branches_foldout") else None)
        add("go-to-commit-message", lambda: self._summary.grab_focus() if hasattr(self, "_summary") else None)
        add("push", lambda: self._repo_op(lambda r: self.store.push_repo(r)))
        add("force-push", lambda: self.store.show_popup(PopupType.CONFIRM_FORCE_PUSH))
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
        add("stash-all", self._stash_all)
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
        add("increase-resizable", lambda: self._nudge_paned(20))
        add("decrease-resizable", lambda: self._nudge_paned(-20))
        add("pr-suggested-preview", self._pr_suggested_preview)
        add("pr-suggested-create", self._pr_suggested_create)
        add("show-shortcuts", self._show_shortcuts)
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

    def _repo_op(self, fn) -> None:
        repo = self.store.selected_repository
        if repo:
            fn(repo)

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

        def run() -> None:
            self.store.stash_and_drop_previous(repo, state.status.current_branch if state.status else "unknown")
            self.store.refresh_repository(repo)

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
        self.store.set_section(RepositorySectionTab.HISTORY)
        if hasattr(self, "_view_stack"):
            self._view_stack.set_visible_child_name("history")
        if hasattr(self, "_compare_search"):
            GLib.idle_add(self._compare_search.grab_focus)

    def _refresh_empty(self) -> None:
        if not hasattr(self, "_empty_tutorial_btn"):
            return
        paused = self.store.tutorial_step == TutorialStep.PAUSED
        self._empty_tutorial_btn.set_label(
            "Return to in progress tutorial" if paused else "Create a tutorial repository…"
        )

    def _on_empty_tutorial(self, *_args: object) -> None:
        if self.store.tutorial_step == TutorialStep.PAUSED:
            self.store.resume_tutorial()
            return
        self.store.show_popup(PopupType.CREATE_TUTORIAL_REPOSITORY)

    def _open_submodule(self, full_path: str) -> None:
        try:
            self.store.add_repositories([full_path])
        except Exception as exc:
            self.store.show_popup(PopupType.ERROR, error=str(exc))

    def _install_file_drop(self) -> None:
        try:
            target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)

            def on_drop(_t, value, _x, _y) -> bool:
                files = value.get_files() if hasattr(value, "get_files") else []
                paths = [f.get_path() for f in files if f.get_path()]
                if paths:
                    self.store.add_dropped_paths(paths)
                    return True
                return False

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

    def _toggle_repo_sidebar(self) -> None:
        if hasattr(self, "_split"):
            self._split.set_show_sidebar(not self._split.get_show_sidebar())

    def _build_welcome(self) -> Gtk.Widget:
        page = Adw.StatusPage()
        page.set_title("Let's get started")
        page.set_description("Sign in to GitHub.com or GitHub Enterprise, or skip and configure Git first.")
        page.set_icon_name("folder-remote-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        sign = Gtk.Button(label="Sign in to GitHub.com")
        sign.add_css_class("suggested-action")
        sign.add_css_class("pill")
        sign.connect("clicked", lambda *_: self.store.begin_sign_in(False))
        ent = Gtk.Button(label="Sign in to GitHub Enterprise")
        ent.connect("clicked", lambda *_: self.store.begin_sign_in(True))
        skip = Gtk.Button(label="Skip this step")
        skip.add_css_class("flat")
        skip.connect("clicked", lambda *_: self.store.skip_welcome_sign_in())
        box.append(sign)
        box.append(ent)
        box.append(skip)
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
        if self.store.welcome_step == WelcomeStep.CONFIGURE_GIT:
            name, email = __import__("github_desktop.git.ops", fromlist=["get_author_identity"]).get_author_identity()
            name_row = Adw.EntryRow(title="Name")
            name_row.set_text(name or "")
            email_row = Adw.EntryRow(title="Email")
            email_row.set_text(email or "")
            finish = Gtk.Button(label="Finish")
            finish.add_css_class("suggested-action")

            def done(*_a: object) -> None:
                try:
                    self.store.save_git_user(name_row.get_text(), email_row.get_text())
                except Exception as exc:
                    self.store.show_popup(PopupType.ERROR, error=str(exc))
                    return
                self.store.finish_welcome()

            finish.connect("clicked", done)
            self._welcome_extra.append(name_row)
            self._welcome_extra.append(email_row)
            self._welcome_extra.append(finish)

    def _build_empty(self) -> Gtk.Widget:
        page = Adw.StatusPage(title="No repositories", description="Add a local repository, clone from GitHub, or create a new one.")
        page.set_icon_name("folder-symbolic")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        for label, action in [
            ("Clone a repository from the Internet…", "win.clone-repository"),
            ("Create a New Repository on my local drive…", "win.new-repository"),
            ("Add an Existing Repository from my local drive…", "win.add-local-repository"),
        ]:
            btn = Gtk.Button(label=label)
            btn.set_action_name(action)
            box.append(btn)
        tutorial = Gtk.Button(label="Create a tutorial repository…")
        tutorial.connect("clicked", self._on_empty_tutorial)
        self._empty_tutorial_btn = tutorial
        box.append(tutorial)
        page.set_child(box)
        return page

    def _build_repo_page(self) -> Gtk.Widget:
        self._split = Adw.OverlaySplitView()
        self._split.set_sidebar(self._build_repo_list())
        self._split.set_sidebar_width_fraction(0.22)
        self._split.set_max_sidebar_width(320)
        self._split.set_show_sidebar(False)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        self._repo_btn = Gtk.Button()
        self._repo_btn.set_label("No repository")
        self._repo_btn.connect("clicked", lambda *_: self._toggle_repo_sidebar())
        header.pack_start(self._repo_btn)

        self._branch_btn = Gtk.MenuButton()
        self._branch_btn.set_always_show_arrow(True)
        self._branches_foldout = BranchesFoldout(
            on_checkout=lambda b: self._repo_op(lambda r: self.store.checkout(r, b)),
            on_create=lambda: self.store.show_popup(PopupType.CREATE_BRANCH),
            on_create_pr=lambda: self._repo_op(self.store.open_pull_request),
            on_rename=lambda b: self.store.show_popup(PopupType.RENAME_BRANCH, branch=b.name),
            on_delete=lambda b: self._delete_named_branch(b),
            on_merge=lambda b: self._repo_op(lambda r: self.store.merge_branch(r, b.name)),
            on_pr=lambda pr: self._repo_op(lambda r: self.store.checkout_pull_request(r, pr)),
            on_view_github=lambda b: self._repo_op(lambda r: self.store.view_branch_on_github(r, b.name)),
            on_cherry_pick=lambda b, sha: self._repo_op(
                lambda r: self.store.cherry_pick_commits(r, [s for s in str(sha).split(",") if s], target_branch=b.name)
            ),
            on_cherry_pick_pr=lambda pr, sha: self._repo_op(
                lambda r: self.store.cherry_pick_onto_pull_request(r, pr, [s for s in str(sha).split(",") if s])
            ),
        )
        self._branch_btn.set_popover(self._branches_foldout)
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
        self._push_btn.set_child(push_inner)
        self._push_btn.connect("clicked", self._on_push_pull)
        self._push_menu_btn = Gtk.MenuButton()
        self._push_menu_btn.set_icon_name("pan-down-symbolic")
        self._push_menu_btn.set_tooltip_text("Fetch and force push")
        self._push_menu_btn.set_visible(False)
        self._push_box.append(self._push_btn)
        self._push_box.append(self._push_menu_btn)
        header.pack_end(self._push_box)

        self._ahead_label = Gtk.Label()
        self._ahead_label.add_css_class("ahead-behind")
        header.pack_end(self._ahead_label)

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
        )
        self._tutorial_panel.set_visible(False)
        self._work_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self._view_stack.set_hexpand(True)
        self._work_area.append(self._view_stack)
        self._work_area.append(self._tutorial_panel)
        self._repo_content = Gtk.Stack()
        self._missing_page = self._build_missing()
        self._repo_content.add_named(self._work_area, "content")
        self._repo_content.add_named(self._missing_page, "missing")
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
        file_m.append("Quit", "app.quit")
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
        view.append("Go to summary", "win.go-to-commit-message")
        view.append(self._stash_menu_label(), "win.toggle-stash")
        view.append("Toggle changes filter", "win.toggle-changes-filter")
        view.append("Increase active resizable", "win.increase-resizable")
        view.append("Decrease active resizable", "win.decrease-resizable")
        view.append("Reset zoom", "win.zoom-reset")
        view.append("Zoom in", "win.zoom-in")
        view.append("Zoom out", "win.zoom-out")
        menu.append_submenu("View", view)
        repo = Gio.Menu()
        repo.append(self._push_menu_label(), self._push_menu_action())
        repo.append("Pull", "win.pull")
        repo.append("Fetch", "win.fetch")
        repo.append("Remove…", "win.remove-repository")
        repo.append("View on GitHub", "win.view-on-github")
        repo.append("Open in shell", "win.open-in-shell")
        repo.append("Show in file manager", "win.open-working-directory")
        repo.append("Open in external editor", "win.open-external-editor")
        repo.append("Create issue on GitHub", "win.create-issue")
        repo.append("Repository settings…", "win.repository-settings")
        menu.append_submenu("Repository", repo)
        branch = Gio.Menu()
        branch.append("New branch…", "win.create-branch")
        branch.append("Rename…", "win.rename-branch")
        branch.append("Delete…", "win.delete-branch")
        branch.append("Discard all changes…", "win.discard-all")
        branch.append("Stash all changes…", "win.stash-all")
        branch.append(self._update_from_default_label(), "win.update-from-default")
        branch.append("Compare to branch", "win.compare-to-branch")
        branch.append("Merge into current branch…", "win.merge-branch")
        branch.append("Squash and merge…", "win.squash-merge")
        branch.append("Rebase current branch…", "win.rebase-branch")
        branch.append("Compare on GitHub", "win.compare-on-github")
        branch.append("View branch on GitHub", "win.branch-on-github")
        branch.append("Preview pull request", "win.preview-pull-request")
        branch.append(self._pull_request_menu_label(), "win.open-pull-request")
        menu.append_submenu("Branch", branch)
        help_m = Gio.Menu()
        help_m.append("Report issue…", "win.report-issue")
        help_m.append("Contact GitHub support…", "win.contact-support")
        help_m.append("Show user guides", "win.show-guides")
        help_m.append("Explore GitHub", "win.github-explore")
        help_m.append("Show keyboard shortcuts", "win.show-shortcuts")
        help_m.append("Show logs in file manager", "win.show-logs")
        help_m.append("Release notes", "win.release-notes")
        help_m.append("About GitHub Desktop", "win.about")
        menu.append_submenu("Help", help_m)
        return menu

    def _selected_state(self):
        repo = self.store.selected_repository
        return self.store.state_for(repo) if repo else None

    def _push_menu_label(self) -> str:
        if self.store.current_branch_force_push_state() == ForcePushBranchState.RECOMMENDED:
            confirm = self.store.settings.confirm_force_push or self.store.settings.ask_for_confirmation_on_force_push
            return "Force push…" if confirm else "Force push"
        return "Push"

    def _push_menu_action(self) -> str:
        if self.store.current_branch_force_push_state() == ForcePushBranchState.RECOMMENDED:
            return "win.force-push"
        return "win.push"

    def _pull_request_menu_label(self) -> str:
        state = self._selected_state()
        if state and state.current_pull_request:
            return "View pull request on GitHub"
        return "Create pull request"

    def _stash_menu_label(self) -> str:
        state = self._selected_state()
        if state and state.stashed_visible:
            return "Hide stashed changes"
        return "Show stashed changes"

    def _update_from_default_label(self) -> str:
        repo = self.store.selected_repository
        name = self.store.default_branch_name(repo) if repo else None
        return f"Update from {name or self.store.settings.default_branch or 'default branch'}"

    def _rebuild_app_menu(self) -> None:
        if not hasattr(self, "_menu_btn"):
            return
        state = self._selected_state()
        sig = (
            self._push_menu_label(),
            self._pull_request_menu_label(),
            self._stash_menu_label(),
            self._update_from_default_label(),
            bool(state and state.current_pull_request),
        )
        if getattr(self, "_menu_sig", None) == sig:
            return
        self._menu_sig = sig
        self._menu_btn.set_menu_model(self._app_menu())

    def _build_repo_list(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        search = Gtk.SearchEntry()
        search.set_placeholder_text("Filter repositories")
        box.append(search)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._repo_list = Gtk.ListBox()
        self._repo_list.add_css_class("navigation-sidebar")
        scroller.set_child(self._repo_list)
        box.append(scroller)
        self._repo_filter = search
        search.connect("search-changed", lambda *_: self._refresh_repo_list())
        add_box = Gtk.Box(spacing=6)
        for label, action in (("Add", "win.add-local-repository"), ("Clone", "win.clone-repository"), ("New", "win.new-repository")):
            b = Gtk.Button(label=label)
            b.set_action_name(action)
            add_box.append(b)
        box.append(add_box)
        return box

    def _build_changes(self) -> Gtk.Widget:
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(280, -1)
        self._filter = Gtk.SearchEntry()
        self._filter.set_placeholder_text("Filter changed files")
        self._filter.connect("search-changed", self._on_changes_filter_text)
        left.append(self._filter)
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
        left.append(chips)
        tools = Gtk.Box(spacing=6)
        self._include_all = Gtk.CheckButton(label="Include all")
        self._include_all.connect("toggled", self._on_include_all)
        tools.append(self._include_all)
        ignore_ws = Gtk.CheckButton(label="Hide whitespace")
        ignore_ws.connect("toggled", self._on_hide_ws)
        tools.append(ignore_ws)
        self._side_toggle = Gtk.CheckButton(label="Side-by-side")
        self._side_toggle.connect("toggled", self._on_side_by_side)
        tools.append(self._side_toggle)
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
        self._summary.set_max_length(72)
        self._summary.set_hexpand(True)
        summary_row.append(self._summary)
        self._issue_store = Gtk.ListStore(str)
        completion = Gtk.EntryCompletion()
        completion.set_model(self._issue_store)
        completion.set_text_column(0)
        completion.set_popup_completion(True)
        completion.set_minimum_key_length(1)
        completion.set_match_func(lambda *_args: True)
        self._summary.connect("changed", self._on_summary_changed)
        self._summary_warn = Gtk.Label(xalign=0)
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
        self._description.get_buffer().connect("changed", lambda *_: (self._flush_commit_form(), self._update_commit_warnings()))
        co = Gtk.CheckButton(label="Co-authors")
        co.connect("toggled", self._on_coauthors)
        self._coauthor_check = co
        self._author_input = AuthorInput(on_changed=self._on_authors_changed)
        self._author_input.set_visible(False)
        self._coauthor_entry = self._author_input.entry
        self._coauthor_store = self._author_input.store
        self._summary.set_completion(completion)
        self._spell = attach_spellcheck(self._description, enabled=self.store.settings.spellcheck_enabled)
        btn_row = Gtk.Box(spacing=6)
        self._commit_btn = Gtk.Button(label="Commit to branch")
        self._commit_btn.add_css_class("suggested-action")
        self._commit_btn.connect("clicked", self._on_commit)
        gen = Gtk.Button(icon_name="emoji-objects-symbolic")
        gen.set_tooltip_text("Generate commit message with Copilot")
        gen.set_action_name("win.generate-commit-message")
        undo = Gtk.Button(label="Undo")
        undo.set_action_name("win.undo-commit")
        self._amend_btn = Gtk.Button(label="Amend")
        self._amend_btn.connect("clicked", self._on_amend)
        self._stop_amend_btn = Gtk.Button(label="Stop amending")
        self._stop_amend_btn.set_visible(False)
        self._stop_amend_btn.connect("clicked", self._on_stop_amend)
        btn_row.append(self._commit_btn)
        btn_row.append(gen)
        btn_row.append(undo)
        btn_row.append(self._amend_btn)
        btn_row.append(self._stop_amend_btn)
        commit_box.append(summary_row)
        self._copilot_hint = Gtk.Label(label="Generated by Copilot", xalign=0)
        self._copilot_hint.add_css_class("dim-label")
        self._copilot_hint.set_visible(False)
        commit_box.append(self._summary_warn)
        commit_box.append(self._author_warn)
        commit_box.append(self._rules_box)
        commit_box.append(self._copilot_hint)
        commit_box.append(self._description)
        commit_box.append(co)
        commit_box.append(self._author_input)
        commit_box.append(btn_row)
        self._conflict_bar = Gtk.Box(spacing=6)
        commit_box.append(self._conflict_bar)
        left.append(commit_box)
        paned.set_start_child(left)
        self._changes_paned = paned
        try:
            paned.set_position(max(220, int(self.store.settings.sidebar_width or 320)))
        except Exception:
            pass
        self._diff_view = DiffViewer(
            interactive=True,
            on_line_toggle=self._on_line_toggle,
            on_hunk_toggle=self._on_hunk_toggle,
            on_discard_selection=self._on_discard_selection,
            on_expand_hunk=self._on_expand_hunk,
            on_expand_whole=self._on_expand_diff,
            on_collapse=self._on_collapse_diff,
            on_image_mode=self._on_image_mode,
            on_open_submodule=self._open_submodule,
            on_open_binary=self._open_binary_file,
            on_hide_whitespace_changed=self._set_hide_whitespace,
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
        )
        self._changes_stack.add_named(paned, "working")
        self._changes_stack.add_named(self._stash_viewer, "stash")
        return self._changes_stack

    def _build_history(self) -> Gtk.Widget:
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(300, -1)
        compare_row = Gtk.Box(spacing=6)
        compare_row.append(Gtk.Label(label="Compare to"))
        compare_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        compare_col.set_hexpand(True)
        self._compare_search = Gtk.SearchEntry()
        self._compare_search.set_placeholder_text("Filter branches")
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
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.connect("edge-reached", self._on_history_edge)
        self._commit_list = Gtk.ListBox()
        self._commit_list.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self._commit_list.connect("row-selected", self._on_commit_selected)
        scroller.set_child(self._commit_list)
        left.append(scroller)
        paned.set_start_child(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._commit_summary = ExpandableCommitSummary()
        right.append(self._commit_summary)
        self._commit_header = self._commit_summary
        self._hist_files = Gtk.ListBox()
        self._hist_files.connect("row-activated", self._on_hist_file)
        files_scroll = Gtk.ScrolledWindow()
        files_scroll.set_min_content_height(120)
        files_scroll.set_child(self._hist_files)
        right.append(files_scroll)
        self._hist_diff_view = DiffViewer(
            interactive=False,
            on_expand_hunk=self._on_expand_hunk,
            on_expand_whole=self._on_expand_diff,
            on_collapse=self._on_collapse_diff,
            on_open_submodule=self._open_submodule,
            on_open_binary=self._open_binary_file,
        )
        right.append(self._hist_diff_view)
        paned.set_end_child(right)
        self._history_paned = paned
        try:
            paned.set_position(max(220, int(self.store.settings.commit_summary_width or 360)))
        except Exception:
            pass
        return paned

    def _on_view_changed(self, *_args: object) -> None:
        name = self._view_stack.get_visible_child_name()
        if name == "history":
            self.store.set_section(RepositorySectionTab.HISTORY)
        else:
            self.store.set_section(RepositorySectionTab.CHANGES)

    def _refresh_repo(self) -> None:
        repo = self.store.selected_repository
        if repo is None:
            if self.store.cloning:
                self._repo_btn.set_label(f"Cloning {self.store.cloning[0].url}…")
            return
        self._repo_btn.set_label(repo.display_name)
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
        branch = state.status.current_branch if state.status else "detached"
        self._branch_btn.set_label(branch or "detached HEAD")
        default_name = self.store.default_branch_name(repo)
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
            is_on_default_branch=bool(current_branch and default_name and current_branch == default_name),
            prs_loading=bool(state.loading),
        )
        if hasattr(self, "_filter_bar"):
            self._filter_bar.set_visible(self.store.settings.show_changes_filter)
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
        if hasattr(self, "_side_toggle"):
            self._building = True
            self._side_toggle.set_active(state.side_by_side or self.store.settings.show_side_by_side_diff)
            self._building = False
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
        if not kind:
            self._push_btn.set_sensitive(True)
            if hasattr(self, "_push_menu_btn"):
                self._push_menu_btn.set_sensitive(True)
            repo = self.store.selected_repository
            if repo:
                self._update_push_label(self.store.state_for(repo))
            if self.store.cloning:
                c = self.store.cloning[0]
                pct = int((c.progress or 0) * 100)
                self._repo_btn.set_label(f"Cloning {c.url}… {pct}%" if pct else f"Cloning {c.url}…")
            return
        title = self.store.progress_title or kind.title()
        pct = int(self.store.progress_value * 100)
        if len(title) > 42:
            title = title[:39] + "…"
        if pct:
            self._set_push_chrome(f"{title} {pct}%", None, sensitive=False, spinning=True)
        else:
            self._set_push_chrome(title, None, sensitive=False, spinning=True)
        if hasattr(self, "_push_menu_btn"):
            self._push_menu_btn.set_sensitive(False)
            self._push_menu_btn.set_visible(False)
        if kind == "clone" and self.store.cloning:
            c = self.store.cloning[0]
            self._repo_btn.set_label(f"Cloning {c.url}… {pct}%" if pct else f"Cloning {c.url}…")

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
        menu = Gio.Menu()
        name = remote or "origin"
        for item in items:
            if item == "fetch":
                menu.append(f"Fetch {name}", "win.fetch")
            elif item == "force-push":
                menu.append(f"Force push {name}", "win.force-push")
        self._push_menu_btn.set_menu_model(menu)
        self._push_menu_btn.set_visible(bool(items))

    def _set_push_chrome(
        self,
        label: str,
        subtitle: str | None,
        *,
        sensitive: bool = True,
        icon: str | None = None,
        spinning: bool = False,
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

    def _update_push_label(self, state) -> None:
        if self.store.progress_kind:
            self._update_network_progress()
            return
        status = state.status
        fetched = format_last_fetched(getattr(state, "last_fetched", None))
        self._push_btn.set_tooltip_text(fetched)
        if hasattr(self, "_push_menu_btn"):
            self._push_menu_btn.set_tooltip_text(fetched)
        if not status:
            self._set_push_chrome("Fetch origin", fetched, sensitive=True, icon="view-refresh-symbolic")
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
        )
        self._set_push_chrome(
            presentation.label,
            fetched,
            sensitive=presentation.sensitive,
            icon=presentation.icon,
        )
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
            self.store.show_popup(PopupType.CONFIRM_FORCE_PUSH)
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
        needle = self._repo_filter.get_text().lower() if hasattr(self, "_repo_filter") else ""
        while True:
            row = self._repo_list.get_first_child()
            if row is None:
                break
            self._repo_list.remove(row)
        github = [r for r in self.store.repositories if r.github]
        other = [r for r in self.store.repositories if not r.github]

        def add_group(title: str, repos) -> None:
            if not repos:
                return
            header = Gtk.ListBoxRow()
            header.set_selectable(False)
            header.set_activatable(False)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("heading")
            header.set_child(label)
            self._repo_list.append(header)
            for repo in repos:
                if needle and needle not in repo.display_name.lower() and needle not in repo.path.lower():
                    continue
                row = Adw.ActionRow(title=repo.display_name, subtitle=repo.path)
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

        add_group("GitHub", github)
        add_group("Other", other)
        for cloning in self.store.cloning:
            pct = int((cloning.progress or 0) * 100)
            title = f"Cloning… {pct}%" if pct else "Cloning…"
            subtitle = cloning.description or cloning.url
            row = Adw.ActionRow(title=title, subtitle=subtitle)
            cancel = Gtk.Button(label="Cancel clone")
            cancel.set_valign(Gtk.Align.CENTER)
            cancel.connect("clicked", lambda *_a, cid=cloning.id: self.store.abort_clone(cid))
            row.add_suffix(cancel)
            self._repo_list.append(row)

    def _refresh_files(self) -> None:
        repo = self.store.selected_repository
        if not repo or not hasattr(self, "_file_list"):
            return
        state = self.store.state_for(repo)
        from ..filter_changes import (
            file_list_filter_state_from_view,
            filter_changed_files,
            get_no_results_message,
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
        files = filter_changed_files(all_files, filters)
        clear_box(self._file_list)
        if not all_files and hasattr(self, "_changes_pages"):
            self._changes_pages.set_visible_child_name("suggested")
            self._populate_suggested_actions(state)
        else:
            if hasattr(self, "_changes_pages"):
                self._changes_pages.set_visible_child_name("files")
            if not files:
                msg = get_no_results_message(filters) or "No matching files"
                empty = Adw.ActionRow(title=msg)
                empty.set_activatable(False)
                empty.set_selectable(False)
                self._file_list.append(empty)
            else:
                for file in files:
                    self._file_list.append(self._file_row(file))
        include_all = state.status.working_directory.include_all if state.status else True
        self._include_all.set_inconsistent(include_all is None)
        self._include_all.set_active(bool(include_all))
        self._building = False
        self._render_working_diff(state)

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
        stashes = list(state.stashes or [])
        if stashes:
            self._suggested.append(
                self._suggested_card(
                    "View your stashed changes",
                    f"You have {len(stashes[0].files) if stashes[0].files is not None else state.stash_count} change(s) in progress that you have not yet committed.",
                    "View stash",
                    lambda: self.store.toggle_stash(repo),
                    primary=True,
                )
            )
        remotes = list(state.remotes or [])
        ahead_behind = state.ahead_behind
        tags = list(state.local_tags_to_push or [])
        if not remotes:
            self._suggested.append(
                self._suggested_card(
                    "Publish your repository to GitHub",
                    "This repository is currently only available on your local machine. By publishing it on GitHub you can share it, and collaborate with others.",
                    "Publish repository",
                    lambda: self.store.show_popup(PopupType.PUBLISH_REPOSITORY),
                    primary=True,
                )
            )
        elif ahead_behind is None:
            self._suggested.append(
                self._suggested_card(
                    "Publish your branch to GitHub",
                    "The current branch is only on this computer. Publish it to back it up and open a pull request.",
                    "Publish branch",
                    lambda: self.store.push_repo(repo),
                    primary=True,
                )
            )
        elif ahead_behind.behind > 0:
            self._suggested.append(
                self._suggested_card(
                    "Pull from the remote",
                    f"Your branch is behind by {ahead_behind.behind} commit(s). Pull to integrate the latest work.",
                    "Pull",
                    lambda: self.store.pull_repo(repo),
                    primary=True,
                )
            )
        elif ahead_behind.ahead > 0 or tags:
            extra = f" and {len(tags)} tag(s)" if tags else ""
            self._suggested.append(
                self._suggested_card(
                    "Push your commits to GitHub",
                    f"You have {ahead_behind.ahead} local commit(s){extra} ready to push.",
                    "Push",
                    lambda: self.store.push_repo(repo),
                    primary=True,
                )
            )
        elif repo.github and not state.current_pull_request:
            current = state.status.current_branch if state.status else None
            default = self.store.default_branch_name(repo)
            if current and current != default:
                action = self.store.settings.pull_request_suggested_next_action
                if action == PullRequestSuggestedNextAction.PREVIEW_PULL_REQUEST.value:
                    self._suggested.append(
                        self._suggested_pr_card(
                            "Preview the pull request from your current branch",
                            f"The current branch ({current}) is already published to GitHub. Preview the changes this pull request will have before proposing your changes.",
                            "Preview pull request",
                            lambda: self.store.preview_pull_request(repo),
                        )
                    )
                else:
                    self._suggested.append(
                        self._suggested_pr_card(
                            "Create a pull request from your current branch",
                            f"The current branch ({current}) is already published to GitHub. Create a pull request to propose and collaborate on your changes.",
                            "Create pull request",
                            lambda: self.store.open_pull_request(repo),
                        )
                    )
        self._suggested.append(
            self._suggested_card(
                "Open the repository in your external editor",
                "Select your editor in Preferences → Integrations.",
                "Open in editor",
                lambda: self.store.open_in_editor(repo),
            )
        )
        self._suggested.append(
            self._suggested_card(
                "View the files of your repository in your File Manager",
                "Always available from the Repository menu.",
                "Show in file manager",
                lambda: self.store.open_working_directory(repo),
            )
        )
        if repo.github:
            self._suggested.append(
                self._suggested_card(
                    "Open the repository page on GitHub in your browser",
                    "Always available from the Repository menu.",
                    "View on GitHub",
                    lambda: self.store.view_on_github(repo),
                )
            )

    def _suggested_card(self, title: str, description: str, button: str, callback, *, primary: bool = False) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.add_css_class("suggested-action-card")
        heading = Gtk.Label(label=title, xalign=0, wrap=True)
        heading.add_css_class("heading")
        body = Gtk.Label(label=description, xalign=0, wrap=True)
        body.add_css_class("dim-label")
        btn = Gtk.Button(label=button, halign=Gtk.Align.START)
        if primary:
            btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: callback())
        box.append(heading)
        box.append(body)
        box.append(btn)
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
        check.set_active(kind != DiffSelectionType.NONE)
        check.set_inconsistent(kind == DiffSelectionType.PARTIAL)
        check.connect("toggled", lambda btn, p=file.path: self._toggle_file(p, btn.get_active()))
        label = Gtk.Label(label=file.path, xalign=0, hexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        badge = Gtk.Label(label=file.status.kind.value)
        badge.add_css_class(STATUS_CLASS.get(file.status.kind, ""))
        box.append(check)
        box.append(label)
        box.append(badge)
        if file.status.is_conflicted:
            ours = Gtk.Button(label="Ours")
            theirs = Gtk.Button(label="Theirs")
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
        if self._building:
            return
        repo = self.store.selected_repository
        if repo:
            self.store.set_include_all(repo, btn.get_active())

    def _on_hide_ws(self, btn: Gtk.CheckButton) -> None:
        self._set_hide_whitespace(btn.get_active())

    def _set_hide_whitespace(self, hidden: bool) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        state.hide_whitespace = hidden
        if state.selected_file:
            self.store.select_file(repo, state.selected_file)

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
            self._summary.set_text("")
            self._description.get_buffer().set_text("")
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
            return
        self._building = True
        clear_box(self._commit_list)
        for commit in commits:
            self._commit_list.append(self._commit_row(commit))
        self._history_shas = new_shas
        self._refresh_compare_cta(state)
        self._building = False

    def _commit_row(self, commit) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("history-commit")
        box = Gtk.Box(spacing=8)
        box.append(AvatarStack(users_from_commit(commit), size=28))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.set_hexpand(True)
        from .emoji import expand_shortcodes

        has_empty_summary = not (commit.summary or "").strip()
        summary_text = "Empty commit message" if has_empty_summary else expand_shortcodes(commit.summary)
        summary = Gtk.Label(label=summary_text, xalign=0)
        summary.add_css_class("commit-summary")
        if has_empty_summary:
            summary.add_css_class("empty-summary")
        attribution = format_commit_attribution(commit)
        relative = format_commit_relative_time(commit.author.date)
        byline = Gtk.Label(label=f"{attribution} • {relative}", xalign=0)
        byline.add_css_class("commit-sha")
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
        repo = self.store.selected_repository
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
        row.set_tooltip_text(commit.sha)
        attach_right_click(row, lambda *_ , r=row: self._commit_item_menu(r))
        self._install_commit_dnd(row, commit)
        return row

    def _on_commit_selected(self, _l, row) -> None:
        if self._building:
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
        commit = self.store.state_for(repo).selected_commit or commit
        state = self.store.state_for(repo)
        if hasattr(self, "_commit_summary"):
            self._commit_summary.bind(
                list(state.selected_commits) or ([commit] if commit else []),
                state.changeset,
                expanded=state.commit_summary_expanded,
                shas_in_diff=list(state.shas_in_diff),
                on_unreachable=lambda: self.store.show_popup(PopupType.UNREACHABLE_COMMITS),
                on_highlight=self._highlight_history_shas,
            )
        clear_box(self._hist_files)
        for f in state.selected_commit_files:
            r = Adw.ActionRow(title=f.path, subtitle=f.status.kind.value)
            r._file = f  # type: ignore[attr-defined]
            r.set_activatable(True)
            attach_right_click(r, lambda *_ , file=f: self._hist_file_menu(file))
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
        files = list(status.working_directory.files) if status.working_directory else []
        unresolved = get_conflicted_files(files)
        can_continue = not unresolved
        continue_tooltip = (
            "Continue rebase"
            if can_continue
            else "Resolve all conflicts before continuing"
        )
        has_untracked = any(f.status.kind == AppFileStatusKind.UNTRACKED for f in files)
        if status.merge_head_found:
            self._conflict_bar.append(Gtk.Label(label="Merge in progress"))
            view = Gtk.Button(label="View conflicts")
            view.connect("clicked", lambda *_: show_conflicts_dialog(self, self.store, MultiCommitOperationKind.MERGE))
            cont = Gtk.Button(label="Commit merge")
            abort = Gtk.Button(label="Abort merge")
            cont.set_sensitive(can_continue)
            cont.set_tooltip_text(
                "Commit merge" if can_continue else "Resolve all conflicts before continuing"
            )
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.MERGE))
            abort.connect(
                "clicked",
                lambda *_: show_confirm_abort(
                    self,
                    "Merge",
                    lambda: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.MERGE),
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
            cont = Gtk.Button(label="Continue rebase")
            abort = Gtk.Button(label="Abort rebase")
            cont.set_sensitive(can_continue)
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

    def _refresh_stash_bar(self, state) -> None:
        child = self._stash_bar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._stash_bar.remove(child)
            child = nxt
        repo = self.store.selected_repository
        if not repo or not state.stashes:
            return
        label = Gtk.Label(label=f"{len(state.stashes)} stashed change{'s' if len(state.stashes) != 1 else ''}")
        view = Gtk.Button(label="View")
        view.connect("clicked", lambda *_: self.store.toggle_stash(repo) if not state.stashed_visible else None)
        restore = Gtk.Button(label="Restore")
        restore.connect("clicked", lambda *_: self.store.restore_stash(repo))
        discard = Gtk.Button(label="Discard")
        discard.connect("clicked", lambda *_: self.store.discard_stash(repo))
        self._stash_bar.append(label)
        self._stash_bar.append(view)
        self._stash_bar.append(restore)
        self._stash_bar.append(discard)

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
            hide_whitespace=state.hide_whitespace or self.store.settings.hide_whitespace_in_diffs,
            can_collapse=state.original_diff is not None,
            tab_size=self.store.settings.tab_size,
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
            hide_whitespace=state.hide_whitespace or self.store.settings.hide_whitespace_in_diffs,
            can_collapse=state.original_diff is not None,
            tab_size=self.store.settings.tab_size,
            comments=list(state.diff_comments),
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
            hide_whitespace=state.hide_whitespace or self.store.settings.hide_whitespace_in_diffs,
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
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        has = bool(state.status and state.status.working_directory.files)
        show_context_menu(
            self._file_list,
            [
                ("Discard all changes…", lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, discarding_all=True), has),
                ("Stash all changes…", self._stash_all, has),
            ],
        )

    def _file_item_menu(self, row: Gtk.ListBoxRow) -> None:
        repo = self.store.selected_repository
        file = getattr(row, "_file", None)
        if not repo or file is None:
            return
        selected = self._selected_change_files() or [file]
        paths = [f.path for f in selected]
        items = [
            ("Discard changes…", lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES, files=selected), True),
            None,
        ]
        if len(paths) == 1:
            items.append(("Ignore file (add to .gitignore)", lambda: self.store.ignore_path(repo, file.path), True))
            folder = "/".join(file.path.split("/")[:-1])
            if folder:
                items.append((f"Ignore folder /{folder}", lambda: self.store.ignore_path(repo, folder), True))
            ext = ""
            if "." in file.path.split("/")[-1]:
                ext = "." + file.path.split(".")[-1]
                items.append((f"Ignore all {ext} files", lambda: self.store.ignore_pattern(repo, f"*{ext}"), True))
        else:
            items.append((f"Ignore {len(paths)} selected files", lambda: [self.store.ignore_path(repo, p) for p in paths], True))
            items.append(("Include selected files", lambda: self.store.set_files_included(repo, paths, True), True))
            items.append(("Exclude selected files", lambda: self.store.set_files_included(repo, paths, False), True))
            items.append(("Copy selected paths", lambda: copy_text("\n".join(os.path.join(repo.path, p) for p in paths)), True))
        items.extend(
            [
                None,
                ("Copy path", lambda: copy_text(os.path.join(repo.path, file.path)), True),
                ("Copy relative path", lambda: copy_text(file.path), True),
                None,
                ("Show in file manager", lambda: self.store.reveal_in_file_manager(repo, file.path), file.status.kind != AppFileStatusKind.DELETED),
                ("Open in external editor", lambda: self.store.open_in_editor(repo, os.path.join(repo.path, file.path)), file.status.kind != AppFileStatusKind.DELETED),
                ("Open with default program", lambda: self.store.open_file_default(repo, file.path), file.status.kind != AppFileStatusKind.DELETED),
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

    def _hist_file_menu(self, file) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        full = os.path.join(repo.path, file.path)
        exists = os.path.exists(full)
        state = self.store.state_for(repo)
        commit = state.selected_commit
        items = [
            ("Copy path", lambda: copy_text(full), True),
            ("Copy relative path", lambda: copy_text(file.path), True),
            ("Open with default program", lambda: self.store.open_file_default(repo, file.path), exists),
            ("Show in file manager", lambda: self.store.reveal_in_file_manager(repo, file.path), exists),
            ("Open in external editor", lambda: self.store.open_in_editor(repo, full), exists),
        ]
        if repo.github and commit:
            items.append(
                (
                    "View on GitHub",
                    lambda: open_external(f"{repo.github.html_url}/blob/{commit.sha}/{file.path}"),
                    True,
                )
            )
        show_context_menu(self._hist_files, items)

    def _commit_item_menu(self, row: Gtk.ListBoxRow) -> None:
        repo = self.store.selected_repository
        commit = getattr(row, "_commit", None)
        if not repo or commit is None:
            return
        state = self.store.state_for(repo)
        selected = list(state.selected_commits) or [commit]
        is_tip = bool(state.commits and state.commits[0].sha == commit.sha)
        local = commit.sha in set(state.local_commit_shas)
        items = []
        if len(selected) > 1:
            items.extend(
                [
                    (f"Cherry-pick {len(selected)} commits…", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Cherry-pick", shas=[c.sha for c in selected]), True),
                    (f"Squash {len(selected)} commits…", lambda: self._squash_selected(selected, commit), True),
                    (f"Reorder {len(selected)} commits…", lambda: show_reorder_commits(self, self.store, selected), True),
                ]
            )
        else:
            if is_tip:
                items.append(("Amend commit…", self._on_amend, True))
                items.append(("Undo commit…", self._undo, local))
            items.extend(
                [
                    ("Reset to commit…", lambda: self.store.reset_to_commit(repo, commit), (not is_tip) and local),
                    ("Checkout commit", lambda: self.store.checkout_commit_sha(repo, commit.sha), not is_tip),
                    ("Reorder commit", lambda: show_reorder_commits(self, self.store, [commit]), True),
                    ("Revert changes in commit", lambda: self.store.revert_commit(repo, commit), True),
                    None,
                    ("Create branch from commit", lambda: self.store.show_popup(PopupType.CREATE_BRANCH, start=commit.sha), True),
                    ("Create tag…", lambda: self.store.show_popup(PopupType.CREATE_TAG, sha=commit.sha), True),
                    *[
                        (
                            f"Delete tag {name}…",
                            lambda n=name: self.store.show_popup(PopupType.DELETE_TAG, tag=n),
                            True,
                        )
                        for name in (commit.tags or [])
                    ],
                    ("Cherry-pick commit…", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Cherry-pick", shas=[commit.sha]), True),
                    None,
                    ("Copy SHA", lambda: copy_text(commit.sha), True),
                    ("Copy tags", lambda: copy_text(" ".join(commit.tags)), bool(commit.tags)),
                    ("View on GitHub", lambda: self.store.view_commit_on_github(repo, commit.sha), bool(repo.github) and not local),
                ]
            )
        show_context_menu(row, items)

    def _squash_selected(self, selected, onto) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        others = [c for c in selected if c.sha != onto.sha]
        if not others:
            return
        self.store.show_popup(
            PopupType.COMMIT_MESSAGE,
            title="Squash commits",
            summary=onto.summary,
            description=onto.body,
            button="Squash",
            on_submit=lambda summary, description: self.store.squash_onto(repo, others, onto, f"{summary}\n\n{description}".strip()),
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
                    others = [c for c in moving if c.sha != target.sha]
                    if not others:
                        return False
                    self.store.squash_onto(repo, others, target, target.summary)
                    return True
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
        ab = state.ahead_behind
        if hasattr(self, "_ahead_label"):
            if ab and (ab.ahead or ab.behind):
                self._ahead_label.set_text(f"↑{ab.ahead} ↓{ab.behind}")
            else:
                self._ahead_label.set_text("")

    def _on_checks(self, *_args: object) -> None:
        present_checks_popover(self._checks_btn, self.store)

    def _update_tutorial_banner(self, repo, state) -> None:
        if hasattr(self, "_tutorial_panel"):
            active = bool(repo.tutorial) and self.store.tutorial_step not in {
                TutorialStep.NOT_APPLICABLE,
                TutorialStep.PAUSED,
            }
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

    def _refresh_issue_completion(self, state) -> None:
        if not hasattr(self, "_issue_store"):
            return
        self._issue_store.clear()
        if hasattr(self, "_coauthor_store"):
            self._coauthor_store.clear()
            seen: set[str] = set()
            for user in getattr(state, "mentionables", None) or []:
                login = str(user.get("login") or "")
                if not login or login in seen:
                    continue
                seen.add(login)
                name = str(user.get("name") or login)
                email = str(user.get("email") or f"{login}@users.noreply.github.com")
                self._coauthor_store.append([f"{name} <{email}>"])
                self._coauthor_store.append([f"@{login}"])
            for login in state.mentions:
                if login and login not in seen:
                    self._coauthor_store.append([f"@{login}"])
        self._update_summary_completion()

    def _token_before_cursor(self, entry: Gtk.Entry) -> str:
        text = entry.get_text()
        pos = entry.get_position()
        prefix = text[:pos]
        if not prefix:
            return ""
        for index in range(len(prefix) - 1, -1, -1):
            if prefix[index] in " \t\n":
                return prefix[index + 1 :]
        return prefix

    def _update_summary_completion(self) -> None:
        if not hasattr(self, "_issue_store") or not hasattr(self, "_summary"):
            return
        repo = self.store.selected_repository
        state = self.store.state_for(repo) if repo else None
        token = self._token_before_cursor(self._summary)
        self._issue_store.clear()
        if state is None or len(token) < 1:
            return
        if token.startswith("#"):
            needle = token[1:].lower()
            for number, title in state.issues:
                hay = f"#{number} {title}"
                if not needle or needle in str(number) or needle in title.lower():
                    self._issue_store.append([hay])
        elif token.startswith("@"):
            needle = token[1:].lower()
            for login in state.mentions:
                if not needle or login.lower().startswith(needle):
                    self._issue_store.append([f"@{login}"])
        elif token.startswith(":"):
            for short in matching_shortcodes(token):
                self._issue_store.append([short])

    def _refresh_compare_list(self, state=None) -> None:
        if not hasattr(self, "_compare_list"):
            return
        repo = self.store.selected_repository
        if repo is None:
            return
        if state is None:
            state = self.store.state_for(repo)
        query = (self._compare_search.get_text() if hasattr(self, "_compare_search") else "").strip().lower()
        current_tip = state.status.current_tip if state.status else None
        current_name = state.status.current_branch if state.status else None
        while (child := self._compare_list.get_first_child()) is not None:
            self._compare_list.remove(child)
        history = Gtk.ListBoxRow()
        history.set_child(Gtk.Label(label="History", xalign=0))
        history.branch_name = ""
        self._compare_list.append(history)
        shown = 0
        for branch in state.branches:
            if branch.name == current_name:
                continue
            if query and query not in branch.name.lower():
                continue
            if shown >= 40:
                break
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.append(Gtk.Label(label=branch.name, xalign=0, hexpand=True))
            ab = self.store.ahead_behind_between(repo, current_tip, branch.tip_sha)
            if ab and (ab.ahead or ab.behind):
                counts = Gtk.Label(label=f"{ab.ahead} ahead · {ab.behind} behind")
                counts.add_css_class("ahead-behind")
                box.append(counts)
            row.set_child(box)
            row.branch_name = branch.name
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
        merge_tree = state.merge_tree
        if merge_tree and merge_tree.kind == ComputedAction.CONFLICTS:
            noun = "file" if merge_tree.conflicted_files == 1 else "files"
            warn = Gtk.Label(
                label=f"Can't automatically merge. {merge_tree.conflicted_files} conflicted {noun}.",
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            self._compare_cta.append(warn)
        elif merge_tree and merge_tree.kind == ComputedAction.INVALID:
            self._compare_cta.append(Gtk.Label(label="Unable to merge unrelated histories into this branch.", wrap=True, xalign=0))
        elif merge_tree and merge_tree.kind == ComputedAction.CLEAN and behind:
            self._compare_cta.append(Gtk.Label(label="Able to merge automatically.", xalign=0))
        if behind and repo:
            msg = Gtk.Label(
                label=f"This will merge {behind} commit{'s' if behind != 1 else ''} from {state.compare_branch.name} into {current}",
                wrap=True,
                xalign=0,
            )
            self._compare_cta.append(msg)
            ops = Gtk.Box(spacing=6)
            merge = Gtk.Button(label=f"Merge into {current}")
            merge.add_css_class("suggested-action")
            merge.set_sensitive(not (merge_tree and merge_tree.kind == ComputedAction.INVALID))
            merge.connect(
                "clicked",
                lambda *_: self.store.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind="Merge",
                    initial_branch=state.compare_branch.name,
                ),
            )
            rebase = Gtk.Button(label="Rebase")
            rebase.connect(
                "clicked",
                lambda *_: self.store.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind="Rebase",
                    initial_branch=state.compare_branch.name,
                ),
            )
            squash = Gtk.Button(label="Squash")
            squash.connect(
                "clicked",
                lambda *_: self.store.show_popup(
                    PopupType.MULTI_COMMIT_OPERATION,
                    kind="Squash",
                    initial_branch=state.compare_branch.name,
                ),
            )
            ops.append(merge)
            ops.append(rebase)
            ops.append(squash)
            self._compare_cta.append(ops)

    def _repo_list_menu(self, widget: Gtk.Widget, repo) -> None:
        show_context_menu(
            widget,
            [
                ("Change alias…", lambda: (self.store.select_repository(repo.id), self.store.show_popup(PopupType.CHANGE_REPOSITORY_ALIAS)), True),
                ("Copy path", lambda: copy_text(repo.path), True),
                ("View on GitHub", lambda: self.store.view_on_github(repo), bool(repo.github)),
                ("Open in shell", lambda: self.store.open_in_shell(repo), True),
                ("Show in file manager", lambda: self.store.reveal_in_file_manager(repo, ""), True),
                ("Open in external editor", lambda: self.store.open_in_editor(repo, repo.path), True),
                None,
                ("Remove…", lambda: (self.store.select_repository(repo.id), self.store.show_popup(PopupType.REMOVE_REPOSITORY)), True),
            ],
        )

    def _refresh_author_avatar(self, repo) -> None:
        if not hasattr(self, "_author_avatar_host"):
            return
        from ..email import is_attributable_email_for, lookup_preferred_email
        from ..git.ops import get_author_identity

        name, email = get_author_identity(repo.path)
        account = self.store.account_for_repo(repo)
        clear_box(self._author_avatar_host)
        avatar = Avatar(name or (account.login if account else "Git"), email or "", login=account.login if account else None, avatar_url=account.avatar_url if account else None, size=28)
        self._author_avatar_host.append(avatar)
        misattributed = bool(account and email and not is_attributable_email_for(account, email))
        self._author_btn.remove_css_class("author-warning")
        if misattributed:
            self._author_btn.add_css_class("author-warning")
            self._author_warn.set_text("This email address doesn't match your GitHub account. Commits may not be attributed to you.")
            self._author_warn.set_visible(True)
        else:
            self._author_warn.set_visible(False)
        self._author_btn.set_tooltip_text(f"{name or 'Unknown'} <{email or 'no email'}>")
        clear_box(self._author_popover_box)
        heading = Gtk.Label(label="Commit author", xalign=0)
        heading.add_css_class("heading")
        self._author_popover_box.append(heading)
        self._author_popover_box.append(Gtk.Label(label=f"{name or ''} <{email or ''}>", xalign=0, wrap=True))
        if misattributed:
            warn = Gtk.Label(
                label="This commit may not be attributed to your GitHub account. Choose an email below or update Git config.",
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            self._author_popover_box.append(warn)
        emails = list(account.emails) if account else []
        if account:
            preferred = lookup_preferred_email(account)
            if preferred not in emails:
                emails.insert(0, preferred)
        for item in emails:
            btn = Gtk.Button(label=item)
            btn.add_css_class("flat")
            btn.connect("clicked", lambda _b, addr=item: self._use_author_email(repo, addr))
            self._author_popover_box.append(btn)
        git_btn = Gtk.Button(label="Open Git settings")
        git_btn.connect("clicked", lambda *_: (self._author_popover.popdown(), show_preferences(self, self.store)))
        self._author_popover_box.append(git_btn)
        repo_btn = Gtk.Button(label="Open repository Git config")
        repo_btn.connect("clicked", lambda *_: (self._author_popover.popdown(), self.store.show_popup(PopupType.REPOSITORY_SETTINGS)))
        self._author_popover_box.append(repo_btn)

    def _use_author_email(self, repo, email: str) -> None:
        self.store.set_commit_author_email(repo, email, local=True)
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
        if self.store.settings.show_commit_length_warning and len(text) > 50:
            self._summary_warn.set_text(f"{len(text)} / 72 characters — keep the summary short")
            self._summary_warn.set_visible(True)
        else:
            self._summary_warn.set_visible(False)
        if not hasattr(self, "_rules_warn"):
            return
        repo = self.store.selected_repository

        def hide_rules() -> None:
            self._rules_warn.set_visible(False)
            if hasattr(self, "_rules_link"):
                self._rules_link.set_visible(False)
            if hasattr(self, "_rules_box"):
                self._rules_box.set_visible(False)

        if not repo:
            hide_rules()
            if hasattr(self, "_commit_btn"):
                self._commit_btn.set_sensitive(True)
            return
        from ..github.repo_rules import commit_rule_warnings, rulesets_url_for_branch, use_repo_rules_logic
        from ..git.ops import get_author_identity

        state = self.store.state_for(repo)
        if not use_repo_rules_logic(self.store.account_for_repo(repo), repo):
            hide_rules()
            if hasattr(self, "_commit_btn"):
                self._commit_btn.set_sensitive(True)
            return
        start, end = self._description.get_buffer().get_bounds()
        description = self._description.get_buffer().get_text(start, end, True).strip()
        message = "\n\n".join(part for part in (text.strip(), description) if part)
        _name, email = get_author_identity(repo.path)
        unpublished = state.ahead_behind is None
        warnings, hard = commit_rule_warnings(
            state.repo_rules,
            message=message,
            author_email=email,
            branch=state.status.current_branch if state.status else None,
            ahead_behind=state.ahead_behind,
            unpublished=unpublished,
        )
        if state.commit_to_amend is not None:
            warnings.insert(
                0,
                "Your changes will modify your most recent commit. Stop amending to make these changes as a new commit.",
            )
        branch = state.status.current_branch if state.status else None
        if repo.github and repo.github.permissions == "read":
            warnings.insert(0, f"You don't have write access to {repo.name}. Want to create a fork?")
        elif branch and branch in (state.protected_branches or []):
            warnings.insert(0, f"{branch} is a protected branch. Want to switch branches?")
        if warnings:
            self._rules_warn.set_text("\n".join(warnings))
            self._rules_warn.set_visible(True)
            if hasattr(self, "_rules_box"):
                self._rules_box.set_visible(True)
            uri = rulesets_url_for_branch(repo.github, branch)
            if hasattr(self, "_rules_link"):
                if uri:
                    self._rules_link.set_uri(uri)
                    self._rules_link.set_visible(True)
                else:
                    self._rules_link.set_visible(False)
        else:
            hide_rules()
        if hasattr(self, "_commit_btn"):
            self._commit_btn.set_sensitive(not hard)

    def _generate_commit_message(self) -> None:
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

    def _edit_action(self, action: str) -> None:
        widget = self.get_focus()
        if widget is None:
            return
        clipboard = self.get_clipboard()
        if action in {"undo", "redo"}:
            self._edit_undo_redo(widget, redo=action == "redo")
            return
        if isinstance(widget, Gtk.Editable):
            if action == "cut":
                widget.cut_clipboard()
            elif action == "copy":
                widget.copy_clipboard()
            elif action == "paste":
                widget.paste_clipboard()
            elif action == "select-all":
                widget.select_region(0, -1)
            return
        if isinstance(widget, Gtk.TextView):
            buf = widget.get_buffer()
            bounds = buf.get_selection_bounds()
            if isinstance(bounds, tuple) and len(bounds) == 3:
                has_sel, start, end = bounds
            elif isinstance(bounds, tuple) and len(bounds) == 2:
                has_sel, start, end = True, bounds[0], bounds[1]
            else:
                has_sel, start, end = False, None, None
            if action == "copy" and has_sel:
                clipboard.set(buf.get_text(start, end, True))
            elif action == "cut" and has_sel:
                clipboard.set(buf.get_text(start, end, True))
                buf.delete(start, end)
            elif action == "paste":
                def _paste(_c, result) -> None:
                    try:
                        text = clipboard.read_text_finish(result)
                    except Exception:
                        return
                    if text:
                        buf.insert_at_cursor(text)

                clipboard.read_text_async(None, _paste)
            elif action == "select-all":
                buf.select_range(buf.get_start_iter(), buf.get_end_iter())

    def _edit_undo_redo(self, widget, *, redo: bool) -> None:
        """Undo/redo the focused text field. Never undoes a Git commit (Desktop Edit → Undo)."""
        current = widget
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, Gtk.TextView):
                buf = current.get_buffer()
                try:
                    buf.set_enable_undo(True)
                except Exception:
                    pass
                try:
                    if redo:
                        if buf.get_can_redo():
                            buf.redo()
                    elif buf.get_can_undo():
                        buf.undo()
                except Exception:
                    pass
                return
            delegate = getattr(current, "get_delegate", None)
            inner = delegate() if callable(delegate) else None
            if inner is not None and inner is not current and hasattr(inner, "undo"):
                current = inner
                continue
            if hasattr(current, "undo") and hasattr(current, "get_can_undo"):
                try:
                    if redo:
                        if current.get_can_redo():
                            current.redo()
                    elif current.get_can_undo():
                        current.undo()
                except Exception:
                    pass
                return
            current = current.get_parent() if hasattr(current, "get_parent") else None

    def _nudge_paned(self, delta: int) -> None:
        paned = None
        if hasattr(self, "_view_stack") and self._view_stack.get_visible_child_name() == "history":
            paned = getattr(self, "_history_paned", None)
        else:
            paned = getattr(self, "_changes_paned", None)
        if paned is None:
            return
        pos = paned.get_position()
        paned.set_position(max(180, min(720, pos + delta)))

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
                        ("Increase active resizable", "<Control>9"),
                        ("Decrease active resizable", "<Control>8"),
                    ],
                ),
                (
                    "Repository",
                    [
                        ("Push", "<Control>p"),
                        ("Pull", "<Control><Shift>p"),
                        ("Fetch", "<Control><Shift>t"),
                        ("Open in shell", "<Control>grave"),
                        ("Show in file manager", "<Control><Shift>f"),
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

