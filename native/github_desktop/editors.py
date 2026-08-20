"""Detect installed GUI editors on Linux (parity with Desktop's lookup)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class Editor:
    name: str
    executable: str
    args: tuple[str, ...] = ()


KNOWN_EDITORS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("Visual Studio Code", ("code", "code-oss", "codium", "code-insiders"), ("--wait",)),
    ("VSCodium", ("codium",), ("--wait",)),
    ("Cursor", ("cursor",), ("--wait",)),
    ("Sublime Text", ("subl", "sublime_text"), ("-w",)),
    ("Atom", ("atom",), ("-w",)),
    ("GNOME Text Editor", ("gnome-text-editor",), ()),
    ("Gedit", ("gedit",), ()),
    ("Kate", ("kate",), ()),
    ("KWrite", ("kwrite",), ()),
    ("Mousepad", ("mousepad",), ()),
    ("Neovim", ("nvim",), ()),
    ("Vim", ("gvim", "vim"), ()),
    ("Emacs", ("emacs",), ()),
    ("Geany", ("geany",), ()),
    ("Zed", ("zed",), ()),
    ("IntelliJ IDEA", ("idea", "intellij-idea-community"), ()),
    ("PyCharm", ("pycharm", "pycharm-community"), ()),
    ("Android Studio", ("studio", "android-studio"), ()),
    ("Notepad++", ("notepad-plus-plus",), ()),
)


def get_available_editors() -> list[Editor]:
    found: list[Editor] = []
    seen: set[str] = set()
    for name, bins, args in KNOWN_EDITORS:
        for binary in bins:
            path = shutil.which(binary)
            if path and path not in seen:
                found.append(Editor(name=name, executable=path, args=args))
                seen.add(path)
                break
    return found


def find_editor(name: str | None) -> Editor | None:
    editors = get_available_editors()
    if name:
        for editor in editors:
            if editor.name == name or os.path.basename(editor.executable) == name:
                return editor
    return editors[0] if editors else None


def open_in_editor(editor: Editor, path: str, extra_args: tuple[str, ...] = ()) -> None:
    import subprocess

    subprocess.Popen([editor.executable, *editor.args, *extra_args, path], start_new_session=True)
