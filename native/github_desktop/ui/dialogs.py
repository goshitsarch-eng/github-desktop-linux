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
from ..stats import SamplesURL
from ..editors import SUGGESTED_EXTERNAL_EDITOR, SUGGESTED_EXTERNAL_EDITOR_URL, get_available_editors
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
    PreferencesTab,
    PublishTab,
    RepositorySettingsTab,
    SignInStep,
    UncommittedChangesStrategy,
    git_author_name_is_valid,
    group_pr_base_branches,
    is_dotcom_endpoint,
    map_status,
    path_label,
    pr_base_branches,
    accounts_for_publish_tab,
    default_publish_tab,
    uncommitted_changes_strategy_choices,
)
from ..settings import get_default_dir, set_default_dir
from ..shells import get_available_shells, open_external
from ..store import AppStore
from ..text_tokens import MaxSummaryLength
from ..version import APP_NAME, __version__
from .avatar import Avatar
from .autocompletion import (
    UNREACHABLE_COMMITS_LEARN_MORE,
    TextViewCompleter,
    fill_coauthor_store,
    install_entry_completion,
    populate_completion_store,
    protected_branch_warning,
    summary_length_hint,
    token_before_cursor,
    unreachable_commits_message,
    write_access_warning,
)
from .author_input import AuthorInput
from .checks import show_checks, show_rerun_checks
from .diff_view import DiffViewer
from .menus import (
    TrashNameLabel,
    attach_right_click,
    committed_file_context_items,
    open_in_editor_label,
    show_context_menu,
    view_on_github_label,
)
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


def _author_name_error_row(name_row: Adw.EntryRow) -> Gtk.ListBoxRow:
    """Desktop Git config `InvalidGitAuthorNameMessage` under the name field."""
    label = Gtk.Label(label=INVALID_GIT_AUTHOR_NAME_MESSAGE, wrap=True, xalign=0)
    label.add_css_class("error")
    box = Gtk.Box()
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.set_margin_top(4)
    box.set_margin_bottom(8)
    box.append(label)
    row = Gtk.ListBoxRow()
    row.set_activatable(False)
    row.set_selectable(False)
    row.set_child(box)

    def refresh(*_a: object) -> None:
        row.set_visible(not git_author_name_is_valid(name_row.get_text()))

    name_row.connect("notify::text", refresh)
    refresh()
    return row


def show_editor_failed(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    message = str(payload.get("message") or "Unable to open the selected editor.")
    if payload.get("open_preferences"):
        _alert(
            parent,
            "Unable to open external editor",
            message,
            confirm="Close",
            cancel="Open options",
            on_cancel=lambda: show_preferences(parent, store, PreferencesTab.INTEGRATIONS),
        )
        return
    if payload.get("suggest_default_editor"):
        _alert(
            parent,
            "Unable to open external editor",
            message,
            confirm="Close",
            cancel=f"Download {SUGGESTED_EXTERNAL_EDITOR}",
            on_cancel=lambda: open_external(SUGGESTED_EXTERNAL_EDITOR_URL),
        )
        return
    _alert(parent, "Unable to open external editor", message, cancel=None)


def show_shell_failed(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    _alert(
        parent,
        "Unable to open shell",
        str(payload.get("message") or "Unable to open the selected shell."),
        confirm="Close",
        cancel="Open options",
        on_cancel=lambda: show_preferences(parent, store, PreferencesTab.INTEGRATIONS),
    )


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
    dialog.connect("closed", cancel_clicked)
    dialog.present(parent)


def _coerce_enum(raw: Any, enum_cls: Any) -> Any:
    if isinstance(raw, enum_cls):
        return raw
    if isinstance(raw, str):
        try:
            return enum_cls(raw)
        except ValueError:
            return None
    return None


def present_popup(parent: Gtk.Window, store: AppStore, popup_type: PopupType, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    mapping: dict[PopupType, Callable[..., None]] = {
        PopupType.ERROR: lambda: show_error_dialog(parent, store, payload),
        PopupType.ABOUT: lambda: show_about(parent),
        PopupType.ACKNOWLEDGEMENTS: lambda: show_acknowledgements(parent),
        PopupType.TERMS_AND_CONDITIONS: lambda: show_terms(parent),
        PopupType.PREFERENCES: lambda: show_preferences(
            parent,
            store,
            _coerce_enum(payload.get("tab") or payload.get("initialSelectedTab"), PreferencesTab),
        ),
        PopupType.ADD_REPOSITORY: lambda: show_add_repository(parent, store, payload.get("path", "")),
        PopupType.CREATE_REPOSITORY: lambda: show_create_repository(parent, store, payload.get("path", "")),
        PopupType.CLONE_REPOSITORY: lambda: show_clone_repository(parent, store, payload),
        PopupType.SIGN_IN: lambda: show_sign_in(parent, store, bool(payload.get("enterprise")), payload),
        PopupType.CREATE_BRANCH: lambda: show_create_branch(parent, store, payload),
        PopupType.RENAME_BRANCH: lambda: show_rename_branch(parent, store, payload),
        PopupType.DELETE_BRANCH: lambda: show_delete_branch(parent, store, payload),
        PopupType.DELETE_REMOTE_BRANCH: lambda: show_delete_branch(parent, store, payload, remote=True),
        PopupType.CONFIRM_DISCARD_CHANGES: lambda: show_discard(parent, store, payload),
        PopupType.PUBLISH_REPOSITORY: lambda: show_publish(parent, store),
        PopupType.REMOVE_REPOSITORY: lambda: show_remove_repository(parent, store),
        PopupType.REPOSITORY_SETTINGS: lambda: show_repository_settings(
            parent,
            store,
            _coerce_enum(payload.get("tab") or payload.get("initialSelectedTab"), RepositorySettingsTab),
        ),
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
        PopupType.INSTALL_GIT: lambda: show_install_git(parent, store, payload),
        PopupType.CLI_INSTALLED: lambda: _alert(
            parent,
            "CLI installed",
            f"The github command is available at {payload.get('path') or str(Path.home() / '.local' / 'bin' / 'github')}.",
            cancel=None,
        ),
        PopupType.INITIALIZE_LFS: lambda: show_initialize_lfs(parent, store, payload),
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
            on_confirm=lambda: store.begin_sign_in_for_endpoint(
                payload.get("endpoint")
                or (
                    store.selected_repository.github.endpoint
                    if store.selected_repository and store.selected_repository.github
                    else ""
                )
            ),
        ),
        PopupType.PUSH_PROTECTION_ERROR: lambda: show_push_protection(parent, store, payload),
        PopupType.CREATE_FORK: lambda: show_create_fork(parent, store, payload),
        PopupType.CHOOSE_FORK_SETTINGS: lambda: show_fork_settings(parent, store),
        PopupType.CHANGE_REPOSITORY_ALIAS: lambda: show_alias(parent, store),
        PopupType.EXTERNAL_EDITOR_FAILED: lambda: show_editor_failed(parent, store, payload),
        PopupType.OPEN_SHELL_FAILED: lambda: show_shell_failed(parent, store, payload),
        PopupType.INVALIDATED_TOKEN: lambda: _alert(
            parent,
            "Invalidated account token",
            "Your account token has been invalidated and you have been signed out. Do you want to sign in again?",
            confirm="Yes",
            cancel="No",
            on_confirm=lambda: store.begin_sign_in(not bool(getattr(payload.get("account"), "is_dotcom", True))),
        ),
        PopupType.ADD_SSH_HOST: lambda: _alert(
            parent,
            "SSH Host",
            (
                f"The authenticity of host '{payload.get('host', '')} ({payload.get('ip', '')})' can't "
                f"be established. {payload.get('key_type', '')} key fingerprint is "
                f"{payload.get('fingerprint', '')}.\n\n"
                "Are you sure you want to continue connecting?"
            ),
            confirm="Yes",
            cancel="No",
            on_confirm=lambda: payload.get("on_submit") and payload["on_submit"](True),
            on_cancel=lambda: payload.get("on_submit") and payload["on_submit"](False),
        ),
        PopupType.SSH_KEY_PASSPHRASE: lambda: show_ssh_passphrase(parent, payload),
        PopupType.SSH_USER_PASSWORD: lambda: show_ssh_password(parent, payload),
        PopupType.CONFIRM_COMMIT_FILTERED_CHANGES: lambda: show_filtered_commit(parent, store, payload),
        PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER: lambda: show_copilot_disclaimer(parent, store),
        PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE: lambda: _alert_with_check(
            parent,
            "Commit message override",
            "The commit message you have entered will be overridden by the generated commit message.",
            confirm="Override",
            destructive=True,
            on_confirm=lambda skip: _on_override_commit_message(store, skip),
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
    from ..errors import is_auth_failure_error
    from ..git_error_context import error_dialog_title, format_app_error_body

    heading = error_dialog_title(
        git_context=payload.get("git_context"),
        retry_action=payload.get("retry_action"),
        title=payload.get("title"),
        retry_clone=bool(payload.get("retry_clone")),
        git_error=payload.get("git_error"),
        copilot_quota=bool(payload.get("copilot_quota")),
    )
    body = format_app_error_body(
        str(payload.get("error") or "Something went wrong"),
        git_error=payload.get("git_error"),
        stderr=str(payload.get("stderr") or ""),
        copilot_quota=bool(payload.get("copilot_quota")),
    )
    retry = payload.get("retry")
    if payload.get("retry_clone"):
        name = payload.get("name") or ""
        if name:
            body = f"{body}\n\nWould you like to retry cloning {name}?"
    if callable(retry):
        auth = bool(payload.get("open_preferences")) or is_auth_failure_error(payload.get("git_error"))
        if not auth:
            auth = "authentication failed" in body.lower() or "File > Options." in body
        _alert(
            parent,
            heading,
            body,
            confirm="Retry",
            cancel="Open options" if auth else "Close",
            on_confirm=retry,
            on_cancel=(lambda: show_preferences(parent, store, PreferencesTab.ACCOUNTS)) if auth else None,
        )
        return
    auth = bool(payload.get("open_preferences")) or is_auth_failure_error(payload.get("git_error"))
    lower = body.lower()
    if not auth:
        auth = "authentication failed" in lower or "File > Options." in body
    if auth:
        _alert(
            parent,
            heading,
            body,
            confirm="Close",
            cancel="Open options",
            on_cancel=lambda: show_preferences(parent, store, PreferencesTab.ACCOUNTS),
        )
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


def _on_override_commit_message(store: AppStore, skip: bool) -> None:
    if skip:
        store.settings.confirm_commit_message_override = False
        store.persist_settings()
    _generate(store)


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
    from ..models import RetryAction

    state = store.state_for(repo)
    stash_push(repo.path, state.status.current_branch if state.status else "unknown")
    retry = payload.get("retry")
    if callable(retry):
        retry()
        return
    action = payload.get("retry_action")
    if isinstance(action, RetryAction) or isinstance(action, dict):
        store.perform_retry(action)
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
            store.begin_sign_in_for_endpoint(payload.get("endpoint") or endpoint)

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
    """Desktop `About` for Linux: version/arch, notes, terms, licenses; no auto-update."""
    import platform

    dialog = Adw.Dialog()
    dialog.set_content_width(440)
    try:
        dialog.set_name("about")
    except Exception:
        pass
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=f"About {APP_NAME}"))
    close = Gtk.Button(label="Close")
    close.add_css_class("suggested-action")
    header.pack_end(close)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    icon = Gtk.Image.new_from_icon_name("io.github.desktop.GitHubDesktop")
    icon.set_pixel_size(64)
    icon.set_halign(Gtk.Align.CENTER)
    title = Gtk.Label(label=f"About {APP_NAME}")
    title.add_css_class("title-2")
    arch = platform.machine() or "unknown"
    version = Gtk.Label(label=f"Version {__version__} ({arch})", selectable=True)
    version.add_css_class("dim-label")
    notes = Gtk.Button(label="release notes")
    notes.add_css_class("flat")
    notes.set_halign(Gtk.Align.CENTER)
    terms = Gtk.Button(label="Terms and Conditions")
    terms.add_css_class("flat")
    terms.set_halign(Gtk.Align.START)
    notices = Gtk.Button(label="License and Open Source Notices")
    notices.add_css_class("flat")
    notices.set_halign(Gtk.Align.START)
    copilot = Gtk.LinkButton(
        uri="https://gh.io/copilot-for-desktop-transparency",
        label="Responsible use of Copilot in GitHub Desktop",
    )
    copilot.set_halign(Gtk.Align.START)
    box.append(icon)
    box.append(title)
    box.append(version)
    box.append(notes)
    box.append(terms)
    box.append(notices)
    box.append(copilot)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    close.connect("clicked", lambda *_: dialog.close())
    notes.connect("clicked", lambda *_: show_release_notes(parent))
    terms.connect("clicked", lambda *_: show_terms(parent))
    notices.connect("clicked", lambda *_: show_acknowledgements(parent))
    dialog.present(parent)


def show_acknowledgements(parent: Gtk.Window) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(560)
    dialog.set_content_height(480)
    try:
        dialog.set_name("acknowledgements")
    except Exception:
        pass
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(
        Adw.WindowTitle(title="License and Open Source Notices", subtitle="Open source licenses")
    )
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    inner.set_margin_top(12)
    inner.set_margin_bottom(12)
    inner.set_margin_start(12)
    inner.set_margin_end(12)
    intro = Gtk.Label(
        wrap=True,
        xalign=0,
        label=(
            "GitHub Desktop is an open source project published under the MIT License. "
            "You can view the source code and contribute to this project on GitHub."
        ),
    )
    links = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    links.append(Gtk.LinkButton(uri="https://desktop.github.com", label="GitHub Desktop"))
    links.append(
        Gtk.LinkButton(
            uri="https://github.com/goshitsarch-eng/github-desktop-linux",
            label="GitHub",
        )
    )
    inner.append(intro)
    inner.append(links)
    license_text = ""
    for candidate in (
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "LICENSE"),
        os.path.join(os.path.dirname(__file__), "..", "..", "LICENSE"),
        "/workspace/LICENSE",
    ):
        path = os.path.abspath(candidate)
        if os.path.isfile(path):
            try:
                license_text = Path(path).read_text(encoding="utf-8")
            except OSError:
                license_text = ""
            break
    if not license_text:
        license_text = "MIT License. Copyright (c) GitHub, Inc."
    mit = Gtk.Label(wrap=True, xalign=0, selectable=True, label=license_text)
    mit.add_css_class("monospace")
    inner.append(mit)
    deps = Gtk.Label(label="This Linux port also uses:", xalign=0)
    deps.add_css_class("heading")
    inner.append(deps)
    for name, license_id, url in (
        ("GTK", "LGPL-2.1", "https://gitlab.gnome.org/GNOME/gtk"),
        ("libadwaita", "LGPL-2.1", "https://gitlab.gnome.org/GNOME/libadwaita"),
        ("PyGObject", "LGPL-2.1", "https://gitlab.gnome.org/GNOME/pygobject"),
        ("Git", "GPL-2.0", "https://git-scm.com"),
    ):
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row.append(Gtk.LinkButton(uri=url, label=name))
        row.append(Gtk.Label(label=f"License: {license_id}", xalign=0))
        inner.append(row)
    scroller.set_child(inner)
    toolbar.set_content(scroller)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_terms(parent: Gtk.Window) -> None:
    open_external("https://docs.github.com/en/site-policy/github-terms/github-terms-of-service")


def show_release_notes(parent: Gtk.Window) -> None:
    from ..desktop_fake_repository import DesktopFakeRepository
    from .markdown import sandboxed_markdown_label

    version, notes = load_release_notes()
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Release notes", subtitle=f"GitHub Desktop {version}"))
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    for note in notes:
        notes_box.append(
            sandboxed_markdown_label(note, repository=DesktopFakeRepository, empty=note or "")
        )
    scroller.set_child(notes_box)
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
        from ..desktop_fake_repository import DesktopFakeRepository
        from .markdown import sandboxed_markdown_label

        for line in contributions[:12]:
            box.append(sandboxed_markdown_label(line, repository=DesktopFakeRepository, empty=line))
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
    default = get_default_dir(store.settings)
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
            store.show_popup(
                PopupType.ERROR,
                error=str(exc),
                git_context={"kind": "create-repository"},
            )

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
    selected_clone_url: dict[str, str] | None = None,
    url_row: Adw.EntryRow | None = None,
    path_row: Adw.EntryRow | None = None,
    default_dir: str = "",
    empty_title: str,
    on_pick: Callable[[Any], None] | None = None,
) -> None:
    from ..clone_groups import group_cloneable_repositories
    from ..fuzzy_find import filter_items

    _clear_listbox(listbox)
    any_shown = False
    query = needle.strip()
    for title, items in group_cloneable_repositories(list(repos), login):
        filtered = filter_items(
            query,
            items,
            lambda gh: [gh.full_name, f"{gh.html_url} {gh.name}"],
        )
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
                if selected_clone_url is not None:
                    selected_clone_url["url"] = g.clone_url
                    selected_clone_url["name"] = g.name
                if url_row is not None:
                    url_row.set_text(g.clone_url)
                if path_row is not None:
                    path_row.set_text(os.path.join(default_dir, g.name))
                if on_pick is not None:
                    on_pick(g)

            row.connect("activated", pick)
            listbox.append(row)
            any_shown = True
    if not any_shown:
        listbox.append(Adw.ActionRow(title=empty_title))


