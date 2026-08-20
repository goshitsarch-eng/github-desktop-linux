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
    def is_force_needed(self) -> bool:
        text = f"{self.stderr}\n{self.stdout}".lower()
        return "non-fast-forward" in text or "failed to push some refs" in text


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
