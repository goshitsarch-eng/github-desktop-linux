"""Desktop git terminal output, formatDate, clamp, directoryExists, HttpStatusCode."""

from __future__ import annotations

from datetime import datetime, timezone

from github_desktop.clamp import clamp
from github_desktop.directory_exists import directory_exists
from github_desktop.feature_flag import (
    enable_checkout_commit,
    enable_custom_integration,
    enable_filtered_changes_list,
    enable_multiple_enterprise_accounts,
    enable_recurse_submodules_flag,
    enable_reset_to_commit,
    enable_resizing_toolbar_buttons,
)
from github_desktop.format_date import format_date
from github_desktop.git.progress import (
    TERMINAL_OUTPUT_CAPACITY,
    create_tail_stream,
    create_terminal_output,
    parse_carriage_return,
)
from github_desktop.git.runner import _prepare_env
from github_desktop.http_status import HttpStatusCode
from github_desktop.secrets import GENERIC_GIT_AUTH_USERNAME_KEY_PREFIX


def test_parse_carriage_return_and_tail() -> None:
    assert parse_carriage_return("Downloading: 1%\rDownloading: 2%\r") == "Downloading: 2%"
    assert TERMINAL_OUTPUT_CAPACITY == 256 * 1024
    assert create_tail_stream("abc") == "abc"
    long = "x" * (TERMINAL_OUTPUT_CAPACITY + 50)
    tailed = create_tail_stream(long)
    assert len(tailed.encode("utf-8")) == TERMINAL_OUTPUT_CAPACITY
    assert create_terminal_output("", "fatal: boom\n") == "fatal: boom\n"


def test_term_is_forced_dumb() -> None:
    env = _prepare_env({"TERM": "xterm-256color"})
    assert env["TERM"] == "dumb"


def test_format_date_and_invalid() -> None:
    assert format_date(None) == "Invalid date"
    when = datetime(2026, 8, 21, 13, 27, tzinfo=timezone.utc)
    text = format_date(when)
    assert "2026" in text
    assert "August" in text


def test_clamp_directory_exists_and_http_status(tmp_path) -> None:
    from github_desktop.clamp import ConstrainedValue, constrain

    assert clamp(0.5, 0.7, 3.0) == 0.7
    assert clamp(4.0, 0.7, 3.0) == 3.0
    assert clamp(1.2, 0.7, 3.0) == 1.2
    limited = constrain(400, 220, 100)
    assert limited.min == 220
    assert limited.max == 220
    assert clamp(limited) == 220
    assert clamp(ConstrainedValue(50, min=10, max=40)) == 40
    assert directory_exists(str(tmp_path)) is True
    assert directory_exists(str(tmp_path / "missing")) is False
    assert HttpStatusCode.NotModified == 304
    assert HttpStatusCode.Unauthorized == 401
    assert GENERIC_GIT_AUTH_USERNAME_KEY_PREFIX == "genericGitAuth/username/"


def test_production_feature_flags() -> None:
    assert enable_recurse_submodules_flag() is True
    assert enable_reset_to_commit() is True
    assert enable_checkout_commit() is True
    assert enable_custom_integration() is True
    assert enable_resizing_toolbar_buttons() is True
    assert enable_filtered_changes_list() is True
    assert enable_multiple_enterprise_accounts() is True
