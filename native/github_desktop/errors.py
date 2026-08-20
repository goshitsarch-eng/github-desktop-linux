"""Typed errors used across git, GitHub API, and UI layers."""

from __future__ import annotations


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
    ) -> None:
        super().__init__(message)
        self.git_args = args or []
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.git_error = git_error

    @property
    def is_auth_failure(self) -> bool:
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


class AuthenticationError(DesktopError):
    pass


class APIError(DesktopError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


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
