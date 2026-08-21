"""Desktop localStorage helpers, enum parsing, and status/CI duration helpers."""

from __future__ import annotations

from enum import StrEnum
from math import isnan
from threading import Event

from github_desktop.enum import parse_enum_value
from github_desktop.github.ci_checks import (
    format_long_precise_duration,
    format_precise_duration,
    get_check_duration_in_milliseconds,
    get_formatted_check_run_duration,
    get_formatted_check_run_long_duration,
)
from github_desktop.local_storage import (
    get_boolean,
    get_enum,
    get_float_number,
    get_number,
    get_number_array,
    get_object,
    get_string_array,
    set_boolean,
    set_number,
    set_number_array,
    set_object,
    set_string_array,
)
from github_desktop.models import (
    AppFileStatusKind,
    DEFAULT_CONFLICTS_RESOLVED_MESSAGE,
    FileStatus,
    GitStatusEntry,
    ManualConflictResolution,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
    get_branch_for_resolution,
    get_resolved_file_status_summary,
    get_resolved_files,
    get_unmerged_files,
    get_unmerged_status_entry_description,
    get_untracked_files,
    has_conflicted_files,
    is_conflicted_file,
)
from github_desktop.shells import reveal_in_file_manager
from github_desktop.store import AppStore
from github_desktop.features import get_feature_override, should_render_application_menu
from tests.conftest import run_git


class _Theme(StrEnum):
    LIGHT = "light"
    DARK = "dark"
    SYSTEM = "system"


def test_local_storage_boolean_number_and_arrays(isolated_config) -> None:
    assert get_boolean("missing") is None
    assert get_boolean("missing", False) is False
    set_boolean("flag", True)
    assert get_boolean("flag") is True
    set_boolean("flag", False)
    assert get_boolean("flag") is False
    set_boolean("legacy-true", True)
    assert get_boolean("legacy-true") is True

    set_number("count", 12)
    assert get_number("count") == 12
    assert get_number("missing-num", 7) == 7
    set_number("floaty", 3.5)
    assert get_float_number("floaty") == 3.5

    set_number_array("nums", [1, 2, 3])
    assert get_number_array("nums") == [1.0, 2.0, 3.0]
    set_string_array("names", ["ada", "grace"])
    assert get_string_array("names") == ["ada", "grace"]
    set_object("blob", {"a": 1})
    assert get_object("blob") == {"a": 1}
    assert parse_enum_value(_Theme, "dark") == "dark"
    assert parse_enum_value(_Theme, "nope") is None
    set_boolean("theme-key", False)  # not an enum
    from github_desktop.local_storage import set_item

    set_item("appearance", "system")
    assert get_enum("appearance", _Theme) == "system"


