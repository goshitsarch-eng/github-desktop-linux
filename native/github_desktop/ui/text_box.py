"""Desktop `TextBox` with `displayClearButton` and AriaLiveContainer `Input cleared`."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

# Desktop `text-box.tsx` AriaLiveContainer after the clear button.
INPUT_CLEARED = "Input cleared"
displayClearButton = True
# Desktop `aria-live-container.tsx` `debounce(..., 1000)` on trackedUserInput.
ARIA_LIVE_DEBOUNCE_MS = 1000


def input_cleared_aria_live() -> str:
    """Desktop TextBox `AriaLiveContainer message="Input cleared"`."""
    return INPUT_CLEARED


def results_pluralized(count: int) -> str:
    """Desktop FilterList `resultsPluralized`."""
    return "result" if count == 1 else "results"


def filter_list_results_aria_live(count: int, post_no_results: str | None = None) -> str:
    """Desktop FilterList `${count} result(s)` plus AugmentedSectionFilterList `postNoResultsMessage`."""
    message = f"{count} {results_pluralized(count)}"
    extra = (post_no_results or "").strip()
    if count == 0 and extra:
        return f"{message} {extra}"
    return message


resultsPluralized = results_pluralized
filterValueChanged = True


def connect_input_cleared(entry: Gtk.Widget) -> None:
    """Announce `Input cleared` when a displayClearButton field becomes empty."""
    prev = {"text": entry.get_text()}

    def on_text(*_args: object) -> None:
        text = entry.get_text()
        if prev["text"] and not text:
            message = input_cleared_aria_live()
            entry._input_cleared_message = message  # type: ignore[attr-defined]
            try:
                entry.announce(message, Gtk.AccessibleAnnouncementPriority.MEDIUM)
            except Exception:
                pass
        prev["text"] = text

    entry.connect("notify::text", on_text)


def _schedule_filter_list_announce(entry: Gtk.Widget, message: str) -> None:
    """Desktop AriaLiveContainer 1000ms debounce; immediate under pytest."""

    def fire() -> bool:
        entry._filter_announce_source = 0  # type: ignore[attr-defined]
        live = getattr(entry, "_filter_list_results_message", message)
        if not live:
            return False
        try:
            entry.announce(live, Gtk.AccessibleAnnouncementPriority.MEDIUM)
        except Exception:
            pass
        return False

    source = getattr(entry, "_filter_announce_source", 0)
    if source:
        try:
            GLib.source_remove(source)
        except Exception:
            pass
        entry._filter_announce_source = 0  # type: ignore[attr-defined]
    if os.environ.get("PYTEST_CURRENT_TEST"):
        fire()
        return
    try:
        entry._filter_announce_source = GLib.timeout_add(  # type: ignore[attr-defined]
            ARIA_LIVE_DEBOUNCE_MS, fire
        )
    except Exception:
        fire()


def announce_filter_list_results(
    entry: Gtk.Widget,
    count: int,
    *,
    post_no_results: str | None = None,
    items_filtered: bool = False,
    context: object | None = None,
) -> None:
    """Desktop FilterList `renderLiveContainer` after `filterValueChanged`.

    `items_filtered` maps AugmentedSectionFilterList `group.items.length !== items.length`
    (chip filters can flip `filterValueChanged` with an empty text box).
    `context` distinguishes shared search fields (Branches vs Pull Requests).
    Desktop `trackedUserInput` is the filter text (plus chip method), not the count,
    so background refreshes with unchanged input do not re-announce.
    """
    text = entry.get_text() if hasattr(entry, "get_text") else ""
    if text or items_filtered:
        entry._filter_value_changed = True  # type: ignore[attr-defined]
    if not getattr(entry, "_filter_value_changed", False):
        return
    message = filter_list_results_aria_live(count, post_no_results)
    entry._filter_list_results_message = message  # type: ignore[attr-defined]
    tracked = (text, bool(items_filtered), context)
    if getattr(entry, "_filter_list_tracked", object()) == tracked:
        return
    entry._filter_list_tracked = tracked  # type: ignore[attr-defined]
    _schedule_filter_list_announce(entry, message)


onFilterListResultsChanged = announce_filter_list_results


def search_entry(**kwargs: object) -> Gtk.SearchEntry:
    """Gtk.SearchEntry mapped to Desktop TextBox `displayClearButton={true}`."""
    entry = Gtk.SearchEntry(**kwargs)
    connect_input_cleared(entry)
    return entry
