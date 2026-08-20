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
from ..thank_you import thank_you_note
from ..custom_integration import TARGET_PATH_ARGUMENT
from ..editors import get_available_editors
from ..errors import GitError, ValidationError
from ..git.ops import (
    add_remote,
    add_safe_directory,
    get_author_identity,
    get_config_value,
    get_default_branch,
    get_repository_type,
    is_config_file_lock_error,
    parse_config_lock_file_path_from_error,
    read_gitignore,
    remove_config_value,
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
    ForkContributionTarget,
    GitHubRepository,
    PopupType,
    SignInStep,
    UncommittedChangesStrategy,
    git_author_name_is_valid,
    group_pr_base_branches,
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
    on_cancel: Callable[[], None] | None = None,
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
            if on_cancel:
                on_cancel()
            return
        if response == "ok" and on_confirm:
            on_confirm()
        elif on_cancel:
            on_cancel()

    dialog.choose(parent, None, done)


def _alert_with_check(
    parent: Gtk.Window,
    heading: str,
    body: str,
    *,
    confirm: str = "OK",
    cancel: str | None = "Cancel",
    destructive: bool = False,
    check_label: str = "Do not show this message again",
    extra_responses: list[tuple[str, str]] | None = None,
    on_confirm: Callable[[bool], None] | None = None,
    on_extra: Callable[[str], None] | None = None,
) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    if cancel:
        dialog.add_response("cancel", cancel)
    for key, label in extra_responses or []:
        dialog.add_response(key, label)
    dialog.add_response("ok", confirm)
    if destructive:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    else:
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response(cancel and "cancel" or "ok")
    check = Gtk.CheckButton(label=check_label)
    try:
        dialog.set_extra_child(check)
    except Exception:
        pass

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "ok" and on_confirm:
            on_confirm(check.get_active())
        elif response not in {"ok", "cancel", ""} and on_extra:
            on_extra(response)

    dialog.choose(parent, None, done)


def _text_dialog(
    parent: Gtk.Window,
    heading: str,
    body: str,
    fields: list[tuple[str, str, str]],
    on_submit: Callable[[dict[str, str]], None],
    confirm: str = "Continue",
    on_cancel: Callable[[], None] | None = None,
) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=heading, subtitle=body))
    cancel = Gtk.Button(label="Cancel")
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
    secrets = {"passphrase", "password"}
    for key, label, initial in fields:
        row = Adw.PasswordEntryRow(title=label) if key in secrets else Adw.EntryRow(title=label)
        row.set_text(initial)
        box.append(row)
        entries[key] = row
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    closed = {"done": False}

    def submit(*_args: Any) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        values = {k: e.get_text() for k, e in entries.items()}
        dialog.close()
        on_submit(values)

    def cancel_clicked(*_args: Any) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        dialog.close()
        if on_cancel:
            on_cancel()

    cancel.connect("clicked", cancel_clicked)
    ok.connect("clicked", submit)
    dialog.present(parent)


