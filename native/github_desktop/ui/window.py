"""Main GitHub Desktop window (Adwaita)."""

from __future__ import annotations

import os
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from ..git.ops import (
    abort_cherry_pick,
    abort_merge,
    abort_rebase,
    append_ignore_rule,
    checkout_branch,
    continue_cherry_pick,
    continue_rebase,
    create_merge_commit,
    get_commit_diff,
    get_working_directory_diff,
    merge,
    rebase,
    revert,
    squash_commits,
    stash_pop,
    undo_commit,
)
from ..models import (
    AppFileStatusKind,
    ApplicationTheme,
    BannerType,
    BranchType,
    DiffLineType,
    DiffType,
    FileDiff,
    HistoryTabMode,
    ImageDiff,
    MergeResult,
    MultiCommitOperationKind,
    PopupType,
    RebaseResult,
    RepositorySectionTab,
    TextDiff,
    WelcomeStep,
    WorkingDirectoryFileChange,
)
from ..shells import open_external
from ..store import AppStore
from ..version import APP_NAME
from .dialogs import present_popup, show_preferences


STATUS_CLASS = {
    AppFileStatusKind.NEW: "file-status-new",
    AppFileStatusKind.UNTRACKED: "file-status-new",
    AppFileStatusKind.MODIFIED: "file-status-modified",
    AppFileStatusKind.DELETED: "file-status-deleted",
    AppFileStatusKind.RENAMED: "file-status-renamed",
    AppFileStatusKind.COPIED: "file-status-renamed",
    AppFileStatusKind.CONFLICTED: "file-status-conflicted",
}


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application, store: AppStore) -> None:
        super().__init__(application=app, title=APP_NAME)
        self.store = store
        self.set_default_size(store.settings.window_width, store.settings.window_height)
        self._building = False
        self._toast = Adw.ToastOverlay()
        self.set_content(self._toast)
        self._root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._toast.set_child(self._root)
        self._banner = Adw.Banner()
        self._banner.set_revealed(False)
        self._banner.connect("button-clicked", lambda *_: self.store.clear_banner())
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
        self.store.subscribe(self._on_store)
        self.connect("close-request", self._on_close)
        self._on_store()

    def _on_close(self, *_args: object) -> bool:
        alloc = self.get_width(), self.get_height()
        if alloc[0] > 0:
            self.store.settings.window_width = alloc[0]
            self.store.settings.window_height = alloc[1]
            self.store.persist_settings()
        return False

    def _on_store(self) -> None:
        if self.store.welcome_step is not None:
            self._refresh_welcome()
            self._stack.set_visible_child_name("welcome")
        elif not self.store.repositories and not self.store.cloning:
            self._stack.set_visible_child_name("empty")
        else:
            self._stack.set_visible_child_name("repo")
            self._refresh_repo()
        if self.store.banner:
            self._banner.set_title(self._banner_text(self.store.banner.type, self.store.banner))
            self._banner.set_button_label("Dismiss")
            self._banner.set_revealed(True)
        else:
            self._banner.set_revealed(False)
        popup = self.store.popup
        if popup:
            current = popup
            self.store.popup = None
            present_popup(self, self.store, current.type, current.payload)

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
        }
        return mapping.get(kind, kind.value)

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
        add("show-branches", lambda: self._branch_btn.popup() if hasattr(self, "_branch_btn") else None)
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
        add("delete-branch", lambda: self.store.show_popup(PopupType.DELETE_BRANCH))
        add("discard-all", lambda: self.store.show_popup(PopupType.CONFIRM_DISCARD_CHANGES))
        add("stash-all", self._stash_all)
        add("merge-branch", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Merge"))
        add("squash-merge", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Squash"))
        add("rebase-branch", lambda: self.store.show_popup(PopupType.MULTI_COMMIT_OPERATION, kind="Rebase"))
        add("compare-on-github", lambda: self._repo_op(self.store.compare_on_github))
        add("open-pull-request", lambda: self._repo_op(self.store.open_pull_request))
        add("preview-pull-request", lambda: self.store.show_popup(PopupType.START_PULL_REQUEST))
        add("about", lambda: self.store.show_popup(PopupType.ABOUT))
        add("show-logs", self._show_logs)
        add("find", lambda: self._filter.grab_focus() if hasattr(self, "_filter") else None)
        add("toggle-stash", self._toggle_stash)
        add("undo-commit", self._undo)
        add("create-tag", lambda: self.store.show_popup(PopupType.CREATE_TAG))
        add("generate-commit-message", lambda: self.store.show_popup(PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER))
        add("compare-to-branch", lambda: self.store.set_section(RepositorySectionTab.HISTORY))

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
            "<Ctrl>z": "undo-commit",
            "<Alt>p": "preview-pull-request",
        }
        for accel, name in ctrl.items():
            self.get_application().set_accels_for_action(f"win.{name}", [accel])

    def _repo_op(self, fn) -> None:
        repo = self.store.selected_repository
        if repo:
            fn(repo)

    def _show_logs(self) -> None:
        from ..paths import log_dir

        open_external(str(log_dir()))

    def _stash_all(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        from ..git.ops import stash_push

        state = self.store.state_for(repo)
        stash_push(repo.path, state.status.current_branch if state.status else "unknown")
        self.store.refresh_repository(repo)

    def _toggle_stash(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        state.stashed_visible = not state.stashed_visible
        self.store.emit()

    def _undo(self) -> None:
        repo = self.store.selected_repository
        if repo:
            if self.store.settings.confirm_undo_commit:
                self.store.show_popup(PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO)
            else:
                undo_commit(repo.path)
                self.store.refresh_repository(repo)

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
        tutorial.connect("clicked", lambda *_: self.store.show_popup(PopupType.CREATE_TUTORIAL_REPOSITORY))
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

        self._branch_btn = Gtk.MenuButton(icon_name="view-list-symbolic")
        self._branch_btn.set_always_show_arrow(True)
        header.pack_start(self._branch_btn)

        self._push_btn = Gtk.Button(label="Fetch origin")
        self._push_btn.connect("clicked", self._on_push_pull)
        header.pack_end(self._push_btn)

        pr_btn = Gtk.Button(icon_name="network-transmit-receive-symbolic")
        pr_btn.set_tooltip_text("Create or view pull request")
        pr_btn.set_action_name("win.open-pull-request")
        header.pack_end(pr_btn)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic")
        menu_btn.set_menu_model(self._app_menu())
        header.pack_end(menu_btn)

        switcher = Adw.ViewSwitcher()
        self._view_stack = Adw.ViewStack()
        switcher.set_stack(self._view_stack)
        header.set_title_widget(switcher)
        toolbar.add_top_bar(header)

        self._changes_page = self._build_changes()
        self._history_page = self._build_history()
        self._view_stack.add_titled_with_icon(self._changes_page, "changes", "Changes", "document-edit-symbolic")
        self._view_stack.add_titled_with_icon(self._history_page, "history", "History", "view-list-symbolic")
        self._view_stack.connect("notify::visible-child-name", self._on_view_changed)
        toolbar.set_content(self._view_stack)
        self._split.set_content(toolbar)
        return self._split

    def _app_menu(self) -> Gio.Menu:
        menu = Gio.Menu()
        file_m = Gio.Menu()
        file_m.append("New repository…", "win.new-repository")
        file_m.append("Add local repository…", "win.add-local-repository")
        file_m.append("Clone repository…", "win.clone-repository")
        file_m.append("Options…", "win.preferences")
        file_m.append("Quit", "app.quit")
        menu.append_submenu("File", file_m)
        view = Gio.Menu()
        view.append("Changes", "win.show-changes")
        view.append("History", "win.show-history")
        view.append("Repository list", "win.choose-repository")
        view.append("Branches list", "win.show-branches")
        view.append("Go to summary", "win.go-to-commit-message")
        view.append("Show stashed changes", "win.toggle-stash")
        menu.append_submenu("View", view)
        repo = Gio.Menu()
        repo.append("Push", "win.push")
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
        branch.append("Merge into current branch…", "win.merge-branch")
        branch.append("Squash and merge…", "win.squash-merge")
        branch.append("Rebase current branch…", "win.rebase-branch")
        branch.append("Compare on GitHub", "win.compare-on-github")
        branch.append("Preview pull request", "win.preview-pull-request")
        branch.append("Create pull request", "win.open-pull-request")
        menu.append_submenu("Branch", branch)
        help_m = Gio.Menu()
        help_m.append("About GitHub Desktop", "win.about")
        help_m.append("Show logs", "win.show-logs")
        menu.append_submenu("Help", help_m)
        return menu

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
        self._filter.connect("search-changed", lambda *_: self._refresh_files())
        left.append(self._filter)
        tools = Gtk.Box(spacing=6)
        self._include_all = Gtk.CheckButton(label="Include all")
        self._include_all.connect("toggled", self._on_include_all)
        tools.append(self._include_all)
        ignore_ws = Gtk.CheckButton(label="Hide whitespace")
        ignore_ws.connect("toggled", self._on_hide_ws)
        tools.append(ignore_ws)
        left.append(tools)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._file_list = Gtk.ListBox()
        self._file_list.add_css_class("boxed-list")
        self._file_list.connect("row-selected", self._on_file_selected)
        scroller.set_child(self._file_list)
        left.append(scroller)
        self._stash_bar = Gtk.Box()
        left.append(self._stash_bar)
        commit_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        commit_box.add_css_class("commit-box")
        self._summary = Gtk.Entry()
        self._summary.set_placeholder_text("Summary (required)")
        self._summary.set_max_length(72)
        self._description = Gtk.TextView()
        self._description.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._description.set_size_request(-1, 70)
        co = Gtk.CheckButton(label="Co-authors")
        co.connect("toggled", self._on_coauthors)
        self._coauthor_entry = Gtk.Entry()
        self._coauthor_entry.set_placeholder_text("Name <email>")
        self._coauthor_entry.set_visible(False)
        btn_row = Gtk.Box(spacing=6)
        commit_btn = Gtk.Button(label="Commit to branch")
        commit_btn.add_css_class("suggested-action")
        commit_btn.connect("clicked", self._on_commit)
        gen = Gtk.Button(icon_name="emoji-objects-symbolic")
        gen.set_tooltip_text("Generate commit message with Copilot")
        gen.set_action_name("win.generate-commit-message")
        undo = Gtk.Button(label="Undo")
        undo.set_action_name("win.undo-commit")
        btn_row.append(commit_btn)
        btn_row.append(gen)
        btn_row.append(undo)
        commit_box.append(self._summary)
        commit_box.append(self._description)
        commit_box.append(co)
        commit_box.append(self._coauthor_entry)
        commit_box.append(btn_row)
        self._conflict_bar = Gtk.Box(spacing=6)
        commit_box.append(self._conflict_bar)
        left.append(commit_box)
        paned.set_start_child(left)
        self._diff_scroll = Gtk.ScrolledWindow(hexpand=True, vexpand=True)
        self._diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._diff_box.add_css_class("diff-view")
        self._diff_scroll.set_child(self._diff_box)
        paned.set_end_child(self._diff_scroll)
        return paned

    def _build_history(self) -> Gtk.Widget:
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_resize_start_child(False)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        left.set_size_request(300, -1)
        compare = Gtk.Button(label="Compare to branch…")
        compare.connect("clicked", self._on_compare)
        left.append(compare)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        self._commit_list = Gtk.ListBox()
        self._commit_list.connect("row-selected", self._on_commit_selected)
        scroller.set_child(self._commit_list)
        left.append(scroller)
        paned.set_start_child(left)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._commit_header = Gtk.Label()
        self._commit_header.set_wrap(True)
        self._commit_header.add_css_class("commit-summary")
        right.append(self._commit_header)
        self._hist_files = Gtk.ListBox()
        self._hist_files.connect("row-activated", self._on_hist_file)
        files_scroll = Gtk.ScrolledWindow()
        files_scroll.set_min_content_height(120)
        files_scroll.set_child(self._hist_files)
        right.append(files_scroll)
        self._hist_diff = Gtk.ScrolledWindow(vexpand=True)
        self._hist_diff_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._hist_diff_box.add_css_class("diff-view")
        self._hist_diff.set_child(self._hist_diff_box)
        right.append(self._hist_diff)
        paned.set_end_child(right)
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
        state = self.store.state_for(repo)
        branch = state.status.current_branch if state.status else "detached"
        self._branch_btn.set_label(branch or "detached HEAD")
        self._branch_btn.set_menu_model(self._branch_menu(state))
        self._update_push_label(state)
        self._refresh_repo_list()
        self._refresh_files()
        self._refresh_history()
        self._refresh_conflict_bar(state)
        self._refresh_stash_bar(state)
        if self.store.section == RepositorySectionTab.HISTORY:
            self._view_stack.set_visible_child_name("history")
        else:
            self._view_stack.set_visible_child_name("changes")
        if state.commit_message.summary and not self._summary.get_text():
            self._summary.set_text(state.commit_message.summary)
        if state.commit_message.description:
            self._description.get_buffer().set_text(state.commit_message.description)

    def _update_push_label(self, state) -> None:
        status = state.status
        if not status:
            self._push_btn.set_label("Fetch origin")
            return
        ab = status.branch_ahead_behind
        if not status.current_upstream_branch:
            self._push_btn.set_label("Publish branch")
        elif ab and ab.ahead and ab.behind:
            self._push_btn.set_label(f"Pull {ab.behind} / Push {ab.ahead}")
        elif ab and ab.ahead:
            self._push_btn.set_label(f"Push {ab.ahead}")
        elif ab and ab.behind:
            self._push_btn.set_label(f"Pull {ab.behind}")
        else:
            self._push_btn.set_label("Fetch origin")

    def _on_push_pull(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        status = state.status
        if not status:
            self.store.fetch_repo(repo)
            return
        ab = status.branch_ahead_behind
        if not status.current_upstream_branch or (ab and ab.ahead and not ab.behind):
            self.store.push_repo(repo)
        elif ab and ab.behind:
            self.store.pull_repo(repo)
        else:
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
        for repo in self.store.repositories:
            if needle and needle not in repo.display_name.lower() and needle not in repo.path.lower():
                continue
            row = Adw.ActionRow(title=repo.display_name, subtitle=repo.path)
            if repo.is_missing:
                row.set_subtitle("Can't find this repository")
            if repo.github:
                row.add_prefix(Gtk.Image.new_from_icon_name("user-bookmarks-symbolic"))
            row.set_activatable(True)
            row.connect("activated", lambda _r, rid=repo.id: self.store.select_repository(rid))
            self._repo_list.append(row)
        for cloning in self.store.cloning:
            row = Adw.ActionRow(title="Cloning…", subtitle=cloning.url)
            self._repo_list.append(row)

    def _refresh_files(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        files = list(state.status.working_directory.files) if state.status else []
        needle = self._filter.get_text().lower()
        if needle:
            files = [f for f in files if needle in f.path.lower()]
        while True:
            row = self._file_list.get_first_child()
            if row is None:
                break
            self._file_list.remove(row)
        for file in files:
            row = self._file_row(file)
            self._file_list.append(row)
        if state.selected_file:
            self._render_diff(self._diff_box, state.current_diff)

    def _file_row(self, file: WorkingDirectoryFileChange) -> Gtk.Widget:
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=8)
        check = Gtk.CheckButton()
        check.set_active(file.include)
        check.connect("toggled", lambda btn, p=file.path: self._toggle_file(p, btn.get_active()))
        label = Gtk.Label(label=file.path, xalign=0, hexpand=True)
        label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        badge = Gtk.Label(label=file.status.kind.value)
        badge.add_css_class(STATUS_CLASS.get(file.status.kind, ""))
        box.append(check)
        box.append(label)
        box.append(badge)
        row.set_child(box)
        row._file = file  # type: ignore[attr-defined]
        return row

    def _toggle_file(self, path: str, included: bool) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.set_file_included(repo, path, included)

    def _on_include_all(self, btn: Gtk.CheckButton) -> None:
        repo = self.store.selected_repository
        if repo:
            self.store.set_include_all(repo, btn.get_active())

    def _on_hide_ws(self, btn: Gtk.CheckButton) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        state.hide_whitespace = btn.get_active()
        if state.selected_file:
            self.store.select_file(repo, state.selected_file)

    def _on_file_selected(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        repo = self.store.selected_repository
        if not repo or row is None:
            return
        file = getattr(row, "_file", None)
        if file:
            self.store.select_file(repo, file)

    def _on_coauthors(self, btn: Gtk.CheckButton) -> None:
        self._coauthor_entry.set_visible(btn.get_active())

    def _on_commit(self, *_args: object) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        summary = self._summary.get_text().strip()
        start, end = self._description.get_buffer().get_bounds()
        description = self._description.get_buffer().get_text(start, end, True).strip()
        if not summary:
            self._toast.add_toast(Adw.Toast(title="A commit summary is required"))
            return
        authors = []
        if self._coauthor_entry.get_visible() and self._coauthor_entry.get_text().strip():
            from ..models import Author, parse_name_email

            n, e = parse_name_email(self._coauthor_entry.get_text())
            authors.append(Author(n, e))
        try:
            self.store.commit(repo, summary, description, co_authors=authors)
            self._summary.set_text("")
            self._description.get_buffer().set_text("")
        except Exception as exc:
            self.store.show_popup(PopupType.ERROR, error=str(exc))

    def _refresh_history(self) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        state = self.store.state_for(repo)
        while True:
            row = self._commit_list.get_first_child()
            if row is None:
                break
            self._commit_list.remove(row)
        for commit in state.commits:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            summary = Gtk.Label(label=commit.summary, xalign=0)
            summary.add_css_class("commit-summary")
            meta = Gtk.Label(
                label=f"{commit.short_sha} · {commit.author.name} · {commit.author.date.strftime('%Y-%m-%d %H:%M')}",
                xalign=0,
            )
            meta.add_css_class("commit-sha")
            box.append(summary)
            box.append(meta)
            row.set_child(box)
            row._commit = commit  # type: ignore[attr-defined]
            self._commit_list.append(row)

    def _on_commit_selected(self, _l, row) -> None:
        repo = self.store.selected_repository
        if not repo or row is None:
            return
        commit = getattr(row, "_commit", None)
        if commit:
            self.store.select_commit(repo, commit)
            self._commit_header.set_text(f"{commit.summary}\n{commit.body}".strip())
            while True:
                child = self._hist_files.get_first_child()
                if child is None:
                    break
                self._hist_files.remove(child)
            state = self.store.state_for(repo)
            for f in state.selected_commit_files:
                r = Adw.ActionRow(title=f.path, subtitle=f.status.kind.value)
                r._file = f  # type: ignore[attr-defined]
                r.set_activatable(True)
                self._hist_files.append(r)
            self._render_diff(self._hist_diff_box, state.current_diff)

    def _on_hist_file(self, _l, row) -> None:
        repo = self.store.selected_repository
        if not repo:
            return
        f = getattr(row, "_file", None)
        state = self.store.state_for(repo)
        if f and state.selected_commit:
            diff = get_commit_diff(repo.path, f.path, state.selected_commit.sha, f.status, state.hide_whitespace)
            self._render_diff(self._hist_diff_box, diff)

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
        if status.merge_head_found:
            self._conflict_bar.append(Gtk.Label(label="Merge in progress"))
            cont = Gtk.Button(label="Commit merge")
            abort = Gtk.Button(label="Abort merge")
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.MERGE))
            abort.connect("clicked", lambda *_: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.MERGE))
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)
        elif status.rebase_internal_state:
            self._conflict_bar.append(Gtk.Label(label="Rebase in progress"))
            cont = Gtk.Button(label="Continue rebase")
            abort = Gtk.Button(label="Abort rebase")
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.REBASE))
            abort.connect("clicked", lambda *_: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.REBASE))
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)
        elif status.is_cherry_picking_head_found:
            self._conflict_bar.append(Gtk.Label(label="Cherry-pick in progress"))
            cont = Gtk.Button(label="Continue")
            abort = Gtk.Button(label="Abort")
            cont.connect("clicked", lambda *_: self.store.continue_conflict_operation(repo, MultiCommitOperationKind.CHERRY_PICK))
            abort.connect("clicked", lambda *_: self.store.abort_conflict_operation(repo, MultiCommitOperationKind.CHERRY_PICK))
            self._conflict_bar.append(cont)
            self._conflict_bar.append(abort)

    def _refresh_stash_bar(self, state) -> None:
        child = self._stash_bar.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._stash_bar.remove(child)
            child = nxt
        repo = self.store.selected_repository
        if not repo or not state.stashes:
            return
        label = Gtk.Label(label=f"{len(state.stashes)} Desktop stash(es)")
        restore = Gtk.Button(label="Restore")
        restore.connect("clicked", lambda *_: (stash_pop(repo.path, state.stashes[0].name), self.store.refresh_repository(repo)))
        discard = Gtk.Button(label="Discard")
        discard.connect("clicked", lambda *_: self.store.show_popup(PopupType.CONFIRM_DISCARD_STASH, stash=state.stashes[0].name))
        self._stash_bar.append(label)
        self._stash_bar.append(restore)
        self._stash_bar.append(discard)

    def _render_diff(self, container: Gtk.Box, diff: FileDiff | None) -> None:
        child = container.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            container.remove(child)
            child = nxt
        if diff is None:
            container.append(Adw.StatusPage(title="No file selected", icon_name="document-symbolic"))
            return
        kind = getattr(diff, "kind", None)
        if kind == DiffType.BINARY:
            container.append(Adw.StatusPage(title="Binary file", description="This file can't be displayed as text."))
            return
        if kind == DiffType.IMAGE and isinstance(diff, ImageDiff):
            box = Gtk.Box(spacing=12)
            for blob, title in ((diff.previous, "Previous"), (diff.current, "Current")):
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                col.append(Gtk.Label(label=title))
                if blob:
                    try:
                        from gi.repository import GdkPixbuf

                        loader = GdkPixbuf.PixbufLoader()
                        loader.write(blob)
                        loader.close()
                        pix = loader.get_pixbuf()
                        if pix:
                            tex = Gdk.Texture.new_for_pixbuf(pix)
                            pic = Gtk.Picture.new_for_paintable(tex)
                            pic.set_size_request(240, 240)
                            col.append(pic)
                    except Exception:
                        col.append(Gtk.Label(label="(unable to render image)"))
                box.append(col)
            container.append(box)
            return
        if kind in (DiffType.LARGE_TEXT, DiffType.UNRENDERABLE):
            container.append(Adw.StatusPage(title="Diff too large to display"))
            return
        if kind == DiffType.SUBMODULE:
            container.append(Adw.StatusPage(title="Submodule", description=getattr(diff, "path", "")))
            return
        if not isinstance(diff, TextDiff):
            container.append(Gtk.Label(label="Unable to display this diff"))
            return
        if diff.has_hidden_bidi_chars:
            warn = Gtk.Label(label="This diff contains hidden bidirectional Unicode characters.")
            container.append(warn)
        for hunk in diff.hunks:
            for line in hunk.lines:
                row = Gtk.Box(spacing=8)
                row.add_css_class("diff-line")
                if line.kind == DiffLineType.ADD:
                    row.add_css_class("diff-add")
                elif line.kind == DiffLineType.DELETE:
                    row.add_css_class("diff-del")
                elif line.kind == DiffLineType.HUNK:
                    row.add_css_class("diff-hunk")
                old = Gtk.Label(label=str(line.old_line_number or ""))
                new = Gtk.Label(label=str(line.new_line_number or ""))
                old.add_css_class("diff-num")
                new.add_css_class("diff-num")
                text = Gtk.Label(label=line.text, xalign=0, hexpand=True)
                text.set_selectable(True)
                text.set_ellipsize(Pango.EllipsizeMode.END)
                row.append(old)
                row.append(new)
                row.append(text)
                container.append(row)
