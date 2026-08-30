"""Freedesktop trash implementation.

Plasma, GNOME and every other freedesktop session read the same
`trash specification <https://specifications.freedesktop.org/trash-spec/>`_, so
moving a file to the trash is a filesystem operation rather than something to
delegate to a toolkit. Dolphin shows anything written here, and "Restore"
works because the ``.trashinfo`` companion records the original path.
"""

from __future__ import annotations

import errno
import os
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from .logging import get_logger

log = get_logger()

TRASH_INFO_SUFFIX = ".trashinfo"


def home_trash_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(data_home) / "Trash"


def _top_dir(path: Path) -> Path | None:
    """Walk up to the mount point holding ``path``."""
    try:
        current = path.resolve().parent
        device = os.stat(current).st_dev
    except OSError:
        return None
    while True:
        parent = current.parent
        if parent == current:
            return current
        try:
            if os.stat(parent).st_dev != device:
                return current
        except OSError:
            return current
        current = parent


def _volume_trash_dir(top: Path) -> Path | None:
    """``$topdir/.Trash/$uid`` when it is safe, else ``$topdir/.Trash-$uid``."""
    uid = os.getuid()
    shared = top / ".Trash"
    try:
        stat = os.lstat(shared)
        # The spec requires the sticky bit and forbids a symlink here.
        if not os.path.islink(shared) and stat.st_mode & 0o1000:
            candidate = shared / str(uid)
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
    except OSError:
        pass
    candidate = top / f".Trash-{uid}"
    try:
        candidate.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return candidate


def _unique_name(files_dir: Path, info_dir: Path, name: str) -> str:
    """Pick a name free in both ``files/`` and ``info/``."""
    stem, dot, extension = name.partition(".")
    candidate = name
    counter = 1
    while (files_dir / candidate).exists() or (info_dir / (candidate + TRASH_INFO_SUFFIX)).exists():
        counter += 1
        candidate = f"{stem}.{counter}{dot}{extension}" if dot else f"{name}.{counter}"
    return candidate


def _write_info(info_dir: Path, name: str, original: str) -> Path:
    info_path = info_dir / (name + TRASH_INFO_SUFFIX)
    deleted_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    body = f"[Trash Info]\nPath={quote(original, safe='/')}\nDeletionDate={deleted_at}\n"
    # O_EXCL so two processes trashing at once cannot claim the same name.
    fd = os.open(info_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(body)
    return info_path


def _trash_into(trash_dir: Path, path: Path, recorded_path: str) -> bool:
    files_dir = trash_dir / "files"
    info_dir = trash_dir / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    name = _unique_name(files_dir, info_dir, path.name)
    info_path = _write_info(info_dir, name, recorded_path)
    try:
        os.rename(path, files_dir / name)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            info_path.unlink(missing_ok=True)
            raise
        # Crossing a filesystem boundary: copy then remove the original.
        try:
            if path.is_dir() and not path.is_symlink():
                shutil.copytree(path, files_dir / name, symlinks=True)
                shutil.rmtree(path)
            else:
                shutil.copy2(path, files_dir / name, follow_symlinks=False)
                path.unlink()
        except OSError:
            info_path.unlink(missing_ok=True)
            shutil.rmtree(files_dir / name, ignore_errors=True)
            raise
    return True


def move_to_trash(path: str) -> bool:
    """Move ``path`` to the trash. Returns False when no trash accepts it."""
    target = Path(path)
    if not os.path.lexists(target):
        return True
    absolute = str(target.absolute())

    home_trash = home_trash_dir()
    try:
        same_volume = os.stat(target.parent).st_dev == os.stat(home_trash.parent).st_dev
    except OSError:
        same_volume = False

    if same_volume or not home_trash.exists():
        try:
            return _trash_into(home_trash, target, absolute)
        except OSError as exc:
            log.debug("home trash rejected %s: %s", path, exc)

    top = _top_dir(target)
    if top is not None:
        volume_trash = _volume_trash_dir(top)
        if volume_trash is not None:
            try:
                # The spec stores volume-relative paths so the trash survives
                # the filesystem being mounted somewhere else.
                relative = os.path.relpath(absolute, str(top))
                return _trash_into(volume_trash, target, relative)
            except OSError as exc:
                log.debug("volume trash rejected %s: %s", path, exc)

    try:
        return _trash_into(home_trash, target, absolute)
    except OSError as exc:
        log.warning("no trash directory accepted %s: %s", path, exc)
        return False
