"""Usage stats store matching Desktop `lib/stats/stats-store.ts`."""

from __future__ import annotations

from github_desktop.changelog import CHANGELOG_URL, get_change_log, notes_from_changelog
from github_desktop.exception_reporting import ErrorEndpoint, report_error
from github_desktop.linux import get_architecture, get_os
from github_desktop.settings import Settings
from github_desktop.stats import (
    SamplesURL,
    StatsEndpoint,
    StatsResponse,
    StatsStore,
    get_has_opted_out_of_stats,
    get_renderer_guid,
)
from github_desktop.store import AppStore
from github_desktop.welcome import mark_welcome_flow_complete


def test_native_default_is_opted_out(isolated_config) -> None:
    store = StatsStore(default_opt_out=True)
    assert store.get_opt_out() is True
    posted: list[dict] = []

    def fake_post(body):
        posted.append(dict(body))
        return StatsResponse(200, "OK")

    reporting = StatsStore(post=fake_post, default_opt_out=True)
    reporting.report_stats([], [])
    assert posted == []


def test_increment_and_payload(isolated_config) -> None:
    posted: list[dict] = []

    def fake_post(body):
        posted.append(dict(body))
        return StatsResponse(200, "OK")

    stats = StatsStore(post=fake_post, default_opt_out=True)
    stats.increment("commits", 2)
    stats.increment("openShellCount")
    stats.record_commit()
    stats.note_ui_activity()
    measures = stats.get_daily_measures()
    assert measures["commits"] == 3
    assert measures["openShellCount"] == 1
    assert measures["active"] is True
    stats.set_opt_out(False)
    mark_welcome_flow_complete()
    stats.report_stats([], [], Settings(welcome_shown=True, opt_out_of_usage_tracking=False))
    assert any(item.get("eventType") == "ping" and item.get("optIn") is True for item in posted)
    usage = next(item for item in posted if item.get("eventType") == "usage")
    assert usage["platform"] == "linux"
    assert usage["architecture"] in {"x64", "arm64"}
    assert usage["commits"] == 3
    assert usage["guid"]
    assert usage["diffMode"] in {"split", "unified"}
    assert usage["launchedFromApplicationsFolder"] is None
    assert stats.get_daily_measures()["commits"] == 0


def test_push_and_opt_out_local_storage(isolated_config) -> None:
    stats = StatsStore(default_opt_out=True)
    stats.record_push(None, force_with_lease=True)
    assert stats.get_daily_measures()["externalForcePushCount"] == 1
    stats.set_opt_out(False)
    assert get_has_opted_out_of_stats() is False
    guid = get_renderer_guid()
    assert guid == get_renderer_guid()
    assert SamplesURL.startswith("https://desktop.github.com/")
    assert StatsEndpoint.startswith("https://central.github.com/")


def test_app_store_skips_network_under_pytest(isolated_config, git_repo) -> None:
    store = AppStore()
    assert store.stats.get_opt_out() is True
    repos = store.add_repositories([str(git_repo)])
    assert repos
    store.report_stats()
    store.set_stats_opt_out(False)
    assert store.settings.opt_out_of_usage_tracking is False
    assert get_has_opted_out_of_stats() is False


def test_get_change_log_skips_network_in_pytest(isolated_config) -> None:
    assert get_change_log() == []
    assert CHANGELOG_URL.endswith("changelog.json")
    notes = notes_from_changelog(
        [{"version": "3.5.4", "notes": ["[Fixed] A thing. Thanks @octocat!"]}]
    )
    assert notes == ["[Fixed] A thing. Thanks @octocat!"]


def test_architecture_and_os() -> None:
    assert get_architecture() in {"x64", "arm64"}
    assert "Linux" in get_os() or "linux" in get_os().lower()


def test_report_error_skips_pytest(isolated_config) -> None:
    assert ErrorEndpoint.endswith("/exception")
    report_error(RuntimeError("boom"))
