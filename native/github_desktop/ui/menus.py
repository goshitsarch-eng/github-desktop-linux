"""Context menus and small GTK helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk


MenuItem = tuple[str, Callable[[], None], bool] | None

# Desktop `ui/lib/context-menu.ts` Linux labels.
CopyFilePathLabel = "Copy file path"
CopyRelativeFilePathLabel = "Copy relative file path"
CopySelectedPathsLabel = "Copy paths"
CopySelectedRelativePathsLabel = "Copy relative paths"
DefaultEditorLabel = "Open in external editor"
DefaultShellLabel = "Open in shell"
RevealInFileManagerLabel = "Show in your File Manager"
OpenWithDefaultProgramLabel = "Open with default program"


def open_in_editor_label(editor_name: str | None) -> str:
    return f"Open in {editor_name}" if editor_name else DefaultEditorLabel


def open_in_shell_label(shell_name: str | None) -> str:
    return f"Open in {shell_name}" if shell_name else DefaultShellLabel


def remove_repository_label(confirm: bool) -> str:
    return "Remove…" if confirm else "Remove"


def alias_verb(alias: str | None) -> str:
    return "Change" if alias else "Create"


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


def show_context_menu(anchor: Gtk.Widget, items: Sequence[MenuItem]) -> None:
    popover = Gtk.Popover()
    popover.set_has_arrow(False)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    box.add_css_class("context-menu")
    for item in items:
        if item is None:
            box.append(Gtk.Separator())
            continue
        label, callback, enabled = item
        btn = Gtk.Button(label=label)
        btn.add_css_class("flat")
        btn.add_css_class("context-menu-item")
        btn.set_halign(Gtk.Align.FILL)
        btn.set_sensitive(enabled)

        def _activate(_b: Gtk.Button, cb: Callable[[], None] = callback, pop: Gtk.Popover = popover) -> None:
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
