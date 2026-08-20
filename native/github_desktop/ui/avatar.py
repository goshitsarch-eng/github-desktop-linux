"""Circular avatar with initials fallback and optional GitHub/Gravatar image."""

from __future__ import annotations

import os
import threading
import urllib.request

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from ..avatars import avatar_urls, ensure_avatar_token, initials_for

_CACHE: dict[str, Gdk.Texture] = {}
_FAILED: set[str] = set()
MAX_DISPLAYED_AVATARS = 3


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
        endpoint: str | None = None,
        account: object | None = None,
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
        self._endpoint = endpoint or getattr(account, "endpoint", None)
        self._account = account
        if not _offline():
            def load() -> None:
                token = ensure_avatar_token(account) if account is not None else None
                urls = avatar_urls(
                    email=email,
                    login=login,
                    avatar_url=avatar_url,
                    size=self._size * 2,
                    endpoint=self._endpoint,
                    avatar_token=token,
                )
                if urls:
                    self._fetch(urls)

            threading.Thread(target=load, daemon=True).start()

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


def users_from_commit(commit: object) -> list[tuple[str, str]]:
    users: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(name: str, email: str) -> None:
        key = (name or "", (email or "").lower())
        if key in seen or not (name or email):
            return
        seen.add(key)
        users.append((name or "", email or ""))

    author = getattr(commit, "author", None)
    if author is not None:
        add(getattr(author, "name", "") or "", getattr(author, "email", "") or "")
    if not getattr(commit, "authored_by_committer", True):
        committer = getattr(commit, "committer", None)
        if committer is not None:
            add(getattr(committer, "name", "") or "", getattr(committer, "email", "") or "")
    for co in getattr(commit, "co_authors", None) or []:
        add(getattr(co, "name", "") or "", getattr(co, "email", "") or "")
    return users


def users_from_commits(commits: list[object]) -> list[tuple[str, str]]:
    users: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        for name, email in users_from_commit(commit):
            key = (name, email.lower())
            if key in seen:
                continue
            seen.add(key)
            users.append((name, email))
    return users


class AvatarStack(Gtk.Box):
    """Stacked avatars matching GitHub Desktop's AvatarStack (max 3 visible + overflow)."""

    def __init__(self, users: list[tuple[str, str]], *, size: int = 28) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add_css_class("avatar-stack")
        self.set_valign(Gtk.Align.CENTER)
        names = [name or email for name, email in users if name or email]
        self.set_tooltip_text(", ".join(names) if names else "")
        extra = max(0, len(users) - MAX_DISPLAYED_AVATARS)
        shown = users[:MAX_DISPLAYED_AVATARS]
        for name, email in shown:
            self.append(Avatar(name, email, size=size))
        if extra:
            more = Gtk.Label(label=f"+{extra}")
            more.add_css_class("avatar-more")
            more.set_size_request(size, size)
            more.set_tooltip_text(f"{extra} more author{'s' if extra != 1 else ''}")
            self.append(more)
