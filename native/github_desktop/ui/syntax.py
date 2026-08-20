"""Pygments-backed Pango markup highlighting, with a regex fallback."""

from __future__ import annotations

import html
import re
from functools import lru_cache

_STRING = re.compile(r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_COMMENT_HASH = re.compile(r"(#.*?)$")
_COMMENT_SLASH = re.compile(r"(//.*?)$")

KEYWORDS = {
    ".py": r"\b(and|as|assert|async|await|break|class|continue|def|del|elif|else|except|False|finally|for|from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield)\b",
    ".js": r"\b(async|await|break|case|catch|class|const|continue|debugger|default|delete|else|export|extends|false|finally|for|function|if|import|in|instanceof|let|new|null|return|static|super|switch|this|throw|true|try|typeof|var|void|while|yield)\b",
    ".ts": r"\b(async|await|break|case|catch|class|const|continue|default|else|enum|export|extends|false|finally|for|function|if|import|interface|let|new|null|return|static|super|switch|this|throw|true|try|type|typeof|var|void|while|yield)\b",
    ".json": r"\b(true|false|null)\b",
}

HASH_COMMENTS = {".py", ".rb", ".sh", ".yml", ".yaml", ".toml"}
SLASH_COMMENTS = {".js", ".ts", ".tsx", ".jsx", ".rs", ".go", ".c", ".h", ".cpp", ".java", ".php", ".cs"}

LIGHT = {
    "keyword": "#c45c26",
    "string": "#2a7f3e",
    "number": "#1a5fb4",
    "comment": "#77767b",
    "name": "#1c71d8",
    "builtin": "#613583",
}
DARK = {
    "keyword": "#ffa348",
    "string": "#8ff0a4",
    "number": "#99c1f1",
    "comment": "#9a9996",
    "name": "#62a0ea",
    "builtin": "#dc8add",
}


def _colors() -> dict[str, str]:
    try:
        from ..theme import is_dark

        return DARK if is_dark() else LIGHT
    except Exception:
        return LIGHT


@lru_cache(maxsize=64)
def _lexer_for(path: str):
    try:
        from pygments.lexers import TextLexer, get_lexer_for_filename

        if not path:
            return TextLexer(stripnl=False)
        return get_lexer_for_filename(path, stripnl=False, encoding="utf-8")
    except Exception:
        try:
            from pygments.lexers import TextLexer

            return TextLexer(stripnl=False)
        except Exception:
            return None


def _token_color(ttype, colors: dict[str, str]) -> str | None:
    names = [str(ttype)]
    current = ttype
    while getattr(current, "parent", None) is not None:
        current = current.parent
        names.append(str(current))
    joined = " ".join(names).lower()
    if "comment" in joined:
        return colors["comment"]
    if "string" in joined or "literal.string" in joined:
        return colors["string"]
    if "keyword" in joined or "operator.word" in joined:
        return colors["keyword"]
    if "number" in joined:
        return colors["number"]
    if "name.builtin" in joined or "name.function.magic" in joined:
        return colors["builtin"]
    if "name.function" in joined or "name.class" in joined or "name.decorator" in joined:
        return colors["name"]
    return None


def highlight_diff_line(text: str, path: str) -> str:
    """Return Pango markup for a single diff line body (without +/- prefix)."""
    lexer = _lexer_for(path)
    if lexer is not None:
        try:
            from pygments import lex

            colors = _colors()
            parts: list[str] = []
            for ttype, value in lex(text, lexer):
                escaped = html.escape(value)
                color = _token_color(ttype, colors)
                if color:
                    parts.append(f'<span foreground="{color}">{escaped}</span>')
                else:
                    parts.append(escaped)
            return "".join(parts)
        except Exception:
            pass
    return _regex_highlight(text, path)


def _regex_highlight(text: str, path: str) -> str:
    escaped = html.escape(text)
    ext = ""
    if path:
        dot = path.rfind(".")
        if dot >= 0:
            ext = path[dot:].lower()
    kw = KEYWORDS.get(ext) or KEYWORDS.get(".js" if ext in {".tsx", ".jsx"} else "")
    if kw:
        escaped = re.sub(kw, r'<span foreground="#c45c26">\1</span>', escaped)
    escaped = _STRING.sub(r'<span foreground="#2a7f3e">\1</span>', escaped)
    escaped = _NUMBER.sub(r'<span foreground="#1a5fb4">\g<0></span>', escaped)
    if ext in HASH_COMMENTS:
        escaped = _COMMENT_HASH.sub(r'<span foreground="#77767b">\1</span>', escaped)
    elif ext in SLASH_COMMENTS:
        escaped = _COMMENT_SLASH.sub(r'<span foreground="#77767b">\1</span>', escaped)
    return escaped
