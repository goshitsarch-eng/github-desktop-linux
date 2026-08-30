"""Desktop `AuthorInput` / `AuthorHandle`: co-author chips with autocomplete."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from ..email import legacy_stealth_email_for_user
from ..models import Author

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
