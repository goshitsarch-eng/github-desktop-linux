"""GitHub-style emoji shortcodes for commit message completion."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

_FALLBACK: dict[str, str] = {
    "+1": "👍",
    "-1": "👎",
    "smile": "😄",
    "grinning": "😀",
    "joy": "😂",
    "thinking": "🤔",
    "tada": "🎉",
    "rocket": "🚀",
    "fire": "🔥",
    "bug": "🐛",
    "sparkles": "✨",
    "memo": "📝",
    "wrench": "🔧",
    "lock": "🔒",
    "unlock": "🔓",
    "warning": "⚠️",
    "x": "❌",
    "white_check_mark": "✅",
    "construction": "🚧",
    "recycle": "♻️",
    "art": "🎨",
    "zap": "⚡️",
    "boom": "💥",
    "book": "📖",
    "link": "🔗",
    "package": "📦",
    "ship": "🚢",
    "whale": "🐳",
    "penguin": "🐧",
    "heart": "❤️",
    "eyes": "👀",
    "pray": "🙏",
    "clap": "👏",
    "ok_hand": "👌",
    "hourglass": "⌛",
    "alarm_clock": "⏰",
    "shipit": "🚢",
}


@lru_cache(maxsize=1)
def emoji_map() -> dict[str, str]:
    path = Path(__file__).with_name("emoji_data.json")
    mapping = dict(_FALLBACK)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if isinstance(data, dict):
        for key, value in data.items():
            code = str(key).strip().strip(":")
            glyph = str(value)
            if code and glyph:
                mapping[code] = glyph
    return mapping


# Populated at import so existing `from .emoji import EMOJI` callers keep working.
EMOJI: dict[str, str] = emoji_map()


def expand_shortcodes(text: str) -> str:
    for code, glyph in emoji_map().items():
        text = text.replace(f":{code}:", glyph)
    return text


def matching_shortcodes(prefix: str, *, limit: int = 20) -> list[str]:
    needle = prefix.lower().lstrip(":")
    if not needle:
        return []
    matches = [f":{code}:" for code in emoji_map() if code.startswith(needle)]
    return matches[:limit]
