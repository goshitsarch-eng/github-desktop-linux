"""Desktop `renderSummaryLengthHint` / `ToggledtippedContent` chrome."""

from __future__ import annotations

from ..text_tokens import IdealSummaryLength

SUMMARY_LENGTH_HINT_TITLE = "Great commit summaries contain fewer than 50 characters"
SUMMARY_LENGTH_HINT_DESCRIPTION = "Place extra information in the description field."
SUMMARY_LENGTH_HINT = (
    f"{SUMMARY_LENGTH_HINT_TITLE}. {SUMMARY_LENGTH_HINT_DESCRIPTION}"
)
OPEN_SUMMARY_LENGTH_INFO = "Open Summary Length Info"
LENGTH_HINT = "length-hint"
LENGTH_HINT_TOOLTIP = "length-hint-tooltip"
LIGHT_BULB = "emoji-objects-symbolic"


def summary_length_hint(text: str, enabled: bool) -> str | None:
    """Aria-live copy when the summary exceeds `IdealSummaryLength` (50)."""
    if enabled and len(text) > IdealSummaryLength:
        return SUMMARY_LENGTH_HINT
    return None


def show_summary_length_hint(text: str, enabled: bool, *, rule_hint: bool = False) -> bool:
    """Desktop `showSummaryLengthHint`: length warning unless a rule-failure hint is up."""
    return (not rule_hint) and summary_length_hint(text, enabled) is not None
