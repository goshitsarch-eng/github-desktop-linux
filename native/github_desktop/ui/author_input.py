"""Desktop `AuthorInput` / `AuthorHandle`: co-author chips with autocomplete."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from ..models import Author, parse_co_authors, parse_name_email


class AuthorInput(Gtk.Box):
    """Chip list plus an autocompleting entry, matching Desktop's AuthorInput."""

    def __init__(self, on_changed: Callable[[list[Author]], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._on_changed = on_changed
        self._authors: list[Author] = []
        self._updating = False
        self.store = Gtk.ListStore(str)
        self._chips = Gtk.FlowBox()
        self._chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self._chips.set_max_children_per_line(6)
        self._chips.add_css_class("co-author-chips")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Co-Author")
        self.entry.set_hexpand(True)
        completion = Gtk.EntryCompletion()
        completion.set_model(self.store)
        completion.set_text_column(0)
        completion.set_minimum_key_length(1)
        completion.set_inline_completion(False)
        completion.set_popup_completion(True)
        self.entry.set_completion(completion)
        self.entry.connect("activate", lambda *_: self.commit_pending())
        completion.connect("match-selected", self._on_match_selected)
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_key)
        self.entry.add_controller(controller)
        self.append(self._chips)
        self.append(self.entry)

    def get_authors(self) -> list[Author]:
        return list(self._authors)

    def get_pending_text(self) -> str:
        return self.entry.get_text().strip()

    def set_authors(self, authors: list[Author]) -> None:
        self._updating = True
        try:
            self._authors = list(authors)
            self._rebuild_chips()
        finally:
            self._updating = False

    def commit_pending(self) -> None:
        text = self.entry.get_text().strip().strip(",")
        if not text:
            return
        for author in parse_co_authors(text):
            if not any(a.email == author.email and a.name == author.name for a in self._authors):
                self._authors.append(author)
        self.entry.set_text("")
        self._rebuild_chips()
        self._emit()

    def _on_match_selected(self, _completion, model, it) -> bool:
        text = model.get_value(it, 0)
        self.entry.set_text(text)
        self.commit_pending()
        return True

    def _on_key(self, _controller, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        if keyval in (Gdk.KEY_comma, Gdk.KEY_semicolon):
            self.commit_pending()
            return True
        if keyval == Gdk.KEY_BackSpace and not self.entry.get_text() and self._authors:
            self._authors.pop()
            self._rebuild_chips()
            self._emit()
            return True
        return False

    def _rebuild_chips(self) -> None:
        while (child := self._chips.get_first_child()) is not None:
            self._chips.remove(child)
        for index, author in enumerate(self._authors):
            self._chips.insert(self._chip(author, index), -1)

    def _chip(self, author: Author, index: int) -> Gtk.Widget:
        chip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        chip.add_css_class("co-author")
        chip.add_css_class("co-author-chip")
        if author.unknown or not author.email:
            chip.add_css_class("unknown")
        handle = f"@{author.username}" if author.username and not author.email else ""
        label = handle or (f"{author.name} <{author.email}>" if author.email else author.name)
        chip.append(Gtk.Label(label=label))
        remove = Gtk.Button(icon_name="window-close-symbolic")
        remove.add_css_class("flat")
        remove.add_css_class("circular")
        remove.set_tooltip_text("Remove co-author")
        remove.connect("clicked", lambda *_a, i=index: self._remove(i))
        chip.append(remove)
        return chip

    def _remove(self, index: int) -> None:
        if 0 <= index < len(self._authors):
            self._authors.pop(index)
            self._rebuild_chips()
            self._emit()

    def _emit(self) -> None:
        if not self._updating and self._on_changed is not None:
            self._on_changed(self.get_authors())


def author_from_mentionable(user: dict) -> Author:
    login = str(user.get("login") or "")
    name = str(user.get("name") or login)
    email = str(user.get("email") or "")
    if not email and login:
        email = f"{login}@users.noreply.github.com"
    return Author(name=name, email=email, username=login or None)


def display_author(author: Author) -> str:
    name, email = parse_name_email(f"{author.name} <{author.email}>") if author.email else (author.name, "")
    if author.username and not email:
        return f"@{author.username}"
    if email:
        return f"{name} <{email}>"
    return name
