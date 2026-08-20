"""Circular avatar with initials fallback and optional GitHub/Gravatar image."""

from __future__ import annotations

import os
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from ..avatars import avatar_urls, initials_for

_CACHE: dict[str, Gdk.Texture] = {}
_FAILED: set[str] = set()


def _offline() -> bool:
    if os.environ.get("GITHUB_DESKTOP_OFFLINE") == "1":
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False


class Avatar(Gtk.Overlay):
    def __init__(
        self,
        name: str,
        email: str = "",
        *,
        login: str | None = None,
        avatar_url: str | None = None,
        size: int = 28,
    ) -> None:
        super().__init__()
        self._size = max(16, int(size))
        self.set_size_request(self._size, self._size)
        self.add_css_class("avatar")
        initials = Gtk.Label(label=initials_for(name, email))
        initials.add_css_class("avatar-initials")
        initials.set_hexpand(True)
        initials.set_vexpand(True)
        initials.set_halign(Gtk.Align.FILL)
        initials.set_valign(Gtk.Align.FILL)
        self.set_child(initials)
        self._image = Gtk.Picture()
        self._image.set_can_shrink(True)
        self._image.set_content_fit(Gtk.ContentFit.COVER)
        self._image.set_size_request(self._size, self._size)
        self._image.add_css_class("avatar-image")
        self._image.set_visible(False)
        self.add_overlay(self._image)
        self.set_tooltip_text(name or email or login or "Unknown author")
        if not _offline():
            urls = avatar_urls(email=email, login=login, avatar_url=avatar_url, size=self._size * 2)
            if urls:
                threading.Thread(target=self._fetch, args=(urls,), daemon=True).start()

    def _fetch(self, urls: list[str]) -> None:
        for url in urls:
            if url in _FAILED:
                continue
            texture = _CACHE.get(url)
            if texture is None:
                try:
                    with urllib.request.urlopen(url, timeout=4) as resp:
                        data = resp.read()
                    bytes_data = GLib.Bytes.new(data)
                    texture = Gdk.Texture.new_from_bytes(bytes_data)
                    _CACHE[url] = texture
                except Exception:
                    _FAILED.add(url)
                    continue
            GLib.idle_add(self._apply, texture)
            return

    def _apply(self, texture: Gdk.Texture) -> bool:
        try:
            self._image.set_paintable(texture)
            self._image.set_visible(True)
        except Exception:
            pass
        return False
