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

from ..fuzzy_find import filter_items
from ..git.ops import (
    determine_mergeability,
    get_ahead_behind_range,
    get_commits_between,
)
from ..git.progress import MultiCommitProgress
from ..models import (
    ComputedAction,
    DEFAULT_CONFLICTS_RESOLVED_MESSAGE,
    GitStatusEntry,
    ManualConflictResolution,
    MergeTreeResult,
    MultiCommitOperationKind,
    WorkingDirectoryFileChange,
    get_branch_for_resolution,
    get_label_for_manual_resolution_option,
    get_conflicted_files,
    get_resolved_file_status_summary,
    get_resolved_files,
    calculate_conflicts,
    is_conflict_with_markers,
    is_manual_conflict,
)
from ..shells import open_in_default_program
from ..store import AppStore
from ..truncate import truncate_with_ellipsis
from .branches import group_branches
from .menus import OpenWithDefaultProgramLabel, RevealInFileManagerLabel, clear_box
from .text_box import search_entry


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


def get_merge_options() -> tuple:
    """Desktop `getMergeOptions()` labels for the compare Merge CTA dropdown."""
    return MERGE_OPTIONS


def editor_button_string(editor_name: str | None) -> str:
    """Desktop `editorButtonString`."""
    return f"Open in {editor_name or 'editor'}"


def editor_button_tooltip(editor_name: str | None) -> str | None:
    """Desktop `editorButtonTooltip` (Linux)."""
    if editor_name:
        return None
    return "No editor configured in Options > Advanced"


def manual_conflict_status_copy(
    status,
    *,
    our_branch: str | None,
    their_branch: str | None,
) -> str:
    """Desktop unmerged-file `manualConflictString` / deleted-file copy."""
    us, them = getattr(status, "us", None), getattr(status, "them", None)
    if us != GitStatusEntry.DELETED and them != GitStatusEntry.DELETED:
        return "Manual conflict"
    target_branch = "target branch"
    if us == GitStatusEntry.DELETED and our_branch:
        target_branch = our_branch
    if them == GitStatusEntry.DELETED and their_branch:
        target_branch = their_branch
    return f"File does not exist on {target_branch}."


def merge_cta_message(
    kind: MultiCommitOperationKind | str,
    current: str,
    compare: str,
    commit_count: int,
    action: ComputedAction | None,
    conflicted_files: int = 0,
) -> tuple[str, bool]:
    """Copy from Desktop `merge-call-to-action-with-conflicts.tsx`.

    Returns ``(message, can_proceed)``. Loading uses
    ``Checking for ability to merge automatically…`` (or squash/rebase).
    Invalid merge: ``Unable to merge unrelated histories in this repository``.
    Conflicts: ``There will be N conflicted file(s) when merging …``.
    """
    if isinstance(kind, MultiCommitOperationKind):
        op = kind.value.lower()
        is_rebase = kind == MultiCommitOperationKind.REBASE
    else:
        op = str(kind).lower()
        is_rebase = op == "rebase"
    if action is None or action == ComputedAction.LOADING:
        return f"Checking for ability to {op} automatically…", False
    if action == ComputedAction.INVALID:
        if is_rebase:
            return "Unable to start rebase. Check you have chosen a valid branch.", False
        return "Unable to merge unrelated histories in this repository", False
    if commit_count <= 0:
        return "", False
    if is_rebase:
        if action != ComputedAction.CLEAN:
            return "", False
        noun = "commit" if commit_count == 1 else "commits"
        return (
            f"This will update {current} by applying its {commit_count} {noun} on top of {compare}",
            True,
        )
    if action == ComputedAction.CONFLICTS:
        noun = "file" if conflicted_files == 1 else "files"
        return (
            f"There will be {conflicted_files} conflicted {noun} when merging {compare} into {current}",
            True,
        )
    noun = "commit" if commit_count == 1 else "commits"
    return (
        f"This will merge {commit_count} {noun} from {compare} into {current}",
        True,
    )


