"""Linux system proxy, PAC strings, and notify-send click-open."""

from __future__ import annotations

from github_desktop.git.ops import env_for_proxy
from github_desktop.linux_proxy import (
    gnome_proxy_settings,
    host_matches_no_proxy,
    parse_gvariant,
    parse_kioslaverc,
    proxy_url_for_remote,
)
from github_desktop.notifications import NOTIFY_SEND_DEFAULT_ACTION, notify_send_command
from github_desktop.parse_pac import parse_pac_string


def test_parse_pac_string_matches_desktop() -> None:
    assert parse_pac_string("DIRECT") is None
    assert parse_pac_string("PROXY myproxy:80;DIRECT") == ["http://myproxy:80"]
    assert parse_pac_string("PROXY myproxy:80") == ["http://myproxy:80"]
    assert parse_pac_string("PROXY myproxy:80; HTTPS secureproxy:443") == [
        "http://myproxy:80",
        "https://secureproxy:443",
    ]
    assert parse_pac_string(
        "PROXY a:1;HTTP b:2;HTTPS c:3;SOCKS d:4;SOCKS4 e:5;SOCKS5 f:5;DIRECT"
    ) == [
        "http://a:1",
        "http://b:2",
        "https://c:3",
        "socks4://d:4",
        "socks4://e:5",
        "socks5://f:5",
    ]
    assert parse_pac_string(
        "PROXY a:1; HTTP b:2 ;\tHTTPS c:3\t;\tSOCKS d:4 ; SOCKS4 e:5  ;  SOCKS5 f:5  ; DIRECT"
    ) == [
        "http://a:1",
        "http://b:2",
        "https://c:3",
        "socks4://d:4",
        "socks4://e:5",
        "socks5://f:5",
    ]
    assert parse_pac_string("QUIC qhost:1;PROXY phost:2;DIRECT") == ["http://phost:2"]
    assert parse_pac_string("PROXY;HTTPS;DIRECT") is None


def test_parse_gvariant_and_host_ignore() -> None:
    assert parse_gvariant("'manual'") == "manual"
    assert parse_gvariant("uint32 8080") == 8080
    assert parse_gvariant("['localhost', '127.0.0.0/8', '::1']") == [
        "localhost",
        "127.0.0.0/8",
        "::1",
    ]
    ignore = ["localhost", "127.0.0.0/8", "::1", "*.internal"]
    assert host_matches_no_proxy("localhost", ignore)
    assert host_matches_no_proxy("127.0.0.1", ignore)
    assert host_matches_no_proxy("foo.internal", ignore)
    assert not host_matches_no_proxy("github.com", ignore)


def test_gnome_manual_proxy_for_https() -> None:
    settings = gnome_proxy_settings(
        mode="manual",
        http_host="proxy.example",
        http_port=8080,
        ignore_hosts=["localhost"],
    )
    assert proxy_url_for_remote(settings, "https://github.com/a/b.git") == "http://proxy.example:8080"
    assert proxy_url_for_remote(settings, "http://example.com") == "http://proxy.example:8080"


def test_kioslaverc_manual_proxy() -> None:
    text = """
[Proxy Settings]
ProxyType=1
httpProxy=http://kde.example:3128
httpsProxy=http://kde.example:3128
socksProxy=socks://kde.example:1080
NoProxyFor=localhost,127.0.0.1
"""
    settings = parse_kioslaverc(text)
    assert settings is not None
    assert settings.mode == "manual"
    assert settings.http == "http://kde.example:3128"
    assert "localhost" in settings.ignore_hosts


def test_env_for_proxy_uses_system_proxy_and_no_proxy(monkeypatch) -> None:
    from github_desktop.git import runner as runner_mod
    from github_desktop.linux_proxy import SystemProxySettings

    settings = SystemProxySettings(
        mode="manual",
        http="http://corp.example:8080",
        https="http://corp.example:8080",
        ignore_hosts=["localhost", "127.0.0.0/8"],
    )
    monkeypatch.setattr(runner_mod, "read_linux_system_proxy", lambda: settings)
    monkeypatch.setattr(runner_mod, "_git_config_http_proxy", lambda: "http://git-config:1")
    result = env_for_proxy("https://github.com/a/b.git", env={})
    assert result["https_proxy"] == "http://corp.example:8080"
    assert result["no_proxy"] == "localhost,127.0.0.0/8"
    assert env_for_proxy("https://localhost/repo.git", env={}) == {}


def test_notify_send_command_includes_click_action() -> None:
    plain = notify_send_command("Title", "Body")
    assert plain == ["notify-send", "Title", "Body"]
    clickable = notify_send_command("Title", "Body", with_action=True)
    assert "--wait" in clickable
    assert f"--action={NOTIFY_SEND_DEFAULT_ACTION}:Open" in clickable
    assert clickable[-2:] == ["Title", "Body"]