def _clone_list_empty_title(account, needle: str) -> str:
    """Desktop `CloneableRepositoryFilterList` empty copy."""
    if needle:
        return f"Sorry, I can't find any repository matching {needle}"
    login = getattr(account, "login", "") or ""
    host = getattr(account, "friendly_endpoint", None) or "GitHub"
    return f"Looks like there are no repositories for {login} on {host}."


def _clone_list_loading_title(account) -> str:
    """Desktop `Loading repositories from ${account.friendlyEndpoint}…`."""
    host = getattr(account, "friendly_endpoint", None) or "GitHub"
    return f"Loading repositories from {host}…"


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

    default_dir = get_default_dir(store.settings)
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
    gh_filter.set_placeholder_text("Filter your repositories")
    gh_filter.set_hexpand(True)
    refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
    refresh_btn.set_tooltip_text("Refresh the list of repositories")
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
    ent_filter.set_placeholder_text("Filter your repositories")
    ent_filter.set_hexpand(True)
    ent_refresh = Gtk.Button(icon_name="view-refresh-symbolic")
    ent_refresh.set_tooltip_text("Refresh the list of repositories")
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

    def repos_for(account) -> tuple[list, bool]:
        state = store.api_repositories.get_account_state(account) if account else None
        if state is None:
            return [], True
        return list(state.repositories), state.loading

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
        loaded, loading = repos_for(account)
        refresh_btn.set_sensitive(not loading)
        if loading and not loaded:
            _clear_listbox(repo_list)
            repo_list.append(Adw.ActionRow(title=_clone_list_loading_title(account)))
            return
        needle = gh_filter.get_text().strip()
        empty = _clone_list_empty_title(account, needle)
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

    def fill_github(*_a: Any, force: bool = False) -> None:
        account = selected_account()
        render_github_list()
        if account and (force or store.api_repositories.get_account_state(account) is None):
            store.refresh_api_repositories(account)

    fill_github()
    gh_filter.connect("search-changed", lambda *_: render_github_list())
    refresh_btn.connect("clicked", lambda *_: fill_github(force=True))
    if account_drop is not None:
        account_drop.connect("notify::selected", fill_github)

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
        loaded_ent, loading = repos_for(account)
        ent_refresh.set_sensitive(not loading)
        if loading and not loaded_ent:
            _clear_listbox(ent_list)
            ent_list.append(Adw.ActionRow(title=_clone_list_loading_title(account)))
            return
        needle = ent_filter.get_text().strip()
        empty = _clone_list_empty_title(account, needle)
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

    def fill_enterprise(*_a: Any, force: bool = False) -> None:
        account = selected_account(True)
        render_enterprise_list()
        if account and (force or store.api_repositories.get_account_state(account) is None):
            store.refresh_api_repositories(account)

    fill_enterprise()
    ent_filter.connect("search-changed", lambda *_: render_enterprise_list())
    ent_refresh.connect("clicked", lambda *_: fill_enterprise(force=True))
    if ent_drop is not None:
        ent_drop.connect("notify::selected", fill_enterprise)

    def on_api_repos() -> None:
        render_github_list()
        render_enterprise_list()

    unsub = store.api_repositories.subscribe(on_api_repos)

    def _unsub(*_a: Any) -> None:
        unsub()

    try:
        dialog.connect("closed", _unsub)
    except TypeError:
        dialog.connect("destroy", _unsub)

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


