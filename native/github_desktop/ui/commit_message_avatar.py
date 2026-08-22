"""CommitMessageAvatar — author avatar plus git-config / email-rule popover.

Desktop: ``ui/changes/commit-message-avatar.tsx``.
The Changes form and ``CommitMessageDialog`` both wrap ``CommitMessage``, which
always mounts this control. Native previously only had the avatar on the Changes
form; the squash/amend/reword dialog dumped email-rule copy into the inline
warning label.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from ..email import COMMIT_ATTRIBUTION_DOCS, is_attributable_email_for, lookup_preferred_email
from ..github.repo_rules import use_repo_rules_logic
from ..git.ops import get_config_value
from ..models import PopupType, RepositorySettingsTab
from .avatar import Avatar
from .menus import (
    IGNORE_LABEL,
    LEARN_MORE_ABOUT_COMMIT_ATTRIBUTION,
    THIS_COMMIT_WILL_BE_MISATTRIBUTED,
    THIS_EMAIL_ADDRESS_IS_DISALLOWED,
    UPDATE_EMAIL_LABEL,
    YOUR_ACCOUNT_EMAILS,
    clear_box,
    commit_message_avatar_aria_label,
    commit_message_avatar_choose_local_email_copy,
    commit_message_avatar_email_leading_text,
    commit_message_avatar_warning_type,
    committing_as_title,
    git_config_popover_copy,
    open_git_settings_label,
)
from .rule_failure_popover import repo_rules_failure_list_widget

getCommittingAsTitle = committing_as_title
CommitMessageAvatarWarningType = commit_message_avatar_warning_type


class CommitMessageAvatar:
    """Author avatar MenuButton plus git-config / email-rule popover."""

    def __init__(self, store, parent: Gtk.Window | None = None) -> None:
        self.store = store
        self.parent = parent
        self._author_btn = Gtk.MenuButton()
        self._author_btn.set_tooltip_text("View commit author information")
        self._author_avatar_host = Gtk.Box()
        self._author_btn.set_child(self._author_avatar_host)
        self._author_popover = Gtk.Popover()
        self._author_popover_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self._author_popover_box.set_margin_top(8)
        self._author_popover_box.set_margin_bottom(8)
        self._author_popover_box.set_margin_start(8)
        self._author_popover_box.set_margin_end(8)
        self._author_popover.set_child(self._author_popover_box)
        self._author_btn.set_popover(self._author_popover)

    @property
    def widget(self) -> Gtk.Widget:
        return self._author_btn

    def renderAvatar(self) -> Gtk.Widget:
        """Desktop ``CommitMessage.renderAvatar``."""
        return self.widget

    def renderWarningPopover(self) -> Gtk.Popover:
        """Desktop ``CommitMessageAvatar.renderWarningPopover`` host."""
        return self._author_popover

    def renderGitConfigPopover(self) -> Gtk.Popover:
        """Desktop ``CommitMessageAvatar.renderGitConfigPopover`` host."""
        return self._author_popover

    def _open_git_settings(self, *_args: object) -> None:
        from .dialogs import show_preferences
        from ..models import PreferencesTab

        self._author_popover.popdown()
        if self.parent is not None:
            show_preferences(self.parent, self.store, PreferencesTab.GIT)

    def _open_repository_settings(self, *_args: object) -> None:
        self._author_popover.popdown()
        self.store.show_popup(
            PopupType.REPOSITORY_SETTINGS, tab=RepositorySettingsTab.GIT_CONFIG
        )

    def _use_author_email(self, repo, email: str) -> None:
        self.store.set_commit_author_email(repo, email)
        self._author_popover.popdown()
        self.refresh(repo)

    def refresh(self, repo) -> None:
        """Rebuild the avatar popover. Desktop ``CommitMessageAvatar`` render."""
        name, email = self.store.author_identity(repo)
        account = self.store.account_for_repo(repo) if repo is not None else None
        state = self.store.state_for(repo) if repo is not None else None
        email_failures = (
            state.repo_rules.commit_author_email_patterns.get_failed_rules(email or "")
            if state is not None
            else None
        )
        emailRuleFailures = email_failures
        misattributed = bool(account and email and not is_attributable_email_for(account, email))
        repo_rules_enabled = bool(repo is not None and use_repo_rules_logic(account, repo))
        warningType = commit_message_avatar_warning_type(
            email=email,
            repo_rules_enabled=repo_rules_enabled,
            email_failures_status=emailRuleFailures.status if emailRuleFailures is not None else "pass",
            misattributed=misattributed,
        )
        warning_type = warningType
        clear_box(self._author_avatar_host)
        avatar = Avatar(
            name or (account.login if account else "Git"),
            email or "",
            login=account.login if account else None,
            avatar_url=account.avatar_url if account else None,
            size=28,
            account=account,
            endpoint=account.endpoint if account else None,
        )
        self._author_avatar_host.append(avatar)
        self._author_btn.remove_css_class("author-warning")
        self._author_btn.remove_css_class("author-error")
        is_error = (
            warning_type == "disallowedEmail"
            and emailRuleFailures is not None
            and emailRuleFailures.status == "fail"
        )
        if warning_type != "none":
            self._author_btn.add_css_class("author-error" if is_error else "author-warning")
        aria = commit_message_avatar_aria_label(warning_type)
        self._author_btn.set_tooltip_text(aria)
        try:
            self._author_btn.update_property([Gtk.AccessibleProperty.LABEL], [aria])
        except Exception:
            pass
        clear_box(self._author_popover_box)
        if warning_type == "disallowedEmail":
            heading_text = THIS_EMAIL_ADDRESS_IS_DISALLOWED
        elif warning_type == "misattribution":
            heading_text = THIS_COMMIT_WILL_BE_MISATTRIBUTED
        else:
            heading_text = committing_as_title(name=name, email=email)
        heading = Gtk.Label(label=heading_text, xalign=0)
        heading.add_css_class("heading")
        self._author_popover_box.append(heading)
        branch = state.status.current_branch if state is not None and state.status else None
        github = getattr(repo, "github", None) if repo is not None else None
        if warning_type == "disallowedEmail" and github and branch and emailRuleFailures is not None:
            self._author_popover_box.append(
                repo_rules_failure_list_widget(
                    commit_message_avatar_email_leading_text(email or ""),
                    emailRuleFailures,
                    github,
                    branch,
                )
            )
        elif warning_type == "misattribution":
            enterprise_suffix = " Enterprise" if account and account.is_enterprise else ""
            user_name = f" for {name}" if name else ""
            warn = Gtk.Label(
                label=(
                    f"The email in your global Git config ({email}) doesn't match your "
                    f"GitHub{enterprise_suffix} account{user_name}. "
                    "This email address doesn't match your GitHub account. "
                    "Commits may not be attributed to you."
                ),
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            self._author_popover_box.append(warn)
            learn = Gtk.LinkButton(uri=COMMIT_ATTRIBUTION_DOCS, label="Learn more")
            learn.set_tooltip_text(LEARN_MORE_ABOUT_COMMIT_ATTRIBUTION)
            learn.set_halign(Gtk.Align.START)
            self._author_popover_box.append(learn)
        else:
            if name and email:
                self._author_popover_box.append(Gtk.Label(label=f"Email: {email}", xalign=0, wrap=True))
            isGitConfigLocal = False
            if repo is not None:
                try:
                    isGitConfigLocal = bool(
                        get_config_value(repo.path, "user.name", local_only=True)
                        or get_config_value(repo.path, "user.email", local_only=True)
                    )
                except Exception:
                    isGitConfigLocal = False
            is_local = isGitConfigLocal
            self._author_popover_box.append(
                Gtk.Label(label=git_config_popover_copy(local=is_local), wrap=True, xalign=0)
            )
        emails = list(account.email_addresses) if account else []
        if account:
            preferred = lookup_preferred_email(account)
            if preferred not in emails:
                emails.insert(0, preferred)
        has_emails = bool(emails)
        if warning_type != "none" and has_emails:
            emails_heading = Gtk.Label(label=YOUR_ACCOUNT_EMAILS, xalign=0)
            emails_heading.add_css_class("heading")
            self._author_popover_box.append(emails_heading)
            for item in emails:
                btn = Gtk.Button(label=item)
                btn.add_css_class("flat")
                btn.connect("clicked", lambda _b, addr=item: self._use_author_email(repo, addr))
                self._author_popover_box.append(btn)
        choose = Gtk.Label(
            label=commit_message_avatar_choose_local_email_copy(has_emails=has_emails),
            wrap=True,
            xalign=0,
        )
        choose.add_css_class("dim-label")
        self._author_popover_box.append(choose)
        row = Gtk.Box(spacing=6)
        ignore = Gtk.Button(label=IGNORE_LABEL)
        ignore.connect("clicked", lambda *_: self._author_popover.popdown())
        row.append(ignore)
        if warning_type != "none" and has_emails:
            update = Gtk.Button(label=UPDATE_EMAIL_LABEL)
            update.add_css_class("suggested-action")
            update.connect("clicked", lambda *_: self._use_author_email(repo, emails[0]))
            row.append(update)
        elif warning_type == "none":
            git_btn = Gtk.Button(label=open_git_settings_label())
            git_btn.add_css_class("suggested-action")
            git_btn.connect("clicked", self._open_git_settings)
            row.append(git_btn)
        self._author_popover_box.append(row)
        repo_btn = Gtk.Button(label="repository settings")
        repo_btn.add_css_class("flat")
        repo_btn.connect("clicked", self._open_repository_settings)
        self._author_popover_box.append(repo_btn)
