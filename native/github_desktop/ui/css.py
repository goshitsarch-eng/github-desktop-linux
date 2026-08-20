"""Adwaita stylesheet for diffs, lists, and chrome."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

APP_CSS = """
.diff-view {
  font-family: monospace;
  font-size: 0.92rem;
}
.diff-line {
  padding: 0 8px;
}
.diff-add {
  background-color: alpha(@success_color, 0.18);
}
.diff-del {
  background-color: alpha(@error_color, 0.18);
}
.diff-hunk {
  background-color: alpha(@accent_bg_color, 0.18);
  font-weight: 600;
}
.diff-num {
  color: alpha(@window_fg_color, 0.45);
  min-width: 3.2em;
  font-variant-numeric: tabular-nums;
}
.diff-expand {
  min-width: 1.8em;
  padding: 0 4px;
}
.file-status-new { color: @success_color; }
.file-status-modified { color: @warning_color; }
.file-status-deleted { color: @error_color; }
.file-status-renamed { color: @accent_color; }
.file-status-conflicted { color: @error_color; font-weight: 700; }
.commit-summary {
  font-weight: 600;
}
.commit-sha {
  font-family: monospace;
  opacity: 0.7;
}
.toolbar-status {
  font-size: 0.85rem;
  opacity: 0.8;
}
.welcome-title {
  font-weight: 700;
  font-size: 1.6rem;
}
.sidebar-list row {
  padding: 4px 8px;
}
.filter-bar {
  padding: 6px;
}
.commit-box {
  padding: 8px;
}
.co-author {
  font-size: 0.85rem;
  opacity: 0.8;
}
.checks-success { color: @success_color; }
.checks-failure { color: @error_color; }
.checks-pending { color: @warning_color; }
.diff-excluded {
  opacity: 0.45;
}
.diff-side {
  min-width: 12em;
  padding: 0 6px;
}
.diff-empty {
  background-color: alpha(@window_fg_color, 0.04);
}
.context-menu-item {
  padding: 4px 10px;
}
.image-diff-toolbar {
  padding: 6px;
}
.ahead-behind {
  font-size: 0.85rem;
  opacity: 0.8;
  padding: 0 8px;
}
.filter-chip {
  font-size: 0.85rem;
}
.compare-cta {
  padding: 8px;
}
.diff-search {
  padding: 6px 8px;
}
.diff-search-hit {
  background-color: alpha(@warning_color, 0.28);
}
.diff-search-current {
  background-color: alpha(@accent_bg_color, 0.45);
}
.stash-header {
  padding: 10px 12px;
}
.commit-stats {
  font-size: 0.85rem;
  opacity: 0.8;
}
.expandable-commit-summary {
  padding: 8px 12px;
}

.avatar {
  min-width: 28px;
  min-height: 28px;
}
.avatar-initials {
  background-color: @accent_bg_color;
  color: @accent_fg_color;
  border-radius: 999px;
  font-weight: 700;
  font-size: 0.7rem;
  min-width: 28px;
  min-height: 28px;
}
.avatar-image {
  border-radius: 999px;
}
.avatar-stack .avatar {
  margin-left: -8px;
}
.avatar-stack .avatar:first-child {
  margin-left: 0;
}
.avatar-more {
  min-width: 28px;
  min-height: 28px;
  margin-left: -8px;
  border-radius: 999px;
  background-color: alpha(@window_fg_color, 0.14);
  font-weight: 700;
  font-size: 0.7rem;
}
.diff-contents-warning {
  padding: 8px 12px;
  background-color: alpha(@warning_color, 0.12);
  border-radius: 8px;
  margin: 6px 8px;
}
.tutorial-panel {
  padding: 12px;
  min-width: 260px;
  border-left: 1px solid alpha(@window_fg_color, 0.12);
}
.diff-comment {
  margin: 0 12px 8px 48px;
  padding: 8px;
  background-color: alpha(@accent_bg_color, 0.12);
  border-radius: 8px;
}

.whitespace-hint {
  padding: 6px 8px;
  font-size: 0.85rem;
  opacity: 0.8;
}
"""

_provider: Gtk.CssProvider | None = None
_zoom_provider: Gtk.CssProvider | None = None


def load_css() -> None:
    global _provider
    _provider = Gtk.CssProvider()
    _provider.load_from_data(APP_CSS.encode("utf-8"))
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, _provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )


def apply_zoom(factor: float) -> None:
    """Scale UI chrome similarly to Desktop's Ctrl+0/=/− webview zoom."""
    global _zoom_provider
    factor = min(3.0, max(0.7, float(factor)))
    display = Gdk.Display.get_default()
    if display is None:
        return
    if _zoom_provider is None:
        _zoom_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            display, _zoom_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
        )
    size = round(13 * factor, 2)
    css = f"window.github-desktop-zoom {{ font-size: {size}pt; }}\n"
    _zoom_provider.load_from_data(css.encode("utf-8"))
