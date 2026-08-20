"""Avatar URL candidates and initials (no GTK). Matches Desktop's GitHub.com email avatars."""

from __future__ import annotations

import hashlib
import re
import urllib.parse

GITHUB_EMAIL_AVATAR = "https://avatars.githubusercontent.com/u/e"
GITHUB_LOGIN_AVATAR = "https://avatars.githubusercontent.com"
NOREPLY_RE = re.compile(r"^(?:(?P<id>\d+)\+)?(?P<login>[^@]+)@users\.noreply\.github\.com$", re.I)


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


def avatar_urls(
    *,
    email: str = "",
    login: str | None = None,
    avatar_url: str | None = None,
    size: int = 48,
) -> list[str]:
    """Ordered candidates, same idea as Desktop getAvatarUrlCandidates for github.com."""
    size = max(16, min(int(size), 256))
    urls: list[str] = []
    if avatar_url:
        parsed = urllib.parse.urlparse(avatar_url)
        if parsed.scheme in ("http", "https"):
            query = urllib.parse.parse_qs(parsed.query)
            query["s"] = [str(size)]
            rebuilt = parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
            urls.append(urllib.parse.urlunparse(rebuilt))
    resolved_login = login or login_from_email(email)
    if resolved_login:
        urls.append(f"{GITHUB_LOGIN_AVATAR}/{urllib.parse.quote(resolved_login)}?s={size}")
    if email:
        qs = urllib.parse.urlencode({"email": email, "s": str(size)})
        urls.append(f"{GITHUB_EMAIL_AVATAR}?{qs}")
        digest = hashlib.md5(email.strip().lower().encode("utf-8")).hexdigest()
        urls.append(f"https://www.gravatar.com/avatar/{digest}?s={size}&d=404")
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    return out
