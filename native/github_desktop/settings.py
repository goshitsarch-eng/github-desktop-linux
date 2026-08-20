"""Persistent application settings (JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from .models import ApplicationTheme, UncommittedChangesStrategy
from .paths import settings_path


@dataclass
class Settings:
    theme: str = ApplicationTheme.SYSTEM.value
    confirm_repository_removal: bool = True
    confirm_discard_changes: bool = True
    confirm_discard_changes_permanently: bool = True
    confirm_discard_stash: bool = True
    confirm_checkout_commit: bool = True
    confirm_force_push: bool = True
    confirm_undo_commit: bool = True
    confirm_commit_filtered_changes: bool = True
    confirm_commit_message_override: bool = True
    confirm_stash_all_changes: bool = True
    commit_message_generation_disclaimer_last_seen: int = 0
    uncommitted_changes_strategy: str = UncommittedChangesStrategy.ASK_FOR_CONFIRMATION.value
    selected_external_editor: str | None = None
    selected_shell: str | None = None
    use_custom_editor: bool = False
    custom_editor_path: str = ""
    custom_editor_args: str = ""
    use_custom_shell: bool = False
    custom_shell_path: str = ""
    custom_shell_args: str = ""
    tab_size: int = 4
    show_commit_length_warning: bool = True
    notifications_enabled: bool = True
    opt_out_of_usage_tracking: bool = True
    use_external_credential_helper: bool = False
    repository_indicators_enabled: bool = True
    underline_links: bool = True
    show_diff_check_marks: bool = True
    hide_whitespace_in_diffs: bool = False
    show_side_by_side_diff: bool = False
    image_diff_type: str = "TwoUp"
    clone_default_directory: str = ""
    default_branch: str = "main"
    show_changes_filter: bool = True
    welcome_shown: bool = False
    window_width: int = 1280
    window_height: int = 800
    sidebar_width: int = 320
    commit_summary_width: int = 360
    selected_repository_id: int | None = None
    repository_section: str = "Changes"
    ask_for_confirmation_on_force_push: bool = True
    zoom_factor: float = 1.0
    last_thank_you_version: str = ""
    last_thank_you_users: list[str] = field(default_factory=list)
    recent_branches: dict[str, list[str]] = field(default_factory=dict)
    last_prune_dates: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})


def load_settings(path: Path | None = None) -> Settings:
    p = path or settings_path()
    if not p.exists():
        return Settings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return Settings()
        return Settings.from_dict(data)
    except (OSError, json.JSONDecodeError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    p = path or settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(settings.to_dict(), indent=2), encoding="utf-8")
