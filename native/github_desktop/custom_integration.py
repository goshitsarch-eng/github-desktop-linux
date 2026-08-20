"""Custom editor/shell helpers matching Desktop's `lib/custom-integration`."""

from __future__ import annotations

import os
import shlex
from collections.abc import Sequence

# Desktop replaces this token with the repository or file path.
TARGET_PATH_ARGUMENT = "%TARGET_PATH%"


def parse_custom_arguments(args: str) -> list[str]:
    if not args or not args.strip():
        return []
    try:
        return shlex.split(args, posix=True)
    except ValueError:
        return args.split()


def expand_target_path(args: Sequence[str], target: str) -> list[str]:
    return [arg.replace(TARGET_PATH_ARGUMENT, target) for arg in args]


def has_target_path_argument(args: Sequence[str]) -> bool:
    return any(TARGET_PATH_ARGUMENT in arg for arg in args)


def command_for_custom_integration(executable: str, arguments: str, target: str) -> list[str]:
    """Build argv for a custom editor or shell, inserting the target path."""
    argv = parse_custom_arguments(arguments)
    if not has_target_path_argument(argv):
        argv = [*argv, TARGET_PATH_ARGUMENT]
    return [executable, *expand_target_path(argv, target)]


def is_executable_path(path: str) -> bool:
    return bool(path) and os.path.isfile(path) and os.access(path, os.X_OK)
