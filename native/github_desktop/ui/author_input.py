"""Desktop `AuthorInput` / `AuthorHandle`: co-author chips with autocomplete."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from ..models import Author, parse_co_authors

# Desktop `AuthorInput` label is always "Co-Authors"; placeholder is "@username".
CO_AUTHORS_LABEL = "Co-Authors"
AUTHOR_INPUT_PLACEHOLDER = "@username"


def is_known_author(author: Author) -> bool:
    """Desktop `isKnownAuthor`."""
    return not author.unknown


isKnownAuthor = is_known_author


def get_full_text_for_author(author: Author) -> str:
    """Desktop `getFullTextForAuthor`."""
    if is_known_author(author):
        return author.name if author.username is None else f"@{author.username} ({author.name})"
    return f"@{author.username}" if author.username else author.name


getFullTextForAuthor = get_full_text_for_author


def get_display_text_for_author(author: Author) -> str:
    """Desktop `getDisplayTextForAuthor`."""
    if is_known_author(author):
        return author.name if author.username is None else f"@{author.username}"
    return f"@{author.username}" if author.username else author.name


getDisplayTextForAuthor = get_display_text_for_author


def author_handle_title(author: Author) -> str | None:
    """Desktop `AuthorHandle.getTitle`."""
    if is_known_author(author):
        return None
    username = author.username or author.name
    if author.state == "error" or author.state is None:
        return f"Could not find user with username {username}"
    return f"Searching for @{username}"


def author_handle_aria_label(author: Author) -> str:
    """Desktop `AuthorHandle.getAriaLabel`."""
    suffix = "press backspace or delete to remove"
    if is_known_author(author):
        return f"{get_full_text_for_author(author)} {suffix}"
    state_aria = "user not found" if author.state == "error" or author.state is None else "searching"
    username = author.username or author.name
    return f"{username}, {state_aria}, {suffix}"


class AuthorInput(Gtk.Box):
    """Chip list plus an autocompleting entry, matching Desktop's AuthorInput."""

    def __init__(self, on_changed: Callable[[list[Author]], None] | None = None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("author-input-component")
        self._on_changed = on_changed
        self._authors: list[Author] = []
        self._updating = False
        self.store = Gtk.ListStore(str)
        self._chips = Gtk.FlowBox()
        self._chips.set_selection_mode(Gtk.SelectionMode.NONE)
        self._chips.set_max_children_per_line(6)
        self._chips.add_css_class("co-author-chips")
        self._chips.add_css_class("added-author-container")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._label = Gtk.Label(label=CO_AUTHORS_LABEL)
        self._label.set_xalign(0)
        self._label.add_css_class("label")
        self._label.add_css_class("author-input-label")
        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text(AUTHOR_INPUT_PLACEHOLDER)
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
        row.append(self._label)
        row.append(self.entry)
        self.append(self._chips)
        self.append(row)

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
        chip.add_css_class("handle")
        if not is_known_author(author) or not author.email:
            chip.add_css_class("unknown")
            if author.state == "searching":
                chip.add_css_class("progress")
            else:
                chip.add_css_class("error")
        label = Gtk.Label(label=get_display_text_for_author(author))
        chip.append(label)
        title = author_handle_title(author)
        chip.set_tooltip_text(title or get_full_text_for_author(author))
        try:
            chip.set_accessible_role(Gtk.AccessibleRole.LIST_ITEM)
            chip.update_property([Gtk.AccessibleProperty.LABEL], [author_handle_aria_label(author)])
        except Exception:
            pass
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
    """Presentation helper used by tests; chip labels use `getDisplayTextForAuthor`."""
    return get_display_text_for_author(author)