def show_sign_in(
    parent: Gtk.Window,
    store: AppStore,
    enterprise: bool,
    payload: dict[str, Any] | None = None,
) -> None:
    payload = payload or {}
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
    helper_url = str(payload.get("credential_helper_url") or store.sign_in_credential_helper_url or "")

    def clear() -> None:
        while (child := box.get_first_child()) is not None:
            box.remove(child)

    def render(*_a: Any) -> None:
        clear()
        step = store.sign_in_step
        existing = store.sign_in_existing
        if helper_url:
            # Desktop SignIn `isCredentialHelperSignIn` / `credentialHelperUrl`
            banner = Gtk.Label(
                label=f"GitHub Desktop needs access to {helper_url}. Sign in to continue.",
                wrap=True,
                xalign=0,
            )
            banner.add_css_class("warning")
            box.append(banner)
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

    def on_closed(*_a: Any) -> None:
        if store.sign_in_step != SignInStep.SUCCESS:
            store._finish_credential_sign_in(None)

    dialog.connect("closed", on_closed)
    dialog.present(parent)


def show_create_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..create_branch import get_start_point, upstream_default_branch_for
    from ..github.repo_rules import use_repo_rules_logic
    from ..models import (
        BranchType,
        StartPoint,
        TipState,
        sanitize_ref_name,
    )

    state = store.state_for(repo)
    payload = payload or {}
    target_sha = str(payload.get("start") or "")
    current = state.status.current_branch if state.status else None
    current_tip = state.status.current_tip if state.status else None
    default_name = store.default_branch_name(repo)
    default_branch = next((b for b in state.branches if b.name == default_name and b.type == BranchType.LOCAL), None)
    if default_branch is None and default_name:
        default_branch = next((b for b in state.branches if b.name_without_remote == default_name), None)
    upstream_default = upstream_default_branch_for(repo, list(state.branches), default_name)
    detached = bool(state.status and state.status.current_tip and not current)
    unborn = bool(state.status and not state.status.current_tip)
    tip_kind = TipState.DETACHED if detached else TipState.UNBORN if unborn else TipState.VALID
    if target_sha and (not current or target_sha != current):
        # History "Create branch from commit" passes a SHA in `start`.
        if len(target_sha) >= 7 and all(c in "0123456789abcdefABCDEF" for c in target_sha[:7]):
            pass
        else:
            target_sha = ""
    selected = {"point": get_start_point(
        tip_kind=tip_kind,
        default_branch=default_branch,
        upstream_default_branch=upstream_default,
    )}

    dialog = Adw.Dialog()
    dialog.set_content_width(480)
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
    warn = Gtk.Label(wrap=True, xalign=0)
    warn.add_css_class("repo-rules-warning")
    warn.set_visible(False)
    remote_warn = Gtk.Label(wrap=True, xalign=0)
    remote_warn.add_css_class("warning")
    remote_warn.set_visible(False)
    start_info = Gtk.Label(wrap=True, xalign=0)
    start_info.add_css_class("dim-label")
    start_choices = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.append(name_row)
    box.append(warn)
    box.append(remote_warn)
    box.append(start_info)
    box.append(start_choices)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def _set_point(point: StartPoint) -> None:
        selected["point"] = point

    def render_start(*_a: object) -> None:
        while (child := start_choices.get_first_child()) is not None:
            start_choices.remove(child)
        if target_sha:
            short = target_sha[:7]
            summary = next((c.summary for c in state.commits if c.sha == target_sha), "")
            extra = f" '{summary}'" if summary else ""
            start_info.set_text(
                f"Your new branch will be based on the commit{extra} ({short}) from your repository."
            )
            start_info.set_visible(True)
            return
        if unborn:
            start_info.set_text(
                "Your current branch is unborn (does not contain any commits). Creating a new branch will rename the current branch."
            )
            start_info.set_visible(True)
            return
        if detached:
            sha = (current_tip or "")[:7]
            start_info.set_text(
                f"You do not currently have any branch checked out (your HEAD reference is detached). As such your new branch will be based on your currently checked out commit ({sha})."
            )
            start_info.set_visible(True)
            return
        current_name = current or "HEAD"
        if upstream_default is not None:
            parent = repo.github.parent if repo.github else None
            full = f"{parent.owner}/{parent.name}" if parent else "upstream"
            if current_name == upstream_default.name_without_remote:
                start_info.set_text(
                    f"Your new branch will be based on {full}'s default branch ({upstream_default.name_without_remote})."
                )
                start_info.set_visible(True)
                return
            start_info.set_visible(False)
            up = Gtk.CheckButton(
                label=f"{upstream_default.name}\nThe default branch of the upstream repository. Pick this to start on something new that's not dependent on your current branch."
            )
            cur = Gtk.CheckButton(
                label=f"{current_name}\nThe currently checked out branch. Pick this if you need to build on work done on this branch."
            )
            cur.set_group(up)
            up.set_active(selected["point"] == StartPoint.UPSTREAM_DEFAULT_BRANCH)
            cur.set_active(selected["point"] != StartPoint.UPSTREAM_DEFAULT_BRANCH)
            up.connect("toggled", lambda b: b.get_active() and _set_point(StartPoint.UPSTREAM_DEFAULT_BRANCH))
            cur.connect("toggled", lambda b: b.get_active() and _set_point(StartPoint.CURRENT_BRANCH))
            start_choices.append(up)
            start_choices.append(cur)
            return
        if default_branch is None or default_branch.name == current_name:
            extra = ""
            if default_branch is not None and default_branch.name == current_name:
                extra = f" {current_name} is the default branch for your repository."
            start_info.set_text(
                f"Your new branch will be based on your currently checked out branch ({current_name}).{extra}"
            )
            start_info.set_visible(True)
            return
        start_info.set_visible(False)
        dflt = Gtk.CheckButton(
            label=(
                f"{default_branch.name}\n"
                "The default branch in your repository. Pick this to start on something new that's not dependent on your current branch."
            )
        )
        cur = Gtk.CheckButton(
            label=f"{current_name}\nThe currently checked out branch. Pick this if you need to build on work done on this branch."
        )
        cur.set_group(dflt)
        dflt.set_active(selected["point"] == StartPoint.DEFAULT_BRANCH)
        cur.set_active(selected["point"] != StartPoint.DEFAULT_BRANCH)
        dflt.connect("toggled", lambda b: b.get_active() and _set_point(StartPoint.DEFAULT_BRANCH))
        cur.connect("toggled", lambda b: b.get_active() and _set_point(StartPoint.CURRENT_BRANCH))
        start_choices.append(dflt)
        start_choices.append(cur)

    def refresh_warning(*_a: object) -> None:
        raw = name_row.get_text().strip()
        name = sanitize_ref_name(raw) if raw else ""
        if not raw:
            create.set_sensitive(False)
            warn.set_visible(False)
            remote_warn.set_visible(False)
            return
        if not name:
            warn.set_text(f"{raw} is not a valid name.")
            warn.set_visible(True)
            create.set_sensitive(False)
            remote_warn.set_visible(False)
            return
        sanitized_hint = name != raw
        exists = any(b.name == name and b.type == BranchType.LOCAL for b in state.branches)
        if exists:
            warn.set_text(f"A branch named {name} already exists.")
            warn.set_visible(True)
            create.set_sensitive(False)
            remote_warn.set_visible(False)
            return
        on_remote = any(
            b.name_without_remote == name and b.type == BranchType.REMOTE for b in state.branches
        )
        if on_remote:
            remote_warn.set_text(f"A branch named {name} already exists on the remote.")
            remote_warn.set_visible(True)
        else:
            remote_warn.set_visible(False)
        rules = state.repo_rules
        if repo.github and use_repo_rules_logic(store.account_for_repo(repo), repo):
            name_fail = rules.branch_name_patterns.get_failed_rules(name)
            if rules.creation_restricted is True or name_fail.status == "fail":
                warn.set_text(f"Branch name '{name}' is restricted by repo rules.")
                warn.set_visible(True)
                create.set_sensitive(False)
                return
            if rules.creation_restricted == "bypass" or name_fail.status == "bypass":
                warn.set_text(
                    f"Branch name '{name}' is restricted by repo rules, but you can bypass them. Proceed with caution!"
                )
                warn.set_visible(True)
                create.set_sensitive(True)
                return
        if sanitized_hint:
            warn.set_text(
                f"Will be created as {name}. Spaces and invalid characters have been replaced by hyphens."
            )
            warn.set_visible(True)
        else:
            warn.set_visible(False)
        create.set_sensitive(True)

    def submit(*_a: object) -> None:
        name = sanitize_ref_name(name_row.get_text().strip())
        if not name or not create.get_sensitive():
            return
        start_point = None
        no_track = False
        if target_sha:
            start_point = target_sha
        elif selected["point"] == StartPoint.DEFAULT_BRANCH and default_branch:
            start_point = default_branch.name
        elif selected["point"] == StartPoint.UPSTREAM_DEFAULT_BRANCH and upstream_default:
            start_point = upstream_default.name
            no_track = True
        elif selected["point"] == StartPoint.HEAD and current_tip:
            start_point = current_tip
        dialog.close()
        store.create_branch_and_checkout(repo, name, start_point, no_track=no_track)

    name_row.connect("notify::text", refresh_warning)
    create.connect("clicked", submit)
    render_start()
    refresh_warning()
    dialog.present(parent)


def show_rename_branch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..models import sanitize_ref_name

    state = store.state_for(repo)
    current = (payload or {}).get("branch") or (state.status.current_branch if state.status else "")
    branch = next((b for b in state.branches if b.name == current), None)
    dialog = Adw.Dialog()
    dialog.set_content_width(420)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Rename branch"))
    cancel = Gtk.Button(label="Cancel")
    cancel.connect("clicked", lambda *_: dialog.close())
    rename = Gtk.Button(label=f"Rename {current}" if current else "Rename")
    rename.add_css_class("suggested-action")
    header.pack_start(cancel)
    header.pack_end(rename)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    if branch and branch.upstream:
        remote_note = Gtk.Label(
            label=(
                f"This branch is tracking {branch.upstream} and renaming this "
                "branch will not change the branch name on the remote."
            ),
            wrap=True,
            xalign=0,
        )
        remote_note.add_css_class("warning")
        box.append(remote_note)
    name_row = Adw.EntryRow(title="Name")
    name_row.set_text(current or "")
    box.append(name_row)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def submit(*_a: object) -> None:
        new = sanitize_ref_name(name_row.get_text().strip())
        if new and current:
            dialog.close()
            store.rename_current_branch(repo, current, new)

    rename.connect("clicked", submit)
    dialog.present(parent)


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


