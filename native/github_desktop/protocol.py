"""Protocol URL parsing for x-github-client / OAuth / Open in Desktop."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from .models import test_for_invalid_chars


@dataclass
class OAuthAction:
    name: str = "oauth"
    code: str = ""
    state: str = ""


@dataclass
class OpenRepositoryAction:
    name: str = "open-repository-from-url"
    url: str = ""
    branch: str | None = None
    pr: str | None = None
    filepath: str | None = None


@dataclass
class UnknownAction:
    name: str = "unknown"
    url: str = ""


URLAction = OAuthAction | OpenRepositoryAction | UnknownAction


def parse_app_url(url: str) -> URLAction:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    unknown = UnknownAction(url=url)
    if not hostname:
        return unknown
    query = {k: v[0] if v else "" for k, v in parse_qs(parsed.query).items()}
    if hostname == "oauth":
        code = query.get("code")
        state = query.get("state")
        if code and state:
            return OAuthAction(code=code, state=state)
        return unknown
    path = parsed.path or ""
    if len(path) <= 1:
        return unknown
    parsed_path = unquote(path[1:])
    if hostname == "openrepo":
        pr = query.get("pr")
        branch = query.get("branch")
        filepath = query.get("filepath")
        if pr is not None and not pr.isdigit():
            return unknown
        if pr is not None and branch is not None and not (
            branch.startswith("pr/") and branch[3:].isdigit()
        ):
            return unknown
        if branch is not None and test_for_invalid_chars(branch):
            return unknown
        return OpenRepositoryAction(url=parsed_path, branch=branch, pr=pr, filepath=filepath)
    return unknown


def is_protocol_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {
        "x-github-client",
        "x-github-desktop-auth",
        "x-github-desktop-dev-auth",
        "github-mac",
    }
