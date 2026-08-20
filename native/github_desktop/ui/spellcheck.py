"""Apply spellcheck to commit message widgets when the platform supports it.

Tries libspelling, then Gspell, then python-enchant underlines. Missing
backends are a silent no-op so the app still runs without those packages.
"""

from __future__ import annotations

from typing import Any

from gi.repository import Gtk, Pango


class SpellController:
    def __init__(self) -> None:
        self._enabled = True
        self._setters: list[Any] = []

    def add(self, setter) -> None:
        self._setters.append(setter)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        for setter in self._setters:
            try:
                setter(self._enabled)
            except Exception:
                pass


def attach_spellcheck(*widgets: Gtk.Widget | None, enabled: bool = True) -> SpellController:
    controller = SpellController()
    for widget in widgets:
        if widget is None:
            continue
        attached = (
            _try_spelling(widget, controller)
            or _try_gspell(widget, controller)
            or _try_enchant(widget, controller)
        )
        if not attached:
            continue
    controller.set_enabled(enabled)
    return controller


def _try_spelling(widget: Gtk.Widget, controller: SpellController) -> bool:
    try:
        import gi

        gi.require_version("Spelling", "1")
        from gi.repository import Spelling
    except Exception:
        return False
    buffer = _text_buffer(widget)
    if buffer is None:
        return False
    try:
        checker = Spelling.Checker.get_default()
        adapter = Spelling.TextBufferAdapter.new(buffer, checker)
        extra = adapter.get_menu_model()
        if isinstance(widget, Gtk.TextView) and extra is not None:
            widget.set_extra_menu(extra)
        controller.add(adapter.set_enabled)
        return True
    except Exception:
        return False


def _try_gspell(widget: Gtk.Widget, controller: SpellController) -> bool:
    try:
        import gi

        gi.require_version("Gspell", "1")
        from gi.repository import Gspell
    except Exception:
        return False
    try:
        if isinstance(widget, Gtk.TextView):
            view = Gspell.TextView.get_from_gtk_text_view(widget)
            view.basic_setup()
            controller.add(view.set_inline_checker_enabled)
            return True
        if isinstance(widget, Gtk.Entry):
            entry = Gspell.Entry.get_from_gtk_entry(widget)
            entry.basic_setup()
            controller.add(entry.set_inline_spell_checking)
            return True
    except Exception:
        return False
    return False


def _try_enchant(widget: Gtk.Widget, controller: SpellController) -> bool:
    buffer = _text_buffer(widget)
    if buffer is None:
        return False
    try:
        import enchant
    except Exception:
        return False
    try:
        dictionary = enchant.Dict("en_US")
    except Exception:
        try:
            dictionary = enchant.Dict()
        except Exception:
            return False
    tag = buffer.create_tag("desktop-misspelled", underline=Pango.Underline.ERROR)
    state = {"enabled": True}

    def recheck(*_args: object) -> None:
        bounds = buffer.get_bounds()
        buffer.remove_tag(tag, *bounds)
        if not state["enabled"]:
            return
        start, end = bounds
        text = buffer.get_text(start, end, True)
        import re

        for match in re.finditer(r"[A-Za-z][A-Za-z']+", text):
            word = match.group(0)
            if dictionary.check(word):
                continue
            s = buffer.get_iter_at_offset(match.start())
            e = buffer.get_iter_at_offset(match.end())
            buffer.apply_tag(tag, s, e)

    handler = buffer.connect("changed", recheck)

    def set_enabled(enabled: bool) -> None:
        state["enabled"] = enabled
        recheck()

    controller.add(set_enabled)
    _ = handler
    return True


def _text_buffer(widget: Gtk.Widget):
    get_buffer = getattr(widget, "get_buffer", None)
    if not callable(get_buffer):
        return None
    buffer = get_buffer()
    if isinstance(buffer, Gtk.TextBuffer):
        return buffer
    return None