def present_popup(parent: Gtk.Window, store: AppStore, popup_type: PopupType, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    mapping: dict[PopupType, Callable[..., None]] = {
        PopupType.ERROR: lambda: show_error_dialog(parent, store, payload),
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
            "Newer commits on remote",
            "Desktop is unable to push commits to this branch because there are "
            "commits on the remote that are not present on your local branch. "
            "Fetch these new commits before pushing in order to reconcile them "
            "with your local commits.",
            confirm="Fetch",
            on_confirm=lambda: repo and store.fetch_repo(repo),
        ),
        PopupType.GENERIC_GIT_AUTHENTICATION: lambda: show_generic_auth(parent, store, payload),
        PopupType.CREATE_TAG: lambda: show_create_tag(parent, store, payload),
        PopupType.DELETE_TAG: lambda: show_delete_tag(parent, store, payload),
        PopupType.STASH_AND_SWITCH_BRANCH: lambda: show_stash_switch(parent, store, payload),
        PopupType.CONFIRM_DISCARD_STASH: lambda: _alert_with_check(
            parent,
            "Discard stash?",
            "Are you sure you want to discard these stashed changes?",
            destructive=True,
            confirm="Discard",
            on_confirm=lambda skip: _discard_stash(store, payload, skip_confirm=skip),
        ),
        PopupType.CONFIRM_OVERWRITE_STASH: lambda: _alert(
            parent,
            "Overwrite stash?",
            "Are you sure you want to proceed? This will overwrite your existing stash with your current changes.",
            destructive=True,
            confirm="Overwrite",
            on_confirm=lambda: _overwrite_stash(store, payload),
        ),
        PopupType.CONFIRM_CHECKOUT_COMMIT: lambda: _alert_with_check(
            parent,
            "Checkout commit?",
            "Checking out a commit will create a detached HEAD, and you will no longer be on any branch. "
            "Are you sure you want to checkout this commit?",
            confirm="Checkout",
            on_confirm=lambda skip: _checkout_sha(store, payload, skip_confirm=skip),
        ),
        PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO: lambda: show_warn_undo(parent, store, payload),
        PopupType.WARNING_BEFORE_RESET: lambda: _alert(
            parent,
            "Reset to commit?",
            "You have changes in progress. Resetting to a previous commit might result in some of these changes being lost. Do you want to continue anyway?",
            confirm="Continue",
            destructive=True,
            on_confirm=lambda: _reset(store, payload),
        ),
        PopupType.START_PULL_REQUEST: lambda: show_start_pr(parent, store),
        PopupType.INSTALL_GIT: lambda: _alert(
            parent,
            "Git not found",
            "Install Git and restart GitHub Desktop.\n\nsudo apt install git",
            cancel=None,
        ),
        PopupType.CLI_INSTALLED: lambda: _alert(
            parent,
            "CLI installed",
            f"The github command is available at {payload.get('path') or str(Path.home() / '.local' / 'bin' / 'github')}.",
            cancel=None,
        ),
        PopupType.INITIALIZE_LFS: lambda: show_lfs(parent, store),
        PopupType.LFS_ATTRIBUTE_MISMATCH: lambda: show_lfs_mismatch(parent, store),
        PopupType.OVERSIZED_FILES: lambda: show_oversized_files(parent, store, payload),
        PopupType.COMMIT_CONFLICTS_WARNING: lambda: _alert(
            parent,
            "Confirm committing conflicted files",
            "If you choose to commit, you’ll be committing the following conflicted files into your repository:\n"
            + "\n".join(f"• {p}" for p in (payload.get("files") or []))
            + "\n\nAre you sure you want to commit these conflicted files?",
            confirm="Yes, commit files",
            destructive=True,
            on_confirm=lambda: payload.get("on_commit") and payload["on_commit"](),
        ),
        PopupType.SAML_REAUTH_REQUIRED: lambda: show_saml_reauth(parent, store, payload),
        PopupType.PUSH_REJECTED_WORKFLOW_SCOPE: lambda: _alert(
            parent,
            "Push rejected",
            "The push was rejected by the server for containing a modification to a workflow file. "
            "In order to be able to push to workflow files GitHub Desktop needs to request additional permissions.\n\n"
            "Would you like to open a browser to grant GitHub Desktop permission to update workflow files?",
            confirm="Continue in browser",
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
            "Invalidated account token",
            "Your account token has been invalidated and you have been signed out. Do you want to sign in again?",
            confirm="Yes",
            cancel="No",
            on_confirm=lambda: store.begin_sign_in(False),
        ),
        PopupType.ADD_SSH_HOST: lambda: _alert(
            parent,
            f"Unknown SSH host {payload.get('host', '')}",
            f"The authenticity of host {payload.get('host', '')} ({payload.get('ip', '')}) can't be established.\n"
            f"{payload.get('key_type', '')} key fingerprint is {payload.get('fingerprint', '')}.",
            confirm="Trust",
            on_confirm=lambda: payload.get("on_submit") and payload["on_submit"](True),
            on_cancel=lambda: payload.get("on_submit") and payload["on_submit"](False),
        ),
        PopupType.SSH_KEY_PASSPHRASE: lambda: show_ssh_passphrase(parent, payload),
        PopupType.SSH_USER_PASSWORD: lambda: show_ssh_password(parent, payload),
        PopupType.CONFIRM_COMMIT_FILTERED_CHANGES: lambda: show_filtered_commit(parent, store, payload),
        PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER: lambda: show_copilot_disclaimer(parent, store),
        PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE: lambda: _alert(
            parent,
            "Replace commit message?",
            "This will overwrite the summary and description you already typed.",
            confirm="Replace",
            on_confirm=lambda: _generate(store),
        ),
        PopupType.UNKNOWN_AUTHORS: lambda: show_unknown_authors(parent, payload),
        PopupType.MULTI_COMMIT_OPERATION: lambda: show_multi_commit(parent, store, payload),
        PopupType.UNREACHABLE_COMMITS: lambda: show_unreachable_commits(parent, store, payload),
        PopupType.RELEASE_NOTES: lambda: show_release_notes(parent),
        PopupType.THANK_YOU: lambda: show_thank_you(parent, payload),
        PopupType.PUSH_BRANCH_COMMITS: lambda: show_push_branch_commits(parent, store, payload),
        PopupType.DELETE_PULL_REQUEST: lambda: show_delete_pull_request(parent, store, payload),
        PopupType.LOCAL_CHANGES_OVERWRITTEN: lambda: show_local_changes_overwritten(parent, store, payload),
        PopupType.DISCARD_CHANGES_RETRY: lambda: show_discard_retry(parent, store, payload),
        PopupType.CONFIRM_DISCARD_SELECTION: lambda: _alert_with_check(
            parent,
            "Confirm discard changes",
            "Are you sure you want to discard the selected changes to:\n"
            + f"• {payload.get('path') or 'the selected file'}",
            destructive=True,
            confirm="Discard changes",
            on_confirm=lambda skip: _discard_selection(store, payload, skip_confirm=skip),
        ),
        PopupType.COMMIT_MESSAGE: lambda: show_commit_message_dialog(parent, store, payload),
        PopupType.CREATE_TUTORIAL_REPOSITORY: lambda: show_tutorial(parent, store),
        PopupType.CONFIRM_EXIT_TUTORIAL: lambda: _alert(
            parent,
            "Exit tutorial",
            "Are you sure you want to leave the tutorial? This will bring you back to the home screen.",
            confirm="Exit tutorial",
            on_confirm=lambda: store.pause_tutorial(),
        ),
        PopupType.UPSTREAM_ALREADY_EXISTS: lambda: show_upstream_exists(parent, store, payload),
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


def show_error_dialog(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    heading = str(payload.get("title") or "Error")
    body = str(payload.get("error") or "Something went wrong")
    retry = payload.get("retry")
    if payload.get("retry_clone"):
        heading = "Clone failed"
        name = payload.get("name") or ""
        if name:
            body = f"{body}\n\nWould you like to retry cloning {name}?"
    if callable(retry):
        _alert(parent, heading, body, confirm="Retry", cancel="Close", on_confirm=retry)
        return
    _alert(parent, heading, body, cancel=None)


def show_local_changes_overwritten(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    files = [str(path) for path in (payload.get("files") or []) if path]
    has_existing = bool(payload.get("has_existing_stash"))
    kind = str(payload.get("retry_kind") or "checkout")
    listing = "\n".join(files)
    overwritten = " The following files would be overwritten:" if files else ""
    body = f"Unable to {kind} when changes are present on your branch.{overwritten}"
    if listing:
        body = f"{body}\n{listing}"
    if has_existing:
        _alert(parent, "Error", body, confirm="Close", cancel=None)
        return
    body = f"{body}\n\nYou can stash your changes now and recover them afterwards."
    _alert(
        parent,
        "Error",
        body,
        confirm="Stash changes and continue",
        cancel="Close",
        on_confirm=lambda: _stash_and_retry(store, payload),
    )


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
            store.mark_copilot_disclaimer_seen()
            _generate(store)

    dialog.choose(parent, None, done)


MERGE_UNDO_WARNING = (
    "Undoing a merge commit will apply the changes from the merge into your working "
    "directory, and committing again will create an entirely new commit. This means "
    "you will lose the merge commit and, as a result, commits from the merged branch "
    "could disappear from this branch."
)


def show_warn_undo(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    commit = payload.get("commit")
    clean = bool(payload.get("is_working_directory_clean", True))
    merge = bool(commit is not None and getattr(commit, "is_merge_commit", False))
    if merge and clean:
        body = f"{MERGE_UNDO_WARNING}\n\nDo you want to continue anyway?"
        _alert(
            parent,
            "Undo commit?",
            body,
            confirm="Continue",
            destructive=True,
            on_confirm=lambda: _undo(store, confirmed=True),
        )
        return
    if merge:
        body = (
            "You have changes in progress. Undoing the merge commit might result in some "
            f"of these changes being lost.\n\n{MERGE_UNDO_WARNING}\n\nDo you want to continue anyway?"
        )
        _alert(
            parent,
            "Undo commit?",
            body,
            confirm="Continue",
            destructive=True,
            on_confirm=lambda: _undo(store, confirmed=True),
        )
        return
    _alert_with_check(
        parent,
        "Undo commit?",
        "You have changes in progress. Undoing the commit might result in some of these changes being lost. Do you want to continue anyway?",
        confirm="Continue",
        destructive=True,
        on_confirm=lambda dont_show: _undo(store, confirmed=True, persist_skip=dont_show),
    )


def show_unknown_authors(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    authors = list(payload.get("authors") or [])
    if len(authors) > 10:
        body = (
            f"{len(authors)} users weren't found and won't be added as co-authors of this commit. "
            "Are you sure you want to commit?"
        )
    else:
        names = "\n".join(
            f"• {getattr(a, 'username', None) or getattr(a, 'name', '') or str(a)}" for a in authors
        )
        body = (
            "These users weren't found and won't be added as co-authors of this commit. "
            "Are you sure you want to commit?"
        )
        if names.strip():
            body = f"{body}\n\n{names}"
    _alert(
        parent,
        "Unknown co-authors",
        body,
        confirm="Commit anyway",
        destructive=True,
        on_confirm=lambda: payload.get("on_commit") and payload["on_commit"](),
    )


def show_filtered_commit(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    def commit_anyway(dont_show: bool) -> None:
        if dont_show:
            store.settings.confirm_commit_filtered_changes = False
            store.persist_settings()
        cb = payload.get("on_commit")
        if cb:
            cb()

    def show_hidden(_response: str) -> None:
        repo = store.selected_repository
        if repo:
            store.clear_changes_filter(repo)

    _alert_with_check(
        parent,
        "Commit filtered changes?",
        "You have a filter applied. There are hidden changes that will be committed. Are you sure you want to commit these changes?",
        confirm="Commit anyway",
        destructive=True,
        extra_responses=[("show", "Show hidden changes")],
        on_confirm=commit_anyway,
        on_extra=show_hidden,
    )


def show_lfs_mismatch(parent: Gtk.Window, store: AppStore) -> None:
    dialog = Adw.AlertDialog(
        heading="Update existing Git LFS filters?",
        body=(
            "Git LFS filters are already configured in your global git config but are not "
            "the values it expects. Would you like to update them now?"
        ),
    )
    dialog.add_response("cancel", "Not now")
    dialog.add_response("edit", "Open git config")
    dialog.add_response("ok", "Update existing filters")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "edit":
            store.edit_global_git_config()
        elif response == "ok":
            from ..git.ops import install_global_lfs_filters

            install_global_lfs_filters(force=True)

    dialog.choose(parent, None, done)


def _undo(store: AppStore, *, confirmed: bool = False, persist_skip: bool = False) -> None:
    repo = store.selected_repository
    if not repo:
        return
    if persist_skip:
        store.settings.confirm_undo_commit = False
        store.persist_settings()
    store.undo_last_commit(repo, show_confirmation=not confirmed)


def _reset(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    commit = payload.get("commit")
    sha = payload.get("sha")
    if repo and commit is not None:
        store.reset_to_commit(repo, commit, show_confirmation=False)
        return
    if repo and sha:
        from ..git.ops import reset

        reset(repo.path, sha, "mixed")
        store.refresh_repository(repo)


def _checkout_sha(store: AppStore, payload: dict[str, Any], *, skip_confirm: bool = False) -> None:
    if skip_confirm:
        store.settings.confirm_checkout_commit = False
        store.persist_settings()
    repo = store.selected_repository
    sha = payload.get("sha")
    if repo and sha:
        store.checkout_commit_sha(repo, sha, confirmed=True)


def _discard_stash(store: AppStore, payload: dict[str, Any], *, skip_confirm: bool = False) -> None:
    if skip_confirm:
        store.settings.confirm_discard_stash = False
        store.persist_settings()
    repo = store.selected_repository
    name = payload.get("stash")
    if repo and name:
        from ..git.ops import stash_drop

        stash_drop(repo.path, name)
        state = store.state_for(repo)
        state.stashed_visible = False
        store.refresh_repository(repo)


def _discard_selection(store: AppStore, payload: dict[str, Any], *, skip_confirm: bool = False) -> None:
    if skip_confirm:
        store.settings.confirm_discard_changes = False
        store.persist_settings()
    cb = payload.get("on_discard")
    if cb:
        cb()


def _overwrite_stash(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import checkout_branch

    state = store.state_for(repo)
    branch = state.status.current_branch if state.status else "unknown"
    store.stash_and_drop_previous(repo, branch or "unknown")
    target = payload.get("branch")
    if target:
        checkout_branch(repo.path, target)
    store.refresh_repository(repo)


def _stash_and_retry(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import checkout_branch, stash_push

    state = store.state_for(repo)
    stash_push(repo.path, state.status.current_branch if state.status else "unknown")
    retry = payload.get("retry")
    if callable(retry):
        retry()
        return
    kind = payload.get("retry_kind")
    branch = payload.get("branch")
    if kind == "checkout" and branch:
        checkout_branch(repo.path, branch)
        store.refresh_repository(repo)
    elif kind == "pull":
        store.pull_repo(repo)
    elif kind == "push":
        store.push_repo(repo)
    elif kind == "fetch":
        store.fetch_repo(repo)
    else:
        store.refresh_repository(repo)


def show_oversized_files(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    files = payload.get("files") or []
    listing = "\n".join(f"• {path}" for path in files)
    dialog = Adw.AlertDialog(
        heading="Files too large",
        body=(
            "The following files are over 100MB. If you commit these files, you will no longer "
            "be able to push this repository to GitHub.com.\n\n"
            f"{listing}\n\n"
            "We recommend you avoid committing these files or use Git LFS to store large files on GitHub."
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("lfs", "Git LFS docs")
    dialog.add_response("ok", "Commit anyway")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "lfs":
            open_external("https://help.github.com/articles/versioning-large-files/")
        elif response == "ok":
            cb = payload.get("on_commit")
            if cb:
                cb()

    dialog.choose(parent, None, done)


def show_saml_reauth(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    org = payload.get("organization") or "the"
    endpoint = payload.get("endpoint") or "https://github.com"
    html = endpoint.replace("/api/v3", "").rstrip("/")
    if html.endswith("api.github.com") or html == "https://api.github.com":
        html = "https://github.com"
    dialog = Adw.AlertDialog(
        heading="Re-authorization required",
        body=(
            f'The "{org}" organization has enabled or enforced SAML SSO. To access this repository, '
            "you must sign in again and grant GitHub Desktop permission to access the organization's "
            "repositories.\n\nWould you like to open a browser to grant GitHub Desktop permission "
            "to access the repository?"
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("ok", "Continue in browser")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "ok":
            enterprise = "github.com" not in html
            store.begin_sign_in(enterprise)
            if not enterprise:
                store.request_browser_auth()

    dialog.choose(parent, None, done)


def show_push_branch_commits(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    unpublished = bool(payload.get("unpublished"))
    unpushed = int(payload.get("unpushed") or 0)
    if unpublished:
        heading = "Publish branch?"
        body = "This branch hasn't been published yet. Publish it to create a pull request."
        confirm = "Publish branch"
    else:
        heading = "Push local changes?"
        noun = "commit" if unpushed == 1 else "commits"
        body = f"You have {unpushed} unpushed {noun}. Push them before creating a pull request?"
        confirm = "Push commits"

    def confirm_cb() -> None:
        cb = payload.get("on_confirm")
        if cb:
            cb()
        else:
            repo = store.selected_repository
            if repo:
                store.push_repo(repo)

    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", "Cancel")
    if not unpublished:
        dialog.add_response("skip", "Create without pushing")
    dialog.add_response("ok", confirm)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "ok":
            confirm_cb()
        elif response == "skip":
            skip = payload.get("on_skip")
            if skip:
                skip()

    dialog.choose(parent, None, done)


def show_upstream_exists(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    existing = payload.get("existing_url") or ""
    parent_url = payload.get("parent_url") or ""
    repo = store.selected_repository
    dialog = Adw.AlertDialog(
        heading="Upstream already exists",
        body=(
            "This fork already has an upstream remote, but it doesn't point at the parent repository.\n\n"
            f"Current: {existing}\nParent: {parent_url}"
        ),
    )
    dialog.add_response("ignore", "Ignore")
    dialog.add_response("ok", "Update")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if not repo:
            return
        if response == "ok":
            store.update_existing_upstream_remote(repo, parent_url)
        else:
            store.ignore_existing_upstream_remote(repo)

    dialog.choose(parent, None, done)


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


def show_thank_you(parent: Gtk.Window, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    version, notes = load_release_notes()
    friendly = str(payload.get("friendly_name") or "contributor")
    latest = payload.get("latest_version")
    contributions = list(payload.get("contributions") or [])
    if not contributions:
        contributions = [n for n in notes if "Thanks @" in n][:8]
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(title=f"Thank you {friendly}! 🎉", subtitle=f"GitHub Desktop {version}")
    )
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    label = Gtk.Label(
        label=thank_you_note(str(latest) if latest else None),
        wrap=True,
        xalign=0,
    )
    box.append(label)
    heading = Gtk.Label(label="You contributed:", xalign=0)
    heading.add_css_class("heading")
    box.append(heading)
    if contributions:
        preview = Gtk.Label(label="\n".join(contributions[:12]), wrap=True, xalign=0)
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
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(360)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(
            title="Add local repository",
            subtitle="Choose a Git repository on this computer.",
        )
    )
    add_btn = Gtk.Button(label="Add")
    add_btn.add_css_class("suggested-action")
    header.pack_end(add_btn)
    toolbar.add_top_bar(header)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup()
    path_row = Adw.EntryRow(title="Local path")
    path_row.set_text(initial or os.path.expanduser("~/"))
    choose = Gtk.Button(label="Choose…")
    choose.set_valign(Gtk.Align.CENTER)

    def choose_folder(*_a: Any) -> None:
        picker = Gtk.FileDialog(title="Add local repository")

        def done(d, result) -> None:
            try:
                folder = d.select_folder_finish(result)
            except Exception:
                return
            if folder:
                path_row.set_text(folder.get_path() or path_row.get_text())

        picker.select_folder(parent, None, done)

    choose.connect("clicked", choose_folder)
    path_row.add_suffix(choose)

    missing_row = Adw.ActionRow(title="This directory does not appear to be a Git repository.")
    missing_row.set_subtitle("Would you like to create a repository here instead?")
    create_here = Gtk.Button(label="Create a repository")
    create_here.set_valign(Gtk.Align.CENTER)
    missing_row.add_suffix(create_here)
    missing_row.set_activatable(False)
    missing_row.set_visible(False)

    bare_row = Adw.ActionRow(title="This directory appears to be a bare repository.")
    bare_row.set_subtitle("Bare repositories are not currently supported.")
    bare_row.set_activatable(False)
    bare_row.set_visible(False)

    unsafe_row = Adw.ActionRow(title="This Git repository appears to be owned by another user on your machine.")
    unsafe_row.set_subtitle("Adding untrusted repositories may automatically execute files in the repository.")
    trust_btn = Gtk.Button(label="add an exception for this directory")
    trust_btn.set_valign(Gtk.Align.CENTER)
    unsafe_row.add_suffix(trust_btn)
    unsafe_row.set_activatable(False)
    unsafe_row.set_visible(False)

    def expanded_path() -> str:
        return os.path.abspath(os.path.expanduser(path_row.get_text().strip() or ""))

    def refresh(*_a: Any) -> None:
        raw = path_row.get_text().strip()
        if not raw:
            missing_row.set_visible(False)
            bare_row.set_visible(False)
            unsafe_row.set_visible(False)
            add_btn.set_sensitive(False)
            return
        info = get_repository_type(expanded_path())
        kind = info.get("kind")
        missing_row.set_visible(kind == "missing")
        bare_row.set_visible(kind == "bare")
        unsafe_row.set_visible(kind == "unsafe")
        add_btn.set_sensitive(kind == "regular")

    def create_instead(*_a: Any) -> None:
        dialog.close()
        store.show_popup(PopupType.CREATE_REPOSITORY, path=expanded_path())

    def trust_directory(*_a: Any) -> None:
        info = get_repository_type(expanded_path())
        add_safe_directory(info.get("path") or expanded_path())
        refresh()

    def submit(*_a: Any) -> None:
        path = expanded_path()
        if not path:
            return
        try:
            store.add_repositories([path])
            dialog.close()
        except Exception as exc:
            store.show_popup(PopupType.ERROR, error=str(exc))

    create_here.connect("clicked", create_instead)
    trust_btn.connect("clicked", trust_directory)
    path_row.connect("changed", refresh)
    add_btn.connect("clicked", submit)
    group.add(path_row)
    group.add(missing_row)
    group.add(bare_row)
    group.add(unsafe_row)
    page.add(group)
    toolbar.set_content(page)
    dialog.set_child(toolbar)
    refresh()
    dialog.present(parent)


def show_create_repository(parent: Gtk.Window, store: AppStore, initial: str) -> None:
    from ..create_repo import (
        NO_GITIGNORE,
        NO_LICENSE,
        classify_create_path,
        gitignore_names,
        license_templates,
        sanitized_repository_name,
    )

    submodule_docs_url = "https://gh.io/git-submodules"
    default = store.settings.clone_default_directory or os.path.expanduser("~/Documents/GitHub")
    initial_path = (initial or "").strip() or None
    if initial_path:
        parent_path = os.path.dirname(os.path.abspath(initial_path)) or default
        initial_name = sanitized_repository_name(os.path.basename(os.path.abspath(initial_path)))
    else:
        parent_path = default
        initial_name = ""

    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(680)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(
            title="Create a new repository",
            subtitle="This will create a new Git repository on your local machine.",
        )
    )
    create_btn = Gtk.Button(label="Create repository")
    create_btn.add_css_class("suggested-action")
    header.pack_end(create_btn)
    toolbar.add_top_bar(header)

    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup()
    name_row = Adw.EntryRow(title="Name")
    name_row.set_text(initial_name)
    sanitized_row = Adw.ActionRow(title="Will be created as")
    sanitized_row.set_activatable(False)
    sanitized_row.set_visible(False)
    desc_row = Adw.EntryRow(title="Description")
    path_row = Adw.EntryRow(title="Local path")
    path_row.set_text(parent_path)
    choose = Gtk.Button(label="Choose…")
    choose.set_valign(Gtk.Align.CENTER)
    if initial_path:
        path_row.set_sensitive(False)
        choose.set_sensitive(False)

    def choose_folder(*_a: Any) -> None:
        picker = Gtk.FileDialog(title="Create repository in")

        def done(d, result) -> None:
            try:
                folder = d.select_folder_finish(result)
            except Exception:
                return
            if folder:
                path_row.set_text(folder.get_path() or default)

        picker.select_folder(parent, None, done)

    choose.connect("clicked", choose_folder)
    path_row.add_suffix(choose)

    exists_row = Adw.ActionRow(title="The directory appears to be a Git repository.")
    exists_row.set_subtitle("Would you like to add this repository instead?")
    add_instead = Gtk.Button(label="Add this repository")
    add_instead.set_valign(Gtk.Align.CENTER)
    exists_row.add_suffix(add_instead)
    exists_row.set_activatable(False)
    exists_row.set_visible(False)

    subfolder_row = Adw.ActionRow(title="This directory appears to be a subfolder of a Git repository.")
    learn = Gtk.Button(label="Learn about submodules.")
    learn.set_valign(Gtk.Align.CENTER)

    def open_submodule_docs(*_a: Any) -> None:
        open_external(submodule_docs_url)

    learn.connect("clicked", open_submodule_docs)
    subfolder_row.add_suffix(learn)
    subfolder_row.set_activatable(False)
    subfolder_row.set_visible(False)

    readme = Adw.SwitchRow(title="Initialize this repository with a README")
    readme.set_active(False)
    readme_warn = Adw.ActionRow(title="This directory contains a README.md file already.")
    readme_warn.set_subtitle("Checking this box will result in the existing file being overwritten.")
    readme_warn.set_activatable(False)
    readme_warn.set_visible(False)

    ignore_names = [NO_GITIGNORE, *gitignore_names()]
    ignore_row = Adw.ComboRow(title="Git ignore")
    ignore_row.set_model(Gtk.StringList.new(ignore_names))
    licenses = license_templates()
    license_names = [NO_LICENSE, *[item.name for item in licenses]]
    license_row = Adw.ComboRow(title="License")
    license_row.set_model(Gtk.StringList.new(license_names))
    invalid_row = Adw.ActionRow(
        title="Directory could not be created at this path.",
        subtitle="You may not have permissions to create a directory here.",
    )
    invalid_row.set_activatable(False)
    invalid_row.set_visible(False)
    path_group = Adw.PreferencesGroup()
    path_group.set_description("")

    def selected_label(row: Adw.ComboRow, fallback: str) -> str:
        model = row.get_model()
        idx = row.get_selected()
        if model is None or idx < 0:
            return fallback
        item = model.get_item(idx)
        return item.get_string() if item is not None else fallback

    def resolved_path() -> str:
        name = sanitized_repository_name(name_row.get_text().strip())
        base = path_row.get_text().strip() or default
        if initial_path and os.path.abspath(base) == os.path.abspath(initial_path):
            return os.path.abspath(base)
        if not name:
            return os.path.abspath(base)
        return os.path.join(os.path.abspath(base), name)

    def refresh_hints(*_a: Any) -> None:
        raw = name_row.get_text().strip()
        clean = sanitized_repository_name(raw) if raw else ""
        if raw and clean != raw:
            sanitized_row.set_title(f"Will be created as {clean}")
            sanitized_row.set_visible(True)
        else:
            sanitized_row.set_visible(False)
        full = resolved_path()
        is_repo, is_sub = classify_create_path(full) if raw else (False, False)
        exists_row.set_visible(is_repo)
        subfolder_row.set_visible(is_sub and not is_repo)
        readme_exists = bool(raw) and readme.get_active() and os.path.isfile(os.path.join(full, "README.md"))
        readme_warn.set_visible(readme_exists)
        if raw and not is_repo:
            path_group.set_description(f"The repository will be created at {full}.")
        else:
            path_group.set_description("")
        create_btn.set_sensitive(bool(raw) and bool(path_row.get_text().strip()) and not is_repo)

    def add_existing(*_a: Any) -> None:
        dialog.close()
        store.show_popup(PopupType.ADD_REPOSITORY, path=resolved_path())

    add_instead.connect("clicked", add_existing)

    def submit(*_a: Any) -> None:
        raw_name = name_row.get_text().strip()
        if not raw_name:
            return
        full = resolved_path()
        try:
            os.makedirs(full, exist_ok=True)
            invalid_row.set_visible(False)
        except OSError:
            invalid_row.set_visible(True)
            return
        try:
            store.create_repository(
                full,
                desc_row.get_text().strip(),
                name=raw_name,
                create_readme=readme.get_active(),
                gitignore=selected_label(ignore_row, NO_GITIGNORE),
                license_name=selected_label(license_row, NO_LICENSE),
                update_default_directory=not bool(initial_path),
            )
            dialog.close()
        except Exception as exc:
            store.show_popup(PopupType.ERROR, error=str(exc))

    name_row.connect("changed", refresh_hints)
    path_row.connect("changed", refresh_hints)
    readme.connect("notify::active", refresh_hints)
    create_btn.connect("clicked", submit)

    group.add(invalid_row)
    group.add(name_row)
    group.add(sanitized_row)
    group.add(desc_row)
    group.add(path_row)
    group.add(exists_row)
    group.add(subfolder_row)
    group.add(readme)
    group.add(readme_warn)
    group.add(ignore_row)
    group.add(license_row)
    page.add(group)
    page.add(path_group)
    toolbar.set_content(page)
    dialog.set_child(toolbar)
    refresh_hints()
    dialog.present(parent)



def _decorate_clone_row(row: Adw.ActionRow, gh: GitHubRepository) -> None:
    """Desktop clone list: private lock + Archived badge."""
    if gh.private:
        lock = Gtk.Image.new_from_icon_name("channel-secure-symbolic")
        lock.set_tooltip_text("Private repository")
        row.add_prefix(lock)
    if gh.archived:
        badge = Gtk.Label(label="Archived")
        badge.add_css_class("dim-label")
        row.add_suffix(badge)


def _clear_listbox(listbox: Gtk.ListBox) -> None:
    while True:
        row = listbox.get_first_child()
        if row is None:
            break
        listbox.remove(row)


def _render_grouped_clone_list(
    listbox: Gtk.ListBox,
    repos: list,
    login: str,
    needle: str,
    *,
    selected_clone_url: dict[str, str],
    url_row: Adw.EntryRow,
    path_row: Adw.EntryRow,
    default_dir: str,
    empty_title: str,
) -> None:
    from ..clone_groups import group_cloneable_repositories

    _clear_listbox(listbox)
    shown = 0
    any_shown = False
    needle = needle.strip().lower()
    for title, items in group_cloneable_repositories(list(repos), login):
        filtered = [
            gh
            for gh in items
            if not needle or needle in f"{gh.full_name} {gh.html_url} {gh.name}".lower()
        ]
        if not filtered:
            continue
        header = Adw.ActionRow(title=title)
        header.set_sensitive(False)
        listbox.append(header)
        for gh in filtered:
            row = Adw.ActionRow(title=gh.full_name, subtitle=gh.clone_url)
            row.set_activatable(True)
            _decorate_clone_row(row, gh)

            def pick(_r, g=gh) -> None:
                selected_clone_url["url"] = g.clone_url
                selected_clone_url["name"] = g.name
                url_row.set_text(g.clone_url)
                path_row.set_text(os.path.join(default_dir, g.name))

            row.connect("activated", pick)
            listbox.append(row)
            shown += 1
            any_shown = True
            if shown >= 300:
                break
        if shown >= 300:
            break
    if not any_shown:
        listbox.append(Adw.ActionRow(title=empty_title))


def show_config_lock_file_exists(
    parent: Gtk.Window | None,
    lock_path: str,
    on_deleted: Callable[[], None],
) -> None:
    """Desktop `ConfigLockFileExists` when git cannot lock a config file."""
    dialog = Adw.AlertDialog()
    dialog.set_heading("Failed to update Git configuration file.")
    dialog.set_body(
        f"A lock file already exists at {lock_path}. "
        "This can happen if another tool is currently modifying the Git "
        "configuration or if a Git process has terminated earlier without "
        "cleaning up the lock file. Do you want to delete the lock file "
        "and try again?"
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("delete", "Delete the lock file")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

    def on_response(_dialog, response: str) -> None:
        if response != "delete":
            return
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            return
        on_deleted()

    dialog.connect("response", on_response)
    dialog.present(parent)


def _handle_config_lock(parent: Gtk.Window | None, error: BaseException, retry: Callable[[], None]) -> bool:
    """Show ConfigLockFileExists when `isConfigFileLockError`; return True if handled."""
    if not is_config_file_lock_error(error):
        return False
    lock = parse_config_lock_file_path_from_error(error) if isinstance(error, GitError) else None
    if not lock:
        return False
    show_config_lock_file_exists(parent, lock, retry)
    return True


def _clone_sign_in_cta(
    store: "AppStore",
    dialog: Adw.Dialog,
    *,
    enterprise: bool,
    message: str,
    action_title: str = "Sign in",
) -> Gtk.Widget:
    """Desktop clone `CallToAction` prompting Sign in."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.add_css_class("call-to-action")
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(16)
    box.set_margin_end(16)
    label = Gtk.Label(label=message, wrap=True, xalign=0)
    btn = Gtk.Button(label=action_title)
    btn.add_css_class("suggested-action")
    btn.set_halign(Gtk.Align.START)

    def go(*_a: Any) -> None:
        dialog.close()
        store.begin_sign_in(enterprise)

    btn.connect("clicked", go)
    box.append(label)
    box.append(btn)
    return box


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
    accounts = [a for a in store.accounts if a.is_dotcom]
    gh_sign_in = _clone_sign_in_cta(
        store,
        dialog,
        enterprise=False,
        message="Sign in to your GitHub.com account to access your repositories.",
    )
    list_box.append(gh_sign_in)
    account_drop = None
    if accounts:
        account_drop = Gtk.DropDown.new_from_strings([a.login for a in accounts])
        list_box.append(account_drop)
    gh_sign_in.set_visible(not accounts)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    repo_list = Gtk.ListBox()
    repo_list.add_css_class("boxed-list")
    scroller.set_child(repo_list)
    list_box.append(scroller)
    gh_clone = Gtk.Button(label="Clone selected")
    gh_clone.add_css_class("suggested-action")
    list_box.append(gh_clone)
    stack.add_titled(list_box, "github", "GitHub.com")
    filter_row.set_visible(bool(accounts))
    scroller.set_visible(bool(accounts))
    gh_clone.set_visible(bool(accounts))

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
    ent_accounts = [a for a in store.accounts if not a.is_dotcom]
    ent_sign_in = _clone_sign_in_cta(
        store,
        dialog,
        enterprise=True,
        message="If you are using GitHub Enterprise at work, sign in to it to get access to your repositories.",
    )
    ent_box.append(ent_sign_in)
    ent_drop = None
    if ent_accounts:
        ent_drop = Gtk.DropDown.new_from_strings([a.login for a in ent_accounts])
        ent_box.append(ent_drop)
    ent_sign_in.set_visible(not ent_accounts)
    ent_scroller = Gtk.ScrolledWindow(vexpand=True)
    ent_list = Gtk.ListBox()
    ent_list.add_css_class("boxed-list")
    ent_scroller.set_child(ent_list)
    ent_box.append(ent_scroller)
    ent_clone = Gtk.Button(label="Clone selected")
    ent_clone.add_css_class("suggested-action")
    ent_box.append(ent_clone)
    stack.add_titled(ent_box, "enterprise", "GitHub Enterprise")
    ent_filter_row.set_visible(bool(ent_accounts))
    ent_scroller.set_visible(bool(ent_accounts))
    ent_clone.set_visible(bool(ent_accounts))

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
        return next((a for a in store.accounts if a.is_dotcom), None)

    def render_github_list() -> None:
        account = selected_account()
        signed_in = account is not None
        gh_sign_in.set_visible(not signed_in)
        filter_row.set_visible(signed_in)
        scroller.set_visible(signed_in)
        gh_clone.set_visible(signed_in)
        if account_drop is not None:
            account_drop.set_visible(signed_in)
        if not signed_in:
            _clear_listbox(repo_list)
            return
        needle = gh_filter.get_text().strip()
        empty = "Sorry, I can't find that repository" if needle else "No matching repositories"
        _render_grouped_clone_list(
            repo_list,
            loaded,
            account.login if account else "",
            needle,
            selected_clone_url=selected_clone_url,
            url_row=url_row,
            path_row=path_row,
            default_dir=default_dir,
            empty_title=empty,
        )

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
            _clear_listbox(repo_list)
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
        account = selected_account(True)
        signed_in = account is not None
        ent_sign_in.set_visible(not signed_in)
        ent_filter_row.set_visible(signed_in)
        ent_scroller.set_visible(signed_in)
        ent_clone.set_visible(signed_in)
        if ent_drop is not None:
            ent_drop.set_visible(signed_in)
        if not signed_in:
            _clear_listbox(ent_list)
            return
        needle = ent_filter.get_text().strip()
        empty = "Sorry, I can't find that repository" if needle else "No matching repositories"
        _render_grouped_clone_list(
            ent_list,
            loaded_ent,
            account.login if account else "",
            needle,
            selected_clone_url=selected_clone_url,
            url_row=url_row,
            path_row=path_row,
            default_dir=default_dir,
            empty_title=empty,
        )

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
            _clear_listbox(ent_list)
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

    def clear() -> None:
        while (child := box.get_first_child()) is not None:
            box.remove(child)

    def render(*_a: Any) -> None:
        clear()
        step = store.sign_in_step
        existing = store.sign_in_existing
        if store.sign_in_error:
            err = Gtk.Label(label=store.sign_in_error, wrap=True, xalign=0)
            err.add_css_class("error")
            box.append(err)
        if step == SignInStep.ENDPOINT_ENTRY or (enterprise and not step):
            endpoint = Adw.EntryRow(title="Enterprise URL")
            if store.sign_in_endpoint:
                endpoint.set_text(store.sign_in_endpoint)
            box.append(endpoint)

            def continue_ent(*_b: Any) -> None:
                store.set_sign_in_endpoint(endpoint.get_text().strip())
                render()

            btn = Gtk.Button(label="Continue")
            btn.add_css_class("suggested-action")
            btn.connect("clicked", continue_ent)
            box.append(btn)
            return
        if step == SignInStep.EXISTING_ACCOUNT_WARNING and existing:
            warn = Gtk.Label(
                label=(
                    f"You're already signed in to {existing.friendly_endpoint} with the account "
                    f"{existing.login}. If you continue, you will first be signed out."
                ),
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            box.append(warn)

            def continue_warning(*_b: Any) -> None:
                store.continue_existing_account_warning()
                render()

            btn = Gtk.Button(label="Continue")
            btn.add_css_class("suggested-action")
            btn.connect("clicked", continue_warning)
            box.append(btn)
            return
        label = Gtk.Label(
            label="Sign in using your browser. GitHub Desktop will receive the token via the x-github-client protocol.",
            wrap=True,
            xalign=0,
        )
        box.append(label)
        btn = Gtk.Button(label="Sign in with browser" if not enterprise else "Continue with browser")
        btn.add_css_class("suggested-action")
        btn.connect("clicked", lambda *_: store.request_browser_auth())
        box.append(btn)

    render()
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
            store.rename_current_branch(repo, current, new)

    _text_dialog(parent, "Rename branch", f"Rename {current}", [("name", "New name", current or "")], submit, "Rename")


def show_delete_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any], remote: bool = False) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    name = payload.get("branch") or (state.status.current_branch if state.status else "")
    if not name:
        return
    branch = next((b for b in state.branches if b.name == name or b.name_without_remote == name), None)
    exists_on_remote = bool(branch and branch.upstream) and not remote
    dialog = Adw.AlertDialog(
        heading="Delete branch?",
        body=f"Delete branch {name}?\n\nThis action cannot be undone.",
    )
    include_remote = Gtk.CheckButton(label="Yes, delete this branch on the remote")
    if exists_on_remote:
        extra = Gtk.Label(
            label="The branch also exists on the remote, do you wish to delete it there as well?",
            wrap=True,
            xalign=0,
        )
        extra.add_css_class("dim-label")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(extra)
        box.append(include_remote)
        dialog.set_extra_child(box)
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("delete", "Delete")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def done(_d, response: str) -> None:
        if response != "delete":
            return
        from ..git.ops import delete_local_branch, delete_remote_branch

        if remote or include_remote.get_active():
            remotes = state.remotes
            remote_name = (branch.upstream.split("/", 1)[0] if branch and branch.upstream and "/" in branch.upstream else None)
            if remotes:
                rname = remote_name or remotes[0].name
                local = name if not remote else name
                try:
                    delete_remote_branch(repo.path, rname, local, store.env_for_repo(repo, remotes[0].url))
                except Exception:
                    pass
        if not remote:
            delete_local_branch(repo.path, name)
        store.refresh_repository(repo)

    dialog.connect("response", done)
    dialog.present(parent)


def show_delete_pull_request(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    pr = (payload or {}).get("pull_request") or state.current_pull_request
    number = getattr(pr, "number", None) or (pr.get("number") if isinstance(pr, dict) else None)
    html = getattr(pr, "html_url", None) or (pr.get("html_url") if isinstance(pr, dict) else None)
    body = "This branch may have an open pull request associated with it."
    if number:
        body += (
            f"\n\nIf #{number} has been merged, you can also go to GitHub to delete the remote branch."
        )
    dialog = Adw.AlertDialog(heading="Delete branch?", body=body)
    dialog.add_response("cancel", "Cancel")
    if html:
        dialog.add_response("open", f"Open #{number}" if number else "Open pull request")
    dialog.add_response("delete", "Delete")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "open" and html:
            open_external(html)
            return
        if response == "delete":
            _delete_current_branch(store)

    dialog.choose(parent, None, done)


def show_discard(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    files = payload.get("files")
    state = store.state_for(repo)
    if not files:
        files = state.status.working_directory.files if state.status else []
    discarding_all = bool(payload.get("discarding_all") or (not payload.get("files") and files))

    def confirm() -> None:
        store.discard_files(repo, files)

    if not store.settings.confirm_discard_changes:
        confirm()
        return
    names = [getattr(f, "path", str(f)) for f in files]
    if len(names) > 10:
        listing = f"Are you sure you want to discard all {len(names)} changed files?"
    elif names:
        listing = "Are you sure you want to discard all changes to:\n" + "\n".join(f"• {n}" for n in names)
    else:
        listing = "Are you sure you want to discard these changes?"
    heading = "Confirm discard all changes" if discarding_all else "Confirm discard changes"
    body = (
        f"{listing}\n\n"
        "Changes can be restored by retrieving them from the Trash."
    )

    def on_confirm(skip: bool) -> None:
        if skip:
            store.settings.confirm_discard_changes = False
            store.persist_settings()
        confirm()

    _alert_with_check(
        parent,
        heading,
        body,
        destructive=True,
        confirm="Discard all changes" if discarding_all else "Discard changes",
        on_confirm=on_confirm,
    )


def show_discard_retry(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    def on_confirm(skip: bool) -> None:
        if skip:
            store.settings.confirm_discard_changes_permanently = False
            store.persist_settings()
        retry = payload.get("retry")
        if retry:
            retry()

    _alert_with_check(
        parent,
        "Discarded changes will be unrecoverable",
        "Failed to discard changes to Trash.\n\n"
        "Common reasons are that the file is locked or the Trash is full. "
        "Retrying will leave the files discarded permanently.",
        destructive=True,
        confirm="Discard changes permanently",
        on_confirm=on_confirm,
    )


def show_publish(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    accounts = list(store.accounts)
    account = accounts[0] if accounts else None
    if not account:
        dialog = Adw.Dialog()
        dialog.set_content_width(460)
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Publish repository", subtitle="Sign in required"))
        toolbar.add_top_bar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.append(
            _clone_sign_in_cta(
                store,
                dialog,
                enterprise=False,
                message="Sign in to your GitHub.com account to access your repositories.",
            )
        )
        box.append(
            _clone_sign_in_cta(
                store,
                dialog,
                enterprise=True,
                message="If you are using GitHub Enterprise at work, sign in to it to get access to your repositories.",
            )
        )
        toolbar.set_content(box)
        dialog.set_child(toolbar)
        dialog.present(parent)
        return

    from ..create_repo import sanitized_repository_name
    from ..git.ops import read_description
    from ..github.api import GitHubAPI

    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Publish repository", subtitle=f"Signed in as {account.login}"))
    publish_btn = Gtk.Button(label="Publish repository")
    publish_btn.add_css_class("suggested-action")
    header.pack_end(publish_btn)
    toolbar.add_top_bar(header)
    page = Adw.PreferencesPage()
    group = Adw.PreferencesGroup()
    name_row = Adw.EntryRow(title="Name")
    name_row.set_text(repo.name)
    sanitized_row = Adw.ActionRow(title="Will be created as")
    sanitized_row.set_subtitle("")
    sanitized_row.set_visible(False)
    desc_row = Adw.EntryRow(title="Description")
    desc_row.set_text(read_description(repo.path) or "")
    private_row = Adw.SwitchRow(title="Keep this code private")
    private_row.set_active(True)
    org_row = Adw.ComboRow(title="Organization")
    org_logins = ["None"]
    org_row.set_model(Gtk.StringList.new(org_logins))

    def refresh_name(*_a: Any) -> None:
        raw = name_row.get_text().strip()
        clean = sanitized_repository_name(raw) if raw else ""
        if raw and clean and clean != raw:
            sanitized_row.set_subtitle(clean)
            sanitized_row.set_visible(True)
        else:
            sanitized_row.set_visible(False)

    name_row.connect("changed", refresh_name)

    def submit(*_a: Any) -> None:
        raw = name_row.get_text().strip() or repo.name
        name = sanitized_repository_name(raw) or repo.name
        org = None
        idx = org_row.get_selected()
        if idx > 0 and idx < len(org_logins):
            org = org_logins[idx]
        dialog.close()
        store.publish_repository(repo, name, desc_row.get_text().strip(), private_row.get_active(), org, account)

    publish_btn.connect("clicked", submit)
    group.add(name_row)
    group.add(sanitized_row)
    group.add(desc_row)
    group.add(private_row)
    group.add(org_row)
    page.add(group)
    toolbar.set_content(page)
    dialog.set_child(toolbar)
    dialog.present(parent)
    refresh_name()

    try:
        fetched = GitHubAPI.from_account(account).fetch_orgs()
    except Exception:
        fetched = []
    fetched = sorted(fetched, key=lambda item: str(item.get("login") or "").casefold())
    org_logins = ["None"] + [str(item.get("login") or "") for item in fetched if item.get("login")]
    org_row.set_model(Gtk.StringList.new(org_logins or ["None"]))


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
    if remotes:
        save_remote = Gtk.Button(label="Save remote")
        save_remote.add_css_class("suggested-action")

        def save_r(*_a: Any) -> None:
            url = url_row.get_text().strip()
            if not url:
                return
            set_remote_url(repo.path, remotes[0].name, url)
            store.refresh_repository(repo)

        save_remote.connect("clicked", save_r)
        remote_group.add(save_remote)
    else:
        publish_cta = Gtk.Button(label="Publish repository")
        publish_cta.add_css_class("suggested-action")

        def publish_now(*_a: Any) -> None:
            dialog.close()
            store.show_popup(PopupType.PUBLISH_REPOSITORY)

        publish_cta.connect("clicked", publish_now)
        hint = Adw.ActionRow(title="This repository has no remotes yet")
        hint.set_subtitle("Publish this repository to GitHub to add an origin remote.")
        remote_group.add(hint)
        remote_group.add(publish_cta)
    remote_page.add(remote_group)

    ignore_group = Adw.PreferencesGroup(title=".gitignore")
    ignore_group.set_description(
        "This file specifies intentionally untracked files that Git should ignore. "
        "Files already tracked by Git are not affected."
    )
    examples = Gtk.LinkButton(
        uri="https://docs.github.com/en/get-started/git-basics/ignoring-files",
        label="Learn more about gitignore files",
    )
    examples.set_halign(Gtk.Align.START)
    ignore_group.add(examples)
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

    git_group = Adw.PreferencesGroup(title="For this repository I wish to")
    git_group.set_description("Use my global Git config or a local Git config.")
    global_check = Gtk.CheckButton(label="Use my global Git config")
    local_check = Gtk.CheckButton(label="Use a local Git config")
    local_check.set_group(global_check)
    local_n = get_config_value(repo.path, "user.name", local_only=True)
    local_e = get_config_value(repo.path, "user.email", local_only=True)
    global_n, global_e = get_author_identity(None)
    use_local = bool(local_n or local_e)
    (local_check if use_local else global_check).set_active(True)
    git_group.add(global_check)
    git_group.add(local_check)
    name_row = Adw.EntryRow(title="Name")
    from ..models import account_email_choices  # Desktop GitConfigUserForm: repo account emails + stealth + Other

    account = store.account_for_repo(repo)
    email_choices: list[str] = []
    if account:
        for item in account_email_choices(account):
            if item not in email_choices:
                email_choices.append(item)
    current_email = (local_e if use_local else global_e) or ""
    if current_email and current_email not in email_choices:
        email_choices.insert(0, current_email)
    email_choices.append("Other")
    email_row = Adw.ComboRow(title="Email")
    email_row.set_model(Gtk.StringList.new(email_choices or ["Other"]))
    if current_email and current_email in email_choices:
        email_row.set_selected(email_choices.index(current_email))
    other_email = Adw.EntryRow(title="Other email")
    other_email.set_text(current_email)
    other_email.set_visible(False)

    def sync_other(*_a: Any) -> None:
        idx = email_row.get_selected()
        other_email.set_visible(local_check.get_active() and idx >= 0 and idx == len(email_choices) - 1)

    email_row.connect("notify::selected", sync_other)
    name_row.set_text((local_n if use_local else global_n) or "")
    git_group.add(name_row)
    git_group.add(email_row)
    git_group.add(other_email)
    save_git = Gtk.Button(label="Save Git config")

    def _selected_email() -> str:
        idx = email_row.get_selected()
        if idx < 0 or idx >= len(email_choices) - 1:
            return other_email.get_text().strip()
        model = email_row.get_model()
        return model.get_string(idx) if model is not None else other_email.get_text().strip()

    def apply_location(*_a: Any) -> None:
        local = local_check.get_active()
        name_row.set_sensitive(local)
        email_row.set_sensitive(local)
        other_email.set_sensitive(local)
        if local:
            name_row.set_text(local_n or global_n or "")
        else:
            name_row.set_text(global_n or "")
        sync_other()

    def save_g(*_a: Any) -> None:
        def apply_config() -> None:
            if local_check.get_active():
                set_config_value(repo.path, "user.name", name_row.get_text())
                set_config_value(repo.path, "user.email", _selected_email())
            else:
                remove_config_value(repo.path, "user.name")
                remove_config_value(repo.path, "user.email")

        try:
            apply_config()
        except GitError as exc:
            if not _handle_config_lock(parent, exc, apply_config):
                store.show_popup(PopupType.ERROR, error=str(exc))

    global_check.connect("toggled", apply_location)
    local_check.connect("toggled", apply_location)
    save_git.connect("clicked", save_g)
    git_group.add(save_git)
    git_page.add(git_group)
    apply_location()

    fork_group = Adw.PreferencesGroup(title="Contribute to")
    fork_group.set_description("When this repository is a fork, choose whether to contribute to the parent or the fork.")
    parent_row = Adw.SwitchRow(title="Contribute to the parent repository")
    parent_row.set_active(repo.workflow_preferences.get("fork_target") != "Self")
    parent_row.set_subtitle("When off, fetch, issues, and pull requests target the fork itself.")
    fork_group.add(parent_row)

    def persist_fork(*_a: Any) -> None:
        from ..models import ForkContributionTarget

        store.set_fork_contribution_target(
            repo,
            ForkContributionTarget.PARENT if parent_row.get_active() else ForkContributionTarget.SELF,
        )

    parent_row.connect("notify::active", persist_fork)
    if repo.is_fork:
        fork_page.add(fork_group)

    dialog.add(remote_page)
    dialog.add(ignore_page)
    dialog.add(git_page)
    if repo.is_fork:
        dialog.add(fork_page)
    dialog.present(parent)


def show_preferences(parent: Gtk.Window, store: AppStore) -> None:
    dialog = Adw.PreferencesDialog()
    dialog.set_title("Preferences")
    s = store.settings

    accounts = Adw.PreferencesPage(title="Accounts", icon_name="system-users-symbolic")
    dotcom_group = Adw.PreferencesGroup(title="GitHub.com")
    ent_group = Adw.PreferencesGroup(title="GitHub Enterprise")
    dotcom_accounts = [a for a in store.accounts if a.is_dotcom]
    ent_accounts = [a for a in store.accounts if not a.is_dotcom]

    def _sign_out_row(account) -> Adw.ActionRow:
        row = Adw.ActionRow(title=account.login, subtitle=account.friendly_endpoint)
        row.add_prefix(
            Avatar(
                account.name or account.login,
                account.emails[0] if account.emails else "",
                login=account.login,
                avatar_url=account.avatar_url,
                size=28,
            )
        )
        btn = Gtk.Button(label="Sign out")
        btn.connect("clicked", lambda _b, a=account: (store.sign_out(a), dialog.close()))
        row.add_suffix(btn)
        return row

    def _prefs_sign_in_cta(*, enterprise: bool) -> Adw.ActionRow:
        if enterprise:
            title = "Sign into GitHub Enterprise"
            message = "If you are using GitHub Enterprise at work, sign in to it to get access to your repositories."
        else:
            title = "Sign into GitHub.com"
            message = "Sign in to your GitHub.com account to access your repositories."
        row = Adw.ActionRow(title=title, subtitle=message)
        row.add_css_class("call-to-action")
        btn = Gtk.Button(label=title)
        btn.add_css_class("suggested-action")
        btn.set_valign(Gtk.Align.CENTER)

        def go(*_a: Any) -> None:
            dialog.close()
            store.begin_sign_in(enterprise)

        btn.connect("clicked", go)
        row.add_suffix(btn)
        row.set_activatable(False)
        return row

    if dotcom_accounts:
        for account in dotcom_accounts:
            dotcom_group.add(_sign_out_row(account))
    else:
        dotcom_group.add(_prefs_sign_in_cta(enterprise=False))
    if ent_accounts:
        for account in ent_accounts:
            ent_group.add(_sign_out_row(account))
        add_row = Adw.ActionRow(title="Add GitHub Enterprise account")
        add_ent = Gtk.Button(label="Add GitHub Enterprise account")
        add_ent.connect("clicked", lambda *_: (dialog.close(), store.begin_sign_in(True)))
        add_row.add_suffix(add_ent)
        ent_group.add(add_row)
    else:
        ent_group.add(_prefs_sign_in_cta(enterprise=True))
    accounts.add(dotcom_group)
    accounts.add(ent_group)

    integrations = Adw.PreferencesPage(title="Integrations", icon_name="applications-engineering-symbolic")
    ed_group = Adw.PreferencesGroup(title="External editor")
    editors = get_available_editors()
    CUSTOM_EDITOR = "Configure custom editor…"
    CUSTOM_SHELL = "Configure custom shell…"
    editor_names = [e.name for e in editors] + [CUSTOM_EDITOR]
    editor_row = Adw.ComboRow(title="Editor")
    editor_row.set_model(Gtk.StringList.new(editor_names or [CUSTOM_EDITOR]))
    if s.use_custom_editor or not editors:
        editor_row.set_selected(max(0, len(editor_names) - 1))
    elif s.selected_external_editor:
        for i, e in enumerate(editors):
            if e.name == s.selected_external_editor:
                editor_row.set_selected(i)
                break
    ed_path = Adw.EntryRow(title="Editor path")
    ed_path.set_text(s.custom_editor_path)
    ed_choose = Gtk.Button(label="Choose…")
    ed_choose.add_css_class("flat")

    def choose_editor(*_a: Any) -> None:
        picker = Gtk.FileDialog(title="Choose editor")

        def done(d, result) -> None:
            try:
                picked = d.open_finish(result)
            except Exception:
                return
            if picked:
                ed_path.set_text(picked.get_path() or "")

        picker.open(parent, None, done)

    ed_choose.connect("clicked", choose_editor)
    ed_path.add_suffix(ed_choose)
    ed_args = Adw.EntryRow(title="Arguments")
    ed_args.set_text(s.custom_editor_args or TARGET_PATH_ARGUMENT)
    ed_hint = Gtk.Label(
        label=f"Use {TARGET_PATH_ARGUMENT} where the file or repository path should appear.",
        wrap=True,
        xalign=0,
    )
    ed_hint.add_css_class("dim-label")
    ed_group.add(editor_row)
    ed_group.add(ed_path)
    ed_group.add(ed_args)
    ed_group.add(ed_hint)
    sh_group = Adw.PreferencesGroup(title="Shell")
    shells = get_available_shells()
    shell_names = [sh.name for sh in shells] + [CUSTOM_SHELL]
    shell_row = Adw.ComboRow(title="Shell")
    shell_row.set_model(Gtk.StringList.new(shell_names or [CUSTOM_SHELL]))
    if s.use_custom_shell or not shells:
        shell_row.set_selected(max(0, len(shell_names) - 1))
    elif s.selected_shell:
        for i, sh in enumerate(shells):
            if sh.name == s.selected_shell:
                shell_row.set_selected(i)
                break
    sh_path = Adw.EntryRow(title="Shell path")
    sh_path.set_text(s.custom_shell_path)
    sh_choose = Gtk.Button(label="Choose…")
    sh_choose.add_css_class("flat")

    def choose_shell(*_a: Any) -> None:
        picker = Gtk.FileDialog(title="Choose shell")

        def done(d, result) -> None:
            try:
                picked = d.open_finish(result)
            except Exception:
                return
            if picked:
                sh_path.set_text(picked.get_path() or "")

        picker.open(parent, None, done)

    sh_choose.connect("clicked", choose_shell)
    sh_path.add_suffix(sh_choose)
    sh_args = Adw.EntryRow(title="Arguments")
    sh_args.set_text(s.custom_shell_args or TARGET_PATH_ARGUMENT)
    sh_hint = Gtk.Label(
        label=f"Use {TARGET_PATH_ARGUMENT} where the working directory should appear.",
        wrap=True,
        xalign=0,
    )
    sh_hint.add_css_class("dim-label")
    sh_group.add(shell_row)
    sh_group.add(sh_path)
    sh_group.add(sh_args)
    sh_group.add(sh_hint)

    def sync_custom_rows(*_a: Any) -> None:
        custom_ed = editor_row.get_selected() >= len(editors)
        ed_path.set_visible(custom_ed)
        ed_args.set_visible(custom_ed)
        ed_hint.set_visible(custom_ed)
        custom_sh = shell_row.get_selected() >= len(shells)
        sh_path.set_visible(custom_sh)
        sh_args.set_visible(custom_sh)
        sh_hint.set_visible(custom_sh)

    editor_row.connect("notify::selected", sync_custom_rows)
    shell_row.connect("notify::selected", sync_custom_rows)
    sync_custom_rows()
    integrations.add(ed_group)
    integrations.add(sh_group)

    git_page = Adw.PreferencesPage(title="Git", icon_name="utilities-terminal-symbolic")
    git_group = Adw.PreferencesGroup(title="Git author")
    name_row = Adw.EntryRow(title="Name")
    n, e = get_author_identity(None)
    name_row.set_text(n or "")
    from ..models import account_email_choices

    email_choices: list[str] = []
    for account in store.accounts:
        for item in account_email_choices(account):
            if item not in email_choices:
                email_choices.append(item)
    if e and e not in email_choices:
        email_choices.insert(0, e)
    email_choices.append("Other")
    email_row = Adw.ComboRow(title="Email")
    email_row.set_model(Gtk.StringList.new(email_choices or ["Other"]))
    if e and e in email_choices:
        email_row.set_selected(email_choices.index(e))
    other_email = Adw.EntryRow(title="Other email")
    other_email.set_text(e or "")
    other_email.set_visible(False)

    def sync_other(*_a: Any) -> None:
        idx = email_row.get_selected()
        other_email.set_visible(idx >= 0 and idx == len(email_choices) - 1)

    email_row.connect("notify::selected", sync_other)
    sync_other()
    branch_row = Adw.EntryRow(title="Default branch name")
    branch_row.set_text(get_default_branch())
    git_group.add(name_row)
    git_group.add(email_row)
    git_group.add(other_email)
    git_group.add(branch_row)
    clone_row = Adw.EntryRow(title="Clone default directory")
    clone_row.set_text(s.clone_default_directory or os.path.expanduser("~/Documents/GitHub"))
    git_group.add(clone_row)
    length_row = Adw.SwitchRow(title="Show commit summary length warning", active=s.show_commit_length_warning)
    git_group.add(length_row)
    edit_cfg = Gtk.Button(label="Edit global Git config")
    edit_cfg.connect("clicked", lambda *_: (store.edit_global_git_config(), dialog.close()))
    git_group.add(edit_cfg)
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
    n_row.set_subtitle(
        "Allows the display of notifications when high-signal events take place in the current repository."
    )
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
        ("confirm_stash_all_changes", "Stashing all changes"),
        ("confirm_discard_changes_permanently", "Discarding changes permanently"),
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
    try:
        strategy.set_selected(
            [
                UncommittedChangesStrategy.ASK_FOR_CONFIRMATION.value,
                UncommittedChangesStrategy.STASH_ON_CURRENT_BRANCH.value,
                UncommittedChangesStrategy.MOVE_TO_NEW_BRANCH.value,
            ].index(s.uncommitted_changes_strategy)
        )
    except ValueError:
        strategy.set_selected(0)
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
    spell = Adw.SwitchRow(title="Enable spellcheck in commit messages", active=s.spellcheck_enabled)
    ac_group.add(underline)
    ac_group.add(checks)
    ac_group.add(spell)
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
        s.spellcheck_enabled = spell.get_active()
        s.clone_default_directory = clone_row.get_text().strip()
        s.show_commit_length_warning = length_row.get_active()
        model = strategy.get_model()
        idx = strategy.get_selected()
        if model is not None and idx >= 0:
            s.uncommitted_changes_strategy = model.get_string(idx)
        for key, row in switches.items():
            setattr(s, key, row.get_active())
        idx = editor_row.get_selected()
        if idx >= len(editors):
            s.use_custom_editor = True
            s.custom_editor_path = ed_path.get_text().strip()
            s.custom_editor_args = ed_args.get_text().strip() or TARGET_PATH_ARGUMENT
        elif 0 <= idx < len(editors):
            s.use_custom_editor = False
            s.selected_external_editor = editors[idx].name
        idx = shell_row.get_selected()
        if idx >= len(shells):
            s.use_custom_shell = True
            s.custom_shell_path = sh_path.get_text().strip()
            s.custom_shell_args = sh_args.get_text().strip() or TARGET_PATH_ARGUMENT
        elif 0 <= idx < len(shells):
            s.use_custom_shell = False
            s.selected_shell = shells[idx].name
        try:
            idx = email_row.get_selected()
            if idx < 0 or idx >= len(email_choices) - 1:
                email = other_email.get_text().strip()
            else:
                model = email_row.get_model()
                email = model.get_string(idx) if model is not None else other_email.get_text().strip()
            name = name_row.get_text()
            branch = branch_row.get_text().strip() or None

            def save_user() -> None:
                store.save_git_user(name, email, branch)

            try:
                save_user()
            except GitError as exc:
                _handle_config_lock(parent, exc, save_user)
        except ValidationError:
            pass
        store.persist_settings()
        store.apply_theme()
        store.set_zoom(s.zoom_factor)
        store.emit()

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
        store.retry_last_remote_action()

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
        from ..git.ops import checkout_branch

        state = store.state_for(repo)
        current = state.status.current_branch if state.status else "unknown"
        if response == "stash":
            store.stash_and_drop_previous(repo, current or "unknown")
            checkout_branch(repo.path, branch)
            store.remember_branch(repo, branch)
            store.refresh_repository(repo)
        elif response == "leave":
            from ..models import Branch, BranchType

            target = next((b for b in state.branches if b.name == branch), None) or Branch(
                branch, None, "", BranchType.LOCAL
            )
            store.checkout_and_bring_changes(repo, target)

    dialog.choose(parent, None, done)


def show_start_pr(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo or not repo.github:
        store.show_popup(PopupType.ERROR, error="This repository isn't on GitHub.")
        return
    store.load_pr_preview(repo)
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else "?"
    from ..models import github_for_contribution

    target = github_for_contribution(repo) or repo.github
    base_names = [b.name for b in state.branches if b.name != current]
    default = state.pr_base_branch or (target.default_branch if target else repo.github.default_branch)
    recent_bases, other_bases = group_pr_base_branches(
        base_names,
        list(state.recent_branches or []),
        current=current,
        default=default,
    )
    # prRecentBaseBranches: recent checkouts first, then the remaining remote-capable names.
    if default and default not in recent_bases and default not in other_bases and default != current:
        other_bases.insert(0, default)
    selected = {"name": default or (recent_bases[0] if recent_bases else (other_bases[0] if other_bases else ""))}

    dialog = Adw.Dialog()
    dialog.set_content_width(900)
    dialog.set_content_height(640)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Open a pull request", subtitle=f"{current} → {selected['name']}"))
    toolbar.add_top_bar(header)

    root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    root.set_margin_start(12)
    root.set_margin_end(12)
    root.set_margin_top(8)
    root.set_margin_bottom(8)
    details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    merge_into = Gtk.Label(wrap=True, xalign=0)
    merge_into.add_css_class("base-branch-details")
    details.append(merge_into)
    stats = Gtk.Label(xalign=0, hexpand=True)
    stats.add_css_class("lines-added-deleted")
    details.append(stats)
    merge_info = Gtk.Label(wrap=True, xalign=0)
    merge_info.add_css_class("merge-info")
    details.append(merge_info)
    root.append(details)

    base_btn = Gtk.MenuButton()
    base_btn.set_halign(Gtk.Align.START)
    base_label = Gtk.Label(label=selected["name"] or "Base")
    base_child = Gtk.Box(spacing=6)
    base_child.append(Gtk.Label(label="Base"))
    base_child.append(base_label)
    base_btn.set_child(base_child)
    popover = Gtk.Popover()
    list_wrap = Gtk.ScrolledWindow()
    list_wrap.set_min_content_height(220)
    list_wrap.set_min_content_width(280)
    base_list = Gtk.ListBox()
    base_list.add_css_class("boxed-list")
    list_wrap.set_child(base_list)
    popover.set_child(list_wrap)
    base_btn.set_popover(popover)
    root.append(base_btn)

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
    draft = Gtk.CheckButton(label="Create as draft")
    root.append(title_row)
    root.append(body_row)
    root.append(draft)
    actions = Gtk.Box(spacing=8)
    create_btn = Gtk.Button(label="Create pull request")
    create_btn.add_css_class("suggested-action")
    view_btn = Gtk.Button(label="View pull request")
    view_btn.set_visible(bool(state.current_pull_request))
    actions.append(create_btn)
    actions.append(view_btn)
    root.append(actions)

    def _preview_kwargs():
        st = store.state_for(repo)
        return {
            "show_checks": False,
            "side_by_side": st.side_by_side or store.settings.show_side_by_side_diff,
            "image_mode": st.image_diff_type or store.settings.image_diff_type,
            "hide_whitespace": st.hide_whitespace or store.settings.hide_whitespace_in_diffs,
        }

    def _fill_base_list() -> None:
        while True:
            row = base_list.get_first_child()
            if row is None:
                break
            base_list.remove(row)
        def add_header(title: str) -> None:
            header_row = Gtk.ListBoxRow()
            header_row.set_selectable(False)
            header_row.set_activatable(False)
            label = Gtk.Label(label=title, xalign=0)
            label.add_css_class("dim-label")
            header_row.set_child(label)
            base_list.append(header_row)

        def add_name(name: str) -> None:
            row = Gtk.ListBoxRow()
            row.set_child(Gtk.Label(label=name, xalign=0))
            row.branch_name = name  # type: ignore[attr-defined]
            base_list.append(row)

        if recent_bases:
            add_header("Recent")
            for name in recent_bases:
                add_name(name)
        if other_bases:
            add_header("Other branches")
            for name in other_bases:
                add_name(name)
        if not recent_bases and not other_bases:
            empty = Gtk.ListBoxRow()
            empty.set_selectable(False)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.append(Gtk.Label(label="Sorry, I can't find that remote branch.", wrap=True, xalign=0))
            box.append(Gtk.Label(label="You can only open pull requests against remote branches.", wrap=True, xalign=0))
            empty.set_child(box)
            base_list.append(empty)

    def render_preview() -> None:
        st = store.state_for(repo)
        cs = st.pr_changeset
        n = len(st.pr_commits)
        added = cs.lines_added if cs else 0
        deleted = cs.lines_deleted if cs else 0
        files_n = len(st.pr_files)
        base_name = selected["name"] or default
        commit_word = "commit" if n == 1 else "commits"
        merge_into.set_text(f"Merge {n} {commit_word} into {base_name} from {current}.")
        if n == 0:
            stats.set_text("No commits to merge into the base branch")
            merge_info.set_text("")
        else:
            stats.set_text(f"{files_n} files · {added} added lines, {deleted} removed lines")
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
        kwargs = _preview_kwargs()
        if st.pr_files:
            diff = store.load_pr_preview_diff(repo, st.pr_files[0])
            viewer.render(diff, path=st.pr_files[0].path, **kwargs)
        else:
            viewer.render(None)

    def on_file(_l, row) -> None:
        file = getattr(row, "_file", None)
        if file:
            diff = store.load_pr_preview_diff(repo, file)
            viewer.render(diff, path=file.path, **_preview_kwargs())

    file_list.connect("row-activated", on_file)

    def on_base(_l, row) -> None:
        name = getattr(row, "branch_name", "") or ""
        if not name:
            return
        selected["name"] = name
        base_label.set_text(name)
        store.load_pr_preview(repo, name)
        header.set_title_widget(Adw.WindowTitle(title="Open a pull request", subtitle=f"{current} → {name}"))
        popover.popdown()
        render_preview()

    base_list.connect("row-activated", on_base)

    def create(*_a: Any) -> None:
        base = selected["name"] or default
        dialog.close()
        store.create_pull_request(repo, title_row.get_text().strip() or current, base, body_row.get_text().strip(), draft=draft.get_active())

    def view(*_a: Any) -> None:
        st = store.state_for(repo)
        if st.current_pull_request:
            dialog.close()
            open_external(st.current_pull_request.html_url)

    create_btn.connect("clicked", create)
    view_btn.connect("clicked", view)
    _fill_base_list()
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
        from ..errors import GitError
        from ..git.ops import install_global_lfs_filters, lfs_track

        try:
            install_global_lfs_filters()
        except GitError as exc:
            if exc.is_lfs_attribute_mismatch:
                dialog.close()
                store.show_popup(PopupType.LFS_ATTRIBUTE_MISMATCH)
                return
            store.show_popup(PopupType.ERROR, error=str(exc))
            return
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
    secret = payload.get("secret")
    description = "secret"
    if secret is not None:
        description = getattr(secret, "description", None) or "secret"
    description = payload.get("description") or description

    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(
            title="Bypass push detection",
            subtitle=f"Why are you bypassing this {description}?",
        )
    )
    cancel = Gtk.Button(label="Cancel")
    ok = Gtk.Button(label="Allow me to expose this secret")
    ok.add_css_class("destructive-action")
    header.pack_start(cancel)
    header.pack_end(ok)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.set_margin_top(12)
    box.set_margin_bottom(18)
    box.set_margin_start(12)
    box.set_margin_end(12)
    reasons = [
        (
            BypassReason.USED_IN_TESTS,
            "It's used in tests",
            "The secret poses no risk. If anyone finds it, they cannot do any damage or gain access to sensitive information.",
        ),
        (
            BypassReason.FALSE_POSITIVE,
            "It's a false positive",
            "The detected string is not a secret",
        ),
        (
            BypassReason.WILL_FIX_LATER,
            "I'll fix it later",
            "The secret is real, I understand the risk, and I will need to revoke it. This will open a security alert and notify admins of this repository.",
        ),
    ]
    group = None
    selected = {"reason": BypassReason.FALSE_POSITIVE}

    def on_toggled(btn: Gtk.CheckButton, reason: BypassReason) -> None:
        if btn.get_active():
            selected["reason"] = reason

    for reason, title, body in reasons:
        check = Gtk.CheckButton()
        if group is None:
            group = check
        else:
            check.set_group(group)
        if reason == BypassReason.FALSE_POSITIVE:
            check.set_active(True)
        check.connect("toggled", on_toggled, reason)
        row = Adw.ActionRow(title=title, subtitle=body)
        row.set_activatable_widget(check)
        row.add_prefix(check)
        box.append(row)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    closed = {"done": False}

    def close(*_a: Any) -> None:
        if not closed["done"]:
            closed["done"] = True
            dialog.close()

    def submit(*_a: Any) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        dialog.close()
        from ..github.api import GitHubAPI

        placeholder_id = payload.get("placeholder_id") or (
            getattr(secret, "id", None) if secret is not None else None
        )
        GitHubAPI.from_account(account).create_push_protection_bypass(
            repo.github.owner, repo.github.name, selected["reason"].value, placeholder_id=placeholder_id
        )
        store.push_repo(repo)

    cancel.connect("clicked", close)
    ok.connect("clicked", submit)
    dialog.present(parent)


def show_create_fork(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    account = store.account_for_repo(repo) if repo else None
    if not repo or not repo.github or not account:
        return

    def confirm() -> None:
        store.create_fork(repo)

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

    def cancel() -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(None, False)

    _text_dialog(
        parent,
        "SSH key passphrase",
        payload.get("key_path") or "",
        [("passphrase", "Passphrase", "")],
        submit,
        "Continue",
        on_cancel=cancel,
    )


def show_ssh_password(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    def submit(values: dict[str, str]) -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(values.get("password") or None, True)

    def cancel() -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(None, False)

    _text_dialog(
        parent,
        "SSH password",
        payload.get("username") or "",
        [("password", "Password", "")],
        submit,
        "Continue",
        on_cancel=cancel,
    )


def show_commit_message_dialog(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    def submit(values: dict[str, str]) -> None:
        cb = payload.get("on_submit")
        if cb:
            cb(values.get("summary") or "", values.get("description") or "")

    fields = [
        ("summary", "Summary", payload.get("summary") or ""),
        ("description", "Description", payload.get("description") or ""),
    ]
    if payload.get("show_co_authors"):
        fields.append(("co_authors", "Co-authors", payload.get("co_authors") or ""))
    _text_dialog(
        parent,
        payload.get("title") or "Commit message",
        payload.get("body") or "",
        fields,
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
        from .markdown import issue_base_from_html_url, sandboxed_markdown_label

        box.append(
            sandboxed_markdown_label(
                body,
                issue_base_url=issue_base_from_html_url(html_url),
                max_chars=4000,
            )
        )
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
