"""Git `credential.helper` trampoline matching Desktop's HTTPS auth flow.

Desktop configures Git with undocumented `GIT_CONFIG_PARAMETERS` so LFS filters
inherit the helper (`'credential.helper=' 'credential.helper=desktop'`). This
module is the same protocol: Git invokes a helper script with `get` / `store` /
`erase` and credential stdin; the running app answers over a Unix socket.

See `app/src/lib/trampoline/trampoline-credential-helper.ts` and
`createCredentialHelperTrampolineHandler`.
"""

from __future__ import annotations

import json
import os
import socket
import stat
import sys
import threading
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO
from urllib.parse import quote, urlparse, urlsplit, urlunsplit

from ..logging import get_logger
from ..models import Account, html_url_from_endpoint, is_dotcom_endpoint, is_ghe_endpoint
from ..paths import cache_dir
from ..remote_parsing import get_api_endpoint, is_github_host, parse_remote
from .ops import (
    approve_credential,
    fill_credential,
    format_credential,
    parse_credential,
    reject_credential,
)

log = get_logger()

SOCK_ENV = "GITHUB_DESKTOP_CREDENTIAL_SOCK"
BACKGROUND_ENV = "GITHUB_DESKTOP_BACKGROUND_TASK"
PATH_ENV = "GITHUB_DESKTOP_TRAMPOLINE_PATH"

CredentialCallback = Callable[..., dict[str, str] | None]

_credential_callback: CredentialCallback | None = None
_server_thread: threading.Thread | None = None
_server_sock: socket.socket | None = None

GITLAB_GITEA_BITBUCKET_REALM = (
    'realm="GitLab"',
    'realm="Gitea"',
    'realm="Atlassian Bitbucket"',
)


def socket_path() -> Path:
    return cache_dir() / "credential-helper.sock"


def helper_path() -> Path:
    return cache_dir() / "git-credential-desktop.sh"


def write_helper_script() -> Path:
    """Create an executable credential helper that re-enters this module."""
    native_root = str(Path(__file__).resolve().parents[2])
    path = helper_path()
    python = sys.executable or "python3"
    script = (
        "#!/bin/sh\n"
        f'export PYTHONPATH="{native_root}${{PYTHONPATH:+:$PYTHONPATH}}"\n'
        f'exec "{python}" -m github_desktop.git.credential_helper "$@"\n'
    )
    if not path.exists() or path.read_text(encoding="utf-8") != script:
        path.write_text(script, encoding="utf-8")
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def credential_helper_env(
    *,
    path: str | None = None,
    background: bool = False,
) -> dict[str, str]:
    """Env so git/LFS invoke the trampoline. Empty when the server is not running."""
    sock = socket_path()
    if not sock.exists() or os.environ.get("PYTEST_CURRENT_TEST"):
        return {}
    helper = write_helper_script()
    existing = os.environ.get("GIT_CONFIG_PARAMETERS") or ""
    prefix = f"{existing} " if existing else ""
    # Desktop `withTrampolineEnv`:
    # GIT_CONFIG_PARAMETERS "'credential.helper=' 'credential.helper=desktop'"
    env = {
        SOCK_ENV: str(sock),
        "GIT_CONFIG_PARAMETERS": f"{prefix}'credential.helper=' 'credential.helper={helper}'",
        "GIT_TERMINAL_PROMPT": "0",
    }
    if path:
        env[PATH_ENV] = path
    if background:
        env[BACKGROUND_ENV] = "1"
    return env


def set_credential_callback(callback: CredentialCallback | None) -> None:
    global _credential_callback
    _credential_callback = callback


def start_credential_helper_server() -> None:
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

    _server_thread = threading.Thread(target=serve, name="credential-helper-server", daemon=True)
    _server_thread.start()
    log.debug("credential helper server listening on %s", path)


def stop_credential_helper_server() -> None:
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


