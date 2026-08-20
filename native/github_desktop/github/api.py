"""GitHub REST API client (dotcom + Enterprise) plus Copilot commit messages."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
import re
from typing import Any, Callable, Iterable

from ..errors import APIError, CopilotError, MaxResultsError
from ..logging import get_logger
from ..models import (
    Account,
    AccountEmail,
    CheckSuite,
    GitHubRepository,
    Issue,
    PullRequest,
    RefCheck,
    is_ghes_endpoint,
)
from .ci_checks import annotation_from_api, api_status_to_ref_check, duration_ms, get_check_run_short_description
from .push_control import PushControl, default_push_control
from ..version import APP_NAME, __version__

log = get_logger()

DOTCOM_API = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/{__version__}"
PER_PAGE = 100
ANTIOPE_PREVIEW_ACCEPT = "application/vnd.github.antiope-preview+json"
_NEXT_LINK_RE = re.compile(r'<([^>]+)>; rel="([^"]+)"')


def url_with_query_string(url: str, params: dict[str, str]) -> str:
    """Desktop `urlWithQueryString`: append query params, preserving an existing query."""
    qs = "&".join(f"{key}={urllib.parse.quote(str(value), safe='')}" for key, value in params.items())
    if not qs:
        return url
    return f"{url}&{qs}" if "?" in url else f"{url}?{qs}"


def _link_header(source: Any) -> str:
    if source is None:
        return ""
    if isinstance(source, str):
        return source
    if isinstance(source, dict):
        for key, value in source.items():
            if str(key).lower() == "link":
                return str(value)
        return ""
    headers = getattr(source, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if callable(getter):
        return str(getter("Link") or getter("link") or "")
    if isinstance(headers, dict):
        return _link_header(headers)
    return str(headers)


def get_next_page_path_from_link(source: Any) -> str | None:
    """Desktop `getNextPagePathFromLink`.

    Node's `url.parse().path` includes the query string; Python's
    `urlsplit().path` does not, so this concatenates `?query` when present.
    """
    header = _link_header(source)
    if not header:
        return None
    for part in header.split(","):
        match = _NEXT_LINK_RE.search(part.strip())
        if match and match.group(2) == "next":
            parsed = urllib.parse.urlsplit(match.group(1))
            path = parsed.path or ""
            if parsed.query:
                path = f"{path}?{parsed.query}"
            return path or None
    return None


def get_next_page_path_with_increasing_page_size(source: Any) -> str | None:
    """Desktop `getNextPagePathWithIncreasingPageSize`.

    Follows GitHub `Link` headers and doubles `per_page` only when
    `received % nextPageSize === 0` so later pages do not skip items
    (Desktop `app/test/unit/api-test.ts`).
    """
    next_path = get_next_page_path_from_link(source)
    if not next_path:
        return None
    parsed = urllib.parse.urlsplit(next_path)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    per_page_s = query.get("per_page")
    page_s = query.get("page")
    try:
        page_size = int(per_page_s) if per_page_s else 0
        page_number = int(page_s) if page_s else 0
    except ValueError:
        return next_path
    if not page_size or not page_number:
        return next_path
    # Confusing, but we're looking at the _next_ page path here
    # so the current is whatever came before it.
    current_page = page_number - 1
    received = current_page * page_size
    next_page_size = min(100, page_size * 2)
    if page_size != next_page_size and received % next_page_size == 0:
        query["per_page"] = str(next_page_size)
        query["page"] = str(received // next_page_size + 1)
        new_query = urllib.parse.urlencode(query)
        return urllib.parse.urlunsplit(("", "", parsed.path, new_query, ""))
    return next_path

_token_invalidated_callback = None


def on_token_invalidated(callback) -> None:
    """Desktop `API.onTokenInvalidated`."""
    global _token_invalidated_callback
    _token_invalidated_callback = callback


def emit_token_invalidated(endpoint: str, token: str) -> None:
    """Desktop `API.emitTokenInvalidated`."""
    callback = _token_invalidated_callback
    if callback is not None:
        callback(endpoint, token)


def get_dotcom_api_endpoint() -> str:
    import os

    return os.environ.get("DESKTOP_GITHUB_DOTCOM_API_ENDPOINT") or DOTCOM_API


class GitHubAPI:
    def __init__(self, endpoint: str, token: str | None, copilot_endpoint: str | None = None) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.copilot_endpoint = copilot_endpoint

    @classmethod
    def from_account(cls, account: Account) -> "GitHubAPI":
        return cls(account.endpoint, account.token, account.copilot_endpoint)

    def fetch_feature_flags(self) -> list[str]:
        """Desktop `fetchFeatureFlags`: `GET /desktop_internal/features`."""
        try:
            data = self.get("/desktop_internal/features")
        except APIError:
            log.warn("fetchFeatureFlags: failed with endpoint %s", self.endpoint)
            return []
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            return [str(item) for item in data["features"]]
        if isinstance(data, list):
            return [str(item) for item in data]
        return []

    def fetch_user_copilot_info(self) -> dict[str, Any]:
        """Desktop `fetchUserCopilotInfo`: GraphQL `isCopilotDesktopEnabled` + Copilot API endpoint."""
        from ..models import is_ghes_endpoint

        empty = {"copilot_endpoint": None, "is_copilot_desktop_enabled": False}
        if is_ghes_endpoint(self.endpoint):
            return empty
        query = """
        {
          viewer {
            copilotEndpoints { api }
            isCopilotDesktopEnabled
          }
        }
        """
        try:
            data = self.post("/graphql", {"query": query})
            viewer = ((data or {}).get("data") or {}).get("viewer") or {}
            endpoints = viewer.get("copilotEndpoints") or {}
            return {
                "copilot_endpoint": endpoints.get("api"),
                "is_copilot_desktop_enabled": bool(viewer.get("isCopilotDesktopEnabled")),
            }
        except APIError:
            log.warn("fetchUserCopilotInfo: failed with endpoint %s", self.endpoint)
            info = self.fetch_copilot_info()
            if not info:
                return empty
            return {
                "copilot_endpoint": info.get("copilot_endpoint")
                or (info.get("copilotEndpoints") or {}).get("api"),
                "is_copilot_desktop_enabled": bool(
                    info.get("isCopilotDesktopEnabled") or info.get("copilot_endpoint")
                ),
            }

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"token {self.token}"
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        query: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        raw_url: str | None = None,
        return_headers: bool = False,
    ) -> Any:
        if raw_url:
            url = raw_url
        else:
            url = self.endpoint + (path if path.startswith("/") else "/" + path)
            if query:
                url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
        data = None
        headers = self._headers(extra_headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                header_map = {
                    str(key).lower(): str(value) for key, value in (resp.headers.items() if resp.headers else [])
                }
                raw = resp.read()
                if not raw:
                    parsed: Any = None
                else:
                    ctype = resp.headers.get("Content-Type", "")
                    if "json" in ctype or raw[:1] in (b"{", b"["):
                        parsed = json.loads(raw.decode("utf-8"))
                    else:
                        parsed = raw.decode("utf-8")
                if return_headers:
                    return parsed, header_map
                return parsed
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            header_map: dict[str, str] = {}
            try:
                header_map = {
                    str(key).lower(): str(value) for key, value in (exc.headers.items() if exc.headers else [])
                }
            except Exception:
                header_map = {}
            # Desktop ghRequest: 401 + X-GitHub-Request-Id and no OTP => emitTokenInvalidated.
            if (
                exc.code == 401
                and self.token
                and header_map.get("x-github-request-id")
                and not header_map.get("x-github-otp")
            ):
                emit_token_invalidated(self.endpoint, self.token)
            raise APIError(
                f"GitHub API {method} {url} failed: {exc.code} {payload[:500]}",
                status=exc.code,
                body=payload,
                headers=header_map,
            ) from exc
        except urllib.error.URLError as exc:
            raise APIError(f"GitHub API network error: {exc}") from exc

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Any | None = None, **kwargs: Any) -> Any:
        return self.request("POST", path, body=body, **kwargs)

    def put(self, path: str, body: Any | None = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, body=body, **kwargs)

    def patch(self, path: str, body: Any | None = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, body=body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def fetch_user(self) -> dict[str, Any]:
        return self.get("/user")

    def fetch_emails(self) -> list[dict[str, Any]]:
        data = self.get("/user/emails")
        return data if isinstance(data, list) else []

    def fetch_copilot_info(self) -> dict[str, Any] | None:
        try:
            return self.get("/copilot_internal/user")
        except APIError:
            return None

    def fetch_account(self, token: str | None = None) -> Account:
        if token:
            self.token = token
        user = self.fetch_user()
        emails: list[AccountEmail] = []
        try:
            emails = [AccountEmail.coerce(item) for item in self.fetch_emails() if item.get("email")]
        except APIError:
            if user.get("email"):
                emails = [AccountEmail(email=user["email"], primary=True, verified=True, visibility="public")]
        copilot_endpoint = None
        is_copilot_desktop_enabled = False
        try:
            copilot = self.fetch_user_copilot_info()
            copilot_endpoint = copilot.get("copilot_endpoint")
            is_copilot_desktop_enabled = bool(copilot.get("is_copilot_desktop_enabled"))
        except APIError:
            pass
        features = self.fetch_feature_flags()
        return Account(
            login=user.get("login", ""),
            endpoint=self.endpoint,
            token=self.token or "",
            emails=emails,
            avatar_url=user.get("avatar_url", ""),
            name=user.get("name") or user.get("login", ""),
            id=int(user.get("id") or 0),
            plan=(user.get("plan") or {}).get("name") if isinstance(user.get("plan"), dict) else None,
            copilot_endpoint=copilot_endpoint,
            is_copilot_desktop_enabled=is_copilot_desktop_enabled,
            features=features,
        )

    def _paginate(self, path: str, query: dict[str, str] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        q = dict(query or {})
        q["per_page"] = str(PER_PAGE)
        while True:
            q["page"] = str(page)
            data = self.get(path, query=q)
            if not isinstance(data, list) or not data:
                if isinstance(data, list):
                    items.extend(data)
                break
            items.extend(data)
            if len(data) < PER_PAGE:
                break
            page += 1
            if page > 50:
                break
        return items

    def fetch_all(
        self,
        path: str,
        *,
        per_page: int = 100,
        get_next_page_path: Callable[[Any], str | None] | None = None,
        continue_fn: Callable[[list[Any]], bool] | None = None,
        suppress_errors: bool = True,
    ) -> list[Any]:
        """Desktop `API.fetchAll`: follow GitHub `Link` headers until exhausted."""
        buf: list[Any] = []
        next_path: str | None = url_with_query_string(path, {"per_page": str(per_page)})
        resolve_next = get_next_page_path or get_next_page_path_from_link
        while next_path:
            try:
                data, headers = self.request("GET", next_path, return_headers=True)
            except APIError as exc:
                if suppress_errors:
                    log.warn("fetchAll: '%s' returned a %s", path, exc.status)
                    return buf
                raise
            page = data if isinstance(data, list) else []
            buf.extend(page)
            next_path = resolve_next(headers)
            if not next_path:
                break
            if continue_fn is not None and not continue_fn(buf):
                break
        return buf

    def fetch_repos(self, affiliation: str = "owner,collaborator,organization_member") -> list[GitHubRepository]:
        items = self._paginate("/user/repos", {"affiliation": affiliation, "sort": "updated"})
        return [self._to_repo(item) for item in items]

    def fetch_orgs(self) -> list[dict[str, Any]]:
        return self._paginate("/user/orgs")

    def fetch_org_repos(self, org: str) -> list[GitHubRepository]:
        items = self._paginate(f"/orgs/{org}/repos", {"sort": "updated"})
        return [self._to_repo(item) for item in items]

    def fetch_repository(self, owner: str, name: str) -> GitHubRepository:
        data = self.get(f"/repos/{owner}/{name}")
        return self._to_repo(data)

    def fetch_repository_clone_info(
        self, owner: str, name: str, protocol: str | None = None
    ) -> dict[str, str] | None:
        """Desktop `fetchRepositoryCloneInfo`: canonical clone URL after rename, SSH vs HTTPS."""
        try:
            data = self.get(
                f"/repos/{owner}/{name}",
                extra_headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
            )
        except APIError as exc:
            if exc.status == 404:
                return None
            raise
        if not isinstance(data, dict):
            return None
        url = data.get("ssh_url") if protocol == "ssh" else data.get("clone_url")
        return {
            "url": str(url or ""),
            "default_branch": str(data.get("default_branch") or ""),
        }

    def create_repository(
        self,
        name: str,
        *,
        description: str = "",
        private: bool = False,
        org: str | None = None,
    ) -> GitHubRepository:
        body = {"name": name, "description": description, "private": private}
        if org:
            data = self.post(f"/orgs/{org}/repos", body)
        else:
            data = self.post("/user/repos", body)
        return self._to_repo(data)

    def fork_repository(self, owner: str, name: str, org: str | None = None) -> GitHubRepository:
        body = {"organization": org} if org else {}
        data = self.post(f"/repos/{owner}/{name}/forks", body)
        return self._to_repo(data)

    def fetch_pull_requests(self, owner: str, name: str, state: str = "open") -> list[PullRequest]:
        items = self._paginate(f"/repos/{owner}/{name}/pulls", {"state": state, "sort": "updated"})
        return [self._to_pr(item) for item in items]

    def fetch_all_open_pull_requests(self, owner: str, name: str) -> list[PullRequest]:
        """Desktop `fetchAllOpenPullRequests`: `GET /repos/{owner}/{name}/pulls?state=open`."""
        path = url_with_query_string(f"/repos/{owner}/{name}/pulls", {"state": "open"})
        try:
            items = self.fetch_all(path)
        except APIError:
            log.warn("failed fetching open PRs for repository %s/%s", owner, name)
            raise
        return [self._to_pr(item) for item in items if isinstance(item, dict)]

    def fetch_updated_pull_requests(
        self, owner: str, name: str, since: str, max_results: int = 320
    ) -> list[PullRequest]:
        """Desktop `fetchUpdatedPullRequests`.

        Starts at ``per_page=10`` and follows GitHub ``Link`` headers via
        ``getNextPagePathWithIncreasingPageSize`` so later pages double
        ``per_page`` without skipping items (Desktop ``api-test.ts``).
        """
        since_stamp = since or ""
        path = url_with_query_string(
            f"/repos/{owner}/{name}/pulls",
            {"state": "all", "sort": "updated", "direction": "desc"},
        )

        def should_continue(results: list[Any]) -> bool:
            if len(results) >= max_results:
                raise MaxResultsError("got max pull requests, aborting")
            last = results[-1] if results else None
            if not isinstance(last, dict):
                return False
            return str(last.get("updated_at") or "") > since_stamp

        try:
            items = self.fetch_all(
                path,
                per_page=10,
                get_next_page_path=get_next_page_path_with_increasing_page_size,
                continue_fn=should_continue,
                suppress_errors=False,
            )
        except MaxResultsError:
            raise
        except APIError:
            log.warn("failed fetching updated PRs for repository %s/%s", owner, name)
            raise
        return [
            self._to_pr(item)
            for item in items
            if isinstance(item, dict) and str(item.get("updated_at") or "") >= since_stamp
        ]

    def fetch_pull_request(self, owner: str, name: str, number: int) -> PullRequest:
        return self._to_pr(self.get(f"/repos/{owner}/{name}/pulls/{number}"))

    def create_pull_request(
        self,
        owner: str,
        name: str,
        title: str,
        head: str,
        base: str,
        body: str = "",
        draft: bool = False,
    ) -> PullRequest:
        data = self.post(
            f"/repos/{owner}/{name}/pulls",
            {"title": title, "head": head, "base": base, "body": body, "draft": draft},
        )
        return self._to_pr(data)

    def fetch_issues(
        self, owner: str, name: str, state: str = "open", since: str | None = None
    ) -> list[Issue]:
        query: dict[str, str] = {"state": state}
        if since:
            query["since"] = since
        items = self._paginate(f"/repos/{owner}/{name}/issues", query)
        issues = []
        for item in items:
            if "pull_request" in item:
                continue
            issues.append(
                Issue(
                    number=item["number"],
                    title=item["title"],
                    state=item.get("state", "open"),
                    updated_at=item.get("updated_at") or "",
                )
            )
        return issues

    def fetch_notifications(self) -> list[dict[str, Any]]:
        try:
            data = self.get("/notifications", query={"all": "false", "participating": "false"})
        except APIError:
            return []
        return data if isinstance(data, list) else []

    def get_fetch_poll_interval(self, owner: str, name: str) -> int | None:
        """Desktop `getFetchPollInterval`: parsed `x-poll-interval` from HEAD `/repos/{owner}/{name}/git`.

        Returns the raw header integer (Desktop treats it as milliseconds) or None.
        """
        path = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/git"
        url = self.endpoint + path
        req = urllib.request.Request(url, headers=self._headers(), method="HEAD")
        headers = None
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                headers = resp.headers
        except urllib.error.HTTPError as exc:
            headers = exc.headers
        except Exception as exc:
            log.debug("get_fetch_poll_interval failed: %s", exc)
            return None
        if headers is None:
            return None
        raw = headers.get("X-Poll-Interval") or headers.get("x-poll-interval")
        if not raw:
            return None
        try:
            parsed = int(raw)
        except ValueError:
            return None
        return parsed if parsed > 0 else None

    def get_alive_websocket_url(self) -> str | None:
        """Desktop `getAliveWebSocketURL`. Native polls `/notifications` instead of keeping a socket."""
        try:
            data = self.get("/alive_internal/websocket-url")
        except APIError as exc:
            if exc.status == 404:
                return None
            log.debug("Alive websocket URL failed: %s", exc)
            return None
        if isinstance(data, dict):
            url = data.get("url")
            return str(url) if url else None
        return None

    def fetch_check_runs(self, owner: str, name: str, ref: str) -> list[RefCheck]:
        mapped: list[RefCheck] = []
        page = 1
        quoted = urllib.parse.quote(ref)
        while page <= 10:
            try:
                data = self.get(
                    f"/repos/{owner}/{name}/commits/{quoted}/check-runs",
                    query={"per_page": "100", "page": str(page)},
                )
            except APIError:
                break
            runs = data.get("check_runs", []) if isinstance(data, dict) else []
            for r in runs:
                status = r.get("status") or ""
                conclusion = r.get("conclusion")
                started = r.get("started_at")
                completed = r.get("completed_at")
                title = (r.get("output") or {}).get("title") or r.get("title") or ""
                mapped.append(
                    RefCheck(
                        id=int(r.get("id") or 0),
                        name=r.get("name") or "",
                        description=title
                        or get_check_run_short_description(status, conclusion, duration_ms(started, completed)),
                        status=status,
                        conclusion=conclusion,
                        html_url=r.get("html_url"),
                        app_name=(r.get("app") or {}).get("name"),
                        check_suite_id=(r.get("check_suite") or {}).get("id"),
                        started_at=started,
                        completed_at=completed,
                        has_pull_requests=bool(r.get("pull_requests")),
                    )
                )
            if len(runs) < 100:
                break
            page += 1
        statuses: list[RefCheck] = []
        try:
            statuses = [api_status_to_ref_check(item) for item in self.fetch_combined_ref_status(owner, name, ref)]
        except APIError:
            statuses = []
        from .ci_checks import get_latest_check_runs_by_id

        return get_latest_check_runs_by_id(statuses + mapped)

    def fetch_combined_ref_status(self, owner: str, name: str, ref: str) -> list[dict[str, Any]]:
        """Desktop `fetchCombinedRefStatus` (`GET /commits/{ref}/status`)."""
        quoted = urllib.parse.quote(ref)
        try:
            data = self.get(
                f"/repos/{owner}/{name}/commits/{quoted}/status",
                query={"per_page": "100"},
            )
        except APIError:
            return []
        if not isinstance(data, dict):
            return []
        items = data.get("statuses") or []
        return [item for item in items if isinstance(item, dict)]

    def get_avatar_token(self) -> str | None:
        """Desktop `getAvatarToken` (`GET /desktop/avatar-token`) for GHE email avatars."""
        try:
            data = self.get("/desktop/avatar-token")
        except APIError:
            return None
        if isinstance(data, dict):
            token = data.get("avatar_token")
            return token if isinstance(token, str) and token else None
        return None

    def fetch_workflow_run_jobs(
        self, owner: str, name: str, workflow_run_id: int
    ) -> dict[str, Any] | None:
        """Desktop `fetchWorkflowRunJobs`: jobs for one Actions workflow run."""
        extra = {"Accept": ANTIOPE_PREVIEW_ACCEPT}
        try:
            data = self.get(
                f"/repos/{owner}/{name}/actions/runs/{int(workflow_run_id)}/jobs",
                extra_headers=extra,
            )
        except APIError:
            log.debug(
                "Failed fetching workflow jobs (%s/%s) workflow run: %s",
                owner,
                name,
                workflow_run_id,
            )
            return None
        return data if isinstance(data, dict) else None

    def fetch_workflow_jobs_for_sha(self, owner: str, name: str, sha: str) -> list[dict[str, Any]]:
        try:
            data = self.get(f"/repos/{owner}/{name}/actions/runs", query={"head_sha": sha})
        except APIError:
            return []
        runs = (data or {}).get("workflow_runs") if isinstance(data, dict) else []
        jobs: list[dict[str, Any]] = []
        for run in runs or []:
            run_id = run.get("id")
            if not run_id:
                continue
            payload = self.fetch_workflow_run_jobs(owner, name, int(run_id))
            if not payload:
                continue
            workflow_meta = {
                "id": int(run_id),
                "name": run.get("name") or "",
                "event": run.get("event") or "",
                "check_suite_id": run.get("check_suite_id"),
                "html_url": run.get("html_url"),
            }
            for job in payload.get("jobs") or []:
                if isinstance(job, dict):
                    job["_workflow"] = workflow_meta
                    jobs.append(job)
        return jobs

    def fetch_pr_workflow_runs_by_branch_name(
        self, owner: str, name: str, branch_name: str
    ) -> list[dict[str, Any]]:
        """Desktop `fetchPRWorkflowRunsByBranchName`."""
        extra = {"Accept": ANTIOPE_PREVIEW_ACCEPT}
        try:
            data = self.get(
                f"/repos/{owner}/{name}/actions/runs",
                query={"event": "pull_request", "branch": branch_name},
                extra_headers=extra,
            )
        except APIError:
            log.debug("Failed fetching workflow runs for %s (%s/%s)", branch_name, owner, name)
            return []
        if isinstance(data, dict):
            runs = data.get("workflow_runs") or []
            return [item for item in runs if isinstance(item, dict)]
        return []

    def fetch_pr_action_workflow_run_by_check_suite_id(
        self, owner: str, name: str, check_suite_id: int
    ) -> dict[str, Any] | None:
        """Desktop `fetchPRActionWorkflowRunByCheckSuiteId`."""
        extra = {"Accept": ANTIOPE_PREVIEW_ACCEPT}
        try:
            data = self.get(
                f"/repos/{owner}/{name}/actions/runs",
                query={"event": "pull_request", "check_suite_id": str(int(check_suite_id))},
                extra_headers=extra,
            )
        except APIError:
            log.debug("Failed fetching workflow runs for %s (%s/%s)", check_suite_id, owner, name)
            return None
        runs = (data or {}).get("workflow_runs") if isinstance(data, dict) else []
        if isinstance(runs, list) and runs:
            first = runs[0]
            return first if isinstance(first, dict) else None
        return None

    def attach_action_workflows(
        self, owner: str, name: str, branch_name: str | None, check_runs: list[RefCheck]
    ) -> list[RefCheck]:
        """Desktop `getCheckRunActionsWorkflowRuns` (suite id on dotcom, branch name on GHES)."""
        from .ci_checks import get_latest_pr_workflow_runs, map_action_workflows_runs_to_check_runs

        if not check_runs:
            return check_runs
        if is_ghes_endpoint(self.endpoint):
            if not branch_name:
                return check_runs
            runs = self.fetch_pr_workflow_runs_by_branch_name(owner, name, branch_name)
            return map_action_workflows_runs_to_check_runs(check_runs, get_latest_pr_workflow_runs(runs))
        cache: dict[int, dict[str, Any] | None] = {}
        for check in check_runs:
            if not check.check_suite_id:
                continue
            if check.check_suite_id not in cache:
                cache[check.check_suite_id] = self.fetch_pr_action_workflow_run_by_check_suite_id(
                    owner, name, check.check_suite_id
                )
            run = cache[check.check_suite_id]
            if run:
                from .ci_checks import actions_workflow_from_run

                check.actions_workflow = actions_workflow_from_run(run) or check.actions_workflow
        return check_runs

    def fetch_check_suite(self, owner: str, name: str, suite_id: int) -> CheckSuite | None:
        try:
            data = self.get(f"/repos/{owner}/{name}/check-suites/{suite_id}")
        except APIError:
            return None
        if not isinstance(data, dict):
            return None
        return CheckSuite(
            id=int(data.get("id") or suite_id),
            rerequestable=bool(data.get("rerequestable")),
            status=data.get("status") or "",
            created_at=data.get("created_at") or "",
        )

    def fetch_check_run_annotations(self, owner: str, name: str, check_run_id: int) -> list:
        try:
            data = self.get(f"/repos/{owner}/{name}/check-runs/{check_run_id}/annotations")
        except APIError:
            return []
        items = data if isinstance(data, list) else []
        return [annotation_from_api(item) for item in items[:50] if isinstance(item, dict)]

    def fetch_job_logs(self, owner: str, name: str, job_id: int, max_bytes: int = 512 * 1024) -> str:
        url = self.endpoint + f"/repos/{owner}/{name}/actions/jobs/{job_id}/logs"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read(max_bytes + 1)
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 410}:
                return ""
            payload = exc.read().decode("utf-8", errors="replace")
            raise APIError(
                f"GitHub API GET {url} failed: {exc.code} {payload[:500]}",
                status=exc.code,
                body=payload,
            ) from exc
        except urllib.error.URLError as exc:
            raise APIError(f"GitHub API network error: {exc}") from exc
        if raw[:2] == b"\x1f\x8b":
            import gzip

            try:
                raw = gzip.decompress(raw)
            except Exception:
                pass
        text = raw[:max_bytes].decode("utf-8", errors="replace")
        if len(raw) > max_bytes:
            text += "\n… truncated …\n"
        return text

    def rerequest_check_suite(self, owner: str, name: str, suite_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/check-suites/{suite_id}/rerequest")

    def rerequest_check_run(self, owner: str, name: str, run_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/check-runs/{run_id}/rerequest")

    def rerun_failed_jobs(self, owner: str, name: str, workflow_run_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/actions/runs/{workflow_run_id}/rerun-failed-jobs")

    def rerun_job(self, owner: str, name: str, job_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/actions/jobs/{job_id}/rerun")

    def fetch_protected_branches(self, owner: str, name: str) -> list[str]:
        try:
            items = self._paginate(f"/repos/{owner}/{name}/branches", {"protected": "true"})
            return [i.get("name") for i in items if i.get("name")]
        except APIError:
            return []

    def fetch_push_control(self, owner: str, name: str, branch: str) -> PushControl:
        """Desktop `fetchPushControl`. On failure, assume the user can push."""
        path = f"/repos/{owner}/{name}/branches/{urllib.parse.quote(branch, safe='')}/push_control"
        extra = {"Accept": "application/vnd.github.phandalin-preview"}
        try:
            data = self.get(path, extra_headers=extra)
        except APIError:
            log.info("fetchPushControl unable to check if branch is potentially pushable")
            return default_push_control()
        if not isinstance(data, dict):
            return default_push_control()
        checks = data.get("required_status_checks")
        return PushControl(
            required_status_checks=list(checks) if isinstance(checks, list) else [],
            required_approving_review_count=int(data.get("required_approving_review_count") or 0),
            allow_actor=data.get("allow_actor"),
            pattern=data.get("pattern"),
            required_signatures=bool(data.get("required_signatures")),
            required_linear_history=bool(data.get("required_linear_history")),
            allow_deletions=data.get("allow_deletions"),
            allow_force_pushes=data.get("allow_force_pushes"),
            required_conversation_resolution=bool(data.get("required_conversation_resolution")),
            lock_branch=bool(data.get("lock_branch")),
        )

    def fetch_repo_rules_for_branch(self, owner: str, name: str, branch: str) -> list[dict[str, Any]]:
        path = f"/repos/{owner}/{name}/rules/branches/{urllib.parse.quote(branch, safe='')}"
        try:
            data = self.get(path)
            return data if isinstance(data, list) else []
        except APIError as exc:
            if exc.status in {403, 404}:
                return []
            log.info("fetch repo rules for %s/%s@%s failed: %s", owner, name, branch, exc)
            return []

    def fetch_repo_ruleset(self, owner: str, name: str, ruleset_id: int) -> dict[str, Any] | None:
        try:
            data = self.get(f"/repos/{owner}/{name}/rulesets/{int(ruleset_id)}")
            return data if isinstance(data, dict) else None
        except APIError as exc:
            log.info("fetch repo ruleset %s failed: %s", ruleset_id, exc)
            return None

    def fetch_all_repo_rulesets(self, owner: str, name: str) -> list[dict[str, Any]] | None:
        """Desktop `fetchAllRepoRulesets`: slim rulesets for cache prefetch."""
        try:
            data = self.get(f"/repos/{owner}/{name}/rulesets")
            return data if isinstance(data, list) else []
        except APIError as exc:
            if exc.status in {403, 404}:
                return None
            log.info("fetchAllRepoRulesets unable to fetch all repo rulesets | /repos/%s/%s/rulesets", owner, name)
            return None

    def fetch_mentionables(
        self, owner: str, name: str, etag: str | None = None
    ) -> tuple[list[dict[str, Any]] | None, str | None]:
        """Desktop `fetchMentionables`. Returns `(users, etag)`; `users` is None on HTTP 304."""
        extra = {"Accept": "application/vnd.github.jerry-maguire-preview"}
        if etag:
            extra["If-None-Match"] = etag
        try:
            data, headers = self.request(
                "GET",
                f"/repos/{owner}/{name}/mentionables/users",
                extra_headers=extra,
                return_headers=True,
            )
        except APIError as exc:
            if exc.status == 304:
                return None, etag
            if exc.status == 404:
                log.warn("fetchMentionables: '%s/%s' returned a 404", owner, name)
                return [], None
            log.warn("fetchMentionables: failed for %s/%s", owner, name)
            return [], None
        users: list[dict[str, Any]] = []
        if isinstance(data, list):
            for item in data:
                login = item.get("login")
                if not login:
                    continue
                users.append(
                    {
                        "login": login,
                        "name": item.get("name"),
                        "email": item.get("email"),
                        "avatar_url": item.get("avatar_url"),
                    }
                )
        return users, (headers or {}).get("etag")

    def fetch_mentions(self, owner: str, name: str) -> list[str]:
        mentionables, _etag = self.fetch_mentionables(owner, name)
        if mentionables:
            return [item["login"] for item in mentionables if item.get("login")]
        try:
            items = self.get(f"/repos/{owner}/{name}/collaborators")
            if isinstance(items, list):
                return [i.get("login") for i in items if i.get("login")]
        except APIError:
            return []
        return []

    def fetch_user_by_login(self, login: str) -> dict[str, Any] | None:
        try:
            data = self.get(f"/users/{urllib.parse.quote(login)}")
            return data if isinstance(data, dict) else None
        except APIError:
            return None

    def fetch_pull_request_comments(self, owner: str, name: str, number: int) -> list[dict[str, Any]]:
        try:
            items = self._paginate(f"/repos/{owner}/{name}/pulls/{number}/comments")
            return items if isinstance(items, list) else []
        except APIError:
            return []

    def fetch_issue_comment(self, owner: str, name: str, comment_id: str | int) -> dict[str, Any] | None:
        """Desktop `fetchIssueComment`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/issues/comments/{comment_id}")
            return data if isinstance(data, dict) else None
        except APIError as exc:
            if exc.status == 404:
                log.warn("fetchIssueComment: '%s/%s/issues/comments/%s' returned a 404", owner, name, comment_id)
            else:
                log.warn("fetchIssueComment: an error occurred for '%s/%s/issues/comments/%s'", owner, name, comment_id)
            return None

    def fetch_pull_request_review_comment(
        self, owner: str, name: str, comment_id: str | int
    ) -> dict[str, Any] | None:
        """Desktop `fetchPullRequestReviewComment`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/pulls/comments/{comment_id}")
            return data if isinstance(data, dict) else None
        except APIError as exc:
            if exc.status == 404:
                log.warn(
                    "fetchPullRequestReviewComment: '%s/%s/pulls/comments/%s' returned a 404",
                    owner,
                    name,
                    comment_id,
                )
            else:
                log.warn(
                    "fetchPullRequestReviewComment: an error occurred for '%s/%s/pulls/comments/%s'",
                    owner,
                    name,
                    comment_id,
                )
            return None

    def fetch_pull_request_review(
        self, owner: str, name: str, pr_number: str | int, review_id: str | int
    ) -> dict[str, Any] | None:
        """Desktop `fetchPullRequestReview`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/pulls/{pr_number}/reviews/{review_id}")
            return data if isinstance(data, dict) else None
        except APIError:
            log.debug(
                "failed fetching PR review %s for %s/%s/pulls/%s",
                review_id,
                owner,
                name,
                pr_number,
            )
            return None

    def fetch_pull_request_reviews(
        self, owner: str, name: str, pr_number: str | int
    ) -> list[dict[str, Any]]:
        """Desktop `fetchPullRequestReviews`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/pulls/{pr_number}/reviews")
            return data if isinstance(data, list) else []
        except APIError:
            log.debug("failed fetching PR reviews for %s/%s/pulls/%s", owner, name, pr_number)
            return []

    def fetch_pull_request_review_comments(
        self, owner: str, name: str, pr_number: str | int, review_id: str | int
    ) -> list[dict[str, Any]]:
        """Desktop `fetchPullRequestReviewComments`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/pulls/{pr_number}/reviews/{review_id}/comments")
            return data if isinstance(data, list) else []
        except APIError:
            log.debug(
                "failed fetching PR review comments for %s/%s/pulls/%s",
                owner,
                name,
                pr_number,
            )
            return []

    def fetch_issue_comments(
        self, owner: str, name: str, issue_number: str | int
    ) -> list[dict[str, Any]]:
        """Desktop `fetchIssueComments`."""
        try:
            data = self.get(f"/repos/{owner}/{name}/issues/{issue_number}/comments")
            return data if isinstance(data, list) else []
        except APIError:
            log.debug(
                "failed fetching issue comments for %s/%s/issues/%s",
                owner,
                name,
                issue_number,
            )
            return []

    def fetch_notification_subject(self, url: str) -> dict[str, Any] | None:
        """Load a notification's latest comment/review using Desktop's typed endpoints when possible."""
        parsed = urllib.parse.urlparse(url)
        parts = [part for part in parsed.path.split("/") if part]
        try:
            if len(parts) >= 6 and parts[0] == "repos" and parts[3] == "issues" and parts[4] == "comments":
                return self.fetch_issue_comment(parts[1], parts[2], parts[5])
            if len(parts) >= 6 and parts[0] == "repos" and parts[3] == "pulls" and parts[4] == "comments":
                return self.fetch_pull_request_review_comment(parts[1], parts[2], parts[5])
            if (
                len(parts) >= 7
                and parts[0] == "repos"
                and parts[3] == "pulls"
                and parts[5] == "reviews"
            ):
                return self.fetch_pull_request_review(parts[1], parts[2], parts[4], parts[6])
        except Exception:
            pass
        try:
            fetched = self.get("", raw_url=url)
            return fetched if isinstance(fetched, dict) else None
        except Exception:
            return None

    def create_issue(self, owner: str, name: str, title: str, body: str = "") -> dict[str, Any]:
        return self.post(f"/repos/{owner}/{name}/issues", {"title": title, "body": body})

    def generate_commit_message(self, diff: str, files: Iterable[str]) -> tuple[str, str]:
        if not self.copilot_endpoint:
            raise CopilotError("Copilot is not available for this account")
        import uuid

        path = "/agents/github-desktop-commit-message-generation"
        url = self.copilot_endpoint.rstrip("/") + path
        body = {
            "messages": [{"role": "user", "content": diff[:80_000]}],
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        extra = {
            "X-Initiator": "user",
            "X-Interaction-ID": str(uuid.uuid4()),
            "X-Interaction-Type": "generateCommitMessage",
            "Authorization": f"Bearer {self.token}",
        }
        try:
            payload = self.request("POST", path, body=body, extra_headers=extra, raw_url=url)
        except APIError as exc:
            if exc.status in {404, 405}:
                return self._generate_commit_message_chat(diff, files)
            raise CopilotError(self._copilot_error_message(exc)) from exc
        return self._commit_message_from_payload(payload)

    def _generate_commit_message_chat(self, diff: str, files: Iterable[str]) -> tuple[str, str]:
        body = {
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Write a concise git commit message for this diff. "
                        "Return JSON with keys summary and description.\n\n"
                        f"Files: {', '.join(files)}\n\n{diff[:80_000]}"
                    ),
                }
            ],
        }
        url = self.copilot_endpoint.rstrip("/") + "/v1/chat/completions"
        extra = {"Authorization": f"Bearer {self.token}"}
        try:
            payload = self.request("POST", "/v1/chat/completions", body=body, extra_headers=extra, raw_url=url)
        except APIError as exc:
            raise CopilotError(self._copilot_error_message(exc)) from exc
        return self._commit_message_from_payload(payload)

    def _commit_message_from_payload(self, payload: Any) -> tuple[str, str]:
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CopilotError("No choice found in response") from exc
        if not content:
            raise CopilotError("No message found in response")
        return _parse_generated_message(content)

    def _copilot_error_message(self, exc: APIError) -> str:
        body = exc.body or ""
        if exc.status == 429:
            retry = (exc.headers or {}).get("retry-after")
            if retry:
                return f"Rate limited, retry after {retry} seconds."
            return "Rate limited, try again in a few minutes."
        if exc.status == 402:
            return body.strip() or "You have reached your quota limit."
        if exc.status == 401:
            return "Unauthorized: error with authentication."
        if exc.status == 403:
            if "not licensed to use Copilot" in body:
                return "Unauthorized: not licensed to use Copilot."
            if "not authorized to use this Copilot feature" in body:
                return "Unauthorized: not authorized to use this Copilot feature."
            if "integration does not have GitHub chat enabled" in body:
                return "Integration does not have GitHub chat enabled."
        return f"Copilot request failed: {exc.status or body[:200]}"

    def create_push_protection_bypass(
        self, owner: str, name: str, reason: str, placeholder_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"reason": reason}
        if placeholder_id:
            body["placeholder_id"] = placeholder_id
        return self.post(f"/repos/{owner}/{name}/secret-scanning/push-protection-bypasses", body)

    def _to_repo(self, data: dict[str, Any]) -> GitHubRepository:
        owner = data.get("owner") or {}
        parent_data = data.get("parent")
        parent = self._to_repo(parent_data) if parent_data else None
        return GitHubRepository(
            name=data.get("name") or "",
            owner=owner.get("login") or "",
            html_url=data.get("html_url") or "",
            clone_url=data.get("clone_url") or "",
            ssh_url=data.get("ssh_url") or "",
            default_branch=data.get("default_branch") or "main",
            private=bool(data.get("private")),
            fork=bool(data.get("fork")),
            parent=parent,
            endpoint=self.endpoint,
            permissions=(data.get("permissions") or {}).get("push") and "write" or "read",
            has_issues=bool(data.get("has_issues", True)),
            archived=bool(data.get("archived")),
        )

    def _to_pr(self, data: dict[str, Any]) -> PullRequest:
        head = data.get("head") or {}
        base = data.get("base") or {}
        user = data.get("user") or {}
        repo = head.get("repo") or {}
        return PullRequest(
            number=int(data.get("number") or 0),
            title=data.get("title") or "",
            body=data.get("body") or "",
            created_at=data.get("created_at") or "",
            author=user.get("login") or "",
            draft=bool(data.get("draft")),
            head_ref=head.get("ref") or "",
            head_sha=head.get("sha") or "",
            base_ref=base.get("ref") or "",
            html_url=data.get("html_url") or "",
            state=data.get("state") or "open",
            head_clone_url=repo.get("clone_url"),
            head_owner=(head.get("user") or {}).get("login"),
            updated_at=data.get("updated_at") or "",
        )


