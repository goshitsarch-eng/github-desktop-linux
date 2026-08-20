"""Desktop `parsePACString`: Chromium PAC lists to cURL-compatible proxy URLs."""

from __future__ import annotations

import re

_SPEC_SPLIT = re.compile(r"\s*;\s*")
_WORD_SPLIT = re.compile(r"\s+")


def parse_pac_string(pac_string: str) -> list[str] | None:
    """Parse a Proxy Auto Configuration (PAC) string into cURL proxy URLs.

    Mirrors Desktop `parsePACString`. Not a generic PAC JS evaluator: it
    translates PAC strings returned from Electron `session.resolveProxy`
    (Chromium `ProxyList::ToPacString()`). QUIC and other cURL-unsupported
    protocols are omitted. Specs after ``DIRECT`` are ignored.
    """
    if pac_string == "DIRECT":
        return None

    specs = _SPEC_SPLIT.split(pac_string.strip())
    urls: list[str] = []

    for spec in specs:
        if re.match(r"^direct", spec, flags=re.I):
            break
        parts = _WORD_SPLIT.split(spec, maxsplit=1)
        protocol = parts[0] if parts else ""
        endpoint = parts[1] if len(parts) > 1 else None
        if endpoint:
            url = _url_from_protocol_and_endpoint(protocol, endpoint)
            if url is not None:
                urls.append(url)

    return urls if urls else None


def _url_from_protocol_and_endpoint(protocol: str, endpoint: str) -> str | None:
    # Preserve the port. URL parsers strip default ports, but cURL defaults
    # to 1080 for every proxy protocol, so `PROXY myproxy:80` must stay
    # `http://myproxy:80`.
    kind = protocol.lower()
    if kind in {"proxy", "http"}:
        return f"http://{endpoint}"
    if kind == "https":
        return f"https://{endpoint}"
    if kind in {"socks", "socks4"}:
        return f"socks4://{endpoint}"
    if kind == "socks5":
        return f"socks5://{endpoint}"
    return None
