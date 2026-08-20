"""GIT_ASKPASS / SSH_ASKPASS trampoline matching Desktop's askpass handler.

Git and OpenSSH invoke this helper as a separate process. The running app
listens on a Unix socket, shows the corresponding GTK dialog on the main
thread, and returns the answer. github.com's published RSA host key is
accepted automatically, the same way Desktop does.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TextIO

from ..logging import get_logger
from ..paths import cache_dir

log = get_logger()

# https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints
GITHUB_RSA_FINGERPRINT = "SHA256:nThbg6kXUpJWGl7E1IGOCspRomTxdCARLviKw6E5SY8"

SOCK_ENV = "GITHUB_DESKTOP_ASKPASS_SOCK"
SSH_SERVICE = "GitHub Desktop SSH"

_HOST_RE = (
    r"^The authenticity of host '([^ ]+) \(([^\)]+)\)' can't be established[^.]*\.\n"
    r"([^ ]+) key fingerprint is ([^.]+)\."
)
_KEY_RE = r"^Enter passphrase for key '(.+)':\s*$"
_USER_RE = r"^(.+@.+)'s password:\s*$"

_prompt_callback: Callable[[str], str] | None = None
_server_thread: threading.Thread | None = None
_server_sock: socket.socket | None = None


@dataclass
class AskpassRequest:
    kind: str  # host, key, password, unknown
    prompt: str
    host: str = ""
    ip: str = ""
    key_type: str = ""
    fingerprint: str = ""
    key_path: str = ""
    username: str = ""


def parse_askpass_prompt(prompt: str) -> AskpassRequest:
    import re

    host = re.search(_HOST_RE, prompt, re.M)
    if host:
        return AskpassRequest(
            kind="host",
            prompt=prompt,
            host=host.group(1),
            ip=host.group(2),
            key_type=host.group(3),
            fingerprint=host.group(4),
        )
    key = re.search(_KEY_RE, prompt)
    if key:
        return AskpassRequest(kind="key", prompt=prompt, key_path=key.group(1))
    user = re.search(_USER_RE, prompt)
    if user:
        return AskpassRequest(kind="password", prompt=prompt, username=user.group(1))
    return AskpassRequest(kind="unknown", prompt=prompt)


def auto_answer(parsed: AskpassRequest) -> str | None:
    if (
        parsed.kind == "host"
        and parsed.host == "github.com"
        and parsed.key_type.upper() == "RSA"
        and parsed.fingerprint == GITHUB_RSA_FINGERPRINT
    ):
        return "yes"
    if parsed.kind == "key" and parsed.key_path:
        try:
            from .. import secrets

            stored = secrets.get_password(SSH_SERVICE, parsed.key_path)
            if stored:
                return stored
        except Exception:
            pass
    if parsed.kind == "password" and parsed.username:
        try:
            from .. import secrets

            stored = secrets.get_password(SSH_SERVICE, parsed.username)
            if stored:
                return stored
        except Exception:
            pass
    return None


def socket_path() -> Path:
    return cache_dir() / "askpass.sock"


def helper_path() -> Path:
    return cache_dir() / "askpass.sh"


def write_helper_script() -> Path:
    """Create an executable GIT_ASKPASS wrapper that re-enters this module."""
    native_root = str(Path(__file__).resolve().parents[2])
    path = helper_path()
    python = sys.executable or "python3"
    script = (
        "#!/bin/sh\n"
        f'export PYTHONPATH="{native_root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        f'exec "{python}" -m github_desktop.git.askpass "$@"\n'
    )
    if not path.exists() or path.read_text(encoding="utf-8") != script:
        path.write_text(script, encoding="utf-8")
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def askpass_env() -> dict[str, str]:
    """Env vars so git/ssh invoke the trampoline. Empty when the server is not running."""
    sock = socket_path()
    if not sock.exists() or os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    helper = write_helper_script()
    display = os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") or "."
    return {
        "GIT_ASKPASS": str(helper),
        "SSH_ASKPASS": str(helper),
        "SSH_ASKPASS_REQUIRE": "force",
        "DISPLAY": display,
        SOCK_ENV: str(sock),
        "GIT_TERMINAL_PROMPT": "0",
    }


def set_prompt_callback(callback: Callable[[str], str] | None) -> None:
    global _prompt_callback
    _prompt_callback = callback


def start_askpass_server() -> None:
    """Listen for helper connections. Safe to call more than once."""
    global _server_thread, _server_sock
    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("GITHUB_DESKTOP_OFFLINE") == "1":
        return
    if _server_thread is not None and _server_thread.is_alive():
        return
    path = socket_path()
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    os.chmod(path, 0o600)
    sock.listen(8)
    sock.settimeout(1.0)
    _server_sock = sock

    def serve() -> None:
        while _server_sock is sock:
            try:
                conn, _addr = sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            threading.Thread(target=_handle_conn, args=(conn,), daemon=True).start()

    _server_thread = threading.Thread(target=serve, name="askpass-server", daemon=True)
    _server_thread.start()
    log.debug("askpass server listening on %s", path)


def stop_askpass_server() -> None:
    global _server_sock
    sock = _server_sock
    _server_sock = None
    if sock is not None:
        try:
            sock.close()
        except OSError:
            pass
    try:
        socket_path().unlink()
    except OSError:
        pass


def _handle_conn(conn: socket.socket) -> None:
    try:
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
        try:
            payload = json.loads(data.decode("utf-8").split("\n", 1)[0] or "{}")
        except json.JSONDecodeError:
            payload = {}
        prompt = str(payload.get("prompt") or "")
        answer = ""
        parsed = parse_askpass_prompt(prompt)
        auto = auto_answer(parsed)
        if auto is not None:
            answer = auto
        elif _prompt_callback is not None:
            try:
                answer = _prompt_callback(prompt) or ""
            except Exception:
                log.exception("askpass prompt callback failed")
                answer = ""
        conn.sendall((json.dumps({"response": answer}) + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _query_server(prompt: str, sock_path: str, timeout: float = 300.0) -> str:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock_path)
        client.sendall((json.dumps({"prompt": prompt}) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        payload = json.loads(data.decode("utf-8").split("\n", 1)[0] or "{}")
        return str(payload.get("response") or "")
    finally:
        try:
            client.close()
        except OSError:
            pass


def answer_prompt(prompt: str, sock_path: str | None = None) -> str:
    parsed = parse_askpass_prompt(prompt)
    auto = auto_answer(parsed)
    if auto is not None:
        return auto
    path = sock_path or os.environ.get(SOCK_ENV)
    if path:
        try:
            return _query_server(prompt, path)
        except OSError as exc:
            log.debug("askpass socket failed: %s", exc)
    return ""


def main(argv: list[str] | None = None, stdout: TextIO | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    prompt = args[0] if args else sys.stdin.read()
    answer = answer_prompt(prompt)
    out = stdout or sys.stdout
    out.write(answer)
    if not answer.endswith("\n"):
        out.write("\n")
    out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
