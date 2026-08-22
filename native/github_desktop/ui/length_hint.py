"""Desktop `renderSummaryLengthHint` / `ToggledtippedContent` chrome."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..text_tokens import IdealSummaryLength

# Desktop `commit-message.tsx` `renderSummaryLengthHint` tooltip title / description.
SUMMARY_LENGTH_HINT_TITLE = "Great commit summaries contain fewer than 50 characters"
SUMMARY_LENGTH_HINT_DESCRIPTION = "Place extra information in the description field."
SUMMARY_LENGTH_HINT = (
    f"{SUMMARY_LENGTH_HINT_TITLE}. {SUMMARY_LENGTH_HINT_DESCRIPTION}"
)
OPEN_SUMMARY_LENGTH_INFO = "Open Summary Length Info"
LENGTH_HINT = "length-hint"
LENGTH_HINT_TOOLTIP = "length-hint-tooltip"
# Desktop `octicons.lightBulb` — Adwaita objects category is a light bulb.
LIGHT_BULB = "emoji-objects-symbolic"


def summary_length_hint(text: str, enabled: bool) -> str | None:
    """Aria-live copy when the summary exceeds `IdealSummaryLength` (50)."""
    if enabled and len(text) > IdealSummaryLength:
        return SUMMARY_LENGTH_HINT
    return None


def show_summary_length_hint(text: str, enabled: bool, *, rule_hint: bool = False) -> bool:
    """Desktop `showSummaryLengthHint`: length warning unless a rule-failure hint is up."""
    return (not rule_hint) and summary_length_hint(text, enabled) is not None


class ToggledtippedContent(Gtk.MenuButton):
    """Desktop `ToggledtippedContent` — click-to-toggle tooltip (`isToggleTip`) with aria-live."""

    def __init__(
        self,
        *,
        tooltip_title: str,
        tooltip_description: str,
        aria_live_message: str,
        aria_label: str,
        class_name: str = "toggletip",
        tooltip_class_name: str = "",
        icon_name: str = LIGHT_BULB,
    ) -> None:
        super().__init__()
        self.add_css_class("toggletip")
        if class_name:
            self.add_css_class(class_name)
        self.add_css_class("flat")
        self.add_css_class("circular")
        self.set_icon_name(icon_name)
        self.set_always_show_arrow(False)
        self._aria_live_message = aria_live_message
        self._aria_label = aria_label
        try:
            self.update_property(
                [Gtk.AccessibleProperty.LABEL, Gtk.AccessibleProperty.HAS_POPUP],
                [aria_label, True],
            )
        except Exception:
            try:
                self.update_property([Gtk.AccessibleProperty.LABEL], [aria_label])
            except Exception:
                pass
        popover = Gtk.Popover()
        popover.set_autohide(True)
        popover.set_position(Gtk.PositionType.TOP)
        if tooltip_class_name:
            popover.add_css_class(tooltip_class_name)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        pop_box.set_margin_top(10)
        pop_box.set_margin_bottom(10)
        pop_box.set_margin_start(12)
        pop_box.set_margin_end(12)
        title = Gtk.Label(label=tooltip_title, wrap=True, xalign=0)
        title.add_css_class("title")
        title.add_css_class("heading")
        description = Gtk.Label(label=tooltip_description, wrap=True, xalign=0)
        description.add_css_class("description")
        description.add_css_class("dim-label")
        pop_box.append(title)
        pop_box.append(description)
        self._live = Gtk.Label(label="", xalign=0)
        self._live.set_visible(False)
        try:
            self._live.update_property(
                [Gtk.AccessibleProperty.LIVE],
                [Gtk.AccessibleLive.POLITE],
            )
        except Exception:
            pass
        pop_box.append(self._live)
        popover.set_child(pop_box)
        self.set_popover(popover)
        self._popover = popover
        popover.connect("notify::visible", self._on_popover_visible)
        self._force_aria = False

    def _on_popover_visible(self, popover: Gtk.Popover, *_args: object) -> None:
        visible = bool(popover.get_visible())
        if not visible:
            self._live.set_text("")
            return
        # Desktop `shouldForceAriaLiveMessage` flips on each click so the
        # AriaLiveContainer re-announces the same `ariaLiveMessage`.
        self._force_aria = not self._force_aria
        self._live.set_text("")
        self._live.set_text(self._aria_live_message)

    def ariaLiveMessage(self) -> str:
        return self._aria_live_message


class SummaryLengthHint(ToggledtippedContent):
    """Desktop `renderSummaryLengthHint` lightbulb beside the summary field."""

    def __init__(self) -> None:
        super().__init__(
            tooltip_title=SUMMARY_LENGTH_HINT_TITLE,
            tooltip_description=SUMMARY_LENGTH_HINT_DESCRIPTION,
            aria_live_message=SUMMARY_LENGTH_HINT,
            aria_label=OPEN_SUMMARY_LENGTH_INFO,
            class_name=LENGTH_HINT,
            tooltip_class_name=LENGTH_HINT_TOOLTIP,
            icon_name=LIGHT_BULB,
        )
        self.set_visible(False)

    def renderSummaryLengthHint(self) -> Gtk.Widget:
        """Desktop `CommitMessage.renderSummaryLengthHint`."""
        return self

    def set_active_hint(self, show: bool) -> None:
        self.set_visible(bool(show))
        if not show:
            try:
                self.set_active(False)
            except Exception:
                popover = self.get_popover()
                if popover is not None:
                    popover.popdown()
