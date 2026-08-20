"""Detect installed GUI editors on Linux (parity with Desktop `lib/editors/linux.ts`)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from .linux import path_exists, spawn


@dataclass(frozen=True)
class Editor:
    name: str
    executable: str
    args: tuple[str, ...] = ()


SUGGESTED_EXTERNAL_EDITOR = "Visual Studio Code"
SUGGESTED_EXTERNAL_EDITOR_URL = "https://code.visualstudio.com"

# Desktop `ILinuxExternalEditor.paths`: snap, system, WSL, Flatpak, and Toolbox.
# Relative paths are resolved from $HOME (same as Desktop's `.local/share/...` entries).
LINUX_EDITORS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("Atom", ("/snap/bin/atom", "/usr/bin/atom"), ("-w",)),
    ("Neovim", ("/usr/bin/nvim",), ()),
    ("Neovim-Qt", ("/usr/bin/nvim-qt",), ()),
    ("Neovide", ("/usr/bin/neovide",), ()),
    ("gVim", ("/usr/bin/gvim",), ()),
    (
        "Visual Studio Code",
        (
            "/usr/share/code/bin/code",
            "/snap/bin/code",
            "/usr/bin/code",
            "/mnt/c/Program Files/Microsoft VS Code/bin/code",
            "/var/lib/flatpak/app/com.visualstudio.code/current/active/export/bin/com.visualstudio.code",
            ".local/share/flatpak/app/com.visualstudio.code/current/active/export/bin/com.visualstudio.code",
        ),
        ("--wait",),
    ),
    (
        "Visual Studio Code (Insiders)",
        (
            "/snap/bin/code-insiders",
            "/usr/bin/code-insiders",
            "/var/lib/flatpak/app/com.visualstudio.code.insiders/current/active/export/bin/com.visualstudio.code.insiders",
            ".local/share/flatpak/app/com.visualstudio.code.insiders/current/active/export/bin/com.visualstudio.code.insiders",
        ),
        ("--wait",),
    ),
    (
        "VSCodium",
        (
            "/usr/bin/codium",
            "/var/lib/flatpak/app/com.vscodium.codium/current/active/export/bin/com.vscodium.codium",
            "/usr/share/vscodium-bin/bin/codium",
            ".local/share/flatpak/app/com.vscodium.codium/current/active/export/bin/com.vscodium.codium",
            "/snap/bin/codium",
        ),
        ("--wait",),
    ),
    ("VSCodium (Insiders)", ("/usr/bin/codium-insiders",), ("--wait",)),
    ("Sublime Text", ("/usr/bin/subl",), ("-w",)),
    ("Typora", ("/usr/bin/typora",), ()),
    (
        "SlickEdit",
        (
            "/opt/slickedit-pro2018/bin/vs",
            "/opt/slickedit-pro2017/bin/vs",
            "/opt/slickedit-pro2016/bin/vs",
            "/opt/slickedit-pro2015/bin/vs",
        ),
        (),
    ),
    ("Code", ("/usr/bin/io.elementary.code",), ()),
    ("Lite XL", ("/usr/bin/lite-xl",), ()),
    (
        "JetBrains PhpStorm",
        ("/snap/bin/phpstorm", ".local/share/JetBrains/Toolbox/scripts/PhpStorm"),
        (),
    ),
    (
        "JetBrains WebStorm",
        ("/snap/bin/webstorm", ".local/share/JetBrains/Toolbox/scripts/webstorm"),
        (),
    ),
    ("IntelliJ IDEA", ("/snap/bin/idea", ".local/share/JetBrains/Toolbox/scripts/idea"), ()),
    (
        "IntelliJ IDEA Ultimate Edition",
        (
            "/snap/bin/intellij-idea-ultimate",
            ".local/share/JetBrains/Toolbox/scripts/intellij-idea-ultimate",
        ),
        (),
    ),
    ("JetBrains Goland", ("/snap/bin/goland", ".local/share/JetBrains/Toolbox/scripts/goland"), ()),
    ("JetBrains CLion", ("/snap/bin/clion", ".local/share/JetBrains/Toolbox/scripts/clion1"), ()),
    ("JetBrains Rider", ("/snap/bin/rider", ".local/share/JetBrains/Toolbox/scripts/rider"), ()),
    (
        "JetBrains RubyMine",
        ("/snap/bin/rubymine", ".local/share/JetBrains/Toolbox/scripts/rubymine"),
        (),
    ),
    (
        "JetBrains PyCharm",
        (
            "/snap/bin/pycharm",
            "/snap/bin/pycharm-professional",
            ".local/share/JetBrains/Toolbox/scripts/pycharm",
        ),
        (),
    ),
    (
        "JetBrains RustRover",
        ("/snap/bin/rustrover", ".local/share/JetBrains/Toolbox/scripts/rustrover"),
        (),
    ),
    ("Android Studio", ("/snap/bin/studio", ".local/share/JetBrains/Toolbox/scripts/studio"), ()),
    ("Emacs", ("/snap/bin/emacs", "/usr/local/bin/emacs", "/usr/bin/emacs"), ()),
    ("Kate", ("/usr/bin/kate",), ()),
    ("GEdit", ("/usr/bin/gedit",), ()),
    ("GNOME Text Editor", ("/usr/bin/gnome-text-editor",), ()),
    ("GNOME Builder", ("/usr/bin/gnome-builder",), ()),
    ("Notepadqq", ("/usr/bin/notepadqq",), ()),
    ("Mousepad", ("/usr/bin/mousepad",), ()),
    ("Pulsar", ("/usr/bin/pulsar",), ()),
    ("Pluma", ("/usr/bin/pluma",), ()),
    (
        "Zed",
        ("/usr/bin/zedit", "/usr/bin/zeditor", "/usr/bin/zed-editor", "~/.local/bin/zed", "/usr/bin/zed"),
        (),
    ),
)

# Additional PATH lookups that Desktop does not list, after the official table.
EXTRA_EDITORS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("Cursor", ("cursor",), ("--wait",)),
    ("Visual Studio Code", ("code-oss",), ("--wait",)),
    ("Geany", ("geany",), ()),
    ("KWrite", ("kwrite",), ()),
    ("Vim", ("vim",), ()),
    ("Notepad++", ("notepad-plus-plus",), ()),
    ("PyCharm", ("pycharm-community",), ()),
    ("IntelliJ IDEA", ("intellij-idea-community",), ()),
    ("Android Studio", ("android-studio",), ()),
    ("Sublime Text", ("sublime_text",), ("-w",)),
)

KNOWN_EDITORS = LINUX_EDITORS + EXTRA_EDITORS


def expand_editor_path(path: str) -> str:
    """Resolve Desktop relative editor paths against the user's home directory."""
    if path.startswith("~"):
        return os.path.expanduser(path)
    if path.startswith("."):
        return os.path.join(os.path.expanduser("~"), path)
    return path


