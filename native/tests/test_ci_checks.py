"""Desktop-parity CI check helpers, line-ending warnings, and avatar stacks."""

from __future__ import annotations

from datetime import datetime, timezone

from github_desktop.git.diff import parse_line_endings_warning
from github_desktop.github.ci_checks import (
    attach_workflow_jobs_to_checks,
    check_run_step_url,
    checks_header_state,
    format_precise_duration,
    get_check_run_short_description,
    get_check_status_count_map,
    get_combined_status_summary,
    group_check_runs_by_workflow,
    is_failure,
    split_rerunnable_checks,
    to_sentence,
)
from github_desktop.models import CheckSuite, Commit, CommitIdentity, RefCheck
from github_desktop.ui.avatar import users_from_commit


def _run(**kwargs) -> RefCheck:
    defaults = dict(id=1, name="build", description="", status="completed", conclusion="success")
    defaults.update(kwargs)
    return RefCheck(**defaults)


def test_to_sentence_and_duration() -> None:
    assert to_sentence([]) == ""
    assert to_sentence(["one"]) == "one"
    assert to_sentence(["one", "two"]) == "one and two"
    assert to_sentence(["one", "two", "three"]) == "one, two, and three"
    assert format_precise_duration(3_670_000) == "1h 1m 10s"


def test_short_description_and_failure() -> None:
    assert get_check_run_short_description("in_progress", None) == "In progress"
    assert "Successful in" in get_check_run_short_description("completed", "success", 5000)
    assert is_failure(_run(conclusion="failure"))
    assert not is_failure(_run(conclusion="success"))


def test_group_by_workflow_and_header() -> None:
    from github_desktop.models import ActionsWorkflow

    ci = _run(id=1, name="linux", actions_workflow=ActionsWorkflow(id=9, name="CI", event="push"))
    scan = _run(id=2, name="codeql", app_name="GitHub Code Scanning", conclusion="neutral")
    groups = group_check_runs_by_workflow([ci, scan])
    assert "CI" in groups
    assert "Code scanning results" in groups
    title, css = checks_header_state([ci, scan])
    assert title == "All checks have passed"
    assert css == "success"
    failed = _run(id=3, name="test", conclusion="failure")
    title, css = checks_header_state([ci, failed])
    assert title == "Some checks were not successful"
    assert "1 successful and 1 failed checks" == get_combined_status_summary([ci, failed]) or "failed" in get_combined_status_summary(
        [ci, failed]
    )
    from github_desktop.models import CheckStep

    steps = [
        CheckStep(name="a", number=1, status="completed", conclusion="success"),
        CheckStep(name="b", number=2, status="completed", conclusion="failure"),
    ]
    assert get_combined_status_summary(steps, "step") == "1 successful and 1 failed steps"


def test_check_status_count_map() -> None:
    mixed = [
        _run(id=1, name="a", conclusion="success"),
        _run(id=2, name="b", conclusion="failure"),
        _run(id=3, name="c", status="in_progress", conclusion=None),
    ]
    counts = get_check_status_count_map(mixed)
    assert counts["success"] == 1
    assert counts["failure"] == 1
    assert counts["in_progress"] == 1


def test_attach_jobs_matches_by_id() -> None:
    run = _run(id=42, name="linux")
    jobs = [
        {
            "id": 42,
            "name": "linux",
            "html_url": "https://github.com/o/r/actions/runs/1/job/42",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:01:05Z",
            "steps": [{"name": "checkout", "number": 1, "status": "completed", "conclusion": "success", "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-01T00:00:04Z"}],
            "_workflow": {"id": 7, "name": "CI", "event": "pull_request", "check_suite_id": 99, "html_url": "https://github.com/o/r/actions/runs/7"},
        }
    ]
    mapped = attach_workflow_jobs_to_checks([run], jobs)
    assert mapped[0].html_url.endswith("/job/42")
    assert mapped[0].actions_workflow is not None
    assert mapped[0].actions_workflow.name == "CI"
    assert mapped[0].steps[0].name == "checkout"
    url = check_run_step_url(mapped[0], mapped[0].steps[0])
    assert url.endswith("#step:1:1")


def test_split_rerunnable_respects_age_and_rerequestable() -> None:
    fresh = _run(id=1, name="a", check_suite_id=10, conclusion="failure")
    old = _run(id=2, name="b", check_suite_id=11, conclusion="failure")
    suites = {
        10: CheckSuite(id=10, rerequestable=True, status="completed", created_at="2026-08-01T00:00:00Z"),
        11: CheckSuite(id=11, rerequestable=True, status="completed", created_at="2025-01-01T00:00:00Z"),
    }
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    rerunnable, skipped = split_rerunnable_checks([fresh, old], suites, failed_only=True, now=now)
    assert [r.id for r in rerunnable] == [1]
    assert [r.id for r in skipped] == [2]


