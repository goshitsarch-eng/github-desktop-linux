"""Dialog wording, and the rules for choosing between wordings.

Layout lives in ``ui/qml/dialogs``; every string a dialog shows is here so it
can be checked against Desktop without a window on screen.
:func:`dialog_copy` assembles the title, body and button labels for one popup
and the QML dialog binds to that.
"""

from __future__ import annotations

from typing import Any

from ..models import ComputedAction, PopupType
from ..shells import open_external
from ..store import AppStore

THERE_ARE_NO_CHANGES = "There are no changes."
COULD_NOT_FIND_DEFAULT_BRANCH = "Could not find a default branch to compare against."
SELECT_A_BASE_BRANCH_ABOVE = "Select a base branch above."


def pull_request_merge_status_text(kind: ComputedAction | None) -> str:
    """Desktop `PullRequestMergeStatus` footer copy (Linux)."""
    if kind is None:
        return ""
    if kind == ComputedAction.LOADING:
        return "Checking mergeability… Don’t worry, you can still create the pull request."
    if kind == ComputedAction.INVALID:
        return "Error checking merge status. Unable to merge unrelated histories in this repository"
    if kind == ComputedAction.CLEAN:
        return "Able to merge. These branches can be automatically merged."
    if kind == ComputedAction.CONFLICTS:
        return "Can't automatically merge. Don’t worry, you can still create the pull request."
    return ""


def open_pull_request_no_changes_body(*, has_merge_base: bool, base: str, current: str) -> str:
    """Desktop `renderNoChanges` body under `There are no changes.`"""
    if has_merge_base:
        return f"{base} is up to date with all commits from {current}."
    return f"{base} and {current} are entirely different commit histories."


def open_pull_request_ok_label(*, has_pull_request: bool) -> str:
    """Desktop Linux `{View|Create} pull request`."""
    return "View pull request" if has_pull_request else "Create pull request"


def open_pull_request_ok_title(*, has_pull_request: bool, enterprise: bool = False) -> str:
    """Desktop `okButtonTitle`: `{View|Create} pull request on GitHub[ Enterprise].`"""
    verb = "View" if has_pull_request else "Create"
    suffix = " Enterprise" if enterprise else ""
    return f"{verb} pull request on GitHub{suffix}."


def open_pull_request_commit_word(count: int) -> str:
    """Desktop `commit${commitCount > 1 ? 's' : ''}`."""
    return "commit" if count == 1 else "commits"


def open_pull_request_merge_prefix(count: int) -> str:
    """Desktop `Merge {commits} into ` before `BranchSelect`."""
    return f"Merge {count} {open_pull_request_commit_word(count)} into "


def open_pull_request_merge_suffix(current: str) -> str:
    """Desktop ` from {currentBranch}.` after `BranchSelect`."""
    return f" from {current}."


LINES_CHANGED_SR_ONLY = "Lines changed:"


def open_pull_request_added_lines(added: int) -> str:
    """Desktop `{linesAdded} added lines`."""
    return f"{added} added lines"


def open_pull_request_removed_lines(deleted: int) -> str:
    """Desktop `{linesDeleted} removed lines`."""
    return f"{deleted} removed lines"


def open_pull_request_lines_changed(*, added: int, deleted: int) -> str:
    """Desktop `{linesAdded} added lines, {linesDeleted} removed lines`."""
    return f"{open_pull_request_added_lines(added)}, {open_pull_request_removed_lines(deleted)}"


CREATE_WITHOUT_PUSHING = "Create without pushing"


def pluralize(number_of_commits: int, unit: str) -> str:
    """Desktop `pluralize` in `push-branch-commits.tsx`."""
    if number_of_commits == 1:
        return f"{number_of_commits} {unit}"
    return f"{number_of_commits} {unit}s"


def renderPublishView(unPushedCommits: int | None) -> bool:
    """Desktop `renderPublishView(unPushedCommits)` — true when the branch is unpublished."""
    return unPushedCommits is None


