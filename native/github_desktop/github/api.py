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
    GitHubRepository,
    Issue,
    PullRequest,
    RefCheck,
    html_url_from_endpoint,
)
from ..version import APP_NAME, __version__

log = get_logger()

DOTCOM_API = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/{__version__}"
PER_PAGE = 100


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
            raise APIError(
                f"GitHub API {method} {url} failed: {exc.code} {payload[:500]}",
                status=exc.code,
                body=payload,
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
        emails = []
        try:
            emails = [e.get("email", "") for e in self.fetch_emails() if e.get("email")]
        except APIError:
            if user.get("email"):
                emails = [user["email"]]
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

    def fetch_check_runs(self, owner: str, name: str, ref: str) -> list[RefCheck]:
        try:
            data = self.get(f"/repos/{owner}/{name}/commits/{urllib.parse.quote(ref)}/check-runs")
        except APIError:
            return []
        runs = data.get("check_runs", []) if isinstance(data, dict) else []
        return [
            RefCheck(
                id=int(r.get("id") or 0),
                name=r.get("name") or "",
                description=(r.get("output") or {}).get("title") or r.get("title") or "",
                status=r.get("status") or "",
                conclusion=r.get("conclusion"),
                html_url=r.get("html_url"),
                app_name=(r.get("app") or {}).get("name"),
            )
            for r in runs
        ]

    def rerequest_check_suite(self, owner: str, name: str, suite_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/check-suites/{suite_id}/rerequest")

    def rerequest_check_run(self, owner: str, name: str, run_id: int) -> None:
        self.post(f"/repos/{owner}/{name}/check-runs/{run_id}/rerequest")

    def fetch_protected_branches(self, owner: str, name: str) -> list[str]:
        try:
            items = self._paginate(f"/repos/{owner}/{name}/branches", {"protected": "true"})
            return [i.get("name") for i in items if i.get("name")]
        except APIError:
            return []

    def fetch_mentions(self, owner: str, name: str) -> list[str]:
        try:
            items = self.get(f"/repos/{owner}/{name}/collaborators")
            if isinstance(items, list):
                return [i.get("login") for i in items if i.get("login")]
        except APIError:
            return []
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