def merge_updated_pull_requests(
    existing: list[PullRequest], updated: list[PullRequest]
) -> list[PullRequest]:
    """Upsert open PRs and prune closed/merged ones (Desktop `storePullRequests`)."""
    by_number = {pr.number: pr for pr in existing}
    for pr in updated:
        if (pr.state or "open").lower() != "open":
            by_number.pop(pr.number, None)
        else:
            by_number[pr.number] = pr
    return sorted(by_number.values(), key=lambda item: item.updated_at or item.created_at, reverse=True)


def merge_updated_issues(existing: list[Issue], fetched: list[Issue]) -> list[Issue]:
    """Upsert open issues and prune closed ones (Desktop `storeIssues`)."""
    by_number = {issue.number: issue for issue in existing}
    for issue in fetched:
        if (issue.state or "open").lower() == "closed":
            by_number.pop(issue.number, None)
        else:
            by_number[issue.number] = issue
    return sorted(by_number.values(), key=lambda item: item.number, reverse=True)


def _parse_generated_message(content: str) -> tuple[str, str]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        data = json.loads(content)
        return str(data.get("summary") or data.get("title") or ""), str(data.get("description") or data.get("body") or "")
    except json.JSONDecodeError:
        lines = content.splitlines()
        summary = lines[0] if lines else content
        description = "\n".join(lines[1:]).strip()
        return summary[:72], description