def url_without_credentials(url: str) -> str:
    """Desktop `urlWithoutCredentials`."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def get_credential_url(cred: Mapping[str, str]) -> str:
    """Desktop `getCredentialUrl` as a string."""
    raw = cred.get("url")
    if raw:
        return raw
    protocol = cred.get("protocol") or "https"
    username = cred.get("username")
    user = f"{quote(username, safe='')}@" if username else ""
    host = cred.get("host") or ""
    path = (cred.get("path") or "").lstrip("/")
    return f"{protocol}://{user}{host}/{path}"


def _origin(url: str) -> str:
    parts = urlparse(url if "://" in url else f"https://{url}")
    scheme = (parts.scheme or "https").lower()
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (scheme == "https" and port == 443) and not (scheme == "http" and port == 80):
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def find_github_trampoline_account(
    accounts: Sequence[Account],
    remote_url: str,
) -> Account | None:
    """Desktop `findGitHubTrampolineAccount`: HTML origin of the account endpoint."""
    target = _origin(remote_url)
    host = urlparse(target).hostname
    if not host:
        return None
    for account in accounts:
        html = html_url_from_endpoint(account.endpoint)
        if _origin(html) == target:
            return account
    return None


def find_generic_trampoline_account(endpoint: str, username: str | None = None) -> dict[str, str] | None:
    """Desktop `findGenericTrampolineAccount` against `secrets.get_generic`."""
    from .. import secrets

    host = _generic_host(endpoint)
    login = username
    if not login:
        stored_user, stored_pass = secrets.get_generic(host)
        if stored_user and stored_pass:
            return {"login": stored_user, "endpoint": endpoint, "token": stored_pass}
        return None
    user, password = secrets.get_generic(host, login)
    if not password:
        return None
    return {"login": user or login, "endpoint": endpoint, "token": password}


def _generic_host(endpoint: str) -> str:
    raw = endpoint if "://" in endpoint else f"https://{endpoint}"
    host = urlparse(raw).hostname
    if host:
        return host.lower()
    parsed = parse_remote(url_without_credentials(endpoint) if "://" in endpoint else endpoint)
    if parsed:
        return parsed.hostname.lower()
    return endpoint.lower()


def cred_with_account(cred: Mapping[str, str], login: str, token: str) -> dict[str, str]:
    filled = dict(cred)
    filled["username"] = login
    filled["password"] = token
    return filled


def _wwwauth_kind(cred: Mapping[str, str]) -> str | None:
    for key, value in cred.items():
        if not key.startswith("wwwauth["):
            continue
        if 'realm="GitHub"' in value:
            return "enterprise"
        if any(marker in value for marker in GITLAB_GITEA_BITBUCKET_REALM):
            return "generic"
    return None


def _is_gist_url(endpoint: str) -> bool:
    host = (urlparse(endpoint if "://" in endpoint else f"https://{endpoint}").hostname or "").lower()
    return host in {"gist.github.com", "gist.ghe.io"}


def get_endpoint_kind(
    cred: Mapping[str, str],
    accounts: Sequence[Account],
    *,
    probe: bool = True,
) -> str:
    """Desktop `getEndpointKind`: gist / github.com / ghe.com / wwwauth / probe."""
    endpoint = get_credential_url(cred)
    if _is_gist_url(endpoint):
        return "generic"
    if is_dotcom_endpoint(endpoint) or (urlparse(endpoint).hostname or "").lower() in {
        "github.com",
        "www.github.com",
        "api.github.com",
    }:
        return "github.com"
    if is_ghe_endpoint(endpoint) or (urlparse(endpoint).hostname or "").lower().endswith(".ghe.com"):
        return "ghe.com"
    www = _wwwauth_kind(cred)
    if www:
        return www
    existing = find_github_trampoline_account(accounts, endpoint)
    if existing:
        return "github.com" if existing.is_dotcom else "enterprise"
    protocol = (cred.get("protocol") or urlparse(endpoint).scheme or "").lower()
    if protocol and protocol != "https":
        return "generic"
    if is_github_host(endpoint, list(accounts), probe=probe):
        return "enterprise"
    return "generic"


def _gcm_env(background: bool) -> dict[str, str]:
    env = {"GCM_INTERACTIVE": "0" if background else "1"}
    if os.environ.get("GITHUB_DESKTOP_DISABLE_HARDWARE_ACCELERATION"):
        env["GCM_GUI_SOFTWARE_RENDERING"] = "1"
    return env


def _get_external_credential(
    cred: Mapping[str, str],
    trampoline_path: str,
    background: bool,
) -> dict[str, str] | None:
    try:
        filled = fill_credential(dict(cred), trampoline_path, _gcm_env(background), helper="manager")
    except Exception:
        log.debug("external credential helper fill failed", exc_info=True)
        return None
    if filled.get("username") and filled.get("password"):
        return filled
    return None


def get_credential(
    cred: Mapping[str, str],
    accounts: Sequence[Account],
    *,
    background: bool = False,
    use_external: bool = False,
    prompt_github: Callable[[str], Account | None] | None = None,
    prompt_generic: Callable[[str, str | None], dict[str, str] | None] | None = None,
    trampoline_path: str = ".",
) -> dict[str, str] | None:
    """Desktop `getCredential`."""
    endpoint = get_credential_url(cred)
    gh = find_github_trampoline_account(accounts, endpoint)
    if gh:
        log.info("credential-helper: found GitHub credential for %s", endpoint)
        return cred_with_account(cred, gh.login, gh.token)

    kind = get_endpoint_kind(cred, accounts)
    api_endpoint = get_api_endpoint(endpoint).rstrip("/")
    has_api_account = any(account.endpoint.rstrip("/") == api_endpoint for account in accounts)

    if kind != "generic" and not has_api_account:
        if background or prompt_github is None:
            log.debug("credential-helper: skipping GitHub sign-in prompt")
            return None
        account = prompt_github(endpoint)
        if account is None:
            return None
        return cred_with_account(cred, account.login, account.token)

    if kind != "generic":
        return None

    if use_external:
        return _get_external_credential(cred, trampoline_path, background)

    username = cred.get("username") or None
    try:
        parsed_user = urlparse(endpoint).username
        username = username or (parsed_user or None)
    except Exception:
        pass
    generic = find_generic_trampoline_account(endpoint, username)
    if generic:
        log.info("credential-helper: found generic credential for %s", endpoint)
        return cred_with_account(cred, generic["login"], generic["token"])
    if background or prompt_generic is None:
        log.debug("credential-helper: skipping generic prompt")
        return None
    prompted = prompt_generic(url_without_credentials(endpoint), username)
    if not prompted or not prompted.get("login") or not prompted.get("token"):
        return None
    return cred_with_account(cred, prompted["login"], prompted["token"])


def store_credential(
    cred: Mapping[str, str],
    accounts: Sequence[Account],
    *,
    use_external: bool = False,
    trampoline_path: str = ".",
    background: bool = False,
) -> None:
    """Desktop `storeCredential`: persist generic (or GCM) credentials only."""
    if get_endpoint_kind(cred, accounts) != "generic":
        return
    if use_external:
        try:
            approve_credential(dict(cred), trampoline_path, _gcm_env(background), helper="manager")
        except Exception:
            log.debug("external credential helper store failed", exc_info=True)
        return
    username = cred.get("username")
    password = cred.get("password")
    if not username or not password:
        return
    from .. import secrets

    secrets.set_generic(_generic_host(get_credential_url(cred)), username, password)


def erase_credential(
    cred: Mapping[str, str],
    accounts: Sequence[Account],
    *,
    use_external: bool = False,
    trampoline_path: str = ".",
    background: bool = False,
) -> None:
    """Desktop `eraseCredential`."""
    if get_endpoint_kind(cred, accounts) != "generic":
        return
    if use_external:
        try:
            reject_credential(dict(cred), trampoline_path, _gcm_env(background), helper="manager")
        except Exception:
            log.debug("external credential helper erase failed", exc_info=True)
        return
    username = cred.get("username")
    if not username:
        return
    from .. import secrets

    secrets.delete_generic(_generic_host(get_credential_url(cred)), username)


def create_credential_helper_trampoline_handler(
    accounts: Sequence[Account],
    *,
    use_external: bool = False,
    prompt_github: Callable[[str], Account | None] | None = None,
    prompt_generic: Callable[[str, str | None], dict[str, str] | None] | None = None,
    trampoline_path: str = ".",
    background: bool = False,
) -> Callable[[str, str], str | None]:
    """Desktop `createCredentialHelperTrampolineHandler`."""

    def handler(action: str, stdin: str) -> str | None:
        cred = parse_credential(stdin)
        try:
            if action == "get":
                filled = get_credential(
                    cred,
                    accounts,
                    background=background,
                    use_external=use_external,
                    prompt_github=prompt_github,
                    prompt_generic=prompt_generic,
                    trampoline_path=trampoline_path,
                )
                return format_credential(filled) if filled else None
            if action == "store":
                store_credential(
                    cred,
                    accounts,
                    use_external=use_external,
                    trampoline_path=trampoline_path,
                    background=background,
                )
            elif action == "erase":
                erase_credential(
                    cred,
                    accounts,
                    use_external=use_external,
                    trampoline_path=trampoline_path,
                    background=background,
                )
        except Exception:
            log.exception("credential-helper: %s failed", action)
        return None

    return handler


# Desktop export name (parity inventory).
createCredentialHelperTrampolineHandler = create_credential_helper_trampoline_handler


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
        action = str(payload.get("action") or "")
        stdin = str(payload.get("stdin") or "")
        background = bool(payload.get("background"))
        trampoline_path = str(payload.get("path") or ".")
        stdout = ""
        if _credential_callback is not None:
            try:
                cred = parse_credential(stdin)
                filled = _credential_callback(
                    action,
                    cred,
                    background=background,
                    trampoline_path=trampoline_path,
                )
                if filled:
                    stdout = format_credential(filled)
            except Exception:
                log.exception("credential helper callback failed")
                stdout = ""
        conn.sendall((json.dumps({"stdout": stdout}) + "\n").encode("utf-8"))
    except OSError:
        pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def _query_server(
    action: str,
    stdin: str,
    sock_path: str,
    background: bool,
    trampoline_path: str,
    timeout: float = 600.0,
) -> str:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock_path)
        client.sendall(
            (
                json.dumps(
                    {
                        "action": action,
                        "stdin": stdin,
                        "background": background,
                        "path": trampoline_path,
                    }
                )
                + "\n"
            ).encode("utf-8")
        )
        data = b""
        while b"\n" not in data:
            chunk = client.recv(4096)
            if not chunk:
                break
            data += chunk
        payload = json.loads(data.decode("utf-8").split("\n", 1)[0] or "{}")
        return str(payload.get("stdout") or "")
    finally:
        try:
            client.close()
        except OSError:
            pass


def main(argv: list[str] | None = None, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    action = args[0] if args else ""
    body = (stdin or sys.stdin).read()
    sock = os.environ.get(SOCK_ENV)
    answer = ""
    if sock:
        try:
            answer = _query_server(
                action,
                body,
                sock,
                os.environ.get(BACKGROUND_ENV) == "1",
                os.environ.get(PATH_ENV) or os.getcwd(),
            )
        except OSError as exc:
            log.debug("credential helper socket failed: %s", exc)
    out = stdout or sys.stdout
    if answer:
        out.write(answer)
        if not answer.endswith("\n"):
            out.write("\n")
        out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
