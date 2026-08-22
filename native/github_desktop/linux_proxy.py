"""Linux system proxy (GNOME gsettings / KDE kioslaverc) as Chromium PAC stand-in."""

from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .logging import get_logger

log = get_logger()

_CACHE: tuple[float, "SystemProxySettings | None"] | None = None
_CACHE_TTL = 30.0
_GVARIANT_QUOTED = re.compile(r"'((?:\\'|[^'])*)'")


@dataclass(frozen=True)
class SystemProxySettings:
    """Normalized desktop proxy settings. ``mode`` is none/manual/auto."""

    mode: str
    http: str | None = None
    https: str | None = None
    socks: str | None = None
    ignore_hosts: list[str] = field(default_factory=list)
    pac_url: str | None = None


def clear_linux_proxy_cache() -> None:
    global _CACHE
    _CACHE = None


def parse_gvariant(raw: str):
    """Parse `gsettings get` GVariant text (string, uint32, boolean, strv)."""
    text = (raw or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if text.startswith(("uint32", "int32", "uint16", "int16", "uint64", "int64")):
        return int(text.split()[-1])
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1].replace("\\'", "'")
    if text.startswith("[") and text.endswith("]"):
        return [item.replace("\\'", "'") for item in _GVARIANT_QUOTED.findall(text)]
    try:
        return int(text)
    except ValueError:
        return text.strip("'\"")


def host_matches_no_proxy(host: str, patterns: list[str] | tuple[str, ...]) -> bool:
    """Match a hostname/IP against GNOME ignore-hosts / curl ``no_proxy`` patterns."""
    host = (host or "").lower().rstrip(".")
    if not host:
        return False
    host_ip = None
    try:
        host_ip = ipaddress.ip_address(host)
    except ValueError:
        host_ip = None
    for pattern in patterns:
        raw = (pattern or "").strip().strip("'\"")
        if not raw:
            continue
        lowered = raw.lower()
        if lowered == "*":
            return True
        if "/" in lowered:
            if host_ip is None:
                continue
            try:
                if host_ip in ipaddress.ip_network(raw, strict=False):
                    return True
            except ValueError:
                continue
            continue
        if lowered.startswith("*."):
            suffix = lowered[1:]
            if host.endswith(suffix) or host == lowered[2:]:
                return True
            continue
        if lowered.startswith("."):
            if host.endswith(lowered) or host == lowered[1:]:
                return True
            continue
        if host == lowered or host.endswith("." + lowered):
            return True
    return False


def proxy_url_for_remote(settings: SystemProxySettings, remote_url: str) -> str | None:
    """Pick http/https/socks proxy URL for ``remote_url``'s scheme."""
    scheme = (urlsplit(remote_url).scheme or "").lower()
    if scheme == "https":
        return settings.https or settings.http or settings.socks
    if scheme == "http":
        return settings.http or settings.socks
    return None


def _proxy_url(scheme: str, host: str, port: int) -> str | None:
    host = (host or "").strip().strip("'\"")
    if not host:
        return None
    if "://" in host:
        parsed = urlsplit(host)
        if parsed.port:
            return host
        return f"{host}:{port}" if port else host
    if " " in host and ":" not in host.split()[-1]:
        parts = host.split()
        if len(parts) >= 2 and parts[-1].isdigit():
            host = parts[0]
            port = int(parts[-1])
    if ":" in host.rsplit("@", 1)[-1] and host.rsplit(":", 1)[-1].isdigit():
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def gnome_proxy_settings(
    *,
    mode: str,
    http_host: str = "",
    http_port: int = 8080,
    http_enabled: bool = True,
    https_host: str = "",
    https_port: int = 8080,
    socks_host: str = "",
    socks_port: int = 1080,
    ignore_hosts: list[str] | None = None,
    use_same_proxy: bool = True,
    pac_url: str = "",
) -> SystemProxySettings:
    """Build settings from already-parsed GNOME `org.gnome.system.proxy` values."""
    http = _proxy_url("http", http_host, int(http_port or 8080)) if http_enabled else None
    https = _proxy_url("http", https_host, int(https_port or 8080))
    if use_same_proxy and not https:
        https = http
    socks = _proxy_url("socks5", socks_host, int(socks_port or 1080))
    return SystemProxySettings(
        mode=(mode or "none").strip().strip("'\"").lower(),
        http=http,
        https=https,
        socks=socks,
        ignore_hosts=list(ignore_hosts or []),
        pac_url=pac_url or None,
    )


