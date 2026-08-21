"""CI check helpers matching GitHub Desktop's lib/ci-checks."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isnan
from typing import Any, Iterable, Sequence

from ..models import (
    ActionsWorkflow,
    CheckAnnotation,
    CheckStep,
    CheckSuite,
    RefCheck,
)

FAILING_CONCLUSIONS = ("failure", "cancelled", "canceled", "action_required", "timed_out")
SUCCESSISH_CONCLUSIONS = ("success", "neutral", "skipped")
RERUNNABLE_MAX_AGE = timedelta(days=30)
MAX_JOB_LOG_CHARS = 512 * 1024


def to_sentence(parts: Sequence[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return ", ".join(parts[:-1]) + ", and " + parts[-1]


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def duration_ms(started_at: str | None, completed_at: str | None) -> int | None:
    start = parse_iso(started_at)
    end = parse_iso(completed_at)
    if start is None or end is None:
        return None
    delta = int((end - start).total_seconds() * 1000)
    return delta


def format_precise_duration(ms: int | float) -> str:
    remaining = abs(int(ms))
    units = (("d", 86_400_000), ("h", 3_600_000), ("m", 60_000), ("s", 1_000))
    parts: list[str] = []
    for short, size in units:
        if parts or remaining >= size or short == "s":
            qty = remaining // size
            remaining -= qty * size
            parts.append(f"{qty}{short}")
    return " ".join(parts)


def format_long_precise_duration(ms: int | float) -> str:
    remaining = abs(int(ms))
    units = (("day", 86_400_000), ("hour", 3_600_000), ("minute", 60_000), ("second", 1_000))
    parts: list[str] = []
    for name, size in units:
        if parts or remaining >= size or name == "second":
            qty = remaining // size
            remaining -= qty * size
            suffix = "" if qty == 1 else "s"
            parts.append(f"{qty} {name}{suffix}")
    return " ".join(parts)


def get_check_duration_in_milliseconds(check: Any) -> float:
    """Desktop `getCheckDurationInMilliseconds`. NaN when either timestamp fails to parse."""
    if isinstance(check, dict):
        started = check.get("started_at")
        completed = check.get("completed_at")
    else:
        started = getattr(check, "started_at", None)
        completed = getattr(check, "completed_at", None)
    start = parse_iso(started)
    end = parse_iso(completed)
    if start is None or end is None:
        return float("nan")
    return (end - start).total_seconds() * 1000


def get_formatted_check_run_duration(check: Any) -> str:
    """Desktop `getFormattedCheckRunDuration` (``1h 1m 10s``)."""
    duration = get_check_duration_in_milliseconds(check)
    return "" if isnan(duration) else format_precise_duration(duration)


def get_formatted_check_run_long_duration(check: Any) -> str:
    """Desktop `getFormattedCheckRunLongDuration` (``1 hour 1 minute 10 seconds``)."""
    duration = get_check_duration_in_milliseconds(check)
    return "" if isnan(duration) else format_long_precise_duration(duration)


def get_check_run_conclusion_adjective(conclusion: str | None) -> str:
    if conclusion is None:
        return "In progress"
    mapping = {
        "action_required": "Action required",
        "cancelled": "Canceled",
        "canceled": "Canceled",
        "timed_out": "Timed out",
        "failure": "Failed",
        "neutral": "Neutral",
        "success": "Successful",
        "skipped": "Skipped",
        "stale": "Marked as stale",
    }
    return mapping.get(conclusion, conclusion.replace("_", " ").title())


def get_check_run_short_description(
    status: str,
    conclusion: str | None,
    duration: int | None = None,
) -> str:
    if status != "completed" or conclusion is None:
        return "In progress"
    adjective = get_check_run_conclusion_adjective(conclusion)
    if conclusion in {"action_required", "skipped", "stale"}:
        return adjective
    preposition = "in" if conclusion == "success" else "after"
    if duration is not None and duration > 0:
        return f"{adjective} {preposition} {format_precise_duration(duration)}"
    return adjective


def is_incomplete(check: RefCheck | CheckStep) -> bool:
    if check.status == "completed" and check.conclusion in {"timed_out", "stale", "cancelled", "canceled"}:
        return True
    return False


def is_failure(check: RefCheck | CheckStep) -> bool:
    if check.status == "completed" and check.conclusion in {"failure", "action_required"}:
        return True
    return False


def is_incomplete_or_failure(check: RefCheck | CheckStep) -> bool:
    return is_incomplete(check) or is_failure(check)


def failing_checks(runs: Iterable[RefCheck]) -> list[RefCheck]:
    return [r for r in runs if r.conclusion in FAILING_CONCLUSIONS or is_failure(r)]


def api_status_to_ref_check(api_status: dict) -> RefCheck:
    """Desktop `apiStatusToRefCheck`: map a legacy combined commit status to `IRefCheck`."""
    state = str(api_status.get("state") or "")
    if state == "success":
        status, conclusion = "completed", "success"
    elif state == "pending":
        status, conclusion = "in_progress", None
    else:
        status, conclusion = "completed", "failure"
    return RefCheck(
        id=int(api_status.get("id") or 0),
        name=api_status.get("context") or "",
        description=get_check_run_short_description(status, conclusion),
        status=status,
        conclusion=conclusion,
        html_url=api_status.get("target_url"),
        app_name="",
        check_suite_id=None,
    )


def summarize_check_runs(runs: Sequence[RefCheck]) -> str:
    """Desktop `CIStatus` roll-up: success, failure, pending, or empty."""
    items = list(runs)
    if not items:
        return ""
    if failing_checks(items):
        return "failure"
    if any(item.status != "completed" for item in items):
        return "pending"
    return "success"


def check_run_step_url(
    check: RefCheck,
    step: CheckStep,
    repository_html_url: str | None = None,
    pull_request_number: int | None = None,
) -> str | None:
    if check.html_url:
        return f"{check.html_url.rstrip('/')}/#step:{step.number}:1"
    if repository_html_url and pull_request_number:
        return f"{repository_html_url.rstrip('/')}/pull/{pull_request_number}"
    return None


def get_combined_status_summary(runs: Sequence[RefCheck], description: str = "check") -> str:
    if not runs:
        return ""
    grouped: dict[str | None, int] = defaultdict(int)
    for run in runs:
        grouped[run.conclusion] += 1
    phrases = [
        f"{count} {get_check_run_conclusion_adjective(conclusion).lower()}"
        for conclusion, count in grouped.items()
    ]
    noun = description if len(runs) == 1 else f"{description}s"
    return f"{to_sentence(phrases)} {noun}"


def get_check_status_count_map(runs: Sequence[RefCheck]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for run in runs:
        counts[run.conclusion or run.status or "unknown"] += 1
    return dict(counts)


def get_latest_check_runs_by_id(check_runs: Sequence[RefCheck]) -> list[RefCheck]:
    """Desktop `getLatestCheckRunsById`: keep the newest suite per check name and PR/push origin."""
    latest: dict[str, RefCheck] = {}
    for run in check_runs:
        key = f"{run.name}:{('isPullRequestCheckRun' if run.has_pull_requests else 'isPushCheckRun')}"
        current = latest.get(key)
        if current is None:
            latest[key] = run
            continue
        current_suite = int(current.check_suite_id or 0)
        given_suite = int(run.check_suite_id or 0)
        if current_suite < given_suite:
            latest[key] = run
    return list(latest.values())


def actions_workflow_from_run(run: dict) -> ActionsWorkflow | None:
    run_id = run.get("id")
    if not run_id:
        return None
    return ActionsWorkflow(
        id=int(run_id),
        name=str(run.get("name") or ""),
        event=str(run.get("event") or ""),
        check_suite_id=run.get("check_suite_id"),
        html_url=run.get("html_url"),
    )


def get_latest_pr_workflow_runs(workflow_runs: Sequence[dict]) -> list[dict]:
    """Keep the newest Actions run per `workflow_id` (Desktop `getLatestPRWorkflowRunsByBranchName`)."""
    latest: dict[int, dict] = {}
    for run in workflow_runs:
        workflow_id = int(run.get("workflow_id") or 0)
        if not workflow_id:
            continue
        stored = latest.get(workflow_id)
        if stored is None:
            latest[workflow_id] = run
            continue
        if str(stored.get("created_at") or "") < str(run.get("created_at") or ""):
            latest[workflow_id] = run
    return list(latest.values())


def map_action_workflows_runs_to_check_runs(
    check_runs: Sequence[RefCheck], action_workflow_runs: Sequence[dict]
) -> list[RefCheck]:
    """Desktop `mapActionWorkflowsRunsToCheckRuns`: match by check suite id."""
    if not action_workflow_runs or not check_runs:
        return list(check_runs)
    by_suite: dict[int, dict] = {}
    for run in action_workflow_runs:
        suite_id = run.get("check_suite_id")
        if suite_id is not None:
            by_suite[int(suite_id)] = run
    mapped: list[RefCheck] = []
    for check in check_runs:
        matching = by_suite.get(int(check.check_suite_id)) if check.check_suite_id else None
        if matching:
            check.actions_workflow = actions_workflow_from_run(matching) or check.actions_workflow
        mapped.append(check)
    return mapped


def manually_set_checks_to_pending(
    cached_checks: Sequence[RefCheck], pending_checks: Sequence[RefCheck]
) -> list[RefCheck]:
    """Desktop `manuallySetChecksToPending`: optimistic in-progress after a re-run."""
    pending_ids = {check.id for check in pending_checks}
    updated: list[RefCheck] = []
    for check in cached_checks:
        if check.id not in pending_ids:
            updated.append(check)
            continue
        check.status = "in_progress"
        check.conclusion = None
        for step in check.steps or []:
            step.status = "in_progress"
            step.conclusion = None
        updated.append(check)
    return updated


def checks_header_state(runs: Sequence[RefCheck], *, loading: bool = False) -> tuple[str, str]:
    """Return (title, css_class) for the Desktop checks popover header."""
    if loading:
        return "Checks Summary", ""
    some_pending = any(v.conclusion is None for v in runs) and not any(
        v.conclusion in FAILING_CONCLUSIONS for v in runs if v.conclusion
    )
    if some_pending:
        return "Some checks haven't completed yet", "pending"
    all_failure = bool(runs) and all(
        v.conclusion in FAILING_CONCLUSIONS for v in runs
    )
    if all_failure:
        return "All checks have failed", "failure"
    all_success = bool(runs) and all(
        v.conclusion in SUCCESSISH_CONCLUSIONS for v in runs
    )
    if all_success:
        return "All checks have passed", "success"
    if not runs:
        return "No checks for this branch", ""
    return "Some checks were not successful", "failure"


def group_check_runs_by_workflow(runs: Sequence[RefCheck]) -> dict[str, list[RefCheck]]:
    events = {r.actions_workflow.event for r in runs if r.actions_workflow and r.actions_workflow.event.strip()}
    multiple_events = len(events) > 1
    groups: dict[str, list[RefCheck]] = {}
    for run in runs:
        group = run.actions_workflow.name if run.actions_workflow else "Other"
        if multiple_events and run.actions_workflow and run.actions_workflow.event.strip():
            group = f"{group} ({run.actions_workflow.event})"
        if group == "Other" and run.app_name == "GitHub Code Scanning":
            group = "Code scanning results"
        groups.setdefault(group, []).append(run)
    for name, items in groups.items():
        items.sort(key=lambda r: r.name.lower())
        groups[name] = items
    return {name: groups[name] for name in check_run_group_names(groups)}


def check_run_group_names(groups: dict[str, Sequence[RefCheck]]) -> list[str]:
    names = list(groups.keys())

    def sort_key(name: str) -> tuple[int, str]:
        return (1 if name == "Other" else 0, name.lower())

    names.sort(key=sort_key)
    return names


def _step_from_api(step: dict, job_html: str | None) -> CheckStep:
    return CheckStep(
        name=step.get("name") or "",
        number=int(step.get("number") or 0),
        status=step.get("status") or "",
        conclusion=step.get("conclusion"),
        html_url=job_html,
        started_at=step.get("started_at"),
        completed_at=step.get("completed_at"),
    )


def get_latest_pr_workflow_runs_logs_for_check_run(
    api: Any,
    owner: str,
    repo: str,
    check_runs: Sequence[RefCheck],
) -> list[RefCheck]:
    """Desktop `getLatestPRWorkflowRunsLogsForCheckRun`: job steps via `fetchWorkflowRunJobs`."""
    jobs_cache: dict[int, dict | None] = {}
    mapped: list[RefCheck] = []
    for check in check_runs:
        workflow = check.actions_workflow
        if workflow is None:
            mapped.append(check)
            continue
        run_id = int(workflow.id)
        if run_id not in jobs_cache:
            jobs_cache[run_id] = api.fetch_workflow_run_jobs(owner, repo, run_id)
        payload = jobs_cache[run_id]
        jobs = (payload or {}).get("jobs") or [] if isinstance(payload, dict) else []
        matching = next((job for job in jobs if isinstance(job, dict) and job.get("id") == check.id), None)
        if matching is None:
            mapped.append(check)
            continue
        html = matching.get("html_url") or check.html_url
        check.html_url = html
        check.steps = [_step_from_api(step, html) for step in (matching.get("steps") or [])]
        mapped.append(check)
    return mapped


def attach_workflow_jobs_to_checks(check_runs: Sequence[RefCheck], jobs: Sequence[dict]) -> list[RefCheck]:
    """Match Actions jobs onto check runs the same way Desktop does (job id == check run id)."""
    by_id: dict[int, dict] = {}
    by_name: dict[str, dict] = {}
    for job in jobs:
        job_id = job.get("id")
        if job_id is not None:
            by_id[int(job_id)] = job
        if job.get("name"):
            by_name[str(job["name"])] = job
    mapped: list[RefCheck] = []
    for run in check_runs:
        job = by_id.get(run.id) or by_name.get(run.name)
        if not job:
            mapped.append(run)
            continue
        wf = job.get("_workflow") or {}
        workflow = None
        if wf.get("id"):
            workflow = ActionsWorkflow(
                id=int(wf["id"]),
                name=str(wf.get("name") or ""),
                event=str(wf.get("event") or ""),
                check_suite_id=wf.get("check_suite_id"),
                html_url=wf.get("html_url"),
            )
        html = job.get("html_url") or run.html_url
        started = job.get("started_at") or run.started_at
        completed = job.get("completed_at") or run.completed_at
        steps = [_step_from_api(step, html) for step in (job.get("steps") or [])]
        duration = duration_ms(started, completed)
        run.html_url = html
        run.started_at = started
        run.completed_at = completed
        run.actions_workflow = workflow or run.actions_workflow
        run.steps = steps
        run.description = get_check_run_short_description(run.status, run.conclusion, duration)
        mapped.append(run)
    return mapped


def split_rerunnable_checks(
    check_runs: Sequence[RefCheck],
    suites: dict[int, CheckSuite],
    *,
    failed_only: bool = True,
    now: datetime | None = None,
) -> tuple[list[RefCheck], list[RefCheck]]:
    """Return (rerunnable, non_rerunnable) using Desktop's check-suite rules."""
    considered = failing_checks(check_runs) if failed_only else list(check_runs)
    stamp = now or datetime.now(timezone.utc)
    cutoff = stamp - RERUNNABLE_MAX_AGE
    rerunnable: list[RefCheck] = []
    skipped: list[RefCheck] = []
    for run in considered:
        suite = suites.get(run.check_suite_id) if run.check_suite_id else None
        if suite is None:
            skipped.append(run)
            continue
        created = parse_iso(suite.created_at)
        if (
            suite.rerequestable
            and suite.status == "completed"
            and created is not None
            and created > cutoff
        ):
            rerunnable.append(run)
        else:
            skipped.append(run)
    return rerunnable, skipped


def annotation_from_api(item: dict) -> CheckAnnotation:
    return CheckAnnotation(
        path=item.get("path") or "",
        message=item.get("message") or "",
        annotation_level=item.get("annotation_level") or "warning",
        start_line=item.get("start_line"),
        end_line=item.get("end_line"),
        title=item.get("title") or "",
    )
