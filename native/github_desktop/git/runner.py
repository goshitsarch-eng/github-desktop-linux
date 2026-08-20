"""Git process runner with authentication, progress, and error mapping."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ..errors import GitError, GitNotFoundError
from ..logging import get_logger

log = get_logger()

ProgressCallback = Callable[[str, float], None]


def find_git() -> str:
    override = os.environ.get("GITHUB_DESKTOP_GIT")
    if override and os.path.isfile(override) and os.access(override, os.X_OK):
        return override
    path = shutil.which("git")
    if not path:
        raise GitNotFoundError("Git was not found on PATH")
    return path


@dataclass
class GitResult:
    stdout: str
    stderr: str
    exit_code: int
    args: list[str]
    stdout_bytes: bytes = b""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def git(
    args: Sequence[str],
    cwd: str | os.PathLike[str],
    *,
    env: Mapping[str, str] | None = None,
    stdin: str | bytes | None = None,
    success_exit_codes: set[int] | None = None,
    expected_errors: bool = False,
    name: str = "git",
    timeout: float | None = None,
    binary: bool = False,
) -> GitResult:
    """Run a git command. Raises GitError unless the exit code is allowed."""
    git_bin = find_git()
    cmd = [git_bin, *args]
    success = success_exit_codes or {0}
    merged_env = os.environ.copy()
    merged_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    merged_env.setdefault("GCM_INTERACTIVE", "Never")
    merged_env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    merged_env.setdefault("LC_ALL", "C")
    merged_env.setdefault("LANGUAGE", "C")
    if env:
        merged_env.update({k: v for k, v in env.items() if v is not None})

    stdin_bytes: bytes | None
    if stdin is None:
        stdin_bytes = None
    elif isinstance(stdin, bytes):
        stdin_bytes = stdin
    else:
        stdin_bytes = stdin.encode("utf-8")

    log.debug("git %s: %s (cwd=%s)", name, " ".join(cmd[1:]), cwd)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=merged_env,
            input=stdin_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitNotFoundError(str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(
            f"Git command timed out: {name}",
            args=list(args),
            stdout=_decode(exc.stdout or b""),
            stderr=_decode(exc.stderr or b""),
        ) from exc

    result = GitResult(
        stdout=_decode(completed.stdout),
        stderr=_decode(completed.stderr),
        exit_code=completed.returncode,
        args=list(args),
        stdout_bytes=completed.stdout,
    )
    if result.exit_code not in success:
        message = result.stderr.strip() or result.stdout.strip() or f"git {name} failed"
        raise GitError(
            message,
            args=list(args),
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def git_path_is_repository(path: str) -> bool:
    try:
        result = git(
            ["rev-parse", "--is-inside-work-tree"],
            path,
            success_exit_codes={0, 128},
            name="isRepository",
        )
        return result.exit_code == 0 and result.stdout.strip() == "true"
    except GitError:
        return False


def resolve_repository_root(path: str) -> str | None:
    try:
        result = git(
            ["rev-parse", "--show-toplevel"],
            path,
            success_exit_codes={0, 128},
            name="showToplevel",
        )
        if result.exit_code != 0:
            return None
        return result.stdout.strip() or None
    except GitError:
        return None


def env_for_remote(
    remote_url: str,
    *,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build env vars that inject HTTPS credentials without prompting."""
    env: dict[str, str] = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Never",
    }
    if extra:
        env.update(extra)
    user = username
    secret = password
    if token:
        user = user or "x-access-token"
        secret = token
    if user and secret:
        import base64

        raw = f"{user}:{secret}".encode("utf-8")
        header = "AUTHORIZATION: basic " + base64.b64encode(raw).decode("ascii")
        # GIT_CONFIG_COUNT injection is host-agnostic via http.extraHeader.
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = header
    return env