def push_branch_commits_heading(*, unpublished: bool) -> str:
    """Desktop Linux `Publish branch?` / `Push local changes?`."""
    return "Publish branch?" if unpublished else "Push local changes?"


def push_branch_commits_ok_label(*, unpublished: bool) -> str:
    """Desktop Linux `Publish branch` / `Push commits`."""
    return "Publish branch" if unpublished else "Push commits"


def push_branch_commits_body(*, unpublished: bool, unpushed: int = 0, branch: str = "") -> str:
    """Desktop `PushBranchCommits` dialog body (title + message paragraphs)."""
    name = branch.strip() or "this branch"
    if unpublished:
        return (
            "Your branch must be published before opening a pull request.\n\n"
            f"Would you like to publish {name} now and open a pull request?"
        )
    local_commits = pluralize(unpushed, "local commit")
    return (
        f"You have {local_commits} that haven't been pushed to the remote yet.\n\n"
        f"Would you like to push your changes to {name} before creating your pull request?"
    )


def _coerce_enum(raw: Any, enum_cls: Any) -> Any:
    if isinstance(raw, enum_cls):
        return raw
    if isinstance(raw, str):
        try:
            return enum_cls(raw)
        except ValueError:
            return None
    return None


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


MERGE_UNDO_WARNING = (
    "Undoing a merge commit will apply the changes from the merge into your working "
    "directory, and committing again will create an entirely new commit. This means "
    "you will lose the merge commit and, as a result, commits from the merged branch "
    "could disappear from this branch."
)


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
        store.reset_to_commit(repo, show_confirmation=False, sha=sha)


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
    if repo:
        store.discard_stash(repo, confirmed=True)


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
    target = payload.get("branch")
    if not target:
        return
    store.stash_then_checkout(repo, str(target))


