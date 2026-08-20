"""Typed errors used across git, GitHub API, and UI layers."""

from __future__ import annotations

import re


class DesktopError(Exception):
    """Base error for the native GitHub Desktop application."""


class GitError(DesktopError):
    def __init__(
        self,
        message: str,
        *,
        args: list[str] | None = None,
        exit_code: int | None = None,
        stdout: str = "",
        stderr: str = "",
        git_error: str | None = None,
        path: str | None = None,
    ) -> None:
        super().__init__(message)
        self.git_args = args or []
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.git_error = git_error
        self.path = path

    @property
    def is_auth_failure(self) -> bool:
        if is_auth_failure_error(self.git_error):
            return True
        text = f"{self.stderr}\n{self.stdout}".lower()
        return any(
            needle in text
            for needle in (
                "authentication failed",
                "could not read username",
                "invalid username or password",
                "permission denied (publickey)",
                "error: 401",
                "fatal: could not read password",
                "repository not found",
            )
        )

    @property
    def is_not_a_repository(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "not a git repository" in text or self.exit_code == 128

    @property
    def is_conflicts(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return any(
            needle in text
            for needle in (
                "fix conflicts",
                "needs merge",
                "unmerged files",
                "conflict",
                "you have unstaged changes",
                "your local changes to the following files would be overwritten",
            )
        )

    @property
    def is_push_protection(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}"
        return "GH013" in text or "push cannot contain secrets" in text.lower()

    @property
    def is_saml_reauth(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "saml" in text and (
            "sso" in text or "authorization" in text or "re-authorize" in text
        )

    @property
    def is_workflow_scope(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "workflow" in text and "scope" in text

    @property
    def is_lfs_attribute_mismatch(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "filter.lfs" in text and "match" in text

    @property
    def is_force_needed(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "non-fast-forward" in text or "failed to push some refs" in text

    @property
    def is_local_changes_overwritten(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "your local changes to the following files would be overwritten" in text


class GitNotFoundError(DesktopError):
    pass


class NotARepositoryError(DesktopError):
    pass


class DiscardChangesError(DesktopError):
    """Desktop `DiscardChangesError`: trash failed and the user should confirm a permanent discard."""

    def __init__(self, message: str, files: list | None = None) -> None:
        super().__init__(message)
        self.files = files or []


class AuthenticationError(DesktopError):
    pass


class APIError(DesktopError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: str = "",
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.headers = headers or {}


class MaxResultsError(DesktopError):
    """Desktop `MaxResultsError`: too many updated PRs to page incrementally."""


class CopilotError(DesktopError):
    pass


class ValidationError(DesktopError):
    pass


class ConfigLockError(DesktopError):
    def __init__(self, message: str, lock_path: str | None = None) -> None:
        super().__init__(message)
        self.lock_path = lock_path


def remote_message(stderr: str) -> str:
    needle = "remote: "
    return "\n".join(line[len(needle) :] for line in stderr.splitlines() if line.startswith(needle))


def parse_saml_organization(text: str) -> str | None:
    """Extract the org name from a GitHub SAML SSO re-authorization error."""
    import re

    blob = remote_message(text) or text
    match = re.search(
        r"`([^']+)' organization has enabled or enforced SAML SSO.*?you must re-authorize",
        blob,
        re.IGNORECASE | re.DOTALL,
    )
    if match:
        return match.group(1)
    match = re.search(r"organization has enabled or enforced SAML SSO", blob, re.IGNORECASE)
    if match:
        before = blob[: match.start()]
        org = re.search(r"`([^']+)'\s*$", before.strip())
        if org:
            return org.group(1)
    return None


def overwritten_files_from_error(text: str) -> list[str]:
    """Parse paths from `Your local changes to the following files would be overwritten`."""
    files: list[str] = []
    collecting = False
    for raw in text.splitlines():
        line = raw.strip()
        lower = line.lower()
        if "would be overwritten" in lower:
            collecting = True
            continue
        if not collecting:
            continue
        if not line or lower.startswith("please commit") or lower.startswith("error:") or lower.startswith("aborting"):
            if files:
                break
            continue
        files.append(line)
    return files


def extract_secret_scanning_results(text: str) -> list:
    """Parse GH013 / secret-scanning push output the way Desktop does."""
    import re

    from .models import SecretLocation, SecretScanResult

    secrets_re = re.compile(
        r"—— (?P<description>.*?) —+[\s\S]*?locations:(?P<locationsGroup>(?:\s+- commit: [a-f0-9]{40}\s+path: [\s\S]*?)+).*?(?P<bypassURL>https[\s\S]*?) ",
        re.MULTILINE,
    )
    loc_re = re.compile(
        r"- commit: (?P<commitSha>[a-f0-9]{40})\s+path: (?P<path>.*?):(?P<lineNumber>\d+)"
    )
    results = []
    blob = remote_message(text) or text
    for match in secrets_re.finditer(blob):
        groups = match.groupdict()
        locations = []
        for loc in loc_re.finditer(groups.get("locationsGroup") or ""):
            lg = loc.groupdict()
            locations.append(
                SecretLocation(
                    commit_sha=lg["commitSha"],
                    path=lg["path"],
                    line_number=int(lg["lineNumber"]),
                )
            )
        bypass = (groups.get("bypassURL") or "").strip()
        first = locations[0] if locations else None
        results.append(
            SecretScanResult(
                id=bypass.rstrip("/").split("/")[-1] if bypass else "",
                description=groups.get("description") or "",
                bypass_url=bypass,
                locations=locations,
                requires_approval="request an exemption" in (match.group(0) or ""),
                secret_type=groups.get("description") or "",
                path=first.path if first else "",
                line=first.line_number if first else None,
            )
        )
    return results


AUTH_FAILURE_ERRORS = {
    "HTTPSAuthenticationFailed",
    "SSHAuthenticationFailed",
    "SSHPermissionDenied",
}

_BAD_CONFIG_VALUE_RE = re.compile(
    r"fatal: bad config value(?: for)? ['\"]?(?P<value>[^'\"]+)['\"]? for ['\"]?(?P<key>[^'\"]+)['\"]?",
    re.IGNORECASE,
)


def is_auth_failure_error(git_error: str | None) -> bool:
    """Desktop `isAuthFailureError`."""
    return git_error in AUTH_FAILURE_ERRORS


def parse_bad_config_value_error_info(stderr: str) -> tuple[str, str] | None:
    """Desktop/dugite `parseBadConfigValueErrorInfo`."""
    match = _BAD_CONFIG_VALUE_RE.search(stderr or "")
    if not match:
        return None
    return match.group("key"), match.group("value")


def classify_git_error(stderr: str, stdout: str = "") -> str | None:
    """Map git output to a dugite-style `GitError` name."""
    text = f"{stderr}\n{stdout}"
    lower = text.lower()
    if "could not lock config file" in stderr and "File exists" in stderr:
        return "ConfigLockFileAlreadyExists"
    if "bad config value" in lower:
        return "BadConfigValue"
    if any(
        needle in lower
        for needle in (
            "authentication failed",
            "could not read username",
            "could not read password",
            "terminal prompts disabled",
            "invalid username or password",
            "error: 401",
            "fatal: could not read password",
        )
    ):
        return "HTTPSAuthenticationFailed"
    if "permission denied (publickey)" in lower or "permission denied (keyboard-interactive)" in lower:
        return "SSHAuthenticationFailed"
    if "permission denied" in lower and "ssh" in lower:
        return "SSHPermissionDenied"
    if "host key verification failed" in lower:
        return "SSHKeyAuditUnverified"
    if "could not resolve hostname" in lower or "failed to connect" in lower:
        return "HostDown"
    if "the remote end hung up" in lower or "early eof" in lower:
        return "RemoteDisconnection"
    if "not a git repository" in lower:
        return "NotAGitRepository"
    if "unrelated histories" in lower:
        return "CannotMergeUnrelatedHistories"
    if "your local changes to the following files would be overwritten" in lower:
        return "LocalChangesOverwritten"
    if "gh013" in lower or "push cannot contain secrets" in lower:
        return "PushWithSecretDetected"
    if "keep my email address private" in lower or "you can only push using a verified email" in lower:
        return "PushWithPrivateEmail"
    if "file exceeds github's file size restriction" in lower or (
        "100 mb" in lower and "file" in lower
    ):
        return "PushWithFileSizeExceedingLimit"
    if "protected branch" in lower and "review" in lower:
        return "ProtectedBranchRequiresReview"
    if "required status check" in lower:
        return "ProtectedBranchRequiredStatus"
    if "protected branch" in lower and "delete" in lower:
        return "ProtectedBranchDeleteRejected"
    if "protected branch" in lower and "force" in lower:
        return "ProtectedBranchForcePush"
    if "force push has been rejected" in lower:
        return "ForcePushRejected"
    if "non-fast-forward" in lower or "failed to push some refs" in lower:
        return "PushNotFastForward"
    if "fix conflicts and then commit" in lower or "merge conflict" in lower:
        return "MergeConflicts"
    if "could not apply" in lower and "rebase" in lower:
        return "RebaseConflicts"
    if "nothing to commit" in lower:
        return "NothingToCommit"
    if "already exists" in lower and "branch" in lower:
        return "BranchAlreadyExists"
    if "already exists" in lower and "tag" in lower:
        return "TagAlreadyExists"
    if "filter.lfs" in lower and "match" in lower:
        return "LFSAttributeDoesNotMatch"
    if "is owned by" in lower and "safe.directory" in lower:
        return "UnsafeDirectory"
    if "path exists but not in" in lower:
        return "PathExistsButNotInRef"
    if "repository not found" in lower:
        if "ssh://" in lower or "git@" in lower:
            return "SSHRepositoryNotFound"
        return "HTTPSRepositoryNotFound"
    if "there is no merge to abort" in lower:
        return "NoMergeToAbort"
    if "unmerged files" in lower or "unresolved conflict" in lower:
        return "UnresolvedConflicts"
    if "lock file already exists" in lower:
        return "LockFileAlreadyExists"
    if "patch does not apply" in lower or "patch failed" in lower:
        return "PatchDoesNotApply"
    if "is outside repository" in lower:
        return "OutsideRepository"
    if "does not exist" in lower and "path" in lower:
        return "PathDoesNotExist"
    return None


def get_description_for_error(error: str | None, stderr: str = "") -> str | None:
    """Desktop `getDescriptionForError` — friendly copy for dugite GitError codes."""
    if not error:
        return None
    if is_auth_failure_error(error):
        return (
            "Authentication failed. Some common reasons include:\n\n"
            "- You are not logged in to your account: see File > Options.\n"
            "- You may need to log out and log back in to refresh your token.\n"
            "- You do not have permission to access this repository.\n"
            "- The repository is archived on GitHub. Check the repository settings to confirm you are still permitted to push commits.\n"
            "- If you use SSH authentication, check that your key is added to the ssh-agent and associated with your account.\n"
            "- If you use SSH authentication, ensure the host key verification passes for your repository hosting service.\n"
            "- If you used username / password authentication, you might need to use a Personal Access Token instead of your account password. Check the documentation of your repository hosting service."
        )
    descriptions = {
        "BadConfigValue": None,  # filled below
        "SSHKeyAuditUnverified": "The SSH key is unverified.",
        "RemoteDisconnection": "The remote disconnected. Check your Internet connection and try again.",
        "HostDown": "The host is down. Check your Internet connection and try again.",
        "RebaseConflicts": "We found some conflicts while trying to rebase. Please resolve the conflicts before continuing.",
        "MergeConflicts": "We found some conflicts while trying to merge. Please resolve the conflicts and commit the changes.",
        "HTTPSRepositoryNotFound": "The repository does not seem to exist anymore. You may not have access, or it may have been deleted or renamed.",
        "SSHRepositoryNotFound": "The repository does not seem to exist anymore. You may not have access, or it may have been deleted or renamed.",
        "PushNotFastForward": "The repository has been updated since you last pulled. Try pulling before pushing.",
        "BranchDeletionFailed": "Could not delete the branch. It was probably already deleted.",
        "DefaultBranchDeletionFailed": "The branch is the repository's default branch and cannot be deleted.",
        "RevertConflicts": "To finish reverting, please merge and commit the changes.",
        "EmptyRebasePatch": "There aren’t any changes left to apply.",
        "NoMatchingRemoteBranch": "There aren’t any remote branches that match the current branch.",
        "NothingToCommit": "There are no changes to commit.",
        "NoSubmoduleMapping": "A submodule was removed from .gitmodules, but the folder still exists in the repository. Delete the folder, commit the change, then try again.",
        "SubmoduleRepositoryDoesNotExist": "A submodule points to a location which does not exist.",
        "InvalidSubmoduleSHA": "A submodule points to a commit which does not exist.",
        "LocalPermissionDenied": "Permission denied.",
        "InvalidMerge": "This is not something we can merge.",
        "InvalidRebase": "This is not something we can rebase.",
        "NonFastForwardMergeIntoEmptyHead": "The merge you attempted is not a fast-forward, so it cannot be performed on an empty branch.",
        "PatchDoesNotApply": "The requested changes conflict with one or more files in the repository.",
        "BranchAlreadyExists": "A branch with that name already exists.",
        "BadRevision": "Bad revision.",
        "NotAGitRepository": "This is not a git repository.",
        "ProtectedBranchForcePush": "This branch is protected from force-push operations.",
        "ProtectedBranchRequiresReview": "This branch is protected and any changes requires an approved review. Open a pull request with changes targeting this branch instead.",
        "PushWithFileSizeExceedingLimit": "The push operation includes a file which exceeds GitHub's file size restriction of 100MB. Please remove the file from history and try again.",
        "HexBranchNameRejected": "The branch name cannot be a 40-character string of hexadecimal characters, as this is the format that Git uses for representing objects.",
        "ForcePushRejected": "The force push has been rejected for the current branch.",
        "InvalidRefLength": "A ref cannot be longer than 255 characters.",
        "CannotMergeUnrelatedHistories": "Unable to merge unrelated histories in this repository.",
        "PushWithPrivateEmail": 'Cannot push these commits as they contain an email address marked as private on GitHub. To push anyway, visit https://github.com/settings/emails, uncheck "Keep my email address private", then switch back to GitHub Desktop to push your commits. You can then enable the setting again.',
        "LFSAttributeDoesNotMatch": "Git LFS attribute found in global Git configuration does not match expected value.",
        "ProtectedBranchDeleteRejected": "This branch cannot be deleted from the remote repository because it is marked as protected.",
        "ProtectedBranchRequiredStatus": "The push was rejected by the remote server because a required status check has not been satisfied.",
        "BranchRenameFailed": "The branch could not be renamed.",
        "PathDoesNotExist": "The path does not exist on disk.",
        "InvalidObjectName": "The object was not found in the Git repository.",
        "OutsideRepository": "This path is not a valid path inside the repository.",
        "LockFileAlreadyExists": "A lock file already exists in the repository, which blocks this operation from completing.",
        "NoMergeToAbort": "There is no merge in progress, so there is nothing to abort.",
        "NoExistingRemoteBranch": "The remote branch does not exist.",
        "LocalChangesOverwritten": "Unable to switch branches as there are working directory changes which would be overwritten. Please commit or stash your changes.",
        "UnresolvedConflicts": "There are unresolved conflicts in the working directory.",
        "TagAlreadyExists": "A tag with that name already exists",
        "ConfigLockFileAlreadyExists": None,
        "RemoteAlreadyExists": None,
        "MergeWithLocalChanges": None,
        "RebaseWithLocalChanges": None,
        "GPGFailedToSignData": None,
        "ConflictModifyDeletedInBranch": None,
        "MergeCommitNoMainlineOption": None,
        "UnsafeDirectory": None,
        "PathExistsButNotInRef": None,
        "PushWithSecretDetected": None,
    }
    if error == "BadConfigValue":
        info = parse_bad_config_value_error_info(stderr)
        if info is None:
            return "Unsupported git configuration value."
        key, value = info
        return f"Unsupported value '{value}' for git config key '{key}'"
    return descriptions.get(error)
