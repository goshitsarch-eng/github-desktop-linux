"""Git process runner with authentication, progress, and error mapping."""

from __future__ import annotations

import os
import signal
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from ..errors import GitError, GitNotFoundError
from ..logging import get_logger
from .progress import GitLFSProgressParser, GitProgress, GitProgressParser, ProgressStep, create_lfs_progress_file

log = get_logger()

ProgressCallback = Callable[[GitProgress], None]


class _LFSProgressWatch:
    """Tail `GIT_LFS_PROGRESS` the way Desktop's `from-process.ts` does."""

    def __init__(self, path: str, callback: ProgressCallback) -> None:
        self.path = path
        self.callback = callback
        self.parser = GitLFSProgressParser()
        self.active = False
        self._stop = threading.Event()
        self._pos = 0
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.5)
        directory = os.path.dirname(self.path)
        try:
            os.unlink(self.path)
        except OSError:
            pass
        try:
            os.rmdir(directory)
        except OSError:
            pass

    def _run(self) -> None:
        while not self._stop.wait(0.08):
            self._drain()
        self._drain()

    def _drain(self) -> None:
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._pos)
                chunk = fh.read()
                self._pos = fh.tell()
        except OSError:
            return
        if not chunk:
            return
        for line in chunk.decode("utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            event = self.parser.parse(line)
            if event.kind == "progress":
                self.active = True
                self.callback(event)


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


def _prepare_env(env: Mapping[str, str] | None) -> dict[str, str]:
    merged_env = os.environ.copy()
    merged_env.setdefault("GIT_TERMINAL_PROMPT", "0")
    merged_env.setdefault("GCM_INTERACTIVE", "Never")
    merged_env.setdefault("GIT_OPTIONAL_LOCKS", "0")
    merged_env.setdefault("LC_ALL", "C")
    merged_env.setdefault("LANGUAGE", "C")
    if env:
        merged_env.update({k: v for k, v in env.items() if v is not None})
    return merged_env


def _stdin_bytes(stdin: str | bytes | None) -> bytes | None:
    if stdin is None:
        return None
    if isinstance(stdin, bytes):
        return stdin
    return stdin.encode("utf-8")


def _read_stream(
    stream,
    chunks: list[bytes],
    on_line: Callable[[str], None] | None,
) -> None:
    buf = b""
    while True:
        data = stream.read(4096)
        if not data:
            break
        chunks.append(data)
        if on_line is None:
            continue
        buf += data
        while True:
            cr = buf.find(b"\r")
            nl = buf.find(b"\n")
            if cr < 0 and nl < 0:
                break
            idx = min(i for i in (cr, nl) if i >= 0)
            line = buf[:idx]
            buf = buf[idx + 1 :]
            if line:
                on_line(_decode(line))
    if on_line and buf.strip():
        on_line(_decode(buf))


def abort_git_process(proc: subprocess.Popen | None) -> None:
    """Terminate a git subprocess and its process group (clone cancel)."""
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.terminate()
        except Exception:
            return
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=1)
        except Exception:
            pass


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
    progress: ProgressCallback | None = None,
    progress_parser: GitProgressParser | None = None,
    on_stdout_line: Callable[[str], None] | None = None,
    on_stderr_line: Callable[[str], None] | None = None,
    process_holder: list | None = None,
    cancel_event: threading.Event | None = None,
) -> GitResult:
    """Run a git command. Raises GitError unless the exit code is allowed."""
    git_bin = find_git()
    cmd = [git_bin, *args]
    success = success_exit_codes or {0}
    merged_env = _prepare_env(env)
    stdin_bytes = _stdin_bytes(stdin)
    stream = progress is not None or on_stdout_line is not None or on_stderr_line is not None
    use_popen = stream or process_holder is not None or cancel_event is not None
    lfs_watch: _LFSProgressWatch | None = None
    if progress is not None:
        try:
            lfs_path = create_lfs_progress_file()
            merged_env["GIT_LFS_PROGRESS"] = lfs_path
            lfs_watch = _LFSProgressWatch(lfs_path, progress)
            lfs_watch.start()
        except OSError:
            log.debug("unable to create GIT_LFS_PROGRESS file", exc_info=True)
            merged_env.pop("GIT_LFS_PROGRESS", None)
            lfs_watch = None

    log.debug("git %s: %s (cwd=%s)", name, " ".join(cmd[1:]), cwd)
    if cancel_event is not None and cancel_event.is_set():
        if lfs_watch is not None:
            lfs_watch.stop()
        raise GitError("Git command aborted", args=list(args), exit_code=-1, stderr="aborted")
    try:
        if not use_popen:
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
            stdout_bytes = completed.stdout
            stderr_bytes = completed.stderr
            exit_code = completed.returncode
        else:
            parser = progress_parser
            if progress is not None and parser is None:
                parser = GitProgressParser((ProgressStep("Receiving objects", 1.0),))

            def handle_stderr(line: str) -> None:
                if progress is not None and parser is not None:
                    event = parser.parse(line)
                    if lfs_watch is not None and lfs_watch.active:
                        if event.kind == "context":
                            if on_stderr_line is not None:
                                on_stderr_line(line)
                            return
                        title = event.details.title if event.details else ""
                        if title == "Filtering content":
                            if event.details and event.details.done:
                                lfs_watch.active = False
                            if on_stderr_line is not None:
                                on_stderr_line(line)
                            return
                    progress(event)
                if on_stderr_line is not None:
                    on_stderr_line(line)

            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=merged_env,
                stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
            if process_holder is not None:
                process_holder.append(proc)
            if cancel_event is not None and cancel_event.is_set():
                abort_git_process(proc)
            stdout_chunks: list[bytes] = []
            stderr_chunks: list[bytes] = []
            stdout_thread = threading.Thread(
                target=_read_stream, args=(proc.stdout, stdout_chunks, on_stdout_line), daemon=True
            )
            stderr_thread = threading.Thread(
                target=_read_stream, args=(proc.stderr, stderr_chunks, handle_stderr), daemon=True
            )
            stdout_thread.start()
            stderr_thread.start()
            if stdin_bytes is not None and proc.stdin is not None:
                proc.stdin.write(stdin_bytes)
                proc.stdin.close()
            try:
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                abort_git_process(proc)
                stdout_thread.join(timeout=1)
                stderr_thread.join(timeout=1)
                raise GitError(
                    f"Git command timed out: {name}",
                    args=list(args),
                    stdout=_decode(b"".join(stdout_chunks)),
                    stderr=_decode(b"".join(stderr_chunks)),
                ) from exc
            stdout_thread.join()
            stderr_thread.join()
            stdout_bytes = b"".join(stdout_chunks)
            stderr_bytes = b"".join(stderr_chunks)
            if cancel_event is not None and cancel_event.is_set():
                raise GitError(
                    "Git command aborted",
                    args=list(args),
                    exit_code=exit_code,
                    stdout=_decode(stdout_bytes),
                    stderr=_decode(stderr_bytes) or "aborted",
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
    finally:
        if lfs_watch is not None:
            lfs_watch.stop()

    result = GitResult(
        stdout=_decode(stdout_bytes) if not binary else "",
        stderr=_decode(stderr_bytes),
        exit_code=exit_code,
        args=list(args),
        stdout_bytes=stdout_bytes,
    )
    if result.exit_code not in success:
        message = result.stderr.strip() or result.stdout.strip() or f"git {name} failed"
        from ..errors import classify_git_error, get_description_for_error

        git_error = classify_git_error(result.stderr, result.stdout)
        friendly = get_description_for_error(git_error, result.stderr)
        if friendly:
            message = friendly
        raise GitError(
            message,
            args=list(args),
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            git_error=git_error,
            path=str(cwd),
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


def env_for_proxy(remote_url: str, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Desktop `envForProxy` without Electron PAC resolution.

    Only HTTP(S) remotes are eligible. Skipped when ``ALL_PROXY``/``all_proxy``
    or the protocol-specific ``http_proxy``/``https_proxy`` is already set.
    Otherwise ``git config --global http.proxy`` is used when present.
    """
    import re as _re

    source = env if env is not None else os.environ
    match = _re.match(r"^(https?)://", remote_url or "", flags=_re.I)
    if match is None:
        return {}
    if "ALL_PROXY" in source or "all_proxy" in source:
        return {}
    proto = match.group(1).lower()
    env_key = f"{proto}_proxy"
    if env_key in source or (proto == "https" and "HTTPS_PROXY" in source):
        return {}
    proxy = ""
    try:
        result = git(
            ["config", "--global", "--get", "http.proxy"],
            os.path.expanduser("~"),
            success_exit_codes={0, 1},
            name="httpProxy",
        )
        proxy = (result.stdout or "").strip()
    except Exception:
        proxy = ""
    if not proxy:
        return {}
    return {env_key: proxy}


def env_for_remote(
    remote_url: str,
    *,
    token: str | None = None,
    username: str | None = None,
    password: str | None = None,
    extra: Mapping[str, str] | None = None,
    use_external_credential_helper: bool = False,
) -> dict[str, str]:
    """Build env vars that inject HTTPS credentials without prompting.

    Desktop Advanced `useExternalCredentialHelper`: when True, do not force
    GCM_INTERACTIVE=Never so the system Git credential helper can prompt.
    GitHub account tokens are still injected as `http.extraHeader`.
    The credential helper trampoline is attached via `GIT_CONFIG_PARAMETERS`
    in `extra` (Desktop `withTrampolineEnv`) so LFS filters inherit it.
    """
    env: dict[str, str] = {
        "GIT_TERMINAL_PROMPT": "0",
        "GCM_INTERACTIVE": "Auto" if use_external_credential_helper else "Never",
    }
    env.update(env_for_proxy(remote_url))
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
