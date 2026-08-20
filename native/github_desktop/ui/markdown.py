"""Sandboxed GFM-lite → Pango markup (Desktop `SandboxedMarkdown` stand-in).

Desktop renders PR bodies in a sandboxed iframe. Native GTK has no WebKit
requirement, so we convert a safe subset of GitHub Flavored Markdown to Pango
markup: emphasis, inline/fenced code, https-only links, emoji shortcodes,
``#123`` issue refs, ``MentionFilter`` (@user), and ``CommitMentionFilter``
(7–40 hex SHAs). Raw HTML, ``javascript:``, and ``data:`` URLs are dropped.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from .emoji import expand_shortcodes

_SAFE_SCHEMES = {"http", "https"}
_PLACEHOLDER = "\x00PH{0}\x00"
_FENCE_RE = re.compile(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)```")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_AUTOLINK_RE = re.compile(r"(?<!href=\")(?<!href=')https?://[^\s<]+")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
_ISSUE_RE = re.compile(r"(?<![/\w])#(\d+)\b")
_QUOTE_RE = re.compile(r"^&gt;\s?(.*)$", re.M)
_MENTION_RE = re.compile(
    r"(^|[^A-Za-z0-9_`])@([A-Za-z0-9][A-Za-z0-9-]{0,38})(?![/\w-])"
)
_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")


def _safe_url(url: str) -> str | None:
    raw = (url or "").strip()
    if not raw or raw.startswith("<"):
        return None
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    return raw


def issue_base_from_html_url(html_url: str | None) -> str | None:
    """``https://github.com/owner/repo/pull/12`` → ``https://github.com/owner/repo/issues``."""
    if not html_url:
        return None
    base = html_url.rstrip("/")
    for suffix in ("/pull/", "/issues/"):
        if suffix in base:
            base = base.split(suffix, 1)[0]
            break
    if not base.startswith("http"):
        return None
    return base + "/issues"


def markdown_to_pango(
    text: str,
    *,
    issue_base_url: str | None = None,
    repo_html_url: str | None = None,
) -> str:
    """Convert a GFM subset to Pango markup. Never emits unsafe URIs."""
    source = expand_shortcodes(text or "")
    held: list[str] = []

    def hold(markup: str) -> str:
        held.append(markup)
        return _PLACEHOLDER.format(len(held) - 1)

    def stash_fence(match: re.Match[str]) -> str:
        body = html.escape(match.group(1).strip("\n"), quote=True)
        return hold(f"<tt>{body}</tt>")

    source = _FENCE_RE.sub(stash_fence, source)

    def stash_code(match: re.Match[str]) -> str:
        return hold(f"<tt>{html.escape(match.group(1), quote=True)}</tt>")

    source = _INLINE_CODE_RE.sub(stash_code, source)

    def stash_link(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        safe = _safe_url(url)
        if safe is None:
            return match.group(0)
        href = html.escape(safe, quote=True)
        return hold(f'<a href="{href}">{html.escape(label, quote=True)}</a>')

    source = _MD_LINK_RE.sub(stash_link, source)
    escaped = html.escape(source, quote=True)

    def bold(match: re.Match[str]) -> str:
        inner = match.group(1) or match.group(2) or ""
        return f"<b>{inner}</b>"

    escaped = _BOLD_RE.sub(bold, escaped)

    def italic(match: re.Match[str]) -> str:
        inner = match.group(1) or match.group(2) or ""
        return f"<i>{inner}</i>"

    escaped = _ITALIC_RE.sub(italic, escaped)
    escaped = _HEADING_RE.sub(lambda m: f"<b>{m.group(2)}</b>", escaped)
    escaped = _QUOTE_RE.sub(lambda m: f"<i>{m.group(1)}</i>", escaped)

    if issue_base_url:
        base = issue_base_url.rstrip("/")

        def stash_issue(match: re.Match[str]) -> str:
            num = match.group(1)
            href = html.escape(f"{base}/{num}", quote=True)
            return hold(f'<a href="{href}">#{num}</a>')

        escaped = _ISSUE_RE.sub(stash_issue, escaped)

    host = None
    if issue_base_url:
        parsed = urlparse(issue_base_url)
        if parsed.scheme and parsed.netloc:
            host = f"{parsed.scheme}://{parsed.netloc}"
    elif repo_html_url:
        parsed = urlparse(repo_html_url)
        if parsed.scheme and parsed.netloc:
            host = f"{parsed.scheme}://{parsed.netloc}"
    if host:

        def stash_mention(match: re.Match[str]) -> str:
            prefix, user = match.group(1), match.group(2)
            href = html.escape(f"{host}/{user}", quote=True)
            return hold(f'{prefix}<a href="{href}">@{html.escape(user, quote=True)}</a>')

        escaped = _MENTION_RE.sub(stash_mention, escaped)

    if repo_html_url:
        base = repo_html_url.rstrip("/")

        def stash_sha(match: re.Match[str]) -> str:
            sha = match.group(1)
            href = html.escape(f"{base}/commit/{sha}", quote=True)
            short = sha[:7]
            return hold(f'<a href="{href}"><tt>{html.escape(short, quote=True)}</tt></a>')

        escaped = _SHA_RE.sub(stash_sha, escaped)

    def autolink(match: re.Match[str]) -> str:
        raw = html.unescape(match.group(0)).rstrip(").,;")
        safe = _safe_url(raw)
        if safe is None:
            return match.group(0)
        href = html.escape(safe, quote=True)
        return f'<a href="{href}">{html.escape(safe, quote=True)}</a>'

    escaped = _AUTOLINK_RE.sub(autolink, escaped)
    for index, chunk in reversed(list(enumerate(held))):
        escaped = escaped.replace(_PLACEHOLDER.format(index), chunk)
    return escaped


def sandboxed_markdown_label(
    markdown: str,
    *,
    issue_base_url: str | None = None,
    max_chars: int = 800,
    empty: str = "No description provided.",
):
    """Gtk.Label showing sandboxed markdown; activates https links."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from ..shells import open_external

    text = (markdown or "").strip() or empty
    if len(text) > max_chars:
        text = text[: max_chars - 1] + "…"
    repo_html = None
    if issue_base_url and issue_base_url.rstrip("/").endswith("/issues"):
        repo_html = issue_base_url.rstrip("/")[: -len("/issues")]
    markup = markdown_to_pango(text, issue_base_url=issue_base_url, repo_html_url=repo_html)
    label = Gtk.Label(wrap=True, xalign=0)
    label.set_use_markup(True)
    label.add_css_class("sandboxed-markdown")
    try:
        label.set_markup(markup)
    except Exception:
        label.set_use_markup(False)
        label.set_text(text)

    def on_link(_widget, uri: str) -> bool:
        if _safe_url(uri):
            open_external(uri)
        return True

    label.connect("activate-link", on_link)
    return label
