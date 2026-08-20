"""Context menus and small GTK helpers."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, Gtk


MenuItem = tuple[str, Callable[[], None], bool] | None


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
