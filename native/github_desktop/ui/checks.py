"""CI checks popover, failed-checks dialog, re-run dialog, and job logs."""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk, Pango

from ..github.ci_checks import (
    check_run_step_url,
    checks_header_state,
    duration_ms,
    failing_checks,
    format_precise_duration,
    get_check_status_count_map,
    get_combined_status_summary,
    group_check_runs_by_workflow,
    is_failure,
)
from ..endpoint_capabilities import (
    supports_rerunning_checks,
    supports_rerunning_individual_or_failed_checks,
)
from ..models import CheckStep, PopupType, RefCheck, is_dotcom_endpoint
from ..shells import open_external
from ..store import AppStore
from .menus import view_on_github_label


def _view_on_github_label(repo) -> str:
    enterprise = bool(repo and getattr(repo, "github", None) and not is_dotcom_endpoint(repo.github.endpoint))
    return view_on_github_label(enterprise=enterprise)


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


class CompletenessDonut(Gtk.DrawingArea):
    """Desktop-style completeness donut for mixed check conclusions."""

    def __init__(self, counts: dict[str, int], size: int = 28) -> None:
        super().__init__()
        self._counts = {k: v for k, v in counts.items() if v > 0}
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_size_request(size, size)
        pending_keys = {"in_progress", "queued", "pending", "waiting"}
        in_progress = counts.get("in_progress", 0)
        queued = counts.get("queued", 0) + counts.get("pending", 0)
        completed = sum(v for k, v in counts.items() if k not in pending_keys)
        self.set_tooltip_text(
            f"Completeness indicator. {completed} completed, {in_progress} in progress, {queued} queued."
        )
        self.add_css_class("completeness-indicator")
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width: int, height: int) -> None:
        total = sum(self._counts.values()) or 1
        cx, cy = width / 2.0, height / 2.0
        radius = max(1.0, min(width, height) / 2.0 - 1.5)
        inner = radius * 0.55
        angle = -math.pi / 2
        for key, value in self._counts.items():
            sweep = (value / total) * 2 * math.pi
            color = DONUT_COLORS.get(key, (0.45, 0.47, 0.50))
            cr.set_source_rgb(*color)
            cr.move_to(cx, cy)
            cr.arc(cx, cy, radius, angle, angle + sweep)
            cr.close_path()
            cr.fill()
            angle += sweep
        try:
            from ..theme import is_dark

            if is_dark():
                cr.set_source_rgb(0.18, 0.18, 0.20)
            else:
                cr.set_source_rgb(0.97, 0.97, 0.98)
        except Exception:
            cr.set_source_rgb(0.96, 0.96, 0.97)
        cr.arc(cx, cy, inner, 0, 2 * math.pi)
        cr.fill()


def _completeness_widget(runs: list[RefCheck], title: str, css: str) -> Gtk.Widget:
    row = Gtk.Box(spacing=8)
    row.set_valign(Gtk.Align.CENTER)
    all_failure = title == "All checks have failed"
    if css == "success":
        img = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        img.add_css_class("completeness-indicator-success")
        img.set_pixel_size(22)
        row.append(img)
    elif all_failure:
        img = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        img.add_css_class("completeness-indicator-error")
        img.set_pixel_size(22)
        row.append(img)
    elif runs:
        row.append(CompletenessDonut(get_check_status_count_map(runs)))
    heading = Gtk.Label(label=title, xalign=0)
    heading.add_css_class("heading")
    if css:
        heading.add_css_class(f"checks-{css}")
    heading.set_hexpand(True)
    row.append(heading)
    return row


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
    ms = duration_ms(step.started_at, step.completed_at)
    if ms:
        return f"{status} · {format_precise_duration(ms)}".strip(" ·")
    return status


