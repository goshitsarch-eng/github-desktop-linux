"""CI checks popover, failed-checks dialog, re-run dialog, and job logs."""

from __future__ import annotations

from typing import Any

from ..models import CheckStep, RefCheck, is_dotcom_endpoint
from ..shells import open_external
from ..store import AppStore
from .menus import view_on_github_label


def _view_on_github_label(repo) -> str:
    enterprise = bool(repo and getattr(repo, "github", None) and not is_dotcom_endpoint(repo.github.endpoint))
    return view_on_github_label(enterprise=enterprise)


def _check_details_context(
    store: AppStore | None,
    repo,
    payload: dict[str, Any] | None,
) -> tuple[str | None, int | None]:
    payload = payload or {}
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    number = pr.get("number") or payload.get("number")
    repo_html = payload.get("repository_html_url")
    if repo is not None and getattr(repo, "github", None) is not None:
        repo_html = repo_html or repo.github.html_url
    if number is None and store is not None and repo is not None:
        current = store.state_for(repo).current_pull_request
        if current is not None:
            number = current.number
    try:
        pr_number = int(number) if number is not None else None
    except (TypeError, ValueError):
        pr_number = None
    return repo_html, pr_number


def onViewCheckExternally(
    run: RefCheck,
    *,
    store: AppStore | None = None,
    repo=None,
    payload: dict[str, Any] | None = None,
    increment_views: bool = False,
) -> None:
    """Desktop `onViewCheckExternally` / `onViewCheckDetails`."""
    repo_html, pr_number = _check_details_context(store, repo, payload)
    url = view_check_details_url(run, repo_html_url=repo_html, pr_number=pr_number)
    if not url:
        return
    if increment_views and store is not None:
        store.stats.increment("viewsCheckOnline")
    open_external(url)


DONUT_COLORS = {
    "success": (0.22, 0.72, 0.44),
    "neutral": (0.22, 0.72, 0.44),
    "skipped": (0.22, 0.72, 0.44),
    "failure": (0.86, 0.24, 0.29),
    "cancelled": (0.86, 0.24, 0.29),
    "canceled": (0.86, 0.24, 0.29),
    "timed_out": (0.86, 0.24, 0.29),
    "action_required": (0.86, 0.24, 0.29),
    "in_progress": (0.90, 0.64, 0.12),
    "queued": (0.55, 0.56, 0.58),
    "pending": (0.55, 0.56, 0.58),
    "stale": (0.55, 0.56, 0.58),
}


def _runs_from_payload(store: AppStore, payload: dict[str, Any]) -> list[RefCheck]:
    payload_checks = payload.get("checks") or payload.get("check_runs") or []
    coerced: list[RefCheck] = []
    for item in payload_checks:
        if isinstance(item, RefCheck):
            coerced.append(item)
        elif isinstance(item, dict):
            coerced.append(
                RefCheck(
                    id=int(item.get("id") or 0),
                    name=item.get("name") or "check",
                    description=item.get("description") or "",
                    status=item.get("status") or "",
                    conclusion=item.get("conclusion"),
                    html_url=item.get("html_url"),
                )
            )
    if coerced:
        return coerced
    repo = store.selected_repository
    if repo:
        live = list(store.state_for(repo).check_runs or [])
        if live:
            return live
    return coerced


def _step_subtitle(step: CheckStep) -> str:
    status = step.conclusion or step.status or ""
    short = get_formatted_check_run_duration(step)
    if short:
        return f"{status} · {short}".strip(" ·")
    return status


def _open_step(
    run: RefCheck,
    step: CheckStep,
    payload: dict[str, Any] | None = None,
    *,
    store: AppStore | None = None,
    increment_views: bool = False,
) -> None:
    payload = payload or {}
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    repo_html = payload.get("repository_html_url")
    number = pr.get("number") or payload.get("number")
    url = check_run_step_url(run, step, repo_html, int(number) if number else None)
    if url:
        if increment_views and store is not None:
            store.stats.increment("viewsCheckJobStepOnline")
        open_external(url)
