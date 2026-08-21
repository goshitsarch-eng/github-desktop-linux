"""Desktop `lib/welcome.ts` — whether the first-run welcome flow has been shown."""

from __future__ import annotations

from .local_storage import get_boolean, set_boolean

HasShownWelcomeFlowKey = "has-shown-welcome-flow"


def has_shown_welcome_flow(legacy_welcome_shown: bool = False) -> bool:
    """Desktop `hasShownWelcomeFlow`.

    Prefers localStorage ``has-shown-welcome-flow``. ``legacy_welcome_shown``
    covers installs that only persisted this in settings JSON.
    """
    if get_boolean(HasShownWelcomeFlowKey, False):
        return True
    return bool(legacy_welcome_shown)


def mark_welcome_flow_complete() -> None:
    """Desktop `markWelcomeFlowComplete`."""
    set_boolean(HasShownWelcomeFlowKey, True)
