"""Desktop `getNextPagePathWithIncreasingPageSize` and incremental PR fetches."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

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
