"""Turn GitHub /notifications payloads into Desktop popup actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import PopupType, PullRequest

REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"}

REVIEW_VERBS = {
    "APPROVED": "approved",
    "CHANGES_REQUESTED": "requested changes on",
    "COMMENTED": "commented on",
    "DISMISSED": "dismissed a review of",
}


@dataclass
class NotificationAction:
    title: str
    body: str
    popup: PopupType | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def pull_request_from_payload(data: dict[str, Any] | PullRequest | None) -> PullRequest | None:
    if isinstance(data, PullRequest):
        return data
    if not isinstance(data, dict):
        return None
    number = data.get("number")
    if not number:
        html = str(data.get("html_url") or data.get("url") or "")
        for part in html.rstrip("/").split("/"):
            if part.isdigit():
                number = int(part)
                break
    if not number:
        return None
    user = data.get("user") or {}
    head = data.get("head") or {}
    base = data.get("base") or {}
    return PullRequest(
        number=int(number),
        title=data.get("title") or "",
        body=data.get("body") or "",
        created_at=data.get("created_at") or "",
        author=(user.get("login") if isinstance(user, dict) else None) or data.get("author") or "",
        draft=bool(data.get("draft")),
        head_ref=head.get("ref") if isinstance(head, dict) else data.get("head_ref") or "",
        head_sha=head.get("sha") if isinstance(head, dict) else data.get("head_sha") or "",
        base_ref=base.get("ref") if isinstance(base, dict) else data.get("base_ref") or "",
        html_url=data.get("html_url") or "",
        state=data.get("state") or "open",
    )


def review_verb(state: str) -> str:
    return REVIEW_VERBS.get((state or "").upper(), "reviewed")


def classify_notification(note: dict[str, Any], subject_payload: dict[str, Any] | None = None) -> NotificationAction:
    subject = note.get("subject") or {}
    stype = str(subject.get("type") or "")
    title = str(subject.get("title") or "GitHub notification")
    repo = note.get("repository") or {}
    repo_name = str(repo.get("full_name") or "GitHub")
    html_url = str(subject.get("url") or repo.get("html_url") or "")
    payload = subject_payload if isinstance(subject_payload, dict) else {}
    state = str(payload.get("state") or "").upper()
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    login = str(user.get("login") or payload.get("user") or "Someone")
    body_text = str(payload.get("body") or title)
    pr = pull_request_from_payload(payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else payload)

    common = {
        "repository": repo_name,
        "url": payload.get("html_url") or html_url,
        "html_url": payload.get("html_url") or html_url,
        "title": title,
        "body": body_text,
        "author": login,
        "pull_request": {
            "number": pr.number if pr else 0,
            "title": (pr.title if pr else title) or title,
            "html_url": (pr.html_url if pr else "") or payload.get("html_url") or "",
            "head_ref": pr.head_ref if pr else "",
            "head_sha": pr.head_sha if pr else "",
            "base_ref": pr.base_ref if pr else "",
            "author": pr.author if pr else login,
            "body": pr.body if pr else "",
            "created_at": pr.created_at if pr else "",
            "draft": pr.draft if pr else False,
            "state": pr.state if pr else "open",
        },
    }

    if stype in ("CheckSuite", "CheckRun"):
        return NotificationAction(
            title=repo_name,
            body=title,
            popup=PopupType.PULL_REQUEST_CHECKS_FAILED,
            payload={**common, "error": title},
        )

    is_review = state in REVIEW_STATES or bool(payload.get("submitted_at"))
    is_pr_resource = bool(payload.get("head") or payload.get("base")) and not is_review
    if is_review and stype in ("PullRequest", ""):
        review = {
            "state": state or "COMMENTED",
            "body": body_text,
            "html_url": payload.get("html_url") or html_url,
            "submitted_at": payload.get("submitted_at") or payload.get("created_at") or "",
            "user": {"login": login, "avatar_url": user.get("avatar_url") or ""},
        }
        return NotificationAction(
            title=repo_name,
            body=f"{login} {review_verb(review['state'])} {title}",
            popup=PopupType.PULL_REQUEST_REVIEW,
            payload={**common, "review": review, "should_checkout": review["state"] != "APPROVED"},
        )

    is_comment = bool(payload) and not is_pr_resource and (
        "diff_hunk" in payload
        or payload.get("pull_request_review_id") is not None
        or "/comments/" in str(payload.get("url") or payload.get("html_url") or "")
        or bool(payload.get("body") and user)
    )
    if stype in ("PullRequest", "Issue") and is_comment:
        comment = {
            "body": body_text,
            "html_url": payload.get("html_url") or html_url,
            "created_at": payload.get("created_at") or "",
            "user": {"login": login, "avatar_url": user.get("avatar_url") or ""},
        }
        popup = PopupType.PULL_REQUEST_COMMENT if stype == "PullRequest" else None
        return NotificationAction(
            title=repo_name,
            body=f"{login} commented: {title}",
            popup=popup,
            payload={**common, "comment": comment, "should_checkout": True},
        )

    return NotificationAction(title=repo_name, body=title, popup=None, payload=common)
