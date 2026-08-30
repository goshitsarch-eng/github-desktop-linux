"""Dialog plumbing: which QML dialog a popup opens, and what its buttons do.

The store raises popups by :class:`~github_desktop.models.PopupType`;
:data:`DIALOG_FOR_POPUP` maps each one onto a QML file under ``qml/dialogs``,
and :meth:`PopupBridge.submit` routes a dialog's result back to the store. The
QML side therefore holds layout and nothing else.

:meth:`PopupBridge.chooseFolder` is also here, because picking a folder is the
one dialog Qt owns rather than us -- see :mod:`github_desktop.ui.filepicker`
for how a network location becomes a path git can use.
"""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import QObject, Signal, Slot

from ..logging import get_logger
from ..models import PopupType
from ..shells import open_external
from .filepicker import PickedFolder, resolve_picked_url

log = get_logger()


def as_dict(value: Any) -> dict:
    """Normalize a value that crossed the QML boundary into a plain dict.

    PySide6 hands a JS object literal over as a ``QJSValue`` rather than a
    ``dict``, so every slot that takes a payload has to unwrap it first.
    """
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    to_variant = getattr(value, "toVariant", None)
    if to_variant is not None:
        converted = to_variant()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(value)
    except (TypeError, ValueError):
        return {}

# Schemes offered in the folder chooser. Listing them lets the KDE dialog show
# Network in its sidebar; anything selected there is resolved to a local path
# before it reaches git.
BROWSABLE_SCHEMES = ("file", "smb", "sftp", "fish", "nfs", "ftp", "webdav", "davs")

