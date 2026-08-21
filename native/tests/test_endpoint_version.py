"""GHES endpoint version cache and clone-list owner filtering."""

from __future__ import annotations

from github_desktop.github.api import GitHubAPI
from github_desktop.local_storage import get_item
from github_desktop.remote_parsing import (
    get_endpoint_version,
    try_update_endpoint_version_from_response,
    update_endpoint_version,
)
from github_desktop import remote_parsing


def test_endpoint_version_persists_in_local_storage(isolated_config) -> None:
    endpoint = "https://ghe.example/api/v3"
    update_endpoint_version(endpoint, "3.12.1")
    assert get_item("endpoint-version:https://ghe.example/api/v3") == "3.12.1"
    remote_parsing._endpoint_versions.clear()
    assert get_endpoint_version(endpoint) == "3.12.1"


def test_try_update_endpoint_version_from_response(isolated_config) -> None:
    endpoint = "https://ghe.example/api/v3"
    try_update_endpoint_version_from_response(
        endpoint, {"x-github-enterprise-version": "3.5.0"}
    )
    assert get_endpoint_version(endpoint) == "3.5.0"


def test_fetch_repos_skips_null_owner() -> None:
    api = GitHubAPI("https://api.github.com", "token")

    def fake_paginate(*_args, **_kwargs):
        return [
            {
                "name": "ok",
                "owner": {"login": "me"},
                "html_url": "https://github.com/me/ok",
                "clone_url": "https://github.com/me/ok.git",
            },
            {"name": "dangling", "owner": None},
        ]

    api._paginate = fake_paginate  # type: ignore[method-assign]
    repos = api.fetch_repos()
    assert [item.name for item in repos] == ["ok"]
    assert repos[0].owner == "me"