def delete_oauth_token(account: Account) -> bool:
    """Desktop `deleteToken`: `DELETE applications/{ClientID}/token` with Basic client credentials."""
    import base64
    import os

    from ..version import OAUTH_CLIENT_ID_DEFAULT, OAUTH_CLIENT_SECRET_DEFAULT

    if not account.token:
        return False
    client_id = os.environ.get("DESKTOP_OAUTH_CLIENT_ID") or OAUTH_CLIENT_ID_DEFAULT
    secret = os.environ.get("DESKTOP_OAUTH_CLIENT_SECRET") or OAUTH_CLIENT_SECRET_DEFAULT
    creds = base64.b64encode(f"{client_id}:{secret}".encode("ascii")).decode("ascii")
    api = GitHubAPI(account.endpoint, None)
    try:
        api.delete(
            f"/applications/{client_id}/token",
            body={"access_token": account.token},
            extra_headers={"Authorization": f"Basic {creds}"},
        )
        return True
    except Exception as exc:
        log.error("deleteToken: failed with endpoint %s: %s", account.endpoint, exc)
        return False


def request_oauth_token(html_base: str, client_id: str, client_secret: str, code: str) -> str | None:
    url = html_base.rstrip("/") + "/login/oauth/access_token"
    body = urllib.parse.urlencode(
        {"client_id": client_id, "client_secret": client_secret, "code": code}
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload.get("access_token")
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        log.warning("request_oauth_token failed: %s", exc)
        return None
