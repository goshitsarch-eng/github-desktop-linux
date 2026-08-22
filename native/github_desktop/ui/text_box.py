"""Desktop `TextBox` with `displayClearButton` and AriaLiveContainer `Input cleared`."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

# Desktop `text-box.tsx` AriaLiveContainer after the clear button.
INPUT_CLEARED = "Input cleared"
displayClearButton = True


def input_cleared_aria_live() -> str:
    """Desktop TextBox `AriaLiveContainer message="Input cleared"`."""
    return INPUT_CLEARED


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


def search_entry(**kwargs: object) -> Gtk.SearchEntry:
    """Gtk.SearchEntry mapped to Desktop TextBox `displayClearButton={true}`."""
    entry = Gtk.SearchEntry(**kwargs)
    connect_input_cleared(entry)
    return entry
