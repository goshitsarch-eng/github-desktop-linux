"""Adwaita stylesheet for diffs, lists, and chrome."""

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
"""


def load_css() -> None:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    provider = Gtk.CssProvider()
    provider.load_from_data(APP_CSS.encode("utf-8"))
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
