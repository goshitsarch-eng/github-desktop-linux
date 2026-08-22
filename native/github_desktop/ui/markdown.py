"""Sandboxed GFM-lite → Pango markup (Desktop `SandboxedMarkdown` stand-in).

Desktop renders PR bodies in a sandboxed iframe. Native GTK has no WebKit
requirement, so we convert a safe subset of GitHub Flavored Markdown to Pango
markup: emphasis, inline/fenced code, https-only links, emoji shortcodes,
``IssueMentionFilter`` (``#123``, ``gh-123``, ``/issues/123``, ``owner/repo#123``),
``MentionFilter`` (@user), ``TeamMentionFilter`` (@org/team),
``CloseKeywordFilter`` (Closes/Fixes/Resolves with tooltip
``This pull request closes #N.``), and ``CommitMentionFilter`` (7–40 hex SHAs,
``SHA...SHA`` ranges, and ``owner/repo@SHA``).
Raw HTML, ``javascript:``, and ``data:`` URLs are dropped.
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
# Desktop VideoTagFilter: keep GitHub user-asset videos, drop others.
_VIDEO_TAG_RE = re.compile(r"<video\b[^>]*/>|<video\b[^>]*>.*?</video\s*>", re.I | re.S)
# Desktop `githubAssetVideoRegex` / `video-url-regex.ts` / VideoLinkFilter
_GITHUB_ASSET_VIDEO_RE = re.compile(
    r"^https://user-images\.githubusercontent\.com/.+\.(?:mp4|webm|ogg|mov|qt|avi|wmv|3gp|mpg|mpeg)(?:\?.*)?$",
    re.I,
)
githubAssetVideoRegex = _GITHUB_ASSET_VIDEO_RE
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)|(?<!_)_(?!_)(.+?)(?<!_)_(?!_)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.M)
_QUOTE_RE = re.compile(r"^&gt;\s?(.*)$", re.M)
# TeamMentionFilter: @org/team before MentionFilter so the slash is not split.
_TEAM_MENTION_RE = re.compile(
    r"(^|[^A-Za-z0-9_`])@([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9][A-Za-z0-9_-]*)\b"
)
_MENTION_RE = re.compile(
    r"(^|[^A-Za-z0-9_`])@([A-Za-z0-9][A-Za-z0-9-]{0,38})(?![/\w-])"
)
_SHA_RE = re.compile(r"\b([0-9a-f]{7,40})\b")
# CommitMentionFilter: SHA...SHA ranges before bare SHAs.
_SHA_RANGE_RE = re.compile(r"(?<![0-9a-f])(?P<a>[0-9a-f]{7,40})\.\.\.(?P<b>[0-9a-f]{7,40})\b")
# CommitMentionFilter: owner@SHA or owner/repo@SHA before bare SHAs.
_OWNER_SHA_RE = re.compile(
    r"(?<!\w)(?P<owner>[\w-]+)(?:/(?P<name>[\w.-]+))?@(?P<sha>[0-9a-f]{7,40})\b"
)
# CloseKeywordFilter: close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved
_CLOSE_KEYWORD_RE = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)(\s*:?\s+)(?=#|gh-|/(?:issues|pull|discussions)/)",
    re.I,
)
# IssueMentionFilter: optional owner/repo, then # | gh- | /issues/ | /pull/ | /discussions/
_ISSUE_MENTION_RE = re.compile(
    r"(?<!\w)(?:(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/(?P<repo>[\w.-]+))?"
    r"(?P<marker>#|gh-|/(?:issues|pull|discussions)/)(?P<num>\d+)\b",
    re.I,
)
CLOSE_KEYWORD_TOOLTIP = "This pull request closes #{0}."


def is_github_asset_video_url(url: str) -> bool:
    """Desktop `githubAssetVideoRegex` / VideoLinkFilter."""
    return bool(_GITHUB_ASSET_VIDEO_RE.match((url or "").strip()))


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


_ISSUE_LINK_RE = re.compile(
    r"https?://[^/\s]+/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)/(?:issues|pull|discussions)/(?P<num>\d+)(?P<anchor>#[\w-]+)?",
    re.I,
)
_ISSUE_PR_TAB_RE = re.compile(r"\d+/(files|commits|conflicts|checks)")
_ISSUE_CUSTOM_FORMAT_RE = re.compile(r"\.[a-z]+$")
_COMMIT_LINK_RE = re.compile(
    r"https?://[^/\s]+/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)/commit/(?P<sha>[0-9a-f]{7,40})(?P<path>/[^?\s]*)?",
    re.I,
)
_COMPARE_LINK_RE = re.compile(
    r"https?://[^/\s]+/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)/compare/(?P<a>[0-9a-f]{7,40})\.\.\.(?P<b>[0-9a-f]{7,40})",
    re.I,
)
_PR_COMMIT_LINK_RE = re.compile(
    r"https?://[^/\s]+/(?P<owner>[\w.-]+)/(?P<name>[\w.-]+)/pull/\d+/commits/(?P<sha>[0-9a-f]{7,40})",
    re.I,
)
_COMMIT_ACTION_PATHS = {"checks_state_summary", "hovercard", "rollup", "show_partial"}
_COMMIT_ACTION_PREFIXES = {"_render_node", "checks"}


def _trim_commit_sha(sha: str) -> str:
    """Desktop CommitMentionFilter / CommitMentionLinkFilter `trimCommitSha`: 30+ chars → first 7."""
    return sha[:7] if len(sha) >= 30 else sha


def resolve_owner_repo(owner_or_owner_repo: str | None, current: tuple[str, str] | None) -> list[str] | None:
    """Desktop `resolveOwnerRepo` for `owner@sha` / `owner/repo@sha` mentions."""
    if owner_or_owner_repo is None:
        return []
    parts = [part for part in owner_or_owner_repo.split("/") if part]
    if len(parts) > 2:
        return None
    if current is None:
        return parts if len(parts) == 2 else None
    if len(parts) == 1 and parts[0] != current[0]:
        return None
    if len(parts) == 2 and (parts[0] != current[0] or parts[1] != current[1]):
        return parts
    return []


def _repo_owner_name(repo_html_url: str | None) -> tuple[str, str] | None:
    if not repo_html_url:
        return None
    parsed = urlparse(repo_html_url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def _issue_anchor_description(anchor: str | None) -> str:
    """Desktop IssueLinkFilter `getAnchorDescription`."""
    if not anchor:
        return ""
    if re.search(r"discussion-diff-", anchor, re.I):
        return "(diff)"
    if re.search(r"commits-pushed-", anchor, re.I):
        return "(commits)"
    if re.search(r"ref-", anchor, re.I):
        return "(reference)"
    if re.search(r"pullrequestreview", anchor, re.I):
        return "(review)"
    return "(comment)"


def shorten_github_autolink(url: str, repo_html_url: str | None = None) -> str | None:
    """Desktop `IssueLinkFilter` / `CommitMentionLinkFilter` display text for raw URLs."""
    raw = (url or "").strip()
    issue = _ISSUE_LINK_RE.match(raw)
    if issue:
        if _ISSUE_PR_TAB_RE.search(raw) or _ISSUE_CUSTOM_FORMAT_RE.search(raw.split("#", 1)[0]):
            return None
        current = _repo_owner_name(repo_html_url)
        if current is not None:
            parsed = urlparse(raw)
            repo_parsed = urlparse(repo_html_url or "")
            if repo_parsed.netloc and parsed.netloc.lower() != repo_parsed.netloc.lower():
                return None
            if (issue.group("owner"), issue.group("name")) != current:
                return None
        label = f"#{issue.group('num')}"
        extra = _issue_anchor_description(issue.group("anchor"))
        return f"{label} {extra}".strip()
    current = _repo_owner_name(repo_html_url)

    def prefix(owner: str, name: str) -> str:
        if current is None or current != (owner, name):
            return f"{owner}/{name}@"
        return ""

    pr_commit = _PR_COMMIT_LINK_RE.match(raw)
    if pr_commit:
        sha = _trim_commit_sha(pr_commit.group("sha"))
        return f"{prefix(pr_commit.group('owner'), pr_commit.group('name'))}<tt>{sha}</tt>"
    compare = _COMPARE_LINK_RE.match(raw)
    if compare:
        left = _trim_commit_sha(compare.group("a"))
        right = _trim_commit_sha(compare.group("b"))
        return f"{prefix(compare.group('owner'), compare.group('name'))}<tt>{left}...{right}</tt>"
    commit = _COMMIT_LINK_RE.match(raw)
    if commit:
        rest = (commit.group("path") or "").lstrip("/")
        first = rest.split("/", 1)[0] if rest else ""
        if rest in _COMMIT_ACTION_PATHS or first in _COMMIT_ACTION_PREFIXES:
            return None
        sha = _trim_commit_sha(commit.group("sha"))
        path = commit.group("path") or ""
        return f"{prefix(commit.group('owner'), commit.group('name'))}<tt>{sha}</tt>{path}"
    return None


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


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def close_keyword_tooltip(text: str) -> str | None:
    """Desktop CloseKeywordFilter tooltip when the body mentions Closes/Fixes #N."""
    match = re.search(
        r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s*(?:#|gh-|/(?:issues|pull|discussions)/)(\d+)",
        text or "",
        re.I,
    )
    if not match:
        return None
    return CLOSE_KEYWORD_TOOLTIP.format(match.group(1))


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
        if is_github_asset_video_url(safe):
            text = "Video"
        elif label.strip() == url.strip():
            shortened = shorten_github_autolink(safe, repo_html_url)
            text = shortened if shortened is not None else html.escape(label, quote=True)
        else:
            text = html.escape(label, quote=True)
        return hold(f'<a href="{href}">{text}</a>')

    source = _MD_LINK_RE.sub(stash_link, source)

    def replace_video_tag(match: re.Match[str]) -> str:
        tag = match.group(0)
        src_match = re.search(r"""\bsrc\s*=\s*["']([^"']+)["']""", tag, re.I)
        src = src_match.group(1) if src_match else ""
        safe = _safe_url(src)
        if safe is None or not is_github_asset_video_url(safe):
            return ""
        href = html.escape(safe, quote=True)
        return hold(f'<a href="{href}">Video</a>')

    source = _VIDEO_TAG_RE.sub(replace_video_tag, source)

    def stash_autolink(match: re.Match[str]) -> str:
        raw = match.group(0).rstrip(").,;")
        safe = _safe_url(raw)
        if safe is None:
            return match.group(0)
        href = html.escape(safe, quote=True)
        if is_github_asset_video_url(safe):
            label = "Video"
        else:
            shortened = shorten_github_autolink(safe, repo_html_url)
            label = shortened if shortened is not None else html.escape(safe, quote=True)
        return hold(f'<a href="{href}">{label}</a>')

    source = _AUTOLINK_RE.sub(stash_autolink, source)
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

    host = _host_from_url(issue_base_url) or _host_from_url(repo_html_url)

    def stash_close(match: re.Match[str]) -> str:
        verb, space = match.group(1), match.group(2)
        return hold(f"<span>{html.escape(verb, quote=True)}</span>") + space

    escaped = _CLOSE_KEYWORD_RE.sub(stash_close, escaped)

    if issue_base_url or host:
        default_base = (issue_base_url or "").rstrip("/")

        def stash_issue(match: re.Match[str]) -> str:
            owner, repo, marker, num = (
                match.group("owner"),
                match.group("repo"),
                match.group("marker"),
                match.group("num"),
            )
            label = match.group(0)
            _ = marker
            if owner and repo and host:
                href = f"{host}/{owner}/{repo}/issues/{num}"
            elif default_base:
                href = f"{default_base}/{num}"
            elif host and repo_html_url:
                href = f"{repo_html_url.rstrip('/')}/issues/{num}"
            else:
                return match.group(0)
            return hold(f'<a href="{html.escape(href, quote=True)}">{html.escape(label, quote=True)}</a>')

        escaped = _ISSUE_MENTION_RE.sub(stash_issue, escaped)

    if host:

        def stash_team(match: re.Match[str]) -> str:
            prefix, org, team = match.group(1), match.group(2), match.group(3)
            href = html.escape(f"{host}/orgs/{org}/teams/{team}", quote=True)
            label = html.escape(f"@{org}/{team}", quote=True)
            return hold(f'{prefix}<a href="{href}">{label}</a>')

        escaped = _TEAM_MENTION_RE.sub(stash_team, escaped)

        def stash_mention(match: re.Match[str]) -> str:
            prefix, user = match.group(1), match.group(2)
            href = html.escape(f"{host}/{user}", quote=True)
            return hold(f'{prefix}<a href="{href}">@{html.escape(user, quote=True)}</a>')

        escaped = _MENTION_RE.sub(stash_mention, escaped)

    if repo_html_url:
        base = repo_html_url.rstrip("/")
        current = _repo_owner_name(repo_html_url)
        mention_host = host or _host_from_url(repo_html_url)

        def stash_sha_range(match: re.Match[str]) -> str:
            left = _trim_commit_sha(match.group("a"))
            right = _trim_commit_sha(match.group("b"))
            href = html.escape(f"{base}/compare/{left}...{right}", quote=True)
            label = f"{html.escape(left, quote=True)}...{html.escape(right, quote=True)}"
            return hold(f'<a href="{href}"><tt>{label}</tt></a>')

        escaped = _SHA_RANGE_RE.sub(stash_sha_range, escaped)

        def stash_owner_sha(match: re.Match[str]) -> str:
            owner, name, sha = match.group("owner"), match.group("name"), match.group("sha")
            spec = f"{owner}/{name}" if name else owner
            resolved = resolve_owner_repo(spec, current)
            if resolved is None:
                return hold(match.group(0))
            trimmed = _trim_commit_sha(sha)
            if len(resolved) < 2:
                href = html.escape(f"{base}/commit/{trimmed}", quote=True)
                return hold(f'<a href="{href}"><tt>{html.escape(trimmed, quote=True)}</tt></a>')
            repo_owner, repo_name = resolved[0], resolved[1]
            href = html.escape(f"{mention_host}/{repo_owner}/{repo_name}/commit/{trimmed}", quote=True)
            prefix = html.escape(f"{repo_owner}/{repo_name}@", quote=True)
            return hold(f'<a href="{href}">{prefix}<tt>{html.escape(trimmed, quote=True)}</tt></a>')

        escaped = _OWNER_SHA_RE.sub(stash_owner_sha, escaped)

        def stash_sha(match: re.Match[str]) -> str:
            sha = match.group(1)
            trimmed = _trim_commit_sha(sha)
            href = html.escape(f"{base}/commit/{trimmed}", quote=True)
            return hold(f'<a href="{href}"><tt>{html.escape(trimmed, quote=True)}</tt></a>')

        escaped = _SHA_RE.sub(stash_sha, escaped)

    for index, chunk in reversed(list(enumerate(held))):
        escaped = escaped.replace(_PLACEHOLDER.format(index), chunk)
    return escaped


def sandboxed_markdown_label(
    markdown: str,
    *,
    issue_base_url: str | None = None,
    max_chars: int = 800,
    empty: str = "No description provided.",
    repository=None,
):
    """Gtk.Label showing sandboxed markdown; activates https links."""
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from ..shells import open_external

    if repository is not None and issue_base_url is None:
        github = getattr(repository, "github", None)
        html = getattr(github, "html_url", None) if github is not None else None
        if html:
            issue_base_url = str(html).rstrip("/") + "/issues"
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
    tip = close_keyword_tooltip(markdown or "")
    if tip:
        label.set_tooltip_text(tip)

    def on_link(_widget, uri: str) -> bool:
        if _safe_url(uri):
            open_external(uri)
        return True

    label.connect("activate-link", on_link)
    return label
