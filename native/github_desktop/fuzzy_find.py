"""Fuzzy filter matching (Desktop `fuzzy-find` / `fuzzaldrin-plus` stand-in)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")
KeyFunction = Callable[[T], Sequence[str]]

_SEPARATORS = frozenset(" \t/_-.")


@dataclass
class FuzzyMatches:
    """Desktop `IMatches`."""

    title: list[int] = field(default_factory=list)
    subtitle: list[int] = field(default_factory=list)


@dataclass
class FuzzyMatch:
    """Desktop `IMatch<T>`: `0 <= score <= 1`."""

    score: float
    item: T
    matches: FuzzyMatches


def is_empty_or_whitespace(value: str | None) -> bool:
    """Desktop `isEmptyOrWhitespace`."""
    return not (value or "").strip()


def _is_word_start(text: str, index: int) -> bool:
    if index <= 0:
        return True
    prev = text[index - 1]
    return prev in _SEPARATORS or (prev.islower() and text[index].isupper())


def fuzzy_match_indices(text: str, query: str) -> list[int]:
    """Return character indices of `query` in `text`, or an empty list."""
    if not query:
        return []
    lower = text.lower()
    needle = query.lower()
    start = lower.find(needle)
    if start >= 0:
        return list(range(start, start + len(needle)))
    indices: list[int] = []
    pos = 0
    for ch in needle:
        found = lower.find(ch, pos)
        if found < 0:
            return []
        indices.append(found)
        pos = found + 1
    return indices


def fuzzy_score(text: str, query: str, indices: Sequence[int] | None = None) -> float:
    """Relative score used before normalizing against a perfect self-match."""
    if not query:
        return 0.0
    hits = list(indices) if indices is not None else fuzzy_match_indices(text, query)
    if not hits:
        return 0.0
    consecutive = sum(1 for i in range(1, len(hits)) if hits[i] == hits[i - 1] + 1)
    word_starts = sum(1 for i in hits if _is_word_start(text, i))
    leading = 2.0 if hits[0] == 0 else 0.0
    coverage = len(hits) / max(len(text), 1)
    return consecutive * 5.0 + word_starts * 3.0 + leading + coverage


def match(query: str, items: Sequence[T], get_key: KeyFunction[T]) -> list[FuzzyMatch[T]]:
    """Desktop `match`: rank items whose title or subtitle fuzzy-matches `query`."""
    if is_empty_or_whitespace(query):
        return []
    max_score = fuzzy_score(query, query) or 1.0
    results: list[FuzzyMatch[T]] = []
    for item in items:
        keys = [str(part) for part in get_key(item)]
        title = keys[0] if keys else ""
        subtitle = keys[1] if len(keys) > 1 else ""
        title_hits = fuzzy_match_indices(title, query)
        subtitle_hits = fuzzy_match_indices(subtitle, query) if subtitle else []
        if not title_hits and not subtitle_hits:
            continue
        joined = "".join(keys)
        score = fuzzy_score(joined, query) / max_score
        results.append(
            FuzzyMatch(
                score=min(max(score, 0.0), 1.0),
                item=item,
                matches=FuzzyMatches(title=title_hits, subtitle=subtitle_hits),
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def filter_items(query: str, items: Sequence[T], get_key: KeyFunction[T]) -> list[T]:
    """All items when `query` is blank; otherwise Desktop `match` order."""
    if is_empty_or_whitespace(query):
        return list(items)
    return [hit.item for hit in match(query, items, get_key)]
