"""Detect and launch terminal emulators on Linux."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Shell:
    name: str
    executable: str
    args: tuple[str, ...] = ()


KNOWN_SHELLS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("GNOME Terminal", ("gnome-terminal",), ("--working-directory", "{cwd}")),
    ("GNOME Console", ("kgx",), ("--working-directory", "{cwd}")),
    ("Konsole", ("konsole",), ("--workdir", "{cwd}")),
    ("Xfce Terminal", ("xfce4-terminal",), ("--working-directory", "{cwd}")),
    ("Tilix", ("tilix",), ("-w", "{cwd}")),
    ("Terminator", ("terminator",), ("--working-directory", "{cwd}")),
    ("Alacritty", ("alacritty",), ("--working-directory", "{cwd}")),
    ("Kitty", ("kitty",), ("--directory", "{cwd}")),
    ("WezTerm", ("wezterm",), ("start", "--cwd", "{cwd}")),
    ("Foot", ("foot",), ("-D", "{cwd}")),
    ("Xterm", ("xterm",), ("-e", "bash")),
    ("Ptyxis", ("ptyxis",), ("--working-directory", "{cwd}")),
    ("Cosmic Term", ("cosmic-term",), ()),
)


def get_available_shells() -> list[Shell]:
    found: list[Shell] = []
    seen: set[str] = set()
    for name, bins, args in KNOWN_SHELLS:
        for binary in bins:
            path = shutil.which(binary)
            if path and path not in seen:
                found.append(Shell(name, path, args))
                seen.add(path)
                break
    return found


def find_shell(name: str | None) -> Shell | None:
    shells = get_available_shells()
    if name:
        for shell in shells:
            if shell.name == name or os.path.basename(shell.executable) == name:
                return shell
    return shells[0] if shells else None


def open_shell(shell: Shell, cwd: str, extra_args: tuple[str, ...] = ()) -> None:
    args = []
    for arg in shell.args:
        args.append(arg.format(cwd=cwd))
    subprocess.Popen([shell.executable, *args, *extra_args], cwd=cwd, start_new_session=True)


def open_file_manager(path: str) -> None:
    subprocess.Popen(["xdg-open", path], start_new_session=True)


def open_external(url: str) -> None:
    subprocess.Popen(["xdg-open", url], start_new_session=True)
