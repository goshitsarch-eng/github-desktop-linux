"""Context menus and small GTK helpers."""

from __future__ import annotations

import os
from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk

from ..models import AppFileStatusKind


MenuCallback = Callable[[], None]
MenuItem = tuple[str, MenuCallback | Sequence["MenuItem"], bool] | None

# Desktop `ui/lib/context-menu.ts` Linux labels.
CopyFilePathLabel = "Copy file path"
CopyRelativeFilePathLabel = "Copy relative file path"
CopySelectedPathsLabel = "Copy paths"
CopySelectedRelativePathsLabel = "Copy relative paths"
DefaultEditorLabel = "Open in external editor"
DefaultShellLabel = "Open in shell"
RevealInFileManagerLabel = "Show in your File Manager"
OpenWithDefaultProgramLabel = "Open with default program"
TrashNameLabel = "Trash"
FileDoesNotExistOnDiskLabel = "File does not exist on disk"
GitIgnoreFileName = ".gitignore"  # Desktop Darwin: Ignore File (Add to .gitignore)


def ignore_folder_labels(path: str) -> list[str]:
    """Desktop ignore-folder submenu labels (`/a`, `/a/b`), deepest first."""
    components = path.split("/")[:-1]
    return ["/" + "/".join(components[: len(components) - index]) for index in range(len(components))]


def ignore_extension_globs(paths: Sequence[str], *, limit: int = 5) -> list[str]:
    """Desktop: up to five unique extensions from the selection."""
    # Five menu items should be enough for everyone
    seen: list[str] = []
    for path in paths:
        extension = os.path.splitext(path)[1]
        if extension and extension not in seen:
            seen.append(extension)
        if len(seen) >= limit:
            break
    return seen


def discard_changes_item_label(paths: Sequence[str], *, confirm: bool) -> str:
    """Desktop `getDiscardChangesMenuItemLabel` (Linux)."""
    if len(paths) == 1:
        base = "Discard changes"
    else:
        base = f"Discard {len(paths)} selected changes"
    return f"{base}…" if confirm else base


def changes_list_context_menu_blocked(*, committing: bool, rebasing: bool) -> bool:
    """Desktop Changes `onContextMenu` / `onItemContextMenu` `isCommitting` + `rebaseConflictState`."""
    return committing or rebasing


def add_remove_co_authors_label(*, showing: bool) -> str:
    """Linux `getAddRemoveCoAuthorsMenuItem` / `toggleCoAuthorsText`."""
    return "Remove co-authors" if showing else "Add co-authors"


def open_git_settings_label() -> str:
    """Linux `CommitMessageAvatar` `buttonText` (`Open git settings`)."""
    return "Open git settings"


def git_config_settings_name() -> str:
    """Linux `CommitMessageAvatar` `settingsName` (`options`, Darwin `settings`)."""
    return "options"


def git_config_popover_copy(*, local: bool) -> str:
    """Linux `CommitMessageAvatar.renderGitConfigPopover` body."""
    if local:
        return (
            "You can update your local git configuration for your repository in your repository settings."
        )
    return "You can update your global git configuration  in your git options."


YOUR_ACCOUNT_EMAILS = "Your Account Emails"
UPDATE_EMAIL_LABEL = "Update email"


GENERATE_COMMIT_MESSAGE_WITH_COPILOT = "Generate commit message with Copilot"


def commit_spellcheck_menu_label(*, enabled: bool) -> str:
    """Linux `getCommitSpellcheckEnabilityMenuItem`."""
    return "Disable commit spellcheck" if enabled else "Enable commit spellcheck"


def generate_commit_message_menu_item_enabled(
    *,
    is_committing: bool,
    is_generating: bool,
    commit_to_amend: bool,
    files_selected: bool,
) -> bool:
    """Desktop `getGenerateCommitMessageMenuItem` `.enabled`."""
    no_files_selected = not files_selected
    no_changes_available = (not commit_to_amend) and no_files_selected
    return (not is_committing) and (not is_generating) and (not no_changes_available)


