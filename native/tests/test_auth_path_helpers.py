"""Desktop auth keys, path safety, media types, RelativeTime, and helpers."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from github_desktop.auth import get_key_for_account, get_key_for_endpoint
from github_desktop.compare import (
    case_insensitive_compare,
    case_insensitive_equals,
    compare,
    compare_descending,
)
from github_desktop.desktop_fake_repository import DesktopFakeRepository, desktop_url
from github_desktop.errors import CopilotError
from github_desktop.fatal_error import assert_never, assert_non_nullable, fatal_error, force_unwrap
from github_desktop.file_system import get_temp_file_path, read_partial_file
from github_desktop.format_relative import format_relative, get_relative_time_info_from_date
from github_desktop.git.diff import get_media_type
from github_desktop.git.progress import create_lfs_progress_file
from github_desktop.http_status import HttpStatusCode
from github_desktop.models import Account, friendly_endpoint_name
from github_desktop.path import encode_path_as_url, resolve_within
from github_desktop.push_pull import format_commit_relative_time, format_last_fetched, format_relative_past


def test_get_key_for_endpoint_and_account(monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_DESKTOP_DEV", raising=False)
    endpoint = "https://api.github.com"
    assert get_key_for_endpoint(endpoint) == "GitHub - https://api.github.com"
    account = Account(login="octocat", endpoint=endpoint, token="t")
    assert get_key_for_account(account) == get_key_for_endpoint(endpoint)
    monkeypatch.setenv("GITHUB_DESKTOP_DEV", "1")
    assert get_key_for_endpoint(endpoint) == "GitHub Desktop Dev - https://api.github.com"


def test_account_token_desktop_key_and_legacy_fallback(isolated_config) -> None:
    from github_desktop import secrets

    endpoint = "https://api.github.com"
    secrets.set_token(f"{endpoint}|octocat", "legacy-token")
    assert secrets.get_account_token(endpoint, "octocat") == "legacy-token"
    secrets.set_account_token(endpoint, "octocat", "desktop-token")
    assert secrets.get_account_token(endpoint, "octocat") == "desktop-token"
    assert secrets.get_token(f"{endpoint}|octocat") is None
    secrets.delete_account_token(endpoint, "octocat")
    assert secrets.get_account_token(endpoint, "octocat") is None


def test_desktop_fake_repository() -> None:
    assert DesktopFakeRepository.id == -1
    assert DesktopFakeRepository.path == ""
    assert DesktopFakeRepository.is_missing is True
    assert DesktopFakeRepository.github is not None
    assert DesktopFakeRepository.github.owner == "desktop"
    assert DesktopFakeRepository.github.name == "desktop"
    assert DesktopFakeRepository.github.html_url == desktop_url
    assert DesktopFakeRepository.github.html_url == "https://github.com/desktop/desktop"


def test_get_media_type_matches_desktop() -> None:
    assert get_media_type(".png") == "image/png"
    assert get_media_type(".jpg") == "image/jpg"
    assert get_media_type(".jpeg") == "image/jpg"
    assert get_media_type(".dds") == "image/vnd-ms.dds"
    assert get_media_type(".exe") == "text/plain"
    assert get_media_type(".JPG") == "image/jpg"


def test_get_temp_file_path_does_not_create() -> None:
    path = get_temp_file_path("squashTodo")
    name = os.path.basename(path)
    assert name.startswith("squashTodo-")
    assert len(name.split("-", 1)[1]) == 16
    assert not os.path.exists(path)


def test_read_partial_file_inclusive_end(tmp_path) -> None:
    target = tmp_path / "blob.bin"
    target.write_bytes(b"abcdefghij")
    assert read_partial_file(str(target), 0, 3) == b"abcd"
    assert read_partial_file(str(target), 2, 5) == b"cdef"


def test_resolve_within_blocks_escape(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    inside = resolve_within(str(root), "README.md")
    assert inside is not None
    assert Path(inside).name == "README.md"
    assert resolve_within(str(root), "..") is None
    assert resolve_within(str(root), "foo\0bar") is None
    assert resolve_within("", "README.md") is None
    outside = tmp_path / "secret.txt"
    outside.write_text("nope\n", encoding="utf-8")
    link = root / "escape"
    link.symlink_to(outside)
    assert resolve_within(str(root), "escape") is None
    uri = encode_path_as_url(str(root), "README.md")
    assert uri.startswith("file://")
    assert "README.md" in uri


def test_fatal_error_and_force_unwrap() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        fatal_error("boom")
    with pytest.raises(RuntimeError, match="missing"):
        force_unwrap("missing", None)
    assert force_unwrap("false is an expected value", False) is False
    assert force_unwrap("zero is an expected value", 0) == 0
    assert assert_non_nullable("ok", "needed") == "ok"
    with pytest.raises(RuntimeError, match="never"):
        assert_never("x", "never")


def test_compare_and_case_insensitive() -> None:
    assert compare(1, 2) == -1
    assert compare(2, 1) == 1
    assert compare("a", "a") == 0
    assert compare_descending(1, 2) == 1
    assert case_insensitive_equals("Ab", "aB")
    assert case_insensitive_compare("b.txt", "A.txt") == 1
    assert case_insensitive_compare("a.txt", "B.txt") == -1


def test_format_relative_and_relative_time() -> None:
    assert format_relative(0) == "now"
    assert format_relative(-1000) == "1 second ago"
    assert format_relative(1000) == "in 1 second"
    assert format_relative(-40_000) == "40 seconds ago"
    assert format_relative(-90_000) == "2 minutes ago"
    assert format_relative(-86_400_000) == "yesterday"
    assert format_relative(86_400_000) == "tomorrow"
    assert format_relative(-2 * 86_400_000) == "2 days ago"
    now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
    info = get_relative_time_info_from_date(now, only_relative=True, now=now)
    assert info["relative_text"] == "just now"
    later = datetime(2026, 8, 21, 12, 0, 50, tzinfo=timezone.utc)
    recent = get_relative_time_info_from_date(later, now=now)
    assert recent["relative_text"] == "just now"
    assert format_relative_past(50) == "just now"
    assert format_relative_past(10 * 60) == "10 minutes ago"
    assert format_last_fetched(100.0, now=100.0) == "Last fetched just now"
    assert "minutes ago" in format_last_fetched(100.0, now=100.0 + 10 * 60)
    assert format_commit_relative_time(now, now=now) == "just now"


def test_copilot_quota_and_friendly_endpoint() -> None:
    err = CopilotError("You have reached your quota limit.", HttpStatusCode.PaymentRequired)
    assert err.is_quota_exceeded_error is True
    assert CopilotError("nope").is_quota_exceeded_error is False
    dotcom = Account(login="octocat", endpoint="https://api.github.com", token="")
    assert friendly_endpoint_name(dotcom) == "GitHub.com"
    assert dotcom.friendly_endpoint == "GitHub.com"
    enterprise = Account(login="ada", endpoint="https://github.example.com/api/v3", token="")
    assert friendly_endpoint_name(enterprise) == "github.example.com"
    assert enterprise.friendly_endpoint == "github.example.com"


def test_generic_git_auth_desktop_keys(isolated_config) -> None:
    from github_desktop.generic_git_auth import (
        delete_generic_credential,
        get_generic_password,
        get_generic_username,
        set_generic_credential,
    )

    endpoint = "https://gitlab.example.com/org/repo.git"
    set_generic_credential(endpoint, "alice", "s3cret")
    assert get_generic_username(endpoint) == "alice"
    assert get_generic_password(endpoint, "alice") == "s3cret"
    from github_desktop import secrets

    user, password = secrets.get_generic("gitlab.example.com")
    assert user == "alice"
    assert password == "s3cret"
    delete_generic_credential(endpoint, "alice")
    assert get_generic_password(endpoint, "alice") is None


def test_create_lfs_progress_file_uses_temp_name() -> None:
    path = create_lfs_progress_file()
    try:
        assert os.path.isfile(path)
        assert os.path.basename(path).startswith("GitHubDesktop-lfs-progress-")
        assert os.path.getsize(path) == 0
    finally:
        os.remove(path)