DIALOG_FOR_POPUP: dict[str, str] = {
    PopupType.ABOUT.value: "AboutDialog",
    PopupType.ACKNOWLEDGEMENTS.value: "AcknowledgementsDialog",
    PopupType.ADD_REPOSITORY.value: "AddRepositoryDialog",
    PopupType.ADD_SSH_HOST.value: "SshHostDialog",
    PopupType.BYPASS_PUSH_PROTECTION.value: "BypassPushProtectionDialog",
    PopupType.CHANGE_REPOSITORY_ALIAS.value: "RepositoryAliasDialog",
    PopupType.CHOOSE_FORK_SETTINGS.value: "ForkSettingsDialog",
    PopupType.CI_CHECK_RUN_RERUN.value: "RerunChecksDialog",
    PopupType.CLI_INSTALLED.value: "MessageDialog",
    PopupType.CLONE_REPOSITORY.value: "CloneRepositoryDialog",
    PopupType.COMMIT_CONFLICTS_WARNING.value: "ConfirmDialog",
    PopupType.COMMIT_MESSAGE.value: "CommitMessageDialog",
    PopupType.CONFIRM_CHECKOUT_COMMIT.value: "ConfirmDialog",
    PopupType.CONFIRM_COMMIT_FILTERED_CHANGES.value: "ConfirmDialog",
    PopupType.CONFIRM_DISCARD_CHANGES.value: "DiscardChangesDialog",
    PopupType.CONFIRM_DISCARD_SELECTION.value: "DiscardChangesDialog",
    PopupType.CONFIRM_DISCARD_STASH.value: "ConfirmDialog",
    PopupType.CONFIRM_EXIT_TUTORIAL.value: "ConfirmDialog",
    PopupType.CONFIRM_FORCE_PUSH.value: "ConfirmDialog",
    PopupType.CONFIRM_OVERWRITE_STASH.value: "ConfirmDialog",
    PopupType.CREATE_BRANCH.value: "CreateBranchDialog",
    PopupType.CREATE_FORK.value: "CreateForkDialog",
    PopupType.CREATE_REPOSITORY.value: "CreateRepositoryDialog",
    PopupType.CREATE_TAG.value: "CreateTagDialog",
    PopupType.CREATE_TUTORIAL_REPOSITORY.value: "TutorialRepositoryDialog",
    PopupType.DELETE_BRANCH.value: "DeleteBranchDialog",
    PopupType.DELETE_PULL_REQUEST.value: "ConfirmDialog",
    PopupType.DELETE_REMOTE_BRANCH.value: "DeleteBranchDialog",
    PopupType.DELETE_TAG.value: "ConfirmDialog",
    PopupType.DISCARD_CHANGES_RETRY.value: "DiscardRetryDialog",
    PopupType.ERROR.value: "ErrorDialog",
    PopupType.EXTERNAL_EDITOR_FAILED.value: "ErrorDialog",
    PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER.value: "ConfirmDialog",
    PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE.value: "ConfirmDialog",
    PopupType.GENERIC_GIT_AUTHENTICATION.value: "GenericAuthDialog",
    PopupType.INITIALIZE_LFS.value: "ConfirmDialog",
    PopupType.INSTALL_GIT.value: "InstallGitDialog",
    PopupType.INSTALLING_UPDATE.value: "MessageDialog",
    PopupType.INVALIDATED_TOKEN.value: "ConfirmDialog",
    PopupType.LFS_ATTRIBUTE_MISMATCH.value: "ConfirmDialog",
    PopupType.LOCAL_CHANGES_OVERWRITTEN.value: "ErrorDialog",
    PopupType.MULTI_COMMIT_OPERATION.value: "MultiCommitOperationDialog",
    PopupType.OPEN_SHELL_FAILED.value: "ErrorDialog",
    PopupType.OVERSIZED_FILES.value: "OversizedFilesDialog",
    PopupType.PREFERENCES.value: "PreferencesDialog",
    PopupType.PUBLISH_REPOSITORY.value: "PublishRepositoryDialog",
    PopupType.PULL_REQUEST_CHECKS_FAILED.value: "ChecksFailedDialog",
    PopupType.PULL_REQUEST_COMMENT.value: "PullRequestCommentDialog",
    PopupType.PULL_REQUEST_REVIEW.value: "PullRequestReviewDialog",
    PopupType.PUSH_BRANCH_COMMITS.value: "PushBranchCommitsDialog",
    PopupType.PUSH_NEEDS_PULL.value: "ConfirmDialog",
    PopupType.PUSH_PROTECTION_ERROR.value: "PushProtectionDialog",
    PopupType.PUSH_REJECTED_WORKFLOW_SCOPE.value: "ConfirmDialog",
    PopupType.RELEASE_NOTES.value: "ReleaseNotesDialog",
    PopupType.REMOVE_REPOSITORY.value: "RemoveRepositoryDialog",
    PopupType.RENAME_BRANCH.value: "RenameBranchDialog",
    PopupType.REPOSITORY_SETTINGS.value: "RepositorySettingsDialog",
    PopupType.SAML_REAUTH_REQUIRED.value: "ConfirmDialog",
    PopupType.SIGN_IN.value: "SignInDialog",
    PopupType.SSH_KEY_PASSPHRASE.value: "PassphraseDialog",
    PopupType.SSH_USER_PASSWORD.value: "PassphraseDialog",
    PopupType.STASH_AND_SWITCH_BRANCH.value: "StashSwitchDialog",
    PopupType.START_PULL_REQUEST.value: "StartPullRequestDialog",
    PopupType.TERMS_AND_CONDITIONS.value: "MessageDialog",
    PopupType.THANK_YOU.value: "ThankYouDialog",
    PopupType.UNKNOWN_AUTHORS.value: "UnknownAuthorsDialog",
    PopupType.UNREACHABLE_COMMITS.value: "MessageDialog",
    PopupType.UNTRUSTED_CERTIFICATE.value: "ConfirmDialog",
    PopupType.UPSTREAM_ALREADY_EXISTS.value: "ConfirmDialog",
    PopupType.WARN_FORCE_PUSH.value: "ConfirmDialog",
    PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO.value: "ConfirmDialog",
    PopupType.WARNING_BEFORE_RESET.value: "ConfirmDialog",
}

DEFAULT_DIALOG = "ConfirmDialog"