def generate_commit_message_menu_item(
    *,
    accounts_can_generate: bool,
    is_committing: bool,
    is_generating: bool,
    commit_to_amend: bool,
    files_selected: bool,
) -> tuple[str, bool] | None:
    """Desktop `getGenerateCommitMessageMenuItem`. ``None`` when Copilot is unavailable."""
    if not accounts_can_generate:
        return None
    return (
        GENERATE_COMMIT_MESSAGE_WITH_COPILOT,
        generate_commit_message_menu_item_enabled(
            is_committing=is_committing,
            is_generating=is_generating,
            commit_to_amend=commit_to_amend,
            files_selected=files_selected,
        ),
    )


def commit_message_shared_menu_specs(
    *,
    showing_co_authors: bool,
    github_repository: bool,
    is_committing: bool,
    accounts_can_generate: bool,
    is_generating: bool,
    commit_to_amend: bool,
    files_selected: bool,
) -> list[tuple[str, bool]]:
    """Desktop `onContextMenu` items before `{ role: 'editMenu' }`."""
    items: list[tuple[str, bool]] = [
        (
            add_remove_co_authors_label(showing=showing_co_authors),
            bool(github_repository) and not is_committing,
        )
    ]
    generate = generate_commit_message_menu_item(
        accounts_can_generate=accounts_can_generate,
        is_committing=is_committing,
        is_generating=is_generating,
        commit_to_amend=commit_to_amend,
        files_selected=files_selected,
    )
    if generate is not None:
        items.append(generate)
    return items


def copy_tags_menu_label(tags: Sequence[str]) -> str:
    """Linux `windowTagsLabel` (`Copy tag` vs `Copy tags`)."""
    return "Copy tags" if len(tags) > 1 else "Copy tag"


def unpushed_tags_for_commit(tags: Sequence[str], tags_to_push: Sequence[str]) -> list[str]:
    """Desktop `getUnpushedTags`."""
    pending = set(tags_to_push)
    return [name for name in tags if name in pending]


def delete_tags_menu_item(
    tags: Sequence[str],
    unpushed: Sequence[str],
    on_delete: Callable[[str], None],
) -> MenuItem:
    """Desktop `getDeleteTagsMenuItem`. ``None`` when the commit has no tags."""
    if not tags:
        return None
    unpushed_set = set(unpushed)
    if len(tags) == 1:
        name = tags[0]
        return (f"Delete tag {name}", lambda: on_delete(name), name in unpushed_set)
    return (
        "Delete tag…",
        [(name, lambda n=name: on_delete(n), name in unpushed_set) for name in tags],
        True,
    )


def rebase_changed_file_menu_labels(
    kind: AppFileStatusKind,
    *,
    confirm_discard: bool,
    editor_label: str,
) -> list[str]:
    """Desktop `getRebaseContextMenu` labels (Linux)."""
    labels: list[str] = []
    if kind is AppFileStatusKind.UNTRACKED:
        labels.append(discard_changes_item_label(["untracked"], confirm=confirm_discard))
    labels.extend(
        [
            CopyFilePathLabel,
            CopyRelativeFilePathLabel,
            RevealInFileManagerLabel,
            editor_label,
            OpenWithDefaultProgramLabel,
        ]
    )
    return labels


def open_in_editor_label(editor_name: str | None) -> str:
    return f"Open in {editor_name}" if editor_name else DefaultEditorLabel


def is_external_editor_available(*, use_custom_editor: bool, selected_external_editor: str | None) -> bool:
    """Desktop `isExternalEditorAvailable`: `useCustomEditor || selectedExternalEditor !== null`."""
    return bool(use_custom_editor or selected_external_editor)


isExternalEditorAvailable = is_external_editor_available

OPEN_THE_REPOSITORY_IN_YOUR_EXTERNAL_EDITOR = "Open the repository in your external editor"
SELECT_YOUR_EDITOR_IN_OPTIONS = "Select your editor in Options"


def open_in_shell_label(shell_name: str | None) -> str:
    return f"Open in {shell_name}" if shell_name else DefaultShellLabel


def remove_repository_label(confirm: bool) -> str:
    return "Remove…" if confirm else "Remove"


def alias_verb(alias: str | None) -> str:
    return "Change" if alias else "Create"


def is_safe_file_extension(extension: str) -> bool:
    """Desktop `isSafeFileExtension`. Linux allows every extension (Windows rejects `.cmd`/`.exe`/`.bat`/`.sh`)."""
    return True


def view_on_github_label(*, enterprise: bool) -> str:
    return "View on GitHub Enterprise" if enterprise else "View on GitHub"


