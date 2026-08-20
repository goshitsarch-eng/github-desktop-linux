"""All GitHub Desktop dialogs as libadwaita dialogs (feature-parity popups)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk

from ..changelog import load_release_notes
from ..editors import get_available_editors
from ..errors import ValidationError
from ..git.ops import (
    add_remote,
    get_author_identity,
    get_config_value,
    get_default_branch,
    read_gitignore,
    remove_remote,
    set_config_value,
    set_remote_url,
    write_gitignore,
)
from ..github.oauth import dotcom_endpoint
from ..models import (
    INVALID_GIT_AUTHOR_NAME_MESSAGE,
    ApplicationTheme,
    BypassReason,
    PopupType,
    UncommittedChangesStrategy,
    git_author_name_is_valid,
)
from ..shells import get_available_shells, open_external
from ..store import AppStore
from ..version import APP_NAME, __version__
from .avatar import Avatar
from .checks import show_checks, show_rerun_checks
from .diff_view import DiffViewer
from .multi_commit import show_multi_commit, show_warn_force_push


def _alert(
    parent: Gtk.Window,
    heading: str,
    body: str,
    *,
    confirm: str = "OK",
    cancel: str | None = "Cancel",
    destructive: bool = False,
    on_confirm: Callable[[], None] | None = None,
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    if cancel:
        dialog.add_response("cancel", cancel)
    dialog.add_response("ok", confirm)
    if destructive:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    else:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response(cancel and "cancel" or "ok")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "ok" and on_confirm:
            on_confirm()

    dialog.choose(parent, None, done)


def _text_dialog(
    parent: Gtk.Window,
    heading: str,
    body: str,
    fields: list[tuple[str, str, str]],
    on_submit: Callable[[dict[str, str]], None],
    confirm: str = "Continue",
) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=heading, subtitle=body))
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda *_: dialog.close())
    ok = Gtk.Button(label=confirm)
    ok.add_css_class("suggested-action")
    header.pack_start(cancel)
    header.pack_end(ok)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    entries: dict[str, Gtk.Entry] = {}
    for key, label, initial in fields:
        row = Adw.EntryRow(title=label)
        row.set_text(initial)
        box.append(row)
        entries[key] = row
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def submit(*_args: Any) -> None:
        values = {k: e.get_text() for k, e in entries.items()}
        dialog.close()
        on_submit(values)

    ok.connect("clicked", submit)
    dialog.present(parent)


def present_popup(parent: Gtk.Window, store: AppStore, popup_type: PopupType, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    mapping: dict[PopupType, Callable[..., None]] = {
        PopupType.ERROR: lambda: _alert(parent, "Error", str(payload.get("error") or "Something went wrong"), cancel=None),
        PopupType.ABOUT: lambda: show_about(parent),
        PopupType.ACKNOWLEDGEMENTS: lambda: show_acknowledgements(parent),
        PopupType.TERMS_AND_CONDITIONS: lambda: show_terms(parent),
        PopupType.PREFERENCES: lambda: show_preferences(parent, store),
        PopupType.ADD_REPOSITORY: lambda: show_add_repository(parent, store, payload.get("path", "")),
        PopupType.CREATE_REPOSITORY: lambda: show_create_repository(parent, store, payload.get("path", "")),
        PopupType.CLONE_REPOSITORY: lambda: show_clone_repository(parent, store, payload),
        PopupType.SIGN_IN: lambda: show_sign_in(parent, store, bool(payload.get("enterprise"))),
        PopupType.CREATE_BRANCH: lambda: show_create_branch(parent, store, payload),
        PopupType.RENAME_BRANCH: lambda: show_rename_branch(parent, store, payload),
        PopupType.DELETE_BRANCH: lambda: show_delete_branch(parent, store, payload),
        PopupType.DELETE_REMOTE_BRANCH: lambda: show_delete_branch(parent, store, payload, remote=True),
        PopupType.CONFIRM_DISCARD_CHANGES: lambda: show_discard(parent, store, payload),
        PopupType.PUBLISH_REPOSITORY: lambda: show_publish(parent, store),
        PopupType.REMOVE_REPOSITORY: lambda: show_remove_repository(parent, store),
        PopupType.REPOSITORY_SETTINGS: lambda: show_repository_settings(parent, store),
        PopupType.CONFIRM_FORCE_PUSH: lambda: show_force_push(parent, store),
        PopupType.PUSH_NEEDS_PULL: lambda: _alert(
            parent,
            "Fetch first?",
            "The remote has commits you don't have locally. Pull or fetch before pushing.",
            confirm="Fetch",
            on_confirm=lambda: repo and store.fetch_repo(repo),
        ),
        PopupType.GENERIC_GIT_AUTHENTICATION: lambda: show_generic_auth(parent, store, payload),
        PopupType.CREATE_TAG: lambda: show_create_tag(parent, store, payload),
        PopupType.DELETE_TAG: lambda: show_delete_tag(parent, store, payload),
        PopupType.STASH_AND_SWITCH_BRANCH: lambda: show_stash_switch(parent, store, payload),
        PopupType.CONFIRM_DISCARD_STASH: lambda: _alert(
            parent,
            "Discard stash?",
            "This cannot be undone.",
            destructive=True,
            confirm="Discard",
            on_confirm=lambda: _discard_stash(store, payload),
        ),
        PopupType.CONFIRM_OVERWRITE_STASH: lambda: _alert(
            parent,
            "Overwrite stash?",
            "A Desktop stash already exists for this branch.",
            destructive=True,
            confirm="Overwrite",
            on_confirm=lambda: _overwrite_stash(store, payload),
        ),
        PopupType.CONFIRM_CHECKOUT_COMMIT: lambda: _alert(
            parent,
            "Checkout commit?",
            "This will detach HEAD. You can create a branch afterwards.",
            confirm="Checkout",
            on_confirm=lambda: repo and payload.get("sha") and store.checkout.__wrapped__ if False else _checkout_sha(store, payload),
        ),
        PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO: lambda: _alert(
            parent,
            "Undo commit?",
            "You have local changes. Undoing the commit keeps them in the working directory.",
            confirm="Undo",
            on_confirm=lambda: repo and _undo(store),
        ),
        PopupType.WARNING_BEFORE_RESET: lambda: _alert(
            parent,
            "Reset to this commit?",
            "Commits after this point will be removed from the current branch.",
            destructive=True,
            confirm="Reset",
            on_confirm=lambda: _reset(store, payload),
        ),
        PopupType.START_PULL_REQUEST: lambda: show_start_pr(parent, store),
        PopupType.INSTALL_GIT: lambda: _alert(
            parent,
            "Git not found",
            "Install Git and restart GitHub Desktop.\n\nsudo apt install git",
            cancel=None,
        ),
        PopupType.CLI_INSTALLED: lambda: _alert(parent, "CLI installed", "The github command is available.", cancel=None),
        PopupType.INITIALIZE_LFS: lambda: show_lfs(parent, store),
        PopupType.LFS_ATTRIBUTE_MISMATCH: lambda: _alert(
            parent, "LFS attributes mismatch", "The repository's Git LFS attributes don't match the global settings.", cancel=None
        ),
        PopupType.OVERSIZED_FILES: lambda: _alert(
            parent,
            "Files too large",
            "These files are over 100MB and cannot be pushed to GitHub:\n" + "\n".join(payload.get("files") or []),
            cancel=None,
        ),
        PopupType.COMMIT_CONFLICTS_WARNING: lambda: _alert(
            parent, "Conflicted files", "Resolve conflicts before committing.", cancel=None
        ),
        PopupType.SAML_REAUTH_REQUIRED: lambda: _alert(
            parent,
            "SAML single sign-on",
            "Authorize this application for the organization, then retry.",
            confirm="Open GitHub",
            on_confirm=lambda: open_external("https://github.com"),
        ),
        PopupType.PUSH_REJECTED_WORKFLOW_SCOPE: lambda: _alert(
            parent,
            "Workflow scope required",
            "Pushing workflow files requires the workflow OAuth scope. Sign in again.",
            confirm="Sign in",
            on_confirm=lambda: store.begin_sign_in(False),
        ),
        PopupType.PUSH_PROTECTION_ERROR: lambda: show_push_protection(parent, store, payload),
        PopupType.CREATE_FORK: lambda: show_create_fork(parent, store),
        PopupType.CHOOSE_FORK_SETTINGS: lambda: show_fork_settings(parent, store),
        PopupType.CHANGE_REPOSITORY_ALIAS: lambda: show_alias(parent, store),
        PopupType.EXTERNAL_EDITOR_FAILED: lambda: _alert(parent, "Editor failed", str(payload.get("message") or ""), cancel=None),
        PopupType.OPEN_SHELL_FAILED: lambda: _alert(parent, "Shell failed", str(payload.get("message") or ""), cancel=None),
        PopupType.INVALIDATED_TOKEN: lambda: _alert(
            parent,
            "Signed out",
            "Your GitHub token is no longer valid. Sign in again.",
            confirm="Sign in",
            on_confirm=lambda: store.begin_sign_in(False),
        ),
        PopupType.ADD_SSH_HOST: lambda: _alert(
            parent,
            f"Unknown SSH host {payload.get('host', '')}",
            f"Fingerprint: {payload.get('fingerprint', '')}",
            confirm="Trust",
            on_confirm=lambda: payload.get("on_submit") and payload["on_submit"](True),
        ),
        PopupType.SSH_KEY_PASSPHRASE: lambda: show_ssh_passphrase(parent, payload),
        PopupType.SSH_USER_PASSWORD: lambda: show_ssh_password(parent, payload),
        PopupType.CONFIRM_COMMIT_FILTERED_CHANGES: lambda: _alert(
            parent,
            "Hidden changes",
            "Some files are hidden by the changes filter. Commit anyway?",
            confirm="Commit anyway",
            on_confirm=lambda: payload.get("on_commit") and payload["on_commit"](),
        ),
        PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER: lambda: show_copilot_disclaimer(parent, store),
        PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE: lambda: _alert(
            parent,
            "Replace commit message?",
            "This will overwrite the summary and description you already typed.",
            confirm="Replace",
            on_confirm=lambda: _generate(store),
        ),
        PopupType.UNKNOWN_AUTHORS: lambda: _alert(
            parent,
            "Unknown authors",
            "Some co-authors could not be matched to GitHub users.",
            confirm="Commit anyway",
            on_confirm=lambda: payload.get("on_commit") and payload["on_commit"](),
        ),
        PopupType.MULTI_COMMIT_OPERATION: lambda: show_multi_commit(parent, store, payload),
        PopupType.UNREACHABLE_COMMITS: lambda: show_unreachable_commits(parent, store, payload),
        PopupType.RELEASE_NOTES: lambda: show_release_notes(parent),
        PopupType.THANK_YOU: lambda: show_thank_you(parent),
        PopupType.PUSH_BRANCH_COMMITS: lambda: _alert(
            parent,
            "Publish branch?",
            "This branch hasn't been published yet. Publish it to create a pull request.",
            confirm="Publish",
            on_confirm=lambda: repo and store.push_repo(repo),
        ),
        PopupType.DELETE_PULL_REQUEST: lambda: _alert(
            parent,
            "Delete branch?",
            "This branch has an open pull request.",
            destructive=True,
            confirm="Delete",
            on_confirm=lambda: _delete_current_branch(store),
        ),
        PopupType.LOCAL_CHANGES_OVERWRITTEN: lambda: _alert(
            parent,
            "Local changes would be overwritten",
            "Stash or commit your changes before continuing.\n" + "\n".join(payload.get("files") or []),
            confirm="Stash and continue",
            on_confirm=lambda: _stash_and_retry(store, payload),
        ),
        PopupType.DISCARD_CHANGES_RETRY: lambda: _alert(
            parent,
            "Discard failed",
            "Some files could not be discarded. Retry?",
            confirm="Retry",
            on_confirm=lambda: payload.get("retry") and payload["retry"](),
        ),
        PopupType.CONFIRM_DISCARD_SELECTION: lambda: _alert(
            parent,
            "Discard selected lines?",
            "Discarded lines cannot be recovered.",
            destructive=True,
            confirm="Discard",
            on_confirm=lambda: payload.get("on_discard") and payload["on_discard"](),
        ),
        PopupType.COMMIT_MESSAGE: lambda: show_commit_message_dialog(parent, store, payload),
        PopupType.CREATE_TUTORIAL_REPOSITORY: lambda: show_tutorial(parent, store),
        PopupType.CONFIRM_EXIT_TUTORIAL: lambda: _alert(
            parent,
            "Exit tutorial?",
            "You can resume later from the repository list.",
            confirm="Exit",
            on_confirm=lambda: store.exit_tutorial(),
        ),
        PopupType.UPSTREAM_ALREADY_EXISTS: lambda: _alert(
            parent, "Upstream exists", "This fork already has an upstream remote.", cancel=None
        ),
        PopupType.PULL_REQUEST_CHECKS_FAILED: lambda: show_checks(parent, store, payload),
        PopupType.CI_CHECK_RUN_RERUN: lambda: show_rerun_checks(parent, store, payload),
        PopupType.WARN_FORCE_PUSH: lambda: show_warn_force_push(parent, store, payload),
        PopupType.PULL_REQUEST_REVIEW: lambda: show_pull_request_review(parent, store, payload),
        PopupType.PULL_REQUEST_COMMENT: lambda: show_pull_request_comment(parent, store, payload),
        PopupType.INSTALLING_UPDATE: lambda: _alert(parent, "Installing update", "The update will be applied shortly.", cancel=None),
        PopupType.BYPASS_PUSH_PROTECTION: lambda: show_bypass(parent, store, payload),
    }
    handler = mapping.get(popup_type)
    if handler:
        handler()
    else:
        _alert(parent, popup_type.value, "This dialog is available.", cancel=None)


def _open_payload_url(payload: dict[str, Any]) -> None:
    url = payload.get("url") or payload.get("html_url")
    if url:
        open_external(url)


def _generate(store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    try:
        store.generate_commit_message(repo)
    except Exception as exc:
        store.show_popup(PopupType.ERROR, error=str(exc))


def show_copilot_disclaimer(parent: Gtk.Window, store: AppStore) -> None:
    dialog = Adw.AlertDialog(
        heading="GitHub Copilot",
        body=(
            "Copilot is powered by AI, so mistakes are possible. Review and edit "
            "the generated message carefully before use."
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", "I understand")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    link = Gtk.LinkButton(
        uri="https://gh.io/copilot-for-desktop-transparency",
        label="Learn more about Copilot in GitHub Desktop.",
    )
    try:
        dialog.set_extra_child(link)
    except Exception:
        pass

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "ok":
            _generate(store)

    dialog.choose(parent, None, done)


def _undo(store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import undo_commit

    undo_commit(repo.path)
    store.refresh_repository(repo)


def _reset(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    sha = payload.get("sha")
    if repo and sha:
        from ..git.ops import reset

        reset(repo.path, sha, "mixed")
        store.refresh_repository(repo)


def _checkout_sha(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    sha = payload.get("sha")
    if repo and sha:
        from ..git.ops import checkout_commit

        checkout_commit(repo.path, sha)
        store.refresh_repository(repo)


def _discard_stash(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    name = payload.get("stash")
    if repo and name:
        from ..git.ops import stash_drop

        stash_drop(repo.path, name)
        state = store.state_for(repo)
        state.stashed_visible = False
        store.refresh_repository(repo)


def _overwrite_stash(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import stash_drop, stash_push

    state = store.state_for(repo)
    if state.stashes:
        stash_drop(repo.path, state.stashes[0].name)
    branch = state.status.current_branch if state.status else "unknown"
    stash_push(repo.path, branch or "unknown")
    target = payload.get("branch")
    if target:
        from ..git.ops import checkout_branch

        checkout_branch(repo.path, target)
    store.refresh_repository(repo)


def _stash_and_retry(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import stash_push

    state = store.state_for(repo)
    stash_push(repo.path, state.status.current_branch if state.status else "unknown")
    store.refresh_repository(repo)


def _delete_current_branch(store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    branch = state.status.current_branch if state.status else None
    if branch:
        from ..git.ops import delete_local_branch

        delete_local_branch(repo.path, branch)
        store.refresh_repository(repo)


def show_about(parent: Gtk.Window) -> None:
    dialog = Adw.AboutDialog(
        application_name=APP_NAME,
        application_icon="io.github.desktop.GitHubDesktop",
        developer_name="GitHub, Inc. (unofficial Linux GTK 4 port)",
        version=__version__,
        comments="Native GTK 4 + libadwaita GitHub Desktop for Linux with full feature parity.",
        website="https://github.com/goshitsarch-eng/github-desktop-linux",
        issue_url="https://github.com/goshitsarch-eng/github-desktop-linux/issues",
        license_type=Gtk.License.MIT_X11,
        copyright="© GitHub, Inc. and contributors",
    )
    dialog.add_link("User guides", "https://docs.github.com/en/desktop")
    dialog.add_link("Keyboard shortcuts", "https://docs.github.com/en/desktop/installing-and-configuring-github-desktop/overview/keyboard-shortcuts")
    dialog.add_link("Copilot transparency", "https://gh.io/copilot-for-desktop-transparency")
    dialog.present(parent)


def show_acknowledgements(parent: Gtk.Window) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(560)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Acknowledgements", subtitle="Open source licenses"))
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    label = Gtk.Label(wrap=True, xalign=0, selectable=True)
    label.add_css_class("monospace")
    license_text = (
        "GitHub Desktop is open source. This GTK 4 port preserves the original "
        "workflows while using native Adwaita widgets.\n\n"
    )
    for candidate in (
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "LICENSE"),
        "/workspace/LICENSE",
    ):
        path = os.path.abspath(candidate)
        if os.path.isfile(path):
            try:
                license_text += Path(path).read_text(encoding="utf-8")
            except OSError:
                license_text += "MIT License. See the LICENSE file in the repository."
            break
    else:
        license_text += "MIT License. Copyright (c) GitHub, Inc."
    label.set_text(license_text)
    scroller.set_child(label)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.append(scroller)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_terms(parent: Gtk.Window) -> None:
    open_external("https://docs.github.com/en/site-policy/github-terms/github-terms-of-service")


def show_release_notes(parent: Gtk.Window) -> None:
    version, notes = load_release_notes()
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Release notes", subtitle=f"GitHub Desktop {version}"))
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    for note in notes:
        row = Adw.ActionRow(title=note)
        listbox.append(row)
    scroller.set_child(listbox)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.append(scroller)
    web = Gtk.Button(label="View releases on GitHub")
    web.connect("clicked", lambda *_: open_external("https://github.com/goshitsarch-eng/github-desktop-linux/releases"))
    box.append(web)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_thank_you(parent: Gtk.Window) -> None:
    version, notes = load_release_notes()
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Thank you", subtitle=f"GitHub Desktop {version}"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    label = Gtk.Label(
        label="Thanks for contributing to GitHub Desktop. This unofficial Linux port keeps the Desktop workflows on GTK 4 and libadwaita.",
        wrap=True,
        xalign=0,
    )
    box.append(label)
    if notes:
        preview = Gtk.Label(label="\n".join(notes[:4]), wrap=True, xalign=0)
        preview.add_css_class("dim-label")
        box.append(preview)
    links = Gtk.Box(spacing=8)
    desktop = Gtk.Button(label="desktop/desktop")
    desktop.connect("clicked", lambda *_: open_external("https://github.com/desktop/desktop"))
    linux = Gtk.Button(label="Linux fork")
    linux.connect("clicked", lambda *_: open_external("https://github.com/goshitsarch-eng/github-desktop-linux"))
    links.append(desktop)
    links.append(linux)
    box.append(links)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_add_repository(parent: Gtk.Window, store: AppStore, initial: str) -> None:
    def submit(values: dict[str, str]) -> None:
        path = values.get("path", "").strip()
        if path:
            try:
                store.add_repositories([path])
            except Exception as exc:
                store.show_popup(PopupType.ERROR, error=str(exc))

    _text_dialog(parent, "Add local repository", "Choose a Git repository on this computer.", [("path", "Path", initial or os.path.expanduser("~/"))], submit, "Add")


def show_create_repository(parent: Gtk.Window, store: AppStore, initial: str) -> None:
    def submit(values: dict[str, str]) -> None:
        path = values.get("path", "").strip()
        name = values.get("name", "").strip()
        if name and path:
            full = os.path.join(path, name)
        else:
            full = path
        if not full:
            return
        try:
            store.create_repository(full, values.get("description", ""))
        except Exception as exc:
            store.show_popup(PopupType.ERROR, error=str(exc))

    default = store.settings.clone_default_directory or os.path.expanduser("~/Documents/GitHub")
    _text_dialog(
        parent,
        "Create a new repository",
        "This will run git init in the chosen folder.",
        [
            ("name", "Name", ""),
            ("path", "Local path", initial or default),
            ("description", "Description", ""),
        ],
        submit,
        "Create",
    )


def show_clone_repository(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(640)
    dialog.set_content_height(560)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    stack = Adw.ViewStack()
    switcher = Adw.ViewSwitcher()
    switcher.set_stack(stack)
    header.set_title_widget(switcher)
    toolbar.add_top_bar(header)

    default_dir = store.settings.clone_default_directory or os.path.expanduser("~/Documents/GitHub")
    url_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    url_box.set_margin_top(18)
    url_box.set_margin_start(18)
    url_box.set_margin_end(18)
    url_row = Adw.EntryRow(title="URL")
    url_row.set_text(str(payload.get("initial_url") or payload.get("url") or ""))
    path_row = Adw.EntryRow(title="Local path")
    path_row.set_text(str(payload.get("path") or default_dir))
    branch_row = Adw.EntryRow(title="Branch (optional)")
    branch_row.set_text(str(payload.get("branch") or ""))
    choose = Gtk.Button(label="Choose…")
    choose.set_halign(Gtk.Align.START)

    def choose_folder(*_a: Any) -> None:
        picker = Gtk.FileDialog(title="Clone into")

        def done(d, result) -> None:
            try:
                folder = d.select_folder_finish(result)
            except Exception:
                return
            if folder:
                path_row.set_text(folder.get_path() or default_dir)

        picker.select_folder(parent, None, done)

    choose.connect("clicked", choose_folder)
    url_box.append(url_row)
    url_box.append(path_row)
    url_box.append(choose)
    url_box.append(branch_row)
    clone_btn = Gtk.Button(label="Clone")
    clone_btn.add_css_class("suggested-action")
    url_box.append(clone_btn)
    stack.add_titled(url_box, "url", "URL")

    list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    list_box.set_margin_top(8)
    list_box.set_margin_start(8)
    list_box.set_margin_end(8)
    filter_row = Gtk.Box(spacing=6)
    gh_filter = Gtk.SearchEntry()
    gh_filter.set_placeholder_text("Filter repositories")
    gh_filter.set_hexpand(True)
    refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
    refresh_btn.set_tooltip_text("Refresh")
    filter_row.append(gh_filter)
    filter_row.append(refresh_btn)
    list_box.append(filter_row)
    accounts = list(store.accounts)
    account_drop = None
    if len(accounts) > 1:
        account_drop = Gtk.DropDown.new_from_strings([a.login for a in accounts])
        list_box.append(account_drop)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    repo_list = Gtk.ListBox()
    repo_list.add_css_class("boxed-list")
    scroller.set_child(repo_list)
    list_box.append(scroller)
    gh_clone = Gtk.Button(label="Clone selected")
    gh_clone.add_css_class("suggested-action")
    list_box.append(gh_clone)
    stack.add_titled(list_box, "github", "GitHub.com")

    ent_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    ent_box.set_margin_top(8)
    ent_box.set_margin_start(8)
    ent_box.set_margin_end(8)
    ent_filter_row = Gtk.Box(spacing=6)
    ent_filter = Gtk.SearchEntry()
    ent_filter.set_placeholder_text("Filter repositories")
    ent_filter.set_hexpand(True)
    ent_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
    ent_refresh.set_tooltip_text("Refresh")
    ent_filter_row.append(ent_filter)
    ent_filter_row.append(ent_refresh)
    ent_box.append(ent_filter_row)
    ent_accounts = [a for a in accounts if not a.is_dotcom]
    ent_drop = None
    if len(ent_accounts) > 1:
        ent_drop = Gtk.DropDown.new_from_strings([a.login for a in ent_accounts])
        ent_box.append(ent_drop)
    ent_scroller = Gtk.ScrolledWindow(vexpand=True)
    ent_list = Gtk.ListBox()
    ent_list.add_css_class("boxed-list")
    ent_scroller.set_child(ent_list)
    ent_box.append(ent_scroller)
    ent_clone = Gtk.Button(label="Clone selected")
    ent_clone.add_css_class("suggested-action")
    ent_box.append(ent_clone)
    stack.add_titled(ent_box, "enterprise", "GitHub Enterprise")

    selected_clone_url = {"url": "", "name": ""}
    loaded: list = []

    def selected_account(enterprise: bool = False):
        dropdown = ent_drop if enterprise else account_drop
        source = ent_accounts if enterprise else accounts
        if dropdown is not None and source:
            idx = dropdown.get_selected()
            if 0 <= idx < len(source):
                return source[idx]
        if enterprise:
            return next((a for a in store.accounts if not a.is_dotcom), None)
        return next((a for a in store.accounts if a.is_dotcom), store.accounts[0] if store.accounts else None)

    def render_github_list() -> None:
        while True:
            row = repo_list.get_first_child()
            if row is None:
                break
            repo_list.remove(row)
        needle = gh_filter.get_text().strip().lower()
        shown = 0
        for gh in loaded:
            hay = f"{gh.full_name} {gh.html_url}".lower()
            if needle and needle not in hay:
                continue
            row = Adw.ActionRow(title=gh.full_name, subtitle=gh.clone_url)
            row.set_activatable(True)

            def pick(_r, g=gh) -> None:
                selected_clone_url["url"] = g.clone_url
                selected_clone_url["name"] = g.name
                url_row.set_text(g.clone_url)
                path_row.set_text(os.path.join(default_dir, g.name))

            row.connect("activated", pick)
            repo_list.append(row)
            shown += 1
            if shown >= 300:
                break
        if shown == 0:
            title = "Sign in to GitHub.com to see your repositories" if not selected_account() else "No matching repositories"
            repo_list.append(Adw.ActionRow(title=title))

    def fill_github(*_a: Any) -> None:
        account = selected_account()
        loaded.clear()
        if not account:
            render_github_list()
            return
        from ..github.api import GitHubAPI

        try:
            loaded.extend(GitHubAPI.from_account(account).fetch_repos())
        except Exception as exc:
            loaded.clear()
            while True:
                row = repo_list.get_first_child()
                if row is None:
                    break
                repo_list.remove(row)
            repo_list.append(Adw.ActionRow(title="Could not load repositories", subtitle=str(exc)))
            return
        render_github_list()

    fill_github()
    gh_filter.connect("search-changed", lambda *_: render_github_list())
    refresh_btn.connect("clicked", fill_github)
    if account_drop is not None:
        account_drop.connect("notify::selected", fill_github)

    loaded_ent: list = []

    def render_enterprise_list() -> None:
        while True:
            row = ent_list.get_first_child()
            if row is None:
                break
            ent_list.remove(row)
        needle = ent_filter.get_text().strip().lower()
        shown = 0
        for gh in loaded_ent:
            hay = f"{gh.full_name} {gh.html_url}".lower()
            if needle and needle not in hay:
                continue
            row = Adw.ActionRow(title=gh.full_name, subtitle=gh.clone_url)
            row.set_activatable(True)

            def pick_ent(_r, g=gh) -> None:
                selected_clone_url["url"] = g.clone_url
                selected_clone_url["name"] = g.name
                url_row.set_text(g.clone_url)
                path_row.set_text(os.path.join(default_dir, g.name))

            row.connect("activated", pick_ent)
            ent_list.append(row)
            shown += 1
            if shown >= 300:
                break
        if shown == 0:
            title = (
                "Sign in to GitHub Enterprise to see your repositories"
                if not selected_account(True)
                else "No matching repositories"
            )
            ent_list.append(Adw.ActionRow(title=title))

    def fill_enterprise(*_a: Any) -> None:
        account = selected_account(True)
        loaded_ent.clear()
        if not account:
            render_enterprise_list()
            return
        from ..github.api import GitHubAPI

        try:
            loaded_ent.extend(GitHubAPI.from_account(account).fetch_repos())
        except Exception as exc:
            loaded_ent.clear()
            while True:
                row = ent_list.get_first_child()
                if row is None:
                    break
                ent_list.remove(row)
            ent_list.append(Adw.ActionRow(title="Could not load repositories", subtitle=str(exc)))
            return
        render_enterprise_list()

    fill_enterprise()
    ent_filter.connect("search-changed", lambda *_: render_enterprise_list())
    ent_refresh.connect("clicked", fill_enterprise)
    if ent_drop is not None:
        ent_drop.connect("notify::selected", fill_enterprise)

    def do_clone(*_a: Any) -> None:
        url = url_row.get_text().strip() or selected_clone_url["url"]
        path = path_row.get_text().strip()
        branch = branch_row.get_text().strip() or None
        if not url or not path:
            return
        if os.path.isdir(path) and os.listdir(path):
            name = selected_clone_url["name"] or os.path.basename(url.rstrip("/").removesuffix(".git"))
            path = os.path.join(path, name)
        dialog.close()
        store.clone(url, path, branch)

    clone_btn.connect("clicked", do_clone)
    gh_clone.connect("clicked", do_clone)
    ent_clone.connect("clicked", do_clone)
    toolbar.set_content(stack)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_sign_in(parent: Gtk.Window, store: AppStore, enterprise: bool) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Sign in", subtitle="GitHub Enterprise" if enterprise else "GitHub.com"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(24)
    box.set_margin_start(24)
    box.set_margin_end(24)
    box.set_margin_bottom(24)
    if enterprise:
        endpoint = Adw.EntryRow(title="Enterprise URL")
        box.append(endpoint)

        def continue_ent(*_a: Any) -> None:
            store.set_sign_in_endpoint(endpoint.get_text().strip())
            store.request_browser_auth()

        btn = Gtk.Button(label="Continue with browser")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", continue_ent)
        box.append(btn)
    else:
        label = Gtk.Label(label="Sign in using your browser. GitHub Desktop will receive the token via the x-github-client protocol.")
        label.set_wrap(True)
        box.append(label)
        btn = Gtk.Button(label="Sign in with browser")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: store.request_browser_auth())
        box.append(btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_create_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..github.repo_rules import use_repo_rules_logic
    from ..models import test_for_invalid_chars

    state = store.state_for(repo)
    start = (payload or {}).get("start") or (state.status.current_branch if state.status else "")
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Create a branch", subtitle="The new branch will be checked out."))
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda *_: dialog.close())
    create = Gtk.Button(label="Create branch")
    create.add_css_class("suggested-action")
    header.pack_start(cancel)
    header.pack_end(create)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    name_row = Adw.EntryRow(title="Name")
    start_row = Adw.EntryRow(title="Create from")
    start_row.set_text(start or "")
    warn = Gtk.Label(wrap=True, xalign=0)
    warn.add_css_class("repo-rules-warning")
    warn.set_visible(False)
    box.append(name_row)
    box.append(start_row)
    box.append(warn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def refresh_warning(*_a: object) -> None:
        name = name_row.get_text().strip()
        if not name:
            create.set_sensitive(False)
            warn.set_visible(False)
            return
        if test_for_invalid_chars(name):
            warn.set_text("Branch names can't contain spaces or Git special characters.")
            warn.set_visible(True)
            create.set_sensitive(False)
            return
        rules = state.repo_rules
        if repo.github and use_repo_rules_logic(store.account_for_repo(repo), repo):
            name_fail = rules.branch_name_patterns.get_failed_rules(name)
            if rules.creation_restricted is True or name_fail.status == "fail":
                extra = ", ".join(f.description for f in name_fail.failed)
                warn.set_text(
                    "Repository rules prevent creating this branch"
                    + (f" ({extra})." if extra else ".")
                )
                warn.set_visible(True)
                create.set_sensitive(False)
                return
            if rules.creation_restricted == "bypass" or name_fail.status == "bypass":
                extra = ", ".join(f.description for f in name_fail.bypassed)
                warn.set_text(
                    "Repository rules restrict this branch name. You can bypass this rule"
                    + (f" ({extra})." if extra else ".")
                )
                warn.set_visible(True)
                create.set_sensitive(True)
                return
        warn.set_visible(False)
        create.set_sensitive(True)

    def submit(*_a: object) -> None:
        name = name_row.get_text().strip()
        start_point = start_row.get_text().strip() or None
        if not name or not create.get_sensitive():
            return
        dialog.close()
        store.create_branch_and_checkout(repo, name, start_point)

    name_row.connect("notify::text", refresh_warning)
    create.connect("clicked", submit)
    refresh_warning()
    dialog.present(parent)


def show_rename_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    current = (payload or {}).get("branch") or (state.status.current_branch if state.status else "")

    def submit(values: dict[str, str]) -> None:
        new = values.get("name", "").strip()
        if new and current:
            from ..git.ops import rename_branch

            rename_branch(repo.path, current, new)
            store.refresh_repository(repo)

    _text_dialog(parent, "Rename branch", f"Rename {current}", [("name", "New name", current or "")], submit, "Rename")


def show_delete_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any], remote: bool = False) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    name = payload.get("branch") or (state.status.current_branch if state.status else "")
    if not name:
        return

    def confirm() -> None:
        from ..git.ops import delete_local_branch, delete_remote_branch

        if remote:
            remotes = state.remotes
            if remotes:
                delete_remote_branch(repo.path, remotes[0].name, name, store.env_for_repo(repo, remotes[0].url))
        else:
            delete_local_branch(repo.path, name)
        store.refresh_repository(repo)

    _alert(parent, "Delete branch?", f"Delete {name}? This cannot be undone.", destructive=True, confirm="Delete", on_confirm=confirm)


def show_discard(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    files = payload.get("files")
    state = store.state_for(repo)
    if not files:
        files = state.status.working_directory.files if state.status else []

    def confirm() -> None:
        store.discard_files(repo, files)

    names = ", ".join(getattr(f, "path", str(f)) for f in files[:8])
    _alert(parent, "Discard changes?", f"Discard changes in {names or 'selected files'}? This cannot be undone.", destructive=True, confirm="Discard", on_confirm=confirm)


def show_publish(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    account = store.accounts[0] if store.accounts else None
    if not account:
        store.begin_sign_in(False)
        return

    def submit(values: dict[str, str]) -> None:
        store.publish_repository(
            repo,
            values.get("name") or repo.name,
            values.get("description") or "",
            values.get("visibility") == "private",
            values.get("org") or None,
            account,
        )

    _text_dialog(
        parent,
        "Publish repository",
        f"Signed in as {account.login}",
        [
            ("name", "Name", repo.name),
            ("description", "Description", ""),
            ("visibility", "Visibility (private/public)", "private"),
            ("org", "Organization (optional)", ""),
        ],
        submit,
        "Publish",
    )


def show_remove_repository(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    dialog = Adw.AlertDialog(
        heading="Remove repository?",
        body=f"Remove {repo.display_name} from GitHub Desktop? Files on disk can optionally be deleted.",
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("keep", "Remove")
    dialog.add_response("delete", "Remove and delete files")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "keep":
            store.remove_repository(repo, False)
        elif response == "delete":
            store.remove_repository(repo, True)

    dialog.choose(parent, None, done)


def show_repository_settings(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import get_remotes

    dialog = Adw.PreferencesDialog()
    dialog.set_title("Repository settings")
    remote_page = Adw.PreferencesPage(title="Remote", icon_name="network-server-symbolic")
    ignore_page = Adw.PreferencesPage(title="Ignored files", icon_name="folder-symbolic")
    git_page = Adw.PreferencesPage(title="Git Config", icon_name="utilities-terminal-symbolic")
    fork_page = Adw.PreferencesPage(title="Fork", icon_name="system-users-symbolic")
    remotes = get_remotes(repo.path)
    remote_group = Adw.PreferencesGroup(title="Remote")
    url_row = Adw.EntryRow(title="Primary remote URL (origin)")
    url_row.set_text(remotes[0].url if remotes else "")
    remote_group.add(url_row)
    save_remote = Gtk.Button(label="Save remote")
    save_remote.add_css_class("suggested-action")

    def save_r(*_a: Any) -> None:
        url = url_row.get_text().strip()
        if not url:
            return
        if remotes:
            set_remote_url(repo.path, remotes[0].name, url)
        else:
            add_remote(repo.path, "origin", url)
        store.refresh_repository(repo)

    save_remote.connect("clicked", save_r)
    remote_group.add(save_remote)
    remote_page.add(remote_group)

    ignore_group = Adw.PreferencesGroup(title=".gitignore")
    buffer = Gtk.TextBuffer()
    buffer.set_text(read_gitignore(repo.path))
    text = Gtk.TextView(buffer=buffer)
    text.set_wrap_mode(Gtk.WrapMode.NONE)
    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(220)
    scroll.set_child(text)
    ignore_group.add(scroll)
    save_ignore = Gtk.Button(label="Save gitignore")

    def save_i(*_a: Any) -> None:
        start, end = buffer.get_bounds()
        write_gitignore(repo.path, buffer.get_text(start, end, True))

    save_ignore.connect("clicked", save_i)
    ignore_group.add(save_ignore)
    ignore_page.add(ignore_group)

    git_group = Adw.PreferencesGroup(title="Local Git config")
    name_row = Adw.EntryRow(title="Name")
    email_row = Adw.EntryRow(title="Email")
    n, e = get_author_identity(repo.path)
    name_row.set_text(n or "")
    email_row.set_text(e or "")
    git_group.add(name_row)
    git_group.add(email_row)
    save_git = Gtk.Button(label="Save local Git config")

    def save_g(*_a: Any) -> None:
        set_config_value(repo.path, "user.name", name_row.get_text())
        set_config_value(repo.path, "user.email", email_row.get_text())

    save_git.connect("clicked", save_g)
    git_group.add(save_git)
    git_page.add(git_group)

    fork_group = Adw.PreferencesGroup(title="Contribute to")
    fork_group.set_description("When this repository is a fork, choose whether to contribute to the parent or the fork.")
    parent_row = Adw.SwitchRow(title="Contribute to the parent repository")
    parent_row.set_active(repo.workflow_preferences.get("fork_target") != "Self")
    fork_group.add(parent_row)
    fork_page.add(fork_group)

    dialog.add(remote_page)
    dialog.add(ignore_page)
    dialog.add(git_page)
    dialog.add(fork_page)
    dialog.present(parent)


def show_preferences(parent: Gtk.Window, store: AppStore) -> None:
    dialog = Adw.PreferencesDialog()
    dialog.set_title("Preferences")
    s = store.settings

    accounts = Adw.PreferencesPage(title="Accounts", icon_name="system-users-symbolic")
    acc_group = Adw.PreferencesGroup(title="GitHub accounts")
    for account in store.accounts:
        row = Adw.ActionRow(title=account.login, subtitle=account.friendly_endpoint)
        row.add_prefix(Avatar(account.name or account.login, account.emails[0] if account.emails else "", login=account.login, avatar_url=account.avatar_url, size=28))
        btn = Gtk.Button(label="Sign out")
        btn.connect("clicked", lambda _b, a=account: (store.sign_out(a), dialog.close()))
        row.add_suffix(btn)
        acc_group.add(row)
    sign_dot = Gtk.Button(label="Sign in to GitHub.com")
    sign_dot.connect("clicked", lambda *_: store.begin_sign_in(False))
    sign_ent = Gtk.Button(label="Sign in to GitHub Enterprise")
    sign_ent.connect("clicked", lambda *_: store.begin_sign_in(True))
    acc_group.add(sign_dot)
    acc_group.add(sign_ent)
    accounts.add(acc_group)

    integrations = Adw.PreferencesPage(title="Integrations", icon_name="applications-engineering-symbolic")
    ed_group = Adw.PreferencesGroup(title="External editor")
    editors = get_available_editors()
    editor_row = Adw.ComboRow(title="Editor")
    model = Gtk.StringList.new([e.name for e in editors] or ["None found"])
    editor_row.set_model(model)
    if s.selected_external_editor:
        for i, e in enumerate(editors):
            if e.name == s.selected_external_editor:
                editor_row.set_selected(i)
    ed_group.add(editor_row)
    sh_group = Adw.PreferencesGroup(title="Shell")
    shells = get_available_shells()
    shell_row = Adw.ComboRow(title="Shell")
    shell_row.set_model(Gtk.StringList.new([sh.name for sh in shells] or ["None found"]))
    sh_group.add(shell_row)
    integrations.add(ed_group)
    integrations.add(sh_group)

    git_page = Adw.PreferencesPage(title="Git", icon_name="utilities-terminal-symbolic")
    git_group = Adw.PreferencesGroup(title="Git author")
    name_row = Adw.EntryRow(title="Name")
    email_row = Adw.EntryRow(title="Email")
    n, e = get_author_identity(None)
    name_row.set_text(n or "")
    email_row.set_text(e or "")
    branch_row = Adw.EntryRow(title="Default branch name")
    branch_row.set_text(get_default_branch())
    git_group.add(name_row)
    git_group.add(email_row)
    git_group.add(branch_row)
    git_page.add(git_group)

    appearance = Adw.PreferencesPage(title="Appearance", icon_name="applications-graphics-symbolic")
    theme_group = Adw.PreferencesGroup(title="Theme")
    theme_row = Adw.ComboRow(title="Appearance")
    theme_row.set_model(Gtk.StringList.new(["system", "light", "dark"]))
    theme_row.set_selected(["system", "light", "dark"].index(s.theme) if s.theme in ("system", "light", "dark") else 0)
    tab_row = Adw.SpinRow(title="Diff tab size")
    tab_row.set_adjustment(Gtk.Adjustment(value=s.tab_size, lower=1, upper=8, step_increment=1))
    zoom_row = Adw.SpinRow(title="Zoom")
    zoom_row.set_adjustment(Gtk.Adjustment(value=s.zoom_factor, lower=0.7, upper=3.0, step_increment=0.1))
    side_row = Adw.SwitchRow(title="Show side-by-side diffs", active=s.show_side_by_side_diff)
    ws_row = Adw.SwitchRow(title="Hide whitespace in diffs", active=s.hide_whitespace_in_diffs)
    theme_group.add(theme_row)
    theme_group.add(tab_row)
    theme_group.add(zoom_row)
    theme_group.add(side_row)
    theme_group.add(ws_row)
    appearance.add(theme_group)

    notes = Adw.PreferencesPage(title="Notifications", icon_name="preferences-system-notifications-symbolic")
    n_group = Adw.PreferencesGroup()
    n_row = Adw.SwitchRow(title="Enable notifications", active=s.notifications_enabled)
    n_group.add(n_row)
    notes.add(n_group)

    prompts = Adw.PreferencesPage(title="Prompts", icon_name="dialog-question-symbolic")
    p_group = Adw.PreferencesGroup(title="Confirm before…")
    switches = {}
    for key, title in [
        ("confirm_repository_removal", "Removing repositories"),
        ("confirm_discard_changes", "Discarding changes"),
        ("confirm_discard_stash", "Discarding stashes"),
        ("confirm_force_push", "Force pushing"),
        ("confirm_undo_commit", "Undoing commits"),
        ("confirm_checkout_commit", "Checking out commits"),
        ("confirm_commit_filtered_changes", "Committing while a filter is active"),
        ("confirm_commit_message_override", "Overwriting commit messages with Copilot"),
    ]:
        row = Adw.SwitchRow(title=title, active=getattr(s, key))
        switches[key] = row
        p_group.add(row)
    strategy = Adw.ComboRow(title="If I have changes and switch branches…")
    strategy.set_model(Gtk.StringList.new([
        UncommittedChangesStrategy.ASK_FOR_CONFIRMATION.value,
        UncommittedChangesStrategy.STASH_ON_CURRENT_BRANCH.value,
        UncommittedChangesStrategy.MOVE_TO_NEW_BRANCH.value,
    ]))
    p_group.add(strategy)
    prompts.add(p_group)

    advanced = Adw.PreferencesPage(title="Advanced", icon_name="emblem-system-symbolic")
    a_group = Adw.PreferencesGroup()
    tracking = Adw.SwitchRow(title="Opt out of usage reporting", active=s.opt_out_of_usage_tracking)
    cred = Adw.SwitchRow(title="Use an external Git credential helper", active=s.use_external_credential_helper)
    indicators = Adw.SwitchRow(title="Show repository indicators", active=s.repository_indicators_enabled)
    a_group.add(tracking)
    a_group.add(cred)
    a_group.add(indicators)
    advanced.add(a_group)

    access = Adw.PreferencesPage(title="Accessibility", icon_name="preferences-desktop-accessibility-symbolic")
    ac_group = Adw.PreferencesGroup()
    underline = Adw.SwitchRow(title="Underline links", active=s.underline_links)
    checks = Adw.SwitchRow(title="Show diff check marks", active=s.show_diff_check_marks)
    ac_group.add(underline)
    ac_group.add(checks)
    access.add(ac_group)

    for page in (accounts, integrations, git_page, appearance, notes, prompts, advanced, access):
        dialog.add(page)

    def persist(*_a: Any) -> None:
        s.theme = ["system", "light", "dark"][theme_row.get_selected()]
        s.tab_size = int(tab_row.get_value())
        s.zoom_factor = float(zoom_row.get_value())
        s.show_side_by_side_diff = side_row.get_active()
        s.hide_whitespace_in_diffs = ws_row.get_active()
        s.notifications_enabled = n_row.get_active()
        s.opt_out_of_usage_tracking = tracking.get_active()
        s.use_external_credential_helper = cred.get_active()
        s.repository_indicators_enabled = indicators.get_active()
        s.underline_links = underline.get_active()
        s.show_diff_check_marks = checks.get_active()
        for key, row in switches.items():
            setattr(s, key, row.get_active())
        if editors:
            idx = editor_row.get_selected()
            if 0 <= idx < len(editors):
                s.selected_external_editor = editors[idx].name
        if shells:
            idx = shell_row.get_selected()
            if 0 <= idx < len(shells):
                s.selected_shell = shells[idx].name
        try:
            store.save_git_user(name_row.get_text(), email_row.get_text(), branch_row.get_text().strip() or None)
        except ValidationError:
            pass
        store.persist_settings()
        store.apply_theme()
        store.set_zoom(s.zoom_factor)

    dialog.connect("closed", persist)
    dialog.present(parent)


def show_force_push(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    _alert(
        parent,
        "Force push?",
        "A force push can overwrite commits on the remote. GitHub Desktop uses --force-with-lease.",
        confirm="Force push",
        destructive=True,
        on_confirm=lambda: repo and store.push_repo(repo, force=True),
    )


def show_generic_auth(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    url = payload.get("remote_url") or ""

    def submit(values: dict[str, str]) -> None:
        from .. import secrets

        user, password = values.get("username", ""), values.get("password", "")
        parsed = url
        host = parsed
        from ..remote_parsing import parse_remote

        info = parse_remote(url)
        if info:
            host = info.hostname
        secrets.set_generic(host, user, password)
        repo = store.selected_repository
        if repo:
            store.push_repo(repo)

    _text_dialog(parent, "Authentication required", url, [("username", "Username", ""), ("password", "Password / token", "")], submit, "Save and retry")


def show_create_tag(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    sha = (payload or {}).get("sha") or (state.selected_commit.sha if state.selected_commit else (state.status.current_tip if state.status else ""))

    def submit(values: dict[str, str]) -> None:
        from ..git.ops import create_tag

        name = values.get("name", "").strip()
        if name and sha:
            create_tag(repo.path, name, sha)
            state.local_tags_to_push.append(name)
            store.refresh_repository(repo)

    _text_dialog(parent, "Create tag", "Annotated tag on the selected commit.", [("name", "Name", "")], submit, "Create tag")


def show_delete_tag(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    name = payload.get("tag")
    if repo and name:
        from ..git.ops import delete_tag

        _alert(parent, "Delete tag?", name, destructive=True, confirm="Delete", on_confirm=lambda: (delete_tag(repo.path, name), store.refresh_repository(repo)))


def show_stash_switch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    branch = payload.get("branch")
    if not repo or not branch:
        return
    dialog = Adw.AlertDialog(heading="Switch branch?", body="You have uncommitted changes.")
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("leave", "Leave my changes")
    dialog.add_response("stash", "Stash changes")
    dialog.set_default_response("stash")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        from ..git.ops import checkout_branch, stash_push

        state = store.state_for(repo)
        current = state.status.current_branch if state.status else "unknown"
        if response == "stash":
            stash_push(repo.path, current or "unknown")
            checkout_branch(repo.path, branch)
        elif response == "leave":
            checkout_branch(repo.path, branch)
        store.refresh_repository(repo)

    dialog.choose(parent, None, done)


def show_start_pr(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo or not repo.github:
        store.show_popup(PopupType.ERROR, error="This repository isn't on GitHub.")
        return
    store.load_pr_preview(repo)
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else "?"
    base_names = [b.name for b in state.branches if b.name != current]
    default = state.pr_base_branch or repo.github.default_branch
    if default and default not in base_names:
        base_names.insert(0, default)

    dialog = Adw.Dialog()
    dialog.set_content_width(900)
    dialog.set_content_height(640)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Preview pull request", subtitle=f"{current} → {default}"))
    toolbar.add_top_bar(header)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_margin_start(12)
    root.set_margin_end(12)
    root.set_margin_top(8)
    root.set_margin_bottom(8)
    top = Gtk.Box(spacing=8)
    top.append(Gtk.Label(label="Base"))
    base_drop = Gtk.DropDown.new_from_strings(base_names or [default])
    if default in base_names:
        base_drop.set_selected(base_names.index(default))
    top.append(base_drop)
    stats = Gtk.Label(xalign=0, hexpand=True)
    top.append(stats)
    merge_info = Gtk.Label(wrap=True, xalign=0)
    merge_info.add_css_class("merge-info")
    root.append(top)
    root.append(merge_info)

    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    paned.set_resize_start_child(False)
    files_scroll = Gtk.ScrolledWindow()
    files_scroll.set_size_request(240, -1)
    file_list = Gtk.ListBox()
    file_list.add_css_class("boxed-list")
    files_scroll.set_child(file_list)
    paned.set_start_child(files_scroll)
    from .diff_view import DiffViewer

    viewer = DiffViewer(interactive=False)
    paned.set_end_child(viewer)
    root.append(paned)

    title_row = Adw.EntryRow(title="Title")
    title_row.set_text(state.commit_message.summary if state.commit_message else (state.pr_commits[0].summary if state.pr_commits else current or ""))
    body_row = Adw.EntryRow(title="Description")
    root.append(title_row)
    root.append(body_row)
    actions = Gtk.Box(spacing=8)
    create_btn = Gtk.Button(label="Create pull request")
    create_btn.add_css_class("suggested-action")
    view_btn = Gtk.Button(label="View pull request")
    view_btn.set_visible(bool(state.current_pull_request))
    actions.append(create_btn)
    actions.append(view_btn)
    root.append(actions)

    def render_preview() -> None:
        st = store.state_for(repo)
        cs = st.pr_changeset
        n = len(st.pr_commits)
        added = cs.lines_added if cs else 0
        deleted = cs.lines_deleted if cs else 0
        files_n = len(st.pr_files)
        if n == 0:
            stats.set_text("No commits to merge into the base branch")
            merge_info.set_text("")
        else:
            stats.set_text(f"{n} commit{'s' if n != 1 else ''} · {files_n} files · +{added} −{deleted}")
            from ..git.ops import determine_mergeability

            ours = next((b.tip_sha for b in st.branches if b.name == (st.pr_base_branch or default)), None)
            theirs = st.status.current_tip if st.status else None
            if ours and theirs:
                status = determine_mergeability(repo.path, ours, theirs)
                if status.kind.value == "conflicts":
                    noun = "file" if status.conflicted_files == 1 else "files"
                    merge_info.set_text(f"Can't automatically merge. {status.conflicted_files} conflicted {noun}.")
                elif status.kind.value == "invalid":
                    merge_info.set_text("Unable to merge unrelated histories into this base branch.")
                else:
                    merge_info.set_text("Able to merge automatically.")
            else:
                merge_info.set_text("")
        while True:
            row = file_list.get_first_child()
            if row is None:
                break
            file_list.remove(row)
        for file in st.pr_files:
            row = Adw.ActionRow(title=file.path, subtitle=file.status.kind.value)
            row.set_activatable(True)
            row._file = file  # type: ignore[attr-defined]
            file_list.append(row)
        if st.pr_files:
            diff = store.load_pr_preview_diff(repo, st.pr_files[0])
            viewer.render(diff, path=st.pr_files[0].path, show_checks=False)
        else:
            viewer.render(None)

    def on_file(_l, row) -> None:
        file = getattr(row, "_file", None)
        if file:
            diff = store.load_pr_preview_diff(repo, file)
            viewer.render(diff, path=file.path, show_checks=False)

    file_list.connect("row-activated", on_file)

    def on_base(*_a: Any) -> None:
        model = base_drop.get_model()
        idx = base_drop.get_selected()
        if model is None or idx < 0:
            return
        name = model.get_string(idx)
        store.load_pr_preview(repo, name)
        header.set_title_widget(Adw.WindowTitle(title="Preview pull request", subtitle=f"{current} → {name}"))
        render_preview()

    base_drop.connect("notify::selected", on_base)

    def create(*_a: Any) -> None:
        model = base_drop.get_model()
        idx = base_drop.get_selected()
        base = model.get_string(idx) if model is not None and idx >= 0 else default
        dialog.close()
        store.create_pull_request(repo, title_row.get_text().strip() or current, base, body_row.get_text().strip())

    def view(*_a: Any) -> None:
        st = store.state_for(repo)
        if st.current_pull_request:
            dialog.close()
            open_external(st.current_pull_request.html_url)

    create_btn.connect("clicked", create)
    view_btn.connect("clicked", view)
    render_preview()
    toolbar.set_content(root)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_lfs(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import lfs_ls_files, lfs_patterns_from_gitattributes, lfs_track

    existing = lfs_patterns_from_gitattributes(repo.path)
    tracked = lfs_ls_files(repo.path)
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Git LFS", subtitle="Track large files with Git LFS"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_bottom(16)
    if tracked:
        box.append(Gtk.Label(label=f"{len(tracked)} LFS object(s) in this repository", xalign=0))
    if existing:
        box.append(Gtk.Label(label="Already tracking: " + ", ".join(existing[:12]), xalign=0))
    patterns = Adw.EntryRow(title="Patterns to track")
    patterns.set_text("*.psd *.zip *.mp4" if not existing else " ".join(existing))
    box.append(patterns)
    init_btn = Gtk.Button(label="Initialize Git LFS and track")
    init_btn.add_css_class("suggested-action")

    def confirm(*_a: Any) -> None:
        items = [p for p in patterns.get_text().split() if p]
        lfs_track(repo.path, items or ["*"])
        dialog.close()
        store.refresh_repository(repo)

    init_btn.connect("clicked", confirm)
    box.append(init_btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_push_protection(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    secrets = list(payload.get("secrets") or [])
    dialog = Adw.Dialog()
    dialog.set_content_width(560)
    dialog.set_content_height(420)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(title="Push blocked: secret detected", subtitle="GitHub secret scanning prevented this push")
    )
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.set_margin_bottom(12)
    if not secrets:
        box.append(Gtk.Label(label=str(payload.get("error") or "GitHub detected a secret in this push."), xalign=0, wrap=True))
    for secret in secrets:
        title = getattr(secret, "description", None) or getattr(secret, "secret_type", None) or "Secret"
        locs = getattr(secret, "locations", None) or []
        if locs:
            loc = locs[0]
            subtitle = f"{loc.path}:{loc.line_number}"
        else:
            subtitle = getattr(secret, "path", "") or ""
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        url = getattr(secret, "bypass_url", None)
        if url:
            open_btn = Gtk.Button(label="Bypass…")
            open_btn.connect(
                "clicked",
                lambda *_ , s=secret, u=url: (
                    dialog.close(),
                    store.show_popup(PopupType.BYPASS_PUSH_PROTECTION, secret=s, bypass_url=u),
                ),
            )
            row.add_suffix(open_btn)
        box.append(row)
    docs = Gtk.Button(label="Remediation docs")
    docs.connect("clicked", lambda *_: open_external("https://docs.github.com/code-security/secret-scanning"))
    box.append(docs)
    scroll = Gtk.ScrolledWindow(vexpand=True)
    scroll.set_child(box)
    toolbar.set_content(scroll)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_unreachable_commits(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    selected = list(state.selected_commits)
    in_diff = set(state.shas_in_diff or payload.get("shas_in_diff") or [])
    reachable = [c for c in selected if c.sha in in_diff] or selected[:1]
    unreachable = [c for c in selected if c.sha not in in_diff]
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(420)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    stack = Adw.ViewStack()
    switcher = Adw.ViewSwitcher()
    switcher.set_stack(stack)
    header.set_title_widget(switcher)
    toolbar.add_top_bar(header)

    def list_commits(commits) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(vexpand=True)
        lst = Gtk.ListBox()
        lst.add_css_class("boxed-list")
        if not commits:
            lst.append(Adw.ActionRow(title="None"))
        for commit in commits:
            lst.append(
                Adw.ActionRow(
                    title=commit.summary or "Empty commit message",
                    subtitle=f"{commit.short_sha} · {commit.author.name}",
                )
            )
        scroller.set_child(lst)
        return scroller

    stack.add_titled(list_commits(unreachable), "unreachable", f"Unreachable ({len(unreachable)})")
    stack.add_titled(list_commits(reachable), "reachable", f"Reachable ({len(reachable)})")
    toolbar.set_content(stack)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_bypass(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo or not repo.github:
        return
    account = store.account_for_repo(repo)
    if not account:
        return

    def submit(values: dict[str, str]) -> None:
        from ..github.api import GitHubAPI

        reason = values.get("reason") or BypassReason.FALSE_POSITIVE.value
        GitHubAPI.from_account(account).create_push_protection_bypass(repo.github.owner, repo.github.name, reason)
        store.push_repo(repo)

    _text_dialog(
        parent,
        "Bypass push protection",
        "Reasons: false_positive, used_in_tests, will_fix_later",
        [("reason", "Reason", BypassReason.FALSE_POSITIVE.value)],
        submit,
        "Bypass",
    )


def show_create_fork(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    account = store.account_for_repo(repo) if repo else None
    if not repo or not repo.github or not account:
        return

    def confirm() -> None:
        from ..github.api import GitHubAPI

        GitHubAPI.from_account(account).fork_repository(repo.github.owner, repo.github.name)
        store.refresh_repository(repo)

    _alert(parent, "Create a fork?", f"Fork {repo.github.full_name} to {account.login}?", confirm="Fork", on_confirm=confirm)


def show_fork_settings(parent: Gtk.Window, store: AppStore) -> None:
    show_repository_settings(parent, store)


def show_alias(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return

    def submit(values: dict[str, str]) -> None:
        repo.alias = values.get("alias") or None
        store._save_repositories()
        store.emit()

    _text_dialog(parent, "Repository alias", "Shown in the repository list.", [("alias", "Alias", repo.alias or "")], submit, "Save")


def show_ssh_passphrase(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    def submit(values: dict[str, str]) -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(values.get("passphrase") or None, True)

    _text_dialog(parent, "SSH key passphrase", payload.get("key_path") or "", [("passphrase", "Passphrase", "")], submit, "Continue")


def show_ssh_password(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    def submit(values: dict[str, str]) -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(values.get("password") or None, True)

    _text_dialog(parent, "SSH password", payload.get("username") or "", [("password", "Password", "")], submit, "Continue")


def show_commit_message_dialog(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    def submit(values: dict[str, str]) -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(values.get("summary") or "", values.get("description") or "")

    _text_dialog(
        parent,
        payload.get("title") or "Commit message",
        "",
        [
            ("summary", "Summary", payload.get("summary") or ""),
            ("description", "Description", payload.get("description") or ""),
        ],
        submit,
        payload.get("button") or "Save",
    )


def show_tutorial(parent: Gtk.Window, store: AppStore) -> None:
    account = store.accounts[0] if store.accounts else None
    if not account:
        store.begin_sign_in(False)
        return
    default = store.settings.clone_default_directory or os.path.expanduser("~/Documents/GitHub")
    path = os.path.join(default, "desktop-tutorial")

    def confirm() -> None:
        from ..github.api import GitHubAPI

        api = GitHubAPI.from_account(account)
        created = api.create_repository("desktop-tutorial", description="GitHub Desktop tutorial repository", private=True)
        store.clone(created.clone_url, path, account=account, tutorial=True)

    _alert(parent, "Create tutorial repository?", f"A private repository will be created for {account.login} and cloned to {path}.", confirm="Create", on_confirm=confirm)


def _pr_event_dialog(
    parent: Gtk.Window,
    store: AppStore,
    payload: dict[str, Any],
    *,
    event: dict[str, Any],
    verb: str,
    title: str,
) -> None:
    user = event.get("user") if isinstance(event.get("user"), dict) else {}
    login = str(user.get("login") or payload.get("author") or "Someone")
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    number = pr.get("number") or payload.get("number") or ""
    pr_title = pr.get("title") or payload.get("title") or "pull request"
    body = str(event.get("body") or payload.get("body") or "")
    html_url = str(event.get("html_url") or payload.get("html_url") or payload.get("url") or "")
    heading = f"{login} {verb}"
    if number:
        heading = f"{login} {verb} #{number}"
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=title, subtitle=pr_title))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    ident = Gtk.Box(spacing=10)
    ident.append(
        Avatar(login, "", login=login, avatar_url=user.get("avatar_url"), size=40)
    )
    who = Gtk.Label(label=heading, xalign=0, wrap=True)
    who.add_css_class("heading")
    ident.append(who)
    box.append(ident)
    if body.strip():
        body_label = Gtk.Label(label=body, xalign=0, wrap=True)
        box.append(body_label)
    buttons = Gtk.Box(spacing=8)
    if html_url:
        browser = Gtk.Button(label="Open in browser")
        browser.connect("clicked", lambda *_: open_external(html_url))
        buttons.append(browser)
    state = str(event.get("state") or "").upper()
    should_switch = payload.get("should_checkout", state != "APPROVED")
    if should_switch:
        switch = Gtk.Button(label="Switch to pull request")
        switch.add_css_class("suggested-action")

        def go(*_a: Any) -> None:
            store.switch_to_pull_request(payload)
            dialog.close()

        switch.connect("clicked", go)
        buttons.append(switch)
    dismiss = Gtk.Button(label="Dismiss")
    dismiss.connect("clicked", lambda *_: dialog.close())
    buttons.append(dismiss)
    box.append(buttons)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_pull_request_review(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    from ..github.notifications import review_verb

    review = payload.get("review") if isinstance(payload.get("review"), dict) else payload
    state = str(review.get("state") or "COMMENTED")
    _pr_event_dialog(
        parent,
        store,
        payload,
        event=review,
        verb=review_verb(state),
        title="Pull request review",
    )


def show_pull_request_comment(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else payload
    _pr_event_dialog(
        parent,
        store,
        payload,
        event=comment,
        verb="commented on",
        title="Pull request comment",
    )


def show_reorder_commits(parent: Gtk.Window, store: AppStore, to_move: list) -> None:
    """Keyboard-first reorder: ↑/↓ choose the commit to insert before, Enter applies."""
    repo = store.selected_repository
    if not repo or not to_move:
        return
    state = store.state_for(repo)
    local = [c for c in state.commits if c.sha in set(state.local_commit_shas)] or list(state.commits)
    moving_shas = {c.sha for c in to_move}
    candidates = [c for c in local if c.sha not in moving_shas]
    if not candidates:
        store.reorder_onto(repo, to_move, None)
        return
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    dialog.set_content_height(420)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(
            title="Reorder commits",
            subtitle="Use Up/Down then Enter to move before the selected commit. Escape cancels.",
        )
    )
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.set_selection_mode(Gtk.SelectionMode.SINGLE)
    for commit in candidates:
        row = Adw.ActionRow(title=commit.summary, subtitle=commit.short_sha)
        row._commit = commit  # type: ignore[attr-defined]
        listbox.append(row)
    scroller.set_child(listbox)
    apply_btn = Gtk.Button(label="Move before selected")
    apply_btn.add_css_class("suggested-action")

    def apply(*_a: Any) -> None:
        row = listbox.get_selected_row()
        target = getattr(row, "_commit", None) if row else None
        dialog.close()
        store.reorder_onto(repo, to_move, target)

    apply_btn.connect("clicked", apply)
    listbox.connect("row-activated", lambda *_: apply())
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.append(scroller)
    box.append(apply_btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    controller = Gtk.EventControllerKey()

    def on_key(_c, keyval, _code, _mod) -> bool:
        if keyval in (65307,):  # Escape
            dialog.close()
            return True
        if keyval in (65293, 65421):  # Return / KP_Enter
            apply()
            return True
        if keyval in (65362, 65364):  # Up / Down
            rows = []
            child = listbox.get_first_child()
            while child is not None:
                if isinstance(child, Gtk.ListBoxRow):
                    rows.append(child)
                child = child.get_next_sibling()
            if not rows:
                return True
            current = listbox.get_selected_row()
            idx = rows.index(current) if current in rows else 0
            idx = idx - 1 if keyval == 65362 else idx + 1
            idx = max(0, min(len(rows) - 1, idx))
            listbox.select_row(rows[idx])
            return True
        return False

    controller.connect("key-pressed", on_key)
    dialog.add_controller(controller)
    first = listbox.get_row_at_index(0)
    if first:
        listbox.select_row(first)
    dialog.present(parent)