def parse_kioslaverc(text: str) -> SystemProxySettings | None:
    """Parse KDE `~/.config/kioslaverc` ``[Proxy Settings]``."""
    section: dict[str, str] = {}
    in_proxy = False
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_proxy = line[1:-1].strip().lower() == "proxy settings"
            continue
        if not in_proxy or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = re.sub(r"\[.*\]$", "", key).strip()
        section[key] = value.strip()
    if not section:
        return None
    proxy_type = (section.get("ProxyType") or "0").strip()
    mode_map = {"0": "none", "1": "manual", "2": "auto", "3": "auto", "4": "none"}
    mode = mode_map.get(proxy_type, "none")
    no_proxy = section.get("NoProxyFor") or section.get("noProxyFor") or ""
    ignore = [part.strip() for part in no_proxy.split(",") if part.strip()]
    return SystemProxySettings(
        mode=mode,
        http=_kde_proxy_value(section.get("httpProxy") or section.get("HttpProxy")),
        https=_kde_proxy_value(section.get("httpsProxy") or section.get("HttpsProxy")),
        socks=_kde_proxy_value(section.get("socksProxy") or section.get("SocksProxy"), default_scheme="socks5"),
        ignore_hosts=ignore,
        pac_url=(section.get("Proxy Config Script") or section.get("ProxyConfigScript") or "") or None,
    )


def _kde_proxy_value(raw: str | None, *, default_scheme: str = "http") -> str | None:
    if not raw:
        return None
    value = raw.strip().strip("'\"")
    if not value or value in {"None", "none", "DIRECT"}:
        return None
    if "://" in value:
        parsed = urlsplit(value)
        if parsed.port or ":" in (parsed.netloc or ""):
            return value
        return value
    if " " in value:
        host, _, port = value.partition(" ")
        if port.strip().isdigit():
            return _proxy_url(default_scheme, host.strip(), int(port.strip()))
    if ":" in value.rsplit("@", 1)[-1] and value.rsplit(":", 1)[-1].isdigit():
        return f"{default_scheme}://{value}"
    return None


def _gsettings_get(schema: str, key: str) -> str | None:
    try:
        result = subprocess.run(
            ["gsettings", "get", schema, key],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def read_gnome_proxy_settings(getter=None) -> SystemProxySettings | None:
    """Read `org.gnome.system.proxy` via ``gsettings`` (safe off the GTK thread)."""
    get = getter or _gsettings_get
    mode_raw = get("org.gnome.system.proxy", "mode")
    if mode_raw is None:
        return None
    mode = str(parse_gvariant(mode_raw) or "none")
    ignore_raw = get("org.gnome.system.proxy", "ignore-hosts") or "[]"
    ignore = parse_gvariant(ignore_raw)
    if not isinstance(ignore, list):
        ignore = []
    same_raw = get("org.gnome.system.proxy", "use-same-proxy")
    use_same = parse_gvariant(same_raw) if same_raw is not None else True
    if not isinstance(use_same, bool):
        use_same = str(use_same).lower() != "false"
    pac_raw = get("org.gnome.system.proxy", "autoconfig-url") or ""
    http_host = str(parse_gvariant(get("org.gnome.system.proxy.http", "host") or "") or "")
    http_port = parse_gvariant(get("org.gnome.system.proxy.http", "port") or "8080") or 8080
    enabled_raw = get("org.gnome.system.proxy.http", "enabled")
    http_enabled = parse_gvariant(enabled_raw) if enabled_raw is not None else True
    if not isinstance(http_enabled, bool):
        http_enabled = str(http_enabled).lower() != "false"
    https_host = str(parse_gvariant(get("org.gnome.system.proxy.https", "host") or "") or "")
    https_port = parse_gvariant(get("org.gnome.system.proxy.https", "port") or "8080") or 8080
    socks_host = str(parse_gvariant(get("org.gnome.system.proxy.socks", "host") or "") or "")
    socks_port = parse_gvariant(get("org.gnome.system.proxy.socks", "port") or "1080") or 1080
    try:
        http_port = int(http_port)
    except (TypeError, ValueError):
        http_port = 8080
    try:
        https_port = int(https_port)
    except (TypeError, ValueError):
        https_port = 8080
    try:
        socks_port = int(socks_port)
    except (TypeError, ValueError):
        socks_port = 1080
    return gnome_proxy_settings(
        mode=mode,
        http_host=http_host,
        http_port=http_port,
        http_enabled=bool(http_enabled),
        https_host=https_host,
        https_port=https_port,
        socks_host=socks_host,
        socks_port=socks_port,
        ignore_hosts=[str(item) for item in ignore],
        use_same_proxy=bool(use_same),
        pac_url=str(parse_gvariant(pac_raw) or ""),
    )


def read_kde_proxy_settings(text: str | None = None) -> SystemProxySettings | None:
    if text is None:
        config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        path = os.path.join(config_home, "kioslaverc")
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            return None
    return parse_kioslaverc(text)


def _read_linux_system_proxy_uncached() -> SystemProxySettings | None:
    gnome = read_gnome_proxy_settings()
    if gnome is not None and gnome.mode == "manual":
        return gnome
    kde = read_kde_proxy_settings()
    if kde is not None and kde.mode == "manual":
        return kde
    return None


def read_linux_system_proxy() -> SystemProxySettings | None:
    """Cached GNOME/KDE manual proxy. ``mode=auto`` PAC JS is not evaluated."""
    global _CACHE
    now = time.monotonic()
    if _CACHE is not None and now - _CACHE[0] < _CACHE_TTL:
        return _CACHE[1]
    value = _read_linux_system_proxy_uncached()
    _CACHE = (now, value)
    return value
