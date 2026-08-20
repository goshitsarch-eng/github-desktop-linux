"""GitHub-style emoji shortcodes for commit message completion."""

from __future__ import annotations

EMOJI: dict[str, str] = {
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
}


def expand_shortcodes(text: str) -> str:
    for code, glyph in EMOJI.items():
        text = text.replace(f":{code}:", glyph)
    return text


def matching_shortcodes(prefix: str) -> list[str]:
    needle = prefix.lower().lstrip(":")
    if not needle:
        return [f":{code}:" for code in list(EMOJI)[:12]]
    return [f":{code}:" for code in EMOJI if code.startswith(needle)][:12]