def new_repository_button_menu_items(
    *,
    on_clone: Callable[[], None],
    on_create: Callable[[], None],
    on_add: Callable[[], None],
) -> list[MenuItem]:
    """Desktop `onNewRepositoryButtonClick` (Linux labels)."""
    return [
        ("Clone repository…", on_clone, True),
        ("Create new repository…", on_create, True),
        ("Add existing repository…", on_add, True),
    ]


# Desktop Linux `no-repositories-view` (Darwin uses Local Drive).
CREATE_NEW_REPOSITORY_ON_LOCAL_DRIVE = "Create a New Repository on your local drive…"
ADD_EXISTING_REPOSITORY_FROM_LOCAL_DRIVE = "Add an Existing Repository from your local drive…"
CLONE_REPOSITORY_FROM_INTERNET = "Clone a repository from the Internet…"
REPOSITORY_TOOLBAR_DESCRIPTION = "Current repository"


def repository_toolbar_title(
    *,
    selected_name: str | None = None,
    has_repositories: bool = False,
    cloning_name: str | None = None,
    cloning_percent: int | None = None,
) -> str:
    """Desktop Linux `renderRepositoryToolbarButton` title."""
    if cloning_name:
        if cloning_percent:
            return f"Cloning {cloning_name}… {cloning_percent}%"
        return f"Cloning {cloning_name}…"
    if selected_name:
        return selected_name
    if has_repositories:
        return "Select a repository"
    return "No repositories"


renderRepositoryToolbarButton = repository_toolbar_title


def generate_repository_list_context_menu_specs(
    *,
    alias: str | None,
    missing: bool,
    github: bool,
    shell_label: str,
    editor_label: str,
    confirm_remove: bool,
    is_repository: bool = True,
) -> list[tuple[str, bool]]:
    """Desktop `generateRepositoryListContextMenu` / `buildAliasMenuItems` (Linux: Create alias)."""
    items: list[tuple[str, bool]] = []
    if is_repository:
        items.append((f"{alias_verb(alias)} alias", True))
        if alias:
            items.append(("Remove alias", True))
    items.extend(
        [
            ("Copy repo name", True),
            ("Copy repo path", True),
            ("View on GitHub", bool(github)),
            (shell_label, not missing),
            (RevealInFileManagerLabel, not missing),
            (editor_label, not missing),
            (remove_repository_label(confirm_remove), True),
        ]
    )
    return items


def committed_file_context_items(
    *,
    full_path: str,
    relative_path: str,
    exists: bool,
    editor_label: str,
    on_reveal: Callable[[], None],
    on_open_editor: Callable[[], None],
    on_open_default: Callable[[], None],
    view_github_label: str,
    on_view_github: Callable[[], None],
    view_github_enabled: bool,
) -> list[MenuItem]:
    """History and Start PR file context menus (`selected-commits` / `pull-request-files-changed`)."""
    if not exists:
        return [(FileDoesNotExistOnDiskLabel, lambda: None, False)]
    extension = os.path.splitext(relative_path)[1]
    return [
        (RevealInFileManagerLabel, on_reveal, True),
        (editor_label, on_open_editor, True),
        (OpenWithDefaultProgramLabel, on_open_default, is_safe_file_extension(extension)),
        None,
        (CopyFilePathLabel, lambda: copy_text(full_path), True),
        (CopyRelativeFilePathLabel, lambda: copy_text(os.path.normpath(relative_path)), True),
        None,
        (view_github_label, on_view_github, view_github_enabled),
    ]


def clear_box(box: Gtk.Widget) -> None:
    child = box.get_first_child()
    while child is not None:
        nxt = child.get_next_sibling()
        box.remove(child)
        child = nxt


def copy_text(text: str) -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def widget_is_or_inside(widget, ancestor) -> bool:
    """True when ``widget`` is ``ancestor`` or a descendant of it."""
    if widget is None or ancestor is None:
        return False
    current = widget
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        if current is ancestor:
            return True
        seen.add(id(current))
        getter = getattr(current, "get_parent", None)
        current = getter() if callable(getter) else None
    return False


