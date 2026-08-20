"""Desktop-parity multi-commit operation wizard: merge, squash, rebase, cherry-pick, conflicts."""

from __future__ import annotations

import os
import re
from pathlib import Path
from threading import Thread
from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from ..git.ops import (
    determine_mergeability,
    get_ahead_behind_range,
    get_binary_paths,
    get_commits_between,
    get_files_with_conflict_markers,
    warn_about_remote_commits,
)
from ..git.progress import MultiCommitProgress
from ..models import (
    ComputedAction,
    ManualConflictResolution,
    MultiCommitOperationKind,
    WorkingDirectoryFileChange,
    get_label_for_manual_resolution_option,
    has_unresolved_conflicts,
    is_conflict_with_markers,
    is_manual_conflict,
)
from ..shells import open_in_default_program
from ..store import AppStore


MERGE_OPTIONS = (
    (
        MultiCommitOperationKind.MERGE,
        "Create a merge commit",
        "The commits from the selected branch will be added to the current branch via a merge commit.",
    ),
    (
        MultiCommitOperationKind.SQUASH,
        "Squash and merge",
        "The commits in the selected branch will be combined into one commit in the current branch.",
    ),
    (
        MultiCommitOperationKind.REBASE,
        "Rebase",
        "The commits from the selected branch will be rebased and added to the current branch.",
    ),
)


def can_start_operation(
    selected_name: str | None,
    current_name: str | None,
    commit_count: int | None,
    status_kind: ComputedAction | None,
) -> bool:
    if not selected_name or selected_name == current_name:
        return False
    if status_kind == ComputedAction.LOADING:
        return False
    if status_kind == ComputedAction.CONFLICTS:
        return True
    if commit_count is None or commit_count == 0:
        return False
    return status_kind != ComputedAction.INVALID


def _truncate(name: str, limit: int = 40) -> str:
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _on_main(fn: Callable[[], None]) -> None:
    def run() -> bool:
        fn()
        return False

    try:
        if GLib.main_context_default().is_owner():
            fn()
            return
    except Exception:
        pass
    GLib.idle_add(run)