def _open_step(run: RefCheck, step: CheckStep, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    repo_html = payload.get("repository_html_url")
    number = pr.get("number") or payload.get("number")
    url = check_run_step_url(run, step, repo_html, int(number) if number else None)
    if url:
        open_external(url)


def _run_expander(
    run: RefCheck,
    *,
    store: AppStore | None = None,
    repo=None,
    payload: dict[str, Any] | None = None,
    on_rerun_one: Callable[[RefCheck], None] | None = None,
    expanded: bool = False,
) -> Adw.ExpanderRow:
    status = run.conclusion or run.status or "unknown"
    subtitle = run.description or status
    row = Adw.ExpanderRow(title=run.name or "check", subtitle=subtitle)
    row.set_expanded(expanded)
    if is_failure(run) or (run.conclusion in {"failure", "timed_out", "cancelled"}):
        row.add_css_class("checks-failure")
    elif run.conclusion in {"success", "neutral", "skipped"}:
        row.add_css_class("checks-success")
    if run.html_url:
        open_btn = Gtk.Button(icon_name="web-browser-symbolic")
        open_btn.add_css_class("flat")
        open_btn.set_tooltip_text("View check on GitHub")
        open_btn.connect("clicked", lambda *_ , url=run.html_url: open_external(url))
        row.add_suffix(open_btn)
    if on_rerun_one:
        rerun_one = Gtk.Button(icon_name="view-refresh-symbolic")
        rerun_one.add_css_class("flat")
        rerun_one.set_tooltip_text(f"Re-run {run.name}")
        rerun_one.connect("clicked", lambda *_ , r=run: on_rerun_one(r))
        row.add_suffix(rerun_one)
    if store and repo:
        logs_btn = Gtk.Button(label="View logs")
        logs_btn.add_css_class("flat")
        logs_btn.connect("clicked", lambda *_ , r=run: show_job_logs(logs_btn.get_root(), store, repo, r))
        row.add_suffix(logs_btn)
    steps = run.steps or []
    if steps:
        for step in steps:
            step_row = Adw.ActionRow(title=step.name or "step", subtitle=_step_subtitle(step))
            if step.number:
                link = Gtk.Button(icon_name="web-browser-symbolic")
                link.add_css_class("flat")
                link.set_tooltip_text(f"View {step.name} on GitHub")
                link.connect("clicked", lambda *_ , rn=run, st=step: _open_step(rn, st, payload or {}))
                step_row.add_suffix(link)
            row.add_row(step_row)
    else:
        row.add_row(Adw.ActionRow(title="No job steps loaded yet", subtitle="Open the check on GitHub for details."))
    for note in run.annotations or []:
        loc = f"{note.path}:{note.start_line}" if note.path else note.annotation_level
        row.add_row(Adw.ActionRow(title=note.title or note.message[:80], subtitle=f"{note.annotation_level} · {loc}"))
    return row


def _grouped_list(
    runs: Sequence[RefCheck],
    *,
    store: AppStore | None = None,
    repo=None,
    payload: dict[str, Any] | None = None,
    on_rerun_one: Callable[[RefCheck], None] | None = None,
) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    groups = group_check_runs_by_workflow(list(runs))
    hide_headers = len(groups) == 1 and next(iter(groups)) in {"Other", "Code scanning results"}
    first_failure_id = next((r.id for r in runs if is_failure(r) and r.steps), None)
    for group_name, items in groups.items():
        if not hide_headers:
            header = Gtk.Label(label=group_name, xalign=0)
            header.add_css_class("heading")
            box.append(header)
        group_box = Gtk.ListBox()
        group_box.add_css_class("boxed-list")
        for run in items:
            group_box.append(
                _run_expander(
                    run,
                    store=store,
                    repo=repo,
                    payload=payload,
                    on_rerun_one=on_rerun_one,
                    expanded=run.id == first_failure_id,
                )
            )
        box.append(group_box)
    return box


def present_checks_popover(anchor: Gtk.Widget, store: AppStore) -> None:
    repo = store.selected_repository
    if not repo:
        return
    popover = Gtk.Popover()
    popover.set_parent(anchor)
    holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

    def rebuild(_exc: object = None) -> None:
        try:
            if popover.get_parent() is None:
                return
        except Exception:
            return
        state = store.state_for(repo)
        runs = list(state.check_runs or [])
        child = holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            holder.remove(child)
            child = nxt
        holder.append(_popover_body(anchor, store, repo, runs, popover))

    holder.append(Gtk.Label(label="Stand by — check runs incoming!"))
    scroller = Gtk.ScrolledWindow()
    scroller.set_min_content_height(140)
    scroller.set_max_content_height(420)
    scroller.set_min_content_width(360)
    scroller.set_child(holder)
    popover.set_child(scroller)
    popover.popup()
    rebuild()
    store.load_check_steps(repo, on_done=rebuild)


def _popover_body(
    anchor: Gtk.Widget,
    store: AppStore,
    repo,
    runs: list[RefCheck],
    popover: Gtk.Popover,
) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(10)
    box.set_margin_bottom(10)
    box.set_margin_start(10)
    box.set_margin_end(10)
    title_text, css = checks_header_state(runs)
    box.append(_completeness_widget(runs, title_text, css))
    summary = get_combined_status_summary(runs)
    if summary:
        sub = Gtk.Label(label=summary, xalign=0, wrap=True)
        sub.add_css_class("dim-label")
        box.append(sub)
    if not runs:
        box.append(Gtk.Label(label="No checks for this branch", xalign=0))
        return box

    def rerun_one(run: RefCheck) -> None:
        popover.popdown()
        store.show_popup(PopupType.CI_CHECK_RUN_RERUN, checks=[run], failed_only=False)

    endpoint = repo.github.endpoint if repo and getattr(repo, "github", None) else ""
    individual = supports_rerunning_individual_or_failed_checks(endpoint)
    box.append(_grouped_list(runs, store=store, repo=repo, on_rerun_one=rerun_one if individual else None))
    failed = failing_checks(runs)
    actions = Gtk.Box(spacing=8)
    if failed and individual:
        rerun = Gtk.Button(label=f"Re-run {len(failed)} failed check(s)")
        rerun.add_css_class("suggested-action")

        def do_rerun(*_a: object) -> None:
            popover.popdown()
            store.show_popup(
                PopupType.CI_CHECK_RUN_RERUN,
                checks=runs,
                failed_only=True,
                on_rerun=lambda: store.rerun_checks(repo, failed_only=True),
            )

        rerun.connect("clicked", do_rerun)
        actions.append(rerun)
    if supports_rerunning_checks(endpoint):
        rerun_all = Gtk.Button(label="Re-run all checks")
        rerun_all.connect(
            "clicked",
            lambda *_: (
                popover.popdown(),
                store.show_popup(PopupType.CI_CHECK_RUN_RERUN, checks=runs, failed_only=False),
            ),
        )
        actions.append(rerun_all)
    state = store.state_for(repo)
    if state.current_pull_request:
        pr = Gtk.Button(label="View checks on GitHub")
        pr.connect("clicked", lambda *_: open_external(state.current_pull_request.html_url + "/checks"))
        actions.append(pr)
    box.append(actions)
    return box


def show_checks(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    runs = _runs_from_payload(store, payload)
    failed = failing_checks(runs)
    heading = payload.get("error") or (
        f"{len(failed)} check{'s' if len(failed) != 1 else ''} failed in your pull request"
        if failed
        else "Checks failed"
    )
    pr = payload.get("pull_request") if isinstance(payload.get("pull_request"), dict) else {}
    subtitle = pr.get("title") or payload.get("title") or ""
    if pr.get("number"):
        subtitle = f"{subtitle} #{pr['number']}".strip()
    dialog = Adw.Dialog()
    dialog.set_content_width(720)
    dialog.set_content_height(520)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Checks failed", subtitle=subtitle or heading))
    toolbar.add_top_bar(header)
    paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    paned.set_shrink_start_child(False)
    paned.set_shrink_end_child(False)
    left = Gtk.ScrolledWindow()
    left.set_min_content_width(240)
    right_holder = Gtk.ScrolledWindow()
    right_holder.set_hexpand(True)
    selected: dict[str, RefCheck | None] = {"run": (failed or runs or [None])[0]}

    def render_right() -> None:
        run = selected["run"]
        child = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        child.set_margin_top(8)
        child.set_margin_bottom(8)
        child.set_margin_start(8)
        child.set_margin_end(8)
        if run is None:
            child.append(Gtk.Label(label="Select a check to see job steps.", xalign=0))
        else:
            heading_row = Gtk.Label(label=run.name, xalign=0)
            heading_row.add_css_class("heading")
            child.append(heading_row)
            child.append(Gtk.Label(label=run.description or run.conclusion or run.status, xalign=0, wrap=True))
            actions = Gtk.Box(spacing=6)
            if run.html_url:
                view = Gtk.Button(label=_view_on_github_label(repo))
                view.connect("clicked", lambda *_ , u=run.html_url: open_external(u))
                actions.append(view)
            if repo:
                logs = Gtk.Button(label="View logs")
                logs.connect("clicked", lambda *_ , r=run: show_job_logs(parent, store, repo, r))
                actions.append(logs)
                rerun = Gtk.Button(label="Re-run job")
                rerun.connect("clicked", lambda *_ , r=run: store.show_popup(PopupType.CI_CHECK_RUN_RERUN, checks=[r], failed_only=False))
                actions.append(rerun)
            child.append(actions)
            if run.steps:
                steps_box = Gtk.ListBox()
                steps_box.add_css_class("boxed-list")
                for step in run.steps:
                    step_row = Adw.ActionRow(title=step.name or "step", subtitle=_step_subtitle(step))
                    if step.number:
                        link = Gtk.Button(icon_name="web-browser-symbolic")
                        link.add_css_class("flat")
                        link.connect("clicked", lambda *_ , rn=run, st=step: _open_step(rn, st, payload))
                        step_row.add_suffix(link)
                    steps_box.append(step_row)
                child.append(steps_box)
            else:
                child.append(Gtk.Label(label="No job steps loaded yet. Open this check on GitHub for logs.", xalign=0, wrap=True))
            for note in run.annotations or []:
                loc = f"{note.path}:{note.start_line}" if note.path else ""
                child.append(Adw.ActionRow(title=note.title or note.message[:80], subtitle=f"{note.annotation_level} · {loc}".strip(" ·")))
        right_holder.set_child(child)

    listbox = Gtk.ListBox()
    listbox.add_css_class("navigation-sidebar")
    shown = failed or runs
    if not shown:
        listbox.append(Adw.ActionRow(title=heading, subtitle="Open the pull request on GitHub to see details."))
    for run in shown[:40]:
        row = Adw.ActionRow(title=run.name or "check", subtitle=run.conclusion or run.status or "failed")
        row.set_activatable(True)
        row._run = run  # type: ignore[attr-defined]
        listbox.append(row)

    def on_row(_lb, row) -> None:
        if row is None:
            return
        selected["run"] = getattr(row, "_run", None)
        render_right()

    listbox.connect("row-activated", on_row)
    listbox.connect("row-selected", on_row)
    left.set_child(listbox)
    paned.set_start_child(left)
    paned.set_end_child(right_holder)
    render_right()
    buttons = Gtk.Box(spacing=8)
    if repo and failed:
        rerun = Gtk.Button(label="Re-run failed checks")
        rerun.add_css_class("suggested-action")

        def do_rerun(*_a: Any) -> None:
            store.show_popup(PopupType.CI_CHECK_RUN_RERUN, checks=runs, failed_only=True)
            dialog.close()

        rerun.connect("clicked", do_rerun)
        buttons.append(rerun)
    if payload.get("should_checkout") or pr:
        switch_label = (
            "Switch to repository and pull request"
            if payload.get("should_change_repository")
            else "Switch to pull request"
        )
        switch = Gtk.Button(label=switch_label)
        switch.add_css_class("suggested-action")
        switch.connect("clicked", lambda *_: (store.switch_to_pull_request(payload), dialog.close()))
        buttons.append(switch)
    html = payload.get("html_url") or payload.get("url") or (pr.get("html_url") if pr else "")
    if html:
        web = Gtk.Button(label="Open in browser")
        web.connect(
            "clicked",
            lambda *_: open_external(
                str(html) + ("/checks" if "/pull/" in str(html) and not str(html).endswith("/checks") else "")
            ),
        )
        buttons.append(web)
    question = Gtk.Label(
        label=(
            f"Do you want to switch to that pull request now and start fixing "
            f"{'them' if len(failed) != 1 else 'it'}?"
            if failed
            else heading
        ),
        wrap=True,
        xalign=0,
    )
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    box.append(Gtk.Label(label=heading, wrap=True, xalign=0))
    box.append(paned)
    box.append(question)
    box.append(buttons)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)
    if repo:
        store.load_check_steps(repo, on_done=lambda: (selected.__setitem__("run", selected["run"]), render_right()))


def show_rerun_checks(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    runs = _runs_from_payload(store, payload)
    failed_only = bool(payload.get("failed_only", True))
    if failed_only:
        considered = failing_checks(runs) or runs
    else:
        considered = runs
    noun = "check" if len(considered) == 1 else "checks"
    descriptor = "failed " if failed_only and len(considered) != 1 else ("single " if len(considered) == 1 else "")
    title = f"Re-run {descriptor}{noun}"
    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    dialog.set_content_height(420)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=title, subtitle="A new attempt will include dependent jobs"))
    toolbar.add_top_bar(header)
    holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    holder.set_margin_top(12)
    holder.set_margin_bottom(12)
    holder.set_margin_start(12)
    holder.set_margin_end(12)
    holder.append(Gtk.Label(label="Determining which checks can be re-run.", xalign=0))
    toolbar.set_content(holder)
    dialog.set_child(toolbar)
    dialog.present(parent)

    def render(rerunnable: list, skipped: list) -> None:
        child = holder.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            holder.remove(child)
            child = nxt
        if rerunnable:
            name = rerunnable[0].name if len(considered) == 1 else "these workflows"
            holder.append(
                Gtk.Label(
                    label=f"A new attempt of {name} will be started, including all of their dependents:",
                    wrap=True,
                    xalign=0,
                )
            )
            holder.append(_grouped_list(rerunnable))
        if skipped:
            plural = "checks" if len(skipped) != 1 else "check"
            verb = "are" if len(skipped) != 1 else "is"
            prefix = (
                f"There are no {'failed ' if failed_only else ''}checks that can be re-run"
                if not rerunnable
                else f"There {verb} {len(skipped)} {'failed ' if failed_only else ''}{plural} that cannot be re-run"
            )
            warn = Gtk.Label(
                label=(
                    f"{prefix}. A check run cannot be re-run if the check is more than one month old, "
                    "the check or its dependent has not completed, or the check is not configured to be re-run."
                ),
                wrap=True,
                xalign=0,
            )
            warn.add_css_class("warning")
            holder.append(warn)
        actions = Gtk.Box(spacing=8)
        confirm = Gtk.Button(label=f"Re-run {noun}")
        confirm.add_css_class("suggested-action")
        confirm.set_sensitive(bool(rerunnable))

        def do_rerun(*_a: Any) -> None:
            cb = payload.get("on_rerun")
            if cb:
                cb()
            elif repo:
                store.rerun_checks(repo, rerunnable, failed_only=failed_only)
            dialog.close()

        confirm.connect("clicked", do_rerun)
        actions.append(confirm)
        holder.append(actions)

    if not repo or not considered:
        render([], considered)
        return

    def on_suites(rerunnable: list, skipped: list) -> None:
        if not rerunnable and not skipped:
            render(considered, [])
        else:
            render(rerunnable, skipped)

    store.load_rerunnable_checks(repo, considered, failed_only=failed_only, on_done=on_suites)


def show_job_logs(parent: Gtk.Window | None, store: AppStore, repo, run: RefCheck) -> None:
    window = parent or Gtk.Window()
    dialog = Adw.Dialog()
    dialog.set_content_width(640)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title="Job logs", subtitle=run.name or "check"))
    toolbar.add_top_bar(header)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    label = Gtk.Label(label="Loading logs…", xalign=0, yalign=0)
    label.set_wrap(False)
    label.set_selectable(True)
    label.add_css_class("diff-view")
    label.set_ellipsize(Pango.EllipsizeMode.NONE)
    scroller.set_child(label)
    toolbar.set_content(scroller)
    dialog.set_child(toolbar)
    dialog.present(window)

    def done(text: str) -> None:
        if text:
            label.set_text(text)
        else:
            label.set_text("No logs are available for this job. They may have expired, or this check is not a GitHub Actions job.")
        if run.html_url:
            open_btn = Gtk.Button(label=_view_on_github_label(repo))
            open_btn.connect("clicked", lambda *_: open_external(run.html_url))
            header.pack_start(open_btn)

    cached = run.logs
    if cached:
        done(cached)
        return

    def receive(text: str) -> None:
        run.logs = text
        done(text)

    store.fetch_job_logs(repo, run.id, on_done=receive)