def _edit_undo_redo(widget, *, redo: bool) -> None:
    """Undo/redo the focused text field. Never undoes a Git commit (Desktop Edit → Undo)."""
    current = widget
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, Gtk.TextView):
            buf = current.get_buffer()
            try:
                buf.set_enable_undo(True)
            except Exception:
                pass
            try:
                if redo:
                    if buf.get_can_redo():
                        buf.redo()
                elif buf.get_can_undo():
                    buf.undo()
            except Exception:
                pass
            return
        delegate = getattr(current, "get_delegate", None)
        inner = delegate() if callable(delegate) else None
        if inner is not None and inner is not current and hasattr(inner, "undo"):
            current = inner
            continue
        if hasattr(current, "undo") and hasattr(current, "get_can_undo"):
            try:
                if redo:
                    if current.get_can_redo():
                        current.redo()
                elif current.get_can_undo():
                    current.undo()
            except Exception:
                pass
            return
        current = current.get_parent() if hasattr(current, "get_parent") else None


def apply_edit_menu_action(widget, action: str, *, clipboard=None) -> bool:
    """Apply `{ role: 'editMenu' }` to a GTK text widget. Returns True if handled."""
    if widget is None:
        return False
    if clipboard is None:
        getter = getattr(widget, "get_clipboard", None)
        clipboard = getter() if callable(getter) else None
    if action in {"undo", "redo"}:
        _edit_undo_redo(widget, redo=action == "redo")
        return True
    if isinstance(widget, Gtk.Editable):
        if action == "cut":
            widget.cut_clipboard()
        elif action == "copy":
            widget.copy_clipboard()
        elif action == "paste":
            widget.paste_clipboard()
        elif action == "select-all":
            widget.select_region(0, -1)
        return True
    if isinstance(widget, Gtk.TextView):
        buf = widget.get_buffer()
        bounds = buf.get_selection_bounds()
        if isinstance(bounds, tuple) and len(bounds) == 3:
            has_sel, start, end = bounds
        elif isinstance(bounds, tuple) and len(bounds) == 2:
            has_sel, start, end = True, bounds[0], bounds[1]
        else:
            has_sel, start, end = False, None, None
        if action == "copy" and has_sel and clipboard is not None:
            clipboard.set(buf.get_text(start, end, True))
        elif action == "cut" and has_sel and clipboard is not None:
            clipboard.set(buf.get_text(start, end, True))
            buf.delete(start, end)
        elif action == "paste" and clipboard is not None:
            def _paste(_c, result) -> None:
                try:
                    text = clipboard.read_text_finish(result)
                except Exception:
                    return
                if text:
                    buf.insert_at_cursor(text)

            clipboard.read_text_async(None, _paste)
        elif action == "select-all":
            buf.select_range(buf.get_start_iter(), buf.get_end_iter())
        return True
    return False


def edit_menu_items(widget) -> list[MenuItem]:
    """Desktop `{ role: 'editMenu' }` (Undo/Redo/Cut/Copy/Paste/Select All)."""
    return [
        ("Undo", lambda: apply_edit_menu_action(widget, "undo"), True),
        ("Redo", lambda: apply_edit_menu_action(widget, "redo"), True),
        ("Cut", lambda: apply_edit_menu_action(widget, "cut"), True),
        ("Copy", lambda: apply_edit_menu_action(widget, "copy"), True),
        ("Paste", lambda: apply_edit_menu_action(widget, "paste"), True),
        ("Select All", lambda: apply_edit_menu_action(widget, "select-all"), True),
    ]


def show_context_menu(anchor: Gtk.Widget, items: Sequence[MenuItem]) -> None:
    popover = Gtk.Popover()
    popover.set_has_arrow(False)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("context-menu")
    for item in items:
        if item is None:
            box.append(Gtk.Separator())
            continue
        label, action, enabled = item
        if not callable(action):
            expander = Gtk.Expander(label=label)
            expander.set_sensitive(enabled)
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            for sub in action:
                if sub is None:
                    inner.append(Gtk.Separator())
                    continue
                sub_label, sub_cb, sub_enabled = sub
                if not callable(sub_cb):
                    continue
                sub_btn = Gtk.Button(label=sub_label)
                sub_btn.add_css_class("flat")
                sub_btn.add_css_class("context-menu-item")
                sub_btn.set_halign(Gtk.Align.FILL)
                sub_btn.set_sensitive(sub_enabled)

                def _sub_activate(
                    _b: Gtk.Button,
                    cb: Callable[[], None] = sub_cb,
                    pop: Gtk.Popover = popover,
                ) -> None:
                    pop.popdown()
                    cb()

                sub_btn.connect("clicked", _sub_activate)
                inner.append(sub_btn)
            expander.set_child(inner)
            box.append(expander)
            continue
        btn = Gtk.Button(label=label)
        btn.add_css_class("flat")
        btn.add_css_class("context-menu-item")
        btn.set_halign(Gtk.Align.FILL)
        btn.set_sensitive(enabled)

        def _activate(_b: Gtk.Button, cb: Callable[[], None] = action, pop: Gtk.Popover = popover) -> None:
            pop.popdown()
            cb()

        btn.connect("clicked", _activate)
        box.append(btn)
    popover.set_child(box)
    popover.set_parent(anchor)
    popover.popup()


