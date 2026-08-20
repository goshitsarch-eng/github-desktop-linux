"""Desktop-parity: intra-line diffs, push_control, combined status, repo grouping, GHE avatars."""

from __future__ import annotations

from github_desktop.avatars import avatar_urls, get_email_avatar_url
from github_desktop.changed_range import (
    apply_inner_highlight,
    get_diff_tokens,
    relative_changes,
    wrap_pango_visible_range,
)
from github_desktop.github.ci_checks import api_status_to_ref_check, summarize_check_runs
from github_desktop.github.push_control import PushControl, default_push_control, is_branch_pushable
from github_desktop.group_repositories import (
    RECENT_REPOSITORIES_THRESHOLD,
    group_repositories,
)
from github_desktop.models import (
    GitHubRepository,
    Repository,
    has_write_permission,
    is_dotcom_endpoint,
    is_ghe_endpoint,
    is_ghes_endpoint,
)
from github_desktop.settings import Settings, load_settings, save_settings


def test_relative_changes_prefix_and_suffix() -> None:
    deleted, added = relative_changes("hello world", "hello there")
    assert "hello world"[deleted.location : deleted.location + deleted.length] == "world"
    assert "hello there"[added.location : added.location + added.length] == "there"
    empty_a, empty_b = relative_changes("same", "same")
    assert empty_a.length == 0
    assert empty_b.length == 0
    whole_a, whole_b = relative_changes("abc", "xyz")
    assert whole_a.location == 0 and whole_a.length == 3
    assert whole_b.location == 0 and whole_b.length == 3


def test_get_diff_tokens_and_pango_wrap() -> None:
    delete_range, add_range = get_diff_tokens("foo bar", "foo baz")
    assert "foo bar"[delete_range.location : delete_range.location + delete_range.length] == "r"
    assert "foo baz"[add_range.location : add_range.location + add_range.length] == "z"
    markup = wrap_pango_visible_range("a&lt;b", 1, 1, "<span>", "</span>")
    assert markup == "a<span>&lt;</span>b"
    highlighted = apply_inner_highlight("hello world", 6, 5, "#8ff0a4")
    assert '<span background="#8ff0a4">world</span>' in highlighted


def test_is_branch_pushable_defaults_to_allow() -> None:
    assert is_branch_pushable(default_push_control())
    assert is_branch_pushable(PushControl(allow_actor=None))
    assert not is_branch_pushable(PushControl(allow_actor=False))
    assert not is_branch_pushable(PushControl(required_status_checks=["ci"]))
    assert not is_branch_pushable(PushControl(required_approving_review_count=1))
    assert has_write_permission(None)
    read_only = GitHubRepository("r", "o", "https://github.com/o/r", "https://github.com/o/r.git", permissions="read")
    assert not has_write_permission(read_only)


def test_api_status_to_ref_check() -> None:
    success = api_status_to_ref_check(
        {"id": 9, "context": "continuous-integration/travis-ci/push", "state": "success", "target_url": "https://travis"}
    )
    assert success.name == "continuous-integration/travis-ci/push"
    assert success.status == "completed"
    assert success.conclusion == "success"
    pending = api_status_to_ref_check({"id": 1, "context": "ci", "state": "pending"})
    assert pending.status == "in_progress"
    assert pending.conclusion is None
    failed = api_status_to_ref_check({"id": 2, "context": "ci", "state": "failure"})
    assert failed.conclusion == "failure"
    assert summarize_check_runs([success, pending]) == "pending"


def test_group_repositories_recent_owner_and_other() -> None:
    def gh(owner: str, name: str, endpoint: str = "https://api.github.com") -> GitHubRepository:
        html = "https://github.com" if "api.github.com" in endpoint else endpoint.replace("/api/v3", "")
        return GitHubRepository(name, owner, f"{html}/{owner}/{name}", f"{html}/{owner}/{name}.git", endpoint=endpoint)

    repos = [
        Repository(i, f"/tmp/{i}", f"repo{i}", github=gh("alice" if i < 4 else "bob", f"repo{i}"))
        for i in range(1, 8)
    ]
    repos.append(Repository(8, "/tmp/local", "local"))
    repos.append(
        Repository(
            9,
            "/tmp/ent",
            "ent",
            github=gh("org", "ent", "https://github.example.com/api/v3"),
        )
    )
    assert len(repos) > RECENT_REPOSITORIES_THRESHOLD
    groups = group_repositories(repos, [8, 1])
    labels = [group.label for group in groups]
    assert labels[0] == "Recent"
    assert "alice" in labels
    assert "bob" in labels
    assert "github.example.com" in labels
    assert "Other" in labels
    recent = next(group for group in groups if group.kind == "recent")
    assert {item.repository.id for item in recent.items} == {8, 1}


def test_ghe_avatar_urls_require_token() -> None:
    assert is_dotcom_endpoint("https://api.github.com")
    assert is_ghe_endpoint("https://api.acme.ghe.com")
    assert is_ghes_endpoint("https://github.example.com/api/v3")
    assert get_email_avatar_url("https://github.example.com/api/v3").endswith("/enterprise/avatars/u/e")
    assert "/avatars/u/e" in get_email_avatar_url("https://api.acme.ghe.com")
    assert get_email_avatar_url("https://api.acme.ghe.com").startswith("https://acme.ghe.com/")
    without = avatar_urls(email="a@b.com", endpoint="https://api.acme.ghe.com", avatar_url="https://avatars.ghe.com/u/1")
    assert without
    assert all("token=" not in url for url in without)
    with_token = avatar_urls(
        email="a@b.com",
        endpoint="https://api.acme.ghe.com",
        avatar_token="secret",
    )
    assert any("token=secret" in url for url in with_token)


def test_recent_repository_ids_roundtrip(tmp_path) -> None:
    path = tmp_path / "settings.json"
    settings = Settings(recent_repository_ids=[3, 1, 2])
    save_settings(settings, path)
    loaded = load_settings(path)
    assert loaded.recent_repository_ids == [3, 1, 2]