def show_install_git(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    """Desktop `InstallGit`: locate Git, or open the set-up-git docs."""
    payload = payload or {}
    dialog = Adw.AlertDialog(
        heading="Unable to locate Git",
        body=(
            "We were unable to locate Git on your system. This means you won't be "
            "able to execute any Git commands in the terminal.\n\n"
            "To help you get Git installed and configured for your operating "
            "system, we have some external resources available."
        ),
    )
    dialog.add_response("install", "Install Git")
    dialog.add_response("ok", "Open without Git")
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("ok")

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "install":
            open_external("https://help.github.com/articles/set-up-git/#setting-up-git")
            return
        repo = store.selected_repository
        path = payload.get("path")
        if repo:
            store.open_in_shell(repo)
        elif path:
            from ..shells import find_shell, open_shell

            shell = find_shell(store.settings.selected_shell)
            if shell:
                try:
                    open_shell(shell, str(path))
                except OSError:
                    pass

    dialog.choose(parent, None, done)


def show_publish(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..create_repo import sanitized_repository_name
    from ..git.ops import read_description

    accounts = list(store.accounts)
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    stack = Adw.ViewStack()
    switcher = Adw.ViewSwitcher()
    switcher.set_stack(stack)
    header.set_title_widget(switcher)
    publish_btn = Gtk.Button(label="Publish repository")
    publish_btn.add_css_class("suggested-action")
    header.pack_end(publish_btn)
    toolbar.add_top_bar(header)
    error = Gtk.Label(wrap=True, xalign=0)
    error.add_css_class("error")
    error.set_visible(False)
    error.set_margin_start(18)
    error.set_margin_end(18)
    error.set_margin_top(8)
    status = Gtk.Label(wrap=True, xalign=0)
    status.add_css_class("dim-label")
    status.set_visible(False)
    status.set_margin_start(18)
    status.set_margin_end(18)
    publishing = {"busy": False}
    forms: dict[str, dict[str, Any]] = {}

    def build_form(tab_accounts: list) -> dict[str, Any]:
        selected = [tab_accounts[0]]
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup()
        account_row = Adw.ComboRow(title="Account")
        labels = [f"{item.login} ({item.friendly_endpoint})" for item in tab_accounts]
        account_row.set_model(Gtk.StringList.new(labels or [""]))
        account_row.set_selected(0)
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

        def load_orgs() -> None:
            nonlocal org_logins
            current = selected[0]

            def work() -> list:
                from ..github.api import GitHubAPI

                try:
                    return GitHubAPI.from_account(current).fetch_orgs()
                except Exception:
                    return []

            def done(exc: BaseException | None, fetched: object = None) -> None:
                nonlocal org_logins
                if current is not selected[0]:
                    return
                items = fetched if isinstance(fetched, list) else []
                items = sorted(items, key=lambda item: str(item.get("login") or "").casefold())
                org_logins = ["None"] + [str(item.get("login") or "") for item in items if item.get("login")]
                org_row.set_model(Gtk.StringList.new(org_logins or ["None"]))
                org_row.set_selected(0)

            store._run(work, done)

        def on_account(*_a: Any) -> None:
            idx = int(account_row.get_selected())
            if 0 <= idx < len(tab_accounts):
                selected[0] = tab_accounts[idx]
                load_orgs()

        name_row.connect("changed", refresh_name)
        account_row.connect("notify::selected", on_account)
        if len(tab_accounts) > 1:
            group.add(account_row)
        group.add(name_row)
        group.add(sanitized_row)
        group.add(desc_row)
        group.add(private_row)
        group.add(org_row)
        page.add(group)
        refresh_name()
        load_orgs()
        return {
            "page": page,
            "selected": selected,
            "name_row": name_row,
            "desc_row": desc_row,
            "private_row": private_row,
            "org_row": org_row,
            "org_logins": lambda: org_logins,
            "set_sensitive": lambda enabled: (
                name_row.set_sensitive(enabled),
                desc_row.set_sensitive(enabled),
                private_row.set_sensitive(enabled),
                org_row.set_sensitive(enabled),
                account_row.set_sensitive(enabled),
            ),
        }

    def tab_content(tab: PublishTab) -> Gtk.Widget:
        tab_accounts = accounts_for_publish_tab(accounts, tab)
        if tab_accounts:
            form = build_form(tab_accounts)
            forms[tab.value] = form
            return form["page"]
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(
            _clone_sign_in_cta(
                store,
                dialog,
                enterprise=tab == PublishTab.ENTERPRISE,
                message=(
                    "If you are using GitHub Enterprise at work, sign in to it to get access to your repositories."
                    if tab == PublishTab.ENTERPRISE
                    else "Sign in to your GitHub.com account to access your repositories."
                ),
            )
        )
        return box

    stack.add_titled(tab_content(PublishTab.DOTCOM), PublishTab.DOTCOM.value, "GitHub.com")
    stack.add_titled(tab_content(PublishTab.ENTERPRISE), PublishTab.ENTERPRISE.value, "GitHub Enterprise")
    stack.set_visible_child_name(default_publish_tab(accounts).value)

    def current_form() -> dict[str, Any] | None:
        return forms.get(stack.get_visible_child_name() or "")

    def refresh_publish_button(*_a: Any) -> None:
        form = current_form()
        has_name = bool(form and form["name_row"].get_text().strip()) if form else False
        publish_btn.set_visible(form is not None)
        publish_btn.set_sensitive(bool(form) and has_name and not publishing["busy"])

    def set_busy(busy: bool, message: str = "") -> None:
        publishing["busy"] = busy
        status.set_text(message)
        status.set_visible(busy and bool(message))
        for form in forms.values():
            form["set_sensitive"](not busy)
        publish_btn.set_label("Publishing…" if busy else "Publish repository")
        refresh_publish_button()

    def submit(*_a: Any) -> None:
        form = current_form()
        if not form or publishing["busy"]:
            return
        error.set_visible(False)
        raw = form["name_row"].get_text().strip() or repo.name
        name = sanitized_repository_name(raw) or repo.name
        org = None
        logins = form["org_logins"]()
        idx = form["org_row"].get_selected()
        if idx > 0 and idx < len(logins):
            org = logins[idx]
        account = form["selected"][0]
        set_busy(True, f"Creating repository on {account.friendly_endpoint}")

        def finished(exc: BaseException | None) -> None:
            if exc:
                error.set_text(str(exc))
                error.set_visible(True)
                set_busy(False)
                return
            dialog.close()

        store.publish_repository(
            repo,
            name,
            form["desc_row"].get_text().strip(),
            form["private_row"].get_active(),
            org,
            account,
            on_done=finished,
        )

    publish_btn.connect("clicked", submit)
    stack.connect("notify::visible-child-name", refresh_publish_button)
    for form in forms.values():
        form["name_row"].connect("changed", refresh_publish_button)
    stack.set_vexpand(True)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content.append(error)
    content.append(status)
    content.append(stack)
    toolbar.set_content(content)
    dialog.set_child(toolbar)
    refresh_publish_button()
    dialog.present(parent)


def show_remove_repository(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    dialog = Adw.AlertDialog(
        heading="Remove repository",
        body=(
            f'Are you sure you want to remove the repository "{repo.name}" from GitHub Desktop?\n\n'
            f"The repository will be removed from GitHub Desktop:\n{repo.path}"
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("remove", "Remove")
    dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("remove")
    check = Gtk.CheckButton(label=f"Also move this repository to {TrashNameLabel}")
    try:
        dialog.set_extra_child(check)
    except Exception:
        pass

    def done(d, result) -> None:
        try:
            response = d.choose_finish(result)
        except Exception:
            return
        if response == "remove":
            store.remove_repository(repo, check.get_active())

    dialog.choose(parent, None, done)


def attach_git_email_not_found_warning(
    group: Adw.PreferencesGroup,
    accounts: list[Any],
    get_email: Callable[[], str],
) -> Callable[[], None]:
    """Desktop `GitEmailNotFoundWarning` under Git Config email fields."""
    from ..email import COMMIT_ATTRIBUTION_DOCS, git_email_attribution_warning

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("git-email-not-found-warning")
    box.set_margin_top(6)
    box.set_margin_bottom(6)
    label = Gtk.Label(wrap=True, xalign=0)
    link = Gtk.LinkButton(label="Learn more.", uri=COMMIT_ATTRIBUTION_DOCS)
    link.set_halign(Gtk.Align.START)
    link.set_tooltip_text("Learn more about commit attribution")
    box.append(label)
    box.append(link)

    def refresh(*_a: object) -> None:
        msg, mismatch = git_email_attribution_warning(list(accounts), get_email())
        if not msg:
            box.set_visible(False)
            return
        box.set_visible(True)
        label.set_text(msg)
        if mismatch:
            label.add_css_class("warning")
        else:
            label.remove_css_class("warning")
        link.set_visible(mismatch)

    refresh()
    group.add(box)
    return refresh


def show_repository_settings(
    parent: Gtk.Window, store: AppStore, tab: RepositorySettingsTab | None = None
) -> None:
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
    git_group.add(_author_name_error_row(name_row))
    git_group.add(email_row)
    git_group.add(other_email)
    save_git = Gtk.Button(label="Save Git config")

    def _selected_email() -> str:
        idx = email_row.get_selected()
        if idx < 0 or idx >= len(email_choices) - 1:
            return other_email.get_text().strip()
        model = email_row.get_model()
        return model.get_string(idx) if model is not None else other_email.get_text().strip()

    refresh_email_warning = attach_git_email_not_found_warning(
        git_group,
        [account] if account else [],
        _selected_email,
    )
    email_row.connect("notify::selected", lambda *_a: refresh_email_warning())
    other_email.connect("notify::text", lambda *_a: refresh_email_warning())

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
        refresh_email_warning()

    def save_g(*_a: Any) -> None:
        def apply_config() -> None:
            if local_check.get_active():
                name = name_row.get_text()
                if not git_author_name_is_valid(name):
                    return
                set_config_value(repo.path, "user.name", name)
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
    remote_page.set_name(RepositorySettingsTab.REMOTE.value)
    ignore_page.set_name(RepositorySettingsTab.IGNORED_FILES.value)
    git_page.set_name(RepositorySettingsTab.GIT_CONFIG.value)
    fork_page.set_name(RepositorySettingsTab.FORK_SETTINGS.value)
    if tab is not None:
        try:
            dialog.set_visible_page_name(tab.value)
        except Exception:
            pass
    dialog.present(parent)


def show_preferences(parent: Gtk.Window, store: AppStore, tab: PreferencesTab | None = None) -> None:
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
                (account.email_addresses[0] if account.email_addresses else ""),
                login=account.login,
                avatar_url=account.avatar_url,
                size=28,
                account=account,
                endpoint=account.endpoint,
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
    git_group.add(_author_name_error_row(name_row))
    git_group.add(email_row)
    git_group.add(other_email)

    def _prefs_email() -> str:
        idx = email_row.get_selected()
        if idx < 0 or idx >= len(email_choices) - 1:
            return other_email.get_text().strip()
        model = email_row.get_model()
        return model.get_string(idx) if model is not None else other_email.get_text().strip()

    refresh_email_warning = attach_git_email_not_found_warning(git_group, list(store.accounts), _prefs_email)
    email_row.connect("notify::selected", lambda *_a: refresh_email_warning())
    other_email.connect("notify::text", lambda *_a: refresh_email_warning())
    git_group.add(branch_row)
    clone_row = Adw.EntryRow(title="Clone default directory")
    clone_row.set_text(get_default_dir(s))
    git_group.add(clone_row)
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
    n_hint = Gtk.Label(wrap=True, xalign=0, use_markup=True)
    n_hint.add_css_class("dim-label")
    n_grant = Gtk.Button(label="Grant permission")
    n_settings = Gtk.Button(label="Notifications Settings")
    n_actions = Gtk.Box(spacing=8)
    n_actions.append(n_grant)
    n_actions.append(n_settings)

    def refresh_notification_hint(*_a: Any) -> None:
        from ..notifications import get_notifications_permission, notification_preference_hint

        permission = get_notifications_permission()
        hint = notification_preference_hint(n_row.get_active(), permission)
        n_hint.set_text(hint)
        n_hint.set_visible(bool(hint))
        n_grant.set_visible(n_row.get_active() and permission == "default")
        n_settings.set_visible(n_row.get_active() and permission in {"granted", "denied"})

    def grant_permission(*_a: Any) -> None:
        from ..notifications import request_notifications_permission

        request_notifications_permission()
        refresh_notification_hint()

    def open_settings(*_a: Any) -> None:
        from ..notifications import open_notification_settings

        open_notification_settings()

    n_row.connect("notify::active", refresh_notification_hint)
    n_grant.connect("clicked", grant_permission)
    n_settings.connect("clicked", open_settings)
    hint_row = Gtk.ListBoxRow()
    hint_row.set_activatable(False)
    hint_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hint_box.set_margin_top(8)
    hint_box.set_margin_bottom(8)
    hint_box.set_margin_start(12)
    hint_box.set_margin_end(12)
    hint_box.append(n_hint)
    hint_box.append(n_actions)
    hint_row.set_child(hint_box)
    n_group.add(hint_row)
    refresh_notification_hint()
    notes.add(n_group)

    prompts = Adw.PreferencesPage(title="Prompts", icon_name="dialog-question-symbolic")
    p_group = Adw.PreferencesGroup(title="Confirm before…")
    switches = {}
    for key, title in [
        ("confirm_repository_removal", "Removing repositories"),
        ("confirm_discard_changes", "Discarding changes"),
        ("confirm_discard_stash", "Discarding stashes"),
        ("confirm_force_push", "Force pushing"),
        ("confirm_undo_commit", "Undo commit"),
        ("confirm_checkout_commit", "Checking out commits"),
        ("confirm_commit_filtered_changes", "Committing while a filter is active"),
        ("confirm_commit_message_override", "Overriding commit message with generated message"),
        ("confirm_stash_all_changes", "Stashing all changes"),
        ("confirm_discard_changes_permanently", "Discarding changes permanently"),
    ]:
        row = Adw.SwitchRow(title=title, active=getattr(s, key))
        switches[key] = row
        p_group.add(row)
    strategy = Adw.ComboRow(title="If I have changes and I switch branches…")
    strategy_choices = uncommitted_changes_strategy_choices()
    strategy.set_model(Gtk.StringList.new([label for _kind, label in strategy_choices]))
    try:
        current_strategy = UncommittedChangesStrategy(s.uncommitted_changes_strategy)
        strategy.set_selected([kind for kind, _label in strategy_choices].index(current_strategy))
    except ValueError:
        strategy.set_selected(0)
    p_group.add(strategy)
    length_group = Adw.PreferencesGroup(title="Commit Length")
    length_row = Adw.SwitchRow(title="Show commit length warning", active=s.show_commit_length_warning)
    length_group.add(length_row)
    prompts.add(p_group)
    prompts.add(length_group)

    advanced = Adw.PreferencesPage(title="Advanced", icon_name="emblem-system-symbolic")
    a_group = Adw.PreferencesGroup(title="Background updates")
    indicators = Adw.SwitchRow(
        title="Show status icons in the repository list",
        subtitle="These icons indicate which repositories have local or remote changes, and require the periodic fetching of repositories that are not currently selected.",
        active=s.repository_indicators_enabled,
    )
    a_group.add(indicators)
    usage_group = Adw.PreferencesGroup(title="Usage")
    tracking = Adw.SwitchRow(
        title="Help GitHub Desktop improve by submitting usage stats",
        active=not s.opt_out_of_usage_tracking,
    )
    usage_link = Gtk.LinkButton(uri=SamplesURL, label="usage stats")
    usage_link.set_valign(Gtk.Align.CENTER)
    tracking.add_suffix(usage_link)
    usage_group.add(tracking)
    cred_group = Adw.PreferencesGroup(title="Network and credentials")
    cred = Adw.SwitchRow(
        title="Use Git Credential Manager",
        subtitle="Use Git Credential Manager for private repositories outside of GitHub.com. This feature is experimental and subject to change.",
        active=s.use_external_credential_helper,
    )
    gcm_link = Gtk.LinkButton(uri="https://gh.io/gcm", label="Git Credential Manager")
    gcm_link.set_valign(Gtk.Align.CENTER)
    cred.add_suffix(gcm_link)
    cred_group.add(cred)
    advanced.add(a_group)
    advanced.add(usage_group)
    advanced.add(cred_group)

    access = Adw.PreferencesPage(title="Accessibility", icon_name="preferences-desktop-accessibility-symbolic")
    ac_group = Adw.PreferencesGroup()
    underline = Adw.SwitchRow(
        title="Underline links",
        subtitle=(
            "When enabled, GitHub Desktop will underline links in commit messages, comments, "
            "and other text fields. This can help make links easier to distinguish. This is an example link"
        ),
        active=s.underline_links,
    )
    checks = Adw.SwitchRow(
        title="Show check marks in the diff",
        subtitle=(
            "When enabled, check marks will be displayed along side the line numbers and groups of "
            "line numbers in the diff when committing. When disabled, the line number controls will be less prominent."
        ),
        active=s.show_diff_check_marks,
    )
    spell = Adw.SwitchRow(title="Enable spellcheck in commit messages", active=s.spellcheck_enabled)
    ac_group.add(underline)
    ac_group.add(checks)
    ac_group.add(spell)
    access.add(ac_group)

    for page in (accounts, integrations, git_page, appearance, notes, prompts, advanced, access):
        dialog.add(page)
    accounts.set_name(PreferencesTab.ACCOUNTS.value)
    integrations.set_name(PreferencesTab.INTEGRATIONS.value)
    git_page.set_name(PreferencesTab.GIT.value)
    appearance.set_name(PreferencesTab.APPEARANCE.value)
    notes.set_name(PreferencesTab.NOTIFICATIONS.value)
    prompts.set_name(PreferencesTab.PROMPTS.value)
    advanced.set_name(PreferencesTab.ADVANCED.value)
    access.set_name(PreferencesTab.ACCESSIBILITY.value)

    def persist(*_a: Any) -> None:
        s.theme = ["system", "light", "dark"][theme_row.get_selected()]
        s.tab_size = int(tab_row.get_value())
        s.zoom_factor = float(zoom_row.get_value())
        s.show_side_by_side_diff = side_row.get_active()
        s.hide_whitespace_in_diffs = ws_row.get_active()
        s.notifications_enabled = n_row.get_active()
        s.opt_out_of_usage_tracking = not tracking.get_active()
        s.use_external_credential_helper = cred.get_active()
        s.repository_indicators_enabled = indicators.get_active()
        s.underline_links = underline.get_active()
        s.show_diff_check_marks = checks.get_active()
        s.spellcheck_enabled = spell.get_active()
        set_default_dir(s, clone_row.get_text().strip())
        s.show_commit_length_warning = length_row.get_active()
        idx = strategy.get_selected()
        if 0 <= idx < len(uncommitted_changes_strategy_choices()):
            s.uncommitted_changes_strategy = uncommitted_changes_strategy_choices()[idx][0].value
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

            if git_author_name_is_valid(name):
                try:
                    save_user()
                except GitError as exc:
                    _handle_config_lock(parent, exc, save_user)
        except ValidationError:
            pass
        store.set_stats_opt_out(s.opt_out_of_usage_tracking, False)
        store.persist_settings()
        store.apply_theme()
        store.set_zoom(s.zoom_factor)
        store.emit()

    dialog.connect("closed", persist)
    if tab is not None:
        try:
            dialog.set_visible_page_name(tab.value)
        except Exception:
            pass
    dialog.present(parent)


def show_force_push(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    upstream = "the remote branch"
    if state.status and state.status.current_upstream_branch:
        upstream = state.status.current_upstream_branch

    def confirm(skip: bool) -> None:
        if skip:
            store.settings.confirm_force_push = False
            store.settings.ask_for_confirmation_on_force_push = False
            store.persist_settings()
        store.push_repo(repo, force=True)

    _alert_with_check(
        parent,
        "Are you sure you want to force push?",
        (
            f"A force push will rewrite history on {upstream}. Any collaborators working on "
            "this branch will need to reset their own local branch to match the history of the remote."
        ),
        confirm="I'm sure",
        destructive=True,
        on_confirm=confirm,
    )


def show_generic_auth(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    url = payload.get("remote_url") or ""
    username = str(payload.get("username") or "")
    on_submit_cb = payload.get("on_submit")
    if not username:
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url if "://" in url else f"https://{url}")
            username = parsed.username or ""
        except Exception:
            username = ""

    def submit(values: dict[str, str]) -> None:
        from .. import secrets

        user, password = values.get("username", ""), values.get("password", "")
        if callable(on_submit_cb):
            on_submit_cb(user, password)
            return
        parsed = url
        host = parsed
        from ..remote_parsing import parse_remote

        info = parse_remote(url)
        if info:
            host = info.hostname
        secrets.set_generic(host, user, password)
        store.retry_last_remote_action()

    def cancel() -> None:
        if callable(on_submit_cb):
            on_submit_cb("", "")

    _text_dialog(
        parent,
        "Authentication required",
        url,
        [("username", "Username", username), ("password", "Password / token", "")],
        submit,
        "Save and retry" if not callable(on_submit_cb) else "Continue",
        on_cancel=cancel,
    )


def show_create_tag(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..git.ops import create_tag
    from ..models import create_tag_error, sanitize_ref_name

    state = store.state_for(repo)
    sha = (payload or {}).get("sha") or (state.selected_commit.sha if state.selected_commit else (state.status.current_tip if state.status else ""))
    local_tags = dict(state.tags or {})
    initial = sanitize_ref_name(str((payload or {}).get("initial_name") or ""))
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Create a tag", subtitle="Annotated tag on the selected commit."))
    cancel = Gtk.Button(label="Cancel")
    ok = Gtk.Button(label="Create tag")
    ok.add_css_class("suggested-action")
    header.pack_start(cancel)
    header.pack_end(ok)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    name_row = Adw.EntryRow(title="Name")
    name_row.set_text(initial)
    error = Gtk.Label(wrap=True, xalign=0)
    error.add_css_class("error")
    error.set_visible(False)
    previous_heading = Gtk.Label(label="Previous tags", xalign=0)
    previous_heading.add_css_class("heading")
    previous_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.append(name_row)
    box.append(error)
    box.append(previous_heading)
    box.append(previous_box)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    closed = {"done": False, "updating": False}

    def current_name() -> str:
        return sanitize_ref_name(name_row.get_text())

    def filtered_tags(needle: str) -> list[str]:
        keys = list(local_tags.keys())
        if not needle:
            return keys
        return [item for item in keys if needle in item]

    def refresh(*_a: Any) -> None:
        name = current_name()
        raw = name_row.get_text()
        err = create_tag_error(name, local_tags)
        if not name and raw.strip():
            err = f"{raw} is not a valid name."
        elif raw != name and name and not err:
            err = (
                f"Will be created as {name}. Spaces and invalid characters have been replaced by hyphens."
            )
            error.remove_css_class("error")
            error.add_css_class("warning")
        else:
            error.remove_css_class("warning")
            error.add_css_class("error")
        error.set_text(err or "")
        error.set_visible(bool(err))
        ok.set_sensitive(bool(name) and (create_tag_error(name, local_tags) is None))
        matches = filtered_tags(name)
        child = previous_box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            previous_box.remove(child)
            child = nxt
        if not local_tags:
            previous_heading.set_visible(False)
            previous_box.set_visible(False)
            return
        previous_heading.set_visible(True)
        previous_box.set_visible(True)
        last_three = matches[-3:]
        if not last_three:
            previous_box.append(Gtk.Label(label=f"No matches found for '{name}'", xalign=0, wrap=True))
        else:
            for item in last_three:
                tag = Gtk.Label(label=item, xalign=0)
                tag.add_css_class("monospace")
                previous_box.append(tag)

    def submit(*_a: Any) -> None:
        if closed["done"]:
            return
        name = current_name()
        if create_tag_error(name, local_tags) or not name or not sha:
            return
        closed["done"] = True
        dialog.close()
        create_tag(repo.path, name, sha)
        state.tags[name] = str(sha)
        store.remember_tag_to_push(repo, name)
        store.refresh_repository(repo)

    def cancel_clicked(*_a: Any) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        dialog.close()

    name_row.connect("changed", refresh)
    cancel.connect("clicked", cancel_clicked)
    ok.connect("clicked", submit)
    refresh()
    dialog.present(parent)


def show_delete_tag(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    name = payload.get("tag")
    if repo and name:
        from ..git.ops import delete_tag

        _alert(
            parent,
            "Delete tag?",
            name,
            destructive=True,
            confirm="Delete",
            on_confirm=lambda: (
                delete_tag(repo.path, name),
                store.forget_tag_to_push(repo, name),
                store.refresh_repository(repo),
            ),
        )


def show_stash_switch(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    branch = payload.get("branch")
    if not repo or not branch:
        return
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else "this branch"
    target_name = branch if isinstance(branch, str) else getattr(branch, "name", str(branch))
    has_stash = store._has_existing_desktop_stash(repo)
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Switch branch"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    prompt = Gtk.Label(
        label="You have changes on this branch. What would you like to do with them?",
        wrap=True,
        xalign=0,
    )
    box.append(prompt)
    leave = Gtk.CheckButton()
    bring = Gtk.CheckButton()
    bring.set_group(leave)
    leave.set_active(True)
    leave_row = Adw.ActionRow(
        title=f"Leave my changes on {current}",
        subtitle="Your in-progress work will be stashed on this branch for you to return to later",
    )
    leave_row.add_prefix(leave)
    leave_row.set_activatable_widget(leave)
    bring_row = Adw.ActionRow(
        title=f"Bring my changes to {target_name}",
        subtitle="Your in-progress work will follow you to the new branch",
    )
    bring_row.add_prefix(bring)
    bring_row.set_activatable_widget(bring)
    group = Gtk.ListBox()
    group.add_css_class("boxed-list")
    group.append(leave_row)
    group.append(bring_row)
    box.append(group)
    warn = Gtk.Label(
        label="Your current stash will be overwritten by creating a new stash",
        wrap=True,
        xalign=0,
    )
    warn.add_css_class("warning")

    def sync_warn(*_a: object) -> None:
        warn.set_visible(bool(has_stash and leave.get_active()))

    leave.connect("toggled", sync_warn)
    sync_warn()
    box.append(warn)
    actions = Gtk.Box(spacing=8)
    actions.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label="Cancel")
    switch = Gtk.Button(label="Switch branch")
    switch.add_css_class("suggested-action")
    actions.append(cancel)
    actions.append(switch)
    box.append(actions)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def close(*_a: object) -> None:
        dialog.close()

    def confirm(*_a: object) -> None:
        from ..git.ops import checkout_branch
        from ..models import Branch, BranchType

        close()
        if leave.get_active():
            if has_stash:
                store.show_popup(PopupType.CONFIRM_OVERWRITE_STASH, branch=branch)
                return
            store.stash_and_drop_previous(repo, current or "unknown")
            checkout_branch(repo.path, branch)
            store.remember_branch(repo, branch)
            store.refresh_repository(repo)
            return
        target = next((b for b in state.branches if b.name == branch), None) or Branch(
            str(target_name), None, "", BranchType.LOCAL
        )
        store.checkout_and_bring_changes(repo, target)

    cancel.connect("clicked", close)
    switch.connect("clicked", confirm)
    dialog.present(parent)


def show_start_pr(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo or not repo.github:
        store.show_popup(PopupType.ERROR, error="This repository isn't on GitHub.")
        return
    store.load_pr_preview(repo)
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else "?"
    from ..models import ForkContributionTarget, github_for_contribution, fork_contribution_target, UPSTREAM_REMOTE_NAME

    target = github_for_contribution(repo) or repo.github
    contribution_remote = (
        UPSTREAM_REMOTE_NAME
        if repo.is_fork and fork_contribution_target(repo) == ForkContributionTarget.PARENT
        else "origin"
    )
    base_names = pr_base_branches(state.branches, remote=contribution_remote, current=current)
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

    # GitHub's /pull/new form includes "Create as draft"; Desktop preview only opens that page.
    actions = Gtk.Box(spacing=8)
    create_btn = Gtk.Button(label="Create pull request")
    create_btn.add_css_class("suggested-action")
    actions.append(create_btn)
    root.append(actions)

    def _pr_file_menu(file, widget) -> None:
        st = store.state_for(repo)
        full = os.path.join(repo.path, file.path)
        exists = os.path.exists(full)
        head = st.status.current_tip if st.status else None
        local = set(st.local_commit_shas or [])
        non_local = head if head and head not in local else None
        enterprise = bool(repo.github and not is_dotcom_endpoint(repo.github.endpoint))

        def view_on_github() -> None:
            if non_local:
                store.view_commit_on_github(repo, non_local, file.path)

        items = committed_file_context_items(
            full_path=full,
            relative_path=file.path,
            exists=exists,
            editor_label=open_in_editor_label(store.settings.selected_external_editor),
            on_reveal=lambda: store.reveal_in_file_manager(repo, file.path),
            on_open_editor=lambda: store.open_in_editor(repo, full),
            on_open_default=lambda: store.open_file_default(repo, file.path),
            view_github_label=view_on_github_label(enterprise=enterprise),
            on_view_github=view_on_github,
            view_github_enabled=bool(non_local and repo.github),
        )
        show_context_menu(widget, items)

    def _preview_kwargs():
        st = store.state_for(repo)
        return {
            "show_checks": False,
            "side_by_side": st.side_by_side or store.settings.show_side_by_side_diff,
            "image_mode": st.image_diff_type or store.settings.image_diff_type,
            "hide_whitespace": store._hide_ws_pr(),
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
            row = Adw.ActionRow(title=path_label(file.path, file.status), subtitle=map_status(file.status))
            row.set_activatable(True)
            row._file = file  # type: ignore[attr-defined]
            attach_right_click(row, lambda *_ , f=file, widget=row: _pr_file_menu(f, widget))
            file_list.append(row)
        kwargs = _preview_kwargs()
        if st.pr_files:
            diff = store.load_pr_preview_diff(repo, st.pr_files[0])
            viewer.render(diff, path=st.pr_files[0].path, **kwargs)
        else:
            viewer.render(None)
        if st.current_pull_request:
            create_btn.set_label("View pull request")
            create_btn.set_sensitive(True)
        else:
            create_btn.set_label("Create pull request")
            create_btn.set_sensitive(bool(st.pr_commits))

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
        st = store.state_for(repo)
        dialog.close()
        if st.current_pull_request:
            open_external(st.current_pull_request.html_url)
            return
        if not st.pr_commits:
            return
        base = selected["name"] or default
        store.create_pull_request_from_preview(repo, base)

    create_btn.connect("clicked", create)

    def on_pr_hide_ws(hidden: bool) -> None:
        store.set_hide_whitespace_in_pull_request_diff(repo, hidden)
        render_preview()

    def on_pr_side(enabled: bool) -> None:
        store.set_side_by_side(repo, enabled)
        render_preview()

    viewer.on_hide_whitespace_changed = on_pr_hide_ws
    viewer.on_side_by_side_changed = on_pr_side
    _fill_base_list()
    render_preview()
    toolbar.set_content(root)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_initialize_lfs(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    """Desktop `InitializeLFS`: install hooks in repositories that already use Git LFS."""
    payload = payload or {}
    repos = list(payload.get("repositories") or [])
    if not repos:
        paths = [os.path.abspath(p) for p in (payload.get("paths") or [])]
        repos = [item for item in store.repositories if os.path.abspath(item.path) in set(paths)]
    if not repos and store.selected_repository:
        repos = [store.selected_repository]
    if not repos:
        return
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Initialize Git LFS"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_bottom(16)
    lfs_link = '<a href="https://git-lfs.github.com/">Git LFS</a>'
    if len(repos) > 10:
        intro = (
            f"{len(repos)} repositories use {lfs_link}. To contribute to them, "
            "Git LFS must first be initialized. Would you like to do so now?"
        )
    else:
        plural = len(repos) != 1
        uses = "The repositories use" if plural else "This repository uses"
        them = "them" if plural else "it"
        intro = (
            f"{uses} {lfs_link}. To contribute to {them}, "
            "Git LFS must first be initialized. Would you like to do so now?"
        )
    label = Gtk.Label(label=intro, wrap=True, xalign=0, use_markup=True)
    label.set_max_width_chars(56)
    box.append(label)
    if len(repos) <= 10:
        listing = Gtk.ListBox()
        listing.add_css_class("boxed-list")
        for repo in repos:
            listing.append(Adw.ActionRow(title=repo.name, subtitle=repo.path))
        box.append(listing)
    actions = Gtk.Box(spacing=8)
    later = Gtk.Button(label="Not now")
    later.connect("clicked", lambda *_: dialog.close())
    init_btn = Gtk.Button(label="Initialize Git LFS")
    init_btn.add_css_class("suggested-action")

    def confirm(*_a: Any) -> None:
        dialog.close()
        store.install_lfs_hooks(repositories=repos)

    init_btn.connect("clicked", confirm)
    actions.append(later)
    actions.append(init_btn)
    box.append(actions)
    toolbar.set_content(box)
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
    dialog.set_content_height(480)
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
    intro = Gtk.Label(
        label=(
            '<a href="https://docs.github.com/code-security/secret-scanning/protecting-pushes-with-secret-scanning">'
            "Secret Scanning</a> found secret(s) in the commit(s) you attempted to push."
        ),
        wrap=True,
        xalign=0,
        use_markup=True,
    )
    intro.set_max_width_chars(60)
    box.append(intro)
    remediate = Gtk.Label(
        label=(
            "Allowing secrets risks exposure. Consider "
            '<a href="https://docs.github.com/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/working-with-push-protection-in-the-github-ui#resolving-a-blocked-commit">'
            "removing the secret from your commit and commit history</a>."
        ),
        wrap=True,
        xalign=0,
        use_markup=True,
    )
    remediate.set_max_width_chars(60)
    box.append(remediate)
    box.append(Gtk.Label(label="Exposing this secret can allow someone to:", xalign=0, wrap=True))
    for item in (
        "Verify the identity of the secret(s)",
        "Know which resources the secret(s) can access",
        "Act on behalf of the secret's owner",
        "Push the secret(s) to this repository without being blocked",
    ):
        box.append(Gtk.Label(label=f"• {item}", xalign=0, wrap=True))
    if not secrets:
        box.append(Gtk.Label(label=str(payload.get("error") or "GitHub detected a secret in this push."), xalign=0, wrap=True))
    descriptions = [getattr(secret, "description", None) or getattr(secret, "secret_type", None) or "Secret" for secret in secrets]
    bypassed: dict[str, Gtk.Widget] = {}

    def copy_sha(sha: str) -> None:
        parent.get_clipboard().set(sha)

    def render_location(loc) -> Gtk.Box:
        row = Gtk.Box(spacing=6)
        sha = getattr(loc, "commit_sha", "") or ""
        short = sha[:7] if sha else ""
        sha_lbl = Gtk.Label(label=short, xalign=0)
        sha_lbl.add_css_class("monospace")
        row.append(sha_lbl)
        if sha:
            copy_btn = Gtk.Button(label="Copy")
            copy_btn.add_css_class("flat")
            copy_btn.set_tooltip_text("Copy the full SHA")
            copy_btn.connect("clicked", lambda *_ , value=sha: copy_sha(value))
            row.append(copy_btn)
        path = getattr(loc, "path", "") or ""
        line = getattr(loc, "line_number", 0) or 0
        row.append(Gtk.Label(label=f"{path} at line {line}", xalign=0, wrap=True, hexpand=True))
        return row

    for secret in secrets:
        title = getattr(secret, "description", None) or getattr(secret, "secret_type", None) or "Secret"
        secret_id = getattr(secret, "id", "") or ""
        if descriptions.count(title) > 1 and secret_id:
            title = f"{title} ({secret_id})"
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_row = Gtk.Box(spacing=8)
        header_row.append(Gtk.Label(label=title, xalign=0, wrap=True, hexpand=True))
        status = Gtk.Label(label="Bypassed")
        status.add_css_class("success")
        status.set_visible(False)
        bypassed[secret_id or title] = status
        header_row.append(status)
        url = getattr(secret, "bypass_url", None)
        if url:
            open_btn = Gtk.Button(label="Bypass")
            open_btn.add_css_class("flat")

            def on_bypass(*_a: Any, s=secret, u=url, btn=open_btn, key=secret_id or title) -> None:
                if getattr(s, "requires_approval", False):
                    open_external(u)
                    return
                btn.set_sensitive(False)

                def after(_exc: BaseException | None = None) -> None:
                    widget = bypassed.get(key)
                    if widget is not None:
                        widget.set_visible(True)
                    btn.set_visible(False)

                show_bypass(parent, store, {"secret": s, "bypass_url": u}, on_bypassed=after)

            open_btn.connect("clicked", on_bypass)
            header_row.append(open_btn)
        group.append(header_row)
        locs = list(getattr(secret, "locations", None) or [])
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        extra.set_visible(False)
        if locs:
            group.append(render_location(locs[0]))
            for loc in locs[1:]:
                extra.append(render_location(loc))
            if len(locs) > 1:
                group.append(extra)
                more = Gtk.Button(label="Show More locations")
                more.add_css_class("flat")

                def toggle(*_a: Any, panel=extra, button=more) -> None:
                    shown = panel.get_visible()
                    panel.set_visible(not shown)
                    button.set_label("Show Less Locations" if not shown else "Show More locations")

                more.connect("clicked", toggle)
                group.append(more)
        box.append(group)
    docs = Gtk.Button(label="Remediation docs")
    docs.connect(
        "clicked",
        lambda *_: open_external(
            "https://docs.github.com/code-security/secret-scanning/working-with-secret-scanning-and-push-protection/working-with-push-protection-in-the-github-ui#resolving-a-blocked-commit"
        ),
    )
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
    dialog.set_content_width(560)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Commit reachability"))
    toolbar.add_top_bar(header)
    stack = Adw.ViewStack()
    switcher = Adw.ViewSwitcher()
    switcher.set_stack(stack)
    switcher.set_halign(Gtk.Align.CENTER)

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
    stack.set_vexpand(True)
    explainer = Gtk.Label(wrap=True, xalign=0)
    explainer.add_css_class("body")
    learn = Gtk.LinkButton(
        uri=UNREACHABLE_COMMITS_LEARN_MORE,
        label="Learn more about unreachable commits.",
    )
    learn.set_halign(Gtk.Align.START)

    def update_explainer(*_a: object) -> None:
        unreachable_tab = stack.get_visible_child_name() != "reachable"
        count = len(unreachable) if unreachable_tab else len(reachable)
        explainer.set_text(unreachable_commits_message(unreachable_tab=unreachable_tab, count=count))

    stack.connect("notify::visible-child", update_explainer)
    update_explainer()
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.append(switcher)
    box.append(explainer)
    box.append(learn)
    box.append(stack)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def show_bypass(parent: Gtk.Window, store: AppStore, payload: dict[str, Any], on_bypassed: Callable[..., None] | None = None) -> None:
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
        try:
            GitHubAPI.from_account(account).create_push_protection_bypass(
                repo.github.owner, repo.github.name, selected["reason"].value, placeholder_id=placeholder_id
            )
        except Exception as exc:
            store.show_popup(PopupType.ERROR, error=str(exc))
            if on_bypassed:
                on_bypassed(exc)
            return
        if on_bypassed:
            on_bypassed(None)
            return
        store.push_repo(repo)

    cancel.connect("clicked", close)
    ok.connect("clicked", submit)
    dialog.present(parent)


def show_create_fork(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    repo = store.selected_repository
    account = store.account_for_repo(repo) if repo else None
    if not repo or not repo.github or not account:
        return
    payload = payload or {}
    html = repo.github.html_url
    full_name = repo.github.full_name
    fork_name = f"{account.login}/{repo.github.name}"

    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    try:
        dialog.set_name("create-fork")
    except Exception:
        pass
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    title = Adw.WindowTitle(title="Do you want to fork this repository?")
    header.set_title_widget(title)
    cancel = Gtk.Button(label="Cancel")
    ok = Gtk.Button(label="Fork this repository")
    ok.add_css_class("destructive-action")
    header.pack_start(cancel)
    header.pack_end(ok)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    content = Gtk.Label(wrap=True, xalign=0)
    content.set_wrap(True)
    spinner_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    spinner = Gtk.Spinner()
    status = Gtk.Label(label="Creating fork…", xalign=0)
    spinner_row.append(spinner)
    spinner_row.append(status)
    spinner_row.set_visible(False)
    error_details = Gtk.Expander(label="Error details")
    error_pre = Gtk.Label(wrap=True, xalign=0, selectable=True)
    error_pre.add_css_class("error")
    error_details.set_child(error_pre)
    error_details.set_visible(False)
    manual = Gtk.LinkButton(uri=html or "https://github.com", label="creating the fork manually on GitHub")
    manual.set_halign(Gtk.Align.START)
    manual.set_visible(False)
    box.append(content)
    box.append(spinner_row)
    box.append(manual)
    box.append(error_details)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    state = {"loading": False, "error": bool(payload.get("error"))}

    def set_can_close(allow: bool) -> None:
        try:
            dialog.set_can_close(allow)
        except Exception:
            pass

    def render_content() -> None:
        if state["error"]:
            title.set_title("Unable to create fork")
            content.set_text(
                f"Creating your fork {fork_name} failed. You can try creating the fork manually on GitHub."
            )
            manual.set_visible(bool(html))
            err = str(payload.get("error") or "")
            error_pre.set_text(err)
            error_details.set_visible(bool(err))
            ok.set_visible(False)
            cancel.set_label("Close")
            spinner_row.set_visible(False)
            return
        title.set_title("Do you want to fork this repository?")
        content.set_text(
            f"It looks like you don't have write access to {full_name}. "
            "If you should, please check with a repository administrator.\n\n"
            f"Do you want to create a fork of this repository at {fork_name} to continue?"
        )
        manual.set_visible(False)
        error_details.set_visible(False)
        ok.set_visible(True)
        cancel.set_label("Cancel")

    def set_loading(loading: bool) -> None:
        state["loading"] = loading
        spinner_row.set_visible(loading)
        if loading:
            spinner.start()
        else:
            spinner.stop()
        ok.set_sensitive(not loading)
        cancel.set_sensitive(not loading)
        set_can_close(not loading)

    def close(*_a: Any) -> None:
        if state["loading"]:
            return
        dialog.close()

    def on_forked(exc: BaseException | None, fork: Any) -> None:
        set_loading(False)
        if exc:
            payload["error"] = str(exc)
            state["error"] = True
            render_content()
            return
        dialog.close()
        if fork is not None:
            store.convert_repository_to_fork(repo, fork)

    def submit(*_a: Any) -> None:
        if state["loading"] or state["error"]:
            return
        set_loading(True)
        store.create_fork(repo, on_done=on_forked)

    cancel.connect("clicked", close)
    ok.connect("clicked", submit)
    render_content()
    dialog.present(parent)


def show_fork_settings(parent: Gtk.Window, store: AppStore) -> None:
    show_repository_settings(parent, store, RepositorySettingsTab.FORK_SETTINGS)


def show_alias(parent: Gtk.Window, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    from ..models import name_of

    verb = "Change" if repo.alias else "Create"
    github_note = (
        " This will not affect the original repository name on GitHub." if repo.github else ""
    )

    def submit(values: dict[str, str]) -> None:
        alias = (values.get("alias") or "").strip()
        if not alias:
            return
        repo.alias = alias
        store._save_repositories()
        store.emit()

    _text_dialog(
        parent,
        f"{verb} repository alias",
        f'Choose a new alias for the repository "{name_of(repo)}".{github_note}',
        [("alias", "Alias", repo.alias or repo.name)],
        submit,
        f"{verb} alias",
    )


def show_ssh_passphrase(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    _ssh_secret_dialog(
        parent,
        "SSH key passphrase",
        payload.get("key_path") or "",
        "passphrase",
        "Passphrase",
        "Remember passphrase",
        payload,
    )


def show_ssh_password(parent: Gtk.Window, payload: dict[str, Any]) -> None:
    _ssh_secret_dialog(
        parent,
        "SSH password",
        payload.get("username") or "",
        "password",
        "Password",
        "Remember password",
        payload,
    )


def _ssh_secret_dialog(
    parent: Gtk.Window,
    heading: str,
    body: str,
    field: str,
    field_title: str,
    remember_label: str,
    payload: dict[str, Any],
) -> None:
    dialog = Adw.Dialog()
    dialog.set_content_width(440)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=heading, subtitle=str(body)))
    cancel = Gtk.Button(label="Cancel")
    ok = Gtk.Button(label="Continue")
    ok.add_css_class("suggested-action")
    header.pack_start(cancel)
    header.pack_end(ok)
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    row = Adw.PasswordEntryRow(title=field_title)
    remember = Gtk.CheckButton(label=remember_label)
    remember.set_active(False)
    box.append(row)
    box.append(remember)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    closed = {"done": False}

    def finish(value: str | None, stored: bool) -> None:
        if closed["done"]:
            return
        closed["done"] = True
        dialog.close()
        cb = payload.get("on_submit")
        if cb:
            cb(value, stored)

    cancel.connect("clicked", lambda *_: finish(None, False))
    ok.connect("clicked", lambda *_: finish(row.get_text() or None, bool(remember.get_active())))
    dialog.present(parent)


def show_commit_message_dialog(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    from .spellcheck import attach_spellcheck

    repo = store.selected_repository
    state = store.state_for(repo) if repo else None
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=payload.get("title") or "Commit message"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(16)
    box.set_margin_bottom(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    if payload.get("body"):
        box.append(Gtk.Label(label=str(payload.get("body")), wrap=True, xalign=0))
    summary = Gtk.Entry()
    summary.set_placeholder_text("Summary (required)")
    summary.set_text(payload.get("summary") or "")
    summary.set_max_length(MaxSummaryLength)
    issue_store = install_entry_completion(summary)
    box.append(summary)
    length_warn = Gtk.Label(xalign=0, wrap=True)
    length_warn.add_css_class("warning")
    length_warn.set_visible(False)
    box.append(length_warn)
    access_warn = Gtk.Label(xalign=0, wrap=True)
    access_warn.add_css_class("warning")
    access_lines = [line for line in (write_access_warning(repo), protected_branch_warning(state)) if line]
    if access_lines:
        access_warn.set_text("\n".join(access_lines))
        access_warn.set_visible(True)
        box.append(access_warn)
    description = Gtk.TextView()
    description.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    description.set_size_request(-1, 120)
    description.get_buffer().set_text(payload.get("description") or "")
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_min_content_height(120)
    scrolled.set_child(description)
    box.append(scrolled)
    attach_spellcheck(summary, description, enabled=store.settings.spellcheck_enabled)

    def exclude_login() -> str | None:
        account = store.account_for_repo(repo) if repo else None
        return account.login if account else None

    def current_state():
        return store.state_for(repo) if repo else None

    desc_completer = TextViewCompleter(
        description,
        current_state,
        on_hash=lambda: store.refresh_issues(repo),
        exclude_login=exclude_login,
    )

    def refresh_completion(*_a: object) -> None:
        token = token_before_cursor(summary.get_text(), summary.get_position())
        populate_completion_store(issue_store, current_state(), token, exclude_login=exclude_login())
        if token.startswith("#"):
            store.refresh_issues(repo)
        hint = summary_length_hint(summary.get_text(), store.settings.show_commit_length_warning)
        if hint:
            length_warn.set_text(hint)
            length_warn.set_visible(True)
        else:
            length_warn.set_visible(False)

    summary.connect("changed", refresh_completion)
    description.get_buffer().connect("changed", lambda *_: desc_completer.update())
    refresh_completion()

    author_input = None
    github_repo = bool(repo and repo.github)
    show_co = bool(payload.get("show_co_authors") or payload.get("co_authors") or github_repo)
    if show_co:
        co_check = Gtk.CheckButton(label="Co-authors")
        author_input = AuthorInput()
        fill_coauthor_store(author_input.store, state)
        raw = payload.get("co_authors")
        if isinstance(raw, list):
            author_input.set_authors(list(raw))
        elif raw:
            from ..models import parse_co_authors

            author_input.set_authors(parse_co_authors(str(raw)))
        has_authors = bool(author_input.get_authors())
        co_check.set_active(has_authors or bool(payload.get("show_co_authors")))
        author_input.set_visible(co_check.get_active())
        co_check.connect("toggled", lambda btn: author_input.set_visible(btn.get_active()))
        box.append(co_check)
        box.append(author_input)
    save = Gtk.Button(label=payload.get("button") or "Save")
    save.add_css_class("suggested-action")
    save.set_halign(Gtk.Align.END)
    box.append(save)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def submit(*_a: Any) -> None:
        start, end = description.get_buffer().get_bounds()
        desc = description.get_buffer().get_text(start, end, True)
        cb = payload.get("on_submit")
        if author_input is not None:
            author_input.commit_pending()
        authors = author_input.get_authors() if author_input is not None else []
        if cb:
            try:
                cb(summary.get_text(), desc, authors)
            except TypeError:
                cb(summary.get_text(), desc)
        dialog.close()

    save.connect("clicked", submit)
    summary.connect("activate", submit)
    dialog.present(parent)


def show_tutorial(parent: Gtk.Window, store: AppStore) -> None:
    account = store.accounts[0] if store.accounts else None
    if not account:
        store.begin_sign_in(False)
        return
    default = get_default_dir(store.settings)
    path = os.path.join(default, "desktop-tutorial")
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Start tutorial"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(16)
    box.set_margin_start(16)
    box.set_margin_end(16)
    box.set_margin_bottom(16)
    host = account.friendly_endpoint
    body = Gtk.Label(
        label=(
            f"This will create a repository on your local machine, and push it to "
            f"your account @{account.login} on {host}. This repository will only be "
            f"visible to you, and not visible publicly.\n\nIt will be created at {path}."
        ),
        wrap=True,
        xalign=0,
    )
    box.append(body)
    status = Gtk.Label(label="", xalign=0, wrap=True)
    status.set_visible(False)
    bar = Gtk.ProgressBar()
    bar.set_visible(False)
    box.append(status)
    box.append(bar)
    actions = Gtk.Box(spacing=8)
    cancel = Gtk.Button(label="Cancel")
    cont = Gtk.Button(label="Continue")
    cont.add_css_class("suggested-action")
    actions.append(cancel)
    actions.append(cont)
    box.append(actions)
    closed = {"done": False}

    def close(*_a: Any) -> None:
        if not closed["done"]:
            closed["done"] = True
            dialog.close()

    def on_progress(title: str, value: float, description: str = "") -> None:
        status.set_visible(True)
        bar.set_visible(True)
        status.set_text(description or title)
        bar.set_fraction(max(0.0, min(1.0, value)))

    def on_done(exc: BaseException | None) -> None:
        close()

    def confirm(*_a: Any) -> None:
        cont.set_sensitive(False)
        cancel.set_sensitive(False)
        store.create_tutorial_repository(account, path, on_progress=on_progress, on_done=on_done)

    cancel.connect("clicked", close)
    cont.connect("clicked", confirm)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


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
            subtitle="Use ↑ ↓ to choose a new location. Press ⏎ to confirm.",
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
    plural = "s" if len(to_move) != 1 else ""
    intro = Gtk.Label(
        label=(
            f"Use the Up and Down arrow keys to choose a new location for the selected commit{plural}, "
            "then press Enter to confirm or Escape to cancel."
        ),
        wrap=True,
        xalign=0,
    )
    intro.add_css_class("dim-label")
    box.append(intro)
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
