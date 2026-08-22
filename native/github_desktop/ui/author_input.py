"""Desktop `AuthorInput` / `AuthorHandle`: co-author chips with autocomplete."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from ..email import legacy_stealth_email_for_user
from ..models import Author, parse_co_authors
from .autocompletion import (
    SEARCH_FOR_USER,
    announce_autocompletion_suggestions,
    fill_coauthor_store,
    widget_should_announce_suggestions,
)

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


def get_email_address_for_user(user: dict[str, Any], endpoint: str = "") -> str:
    """Desktop `getEmailAddressForUser`: public email, else legacy stealth email."""
    email = str(user.get("email") or "")
    if email:
        return email
    login = str(user.get("username") or user.get("login") or "")
    host = endpoint or str(user.get("endpoint") or "")
    return legacy_stealth_email_for_user(login, host)


getEmailAddressForUser = get_email_address_for_user


def author_from_user_hit(user: dict[str, Any]) -> Author:
    """Desktop `authorFromUserHit`."""
    login = str(user.get("username") or user.get("login") or "")
    name = str(user.get("name") or login)
    return Author(
        name=name,
        email=get_email_address_for_user(user),
        username=login or None,
        unknown=False,
    )


authorFromUserHit = author_from_user_hit


def unknown_author_from_username(username: str, *, state: str = "searching") -> Author:
    """Desktop unknown-user hit → `UnknownAuthor` with `state: 'searching'`."""
    login = (username or "").lstrip("@").strip()
    return Author(name=login, email="", username=login or None, unknown=True, state=state)


def update_unknown_author(authors: list[Author], author: Author) -> list[Author]:
    """Desktop `AuthorInput.updateUnknownAuthor`."""
    key = (author.username or "").lower()
    return [
        author if (item.username or "").lower() == key and not is_known_author(item) else item
        for item in authors
    ]


updateUnknownAuthor = update_unknown_author


def apply_unknown_author_search_result(
    authors: list[Author],
    unknown: Author,
    hit: Author | None,
) -> list[Author]:
    """Apply Desktop `attemptUnknownAuthorSearch` once `exactMatch` returns."""
    if hit is None or not is_known_author(hit):
        return update_unknown_author(authors, replace(unknown, state="error", unknown=True))
    return update_unknown_author(authors, hit)


def bind_store_exact_match(store: Any) -> Callable[[str, Callable[[Author | None], None]], None]:
    """Wire Desktop `UserAutocompletionProvider.exactMatch` through `AppStore._run_ui`."""

    def exact_match(login: str, done: Callable[[Author | None], None]) -> None:
        def work() -> dict | None:
            return store.exact_match(login)

        def finished(exc: BaseException | None, result: dict | None = None) -> None:
            done(None if exc or not result else author_from_user_hit(result))

        store._run_ui(work, finished)

    return exact_match


class AuthorInput(Gtk.Box):
    """Chip list plus an autocompleting entry, matching Desktop's AuthorInput."""

    def __init__(
        self,
        on_changed: Callable[[list[Author]], None] | None = None,
        *,
        get_state: Callable[[], Any] | None = None,
        exclude_login: Callable[[], str | None] | None = None,
        get_endpoint: Callable[[], str] | None = None,
        exact_match: Callable[[str, Callable[[Author | None], None]], None] | None = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.add_css_class("author-input-component")
        self._on_changed = on_changed
        self._get_state = get_state
        self._exclude_login = exclude_login
        self._get_endpoint = get_endpoint
        self._exact_match = exact_match
        self._authors: list[Author] = []
        self._updating = False
        self._last_action_description: str | None = None
        self._suggestions_tracker: dict[str, object] = {}
        # display, kind, username, name, email
        self.store = Gtk.ListStore(str, str, str, str, str)
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
        completion.set_match_func(lambda *_args: True)
        self.entry.set_completion(completion)
        self.entry.connect("activate", lambda *_: self.commit_pending())
        self.entry.connect("changed", lambda *_: self.refresh_completion())
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
            self.refresh_completion()
        finally:
            self._updating = False

    def refresh_completion(self) -> None:
        """Populate hits like Desktop `alwaysAutocomplete` + `CoAuthorAutocompletionProvider`."""
        state = self._get_state() if self._get_state is not None else None
        text = self.entry.get_text().strip()
        query = text[1:] if text.startswith("@") else text
        exclude = self._exclude_login() if self._exclude_login is not None else None
        endpoint = self._get_endpoint() if self._get_endpoint is not None else ""
        already = [author.username for author in self._authors if author.username]
        count = fill_coauthor_store(
            self.store,
            state,
            query=query,
            include_unknown_user=True,
            exclude_login=exclude,
            exclude_usernames=already,
            endpoint=endpoint,
        )
        if widget_should_announce_suggestions(self.entry):
            announce_autocompletion_suggestions(
                self.entry,
                count,
                rangeText=query,
                tracker=self._suggestions_tracker,
            )

    def commit_pending(self) -> None:
        text = self.entry.get_text().strip().strip(",")
        if not text:
            return
        for author in parse_co_authors(text):
            self._add_parsed_author(author)
        self.entry.set_text("")
        self.refresh_completion()

    def _on_autocomplete_item_selected(self, item: dict[str, Any]) -> None:
        """Desktop `onAutocompleteItemSelected`."""
        if item.get("kind") == "known-user":
            author = author_from_user_hit(item)
        else:
            author = unknown_author_from_username(str(item.get("username") or ""))
        self._add_author(author)
        action = f"Added {author.username}"
        if is_known_author(author):
            action += f" ({author.name})"
        else:
            self.attempt_unknown_author_search(author)
        self._last_action_description = action
        self.entry.set_text("")
        self.refresh_completion()

    onAutocompleteItemSelected = _on_autocomplete_item_selected

    def attempt_unknown_author_search(self, author: Author) -> None:
        """Desktop `attemptUnknownAuthorSearch`."""
        login = (author.username or "").lstrip("@")
        if not login:
            return
        known = next(
            (
                item
                for item in self._authors
                if is_known_author(item) and (item.username or "").lower() == login.lower()
            ),
            None,
        )
        if known is not None:
            self.update_unknown_author(known)
            return
        if self._exact_match is None:
            self.update_unknown_author(replace(author, username=login, unknown=True, state="error"))
            return

        def done(found: Author | None) -> None:
            if found is None or not is_known_author(found):
                self.update_unknown_author(replace(author, username=login, unknown=True, state="error"))
                self._last_action_description = f"Error: user {login} not found"
                return
            self.update_unknown_author(found)

        self._exact_match(login, done)

    attemptUnknownAuthorSearch = attempt_unknown_author_search

    def update_unknown_author(self, author: Author) -> None:
        """Desktop `updateUnknownAuthor`."""
        self._authors = update_unknown_author(self._authors, author)
        self._rebuild_chips()
        self._emit()

    def _add_parsed_author(self, author: Author) -> None:
        if not is_known_author(author):
            author = replace(author, state="searching", unknown=True)
        self._add_author(author)
        if not is_known_author(author):
            self.attempt_unknown_author_search(author)

    def _add_author(self, author: Author) -> None:
        if author.username:
            key = author.username.lower()
            for index, existing in enumerate(self._authors):
                if (existing.username or "").lower() == key:
                    if is_known_author(author) and not is_known_author(existing):
                        self._authors[index] = author
                        self._rebuild_chips()
                        self._emit()
                    return
        self._authors.append(author)
        self._rebuild_chips()
        self._emit()

    def _on_match_selected(self, _completion, model, it) -> bool:
        self._on_autocomplete_item_selected(self._hit_from_iter(model, it))
        return True

    def _hit_from_iter(self, model, it) -> dict[str, Any]:
        if model.get_n_columns() >= 5:
            kind = model.get_value(it, 1) or "unknown-user"
            username = model.get_value(it, 2) or ""
            name = model.get_value(it, 3) or ""
            email = model.get_value(it, 4) or ""
            return {"kind": kind, "username": username, "name": name or None, "email": email}
        display = str(model.get_value(it, 0) or "")
        if SEARCH_FOR_USER in display:
            username = display.split(SEARCH_FOR_USER, 1)[0].strip().lstrip("@")
            return {"kind": "unknown-user", "username": username}
        from ..models import parse_name_email

        if "<" in display:
            name, email = parse_name_email(display)
            return {"kind": "known-user", "username": "", "name": name, "email": email}
        login = display.split()[0].lstrip("@") if display else ""
        return {"kind": "unknown-user", "username": login}

    def _on_key(self, _controller, keyval: int, _keycode: int, _state: Gdk.ModifierType) -> bool:
        if keyval in (Gdk.KEY_comma, Gdk.KEY_semicolon):
            self.commit_pending()
            return True
        if keyval == Gdk.KEY_space:
            text = self.entry.get_text()
            if self.entry.get_position() == len(text) and text.strip():
                username = text.strip().lstrip("@")
                self._on_autocomplete_item_selected({"kind": "unknown-user", "username": username})
                return True
        if keyval == Gdk.KEY_BackSpace and not self.entry.get_text() and self._authors:
            self._authors.pop()
            self._rebuild_chips()
            self._emit()
            self.refresh_completion()
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
            self.refresh_completion()

    def _emit(self) -> None:
        if not self._updating and self._on_changed is not None:
            self._on_changed(self.get_authors())


def author_from_mentionable(user: dict, endpoint: str = "") -> Author:
    hit = dict(user)
    if endpoint and not hit.get("endpoint"):
        hit["endpoint"] = endpoint
    if "username" not in hit and hit.get("login"):
        hit["username"] = hit["login"]
        hit["kind"] = "known-user"
    return author_from_user_hit(hit)


def display_author(author: Author) -> str:
    """Presentation helper used by tests; chip labels use `getDisplayTextForAuthor`."""
    return get_display_text_for_author(author)