def _stash_and_retry(store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    store.stash_and_retry(repo, payload)


def _delete_current_branch(store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    branch = state.status.current_branch if state.status else None
    if branch:
        store.delete_branch(repo, branch)


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


# --- dialog copy -----------------------------------------------------------
#
# One entry per PopupType that needs more than a title. `dialog_copy()` picks
# the right wording from the popup's payload; the QML dialog only lays it out.

CONFIRM_ABORT = "Confirm abort"
DO_NOT_SHOW_AGAIN = "Do not show this message again"
I_UNDERSTAND = "I understand"
IM_SURE = "I'm sure"
COMMIT_ANYWAY = "Commit anyway"
YES_COMMIT_FILES = "Yes, commit files"
CONTINUE_IN_BROWSER = "Continue in browser"
OPEN_OPTIONS = "Open options"

# Force push
FORCE_PUSH_TITLE = "Are you sure you want to force push?"
FORCE_PUSH_BODY = (
    "A force push will rewrite history on {branch}. Any collaborators working on "
    "this branch will need to reset their own copy to match."
)
REQUIRE_FORCE_PUSH = "This will require force push to update the remote branch."

# Undo / reset
UNDO_COMMIT_TITLE = "Undo commit?"
UNDO_DISABLED_WHILE_UPDATING = "Undo is disabled while the repository is being updated"

# Discarding
DISCARD_TRASH_NOTE = "Changes can be restored by retrieving them from the Trash."
DISCARD_PERMANENT_NOTE = "Discarded changes will be unrecoverable."
DISCARD_PERMANENTLY = "Changes will be discarded permanently and cannot be restored."
UNTRACKED_FILES_EXCLUDED = "Untracked files will be excluded when stashing."

# Stashing
STASH_ALL_TITLE = "Stash all changes?"
STASH_OVERWRITE_BODY = (
    "Your current stash will be overwritten by creating a new stash. "
    "This will overwrite your existing stash for this branch."
)
DISCARD_STASH_TITLE = "Are you sure you want to discard these stashed changes?"
STASH_AND_CONTINUE = "Stash changes and continue"
STASH_SWITCH_QUESTION = "You have changes on this branch. What would you like to do with them?"
LEAVE_MY_CHANGES = "Leave my changes on {branch}"
BRING_MY_CHANGES = "Bring my changes to {branch}"

# Branches
DELETE_BRANCH_REMOTE_NOTE = "The branch also exists on the remote."
ALSO_MOVE_REPOSITORY = "Also move this repository to the trash"
REPOSITORY_MISSING_TITLE = "Can't find this repository"
COULD_NOT_GET_DESCRIPTION = "Couldn't get the repository's description"
CONFIGURE_GIT_USER = "ConfigureGitUser"
CREDENTIAL_HELPER_SIGN_IN = "isCredentialHelperSignIn"
DELETE_BRANCH_REMOTE_CHECK = "Yes, delete this branch on the remote"
DELETE_BRANCH_PR_NOTE = "This branch may have an open pull request associated with it."
BRANCH_NOT_FOUND = "Sorry, I can't find that branch"
CREATE_BRANCH_INSTEAD = "Do you want to create a new branch instead?"
REMOTE_BRANCH_NOT_FOUND = "Sorry, I can't find that remote branch."
PR_REQUIRES_REMOTE_BRANCH = "You can only open pull requests against remote branches."
BRANCH_EXISTS_ON_REMOTE = "A branch with that name already exists on the remote."
DETACHED_HEAD_WARNING = "Checking out a commit will create a detached HEAD."

# Repositories
NOT_A_GIT_REPOSITORY = "This directory does not appear to be a Git repository."
BARE_REPOSITORY_UNSUPPORTED = "Bare repositories are not currently supported."
UNSAFE_DIRECTORY_HINT = (
    "Git refused to open this directory because it is owned by another user. You can "
    "add an exception for this directory with `git config --global --add safe.directory`."
)
REPOSITORY_NOT_FOUND = "Sorry, I can't find that repository"
PULL_REQUEST_NOT_FOUND = "Sorry, I can't find that pull request!"
WILL_BE_CREATED_AS = "Will be created as {name}"
INITIALIZE_WITH_README = "Initialize this repository with a README"
PRIVATE_REPOSITORY = "Private repository"
PUBLISH_REPOSITORY_TITLE = "Publish your repository to GitHub"
PUBLISH_BRANCH_TITLE = "Publish your branch"
DEFAULT_BRANCH_NOTE = "The default branch in your repository is {branch}."
CLONING_PROGRESS = "Cloning…"
CANCEL_CLONE = "Cancel clone"
RETRY_CLONE = "Would you like to retry cloning {name}?"
CONFIG_LOCK_FILE_EXISTS = "ConfigLockFileExists"
CONFIG_LOCK_BODY = (
    "A lock file (config.lock) exists in this repository's .git directory. "
    "Another Git process may be running, or a previous one may have crashed."
)
GITIGNORE_HELP = "Learn more about gitignore files"
GITIGNORE_DESCRIPTION = "Ignored files are intentionally untracked files that Git should ignore."
LFS_HELP_PATH = "versioning-large-files"
UPDATE_LFS_FILTERS = "Update existing Git LFS filters"

# Accounts and auth
SIGN_IN_DOTCOM = "Sign in to your GitHub.com account"
SIGN_INTO_DOTCOM = "Sign into GitHub.com"
ADD_ENTERPRISE_ACCOUNT = "Add GitHub Enterprise account"
ALREADY_SIGNED_IN = "You're already signed in"
REAUTHORIZATION_REQUIRED = "Re-authorization required"
INVALIDATED_TOKEN_TITLE = "Invalidated account token"
SSH_CONTINUE_CONNECTING = "Are you sure you want to continue connecting?"
REMEMBER_PASSPHRASE = "Remember passphrase"

# Git configuration
GIT_CONFIG_SCOPE_QUESTION = "For this repository I wish to"
USE_GLOBAL_GIT_CONFIG = "Use my global Git config"
USE_LOCAL_GIT_CONFIG = "Use a local Git config"
EDIT_GLOBAL_GIT_CONFIG = "Edit global Git config"
EMAIL_MISMATCH_WARNING = "This email address doesn't match your GitHub account"
# Desktop's Git preferences group for line endings and whitespace handling.
LINE_ENDINGS_LABEL = "Line endings and whitespace"
LINE_ENDINGS_HELP = "How Git rewrites line endings when checking files out and committing them."
CONFIGURE_CUSTOM_EDITOR = "Configure custom editor"
DOWNLOAD_EDITOR = "Download {SUGGESTED_EXTERNAL_EDITOR}"
UNABLE_TO_OPEN_EDITOR = "Unable to open external editor"
UNABLE_TO_OPEN_SHELL = "Unable to open shell"
UNABLE_TO_LOCATE_GIT = "Unable to locate Git"
INSTALL_GIT = "Install Git"
OPEN_WITHOUT_GIT = "Open without Git"
FORK_CONTRIBUTE_PARENT = "Contribute to the parent repository"
CREATE_FORK_MANUALLY = "You can continue by creating the fork manually on GitHub."
CREATING_FORK = "Creating fork…"

# Notifications and metrics
HIGH_SIGNAL_EVENTS = "Notifications are only shown for high-signal events."
STASH_TOOLBAR_ALWAYS = "Always available in the toolbar"
STASH_TOOLBAR_WHEN_EXISTS = "When a stash exists"
USER_METRICS_LABEL = "Help GitHub Desktop improve by submitting usage stats"
USER_METRICS_HELP = "Learn more about user metrics."
CREDENTIAL_MANAGER_LABEL = "Use Git Credential Manager"
CREDENTIAL_MANAGER_URL = "https://gh.io/gcm"
SHOW_USER_GUIDES = "Show User Guides"

# Merge / rebase / cherry-pick
RESOLVE_ALL_CONFLICTS = "Resolve all conflicts before continuing"
CONFLICT_MARKERS_REMAIN = "Leftover conflict markers remain"
ABLE_TO_MERGE_AUTOMATICALLY = "Able to merge automatically"
NEWER_COMMITS_ON_REMOTE = "Newer commits on remote"
CONFIRM_CONFLICTED_COMMIT_TITLE = "Confirm committing conflicted files"
CHERRY_PICK_SAME_BRANCH = "You are not able to cherry-pick from and to the same branch"
EMPTY_COMMIT_MESSAGE = "Empty commit message"

# Copilot
COPILOT_DISCLAIMER_TITLE = "Responsible use of Copilot in GitHub Desktop"
COPILOT_AI_NOTE = "Copilot is powered by AI, so mistakes are possible. Review the message before committing."
COMMIT_MESSAGE_OVERRIDE_TITLE = "Commit message override"
COMMIT_MESSAGE_OVERRIDE_BODY = (
    "Your commit message will be overridden by the generated commit message."
)
OVERRIDING_COMMIT_MESSAGE = "Overriding commit message with generated message"

# Secret scanning
EXPOSE_SECRET_LABEL = "Allow me to expose this secret"
FALSE_POSITIVE_LABEL = "It's a false positive"
SHOW_MORE_LOCATIONS = "Show More locations"
VIEW_REPOSITORY_RULESETS = "View repository rulesets"

# Thank you / legal
YOU_CONTRIBUTED = "You contributed:"
LICENSE_NOTICES = "License and Open Source Notices"
TERMS_AND_CONDITIONS = "Terms and Conditions"
EXAMPLE_LINK = "This is an example link"

# Unreachable commits
COMMIT_REACHABILITY = "Commit reachability"
UNREACHABLE_COMMITS_HELP = "Learn more about unreachable commits."


def force_push_body(branch: str) -> str:
    """Desktop's force-push confirmation body, named for the branch at risk."""
    return FORCE_PUSH_BODY.format(branch=branch or "this branch")


def discard_note(*, move_to_trash: bool) -> str:
    """Whether discarded work is recoverable, said plainly."""
    return DISCARD_TRASH_NOTE if move_to_trash else DISCARD_PERMANENT_NOTE


def stash_switch_options(current: str, target: str) -> tuple[str, str]:
    """The two ways out of the "you have changes" prompt when switching branch."""
    return (
        LEAVE_MY_CHANGES.format(branch=current or "this branch"),
        BRING_MY_CHANGES.format(branch=target or "the other branch"),
    )


def dialog_copy(popup_type: str, payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Title, body and button labels for one popup.

    QML binds to this rather than embedding wording, so the strings stay in
    one place and the parity tests can read them.
    """
    data = dict(payload or {})
    branch = str(data.get("branch") or "")
    name = str(data.get("name") or "")
    copy: dict[str, str] = {"title": "", "body": "", "okLabel": "", "checkLabel": ""}

    if popup_type == PopupType.CONFIRM_FORCE_PUSH.value:
        copy.update(
            title=FORCE_PUSH_TITLE,
            body=force_push_body(branch),
            okLabel=IM_SURE,
            checkLabel=DO_NOT_SHOW_AGAIN,
        )
    elif popup_type == PopupType.WARN_FORCE_PUSH.value:
        copy.update(title=FORCE_PUSH_TITLE, body=REQUIRE_FORCE_PUSH, okLabel=IM_SURE)
    elif popup_type == PopupType.WARN_LOCAL_CHANGES_BEFORE_UNDO.value:
        copy.update(title=UNDO_COMMIT_TITLE, body=MERGE_UNDO_WARNING, okLabel=I_UNDERSTAND)
    elif popup_type == PopupType.CONFIRM_DISCARD_STASH.value:
        copy.update(title=DISCARD_STASH_TITLE, body=DISCARD_PERMANENTLY)
    elif popup_type == PopupType.CONFIRM_OVERWRITE_STASH.value:
        copy.update(title=STASH_ALL_TITLE, body=STASH_OVERWRITE_BODY)
    elif popup_type == PopupType.STASH_AND_SWITCH_BRANCH.value:
        leave, bring = stash_switch_options(str(data.get("current") or ""), branch)
        copy.update(title=STASH_SWITCH_QUESTION, body=UNTRACKED_FILES_EXCLUDED, okLabel=STASH_AND_CONTINUE)
        copy["leaveLabel"] = leave
        copy["bringLabel"] = bring
    elif popup_type == PopupType.CONFIRM_CHECKOUT_COMMIT.value:
        copy.update(title=DETACHED_HEAD_WARNING, okLabel=I_UNDERSTAND, checkLabel=DO_NOT_SHOW_AGAIN)
    elif popup_type == PopupType.COMMIT_CONFLICTS_WARNING.value:
        copy.update(
            title=CONFIRM_CONFLICTED_COMMIT_TITLE,
            body=CONFLICT_MARKERS_REMAIN,
            okLabel=YES_COMMIT_FILES,
        )
    elif popup_type == PopupType.PUSH_NEEDS_PULL.value:
        copy.update(title=NEWER_COMMITS_ON_REMOTE, okLabel=COMMIT_ANYWAY)
    elif popup_type == PopupType.INVALIDATED_TOKEN.value:
        copy.update(title=INVALIDATED_TOKEN_TITLE, okLabel=SIGN_INTO_DOTCOM)
    elif popup_type == PopupType.SAML_REAUTH_REQUIRED.value:
        copy.update(title=REAUTHORIZATION_REQUIRED, okLabel=CONTINUE_IN_BROWSER)
    elif popup_type == PopupType.ADD_SSH_HOST.value:
        copy.update(title=SSH_CONTINUE_CONNECTING)
    elif popup_type == PopupType.SSH_KEY_PASSPHRASE.value:
        copy.update(checkLabel=REMEMBER_PASSPHRASE)
    elif popup_type == PopupType.INSTALL_GIT.value:
        copy.update(title=UNABLE_TO_LOCATE_GIT, okLabel=INSTALL_GIT, checkLabel=OPEN_WITHOUT_GIT)
    elif popup_type == PopupType.EXTERNAL_EDITOR_FAILED.value:
        copy.update(title=UNABLE_TO_OPEN_EDITOR, okLabel=DOWNLOAD_EDITOR)
    elif popup_type == PopupType.OPEN_SHELL_FAILED.value:
        copy.update(title=UNABLE_TO_OPEN_SHELL)
    elif popup_type == PopupType.LFS_ATTRIBUTE_MISMATCH.value:
        copy.update(okLabel=UPDATE_LFS_FILTERS)
    elif popup_type == PopupType.CREATE_FORK.value:
        copy.update(body=CREATE_FORK_MANUALLY, okLabel=FORK_CONTRIBUTE_PARENT)
    elif popup_type == PopupType.DELETE_BRANCH.value:
        copy.update(body=DELETE_BRANCH_PR_NOTE, checkLabel=DELETE_BRANCH_REMOTE_CHECK)
        copy["note"] = DELETE_BRANCH_REMOTE_NOTE
    elif popup_type == PopupType.GENERATE_COMMIT_MESSAGE_DISCLAIMER.value:
        copy.update(title=COPILOT_DISCLAIMER_TITLE, body=COPILOT_AI_NOTE, okLabel=I_UNDERSTAND)
    elif popup_type == PopupType.GENERATE_COMMIT_MESSAGE_OVERRIDE.value:
        copy.update(
            title=COMMIT_MESSAGE_OVERRIDE_TITLE,
            body=COMMIT_MESSAGE_OVERRIDE_BODY,
            okLabel=OVERRIDING_COMMIT_MESSAGE,
            checkLabel=DO_NOT_SHOW_AGAIN,
        )
    elif popup_type == PopupType.PUSH_PROTECTION_ERROR.value:
        copy["okLabel"] = SHOW_MORE_LOCATIONS
    elif popup_type == PopupType.BYPASS_PUSH_PROTECTION.value:
        copy.update(title=EXPOSE_SECRET_LABEL, body=FALSE_POSITIVE_LABEL)
    elif popup_type == PopupType.UNREACHABLE_COMMITS.value:
        copy.update(title=COMMIT_REACHABILITY, body=UNREACHABLE_COMMITS_HELP)
    elif popup_type == PopupType.TERMS_AND_CONDITIONS.value:
        copy.update(title=TERMS_AND_CONDITIONS)
    elif popup_type == PopupType.ACKNOWLEDGEMENTS.value:
        copy.update(title=LICENSE_NOTICES)
    elif popup_type == PopupType.THANK_YOU.value:
        copy.update(title=YOU_CONTRIBUTED)
    elif popup_type == PopupType.MULTI_COMMIT_OPERATION.value:
        copy.update(title=RESOLVE_ALL_CONFLICTS, okLabel=CONFIRM_ABORT)
    elif popup_type == PopupType.CREATE_REPOSITORY.value:
        copy.update(title=WILL_BE_CREATED_AS.format(name=name), checkLabel=INITIALIZE_WITH_README)
    elif popup_type == PopupType.PUBLISH_REPOSITORY.value:
        copy.update(title=PUBLISH_REPOSITORY_TITLE, checkLabel=PRIVATE_REPOSITORY)
    elif popup_type == PopupType.ADD_REPOSITORY.value:
        copy.update(body=NOT_A_GIT_REPOSITORY)
        copy["note"] = BARE_REPOSITORY_UNSUPPORTED
        copy["hint"] = UNSAFE_DIRECTORY_HINT
    elif popup_type == PopupType.CLONE_REPOSITORY.value:
        copy.update(body=RETRY_CLONE.format(name=name or "this repository"), okLabel=CANCEL_CLONE)
    elif popup_type == PopupType.SIGN_IN.value:
        copy.update(title=SIGN_IN_DOTCOM, okLabel=CONTINUE_IN_BROWSER)
        copy["note"] = ADD_ENTERPRISE_ACCOUNT
    elif popup_type == PopupType.START_PULL_REQUEST.value:
        copy.update(title=ABLE_TO_MERGE_AUTOMATICALLY, checkLabel="Create as draft")
    return copy