def test_feature_override_reads_local_storage(isolated_config, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_DESKTOP_FEATURE_SHOULD_RENDER_APPLICATION_MENU", raising=False)
    set_boolean("features/should-render-application-menu", False)
    assert get_feature_override("should-render-application-menu", True) is False
    monkeypatch.setenv("GITHUB_DESKTOP_FEATURE_SHOULD_RENDER_APPLICATION_MENU", "1")
    assert should_render_application_menu() is True


def test_status_helpers_match_desktop() -> None:
    markers = FileStatus(AppFileStatusKind.CONFLICTED, conflict_marker_count=2)
    resolved = FileStatus(AppFileStatusKind.CONFLICTED, conflict_marker_count=0)
    untracked = FileStatus(AppFileStatusKind.UNTRACKED)
    modified = FileStatus(AppFileStatusKind.MODIFIED)
    files = [
        WorkingDirectoryFileChange("a.txt", markers),
        WorkingDirectoryFileChange("b.txt", resolved),
        WorkingDirectoryFileChange("c.txt", untracked),
        WorkingDirectoryFileChange("d.txt", modified),
    ]
    wd = WorkingDirectoryStatus.from_files(files)
    assert has_conflicted_files(wd)
    assert is_conflicted_file(markers)
    assert not is_conflicted_file(modified)
    assert [f.path for f in get_unmerged_files(wd)] == ["a.txt", "b.txt"]
    assert [f.path for f in get_resolved_files(wd)] == ["b.txt"]
    assert [f.path for f in get_untracked_files(wd)] == ["c.txt"]
    assert get_unmerged_status_entry_description(GitStatusEntry.ADDED, "main") == "Using the added file from main"
    assert get_unmerged_status_entry_description(GitStatusEntry.DELETED) == "Using the deleted file"
    assert get_unmerged_status_entry_description(GitStatusEntry.UPDATED_BUT_UNMERGED, "topic") == (
        "Using the modified file from topic"
    )
    assert get_resolved_file_status_summary(resolved) == DEFAULT_CONFLICTS_RESOLVED_MESSAGE
    assert get_resolved_file_status_summary(
        FileStatus(AppFileStatusKind.CONFLICTED, conflict_marker_count=None, us=GitStatusEntry.ADDED),
        ManualConflictResolution.OURS,
        "main",
    ) == "Using the added file from main"
    assert get_branch_for_resolution(ManualConflictResolution.OURS, "main", "topic") == "main"
    assert get_branch_for_resolution(ManualConflictResolution.THEIRS, "main", "topic") == "topic"
    assert get_branch_for_resolution(None, "main", "topic") is None


def test_check_run_duration_formatters() -> None:
    assert format_precise_duration(3_670_000) == "1h 1m 10s"
    assert format_long_precise_duration(3_670_000) == "1 hour 1 minute 10 seconds"
    step = {"started_at": "2024-01-01T00:00:00Z", "completed_at": "2024-01-01T01:01:10Z"}
    assert get_formatted_check_run_duration(step) == "1h 1m 10s"
    assert get_formatted_check_run_long_duration(step) == "1 hour 1 minute 10 seconds"
    assert isnan(get_check_duration_in_milliseconds({"started_at": None, "completed_at": None}))
    assert get_formatted_check_run_duration({"started_at": "nope", "completed_at": "nope"}) == ""


def test_try_get_ahead_behind_is_cache_only(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repo = store.add_repositories([str(git_repo)])[0]
    calls: list[str] = []

    def fake_range(path: str, spec: str):
        calls.append(spec)
        from github_desktop.models import AheadBehind

        return AheadBehind(ahead=2, behind=1)

    monkeypatch.setattr("github_desktop.store.get_ahead_behind_range", fake_range)
    assert store.try_get_ahead_behind(repo, "aaa", "bbb") is None
    assert calls == []
    done = Event()
    got = {}

    def on_ab(ab) -> None:
        got["ab"] = ab
        done.set()

    cancel = store.request_ahead_behind(repo, "aaa", "bbb", on_ab)
    assert done.wait(2)
    assert got["ab"].ahead == 2
    assert store.try_get_ahead_behind(repo, "aaa", "bbb") is got["ab"]
    assert len(calls) == 1
    cancel()
    again = store.try_get_ahead_behind(repo, "aaa", "bbb")
    assert again is not None and again.ahead == 2


def test_request_ahead_behind_does_not_retry_failures(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repo = store.add_repositories([str(git_repo)])[0]
    calls = {"n": 0}

    def fake_range(path: str, spec: str):
        calls["n"] += 1
        return None

    monkeypatch.setattr("github_desktop.store.get_ahead_behind_range", fake_range)
    store.request_ahead_behind(repo, "aaa", "bbb", lambda _ab: None)
    import time

    deadline = time.time() + 2
    key = (repo.path, "aaa", "bbb")
    while time.time() < deadline and key not in store._ahead_behind_cache:
        time.sleep(0.02)
    assert key in store._ahead_behind_cache
    assert store._ahead_behind_cache[key] is None
    fired = {"v": False}
    store.request_ahead_behind(repo, "aaa", "bbb", lambda _ab: fired.__setitem__("v", True))
    assert fired["v"] is False
    assert calls["n"] == 1


def test_reveal_in_file_manager_joins_repo_path(git_repo, monkeypatch) -> None:
    from github_desktop.models import Repository

    opened: list[str] = []
    monkeypatch.setattr("github_desktop.shells.open_file_manager", lambda path: opened.append(path))
    repo = Repository(id=1, path=str(git_repo), name="repo")
    reveal_in_file_manager(repo, "README.md")
    assert opened == [str(git_repo / "README.md")]
