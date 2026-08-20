"""Lightweight Pango markup highlighting for common source files."""

from __future__ import annotations

import html
import re

_STRING = re.compile(r"(\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*')")
_NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
_COMMENT_HASH = re.compile(r"(#.*?)$")
_COMMENT_SLASH = re.compile(r"(//.*?)$")

KEYWORDS = {
    ".py": r"\b(and|as|assert|async|await|break|class|continue|def|del|elif|else|except|False|finally|for|from|global|if|import|in|is|lambda|None|nonlocal|not|or|pass|raise|return|True|try|while|with|yield)\b",
    ".js": r"\b(async|await|break|case|catch|class|const|continue|debugger|default|delete|else|export|extends|false|finally|for|function|if|import|in|instanceof|let|new|null|return|static|super|switch|this|throw|true|try|typeof|var|void|while|yield)\b",
    ".ts": r"\b(async|await|break|case|catch|class|const|continue|default|else|enum|export|extends|false|finally|for|function|if|import|interface|let|new|null|return|static|super|switch|this|throw|true|try|type|typeof|var|void|while|yield)\b",
    ".tsx": r"\b(async|await|break|case|catch|class|const|continue|default|else|export|extends|false|finally|for|function|if|import|interface|let|new|null|return|static|super|switch|this|throw|true|try|type|typeof|var|void|while|yield)\b",
    ".rs": r"\b(as|async|await|break|const|continue|crate|dyn|else|enum|extern|false|fn|for|if|impl|in|let|loop|match|mod|move|mut|pub|ref|return|self|Self|static|struct|super|trait|true|type|unsafe|use|where|while)\b",
    ".go": r"\b(break|case|chan|const|continue|default|defer|else|fallthrough|for|func|go|goto|if|import|interface|map|package|range|return|select|struct|switch|type|var)\b",
    ".c": r"\b(auto|break|case|char|const|continue|default|do|double|else|enum|extern|float|for|goto|if|inline|int|long|register|return|short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|volatile|while)\b",
    ".h": r"\b(auto|break|case|char|const|continue|default|do|double|else|enum|extern|float|for|goto|if|inline|int|long|register|return|short|signed|sizeof|static|struct|switch|typedef|union|unsigned|void|volatile|while)\b",
    ".cpp": r"\b(auto|bool|break|case|catch|char|class|const|constexpr|continue|default|delete|do|double|else|enum|explicit|extern|false|float|for|friend|goto|if|inline|int|long|namespace|new|nullptr|operator|private|protected|public|return|short|signed|sizeof|static|struct|switch|template|this|throw|true|try|typedef|typename|union|unsigned|using|virtual|void|volatile|while)\b",
    ".java": r"\b(abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|default|do|double|else|enum|extends|false|final|finally|float|for|goto|if|implements|import|instanceof|int|interface|long|native|new|null|package|private|protected|public|return|short|static|strictfp|super|switch|synchronized|this|throw|throws|transient|true|try|void|volatile|while)\b",
    ".rb": r"\b(BEGIN|END|alias|and|begin|break|case|class|def|defined|do|else|elsif|end|ensure|false|for|if|in|module|next|nil|not|or|redo|rescue|retry|return|self|super|then|true|undef|unless|until|when|while|yield)\b",
    ".sh": r"\b(alias|break|case|do|done|elif|else|esac|export|fi|for|function|if|in|local|return|select|then|time|until|while)\b",
    ".json": r"\b(true|false|null)\b",
}

HASH_COMMENTS = {".py", ".rb", ".sh", ".yml", ".yaml", ".toml"}
SLASH_COMMENTS = {".js", ".ts", ".tsx", ".rs", ".go", ".c", ".h", ".cpp", ".java"}


def highlight_diff_line(text: str, path: str) -> str:
    """Return Pango markup for a single diff line body (without +/- prefix)."""
    escaped = html.escape(text)
    ext = ""
    if path:
        dot = path.rfind(".")
        if dot >= 0:
            ext = path[dot:].lower()
    kw = KEYWORDS.get(ext)
    if kw:
        escaped = re.sub(kw, r'<span foreground="#c45c26">\1</span>', escaped)
    escaped = _STRING.sub(r'<span foreground="#2a7f3e">\1</span>', escaped)
    escaped = _NUMBER.sub(r'<span foreground="#1a5fb4">\g<0></span>', escaped)
    if ext in HASH_COMMENTS:
        escaped = _COMMENT_HASH.sub(r'<span foreground="#77767b">\1</span>', escaped)
    elif ext in SLASH_COMMENTS:
        escaped = _COMMENT_SLASH.sub(r'<span foreground="#77767b">\1</span>', escaped)
    return escaped
