"""Desktop `ui/lib/open-file.ts` — open a working-tree path with the default app."""

from __future__ import annotations

from .logging import get_logger
from .shells import open_external

log = get_logger()

NO_EXTERNAL_PROGRAM = "no-external-program"


def open_file(full_path: str, store: object | None = None) -> bool:
    """Desktop `openFile`: ``shell.openExternal(`file://${fullPath}`)``."""
    ok = open_external(full_path)
    if ok:
        return True
    message = (
        f"Unable to open file {full_path} in an external program. "
        "Please check you have a program associated with this file extension"
    )
    log.warning(message)
    if store is not None and hasattr(store, "show_popup"):
        from .models import PopupType

        store.show_popup(PopupType.ERROR, error=message, name=NO_EXTERNAL_PROGRAM)
    return False
