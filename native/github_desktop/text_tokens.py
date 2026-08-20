"""Commit-message tokenizer and wrap (Desktop `text-token-parser` + `wrap-rich-text-commit-message`)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .models import GitHubRepository, Repository, github_for_contribution, html_url_from_endpoint

MaxSummaryLength = 72
IdealSummaryLength = 50

_ISSUE_REF = re.compile(r"^#\d+$")
_MENTION = re.compile(r"^@[a-zA-Z0-9\-]+$")
_HYPERLINK = re.compile(r"^https?://.+")
_EMOJI_SHORTCODE = re.compile(r"^:.*?:$")


class TokenType(Enum):
    TEXT = "text"
    EMOJI = "emoji"
    LINK = "link"


@dataclass(frozen=True)
class Token:
    kind: TokenType
    text: str
    url: str | None = None
    path: str | None = None
    emoji: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class WrappedCommitMessage:
    summary: list[Token]
    body: list[Token]


def _emoji_lookup() -> dict[str, str]:
    from .ui.emoji import emoji_map

    return {f":{code}:": glyph for code, glyph in emoji_map().items()}


class Tokenizer:
    """Desktop `Tokenizer`: emoji, issues, mentions, and https links."""

    def __init__(
        self,
        emoji: dict[str, str] | None = None,
        repository: Repository | GitHubRepository | None = None,
        *,
        github: GitHubRepository | None = None,
    ) -> None:
        self._emoji = emoji if emoji is not None else _emoji_lookup()
        self.repository: GitHubRepository | None = github
        if self.repository is None and isinstance(repository, GitHubRepository):
            self.repository = repository
        elif self.repository is None and isinstance(repository, Repository):
            self.repository = github_for_contribution(repository)
        self._results: list[Token] = []
        self._current = ""

    def reset(self) -> None:
        self._results = []
        self._current = ""

    def append(self, character: str) -> None:
        self._current += character

    def flush(self) -> None:
        if self._current:
            self._results.append(Token(TokenType.TEXT, self._current))
            self._current = ""

    def _last_char(self) -> str | None:
        return self._current[-1] if self._current else None

    def _end_of_word(self, text: str, index: int) -> int:
        newline = text.find("\n", index + 1)
        space = text.find(" ", index + 1)
        if newline > -1 and space > -1:
            return min(newline, space)
        if newline > -1:
            return newline
        if space > -1:
            return space
        return len(text)

    def _scan_emoji(self, text: str, index: int) -> int | None:
        nxt = self._end_of_word(text, index)
        maybe = text[index:nxt]
        if not _EMOJI_SHORTCODE.match(maybe):
            return None
        glyph = self._emoji.get(maybe)
        if not glyph:
            return None
        self.flush()
        self._results.append(Token(TokenType.EMOJI, maybe, emoji=glyph))
        return nxt

    def _scan_issue(self, text: str, index: int, repository: GitHubRepository) -> int | None:
        nxt = self._end_of_word(text, index)
        maybe = text[index:nxt]
        if maybe.endswith(")"):
            nxt -= 1
            maybe = text[index:nxt]
        if maybe.endswith("."):
            nxt -= 1
            maybe = text[index:nxt]
        if maybe.endswith(","):
            nxt -= 1
            maybe = text[index:nxt]
        if not _ISSUE_REF.match(maybe):
            return None
        issue_id = maybe[1:]
        if not issue_id.isdigit():
            return None
        self.flush()
        url = f"{repository.html_url}/issues/{int(issue_id)}"
        self._results.append(Token(TokenType.LINK, maybe, url=url))
        return nxt

    def _scan_mention(self, text: str, index: int, repository: GitHubRepository) -> int | None:
        last = self._last_char()
        if last and not last.isspace():
            return None
        nxt = self._end_of_word(text, index)
        maybe = text[index:nxt]
        if maybe.endswith("!") or maybe.endswith(","):
            nxt -= 1
            maybe = text[index:nxt]
        if not _MENTION.match(maybe):
            return None
        self.flush()
        html = html_url_from_endpoint(repository.endpoint)
        self._results.append(Token(TokenType.LINK, maybe, url=f"{html}/{maybe[1:]}"))
        return nxt

    def _scan_hyperlink(self, text: str, index: int, repository: GitHubRepository | None = None) -> int | None:
        last = self._last_char()
        if last and not last.isspace():
            return None
        nxt = self._end_of_word(text, index)
        maybe = text[index:nxt]
        if not _HYPERLINK.match(maybe):
            return None
        self.flush()
        if repository and repository.html_url:
            compare = repository.html_url.lower()
            if maybe.lower().startswith(f"{compare}/issues/"):
                match = re.search(r"/issues/(\d+)", maybe)
                if match:
                    self._results.append(Token(TokenType.LINK, f"#{match.group(1)}", url=maybe))
                    return nxt
        self._results.append(Token(TokenType.LINK, maybe, url=maybe))
        return nxt

    def _inspect(self, text: str, index: int, scanner) -> int:
        match = scanner()
        if match is not None:
            return match
        self.append(text[index])
        return index + 1

    def tokenize(self, text: str) -> list[Token]:
        self.reset()
        i = 0
        github = self.repository
        while i < len(text):
            ch = text[i]
            if ch == ":":
                i = self._inspect(text, i, lambda idx=i: self._scan_emoji(text, idx))
            elif github is not None and ch == "#":
                i = self._inspect(text, i, lambda idx=i: self._scan_issue(text, idx, github))
            elif github is not None and ch == "@":
                i = self._inspect(text, i, lambda idx=i: self._scan_mention(text, idx, github))
            elif ch == "h":
                i = self._inspect(text, i, lambda idx=i: self._scan_hyperlink(text, idx, github))
            else:
                self.append(ch)
                i += 1
        self.flush()
        return list(self._results)


def _text(value: str) -> Token:
    return Token(TokenType.TEXT, value)


def _link(text: str, url: str) -> Token:
    return Token(TokenType.LINK, text, url=url)


def _ellipsis() -> Token:
    return _text("…")


def tokens_as_text(tokens: Iterable[Token]) -> str:
    return "".join(token.text for token in tokens)


def wrap_rich_text_commit_message(
    summary_text: str,
    body_text: str = "",
    tokenizer: Tokenizer | None = None,
    max_summary_length: int = MaxSummaryLength,
    *,
    github: GitHubRepository | None = None,
    repository: Repository | None = None,
) -> WrappedCommitMessage:
    """Desktop `wrapRichTextCommitMessage`."""
    parser = tokenizer or Tokenizer(repository=repository, github=github)
    tokens = parser.tokenize(summary_text.rstrip())
    summary: list[Token] = []
    overflow: list[Token] = []
    remainder = max_summary_length
    for token in tokens:
        char_count = 2 if token.kind is TokenType.EMOJI else len(token.text)
        if remainder <= 0:
            overflow.append(token)
        elif remainder >= char_count:
            summary.append(token)
            remainder -= char_count
        else:
            if token.kind is TokenType.TEXT:
                summary.append(_text(token.text[:remainder]))
                overflow.append(_text(token.text[remainder:]))
            elif token.kind is TokenType.EMOJI:
                overflow.append(token)
            elif token.kind is TokenType.LINK:
                if not token.text.startswith("#") and remainder > 5:
                    url = token.text
                    summary.append(_link(token.text[:remainder], url))
                    overflow.append(_link(token.text[remainder:], url))
                else:
                    overflow.append(token)
            remainder = 0
    body = parser.tokenize(body_text.rstrip())
    if overflow:
        summary.append(_ellipsis())
        if body:
            body = [_ellipsis(), *overflow, _text("\n\n"), *body]
        else:
            body = [_ellipsis(), *overflow]
    return WrappedCommitMessage(summary, body)
