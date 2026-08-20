"""Desktop-style # / @ / : autocompletion for commit summary and description.

Ports `app/src/ui/autocompletion/` so the Changes commit box and the squash/amend
`COMMIT_MESSAGE` dialog share the same token matching and insert behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from .emoji import emoji_map, matching_shortcodes

# Desktop `DefaultMaxHits` in `ui/autocompletion/common.ts`.
DefaultMaxHits = 25

SUMMARY_LENGTH_HINT = (
    "Great commit summaries contain fewer than 50 characters. "
    "Place extra information in the description field."
)

UNREACHABLE_COMMITS_LEARN_MORE = (
    "https://github.com/desktop/desktop/blob/development/docs/learn-more/unreachable-commits.md"
)


def token_before_cursor(text: str, pos: int) -> str:
    prefix = text[: max(0, pos)]
    if not prefix:
        return ""
    for index in range(len(prefix) - 1, -1, -1):
        if prefix[index] in " \t\n":
            return prefix[index + 1 :]
    return prefix


def token_from_line_prefix(prefix: str) -> tuple[str, int]:
    """Return `(token, start_offset)` for the token at the end of a line prefix."""
    if not prefix:
        return "", 0
    cut = 0
    for index in range(len(prefix) - 1, -1, -1):
        if prefix[index] in " \t":
            cut = index + 1
            break
    return prefix[cut:], cut


def completion_insert_text(display: str) -> str:
    """Text inserted when a hit is chosen (`getCompletionText` in Desktop)."""
    text = display.strip()
    if not text:
        return ""
    token = text.split()[0]
    if token.startswith("#") or token.startswith("@"):
        return token
    if token.startswith(":"):
        code = token.strip(":")
        return emoji_map().get(code) or token
    return token


def summary_length_hint(text: str, enabled: bool) -> str | None:
    if enabled and len(text) > 50:
        return SUMMARY_LENGTH_HINT
    return None


def write_access_warning(repo: Any) -> str | None:
    github = getattr(repo, "github", None) if repo is not None else None
    if github is not None and getattr(github, "permissions", None) == "read":
        name = getattr(repo, "name", "") or "this repository"
        return f"You don't have write access to {name}. Want to create a fork?"
    return None


def protected_branch_warning(state: Any) -> str | None:
    if state is None or not getattr(state, "current_branch_protected", False):
        return None
    status = getattr(state, "status", None)
    branch = getattr(status, "current_branch", None) if status is not None else None
    if not branch:
        return None
    return f"{branch} is a protected branch. Want to switch branches?"


def unreachable_commits_message(*, unreachable_tab: bool, count: int) -> str:
    commits = "commits" if count != 1 else "commit"
    pronoun = "they're" if count != 1 else "it's"
    if unreachable_tab:
        return (
            f"You will not see changes from the following {commits} because {pronoun} "
            "not in the ancestry path of the most recent commit in your selection."
        )
    return (
        f"You will see changes from the following {commits} because {pronoun} "
        "in the ancestry path of the most recent commit in your selection."
    )


def fill_coauthor_store(list_store: Gtk.ListStore, state: Any) -> None:
    list_store.clear()
    if state is None:
        return
    seen: set[str] = set()
    for user in getattr(state, "mentionables", None) or []:
        login = str(user.get("login") or "")
        if not login or login in seen:
            continue
        seen.add(login)
        name = str(user.get("name") or login)
        email = str(user.get("email") or f"{login}@users.noreply.github.com")
        list_store.append([f"{name} <{email}>"])
        list_store.append([f"@{login}"])
    for login in getattr(state, "mentions", None) or []:
        if login and login not in seen:
            list_store.append([f"@{login}"])


def completion_matches(
    state: Any,
    token: str,
    *,
    max_hits: int = DefaultMaxHits,
    exclude_login: str | None = None,
) -> list[str]:
    if state is None or len(token) < 1 or token[0] not in "#@:":
        return []
    matches: list[str] = []
    if token.startswith("#"):
        needle = token[1:].lower()
        issues = list(getattr(state, "issues", None) or [])
        if not needle:
            issues = sorted(issues, key=lambda item: item[0], reverse=True)
            matches = [f"#{number} {title}" for number, title in issues[:max_hits]]
        else:
            ranked: list[tuple[int, str, str]] = []
            for number, title in issues:
                hay = f"{number} {title}".lower()
                index = hay.find(needle)
                if index >= 0:
                    ranked.append((index, str(title), f"#{number} {title}"))
            ranked.sort(key=lambda item: (item[0], item[1].lower()))
            matches = [item[2] for item in ranked[:max_hits]]
    elif token.startswith("@"):
        needle = token[1:].lower()
        skip = (exclude_login or "").lower()
        seen: set[str] = set()
        mentionables = list(getattr(state, "mentionables", None) or [])
        if mentionables:
            for user in mentionables:
                login = str(user.get("login") or "")
                if not login or login.lower() == skip or login.lower() in seen:
                    continue
                name = str(user.get("name") or "")
                hay = f"{login} {name}".lower()
                if needle and needle not in hay:
                    continue
                seen.add(login.lower())
                display = f"@{login} {name}".strip() if name and name != login else f"@{login}"
                matches.append(display)
                if len(matches) >= max_hits:
                    break
        else:
            for login in getattr(state, "mentions", None) or []:
                if not login or login.lower() == skip or login.lower() in seen:
                    continue
                if needle and not login.lower().startswith(needle):
                    continue
                seen.add(login.lower())
                matches.append(f"@{login}")
                if len(matches) >= max_hits:
                    break
    elif token.startswith(":"):
        matches.extend(matching_shortcodes(token, limit=max_hits))
    return matches


def populate_completion_store(
    list_store: Gtk.ListStore,
    state: Any,
    token: str,
    *,
    exclude_login: str | None = None,
) -> None:
    list_store.clear()
    for item in completion_matches(state, token, exclude_login=exclude_login):
        list_store.append([item])


def replace_entry_token(entry: Gtk.Entry, insert: str) -> None:
    text = entry.get_text()
    pos = entry.get_position()
    token = token_before_cursor(text, pos)
    start = max(0, pos - len(token))
    new = text[:start] + insert + " " + text[pos:]
    entry.set_text(new)
    entry.set_position(start + len(insert) + 1)


def replace_textview_token(textview: Gtk.TextView, insert: str) -> None:
    buf = textview.get_buffer()
    cursor = buf.get_iter_at_mark(buf.get_insert())
    start = cursor.copy()
    start.set_line_offset(0)
    prefix = buf.get_text(start, cursor, True)
    _token, cut = token_from_line_prefix(prefix)
    replace = cursor.copy()
    replace.set_line_offset(cut)
    buf.delete(replace, cursor)
    buf.insert(replace, insert + " ")


def _on_entry_match_selected(completion: Gtk.EntryCompletion, model, it) -> bool:
    display = model.get_value(it, 0)
    insert = completion_insert_text(display)
    entry = completion.get_entry()
    if entry is None or not insert:
        return False
    replace_entry_token(entry, insert)
    return True


def install_entry_completion(entry: Gtk.Entry) -> Gtk.ListStore:
    """Attach a popup completion that replaces only the current `#` / `@` / `:` token."""
    store = Gtk.ListStore(str)
    completion = Gtk.EntryCompletion()
    completion.set_model(store)
    completion.set_text_column(0)
    completion.set_popup_completion(True)
    completion.set_inline_completion(False)
    try:
        completion.set_inline_selection(False)
    except Exception:
        pass
    completion.set_minimum_key_length(1)
    completion.set_match_func(lambda *_args: True)
    completion.connect("match-selected", _on_entry_match_selected)
    entry.set_completion(completion)
    return store


class TextViewCompleter:
    """Popover completion for a multiline commit description, matching Desktop's textarea."""

    def __init__(
        self,
        textview: Gtk.TextView,
        get_state: Callable[[], Any],
        *,
        on_hash: Callable[[], None] | None = None,
        exclude_login: Callable[[], str | None] | None = None,
    ) -> None:
        self.textview = textview
        self.get_state = get_state
        self.on_hash = on_hash
        self.exclude_login = exclude_login
        self.popover = Gtk.Popover()
        self.popover.set_parent(textview)
        self.popover.set_autohide(True)
        self.listbox = Gtk.ListBox()
        self.listbox.connect("row-activated", self._on_row)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(80)
        scroll.set_min_content_width(220)
        scroll.set_child(self.listbox)
        self.popover.set_child(scroll)

    def token(self) -> str:
        buf = self.textview.get_buffer()
        cursor = buf.get_iter_at_mark(buf.get_insert())
        start = cursor.copy()
        start.set_line_offset(0)
        prefix = buf.get_text(start, cursor, True)
        token, _cut = token_from_line_prefix(prefix)
        return token

    def update(self) -> None:
        state = self.get_state()
        token = self.token()
        while (child := self.listbox.get_first_child()) is not None:
            self.listbox.remove(child)
        skip = self.exclude_login() if self.exclude_login else None
        matches = completion_matches(state, token, exclude_login=skip)
        if token.startswith("#") and self.on_hash:
            self.on_hash()
        if not matches:
            self.popover.popdown()
            return
        for item in matches[:12]:
            self.listbox.append(Gtk.Label(label=item, xalign=0))
        self.popover.popup()

    def _on_row(self, _list: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        child = row.get_child()
        text = child.get_text() if isinstance(child, Gtk.Label) else ""
        insert = completion_insert_text(text)
        if not insert:
            return
        replace_textview_token(self.textview, insert)
        self.popover.popdown()