def attach_right_click(widget: Gtk.Widget, handler: Callable[[Gtk.Widget], None]) -> None:
    gesture = Gtk.GestureClick()
    gesture.set_button(3)
    gesture.connect("pressed", lambda *_a: handler(widget))
    widget.add_controller(gesture)


# Desktop `ui/resizable/resizable.tsx`
resizableComponentClass = "resizable-component"
DefaultMinWidth = 200
DefaultMaxWidth = 350
KEYBOARD_RESIZE_DELTA = 5
IncreaseActiveResizableWidth = "increase-active-resizable-width"
DecreaseActiveResizableWidth = "decrease-active-resizable-width"


def resizable_limit(value: float, fallback: int) -> int:
    """Coerce a live `IConstrainedValue` min/max into a finite pixel bound."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    if number != number or abs(number) == float("inf") or abs(number) > 1e8:
        return fallback
    return int(number)


def nudge_resizable_width(width: int, increase: bool, min_width: int, max_width: int) -> int:
    """Desktop `handleMenuResizeEvent` width math (`±5px`, then clamp)."""
    if max_width < min_width:
        max_width = min_width
    delta = KEYBOARD_RESIZE_DELTA if increase else -KEYBOARD_RESIZE_DELTA
    changed = int(width) + delta
    return min(max_width, max(min_width, changed))


def resize_percentage(width: int, min_width: int, max_width: int) -> int:
    """Desktop `getResizePercentage` for the aria-live resize announcement."""
    span = max_width - min_width
    if span <= 0:
        return 100 if width >= max_width else 0
    return round(((width - min_width) / span) * 100)


def find_active_resizable(widget: Gtk.Widget | None) -> Gtk.Widget | None:
    """Walk from `document.activeElement` to the focused `.resizable-component`."""
    current = widget
    while current is not None:
        try:
            if current.has_css_class(resizableComponentClass):
                return current
        except Exception:
            pass
        current = current.get_parent() if hasattr(current, "get_parent") else None
    return None


def handle_menu_resize_event(widget: Gtk.Widget, increase: bool) -> None:
    """Desktop `handleMenuResizeEvent` on the focused Resizable."""
    handler = getattr(widget, "_handle_menu_resize", None)
    if callable(handler):
        handler(increase)


def resize_active_resizable(focus: Gtk.Widget | None, increase: bool) -> bool:
    """Desktop `resizeActiveResizable`: custom event from `document.activeElement`."""
    target = find_active_resizable(focus)
    if target is None:
        return False
    handle_menu_resize_event(target, increase)
    return True


def attach_keyboard_resize(
    widget: Gtk.Widget,
    *,
    get_width: Callable[[], int],
    on_resize: Callable[[int], None],
    description: str,
    get_min: Callable[[], int] | None = None,
    get_max: Callable[[], int] | None = None,
    min_width: int = DefaultMinWidth,
    max_width: int = DefaultMaxWidth,
    constraints: dict[str, float] | None = None,
) -> None:
    """Listen for Expand/Contract active resizable on this `.resizable-component`."""
    widget.add_css_class(resizableComponentClass)

    def _min() -> int:
        if constraints is not None:
            return resizable_limit(constraints.get("min", min_width), min_width)
        if get_min is not None:
            return int(get_min())
        return int(min_width)

    def _max() -> int:
        fallback = int(max_width)
        if constraints is not None:
            bound = resizable_limit(constraints.get("max", fallback), fallback)
        elif get_max is not None:
            bound = int(get_max())
        else:
            bound = fallback
        minimum = _min()
        return minimum if bound < minimum else bound

    def handle_menu_resize(increase: bool) -> None:
        # Desktop `handleMenuResizeEvent` / `updateResizeMessage`
        new_width = nudge_resizable_width(int(get_width()), increase, _min(), _max())
        on_resize(new_width)
        direction = "increased" if increase else "decreased"
        # Desktop AriaLiveContainer: "{description} width increased. Set to N%"
        message = f"{description} width {direction}. Set to {resize_percentage(new_width, _min(), _max())}%"
        widget._resize_message = message
        try:
            widget.announce(message, Gtk.AccessibleAnnouncementPriority.MEDIUM)
        except Exception:
            pass

    widget._handle_menu_resize = handle_menu_resize


def attach_paned_keyboard_resize(
    paned: Gtk.Paned,
    *,
    description: str,
    get_min: Callable[[], int],
    get_max: Callable[[], int],
) -> None:
    """Mark the paned's start child as the Desktop Resizable (not the diff pane)."""
    start = paned.get_start_child()
    if start is None:
        return
    attach_keyboard_resize(
        start,
        get_width=lambda: int(paned.get_position()),
        on_resize=lambda width: paned.set_position(int(width)),
        get_min=get_min,
        get_max=get_max,
        description=description,
    )