def first_existing_editor_path(paths: tuple[str, ...]) -> str | None:
    """Desktop `getAvailablePath`: first candidate that exists, then `PATH`."""
    for raw in paths:
        candidate = expand_editor_path(raw)
        if path_exists(candidate):
            return candidate
    for raw in paths:
        found = shutil.which(os.path.basename(raw))
        if found:
            return found
    return None


def get_available_editors() -> list[Editor]:
    found: list[Editor] = []
    seen: set[str] = set()
    for name, paths, args in KNOWN_EDITORS:
        path = first_existing_editor_path(paths)
        if path and path not in seen:
            found.append(Editor(name=name, executable=path, args=args))
            seen.add(path)
    return found


def find_editor(name: str | None) -> Editor | None:
    editors = get_available_editors()
    if name:
        for editor in editors:
            if editor.name == name or os.path.basename(editor.executable) == name:
                return editor
    return editors[0] if editors else None


def open_in_editor(
    editor: Editor,
    path: str,
    extra_args: tuple[str, ...] = (),
    *,
    append_path: bool = True,
) -> None:
    cmd = [editor.executable, *editor.args, *extra_args]
    if append_path:
        cmd.append(path)
    if not os.path.isfile(editor.executable) and not shutil.which(editor.executable) and not path_exists(editor.executable):
        raise FileNotFoundError(f"Couldn't find the executable '{editor.executable}' for editor '{editor.name}'")
    spawn(
        cmd[0],
        cmd[1:],
        cwd=os.path.dirname(path) if os.path.isfile(path) else path,
        start_new_session=True,
    )
