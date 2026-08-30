"""Breeze icon names, with fallbacks for themes that lack them.

Kirigami draws icons from the user's icon theme. Breeze ships the whole
freedesktop set plus KDE's own ``vcs-*`` family, but a user running Breeze
with a partial third-party theme -- or a non-KDE desktop -- may not have every
name. Each semantic key below lists names in order of preference and
:func:`icon_name` returns the first one the running theme can actually draw,
so nothing renders as a missing-icon placeholder.
"""

from __future__ import annotations

from functools import lru_cache

# Semantic name -> candidate theme icon names, most specific first.
ICONS: dict[str, tuple[str, ...]] = {
    "app": ("io.github.desktop.GitHubDesktop", "vcs-normal", "folder-git"),
    "fetch": ("view-refresh",),
    "push": ("vcs-push", "arrow-up", "go-up"),
    "pull": ("vcs-pull", "arrow-down", "go-down"),
    "force-push": ("vcs-push", "arrow-up", "go-up"),
    "publish": ("cloud-upload", "vcs-push", "document-export"),
    "commit": ("vcs-commit", "dialog-ok-apply", "checkmark"),
    "branch": ("vcs-branch", "distribute-graph-directed", "view-list-tree"),
    "merge": ("vcs-merge", "document-import"),
    "changes": ("vcs-locally-modified", "document-edit"),
    "history": ("vcs-normal", "view-list-details", "view-history"),
    "diff": ("vcs-diff", "text-x-patch", "view-split-left-right"),
    "stash": ("vcs-stash", "edit-copy", "document-save-as"),
    "tag": ("tag", "bookmarks"),
    "repository": ("folder-git", "folder-development", "folder"),
    "repository-remote": ("folder-remote",),
    "network-share": ("folder-network", "folder-remote", "network-server"),
    "clone": ("edit-download", "cloud-download", "document-import"),
    "add": ("list-add",),
    "remove": ("list-remove",),
    "delete": ("edit-delete",),
    "discard": ("edit-undo",),
    "settings": ("settings-configure", "configure"),
    "menu": ("application-menu", "open-menu"),
    "search": ("search", "edit-find"),
    "terminal": ("utilities-terminal", "dialog-scripts"),
    "editor": ("accessories-text-editor", "text-editor"),
    "folder-open": ("folder-open",),
    "browser": ("internet-web-browser", "applications-internet"),
    "pull-request": ("vcs-merge-request", "vcs-merge", "document-share"),
    "checks-ok": ("dialog-ok", "checkmark", "emblem-success"),
    "checks-failed": ("dialog-error", "emblem-error"),
    "checks-pending": ("clock", "chronometer", "process-working"),
    "warning": ("dialog-warning",),
    "error": ("dialog-error",),
    "info": ("dialog-information",),
    "question": ("dialog-question",),
    "user": ("user-identity", "im-user", "user"),
    "users": ("system-users", "group"),
    "copy": ("edit-copy",),
    "conflict": ("vcs-conflicting", "dialog-warning"),
    "submodule": ("folder-development", "folder"),
    "binary": ("application-x-executable", "unknown"),
    "image": ("image-x-generic", "viewimage"),
    "expand": ("arrow-down-double", "go-bottom"),
    "collapse": ("arrow-up-double", "go-top"),
    "close": ("window-close", "dialog-close"),
    "help": ("help-contents", "help-about"),
    "tutorial": ("help-hint", "documentinfo"),
    "accessibility": ("preferences-desktop-accessibility",),
    "notifications": ("preferences-desktop-notification", "preferences-system-notification"),
    "appearance": ("preferences-desktop-theme-global", "preferences-desktop-color"),
    "integrations": ("preferences-desktop-default-applications", "applications-other"),
    "advanced": ("preferences-other", "configure"),
    "accounts": ("preferences-system-users", "system-users"),
    "git": ("vcs-normal", "folder-git"),
    "secure": ("security-high", "channel-secure"),
    "loading": ("process-working", "view-refresh"),
    "dropdown": ("arrow-down", "go-down"),
    "lightbulb": ("help-hint", "dialog-information"),
}


@lru_cache(maxsize=256)
def icon_name(key: str) -> str:
    """Return the best available theme icon name for a semantic ``key``.

    Falls back to the last candidate (rather than an empty string) so a
    missing icon still identifies itself in a screenshot or bug report.
    """
    candidates = ICONS.get(key)
    if not candidates:
        return key
    try:
        from PySide6.QtGui import QIcon

        for candidate in candidates:
            if QIcon.hasThemeIcon(candidate):
                return candidate
    except Exception:
        pass
    return candidates[-1]


def clear_cache() -> None:
    """Forget resolved names (the icon theme can change at runtime)."""
    icon_name.cache_clear()
