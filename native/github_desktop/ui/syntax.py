"""Pygments-backed rich-text highlighting in Breeze colors, with a regex fallback.

Colors follow KSyntaxHighlighting's Breeze Light and Breeze Dark themes so a
diff reads the same as the same file open in Kate.

Desktop lexes the full old/new file (`highlightContents`) then maps tokens onto
diff lines by 1-based line number. Per-line lexing is only the fallback for
when file contents are unavailable.
"""

from __future__ import annotations

import html
import re
from functools import lru_cache

from ..models import DiffLine, DiffLineType
from ..settings import tabSizeDefault

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
    "keyword": "#0057ae",
    "string": "#bf0303",
    "number": "#b08000",
    "comment": "#898887",
    "name": "#644a9b",
    "builtin": "#0057ae",
}
DARK = {
    "keyword": "#2980b9",
    "string": "#f44f4f",
    "number": "#f67400",
    "comment": "#7a7c7d",
    "name": "#8e44ad",
    "builtin": "#3daee9",
}

# Breeze renders keywords bold; the diff viewer follows suit.
BOLD_TOKENS = ("keyword",)

# Desktop MaxHighlightContentLength
MAX_HIGHLIGHT_CONTENT = 256 * 1024


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


def _token_is_bold(ttype) -> bool:
    return "keyword" in str(ttype).lower()


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


def _span(value: str, color: str | None, *, bold: bool = False) -> str:
    """Wrap ``value`` in the Qt rich-text subset understood by ``Text``.

    Qt uses CSS-in-``style`` for colors rather than Pango's ``foreground``
    attribute, and non-breaking spaces keep leading indentation from being
    collapsed when the line is rendered as rich text.
    """
    escaped = html.escape(value).replace(" ", "&nbsp;")
    if bold:
        escaped = f"<b>{escaped}</b>"
    if color:
        return f'<span style="color:{color}">{escaped}</span>'
    return escaped


def highlight_diff_line(text: str, path: str) -> str:
    """Return rich-text markup for a single diff line body (without +/- prefix)."""
    lexer = _lexer_for(path)
    if lexer is not None:
        try:
            from pygments import lex

            colors = _colors()
            parts: list[str] = []
            for ttype, value in lex(text, lexer):
                parts.append(_span(value, _token_color(ttype, colors), bold=_token_is_bold(ttype)))
            return "".join(parts)
        except Exception:
            pass
    return _regex_highlight(text, path)


def highlight_file(contents: list[str], path: str, tab_size: int = tabSizeDefault) -> dict[int, str]:
    """Lex the whole file and return 1-based line number → rich-text markup.

    Tab characters are expanded the same way DiffViewer displays them so tokens
    line up with the rendered diff body.
    """
    tab_size = max(1, int(tab_size or tabSizeDefault))
    expanded = [line.replace("\t", " " * tab_size) for line in contents]
    if not expanded:
        return {}
    blob = "\n".join(expanded)
    if len(blob.encode("utf-8", errors="replace")) > MAX_HIGHLIGHT_CONTENT:
        return {index + 1: highlight_diff_line(line, path) for index, line in enumerate(expanded)}
    lexer = _lexer_for(path)
    if lexer is None:
        return {index + 1: _regex_highlight(line, path) for index, line in enumerate(expanded)}
    try:
        from pygments import lex

        colors = _colors()
        line_parts: dict[int, list[str]] = {1: []}
        lineno = 1
        for ttype, value in lex(blob, lexer):
            color = _token_color(ttype, colors)
            bold = _token_is_bold(ttype)
            chunks = value.split("\n")
            for i, chunk in enumerate(chunks):
                if i:
                    lineno += 1
                    line_parts.setdefault(lineno, [])
                if chunk:
                    line_parts[lineno].append(_span(chunk, color, bold=bold))
        markup = {n: "".join(parts) for n, parts in line_parts.items()}
        for index, line in enumerate(expanded, start=1):
            markup.setdefault(index, _span(line, None))
        return markup
    except Exception:
        return {index + 1: _regex_highlight(line, path) for index, line in enumerate(expanded)}


def markup_for_diff_line(
    line: DiffLine,
    path: str,
    *,
    old_markup: dict[int, str] | None = None,
    new_markup: dict[int, str] | None = None,
    tab_size: int = tabSizeDefault,
) -> str:
    """Prefer file-level tokens (Desktop getTokens), else per-line lex."""
    if line.kind == DiffLineType.ADD and new_markup and line.new_line_number:
        mapped = new_markup.get(line.new_line_number)
        if mapped is not None:
            return mapped
    if line.kind == DiffLineType.DELETE and old_markup and line.old_line_number:
        mapped = old_markup.get(line.old_line_number)
        if mapped is not None:
            return mapped
    if line.kind == DiffLineType.CONTEXT:
        if old_markup and line.old_line_number and line.old_line_number in old_markup:
            return old_markup[line.old_line_number]
        if new_markup and line.new_line_number and line.new_line_number in new_markup:
            return new_markup[line.new_line_number]
    body = line.text[1:] if line.text[:1] in "+- " else line.text
    body = body.replace("\t", " " * max(1, tab_size))
    return highlight_diff_line(body, path)


def _regex_highlight(text: str, path: str) -> str:
    """Colorize without Pygments. Same Breeze palette, fewer token kinds."""
    colors = _colors()
    escaped = html.escape(text).replace(" ", "&nbsp;")
    ext = ""
    if path:
        dot = path.rfind(".")
        if dot >= 0:
            ext = path[dot:].lower()
    kw = KEYWORDS.get(ext) or KEYWORDS.get(".js" if ext in {".tsx", ".jsx"} else "")
    if kw:
        escaped = re.sub(kw, rf'<span style="color:{colors["keyword"]}"><b>\\1</b></span>', escaped)
    escaped = _STRING.sub(rf'<span style="color:{colors["string"]}">\\1</span>', escaped)
    escaped = _NUMBER.sub(rf'<span style="color:{colors["number"]}">\\g<0></span>', escaped)
    if ext in HASH_COMMENTS:
        escaped = _COMMENT_HASH.sub(rf'<span style="color:{colors["comment"]}">\\1</span>', escaped)
    elif ext in SLASH_COMMENTS:
        escaped = _COMMENT_SLASH.sub(rf'<span style="color:{colors["comment"]}">\\1</span>', escaped)
    return escaped
