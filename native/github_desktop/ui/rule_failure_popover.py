"""Desktop `renderRuleFailurePopover` / `renderRepoRuleCommitMessageFailureHint` chrome."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

from ..github.repo_rules import (
    COMMIT_MSG_ERROR_BTN_ID,
    commit_message_failure_hint_aria_label,
    commit_message_rule_failures_header,
    repo_rules_failure_heading,
    ruleset_url,
    rulesets_url_for_branch,
)
from ..shells import open_external


def repo_rules_failure_list_widget(
    leading: str,
    failures,
    repository,
    branch: str | None,
    *,
    on_uri: Callable[[str], bool] | None = None,
) -> Gtk.Widget:
    """Desktop `RepoRulesMetadataFailureList` with per-ruleset links."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.add_css_class("repo-rules-failure-list-component")
    heading = repo_rules_failure_heading(leading, failures)
    view_all = rulesets_url_for_branch(repository, branch) if branch else None

    def activate(_label: Gtk.Label, uri: str) -> bool:
        if on_uri is not None and on_uri(uri):
            return True
        if uri.startswith("http://") or uri.startswith("https://"):
            open_external(uri)
            return True
        return False

    def markup_label(markup: str) -> Gtk.Label:
        label = Gtk.Label(wrap=True, xalign=0, use_markup=True)
        label.set_markup(markup)
        label.add_css_class("repo-rules-warning")
        label.connect("activate-link", activate)
        return label

    if view_all:
        escaped = GLib.markup_escape_text(heading)
        markup = (
            f'{escaped} <a href="{GLib.markup_escape_text(view_all)}">'
            "View all rulesets for this branch.</a>"
        )
        box.append(markup_label(markup))
    else:
        label = Gtk.Label(label=heading, wrap=True, xalign=0)
        label.add_css_class("repo-rules-warning")
        box.append(label)
    for group_name, items in (("Failed rules:", failures.failed), ("Bypassed rules:", failures.bypassed)):
        if not items:
            continue
        group = Gtk.Label(label=group_name, xalign=0)
        group.add_css_class("heading")
        box.append(group)
        for item in items:
            href = ruleset_url(repository, item.ruleset_id) or ""
            text = GLib.markup_escape_text(item.description)
            if href:
                row = markup_label(f'<a href="{GLib.markup_escape_text(href)}">{text}</a>')
                row.add_css_class("repo-ruleset-link")
            else:
                row = Gtk.Label(label=item.description, wrap=True, xalign=0)
                row.add_css_class("repo-rules-warning")
            box.append(row)
    return box


class RuleFailurePopover:
    """Summary-anchored commit-message rule-failure hint and popover."""

    def __init__(self, summary: Gtk.Widget) -> None:
        self.summary = summary
        self.wanted = False
        self._suppress_closed = False
        self.hint = Gtk.Button()
        self.hint.set_name(COMMIT_MSG_ERROR_BTN_ID)
        self.hint.add_css_class("commit-message-failure-hint")
        self.hint.add_css_class("flat")
        self.hint.add_css_class("circular")
        self.hint.set_visible(False)
        self.hint.connect("clicked", self.toggle)
        self.popover = Gtk.Popover()
        self.popover.set_autohide(True)
        self.popover.connect("closed", self._on_closed)
        pop_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pop_box.set_margin_top(12)
        pop_box.set_margin_bottom(12)
        pop_box.set_margin_start(12)
        pop_box.set_margin_end(12)
        header = Gtk.Label(label=commit_message_rule_failures_header(), xalign=0)
        header.add_css_class("title-4")
        header.set_name("commit-message-rule-failure-popover-header")
        pop_box.append(header)
        self.list_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        pop_box.append(self.list_host)
        self.popover.set_child(pop_box)
        self.popover.set_parent(summary)

    def attach_to_row(self, row: Gtk.Box) -> None:
        row.append(self.hint)

    def toggle(self, *_args: object) -> None:
        """Desktop `toggleRuleFailurePopover`."""
        self.wanted = not self.wanted
        if self.wanted:
            self.popover.popup()
        else:
            self._hide_popover(keep_wanted=False)

    toggleRuleFailurePopover = toggle

    def is_open(self) -> bool:
        """Desktop `isRuleFailurePopoverOpen`."""
        return bool(self.wanted)

    isRuleFailurePopoverOpen = is_open

    def hide_hint(self) -> None:
        self.hint.set_visible(False)
        self._hide_popover(keep_wanted=True)

    def update(self, repo, branch: str | None, failures, show_hint: bool) -> None:
        """Desktop `renderRepoRuleCommitMessageFailureHint` + `renderRuleFailurePopover`."""
        if not show_hint:
            self.hide_hint()
            return
        can_bypass = failures.status == "bypass"
        aria = commit_message_failure_hint_aria_label(can_bypass=can_bypass)
        self.hint.set_icon_name(
            "dialog-warning-symbolic" if can_bypass else "dialog-error-symbolic"
        )
        self.hint.set_tooltip_text(aria)
        try:
            self.hint.update_property([Gtk.AccessibleProperty.LABEL], [aria])
        except Exception:
            pass
        self.hint.remove_css_class("warning-icon")
        self.hint.remove_css_class("error-icon")
        self.hint.add_css_class("warning-icon" if can_bypass else "error-icon")
        self.hint.set_visible(True)
        self.render_popover(repo, branch, failures)
        if self.wanted:
            self.popover.popup()
        else:
            self._hide_popover(keep_wanted=True)

    renderRepoRuleCommitMessageFailureHint = update

    def render_popover(self, repo, branch: str | None, failures) -> None:
        """Desktop `renderRuleFailurePopover`."""
        if repo is None or not getattr(repo, "github", None):
            return
        while (child := self.list_host.get_first_child()) is not None:
            self.list_host.remove(child)
        self.list_host.append(
            repo_rules_failure_list_widget(
                "This commit message", failures, repo.github, branch
            )
        )

    renderRuleFailurePopover = render_popover

    def _hide_popover(self, *, keep_wanted: bool) -> None:
        self._suppress_closed = True
        try:
            self.popover.popdown()
        finally:
            self._suppress_closed = False
        if not keep_wanted:
            self.wanted = False

    def _on_closed(self, *_args: object) -> None:
        if self._suppress_closed:
            return
        self.wanted = False
