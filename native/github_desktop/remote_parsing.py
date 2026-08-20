"""Parse GitHub remotes and match them to accounts / known hosts."""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from .models import Account, GitHubRepository, Remote, html_url_from_endpoint, is_dotcom_endpoint, is_ghe_endpoint

GITHUB_GIST = re.compile(r"gist\.github\.com", re.I)
SSH_RE = re.compile(r"^(?:ssh://)?git@([^:]+):(.+?)(?:\.git)?$")
HTTPS_RE = re.compile(r"^https?://([^/]+)/(.+?)(?:\.git)?$")
GIT_RE = re.compile(r"^git://([^/]+)/(.+?)(?:\.git)?$")


@dataclass
class ParsedRemote:
    hostname: str
    owner: str
    name: str
    protocol: str


def parse_remote(url: str) -> ParsedRemote | None:
    url = sanitize_remote_url(url.strip()) if url else url
    if not url:
        return None
    for pattern, proto in ((HTTPS_RE, "https"), (GIT_RE, "git"), (SSH_RE, "ssh")):
        match = pattern.match(url)
        if not match:
            continue
        host, path = match.group(1), match.group(2)
        path = path.strip("/")
        if "/" not in path:
            return None
        owner, name = path.split("/", 1)
        name = name.split("/")[0]
        return ParsedRemote(host, owner, name, proto)
    return None


def hostname_from_endpoint(endpoint: str) -> str:
    html = html_url_from_endpoint(endpoint)
    return html.replace("https://", "").replace("http://", "").split("/")[0]


_KNOWN_THIRD_PARTY_HOSTS = (
    "amazonaws.com",
    "visualstudio.com",
    "azure.com",
    "dev.azure.com",
    "bitbucket.org",
    "gitlab.com",
    "sourceforge.net",
    "codeberg.org",
)


_endpoint_versions: dict[str, str] = {}


def get_api_endpoint(url: str) -> str:
    """Desktop `getAPIEndpoint` / `getEnterpriseAPIURL`."""
    raw = url if "://" in url else f"https://{url}"
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if is_dotcom_endpoint(raw) or host in ("github.com", "www.github.com", "api.github.com"):
        return os.environ.get("DESKTOP_GITHUB_DOTCOM_API_ENDPOINT") or "https://api.github.com"
    netloc = host
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    if is_ghe_endpoint(raw) or host.endswith(".ghe.com"):
        return f"https://api.{netloc}"
    return f"https://{netloc}/api/v3"


def update_endpoint_version(endpoint: str, version: str) -> None:
    """Desktop `updateEndpointVersion` from `x-github-enterprise-version`."""
    if version:
        _endpoint_versions[endpoint.rstrip("/")] = version


def get_endpoint_version(endpoint: str) -> str | None:
    """Desktop `getEndpointVersion`."""
    return _endpoint_versions.get(endpoint.rstrip("/"))


def _should_probe_github_host() -> bool:
    if os.environ.get("GITHUB_DESKTOP_OFFLINE") == "1":
        return False
    if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get("GITHUB_DESKTOP_ALLOW_META_PROBE") != "1":
        return False
    return True


def probe_github_host(url: str, timeout: float = 2.0) -> bool | None:
    """Desktop `isGitHubHost` `/meta` HEAD: `x-github-request-id` means GitHub.

    Returns True/False, or None when the discovery request fails.
    """
    import urllib.error
    import urllib.request

    endpoint = get_api_endpoint(url).rstrip("/")
    meta_url = f"{endpoint}/meta?ghd={uuid.uuid4()}"
    try:
        from .github.api import USER_AGENT
    except Exception:
        USER_AGENT = "GitHub Desktop"

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            return None

    req = urllib.request.Request(meta_url, method="HEAD", headers={"User-Agent": USER_AGENT})
    opener = urllib.request.build_opener(_NoRedirect)
    headers = None
    try:
        with opener.open(req, timeout=timeout) as resp:
            headers = resp.headers
    except urllib.error.HTTPError as exc:
        headers = exc.headers
    except Exception:
        return None
    if headers is None:
        return None
    version = headers.get("x-github-enterprise-version")
    if version:
        update_endpoint_version(endpoint, version)
    keys = {str(key).lower() for key in headers.keys()}
    return "x-github-request-id" in keys


def _hostname_for_github_check(url: str) -> str:
    parsed = parse_remote(url)
    host = (parsed.hostname if parsed else "").lower()
    if host:
        return host
    raw = url if "://" in url else f"https://{url}"
    return (urlparse(raw).hostname or "").lower()


def is_github_host(url: str, accounts: list[Account] | None = None, *, probe: bool = False) -> bool:
    """Desktop `isGitHubHost`: hostname + accounts, optional `/meta` probe."""
    host = _hostname_for_github_check(url)
    if host in ("github.com", "www.github.com", "gist.github.com", "api.github.com"):
        return True
    if host.endswith(".ghe.com") or host.endswith(".github.com"):
        return True
    if re.search(r"(^|\.)github\.", host):
        return True
    if re.search(r"(^|\.)(bitbucket|gitlab)\.", host):
        return False
    if any(host == known or host.endswith("." + known) for known in _KNOWN_THIRD_PARTY_HOSTS):
        return False
    if accounts and account_for_remote(accounts, url):
        return True
    endpoint = get_api_endpoint(url)
    if get_endpoint_version(endpoint) is not None:
        return True
    if not probe or not _should_probe_github_host():
        return False
    result = probe_github_host(url)
    return bool(result)


def account_for_remote(accounts: list[Account], url: str) -> Account | None:
    parsed = parse_remote(url)
    if not parsed:
        return None
    for account in accounts:
        host = hostname_from_endpoint(account.endpoint)
        if parsed.hostname == host or parsed.hostname.endswith("." + host):
            return account
        if parsed.hostname in ("github.com", "www.github.com") and account.is_dotcom:
            return account
    return None


def sanitize_remote_url(url: str) -> str:
    """Drop embedded userinfo so tokens are not written into git remotes."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if not (parts.username or parts.password):
        return url
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))


def url_matches_remote(url: str | None, remote: Remote) -> bool:
    """Desktop `urlMatchesRemote`: same host/owner/name, ignoring protocol and `.git`."""
    if not url:
        return False
    clone = parse_remote(url)
    other = parse_remote(remote.url)
    if clone is None or other is None:
        return False
    return (
        clone.hostname.lower() == other.hostname.lower()
        and clone.owner.lower() == other.owner.lower()
        and clone.name.lower() == other.name.lower()
    )


def github_from_remote(url: str, endpoint: str) -> GitHubRepository | None:
    parsed = parse_remote(url)
    if not parsed:
        return None
    html = html_url_from_endpoint(endpoint)
    return GitHubRepository(
        name=parsed.name,
        owner=parsed.owner,
        html_url=f"{html}/{parsed.owner}/{parsed.name}",
        clone_url=url if parsed.protocol == "https" else f"{html}/{parsed.owner}/{parsed.name}.git",
        ssh_url=url if parsed.protocol == "ssh" else f"git@{parsed.hostname}:{parsed.owner}/{parsed.name}.git",
        endpoint=endpoint,
    )
