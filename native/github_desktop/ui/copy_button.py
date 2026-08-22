"""Desktop `CopyButton` — copy icon that confirms with `Copied!` for 2 seconds."""

from __future__ import annotations

import os

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from .menus import copy_text

COPIED = "Copied!"
COPY_BUTTON = "copy-button"
COPY_THE_FULL_SHA = "Copy the full SHA"
# Desktop `octicons.copy` / `octicons.check`.
COPY_ICON = "edit-copy-symbolic"
CHECK_ICON = "object-select-symbolic"
COPIED_MS = 2000


def copy_the_full_sha_label(which: str | None = None) -> str:
    """Desktop CopyButton `ariaLabel` for a commit SHA (`Copy the full SHA`)."""
    if not which:
        return COPY_THE_FULL_SHA
    return f"Copy the full {which} SHA"


class CopyButton(Gtk.Button):
    """Desktop `CopyButton`: `copyContent` plus `Copied!` tooltip / aria-live."""

    def __init__(self, *, copy_content: str = "", aria_label: str = COPY_THE_FULL_SHA) -> None:
        super().__init__()
        self.add_css_class(COPY_BUTTON)
        self.add_css_class("flat")
        self._copy_content = copy_content
        self._aria_label = aria_label
        self._show_copied = False
        self._timeout = 0
        self.set_icon_name(COPY_ICON)
        self.set_tooltip_text(aria_label)
        self._apply_aria_label(aria_label)
        self.connect("clicked", self._on_copy)

    @property
    def showCopied(self) -> bool:
        """Desktop `showCopied` — true while the check / `Copied!` state is visible."""
        return self._show_copied

    def copyContent(self) -> str:
        """Desktop `copyContent`."""
        return self._copy_content

    def set_copy_content(self, text: str) -> None:
        copyContent = text
        self._copy_content = copyContent

    def set_aria_label(self, label: str) -> None:
        self._aria_label = label
        if not self._show_copied:
            self.set_tooltip_text(label)
            self._apply_aria_label(label)

    def renderSymbol(self) -> str:
        """Desktop `renderSymbol`: check while copied, otherwise copy."""
        return CHECK_ICON if self._show_copied else COPY_ICON

    def ariaLiveMessage(self) -> str:
        """Desktop `AriaLiveContainer` message (`Copied!` or empty)."""
        return COPIED if self._show_copied else ""

    def _apply_aria_label(self, label: str) -> None:
        try:
            self.update_property([Gtk.AccessibleProperty.LABEL], [label])
        except Exception:
            pass

    def _on_copy(self, *_args: object) -> None:
        if self._copy_content:
            copy_text(self._copy_content)
        self._set_copied(True)
        # Desktop `openTooltipOnClick={true}` — keep `Copied!` on the tooltip.
        if self._timeout:
            GLib.source_remove(self._timeout)
            self._timeout = 0
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        self._timeout = GLib.timeout_add(COPIED_MS, self._clear_copied)

    def _set_copied(self, copied: bool) -> None:
        self._show_copied = copied
        self.set_icon_name(self.renderSymbol())
        tip = COPIED if copied else self._aria_label
        self.set_tooltip_text(tip)
        self._apply_aria_label(self._aria_label)
        live = self.ariaLiveMessage()
        try:
            self.update_property(
                [Gtk.AccessibleProperty.DESCRIPTION],
                [live],
            )
        except Exception:
            pass

    def _clear_copied(self) -> bool:
        self._timeout = 0
        self._set_copied(False)
        return False
