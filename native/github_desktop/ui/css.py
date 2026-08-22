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
/* Desktop `_side-by-side-diff.scss` `.content`: white-space: pre-wrap; word-break: break-all */
.diff-add {
  background-color: alpha(@success_color, 0.18);
}
.diff-del {
  background-color: alpha(@error_color, 0.18);
}
.diff-add-inner {
  background-color: alpha(@success_color, 0.45);
}
.diff-delete-inner {
  background-color: alpha(@error_color, 0.45);
}
.diff-no-newline {
  opacity: 0.55;
  min-width: 1.2em;
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
/* Desktop `_changes-list.scss` `.hidden-changes-warning` */
.hidden-changes-warning {
  padding: 6px 8px;
  background-color: alpha(@warning_color, 0.12);
  border-top: 1px solid alpha(@warning_color, 0.35);
  border-bottom: 1px solid alpha(@warning_color, 0.35);
}
.hidden-changes-warning .link-button-component {
  padding: 0;
}
.sr-only {
  opacity: 0;
  min-width: 1px;
  min-height: 1px;
  padding: 0;
  margin: 0;
}
.suggested-actions {
  padding: 8px;
}
.suggested-action-card {
  padding: 12px;
  border-radius: 12px;
  background-color: alpha(@card_bg_color, 0.6);
}
.co-author {
  font-size: 0.85rem;
  opacity: 0.9;
}
.co-author-chip {
  padding: 2px 8px;
  border-radius: 12px;
  background-color: alpha(@accent_bg_color, 0.22);
}
.co-author-chip.unknown {
  background-color: alpha(@warning_color, 0.28);
}
.co-author-chips {
  min-height: 0;
}
.author-input-component {
  min-width: 12em;
}
.author-input-label {
  font-weight: 600;
}
.co-author-chip.handle.error {
  background-color: alpha(@error_color, 0.22);
}
.co-author-chip.handle.progress {
  background-color: alpha(@accent_bg_color, 0.18);
}
.checks-success { color: @success_color; }
.checks-failure { color: @error_color; }
.checks-pending { color: @warning_color; }
.diff-excluded {
  opacity: 0.45;
}
.diff-gutter-selecting {
  background-color: alpha(@accent_bg_color, 0.28);
}
.diff-hunk-hover {
  background-color: alpha(@accent_bg_color, 0.12);
}
.hunk-handle {
  min-width: 18px;
  padding: 0 2px;
}
.hunk-handle:hover {
  background-color: alpha(@accent_bg_color, 0.18);
}
.diff-side {
  min-width: 12em;
  padding: 0 6px;
}
.diff-empty {
  background-color: alpha(@window_fg_color, 0.04);
}
.diff-options-popover {
  min-width: 16em;
}
.diff-options-legend {
  font-weight: 600;
  margin-top: 4px;
}
.context-menu-item {
  padding: 4px 10px;
}
.image-diff-toolbar {
  padding: 6px;
}
.image-diff-header {
  font-weight: 600;
}
.image-diff-swipe {
  padding: 8px;
}
.image-diff-swipe-canvas {
  background-color: alpha(@window_fg_color, 0.04);
}
.image-diff-difference {
  padding: 8px;
}
.image-diff-difference-canvas {
  background-color: alpha(@window_fg_color, 0.04);
}
.tag-indicator, .tag-name {
  font-size: 0.75rem;
  padding: 1px 6px;
  border-radius: 8px;
  background-color: alpha(@accent_bg_color, 0.28);
}
.tag-indicator-more {
  min-width: 8px;
  min-height: 8px;
  border-radius: 999px;
  background-color: alpha(@accent_bg_color, 0.55);
}
.unpushed-indicator {
  color: @accent_color;
}
.commit-summary.empty-summary {
  font-style: italic;
  opacity: 0.7;
}
.toolbar-resizable .resize-handle {
  min-width: 6px;
  min-height: 1px;
}
.toolbar-resizable .resize-handle:hover {
  background-color: alpha(@accent_bg_color, 0.35);
}
.push-pull-button .push-pull-label {
  font-weight: 600;
}
.push-pull-icon {
  min-width: 16px;
  min-height: 16px;
}
.push-last-fetched {
  font-size: 0.75rem;
  opacity: 0.7;
}
.ahead-behind {
  font-size: 0.85rem;
  opacity: 0.8;
  padding: 0 8px;
}
.repo-changes-dot {
  font-size: 0.65rem;
  color: @accent_color;
  padding: 0 6px;
}
.filter-chip {
  font-size: 0.85rem;
}
.merge-info {
  font-size: 0.9rem;
  opacity: 0.85;
  padding: 4px 0;
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
.author-warning {
  border: 2px solid @warning_color;
  border-radius: 999px;
}
.author-error {
  border: 2px solid @error_color;
  border-radius: 999px;
}
.whitespace-hint {
  padding: 8px 12px;
  background-color: alpha(@warning_color, 0.12);
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

.completeness-indicator-success {
  color: @success_color;
}
.completeness-indicator-error {
  color: @error_color;
}
.history-commit.commit-drop-squash {
  background-color: alpha(@accent_bg_color, 0.22);
}
.history-commit.commit-drop-before {
  box-shadow: inset 0 3px 0 @accent_color;
}
.history-commit.commit-highlight {
  background-color: alpha(@accent_bg_color, 0.32);
}
.history-commit.commit-reorder-insert {
  box-shadow: inset 0 3px 0 @accent_color;
}
.history-commit.commit-reorder-after {
  box-shadow: inset 0 -3px 0 @accent_color;
}
.history-commit.commit-reorder-moving {
  opacity: 0.45;
}
.copilot-new {
  font-size: 0.75rem;
  font-weight: 700;
  color: @accent_color;
}
.reorder-commits-hint {
  padding: 10px 12px;
  margin: 6px 8px;
  border-radius: 10px;
  background-color: alpha(@accent_bg_color, 0.16);
}
window.underline-links button.link label,
window.underline-links link {
  text-decoration: underline;
}
window:not(.underline-links) button.link label,
window:not(.underline-links) link {
  text-decoration: none;
}
.prefs-example-link.example-link-on {
  text-decoration: underline;
}
.prefs-example-link.example-link-off {
  text-decoration: none;
}
.sandboxed-markdown {
  opacity: 0.92;
}
.call-to-action {
  padding: 8px;
}
.no-pull-requests {
  padding: 8px;
}
.repo-rulesets-for-branch-link {
  padding: 0;
}
.toast-notification-container {
  padding: 12px;
}
.toast-notification {
  background-color: alpha(@window_bg_color, 0.94);
  color: @window_fg_color;
  padding: 10px 18px;
  border-radius: 8px;
  font-weight: 600;
  box-shadow: 0 4px 16px alpha(black, 0.28);
}
.window-zoom-info {
  font-size: 1.6rem;
}
.protip {
  opacity: 0.8;
}
.no-repositories {
  min-width: 42em;
}
.no-results-found, .no-branches {
  padding: 12px;
}
/* Desktop `onboarding-tutorial/_nudge-arrow.scss` (--nudge-arrow-z-index: 16) */
.nudge-arrow-graphic {
  min-width: 22px;
  min-height: 22px;
}
.nudge-arrow.nudge-arrow-up,
.nudge-arrow.nudge-arrow-left {
  outline-color: #2188FF;
}
/* Desktop `_commit-message.scss` `.length-hint` / `_tooltips.scss` `.length-hint-tooltip` */
.length-hint {
  min-width: 16px;
  min-height: 16px;
}
.length-hint-tooltip .title {
  font-weight: 600;
}
.length-hint-tooltip .description {
  opacity: 0.7;
}
/* Desktop `multiple-selection.tsx` `.panel.blankslate` */
.multiple-selection.blankslate {
  padding: 24px;
}
.multiple-selection .blankslate-image {
  opacity: 0.55;
}
/* Desktop `copy-button.tsx` */
.copy-button {
  min-width: 28px;
  min-height: 28px;
  padding: 2px;
}
/* Desktop `_diff.scss` `.seamless-diff-switcher` */
.seamless-diff-switcher .loading-indicator {
  opacity: 0;
}
.seamless-diff-switcher.loading:not(.has-diff) .loading-indicator {
  opacity: 1;
}
.seamless-diff-switcher.loading.has-diff.slow .loading-indicator {
  opacity: 1;
}
.seamless-diff-switcher.loading.has-diff.slow .diff-switcher-content {
  opacity: 0.2;
}
/* Desktop `open-pull-request` empty message + footer merge status */
.open-pull-request-message {
  padding: 16px;
}
.pull-request-merge-status {
  opacity: 0.9;
}
/* Desktop `_ci-check-run-no-steps.scss` */
.ci-check-run-no-steps {
  padding: 16px;
}
.ci-check-run-no-steps .blankslate-image {
  opacity: 0.55;
  min-width: 64px;
}
.ci-steps-container.no-steps {
  min-height: 150px;
}
/* Desktop `_ci-check-run-popover.scss` `.loading-check-runs` */
.loading-check-runs {
  padding: 16px;
}
.loading-check-runs .title {
  font-weight: 600;
}
.loading-check-runs .call-to-action {
  opacity: 0.8;
}
.loading-check-runs .blankslate-image {
  opacity: 0.55;
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