def merge_cta_can_proceed(
    kind: MultiCommitOperationKind | str,
    commit_count: int,
    merge_tree: MergeTreeResult | None,
) -> bool:
    """Desktop `isUpdateBranchDisabled` inverted: rebase needs Clean; merge blocks Invalid."""
    if commit_count <= 0:
        return False
    if isinstance(kind, str):
        is_rebase = kind.lower() == "rebase"
    else:
        is_rebase = kind == MultiCommitOperationKind.REBASE
    if merge_tree is None:
        return False
    if is_rebase:
        return merge_tree.kind == ComputedAction.CLEAN
    return merge_tree.kind != ComputedAction.INVALID


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
    """Desktop `truncateWithEllipsis` for choose-branch titles."""
    return truncate_with_ellipsis(name, limit)


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
    search = search_entry()
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
        remaining = filter_items(search.get_text(), branches, lambda b: [b.name, b.upstream or ""])
        return group_branches(
            remaining,
            current=None,
            default_name=default_name,
            recent_names=recent_names,
        )

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
            def after_warn(should_warn: bool) -> None:
                if should_warn:

                    def proceed() -> None:
                        begin_operation(k, name, count)

                    show_warn_force_push(parent, store, {"operation": "Rebase", "on_begin": proceed})
                    return
                begin_operation(k, name, count)

            store.warn_if_remote_commits(repo, current_branch, branch.tip_sha, after_warn)
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
    search = search_entry()
    search.set_placeholder_text("Filter branches")
    box.append(search)
    name_row = Adw.EntryRow(title="New branch name")
    name_row.set_visible(bool(payload.get("create_branch")))
    box.append(name_row)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    scroller.set_child(listbox)
    box.append(scroller)
    if payload.get("create_branch"):
        search.set_visible(False)
        scroller.set_visible(False)
    hint = Gtk.Label(wrap=True, xalign=0)
    box.append(hint)
    start_btn = Gtk.Button(label=f"Cherry-pick {count} {noun}")
    start_btn.add_css_class("suggested-action")
    start_btn.set_sensitive(False)
    box.append(start_btn)
    toolbar.set_content(box)
    dialog.set_child(toolbar)
    selected = {"branch": None, "create": bool(payload.get("create_branch"))}

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
        selected["create"] = shown == 0 and bool(needle) or bool(payload.get("create_branch"))
        if payload.get("create_branch"):
            start_btn.set_label("Cherry-pick to new branch")
            start_btn.set_sensitive(bool(name_row.get_text().strip()))
            start_btn.set_tooltip_text("")
            hint.set_text("A new branch will be created from HEAD, then the commits will be cherry-picked onto it.")
        elif selected["create"]:
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

    def run_cherry(target: str | None, *, new_branch: str | None = None) -> None:
        progress = show_operation_progress(parent, MultiCommitOperationKind.CHERRY_PICK, commit_count=count)

        def finished(*_exc: object) -> None:
            def close() -> None:
                try:
                    progress.close()
                except Exception:
                    pass

            _on_main(close)

        if new_branch:
            store.cherry_pick_to_new_branch(repo, shas, new_branch, on_done=finished, on_progress=progress.update)
            return
        store.cherry_pick_commits(repo, shas, target, on_done=finished, on_progress=progress.update)

    def start(*_a: object) -> None:
        if selected["create"]:
            name = name_row.get_text().strip() if payload.get("create_branch") else search.get_text().strip()
            if not name:
                return
            dialog.close()
            run_cherry(None, new_branch=name)
            return
        branch = selected["branch"]
        if not branch:
            return
        dialog.close()
        run_cherry(branch.name)

    search.connect("search-changed", lambda *_: render())
    name_row.connect("changed", lambda *_: render())
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
        elif status.squash_msg_found:
            kind = MultiCommitOperationKind.SQUASH
        else:
            kind = MultiCommitOperationKind.MERGE
    dialog = Adw.Dialog()
    dialog.set_content_width(520)
    dialog.set_content_height(480)
    toolbar = Adw.ToolbarView()
    header = Adw.HeaderBar()
    header.set_title_widget(Adw.WindowTitle(title=f"Resolve {kind.lower()} conflicts", subtitle=status.current_branch or "this branch"))
    toolbar.add_top_bar(header)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    box.set_margin_top(12)
    box.set_margin_bottom(12)
    box.set_margin_start(12)
    box.set_margin_end(12)
    count_label = Gtk.Label(wrap=True, xalign=0)
    box.append(count_label)
    scroller = Gtk.ScrolledWindow(vexpand=True)
    listbox = Gtk.ListBox()
    listbox.add_css_class("boxed-list")
    scroller.set_child(listbox)
    box.append(scroller)
    actions = Gtk.Box(spacing=8)
    cont = Gtk.Button(label=_continue_label(kind))
    cont.add_css_class("suggested-action")
    abort = Gtk.Button(label=_abort_label(kind))
    editor = Gtk.Button(label="Open in editor")
    shell = Gtk.Button(label="Open in command line")
    current = {"files": []}

    def _editor_name() -> str | None:
        if store.settings.use_custom_editor:
            path = (store.settings.custom_editor_path or "").strip()
            return Path(path).name if path else None
        return store.settings.selected_external_editor

    def refresh(_emit: object = None) -> bool:
        """Rebuild `renderUnmergedFile` rows from the current conflict map."""
        view = store.state_for(repo)
        current_status = view.status
        if current_status is None:
            return False
        files = get_conflicted_files(current_status.working_directory, view.manual_resolutions)
        resolved = get_resolved_files(current_status.working_directory, view.manual_resolutions)
        leftover_count = sum(
            (item.status.conflict_marker_count or 0)
            for item in current_status.working_directory.files
            if is_conflict_with_markers(item.status)
            and item.path not in {file.path for file in files}
        )
        current["files"] = files
        count = len(files)
        count_label.remove_css_class("warning")
        count_label.remove_css_class("success")
        if count:
            noun = "file" if count == 1 else "files"
            count_label.set_text(f"{count} conflicted {noun}")
        elif leftover_count:
            count_label.set_text("Leftover conflict markers remain. Resolve them before continuing.")
            count_label.add_css_class("warning")
        else:
            count_label.set_text("All conflicts have been resolved. You can continue.")
            count_label.add_css_class("success")
        our = current_status.current_branch or "this branch"
        their = _their_branch(repo, current_status)
        editor_name = _editor_name()
        clear_box(listbox)
        for file in files:
            listbox.append(
                _conflict_row(
                    parent,
                    store,
                    repo,
                    file,
                    binary=is_manual_conflict(file.status),
                    ours_label=get_label_for_manual_resolution_option(file.status.us, our),
                    theirs_label=get_label_for_manual_resolution_option(file.status.them, their),
                    our_branch=our,
                    their_branch=their,
                    editor_name=editor_name,
                )
            )
        for file in resolved:
            resolution = view.manual_resolutions.get(file.path)
            branch = get_branch_for_resolution(resolution, our, their)
            summary = get_resolved_file_status_summary(file.status, resolution, branch)
            row = Adw.ActionRow(title=file.path, subtitle=summary)
            ok = Gtk.Image.new_from_icon_name("emblem-ok-symbolic")
            row.add_prefix(ok)
            if summary != DEFAULT_CONFLICTS_RESOLVED_MESSAGE:
                # Desktop `renderResolvedFile` / `makeUndoManualResolutionClickHandler`
                undo = Gtk.Button(label="Undo")
                undo.add_css_class("flat")
                undo.connect(
                    "clicked",
                    lambda _b, path=file.path: store.update_manual_conflict_resolution(repo, path, None),
                )
                row.add_suffix(undo)
            listbox.append(row)
        can_continue = count == 0 and leftover_count == 0
        cont.set_sensitive(can_continue)
        if leftover_count and count == 0:
            cont.set_tooltip_text("Resolve leftover conflict markers before continuing")
        elif count:
            cont.set_tooltip_text("Resolve all changes before continuing")
        else:
            cont.set_tooltip_text("")
        return False

    def on_store() -> None:
        GLib.idle_add(refresh)

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

        current_state = store.state_for(repo)
        resolved_now = get_resolved_files(
            current_state.status.working_directory if current_state.status else [],
            current_state.manual_resolutions,
        )
        if current_state.user_has_resolved_conflicts or resolved_now:
            show_confirm_abort(parent, kind, confirm)
        else:
            confirm()

    def open_editor(*_a: object) -> None:
        files = current["files"]
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
    unsubscribe = store.subscribe(on_store)

    def on_closed(*_a: object) -> None:
        unsubscribe()
        current_state = store.state_for(repo)
        if not current_state.status:
            return
        resolved_now = get_resolved_files(current_state.status.working_directory, current_state.manual_resolutions)
        if resolved_now:
            store.set_conflicts_resolved(repo)

    dialog.connect("closed", on_closed)
    refresh()
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
    our_branch: str | None = None,
    their_branch: str | None = None,
    editor_name: str | None = None,
) -> Adw.ActionRow:
    """Desktop `renderUnmergedFile` / `getManualResolutionMenuItems` actions."""
    if is_manual_conflict(file.status) or binary:
        subtitle = manual_conflict_status_copy(
            file.status, our_branch=our_branch, their_branch=their_branch
        )
    elif is_conflict_with_markers(file.status):
        human = calculate_conflicts(file.status.conflict_marker_count or 0)
        subtitle = "1 conflict" if human == 1 else f"{human} conflicts"
    else:
        subtitle = file.status.kind.value
    row = Adw.ActionRow(title=file.path, subtitle=subtitle)
    ours = Gtk.Button(label=ours_label)
    theirs = Gtk.Button(label=theirs_label)
    ours.add_css_class("flat")
    theirs.add_css_class("flat")
    ours.connect(
        "clicked",
        lambda *_: store.update_manual_conflict_resolution(repo, file.path, ManualConflictResolution.OURS),
    )
    theirs.connect(
        "clicked",
        lambda *_: store.update_manual_conflict_resolution(repo, file.path, ManualConflictResolution.THEIRS),
    )
    open_label = editor_button_string(editor_name)
    open_btn = Gtk.Button(label=open_label)
    open_btn.add_css_class("flat")
    open_btn.set_tooltip_text(editor_button_tooltip(editor_name) or open_label)
    open_btn.set_sensitive(editor_name is not None)
    open_btn.connect("clicked", lambda *_: store.open_in_editor(repo, file.path))
    reveal = Gtk.Button(icon_name="folder-symbolic")
    reveal.add_css_class("flat")
    reveal.set_tooltip_text(RevealInFileManagerLabel)
    reveal.connect("clicked", lambda *_: store.reveal_in_file_manager(repo, file.path))
    default_app = Gtk.Button(icon_name="application-x-executable-symbolic")
    default_app.add_css_class("flat")
    default_app.set_tooltip_text(OpenWithDefaultProgramLabel)
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