def test_parse_line_endings_warning_desktop_format() -> None:
    stderr = "warning: in the working copy of 'file.txt', LF will be replaced by CRLF the next time Git touches it"
    assert parse_line_endings_warning(stderr) == ("LF", "CRLF")
    assert parse_line_endings_warning("LF will be replaced by CRLF in file.txt") == ("LF", "CRLF")
    assert parse_line_endings_warning("") is None


def test_users_from_commit_include_coauthors() -> None:
    identity = CommitIdentity(name="Ada", email="ada@example.com", date=datetime.now(timezone.utc))
    committer = CommitIdentity(name="Bot", email="bot@example.com", date=datetime.now(timezone.utc))
    commit = Commit(
        sha="abc",
        short_sha="abc",
        summary="hi",
        body="",
        author=identity,
        committer=committer,
        trailers=[("Co-authored-by", "Grace <grace@example.com>")],
    )
    users = users_from_commit(commit)
    names = {name for name, _email in users}
    assert "Ada" in names
    assert "Bot" in names
    assert "Grace" in names


def test_get_latest_check_runs_by_id_keeps_newest_suite() -> None:
    from github_desktop.github.ci_checks import get_latest_check_runs_by_id

    older = _run(id=1, name="build", check_suite_id=10, has_pull_requests=True)
    newer = _run(id=2, name="build", check_suite_id=20, has_pull_requests=True)
    push = _run(id=3, name="build", check_suite_id=15, has_pull_requests=False)
    latest = get_latest_check_runs_by_id([older, newer, push])
    by_id = {run.id for run in latest}
    assert 2 in by_id
    assert 1 not in by_id
    assert 3 in by_id


def test_map_workflows_and_pending_rerun() -> None:
    from github_desktop.github.ci_checks import (
        get_latest_pr_workflow_runs,
        manually_set_checks_to_pending,
        map_action_workflows_runs_to_check_runs,
    )
    from github_desktop.models import CheckStep

    runs = [
        {"id": 1, "workflow_id": 9, "created_at": "2026-01-01T00:00:00Z", "check_suite_id": 10, "name": "CI"},
        {"id": 2, "workflow_id": 9, "created_at": "2026-02-01T00:00:00Z", "check_suite_id": 11, "name": "CI"},
    ]
    latest = get_latest_pr_workflow_runs(runs)
    assert len(latest) == 1
    assert latest[0]["id"] == 2
    check = _run(id=5, name="linux", check_suite_id=11, conclusion="failure")
    mapped = map_action_workflows_runs_to_check_runs([check], latest)
    assert mapped[0].actions_workflow is not None
    assert mapped[0].actions_workflow.id == 2
    check.steps = [CheckStep(name="test", status="completed", conclusion="failure")]
    pending = manually_set_checks_to_pending([check], [check])
    assert pending[0].status == "in_progress"
    assert pending[0].conclusion is None
    assert pending[0].steps[0].status == "in_progress"


def test_get_latest_pr_workflow_runs_logs_for_check_run() -> None:
    from github_desktop.github.ci_checks import get_latest_pr_workflow_runs_logs_for_check_run
    from github_desktop.models import ActionsWorkflow

    class FakeAPI:
        def fetch_workflow_run_jobs(self, owner, repo, run_id):
            assert (owner, repo, run_id) == ("o", "r", 9)
            return {
                "jobs": [
                    {
                        "id": 5,
                        "html_url": "https://github.com/o/r/actions/runs/9/job/5",
                        "steps": [
                            {
                                "name": "Set up job",
                                "number": 1,
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ],
                    }
                ]
            }

    check = _run(
        id=5,
        name="linux",
        actions_workflow=ActionsWorkflow(id=9, name="CI", event="pull_request"),
    )
    mapped = get_latest_pr_workflow_runs_logs_for_check_run(FakeAPI(), "o", "r", [check])
    assert mapped[0].html_url == "https://github.com/o/r/actions/runs/9/job/5"
    assert mapped[0].steps[0].name == "Set up job"
    assert mapped[0].actionJobSteps is not None
    from github_desktop.github.ci_checks import are_no_check_steps, view_check_details_url

    assert are_no_check_steps(mapped[0]) is False
    assert view_check_details_url(mapped[0]).endswith("/job/5")