class PopupBridge(QObject):
    """Routes dialog results into the store, and owns the folder chooser."""

    folderChosen = Signal("QVariant")

    def __init__(self, store, bridge, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.bridge = bridge

    # -- dialog lookup -----------------------------------------------------

    @Slot(str, result=str)
    def dialogFor(self, popup_type: str) -> str:  # noqa: N802 - QML style
        """QML component name for a popup type."""
        return DIALOG_FOR_POPUP.get(popup_type, DEFAULT_DIALOG)

    @Slot(str, "QVariant", result="QVariant")
    def copyFor(self, popup_type: str, payload: Any = None) -> dict:  # noqa: N802 - QML style
        """Title, body and button labels for a popup (see ui/dialogs.py)."""
        from .dialogs import dialog_copy

        return dialog_copy(popup_type, as_dict(payload))

    # -- folder chooser ----------------------------------------------------

    @Slot(str, str, result="QVariant")
    def chooseFolder(self, title: str, start_path: str = "") -> dict:  # noqa: N802 - QML style
        """Ask for a directory and return one git can actually work in.

        The platform dialog is asked for a *local* file, which is what makes
        KDE mount a network location through KIOFuse and hand back a real
        path. If it still returns a remote URL -- an xdg-desktop-portal
        dialog, or a share nothing has mounted -- the URL is resolved against
        the current mounts, and failing that the caller gets an error naming
        the share rather than a silently ignored click.
        """
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QFileDialog

        dialog = QFileDialog(None, title or "Choose a folder")
        dialog.setFileMode(QFileDialog.FileMode.Directory)
        dialog.setOption(QFileDialog.Option.ShowDirsOnly, True)
        # Local-only: KDE resolves a picked share to its KIOFuse mount point.
        dialog.setSupportedSchemes(list(BROWSABLE_SCHEMES))
        dialog.setOption(QFileDialog.Option.DontResolveSymlinks, False)
        start = start_path or os.path.expanduser("~")
        if os.path.isdir(start):
            dialog.setDirectoryUrl(QUrl.fromLocalFile(start))
        if not dialog.exec():
            return {"cancelled": True, "path": "", "error": "", "help": "", "url": ""}
        urls = dialog.selectedUrls()
        if not urls:
            return {"cancelled": True, "path": "", "error": "", "help": "", "url": ""}
        return self.resolveUrl(urls[0].toString())

    @Slot(str, result="QVariant")
    def resolveUrl(self, url: str) -> dict:  # noqa: N802 - QML style
        """Resolve any picked location to a usable path (exposed for tests)."""
        picked: PickedFolder = resolve_picked_url(url)
        if picked.ok:
            return {"cancelled": False, "path": picked.path, "error": "", "help": "", "url": picked.url}
        log.info("could not use picked location %s: %s", url, picked.error)
        return {
            "cancelled": False,
            "path": "",
            "error": picked.error,
            "help": picked.help_text,
            "url": picked.url,
        }

    @Slot(str)
    def openInFileManager(self, url: str) -> None:  # noqa: N802 - QML style
        """Offered alongside an unmounted-share error so the user can mount it."""
        if url:
            open_external(url)

    # -- dialog results ----------------------------------------------------

    @Slot(str, "QVariant")
    def submit(self, popup_type: str, values: Any = None) -> None:
        """Apply a dialog's result. Unknown types just close the popup."""
        data = as_dict(values)
        handler = getattr(self, f"_submit_{_slug(popup_type)}", None)
        try:
            if handler is not None:
                handler(data)
        except Exception as exc:
            log.exception("dialog %s failed", popup_type)
            self.store.show_popup(PopupType.ERROR, error=str(exc))
            return
        self.store.close_popup()

    def _repo(self):
        return self.store.selected_repository

    def _submit_addrepository(self, values: dict) -> None:
        path = str(values.get("path") or "").strip()
        if path:
            self.store.add_repositories([os.path.expanduser(path)])

    def _submit_createrepository(self, values: dict) -> None:
        self.store.create_repository(
            os.path.expanduser(str(values.get("path") or "")),
            str(values.get("description") or ""),
            values.get("defaultBranch") or None,
            name=values.get("name") or None,
            create_readme=bool(values.get("createReadme")),
            gitignore=values.get("gitignore") or None,
            license_name=values.get("license") or None,
        )

    def _submit_clonerepository(self, values: dict) -> None:
        url = str(values.get("url") or "").strip()
        path = os.path.expanduser(str(values.get("path") or "").strip())
        if url and path:
            self.store.clone(url, path, str(values.get("branch") or "") or None)

    def _submit_createbranch(self, values: dict) -> None:
        repo = self._repo()
        name = str(values.get("name") or "").strip()
        if repo and name:
            self.store.create_branch_and_checkout(
                repo, name, values.get("startPoint") or None, no_track=bool(values.get("noTrack"))
            )

    def _submit_renamebranch(self, values: dict) -> None:
        repo = self._repo()
        name = str(values.get("name") or "").strip()
        old = str(values.get("from") or values.get("branch") or "").strip()
        if repo and name and old:
            self.store.rename_current_branch(repo, old, name)

    def _submit_deletebranch(self, values: dict) -> None:
        repo = self._repo()
        branch = str(values.get("branch") or "").strip()
        if repo and branch:
            self.store.delete_branch(
                repo,
                branch,
                include_upstream=bool(values.get("includeUpstream")),
                remote_only=bool(values.get("remoteOnly")),
            )

    def _submit_deleteremotebranch(self, values: dict) -> None:
        values = dict(values)
        values["remoteOnly"] = True
        self._submit_deletebranch(values)

    def _submit_createtag(self, values: dict) -> None:
        repo = self._repo()
        name = str(values.get("name") or "").strip()
        sha = str(values.get("sha") or "").strip()
        if repo and name and sha:
            self.store.create_tag(repo, name, sha)

    def _submit_deletetag(self, values: dict) -> None:
        repo = self._repo()
        name = str(values.get("name") or "").strip()
        if repo and name:
            self.store.delete_tag(repo, name)

    def _submit_removerepository(self, values: dict) -> None:
        repo = self._repo()
        if repo:
            self.store.remove_repository(repo, bool(values.get("deleteFiles")))

    def _submit_publishrepository(self, values: dict) -> None:
        repo = self._repo()
        account = self.store.account_for_repo(repo) if repo else None
        if repo is None or account is None:
            return
        self.store.publish_repository(
            repo,
            str(values.get("name") or repo.display_name),
            str(values.get("description") or ""),
            bool(values.get("private")),
            values.get("org") or None,
            account,
        )

    def _submit_confirmdiscardchanges(self, values: dict) -> None:
        repo = self._repo()
        if repo is None:
            return
        state = self.store.state_for(repo)
        paths = list(values.get("paths") or [])
        if values.get("discardingAll") or not paths:
            files = list(state.status.working_directory.files) if state.status else []
        else:
            files = [f for f in (state.status.working_directory.files if state.status else []) if f.path in paths]
        if bool(values.get("dontAskAgain")):
            self.store.settings.confirm_discard_changes = False
            self.store.persist_settings()
        self.store.discard_files(repo, files, move_to_trash=not bool(values.get("permanent")))

    def _submit_confirmdiscardselection(self, values: dict) -> None:
        repo = self._repo()
        path = str(values.get("path") or "")
        if repo and path:
            self.store.discard_selection(repo, path)

    def _submit_confirmforcepush(self, values: dict) -> None:
        repo = self._repo()
        if bool(values.get("dontAskAgain")):
            self.store.settings.confirm_force_push = False
            self.store.persist_settings()
        if repo:
            self.store.push_repo(repo, force=True)

    def _submit_pushbranchcommits(self, _values: dict) -> None:
        repo = self._repo()
        if repo:
            self.store.push_repo(repo)

    def _submit_signin(self, values: dict) -> None:
        endpoint = str(values.get("endpoint") or "").strip()
        if endpoint:
            self.store.set_sign_in_endpoint(endpoint)
        self.store.request_browser_auth()

    def _submit_genericgitauthentication(self, values: dict) -> None:
        from .. import secrets

        host = str(values.get("host") or "")
        username = str(values.get("username") or "")
        if not host or not username:
            return
        secrets.set_generic(host, username, str(values.get("password") or ""))
        self.store.retry_last_remote_action()

    def _submit_preferences(self, values: dict) -> None:
        for key, value in values.items():
            self.bridge.updateSetting(key, value)

    def _submit_repositorysettings(self, values: dict) -> None:
        """Remote URL, .gitignore and the local git identity, as Desktop groups them."""
        repo = self._repo()
        if repo is None:
            return
        remote = values.get("remoteUrl")
        if remote is not None:
            self.store.save_remote_url(repo, str(remote))
        gitignore = values.get("gitignore")
        if gitignore is not None:
            self.store.save_gitignore_text(repo, str(gitignore))
        name, email = values.get("authorName"), values.get("authorEmail")
        if name is not None or email is not None:
            self.store.save_local_git_config(repo, str(name or ""), str(email or ""))
        target = values.get("forkContributionTarget")
        if target:
            self.store.set_fork_contribution_target(repo, target)

    def _submit_createfork(self, _values: dict) -> None:
        repo = self._repo()
        if repo:
            self.store.create_fork(repo)

    def _submit_createtutorialrepository(self, values: dict) -> None:
        account = self.store.accounts[0] if self.store.accounts else None
        if account is not None:
            self.store.create_tutorial_repository(account, str(values.get("name") or "desktop-tutorial"))

    def _submit_stashandswitchbranch(self, values: dict) -> None:
        repo = self._repo()
        branch = str(values.get("branch") or "")
        if repo and branch:
            self.store.stash_then_checkout(repo, branch)

    def _submit_warnlocalchangesbeforeundo(self, _values: dict) -> None:
        repo = self._repo()
        if repo:
            self.store.undo_last_commit(repo, show_confirmation=False)

    def _submit_error(self, _values: dict) -> None:
        return


def _slug(popup_type: str) -> str:
    """``CloneRepository`` -> ``clonerepository`` for handler lookup."""
    return "".join(ch for ch in popup_type.lower() if ch.isalnum())
