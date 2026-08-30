"""Desktop `TextBox` with `displayClearButton` and AriaLiveContainer `Input cleared`."""

from __future__ import annotations

INPUT_CLEARED = "Input cleared"
displayClearButton = True


def input_cleared_aria_live() -> str:
    """Desktop TextBox `AriaLiveContainer message="Input cleared"`."""
    return INPUT_CLEARED