def attach_paned_reset(paned: Gtk.Paned, on_reset: Callable[[], None], *, handle_slop: float = 12.0) -> None:
    """Desktop Resizable `onDoubleClick` / `onReset` for a Gtk.Paned handle."""
    click = Gtk.GestureClick()
    click.set_button(1)

    def pressed(_gesture, n_press: int, x: float, _y: float) -> None:
        if n_press != 2:
            return
        if abs(x - paned.get_position()) > handle_slop:
            return
        on_reset()

    click.connect("pressed", pressed)
    paned.add_controller(click)


def wrap_toolbar_resizable(
    widget: Gtk.Widget,
    on_resize: Callable[[int], None],
    on_reset: Callable[[], None],
    *,
    width: int,
    min_width: int = 160,
    max_width: int = 720,
    description: str = "",
    constraints: dict[str, float] | None = None,
) -> Gtk.Box:
    """Desktop `Resizable` for toolbar branch / push-pull buttons (`enableResizingToolbarButtons`)."""
    box = Gtk.Box()
    box.add_css_class("toolbar-resizable")
    box.set_hexpand(False)
    limits = constraints if constraints is not None else {"min": float(min_width), "max": float(max_width)}
    limits.setdefault("min", float(min_width))
    limits.setdefault("max", float(max_width))
    width = max(int(limits["min"]), int(width))
    widget.set_size_request(width, -1)
    widget.set_hexpand(True)
    handle = Gtk.Box()
    handle.add_css_class("resize-handle")
    handle.set_size_request(6, -1)
    if description:
        handle.set_tooltip_text(description)
    try:
        handle.set_cursor_from_name("col-resize")
    except Exception:
        pass
    box.append(widget)
    box.append(handle)
    drag = Gtk.GestureDrag()
    drag.set_button(1)
    start = {"width": width}

    def begin(_gesture, _x: float, _y: float) -> None:
        min_w = int(limits["min"])
        start["width"] = max(min_w, widget.get_allocated_width() or widget.get_width() or start["width"])

    def update(_gesture, dx: float, _dy: float) -> None:
        min_w = int(limits["min"])
        max_w = int(limits["max"])
        new = max(min_w, min(max_w, int(start["width"] + dx)))
        widget.set_size_request(new, -1)
        on_resize(new)

    drag.connect("drag-begin", begin)
    drag.connect("drag-update", update)
    handle.add_controller(drag)

    click = Gtk.GestureClick()
    click.set_button(1)

    def pressed(_gesture, n_press: int, _x: float, _y: float) -> None:
        if n_press == 2:
            on_reset()

    click.connect("pressed", pressed)
    handle.add_controller(click)

    def toolbar_width() -> int:
        min_w = int(limits["min"])
        return max(min_w, widget.get_allocated_width() or widget.get_width() or start["width"])

    def toolbar_resize(new_width: int) -> None:
        widget.set_size_request(new_width, -1)
        on_resize(new_width)

    attach_keyboard_resize(
        box,
        get_width=toolbar_width,
        on_resize=toolbar_resize,
        constraints=limits,
        description=description or "Toolbar button",
        min_width=int(limits["min"]),
        max_width=int(limits["max"]) if limits["max"] < 1e8 else DefaultMaxWidth,
    )
    return box
