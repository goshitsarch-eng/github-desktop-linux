"""Copy-to-clipboard affordance shared by the SHA and path labels.

The button is QML (``ui/qml/CopyButton.qml``); the accessible names and the
"Copied!" confirmation text live here so they stay in one place and the parity
tests can check them.
"""

from __future__ import annotations

COPIED = "Copied!"
COPY_THE_FULL_SHA = "Copy the full SHA"
# Desktop `octicons.copy` / `octicons.check`; resolved through ui.icons.
COPY_ICON_KEY = "copy"
CHECK_ICON_KEY = "checks-ok"
COPIED_MS = 2000


def copy_the_full_sha_label(which: str | None = None) -> str:
    """Desktop CopyButton `ariaLabel` for a commit SHA (`Copy the full SHA`)."""
    if not which:
        return COPY_THE_FULL_SHA
    return f"Copy the full {which} SHA"
