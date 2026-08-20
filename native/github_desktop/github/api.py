"""GitHub REST API client (dotcom + Enterprise) plus Copilot commit messages."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from ..errors import APIError, CopilotError
from ..logging import get_logger
from ..models import (
    Account,
    AccountEmail,
    CheckSuite,
    GitHubRepository,
    Issue,
    PullRequest,
    RefCheck,
)
from .ci_checks import annotation_from_api, api_status_to_ref_check, duration_ms, get_check_run_short_description
from .push_control import PushControl, default_push_control
from ..version import APP_NAME, __version__

log = get_logger()

DOTCOM_API = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/{__version__}"
PER_PAGE = 100

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
                raw = resp.read()
                if not raw:
                    return None
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype or raw[:1] in (b"{", b"["):
                    return json.loads(raw.decode("utf-8"))
                return raw.decode("utf-8")
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
        try:
            info = self.fetch_copilot_info()
            if info:
                copilot_endpoint = (
                    info.get("copilot_endpoint")
                    or (info.get("copilotEndpoints") or {}).get("api")
                )
        except APIError:
            pass
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

    def fetch_issues(self, owner: str, name: str) -> list[Issue]:
        items = self._paginate(f"/repos/{owner}/{name}/issues", {"state": "open"})
        issues = []
        for item in items:
            if "pull_request" in item:
                continue
            issues.append(Issue(number=item["number"], title=item["title"], state=item.get("state", "open")))
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
        return statuses + mapped

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
            try:
                payload = self.get(f"/repos/{owner}/{name}/actions/runs/{run_id}/jobs")
            except APIError:
                continue
            workflow_meta = {
                "id": int(run_id),
                "name": run.get("name") or "",
                "event": run.get("event") or "",
                "check_suite_id": run.get("check_suite_id"),
                "html_url": run.get("html_url"),
            }
            for job in (payload or {}).get("jobs") or []:
                job["_workflow"] = workflow_meta
                jobs.append(job)
        return jobs

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

    def fetch_mentionables(self, owner: str, name: str) -> list[dict[str, Any]]:
        """Desktop `fetchMentionables` (`/mentionables/users` jerry-maguire preview)."""
        extra = {"Accept": "application/vnd.github.jerry-maguire-preview"}
        try:
            data = self.get(
                f"/repos/{owner}/{name}/mentionables/users",
                extra_headers=extra,
            )
        except APIError as exc:
            if exc.status == 404:
                return []
            log.debug("fetch_mentionables failed: %s", exc)
            return []
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
        return users

    def fetch_mentions(self, owner: str, name: str) -> list[str]:
        mentionables = self.fetch_mentionables(owner, name)
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

    def create_issue(self, owner: str, name: str, title: str, body: str = "") -> dict[str, Any]:
        return self.post(f"/repos/{owner}/{name}/issues", {"title": title, "body": body})

    def generate_commit_message(self, diff: str, files: Iterable[str]) -> tuple[str, str]:
        if not self.copilot_endpoint:
            raise CopilotError("Copilot is not available for this account")
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
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise CopilotError(f"Copilot request failed: {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CopilotError(f"Copilot network error: {exc}") from exc
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise CopilotError("Unexpected Copilot response") from exc
        summary, description = _parse_generated_message(content)
        return summary, description

    def create_push_protection_bypass(
        self, owner: str, name: str, reason: str, placeholder_id: str | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"reason": reason}
        if placeholder_id:
            body["placeholder_id"] = placeholder_id
        return self.post(f"/repos/{owner}/{name}/push-protection-bypasses", body)

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
        )


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
