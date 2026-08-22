"""Truncate a unicode string and add an ellipsis (Desktop `truncateWithEllipsis`)."""

from __future__ import annotations


def truncate_with_ellipsis(text: str, max_length: int) -> str:
    """Desktop `truncateWithEllipsis`: unicode-aware, keeps variation selectors."""
    if len(text) <= max_length:
        return text
    code_points = list(text)
    if len(code_points) <= max_length:
        return text
    characters: list[str] = []
    for code in code_points:
        if "\ufe00" <= code <= "\ufe0f":
            if characters:
                characters.append(f"{characters.pop()}{code}")
        else:
            characters.append(code)
    if len(characters) <= max_length:
        return text
    return "".join(characters[:max_length]) + "…"
