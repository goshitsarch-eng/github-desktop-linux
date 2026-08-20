"""Parse GitHub remotes and match them to accounts / known hosts."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import Account, GitHubRepository, Remote, html_url_from_endpoint

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
    url = url.strip()
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
