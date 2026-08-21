"""Avatar URL candidates and initials (no GTK). Matches Desktop `getAvatarUrlCandidates`."""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse

from .endpoint_capabilities import supports_avatars_api
from .models import Account, html_url_from_endpoint, is_dotcom_endpoint, is_ghe_endpoint, is_ghes_endpoint
from .offset_from import offset_from_now

GITHUB_EMAIL_AVATAR = "https://avatars.githubusercontent.com/u/e"
GITHUB_LOGIN_AVATAR = "https://avatars.githubusercontent.com"
NOREPLY_RE = re.compile(r"^(?:(?P<id>\d+)\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$", re.I)

_AVATAR_TOKENS: dict[str, tuple[str, float]] = {}


def initials_for(name: str, email: str = "") -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    local = (email or "").split("@", 1)[0]
    return (local[:2] or "?").upper()


def login_from_email(email: str) -> str | None:
    if not email:
        return None
    match = NOREPLY_RE.match(email.strip())
    if not match:
        return None
    login = match.group("login")
    if login.isdigit():
        return None
    return login


def get_email_avatar_url(endpoint: str | None) -> str:
    """Desktop `getEmailAvatarUrl` for github.com, GHES, and ghe.com."""
    if not endpoint or is_dotcom_endpoint(endpoint):
        return GITHUB_EMAIL_AVATAR
    if is_ghe_endpoint(endpoint):
        return html_url_from_endpoint(endpoint).rstrip("/") + "/avatars/u/e"
    return endpoint.rstrip("/") + "/enterprise/avatars/u/e"


def ensure_avatar_token(account: Account | None) -> str | None:
    """Desktop `getAvatarToken` cache (GHE / ghe.com only). Safe to call off-thread."""
    if account is None or not is_ghe_endpoint(account.endpoint):
        return None
    cached = _AVATAR_TOKENS.get(account.endpoint)
    now_ms = time.time() * 1000.0
    if cached:
        token, expires_at = cached
        if now_ms < expires_at:
            return token
    try:
        from .github.api import GitHubAPI

        token = GitHubAPI.from_account(account).get_avatar_token()
    except Exception:
        return None
    if token:
        # Desktop `ExpiringOperationCache` TTL: `offsetFrom(0, 50, 'minutes')`.
        _AVATAR_TOKENS[account.endpoint] = (token, float(offset_from_now(50, "minutes")))
    return token


def avatar_urls(
    *,
    email: str = "",
    login: str | None = None,
    avatar_url: str | None = None,
    size: int = 48,
    endpoint: str | None = None,
    avatar_token: str | None = None,
) -> list[str]:
    """Ordered candidates, same idea as Desktop `getAvatarUrlCandidates`."""
    size = max(16, min(int(size), 256))
    urls: list[str] = []
    ep = endpoint or "https://api.github.com"
    if not is_ghes_endpoint(ep) and avatar_url:
        parsed = urllib.parse.urlparse(avatar_url)
        if parsed.scheme in ("http", "https"):
            query = urllib.parse.parse_qs(parsed.query)
            query["s"] = [str(size)]
            rebuilt = parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
            urls.append(urllib.parse.urlunparse(rebuilt))
    if is_ghe_endpoint(ep) and not avatar_token:
        seen: set[str] = set()
        out: list[str] = []
        for url in urls:
            if url not in seen:
                seen.add(url)
                out.append(url)
        return out
    if is_dotcom_endpoint(ep):
        resolved_login = login or login_from_email(email)
        if resolved_login:
            urls.append(f"{GITHUB_LOGIN_AVATAR}/{urllib.parse.quote(resolved_login)}?s={size}")
    if email:
        if is_ghes_endpoint(ep) and not supports_avatars_api(ep):
            params = None
        else:
            params = {"email": email, "s": str(size)}
            if is_ghe_endpoint(ep) and avatar_token:
                params["token"] = avatar_token
            qs = urllib.parse.urlencode(params)
            urls.append(f"{get_email_avatar_url(ep)}?{qs}")
        if is_dotcom_endpoint(ep):
            digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
            urls.append(f"https://www.gravatar.com/avatar/{digest}?s={size}&d=404")
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
