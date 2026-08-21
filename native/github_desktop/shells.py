"""Detect and launch terminal emulators on Linux (Desktop `lib/shells/linux.ts`)."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from collections.abc import Sequence

from .linux import path_exists, spawn


@dataclass(frozen=True)
class Shell:
    name: str
    executable: str
    args: tuple[str, ...] = ()


# Desktop `Shell` enum plus launch argv. Extra terminals follow the official list.
KNOWN_SHELLS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("GNOME Terminal", ("gnome-terminal",), ("--working-directory", "{cwd}")),
    ("GNOME Console", ("kgx",), ("--working-directory", "{cwd}")),
    ("Ptyxis", ("ptyxis",), ("--new-window", "--working-directory", "{cwd}")),
    ("MATE Terminal", ("mate-terminal",), ("--working-directory", "{cwd}")),
    ("Tilix", ("tilix",), ("--working-directory", "{cwd}")),
    ("Terminator", ("terminator",), ("--working-directory", "{cwd}")),
    ("URxvt", ("urxvt",), ("-cd", "{cwd}")),
    ("Konsole", ("konsole",), ("--workdir", "{cwd}")),
    ("XTerm", ("xterm",), ("-e", "/bin/bash")),
    ("Terminology", ("terminology",), ("-d", "{cwd}")),
    ("Deepin Terminal", ("deepin-terminal",), ("-w", "{cwd}")),
    ("Elementary Terminal", ("io.elementary.terminal",), ("-w", "{cwd}")),
    ("XFCE Terminal", ("xfce4-terminal",), ("--working-directory", "{cwd}")),
    ("Alacritty", ("alacritty",), ("--working-directory", "{cwd}")),
    ("Kitty", ("kitty",), ("--single-instance", "--directory", "{cwd}")),
    ("LXDE Terminal", ("lxterminal",), ("--working-directory={cwd}",)),
    ("Warp", ("warp-terminal",), ()),
    ("Ghostty", ("ghostty",), ("--working-directory={cwd}",)),
    ("WezTerm", ("wezterm",), ("start", "--cwd", "{cwd}")),
    ("Foot", ("foot",), ("-D", "{cwd}")),
    ("Cosmic Term", ("cosmic-term",), ()),
)

# Desktop `getShellPath` absolute locations, checked before PATH.
LINUX_SHELL_PATHS: dict[str, tuple[str, ...]] = {
    "GNOME Terminal": ("/usr/bin/gnome-terminal",),
    "GNOME Console": ("/usr/bin/kgx",),
    "Ptyxis": ("/usr/bin/ptyxis",),
    "MATE Terminal": ("/usr/bin/mate-terminal",),
    "Tilix": ("/usr/bin/tilix",),
    "Terminator": ("/usr/bin/terminator",),
    "URxvt": ("/usr/bin/urxvt",),
    "Konsole": ("/usr/bin/konsole",),
    "XTerm": ("/usr/bin/xterm",),
    "Terminology": ("/usr/bin/terminology",),
    "Deepin Terminal": ("/usr/bin/deepin-terminal",),
    "Elementary Terminal": ("/usr/bin/io.elementary.terminal",),
    "XFCE Terminal": ("/usr/bin/xfce4-terminal",),
    "Alacritty": ("/usr/bin/alacritty",),
    "Kitty": ("/usr/bin/kitty",),
    "LXDE Terminal": ("/usr/bin/lxterminal",),
    "Warp": ("/usr/bin/warp-terminal",),
    "Ghostty": ("/usr/bin/ghostty",),
}


def first_existing_shell_path(name: str, bins: tuple[str, ...]) -> str | None:
    for path in LINUX_SHELL_PATHS.get(name, ()):
        if path_exists(path):
            return path
    for binary in bins:
        path = shutil.which(binary)
        if path:
            return path
        candidate = f"/usr/bin/{binary}"
        if path_exists(candidate):
            return candidate
    return None


def get_available_shells() -> list[Shell]:
    found: list[Shell] = []
    seen: set[str] = set()
    for name, bins, args in KNOWN_SHELLS:
        path = first_existing_shell_path(name, bins)
        if path and path not in seen:
            found.append(Shell(name, path, args))
            seen.add(path)
    return found


def find_shell(name: str | None) -> Shell | None:
    shells = get_available_shells()
    if name:
        for shell in shells:
            if shell.name == name or os.path.basename(shell.executable) == name:
                return shell
    return shells[0] if shells else None


def open_shell(shell: Shell, cwd: str, extra_args: tuple[str, ...] = ()) -> None:
    args = [arg.format(cwd=cwd) for arg in shell.args]
    spawn(shell.executable, [*args, *extra_args], cwd=cwd, start_new_session=True)


def open_custom_shell(executable: str, argv: Sequence[str], cwd: str) -> None:
    spawn(executable, list(argv), cwd=cwd, start_new_session=True)


def open_file_manager(path: str) -> None:
    spawn("xdg-open", [path], start_new_session=True)


def open_external(url: str) -> bool:
    try:
        spawn("xdg-open", [url], start_new_session=True)
        return True
    except OSError:
        return False


def open_in_default_program(path: str) -> None:
    """Open a working-tree file with the desktop's default handler (Desktop onOpenBinaryFile)."""
    spawn("xdg-open", [path], start_new_session=True)
