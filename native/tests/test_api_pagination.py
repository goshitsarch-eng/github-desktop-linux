"""Desktop `getNextPagePathWithIncreasingPageSize` and incremental PR fetches."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from github_desktop.errors import APIError
from github_desktop.github.api import (
    GitHubAPI,
    get_next_page_path_from_link,
    get_next_page_path_with_increasing_page_size,
    url_with_query_string,
)
from github_desktop.offset_from import offset_from, offset_from_now


def _link(url: str) -> dict[str, str]:
    return {"Link": f'<{url}>; rel="next"'}


def _assert_next(current: tuple[int, int], expected: tuple[int, int]) -> None:
    per_page, page = current
    headers = _link(f"/items?per_page={per_page}&page={page}")
    next_path = get_next_page_path_with_increasing_page_size(headers)
    assert next_path is not None
    parsed = urlsplit(next_path)
    query = parse_qs(parsed.query)
    assert parsed.path == "/items"
    got_per_page = int(query["per_page"][0])
    got_page = int(query["page"][0])
    assert (got_per_page, got_page) == expected
    if current != expected:
        received_current = per_page * page
        received_next = got_per_page * got_page
        assert received_next > received_current


def test_url_with_query_string() -> None:
    assert url_with_query_string("/repos/o/r/pulls", {"state": "open"}) == "/repos/o/r/pulls?state=open"
    assert (
        url_with_query_string("/repos/o/r/pulls?state=open", {"per_page": "10"})
        == "/repos/o/r/pulls?state=open&per_page=10"
    )


def test_get_next_page_path_from_link() -> None:
    assert get_next_page_path_from_link({}) is None
    assert get_next_page_path_from_link(_link("/items?page=2")) == "/items?page=2"
    assert (
        get_next_page_path_from_link(
            _link("https://api.github.com/repos/o/r/pulls?page=2&per_page=10")
        )
        == "/repos/o/r/pulls?page=2&per_page=10"
    )


def test_increasing_page_size_returns_raw_when_incomplete() -> None:
    assert get_next_page_path_with_increasing_page_size({}) is None
    assert get_next_page_path_with_increasing_page_size(_link("/items?page=2")) == "/items?page=2"
    assert (
        get_next_page_path_with_increasing_page_size(_link("/items?per_page=10"))
        == "/items?per_page=10"
    )
    assert (
        get_next_page_path_with_increasing_page_size(_link("/items?per_page=10&page=2"))
        == "/items?per_page=10&page=2"
    )


def test_increasing_page_size_from_10() -> None:
    _assert_next((10, 2), (10, 2))
    _assert_next((10, 3), (20, 2))
    _assert_next((20, 2), (20, 2))
    _assert_next((20, 3), (40, 2))
    _assert_next((40, 2), (40, 2))
    _assert_next((40, 3), (80, 2))
    _assert_next((80, 3), (80, 3))
    _assert_next((80, 4), (80, 4))
    _assert_next((80, 5), (80, 5))
    _assert_next((80, 6), (100, 5))


def test_increasing_page_size_from_5_and_1() -> None:
    _assert_next((5, 2), (5, 2))
    _assert_next((5, 3), (10, 2))
    _assert_next((1, 2), (1, 2))
    _assert_next((1, 3), (2, 2))
    _assert_next((2, 3), (4, 2))
    _assert_next((4, 2), (4, 2))
    _assert_next((4, 3), (8, 2))
    _assert_next((8, 2), (8, 2))
    _assert_next((8, 3), (16, 2))
    _assert_next((16, 2), (16, 2))
    _assert_next((16, 3), (32, 2))
    _assert_next((32, 2), (32, 2))
    _assert_next((32, 3), (64, 2))


def test_increasing_page_size_caps_at_100() -> None:
    for page in range(2, 11):
        _assert_next((100, page), (100, page))


def test_fetch_updated_pull_requests_does_not_skip_items() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def _pr(number: int, updated: str) -> dict:
        return {
            "number": number,
            "title": str(number),
            "updated_at": updated,
            "created_at": updated,
            "user": {},
            "head": {},
            "base": {},
            "html_url": "",
            "state": "open",
        }

    catalog = [_pr(n, "2026-08-01T00:00:00Z") for n in range(1, 36)]
    catalog.extend(_pr(n, "2019-01-01T00:00:00Z") for n in range(36, 41))

    def fake_request(method, path, **kwargs):
        seen.append(path)
        parsed = urlsplit(path)
        query = parse_qs(parsed.query)
        per_page = int(query.get("per_page", ["10"])[0])
        page = int(query.get("page", ["1"])[0])
        start = (page - 1) * per_page
        batch = catalog[start : start + per_page]
        next_start = start + per_page
        headers: dict[str, str] = {}
        if next_start < len(catalog):
            headers["link"] = (
                f"<{parsed.path}?state=all&sort=updated&direction=desc"
                f"&per_page={per_page}&page={page + 1}>; rel=\"next\""
            )
        if kwargs.get("return_headers"):
            return batch, headers
        return batch

    api.request = fake_request  # type: ignore[method-assign]
    prs = api.fetch_updated_pull_requests("o", "r", "2020-01-01T00:00:00Z")
    numbers = [pr.number for pr in prs]
    assert numbers == list(range(1, 36))
    # First two requests stay at per_page=10; the third remaps to per_page=20 page=2.
    assert "per_page=10" in seen[0]
    assert "per_page=10" in seen[1] and "page=2" in seen[1]
    assert "per_page=20" in seen[2] and "page=2" in seen[2]


def test_fetch_all_open_and_named_list_endpoints() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        if kwargs.get("return_headers"):
            return [{"number": 1, "title": "hi", "user": {}, "head": {}, "base": {}, "html_url": ""}], {}
        return [{"id": 1}]

    def fake_get(path, **kwargs):
        seen.append(path)
        if "reviews" in path and path.endswith("comments"):
            return [{"id": 3}]
        if path.endswith("/reviews"):
            return [{"id": 2}]
        if "/issues/" in path and path.endswith("/comments"):
            return [{"id": 4}]
        if path.endswith("/jobs"):
            return {"jobs": [{"id": 9}]}
        return []

    api.request = fake_request  # type: ignore[method-assign]
    api.get = fake_get  # type: ignore[method-assign]
    prs = api.fetch_all_open_pull_requests("o", "r")
    assert prs[0].number == 1
    assert "state=open" in seen[0]
    assert "sort=" not in seen[0]
    assert api.fetch_pull_request_reviews("o", "r", 1) == [{"id": 2}]
    assert api.fetch_pull_request_review_comments("o", "r", 1, 2) == [{"id": 3}]
    assert api.fetch_issue_comments("o", "r", 7) == [{"id": 4}]
    jobs = api.fetch_workflow_run_jobs("o", "r", 11)
    assert jobs == {"jobs": [{"id": 9}]}
    assert seen[-1] == "/repos/o/r/actions/runs/11/jobs"


def test_offset_from_matches_desktop_units() -> None:
    assert offset_from(0, 50, "minutes") == 3_000_000
    assert offset_from(0, -24, "hours") == -86_400_000
    assert offset_from(0, -14, "days") == -1_209_600_000
    now = 1_700_000_000_000
    assert offset_from(now, -24, "hours") == now - 86_400_000
    assert offset_from_now(0, "seconds")  # smoke: returns epoch ms


def _repo_payload(name: str, owner: str | None = "me") -> dict:
    return {
        "name": name,
        "owner": None if owner is None else {"login": owner},
        "html_url": f"https://github.com/{owner or 'gone'}/{name}",
        "clone_url": f"https://github.com/{owner or 'gone'}/{name}.git",
    }


def test_fetch_all_invokes_on_page_and_continue() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []
    pages: list[list] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        if "page=2" in path:
            return [_repo_payload("two")], {}
        return [_repo_payload("one")], {"Link": '</user/repos?page=2>; rel="next"'}

    api.request = fake_request  # type: ignore[method-assign]
    buf = api.fetch_all("user/repos", on_page=pages.append, continue_fn=lambda _items: False)
    assert [item["name"] for item in buf] == ["one"]
    assert len(pages) == 1
    assert len(seen) == 1

    seen.clear()
    pages.clear()
    buf = api.fetch_all("user/repos", on_page=pages.append)
    assert [item["name"] for item in buf] == ["one", "two"]
    assert len(pages) == 2


def test_stream_user_repositories_skips_null_owner_and_pages() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    received: list[str] = []

    def fake_request(method, path, **kwargs):
        return [_repo_payload("ok"), _repo_payload("dangling", None)], {}

    api.request = fake_request  # type: ignore[method-assign]
    api.stream_user_repositories(lambda page: received.extend(item.name for item in page))
    assert received == ["ok"]


def test_load_cloneable_repositories_splits_affiliations_after_first_page() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []
    names: list[str] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        if "affiliation=owner" in path:
            return [_repo_payload("owned")], {}
        if "affiliation=collaborator" in path:
            return [_repo_payload("collab")], {}
        if "affiliation=organization_member" in path:
            return [_repo_payload("org")], {}
        return [_repo_payload("first")], {"Link": '</user/repos?page=2>; rel="next"'}

    api.request = fake_request  # type: ignore[method-assign]
    api.load_cloneable_repositories(lambda page: names.extend(item.name for item in page))
    assert "first" in names
    assert {"owned", "collab", "org"} <= set(names)
    assert any("affiliation=owner" in path for path in seen)
    assert any("affiliation=collaborator" in path for path in seen)
    assert any("affiliation=organization_member" in path for path in seen)
    assert not any("page=2" in path and "affiliation=" not in path for path in seen)


def test_fetch_orgs_follows_link_headers() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        if "page=2" in path:
            return [{"login": "beta"}], {}
        return [{"login": "acme"}], {"Link": '</user/orgs?page=2>; rel="next"'}

    api.request = fake_request  # type: ignore[method-assign]
    assert [item["login"] for item in api.fetch_orgs()] == ["acme", "beta"]
    assert any("user/orgs" in path for path in seen)
    assert not any("?page=1" in path or "&page=1" in path for path in seen)


def test_fetch_issues_skips_pull_requests() -> None:
    api = GitHubAPI("https://api.github.com", "tok")

    def fake_request(method, path, **kwargs):
        assert "repos/o/r/issues" in path
        return [
            {"number": 1, "title": "bug", "state": "open", "updated_at": "2024-01-01T00:00:00Z"},
            {
                "number": 2,
                "title": "pr",
                "state": "open",
                "updated_at": "2024-01-02T00:00:00Z",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/2"},
            },
        ], {}

    api.request = fake_request  # type: ignore[method-assign]
    issues = api.fetch_issues("o", "r")
    assert [item.number for item in issues] == [1]
    assert issues[0].title == "bug"


def test_create_repository_org_and_network_errors() -> None:
    api = GitHubAPI("https://api.github.com", "tok")

    def fail_org(method, path, **kwargs):
        raise APIError("exists", status=422, body="already exists")

    api.request = fail_org  # type: ignore[method-assign]
    with pytest.raises(APIError, match="Unable to create repository for organization 'acme'"):
        api.create_repository("hello", org="acme")

    def fail_net(method, path, **kwargs):
        raise APIError("offline", status=None)

    api.request = fail_net  # type: ignore[method-assign]
    with pytest.raises(APIError, match="Unable to publish repository"):
        api.create_repository("hello")


def test_fetch_protected_branches_is_a_single_get() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        payload = [{"name": "release"}, {"name": "main"}]
        if kwargs.get("return_headers"):
            return payload, {"Link": '</repos/o/r/branches?page=2>; rel="next"'}
        return payload

    api.request = fake_request  # type: ignore[method-assign]
    assert api.fetch_protected_branches("o", "r") == ["release", "main"]
    assert len(seen) == 1
    assert "protected=true" in seen[0]


def test_fetch_user_by_login_404_is_none_other_errors_raise() -> None:
    from github_desktop.http_status import HttpStatusCode

    api = GitHubAPI("https://api.github.com", "tok")

    def not_found(method, path, **kwargs):
        raise APIError("gone", status=HttpStatusCode.NotFound)

    api.request = not_found  # type: ignore[method-assign]
    assert api.fetch_user_by_login("ghost") is None

    def fail(method, path, **kwargs):
        raise APIError("boom", status=500)

    api.request = fail  # type: ignore[method-assign]
    with pytest.raises(APIError, match="boom"):
        api.fetch_user_by_login("octocat")


def test_fetch_pull_request_comments_is_a_single_get() -> None:
    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_request(method, path, **kwargs):
        seen.append(path)
        payload = [{"id": 1}]
        if kwargs.get("return_headers"):
            return payload, {"Link": '</repos/o/r/pulls/3/comments?page=2>; rel="next"'}
        return payload

    api.request = fake_request  # type: ignore[method-assign]
    assert api.fetch_pull_request_comments("o", "r", 3) == [{"id": 1}]
    assert seen == ["/repos/o/r/pulls/3/comments"]


def test_get_avatar_token_logs_and_returns_none(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(*_a, **_k):
        raise APIError("nope", status=500)

    api.get = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="github_desktop"):
        assert api.get_avatar_token() is None
    assert "Failed to load avatar token" in caplog.text


def test_fetch_check_suite_logs_on_failure(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(*_a, **_k):
        raise APIError("nope", status=404)

    api.get = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="github_desktop"):
        assert api.fetch_check_suite("o", "r", 9) is None
    assert "[fetchCheckSuite] Failed fetch check suite id 9 (o/r)" in caplog.text


def test_fetch_repo_rules_skip_log_when_not_enabled(caplog) -> None:
    import logging

    from github_desktop.http_status import HttpStatusCode

    api = GitHubAPI("https://api.github.com", "tok")
    body = '{"message": "Upgrade to GitHub Pro or make this repository public to enable this feature."}'

    def forbidden(*_a, **_k):
        raise APIError("nope", status=HttpStatusCode.Forbidden, body=body)

    api.get = forbidden  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="github_desktop"):
        assert api.fetch_repo_rules_for_branch("o", "r", "main") == []
        assert api.fetch_all_repo_rulesets("o", "r") is None
    assert "[fetchRepoRulesForBranch]" not in caplog.text
    assert "[fetchAllRepoRulesets]" not in caplog.text


def test_fetch_repo_rules_logs_other_errors(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def fail(*_a, **_k):
        raise APIError("boom", status=500)

    api.get = fail  # type: ignore[method-assign]
    with caplog.at_level(logging.INFO, logger="github_desktop"):
        assert api.fetch_repo_rules_for_branch("o", "r", "main") == []
        assert api.fetch_repo_ruleset("o", "r", 7) is None
        assert api.fetch_all_repo_rulesets("o", "r") is None
    assert "[fetchRepoRulesForBranch] unable to fetch repo rules for branch: main | /repos/o/r/rules/branches/main" in caplog.text
    assert "[fetchRepoRuleset] unable to fetch repo ruleset for ID: 7 | /repos/o/r/rulesets/7" in caplog.text
    assert "[fetchAllRepoRulesets] unable to fetch all repo rulesets | /repos/o/r/rulesets" in caplog.text


def test_fork_repository_logs_and_reraises(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(*_a, **_k):
        raise APIError("nope", status=500)

    api.post = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="github_desktop"):
        with pytest.raises(APIError, match="nope"):
            api.fork_repository("o", "r")
    assert "forkRepository: failed to fork o/r at endpoint: https://api.github.com" in caplog.text


def test_fetch_repository_404_and_errors_return_none(caplog) -> None:
    import logging

    from github_desktop.http_status import HttpStatusCode

    api = GitHubAPI("https://api.github.com", "tok")

    def not_found(*_a, **_k):
        raise APIError("gone", status=HttpStatusCode.NotFound)

    api.get = not_found  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="github_desktop"):
        assert api.fetch_repository("o", "r") is None
    assert "fetchRepository: 'o/r' returned a 404" in caplog.text

    def fail(*_a, **_k):
        raise APIError("boom", status=500)

    api.get = fail  # type: ignore[method-assign]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="github_desktop"):
        assert api.fetch_repository("o", "r") is None
    assert "fetchRepository: an error occurred for 'o/r'" in caplog.text


def test_get_permissions_string_matches_desktop() -> None:
    from github_desktop.github.api import get_permissions_string
    from github_desktop.models import has_write_permission

    assert get_permissions_string({"name": "r"}) is None
    assert get_permissions_string({"permissions": {"admin": True, "push": True, "pull": True}}) == "admin"
    assert get_permissions_string({"permissions": {"admin": False, "push": True, "pull": True}}) == "write"
    assert get_permissions_string({"permissions": {"admin": False, "push": False, "pull": True}}) == "read"
    assert get_permissions_string({"permissions": {}}) is None
    api = GitHubAPI("https://api.github.com", "tok")
    unknown = api._to_repo({"name": "r", "owner": {"login": "o"}, "html_url": "", "clone_url": ""})
    assert unknown.permissions is None
    assert has_write_permission(unknown) is True
    admin = api._to_repo(
        {
            "name": "r",
            "owner": {"login": "o"},
            "html_url": "",
            "clone_url": "",
            "permissions": {"admin": True, "push": True, "pull": True},
        }
    )
    assert admin.permissions == "admin"
    assert has_write_permission(admin) is True
    read = api._to_repo(
        {
            "name": "r",
            "owner": {"login": "o"},
            "html_url": "",
            "clone_url": "",
            "permissions": {"admin": False, "push": False, "pull": True},
        }
    )
    assert read.permissions == "read"
    assert has_write_permission(read) is False


def test_fetch_emails_returns_empty_on_error(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(*_a, **_k):
        raise APIError("nope", status=500)

    api.get = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING, logger="github_desktop"):
        assert api.fetch_emails() == []
    assert "fetchEmails: failed with endpoint https://api.github.com" in caplog.text


def test_rerequest_check_suite_returns_false_on_failure(caplog) -> None:
    import logging

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(*_a, **_k):
        raise APIError("nope", status=500)

    api.post = boom  # type: ignore[method-assign]
    with caplog.at_level(logging.DEBUG, logger="github_desktop"):
        assert api.rerequest_check_suite("o", "r", 9) is False
        assert api.rerun_failed_jobs("o", "r", 3) is False
        assert api.rerun_job("o", "r", 4) is False
    assert "Failed retry check suite id 9 (o/r)" in caplog.text
    assert "Failed to rerun failed workflow jobs for (o/r): 3" in caplog.text
    assert "Failed to rerun workflow job (o/r): 4" in caplog.text


def test_refresh_accounts_replaces_stale_profile(isolated_config, monkeypatch) -> None:
    from github_desktop.models import Account
    from github_desktop.store import AppStore

    store = AppStore()
    store.accounts = [
        Account(login="octocat", endpoint="https://api.github.com", token="t", name="old")
    ]

    def fake_fetch(self):
        return Account(
            login="octocat",
            endpoint="https://api.github.com",
            token="t",
            name="The Octocat",
            id=1,
        )

    def sync_run(self, work, done):
        try:
            result = work()
        except BaseException as exc:
            done(exc)
            return
        done(None, result)

    monkeypatch.setattr("github_desktop.github.api.GitHubAPI.fetch_account", fake_fetch)
    monkeypatch.setattr(AppStore, "_run", sync_run)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("GITHUB_DESKTOP_OFFLINE", raising=False)
    monkeypatch.delenv("TEST_ENV", raising=False)
    store.refresh_accounts()
    assert store.accounts[0].name == "The Octocat"
    assert store.accounts[0].id == 1