def show_multi_commit(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    if payload.get("step") == "conflicts":
        show_conflicts_dialog(parent, store, str(payload.get("kind") or ""))
        return
    kind = str(payload.get("kind") or MultiCommitOperationKind.MERGE)
    if kind == MultiCommitOperationKind.REORDER:
        from .dialogs import show_reorder_commits

        show_reorder_commits(parent, store, payload.get("to_move") or payload.get("commits") or [])
        return
    if kind == MultiCommitOperationKind.CHERRY_PICK:
        _show_cherry_pick_target(parent, store, payload)
        return
    _show_choose_branch(parent, store, kind, payload.get("initial_branch"))


def _show_choose_branch(parent: Gtk.Window, store: AppStore, kind: str, initial_name: str | None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else None
    default_name = store.default_branch_name(repo)
    branches = [b for b in state.branches if b.name != current]
    recent_names = list(state.recent_branches or store.settings.recent_branches.get(repo.path, []))
    current_branch = next((b for b in state.branches if b.name == current), None)

    dialog = Adw.Dialog()
    dialog.set_content_width(480)
    dialog.set_content_height(560)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    title = Adw.WindowTitle(title=_choose_title(kind, current or "current branch"))
    header.set_title_widget(title)
    toolbar.add_top_bar(header)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(8)
    box.set_margin_bottom(8)
    box.set_margin_start(12)
    box.set_margin_end(12)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Filter branches")
    box.append(search)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    scroller.set_min_content_height(220)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    scroller.set_child(listbox)
    box.append(scroller)

    preview = Gtk.Label(wrap=True, xalign=0)
    preview.add_css_class("merge-info")
    preview.set_text("Select a branch to see whether this can merge automatically.")
    box.append(preview)

    op_drop = Gtk.DropDown.new_from_strings([label for _kind, label, _hint in MERGE_OPTIONS])
    try:
        op_drop.set_selected(next(i for i, (k, _, _) in enumerate(MERGE_OPTIONS) if k == kind))
    except StopIteration:
        op_drop.set_selected(0)
    box.append(op_drop)
    op_hint = Gtk.Label(wrap=True, xalign=0)
    op_hint.add_css_class("dim-label")
    box.append(op_hint)

    start_btn = Gtk.Button(label=_start_label(kind, current))
    start_btn.add_css_class("suggested-action")
    start_btn.set_sensitive(False)
    start_btn.set_tooltip_text("")
    box.append(start_btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    selected: dict[str, Any] = {"branch": None, "commit_count": None, "status": None, "token": 0, "ahead": 0}

    def current_kind() -> str:
        idx = op_drop.get_selected()
        if 0 <= idx < len(MERGE_OPTIONS):
            return MERGE_OPTIONS[idx][0]
        return kind

    def grouped() -> list:
        needle = search.get_text().strip().lower()
        remaining = [b for b in branches if not needle or needle in b.name.lower()]
        groups: list[tuple[str, list]] = []
        recent = [b for b in remaining if b.name in recent_names]
        if recent:
            groups.append(("Recent", recent))
            remaining = [b for b in remaining if b not in recent]
        default_b = next((b for b in remaining if b.name == default_name or b.name.endswith("/" + (default_name or ""))), None)
        if default_b:
            groups.append(("Default", [default_b]))
            remaining = [b for b in remaining if b is not default_b]
        if remaining:
            groups.append(("Other", remaining))
        return groups

    def render_list() -> None:
        while True:
            row = listbox.get_first_child()
            if row is None:
                break
            listbox.remove(row)
        shown = 0
        for group_name, items in grouped():
            header_row = Adw.ActionRow(title=group_name)
            header_row.set_sensitive(False)
            listbox.append(header_row)
            for branch in items:
                row = Adw.ActionRow(title=branch.name, subtitle=(branch.upstream or branch.tip_sha[:7]))
                row.set_activatable(True)
                row._branch = branch  # type: ignore[attr-defined]
                listbox.append(row)
                shown += 1
                if shown >= 200:
                    return
        if shown == 0:
            listbox.append(Adw.ActionRow(title="No matching branches"))

    def update_op_hint() -> None:
        k = current_kind()
        for option, _label, hint in MERGE_OPTIONS:
            if option == k:
                op_hint.set_text(hint)
                return
        op_hint.set_text("")

    def update_start() -> None:
        k = current_kind()
        start_btn.set_label(_start_label(k, current))
        title.set_title(_choose_title(k, current or "current branch"))
        update_op_hint()
        ok = can_start_operation(
            getattr(selected["branch"], "name", None),
            current,
            selected["commit_count"],
            selected["status"],
        )
        start_btn.set_sensitive(ok)
        if selected["branch"] and getattr(selected["branch"], "name", None) == current:
            if k == MultiCommitOperationKind.REBASE:
                start_btn.set_tooltip_text("You are not able to rebase this branch onto itself.")
            else:
                start_btn.set_tooltip_text("You are not able to merge this branch into itself.")
        elif not ok and selected["status"] == ComputedAction.INVALID:
            if k == MultiCommitOperationKind.REBASE:
                start_btn.set_tooltip_text("Unable to start rebase. Check you have chosen a valid branch.")
            else:
                start_btn.set_tooltip_text("Unable to merge unrelated histories in this repository")
        elif not ok and (selected["commit_count"] or 0) == 0:
            start_btn.set_tooltip_text("The current branch is already up to date with the selected branch.")
        else:
            start_btn.set_tooltip_text("")

    def apply_preview() -> None:
        branch = selected["branch"]
        k = current_kind()
        if branch is None or branch.name == current:
            preview.set_text("Select a branch to see whether this can merge automatically.")
            selected["commit_count"] = None
            selected["status"] = None
            update_start()
            return
        selected["status"] = ComputedAction.LOADING
        selected["commit_count"] = 0
        if k == MultiCommitOperationKind.REBASE:
            preview.set_text("Checking for ability to rebase automatically…")
        else:
            preview.set_text("Checking for ability to merge automatically...")
        update_start()
        token = selected["token"] + 1
        selected["token"] = token
        ours = next((b.tip_sha for b in state.branches if b.name == current), None) or (
            state.status.current_tip if state.status else None
        )
        theirs = branch.tip_sha

        def work() -> tuple:
            if k == MultiCommitOperationKind.REBASE:
                behind = get_commits_between(repo.path, ours or "HEAD", theirs) if ours else []
                ahead = get_commits_between(repo.path, theirs, ours or "HEAD") if ours else []
                if behind is None:
                    return k, ComputedAction.INVALID, 0, 0, 0
                return k, ComputedAction.CLEAN, len(behind), len(ahead or []), 0
            merge_status = determine_mergeability(repo.path, ours or "HEAD", theirs)
            ab = get_ahead_behind_range(repo.path, f"...{branch.name}")
            count = ab.behind if ab else 0
            return k, merge_status.kind, count, 0, merge_status.conflicted_files

        def thread() -> None:
            try:
                result = work()
            except Exception:
                if k == MultiCommitOperationKind.REBASE:
                    result = (k, ComputedAction.INVALID, 0, 0, 0)
                else:
                    result = (k, ComputedAction.CLEAN, 0, 0, 0)

            def apply() -> bool:
                if selected["token"] != token or selected["branch"] is None or selected["branch"].name != branch.name:
                    return False
                op, status, behind_or_count, ahead, conflicted = result
                if current_kind() != op:
                    return False
                selected["status"] = status
                selected["ahead"] = ahead
                selected["commit_count"] = behind_or_count
                if op == MultiCommitOperationKind.REBASE:
                    preview.set_text(
                        _rebase_preview_text(current or "", branch.name, ahead, behind_or_count, status)
                    )
                else:
                    preview.set_text(
                        _merge_preview_text(
                            current or "",
                            branch.name,
                            behind_or_count,
                            status,
                            conflicted,
                        )
                    )
                update_start()
                return False

            if GLib.main_context_default().is_owner():
                apply()
            else:
                GLib.idle_add(apply)

        Thread(target=thread, daemon=True).start()

    def on_row(_lb, row) -> None:
        if row is None:
            return
        branch = getattr(row, "_branch", None)
        if branch is None:
            return
        selected["branch"] = branch
        apply_preview()

    def on_op(*_a: object) -> None:
        apply_preview()

    def begin_operation(k: str, name: str, commit_count: int) -> None:
        dialog.close()
        progress = show_operation_progress(parent, k, commit_count=commit_count or None)
        store.remember_branch(repo, name)

        def finished(*_exc: object) -> None:
            def close() -> None:
                try:
                    progress.close()
                except Exception:
                    pass

            _on_main(close)

        if k == MultiCommitOperationKind.REBASE:
            store.rebase_branch(repo, name, on_done=finished, on_progress=progress.update)
        else:
            store.merge_branch(repo, name, squash=(k == MultiCommitOperationKind.SQUASH), on_done=finished)

    def start(*_a: object) -> None:
        branch = selected["branch"]
        if branch is None or not start_btn.get_sensitive():
            return
        k = current_kind()
        name = branch.name
        count = int(selected["commit_count"] or 0)
        if k == MultiCommitOperationKind.REBASE and current_branch and (
            store.settings.confirm_force_push or store.settings.ask_for_confirmation_on_force_push
        ):
            if warn_about_remote_commits(repo.path, current_branch, branch.tip_sha):

                def proceed() -> None:
                    begin_operation(k, name, count)

                show_warn_force_push(parent, store, {"operation": "Rebase", "on_begin": proceed})
                return
        begin_operation(k, name, count)

    search.connect("search-changed", lambda *_: render_list())
    listbox.connect("row-activated", on_row)
    listbox.connect("row-selected", on_row)
    op_drop.connect("notify::selected", on_op)
    start_btn.connect("clicked", start)
    render_list()
    update_op_hint()
    initial = None
    if initial_name:
        initial = next((b for b in branches if b.name == initial_name), None)
    if initial is None and default_name and default_name != current:
        initial = next((b for b in branches if b.name == default_name), None)
    if initial is None and recent_names:
        initial = next((b for b in branches if b.name == recent_names[0]), None)
    if initial is not None:
        selected["branch"] = initial
        apply_preview()
    dialog.present(parent)


def _choose_title(kind: str, current: str) -> str:
    name = _truncate(current)
    if kind == MultiCommitOperationKind.SQUASH:
        return f"Squash and merge into {name}"
    if kind == MultiCommitOperationKind.REBASE:
        return f"Rebase {name}"
    return f"Merge into {name}"


def _start_label(kind: str, current: str | None) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Rebase"
    if kind == MultiCommitOperationKind.SQUASH:
        return "Squash and merge"
    if current:
        return f"Merge into {current}"
    return "Merge"


def _merge_preview_text(
    current: str,
    other: str,
    commit_count: int,
    status: ComputedAction,
    conflicted: int,
) -> str:
    if status == ComputedAction.LOADING:
        return "Checking for ability to merge automatically..."
    if status == ComputedAction.INVALID:
        return "Unable to merge unrelated histories in this repository"
    if status == ComputedAction.CONFLICTS:
        noun = "file" if conflicted == 1 else "files"
        return f"There will be {conflicted} conflicted {noun} when merging {other} into {current}"
    if commit_count == 0:
        return f"{current} is already up to date with {other}"
    noun = "commit" if commit_count == 1 else "commits"
    return f"This will merge {commit_count} {noun} from {other} into {current}"


def _rebase_preview_text(
    current: str,
    base: str,
    ahead: int,
    behind: int,
    status: ComputedAction,
) -> str:
    if status == ComputedAction.LOADING:
        return "Checking for ability to rebase automatically…"
    if status == ComputedAction.INVALID:
        return "Unable to start rebase. Check you have chosen a valid branch."
    if behind > 0 and ahead <= 0:
        noun = "commit" if behind == 1 else "commits"
        return f"This will fast-forward {current} by {behind} {noun} to match {base}"
    if behind > 0 and ahead > 0:
        noun = "commit" if ahead == 1 else "commits"
        return f"This will update {current} by applying its {ahead} {noun} on top of {base}"
    return f"{current} is already up to date with {base}"


def _show_cherry_pick_target(parent: Gtk.Window, store: AppStore, payload: dict[str, Any]) -> None:
    repo = store.selected_repository
    if not repo:
        return
    shas = list(payload.get("shas") or [])
    count = len(shas) or 1
    state = store.state_for(repo)
    current = state.status.current_branch if state.status else None
    branches = [b for b in state.branches if b.name != current]
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    dialog.set_content_height(520)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    noun = "commits" if count != 1 else "commit"
    header.set_title_widget(Adw.WindowTitle(title=f"Cherry-pick {count} {noun} to a branch"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(8)
    box.set_margin_bottom(8)
    box.set_margin_start(12)
    box.set_margin_end(12)
    search = Gtk.SearchEntry()
    search.set_placeholder_text("Filter branches")
    box.append(search)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    scroller.set_child(listbox)
    box.append(scroller)
    hint = Gtk.Label(wrap=True, xalign=0)
    box.append(hint)
    start_btn = Gtk.Button(label=f"Cherry-pick {count} {noun}")
    start_btn.add_css_class("suggested-action")
    start_btn.set_sensitive(False)
    box.append(start_btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    selected = {"branch": None, "create": False}

    def render() -> None:
        while True:
            row = listbox.get_first_child()
            if row is None:
                break
            listbox.remove(row)
        needle = search.get_text().strip().lower()
        shown = 0
        for branch in branches:
            if needle and needle not in branch.name.lower():
                continue
            row = Adw.ActionRow(title=branch.name)
            row.set_activatable(True)
            row._branch = branch  # type: ignore[attr-defined]
            listbox.append(row)
            shown += 1
        selected["create"] = shown == 0 and bool(needle)
        if selected["create"]:
            listbox.append(Adw.ActionRow(title=f"Create branch “{search.get_text().strip()}”"))
            start_btn.set_label("Cherry-pick to new branch")
            start_btn.set_sensitive(True)
            start_btn.set_tooltip_text("")
            hint.set_text("No matching branches. A new branch will be created from HEAD.")
        elif shown == 0:
            start_btn.set_sensitive(False)
            hint.set_text("Sign in or fetch to see more branches.")
        else:
            hint.set_text("")
            start_btn.set_label(f"Cherry-pick {count} {noun}")

    def on_row(_lb, row) -> None:
        branch = getattr(row, "_branch", None) if row is not None else None
        selected["branch"] = branch
        if branch is None:
            return
        if branch.name == current:
            start_btn.set_sensitive(False)
            start_btn.set_tooltip_text("You are not able to cherry-pick from and to the same branch")
            return
        start_btn.set_sensitive(True)
        start_btn.set_tooltip_text("")
        start_btn.set_label(f"Cherry-pick {count} {noun} to {branch.name}…")

    def run_cherry(target: str | None) -> None:
        progress = show_operation_progress(parent, MultiCommitOperationKind.CHERRY_PICK, commit_count=count)

        def finished(*_exc: object) -> None:
            def close() -> None:
                try:
                    progress.close()
                except Exception:
                    pass

            _on_main(close)

        store.cherry_pick_commits(repo, shas, target, on_done=finished, on_progress=progress.update)

    def start(*_a: object) -> None:
        if selected["create"]:
            name = search.get_text().strip()
            if not name:
                return
            dialog.close()
            store.create_branch_and_checkout(repo, name)
            run_cherry(None)
            return
        branch = selected["branch"]
        if not branch:
            return
        dialog.close()
        run_cherry(branch.name)

    search.connect("search-changed", lambda *_: render())
    listbox.connect("row-activated", on_row)
    listbox.connect("row-selected", on_row)
    start_btn.connect("clicked", start)
    render()
    dialog.present(parent)


class OperationProgress:
    """Desktop ProgressDialog: `Commit n of m` plus the current commit summary."""

    def __init__(self, dialog: Adw.Dialog, bar: Gtk.ProgressBar, detail: Gtk.Label) -> None:
        self.dialog = dialog
        self._bar = bar
        self._detail = detail
        self._closed = False

    def update(self, event: MultiCommitProgress | object) -> None:
        position = int(getattr(event, "position", 0) or 0)
        total = int(getattr(event, "total", 0) or 0)
        value = float(getattr(event, "value", 0) or 0)
        summary = str(getattr(event, "current_commit_summary", "") or "")

        def apply() -> bool:
            if self._closed:
                return False
            if total > 0:
                self._bar.set_visible(True)
                self._bar.set_fraction(max(0.0, min(1.0, value)))
                text = f"Commit {position} of {total}"
                if summary:
                    text += f"\n{summary}"
                self._detail.set_text(text)
            return False

        GLib.idle_add(apply)

    def close(self) -> None:
        self._closed = True
        try:
            self.dialog.close()
        except Exception:
            pass


def show_operation_progress(
    parent: Gtk.Window,
    kind: str,
    *,
    commit_count: int | None = None,
    summary: str | None = None,
) -> OperationProgress:
    dialog = Adw.Dialog()
    dialog.set_content_width(400)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_show_end_title_buttons(False)
    header.set_title_widget(Adw.WindowTitle(title=f"{kind} in progress"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(24)
    box.set_margin_bottom(24)
    box.set_margin_start(24)
    box.set_margin_end(24)
    spinner = Gtk.Spinner()
    spinner.start()
    spinner.set_halign(Gtk.Align.CENTER)
    box.append(spinner)
    bar = Gtk.ProgressBar()
    bar.set_show_text(False)
    if commit_count and commit_count > 0:
        bar.set_fraction(0.0)
        bar.set_visible(True)
    else:
        bar.set_visible(False)
    box.append(bar)
    detail = Gtk.Label(wrap=True, xalign=0.5)
    if commit_count and commit_count > 0:
        noun = "commit" if commit_count == 1 else "commits"
        detail.set_text(f"Commit 1 of {commit_count}" + (f"\n{summary}" if summary else f"\nApplying {commit_count} {noun}"))
    else:
        detail.set_text("Working…")
    box.append(detail)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)
    return OperationProgress(dialog, bar, detail)


def show_warn_force_push(parent: Gtk.Window, store: AppStore, payload: dict[str, Any] | None = None) -> None:
    payload = payload or {}
    operation = str(payload.get("operation") or "Rebase")
    dialog = Adw.Dialog()
    dialog.set_content_width(460)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=f"{operation} will require force push"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_margin_top(18)
    box.set_margin_bottom(18)
    box.set_margin_start(18)
    box.set_margin_end(18)
    box.append(
        Gtk.Label(
            label=f"Are you sure you want to {operation.lower()}?",
            wrap=True,
            xalign=0,
        )
    )
    box.append(
        Gtk.Label(
            label=(
                f"At the end of the {operation.lower()} flow, GitHub Desktop will enable you to force "
                "push the branch to update the upstream branch. Force pushing will alter the history "
                "on the remote and potentially cause problems for others collaborating on this branch."
            ),
            wrap=True,
            xalign=0,
        )
    )
    skip = Gtk.CheckButton(label="Do not show this message again")
    box.append(skip)
    actions = Gtk.Box(spacing=8)
    actions.set_halign(Gtk.Align.END)
    cancel = Gtk.Button(label="Cancel")
    begin = Gtk.Button(label=operation)
    begin.add_css_class("suggested-action")
    actions.append(cancel)
    actions.append(begin)
    box.append(actions)
    toolbar.set_content(box)
    dialog.set_child(toolbar)

    def close(*_a: object) -> None:
        dialog.close()

    def confirm(*_a: object) -> None:
        if skip.get_active():
            store.settings.confirm_force_push = False
            store.settings.ask_for_confirmation_on_force_push = False
            store.persist_settings()
        dialog.close()
        on_begin = payload.get("on_begin")
        if callable(on_begin):
            on_begin()

    cancel.connect("clicked", close)
    begin.connect("clicked", confirm)
    dialog.present(parent)


def show_confirm_abort(
    parent: Gtk.Window,
    operation: str,
    on_confirm: Callable[[], None],
    on_cancel: Callable[[], None] | None = None,
) -> None:
    dialog = Adw.AlertDialog(
        heading=f"Confirm abort {operation.lower()}",
        body=(
            f"Are you sure you want to abort this {operation.lower()}?\n\n"
            "This will take you back to the original branch state and the conflicts "
            "you have already resolved will be discarded."
        ),
    )
    dialog.add_response("cancel", "Cancel")
    dialog.add_response("abort", f"Abort {operation.lower()}")
    dialog.set_response_appearance("abort", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")

    def done(_d, response: str) -> None:
        if response == "abort":
            on_confirm()
        elif on_cancel:
            on_cancel()

    dialog.connect("response", done)
    dialog.present(parent)


def show_conflicts_dialog(parent: Gtk.Window, store: AppStore, kind: str | None = None) -> None:
    repo = store.selected_repository
    if not repo:
        return
    state = store.state_for(repo)
    status = state.status
    if not status:
        return
    if not kind:
        if status.merge_head_found:
            kind = MultiCommitOperationKind.MERGE
        elif status.rebase_internal_state:
            kind = MultiCommitOperationKind.REBASE
        elif status.is_cherry_picking_head_found:
            kind = MultiCommitOperationKind.CHERRY_PICK
        else:
            kind = MultiCommitOperationKind.MERGE
    files = [f for f in status.working_directory.files if f.status.is_conflicted and has_unresolved_conflicts(f.status)]
    resolved = [f for f in status.working_directory.files if f.status.is_conflicted and not has_unresolved_conflicts(f.status)]
    leftover = {}
    try:
        leftover = get_files_with_conflict_markers(repo.path)
    except Exception:
        leftover = {}
    leftover_count = sum(leftover.values())
    ref = "HEAD"
    if status.merge_head_found:
        ref = "MERGE_HEAD"
    elif status.rebase_internal_state:
        ref = "REBASE_HEAD"
    try:
        binary_paths = set(get_binary_paths(repo.path, ref, [f.path for f in files]))
    except Exception:
        binary_paths = set()
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    our = status.current_branch or "this branch"
    their = _their_branch(repo, status)
    header.set_title_widget(Adw.WindowTitle(title=f"Resolve {kind.lower()} conflicts", subtitle=our))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    count = len(files)
    if count:
        noun = "file" if count == 1 else "files"
        box.append(Gtk.Label(label=f"{count} conflicted {noun}", xalign=0))
    elif leftover_count:
        leftover_label = Gtk.Label(
            label="Leftover conflict markers remain. Resolve them before continuing.",
            wrap=True,
            xalign=0,
        )
        leftover_label.add_css_class("warning")
        box.append(leftover_label)
    else:
        success = Gtk.Label(label="All conflicts have been resolved. You can continue.", xalign=0)
        success.add_css_class("success")
        box.append(success)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    for file in files:
        row = _conflict_row(
            parent,
            store,
            repo,
            file,
            binary=file.path in binary_paths,
            ours_label=get_label_for_manual_resolution_option(file.status.us, our),
            theirs_label=get_label_for_manual_resolution_option(file.status.them, their),
        )
        listbox.append(row)
    for file in resolved:
        row = Adw.ActionRow(title=file.path, subtitle="Resolved")
        ok = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
        row.add_prefix(ok)
        listbox.append(row)
    scroller.set_child(listbox)
    box.append(scroller)
    actions = Gtk.Box(spacing=8)
    cont = Gtk.Button(label=_continue_label(kind))
    cont.add_css_class("suggested-action")
    can_continue = count == 0 and leftover_count == 0
    cont.set_sensitive(can_continue)
    if leftover_count and count == 0:
        cont.set_tooltip_text("Resolve leftover conflict markers before continuing")
    elif count:
        cont.set_tooltip_text("Resolve all changes before continuing")
    abort = Gtk.Button(label=_abort_label(kind))
    editor = Gtk.Button(label="Open in editor")
    shell = Gtk.Button(label="Open in command line")

    def do_continue(*_a: object) -> None:
        dialog.close()
        progress = None
        if kind in (MultiCommitOperationKind.REBASE, MultiCommitOperationKind.CHERRY_PICK):
            progress = show_operation_progress(parent, kind)

        def finished(*_exc: object) -> None:
            if progress is None:
                return

            def close() -> None:
                try:
                    progress.close()
                except Exception:
                    pass

            _on_main(close)

        store.continue_conflict_operation(
            repo,
            MultiCommitOperationKind(kind),
            on_done=finished,
            on_progress=progress.update if progress is not None else None,
        )

    def do_abort(*_a: object) -> None:
        def confirm() -> None:
            dialog.close()
            store.abort_conflict_operation(repo, MultiCommitOperationKind(kind))

        show_confirm_abort(parent, kind, confirm)

    def open_editor(*_a: object) -> None:
        path = files[0].path if files else None
        store.open_in_editor(repo, path)

    cont.connect("clicked", do_continue)
    abort.connect("clicked", do_abort)
    editor.connect("clicked", open_editor)
    shell.connect("clicked", lambda *_: store.open_in_shell(repo))
    actions.append(cont)
    actions.append(abort)
    actions.append(editor)
    actions.append(shell)
    box.append(actions)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    dialog.present(parent)


def _their_branch(repo, status) -> str:
    if status.rebase_internal_state:
        return status.rebase_internal_state.target_branch
    merge_msg = os.path.join(repo.path, ".git", "MERGE_MSG")
    try:
        first = Path(merge_msg).read_text(encoding="utf-8").splitlines()[0]
    except OSError:
        return "theirs"
    match = re.search(r"Merge (?:remote-tracking )?branch '([^']+)'", first)
    if match:
        return match.group(1).split("/")[-1]
    return "theirs"


def _conflict_row(
    parent: Gtk.Window,
    store: AppStore,
    repo,
    file: WorkingDirectoryFileChange,
    binary: bool = False,
    ours_label: str = "Use ours",
    theirs_label: str = "Use theirs",
) -> Adw.ActionRow:
    if binary:
        subtitle = "Binary file"
    elif is_manual_conflict(file.status):
        subtitle = file.status.unmerged_action.value if file.status.unmerged_action else "Manual conflict"
    elif is_conflict_with_markers(file.status):
        count = file.status.conflict_marker_count or 0
        subtitle = f"{count} leftover conflict marker{'s' if count != 1 else ''}"
    else:
        subtitle = file.status.kind.value
    row = Adw.ActionRow(title=file.path, subtitle=subtitle)
    ours = Gtk.Button(label=ours_label)
    theirs = Gtk.Button(label=theirs_label)
    ours.add_css_class("flat")
    theirs.add_css_class("flat")
    ours.connect("clicked", lambda *_: store.resolve_conflict(repo, file.path, ManualConflictResolution.OURS))
    theirs.connect("clicked", lambda *_: store.resolve_conflict(repo, file.path, ManualConflictResolution.THEIRS))
    open_btn = Gtk.Button(label="Open in editor")
    open_btn.add_css_class("flat")
    open_btn.set_tooltip_text("Open in editor")
    open_btn.connect("clicked", lambda *_: store.open_in_editor(repo, file.path))
    reveal = Gtk.Button(icon_name="folder-symbolic")
    reveal.add_css_class("flat")
    reveal.set_tooltip_text("Show in file manager")
    reveal.connect("clicked", lambda *_: store.reveal_in_file_manager(repo, file.path))
    default_app = Gtk.Button(icon_name="application-x-executable-symbolic")
    default_app.add_css_class("flat")
    default_app.set_tooltip_text("Open with default program")
    default_app.connect(
        "clicked",
        lambda *_: open_in_default_program(os.path.join(repo.path, file.path)),
    )
    if is_conflict_with_markers(file.status) and not binary:
        open_btn.add_css_class("suggested-action")
        row.add_suffix(open_btn)
        row.add_suffix(ours)
        row.add_suffix(theirs)
    else:
        row.add_suffix(ours)
        row.add_suffix(theirs)
        row.add_suffix(open_btn)
    row.add_suffix(reveal)
    row.add_suffix(default_app)
    return row


def _continue_label(kind: str) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Continue rebase"
    if kind == MultiCommitOperationKind.CHERRY_PICK:
        return "Continue cherry-pick"
    return "Commit merge"


def _abort_label(kind: str) -> str:
    if kind == MultiCommitOperationKind.REBASE:
        return "Abort rebase"
    if kind == MultiCommitOperationKind.CHERRY_PICK:
        return "Abort cherry-pick"
    return "Abort merge"
