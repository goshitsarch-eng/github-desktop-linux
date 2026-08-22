"""Desktop-style # / @ / : autocompletion for commit summary and description.

Ports `app/src/ui/autocompletion/` so the Changes commit box and the squash/amend
`COMMIT_MESSAGE` dialog share the same token matching and insert behavior.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from .emoji import emoji_map, matching_shortcodes

from .length_hint import SUMMARY_LENGTH_HINT, summary_length_hint

# Desktop `DefaultMaxHits` in `ui/autocompletion/common.ts`.
DefaultMaxHits = 25

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


def _markup_escape(text: str) -> str:
    return GLib.markup_escape_text(text or "")


def write_access_warning_markup(repo: Any) -> str | None:
    """Desktop CommitWarning `onShowCreateForkDialog` link."""
    if write_access_warning(repo) is None:
        return None
    name = getattr(repo, "name", "") or "this repository"
    return (
        f'You don\'t have write access to <b>{_markup_escape(name)}</b>. '
        'Want to <a href="fork">create a fork</a>?'
    )


def protected_branch_warning_markup(state: Any) -> str | None:
    """Desktop CommitWarning `onSwitchBranch` link."""
    if protected_branch_warning(state) is None:
        return None
    status = getattr(state, "status", None)
    branch = getattr(status, "current_branch", None) if status is not None else None
    return (
        f'<b>{_markup_escape(str(branch))}</b> is a protected branch. '
        'Want to <a href="switch">switch branches</a>?'
    )


def signed_commits_warning_markup(branch: str | None, *, can_bypass: bool = False) -> str:
    extra = ", but you can bypass them. Proceed with caution!" if can_bypass else "."
    return (
        f'<a href="rulesets">One or more rules</a> apply to the branch '
        f'<b>{_markup_escape(branch or "")}</b> that require signed commits{extra} '
        '<a href="https://docs.github.com/authentication/managing-commit-signature-verification/signing-commits">'
        "Learn more about commit signing.</a>"
    )


def basic_commit_warning_markup(branch: str, *, can_bypass: bool = False) -> str:
    if can_bypass:
        return (
            f'<a href="rulesets">One or more rules</a> apply to the branch '
            f'<b>{_markup_escape(branch)}</b> that would prevent pushing, but you can bypass them. '
            "Proceed with caution!"
        )
    return (
        f'<a href="rulesets">One or more rules</a> apply to the branch '
        f'<b>{_markup_escape(branch)}</b> that will prevent pushing. '
        'Want to <a href="switch">switch branches</a>?'
    )


def unpublished_branch_rules_warning_markup(branch: str, *, can_bypass: bool = False) -> str:
    if can_bypass:
        return (
            f'The branch name <b>{_markup_escape(branch)}</b> fails '
            '<a href="rulesets">one or more rules</a> that would prevent it from being published, '
            "but you can bypass them. Proceed with caution!"
        )
    return (
        f'The branch name <b>{_markup_escape(branch)}</b> fails '
        '<a href="rulesets">one or more rules</a> that will prevent it from being published. '
        'Want to <a href="switch">switch branches</a>?'
    )


def branch_protections_repo_rules_commit_warning_markups(
    repo: Any,
    state: Any,
    *,
    repo_rules_enabled: bool = True,
) -> list[str]:
    """Desktop `renderBranchProtectionsRepoRulesCommitWarning` (exclusive)."""
    fork = write_access_warning_markup(repo)
    if fork:
        return [fork]
    protected = protected_branch_warning_markup(state)
    if protected:
        return [protected]
    if not repo_rules_enabled or state is None:
        return []
    rules = getattr(state, "repo_rules", None)
    if rules is None:
        return []
    status = getattr(state, "status", None)
    branch = getattr(status, "current_branch", None) if status is not None else None
    unpublished = getattr(state, "ahead_behind", None) is None
    if unpublished and branch:
        name_fail = rules.branch_name_patterns.get_failed_rules(branch)
        if rules.creation_restricted is True or name_fail.status == "fail":
            return [unpublished_branch_rules_warning_markup(branch, can_bypass=False)]
        if rules.creation_restricted == "bypass" or name_fail.status == "bypass":
            return [unpublished_branch_rules_warning_markup(branch, can_bypass=True)]
    if rules.signed_commits_required is True:
        return [signed_commits_warning_markup(branch, can_bypass=False)]
    if rules.signed_commits_required == "bypass":
        return [signed_commits_warning_markup(branch, can_bypass=True)]
    if rules.basic_commit_warning is True and branch:
        return [basic_commit_warning_markup(branch, can_bypass=False)]
    if rules.basic_commit_warning == "bypass" and branch:
        return [basic_commit_warning_markup(branch, can_bypass=True)]
    return []


renderBranchProtectionsRepoRulesCommitWarning = branch_protections_repo_rules_commit_warning_markups
onShowCreateForkDialog = write_access_warning_markup
onSwitchBranch = protected_branch_warning_markup


def commit_warning_label(markup: str, store: Any) -> Gtk.Label:
    label = Gtk.Label(wrap=True, xalign=0, use_markup=True)
    label.set_markup(markup)
    label.add_css_class("warning")
    label.connect("activate-link", lambda _widget, uri: handle_commit_warning_uri(store, uri))
    return label


def fill_commit_warning_box(box: Gtk.Box, markups: Sequence[str], store: Any) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt
    for markup in markups:
        box.append(commit_warning_label(markup, store))
    box.set_visible(bool(markups))


def handle_commit_warning_uri(store: Any, uri: str) -> bool:
    """Desktop `onShowCreateForkDialog` / `onSwitchBranch` / ruleset and http links."""
    from ..models import FoldoutType, PopupType
    from ..shells import open_external

    if uri == "fork":
        store.show_popup(PopupType.CREATE_FORK)
        return True
    if uri == "switch":
        store.show_foldout(FoldoutType.BRANCH)
        return True
    if uri == "stop-amend":
        repo = store.selected_repository
        if repo is not None:
            store.stop_amending(repo)
        return True
    if uri == "rulesets":
        repo = store.selected_repository
        if repo is not None and repo.github:
            from ..github.repo_rules import rulesets_url_for_branch

            state = store.state_for(repo)
            branch = state.status.current_branch if state.status else None
            href = rulesets_url_for_branch(repo.github, branch)
            if href:
                open_external(href)
        return True
    if uri.startswith("http://") or uri.startswith("https://"):
        open_external(uri)
        return True
    return False


def committing_just_now_message(summary: str, short_sha: str) -> str:
    """Desktop `isCommittingStatusMessage` after a successful commit."""
    return f"Committed Just now - {summary} (Sha: {short_sha})"


def get_button_title(
    *,
    amending: bool = False,
    committing: bool = False,
    branch: str | None = None,
) -> str:
    """Desktop `getButtonTitle`."""
    if amending:
        verb = "Amending" if committing else "Amend"
        return f"{verb} last commit"
    verb = "Committing" if committing else "Commit"
    if not branch:
        return verb
    return f"{verb} to {branch}"


isCommittingStatusMessage = committing_just_now_message
getButtonTitle = get_button_title


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


# Desktop `CoAuthorAutocompletionProvider.renderItem` description for unknown users.
SEARCH_FOR_USER = "Search for user"
includeUnknownUser = True


def _state_endpoint(state: Any, endpoint: str = "") -> str:
    if endpoint:
        return endpoint
    github = getattr(state, "github", None) if state is not None else None
    if github is None:
        repo = getattr(state, "repository", None) if state is not None else None
        github = getattr(repo, "github", None) if repo is not None else None
    return str(getattr(github, "endpoint", None) or "")


def user_to_hit(user: dict, endpoint: str = "") -> dict[str, Any]:
    """Desktop `userToHit`."""
    login = str(user.get("login") or user.get("username") or "")
    name = user.get("name")
    return {
        "kind": "known-user",
        "username": login,
        "name": None if name in (None, "") else str(name),
        "email": str(user.get("email") or ""),
        "endpoint": endpoint or str(user.get("endpoint") or ""),
        "login": login,
    }


userToHit = user_to_hit


def user_hit_display(item: dict[str, Any]) -> str:
    username = str(item.get("username") or "")
    if item.get("kind") == "unknown-user":
        return f"{username}  {SEARCH_FOR_USER}"
    name = str(item.get("name") or "")
    if name and name != username:
        return f"{username}  {name}"
    return username


def user_hit_completion_text(item: dict[str, Any]) -> str:
    """Desktop `UserAutocompletionProvider.getCompletionText`."""
    return f"@{item.get('username') or ''}"


getCompletionText = user_hit_completion_text


def autocomplete_item_filter(item: dict[str, Any], authors: Sequence[Any]) -> bool:
    """Desktop `AuthorInput.getAutocompleteItemFilter`."""
    if item.get("kind") != "known-user":
        return True
    usernames = {(getattr(author, "username", None) or "").lower() for author in authors}
    return str(item.get("username") or "").lower() not in usernames


getAutocompleteItemFilter = autocomplete_item_filter


def get_user_autocompletion_items(
    state: Any,
    text: str,
    *,
    include_unknown_user: bool = False,
    exclude_login: str | None = None,
    exclude_usernames: Sequence[str] = (),
    endpoint: str = "",
    max_hits: int = DefaultMaxHits,
) -> list[dict[str, Any]]:
    """Desktop `UserAutocompletionProvider.getUserAutocompletionItems`."""
    needle = (text or "").lstrip("@")
    skip = (exclude_login or "").lower()
    already = {name.lower() for name in exclude_usernames if name}
    host = _state_endpoint(state, endpoint)
    mentionables = list(getattr(state, "mentionables", None) or []) if state is not None else []
    if not mentionables and state is not None:
        mentionables = [
            {"login": login, "name": login, "email": ""}
            for login in getattr(state, "mentions", None) or []
            if login
        ]
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    seen: set[str] = set()
    for user in mentionables:
        login = str(user.get("login") or "")
        if not login:
            continue
        key = login.lower()
        if key == skip or key in already or key in seen:
            continue
        name = str(user.get("name") or "")
        hay = f"{login} {name}".strip().lower()
        index = hay.find(needle.lower()) if needle else 0
        if needle and index < 0:
            continue
        seen.add(key)
        ranked.append((index, login.lower(), user_to_hit(user, host)))
    ranked.sort(key=lambda item: (item[0], item[1]))
    hits = [item[2] for item in ranked[:max_hits]]
    if include_unknown_user and needle:
        exact = any(hit["username"].lower() == needle.lower() for hit in hits)
        if not exact:
            hits.append({"kind": "unknown-user", "username": needle})
    return hits


getUserAutocompletionItems = get_user_autocompletion_items


class UserAutocompletionProvider:
    """Desktop `UserAutocompletionProvider`."""

    kind = "user"
    include_unknown_user = False
    includeUnknownUser = False

    def get_user_autocompletion_items(
        self,
        state: Any,
        text: str,
        include_unknown_user: bool | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        include = self.include_unknown_user if include_unknown_user is None else include_unknown_user
        return get_user_autocompletion_items(state, text, include_unknown_user=include, **kwargs)

    getUserAutocompletionItems = get_user_autocompletion_items

    def get_autocompletion_items(self, state: Any, text: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self.get_user_autocompletion_items(state, text, include_unknown_user=False, **kwargs)

    getAutocompletionItems = get_autocompletion_items


class CoAuthorAutocompletionProvider(UserAutocompletionProvider):
    """Desktop `CoAuthorAutocompletionProvider`: optional `@` and includeUnknownUser."""

    include_unknown_user = True
    includeUnknownUser = True

    def get_autocompletion_items(self, state: Any, text: str, **kwargs: Any) -> list[dict[str, Any]]:
        return self.get_user_autocompletion_items(state, text, include_unknown_user=True, **kwargs)


def append_user_hit(list_store: Gtk.ListStore, item: dict[str, Any]) -> None:
    display = user_hit_display(item)
    kind = str(item.get("kind") or "known-user")
    username = str(item.get("username") or "")
    name = str(item.get("name") or "")
    email = str(item.get("email") or "")
    if list_store.get_n_columns() >= 5:
        list_store.append([display, kind, username, name, email])
    else:
        list_store.append([display])


def fill_coauthor_store(
    list_store: Gtk.ListStore,
    state: Any,
    *,
    exclude_login: str | None = None,
    query: str = "",
    include_unknown_user: bool = False,
    exclude_usernames: Sequence[str] = (),
    endpoint: str = "",
) -> int:
    list_store.clear()
    if state is None and not (include_unknown_user and query):
        return 0
    items = get_user_autocompletion_items(
        state,
        query,
        include_unknown_user=include_unknown_user,
        exclude_login=exclude_login,
        exclude_usernames=exclude_usernames,
        endpoint=endpoint,
    )
    for item in items:
        append_user_hit(list_store, item)
    return len(items)


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


def autocompletion_suggestions_aria_live(count: int) -> str | None:
    """Desktop `autocompleting-text-input.tsx` suggestionsMessage.

    AriaLiveContainer `message` is null when `autoCompleteItems.length` is 0.
    """
    if count <= 0:
        return None
    return "1 suggestion" if count == 1 else f"{count} suggestions"


suggestionsMessage = autocompletion_suggestions_aria_live


def widget_should_announce_suggestions(widget: Any) -> bool:
    """Desktop only autocompletes (and live-announces) while the field is focused."""
    if widget is None:
        return False
    try:
        return bool(widget.has_focus())
    except Exception:
        return False


def _cancel_suggestions_announce(widget: Any) -> None:
    if widget is None:
        return
    source = getattr(widget, "_suggestions_announce_source", 0)
    if source:
        try:
            GLib.source_remove(source)
        except Exception:
            pass
        try:
            widget._suggestions_announce_source = 0
        except Exception:
            pass


def announce_autocompletion_suggestions(
    widget: Any,
    count: int,
    *,
    rangeText: str = "",
    tracker: dict[str, Any] | None = None,
) -> str | None:
    """Announce suggestionsMessage; re-read when trackedUserInput rangeText changes.

    Desktop AriaLiveContainer debounces tracked input 1000ms. Count 0 cancels
    a pending announcement (`message` is null). Immediate under pytest.
    """
    message = autocompletion_suggestions_aria_live(count)
    if tracker is not None:
        prev = (tracker.get("count"), tracker.get("rangeText"))
        tracker["count"] = count
        tracker["rangeText"] = rangeText
        if message is None:
            _cancel_suggestions_announce(widget)
            return None
        if prev == (count, rangeText):
            return None
    elif message is None:
        _cancel_suggestions_announce(widget)
        return None
    if widget is not None:
        try:
            widget._suggestions_message = message  # type: ignore[attr-defined]
        except Exception:
            pass
        _cancel_suggestions_announce(widget)

        def fire() -> bool:
            try:
                widget._suggestions_announce_source = 0
            except Exception:
                pass
            try:
                widget.announce(message, Gtk.AccessibleAnnouncementPriority.MEDIUM)
            except Exception:
                pass
            return False

        if os.environ.get("PYTEST_CURRENT_TEST"):
            fire()
        else:
            try:
                widget._suggestions_announce_source = GLib.timeout_add(1000, fire)
            except Exception:
                fire()
    return message


def populate_completion_store(
    list_store: Gtk.ListStore,
    state: Any,
    token: str,
    *,
    exclude_login: str | None = None,
) -> int:
    list_store.clear()
    matches = completion_matches(state, token, exclude_login=exclude_login)
    for item in matches:
        list_store.append([item])
    return len(matches)


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
        self._suggestions_tracker: dict[str, Any] = {}
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
        if widget_should_announce_suggestions(self.textview):
            announce_autocompletion_suggestions(
                self.textview,
                len(matches),
                rangeText=token,
                tracker=self._suggestions_tracker,
            )
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
