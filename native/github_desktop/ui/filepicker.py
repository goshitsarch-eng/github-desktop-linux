"""Folder selection, including repositories that live on network shares.

The old GTK picker handed back a ``Gio.File`` and the callers asked it for
``get_path()``. For anything the kernel cannot see -- an ``smb://`` share the
file manager had merely *listed*, an ``sftp://`` bookmark -- that call returns
``None``, so picking a network folder silently did nothing, or the desktop
offered to hand the location to some other application instead of opening it.

Git needs a real path: it runs ``git`` in a working directory, so a URL that
only a client library can read is not usable. This module closes that gap
properly instead of dropping it on the floor:

* A ``file://`` URL becomes its local path.
* A remote URL is resolved through whatever userspace mount already exposes it
  as a directory -- KIO's ``kio-fuse`` mount, a gvfs FUSE mount, or an ordinary
  ``mount``\\ ed CIFS/NFS/SSHFS path.
* When nothing exposes it, the caller gets a :class:`PickedFolder` carrying the
  reason, so the UI can say what is wrong and what to do about it rather than
  ignoring the click.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlsplit

from ..logging import get_logger

log = get_logger()

# Schemes a userspace mount can expose as a real directory.
NETWORK_SCHEMES = frozenset(
    {"smb", "cifs", "sftp", "ssh", "fish", "nfs", "ftp", "ftps", "webdav", "dav", "davs", "afp", "mtp", "gphoto2"}
)
# Schemes no filesystem can ever expose; git could not use them regardless.
UNSUPPORTED_SCHEMES = frozenset({"trash", "recent", "http", "https", "about", "data"})

MOUNTINFO = "/proc/self/mountinfo"

NETWORK_HELP = (
    "Git needs a folder the system can open directly. Mount this share first "
    "— in Dolphin, open the share and choose Mount, or add it under System "
    "Settings → Network → Network Shares — then pick the mounted folder."
)


@dataclass(frozen=True)
class PickedFolder:
    """Outcome of resolving a picked location to something git can use."""

    path: str | None = None
    url: str = ""
    error: str = ""
    help_text: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.path)


def _mount_points() -> list[tuple[str, str]]:
    """Return ``(mount point, source)`` for every current mount, deepest first."""
    entries: list[tuple[str, str]] = []
    try:
        with open(MOUNTINFO, "r", encoding="utf-8") as handle:
            for line in handle:
                fields = line.split()
                try:
                    separator = fields.index("-")
                except ValueError:
                    continue
                # mountinfo: ... <mount point> ... - <fstype> <source> <options>
                mount_point = fields[4].replace("\\040", " ").replace("\\011", "\t")
                source = fields[separator + 2] if len(fields) > separator + 2 else ""
                entries.append((mount_point, source))
    except OSError as exc:
        log.debug("could not read %s: %s", MOUNTINFO, exc)
        return []
    entries.sort(key=lambda item: len(item[0]), reverse=True)
    return entries


def _gvfs_roots() -> Iterable[Path]:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        yield Path(runtime) / "gvfs"
        yield Path(runtime) / "kio-fuse"
    yield Path(os.path.expanduser("~/.gvfs"))


def _gvfs_candidates(scheme: str, host: str, share: str, user: str) -> list[str]:
    """Directory names gvfs uses for a mount, most specific first.

    gvfs encodes mounts as ``<scheme>:key=value,key=value``; which keys are
    present depends on whether the URL carried a user and a share.
    """
    scheme = "smb-share" if scheme in {"smb", "cifs"} else scheme
    parts: list[list[str]] = []
    base = [f"server={host}"]
    if share:
        base.append(f"share={share}")
    if user:
        parts.append([*base, f"user={user}"])
    parts.append(base)
    if share:
        parts.append([f"server={host}", f"share={share}"])
    names = []
    for combo in parts:
        name = f"{scheme}:" + ",".join(combo)
        if name not in names:
            names.append(name)
    return names


def _match_mounted_share(scheme: str, host: str, share: str, user: str) -> str | None:
    """Find a kernel mount (CIFS/NFS/SSHFS) already exposing this location."""
    host = host.lower()
    share = share.strip("/")
    for mount_point, source in _mount_points():
        lowered = source.lower()
        if scheme in {"smb", "cifs"}:
            expected = f"//{host}/{share}".rstrip("/")
            if lowered.rstrip("/") == expected or lowered.rstrip("/") == expected.replace("//", r"\\"):
                return mount_point
        elif scheme == "nfs":
            if lowered.rstrip("/") == f"{host}:/{share}".rstrip("/"):
                return mount_point
        elif scheme in {"sftp", "ssh", "fish"}:
            # sshfs sources look like user@host:/path
            candidate = lowered.split("@")[-1]
            if candidate.split(":")[0] == host:
                return mount_point
    return None


def _network_url_parts(url: str) -> tuple[str, str, str, str, str]:
    """Split a network URL into ``(scheme, user, host, share, subpath)``."""
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    user = unquote(parsed.username or "")
    path = unquote(parsed.path or "").strip("/")
    share, _, subpath = path.partition("/")
    return scheme, user, host, share, subpath


def resolve_network_url(url: str) -> PickedFolder:
    """Map a remote URL onto a local directory, or explain why we cannot.

    Only reports success when the resolved directory actually exists, so a
    stale mount table never yields a path that git would fail on later.
    """
    scheme, user, host, share, subpath = _network_url_parts(url)
    if not host:
        return PickedFolder(url=url, error=f"{url} is not a location this app can open.")

    found_root: str | None = None

    def finish(root: str) -> PickedFolder | None:
        nonlocal found_root
        found_root = root
        candidate = os.path.join(root, subpath) if subpath else root
        if os.path.isdir(candidate):
            return PickedFolder(path=os.path.realpath(candidate), url=url)
        return None

    mounted = _match_mounted_share(scheme, host, share, user)
    if mounted:
        resolved = finish(mounted)
        if resolved is not None:
            return resolved

    for root in _gvfs_roots():
        if not root.is_dir():
            continue
        # kio-fuse lays mounts out as <root>/<scheme>/<host>/<share>/...
        kio_candidate = root / scheme / host
        if kio_candidate.is_dir():
            resolved = finish(str(kio_candidate / share) if share else str(kio_candidate))
            if resolved is not None:
                return resolved
        for name in _gvfs_candidates(scheme, host, share, user):
            candidate = root / name
            if candidate.is_dir():
                resolved = finish(str(candidate))
                if resolved is not None:
                    return resolved

    label = f"{scheme}://{host}" + (f"/{share}" if share else "")
    if found_root is not None:
        # The share is reachable, so this is a plain "no such folder" rather
        # than something the user needs to go and mount.
        return PickedFolder(
            url=url,
            error=f"{url} does not exist on {label}.",
        )
    return PickedFolder(
        url=url,
        error=f"{label} is not mounted on this computer.",
        help_text=NETWORK_HELP,
    )


def resolve_picked_url(url: str) -> PickedFolder:
    """Turn any URL a folder dialog returns into a path git can work in."""
    if not url:
        return PickedFolder()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", url):
        # Already a plain path.
        return PickedFolder(path=os.path.realpath(os.path.expanduser(url)), url=url)

    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()

    if scheme == "file":
        path = unquote(parsed.path or "")
        if parsed.netloc and parsed.netloc not in {"", "localhost"}:
            # file://host/share is an SMB path written the long way round.
            return resolve_network_url(f"smb://{parsed.netloc}{path}")
        if not path:
            return PickedFolder(url=url, error="That location has no folder to open.")
        return PickedFolder(path=os.path.realpath(path), url=url)

    if scheme in UNSUPPORTED_SCHEMES:
        return PickedFolder(
            url=url,
            error=f"{scheme}: locations cannot hold a Git repository.",
        )

    if scheme in NETWORK_SCHEMES:
        return resolve_network_url(url)

    return PickedFolder(url=url, error=f"{scheme}: locations are not supported.")
