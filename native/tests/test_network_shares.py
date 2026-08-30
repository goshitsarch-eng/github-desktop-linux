"""Picking a repository that lives on a network share.

The GTK build listed network locations in its folder picker but could not act
on one: the dialog handed back a URL with no local path, the caller asked for
``get_path()``, got ``None``, and silently kept the old value -- or the desktop
offered to hand the location to a different application. These tests pin the
replacement behaviour: resolve the URL against whatever is actually mounted,
and when nothing is, say so.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from github_desktop.ui import filepicker
from github_desktop.ui.filepicker import (
    NETWORK_HELP,
    PickedFolder,
    resolve_network_url,
    resolve_picked_url,
)


@pytest.fixture
def no_mounts(monkeypatch, tmp_path):
    """Isolate from the real machine: no mounts, no gvfs, no kio-fuse."""
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [])
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return tmp_path


def test_local_path_passes_through(no_mounts, tmp_path) -> None:
    target = tmp_path / "repo"
    target.mkdir()
    picked = resolve_picked_url(str(target))
    assert picked.ok
    assert picked.path == os.path.realpath(target)


def test_file_url_becomes_a_path(no_mounts, tmp_path) -> None:
    target = tmp_path / "my repo"
    target.mkdir()
    picked = resolve_picked_url(target.as_uri())
    assert picked.ok
    assert picked.path == os.path.realpath(target)


def test_unmounted_share_explains_itself(no_mounts) -> None:
    picked = resolve_picked_url("smb://nas/projects/app")
    assert not picked.ok
    assert picked.path is None
    # The old build ignored this click entirely.
    assert "smb://nas/projects" in picked.error
    assert "not mounted" in picked.error
    assert picked.help_text == NETWORK_HELP
    assert picked.url == "smb://nas/projects/app"


def test_kernel_mounted_share_resolves(monkeypatch, tmp_path) -> None:
    """A CIFS mount of //nas/projects is a real directory; use it."""
    mount = tmp_path / "mnt" / "projects"
    (mount / "app").mkdir(parents=True)
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [(str(mount), "//nas/projects")])
    picked = resolve_picked_url("smb://nas/projects/app")
    assert picked.ok
    assert picked.path == os.path.realpath(mount / "app")


def test_nfs_mount_resolves(monkeypatch, tmp_path) -> None:
    mount = tmp_path / "mnt" / "srv"
    (mount / "code").mkdir(parents=True)
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [(str(mount), "fileserver:/srv")])
    picked = resolve_picked_url("nfs://fileserver/srv/code")
    assert picked.ok
    assert picked.path == os.path.realpath(mount / "code")


def test_sshfs_mount_resolves(monkeypatch, tmp_path) -> None:
    mount = tmp_path / "mnt" / "remote"
    (mount / "work").mkdir(parents=True)
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [(str(mount), "me@build.example:/srv")])
    picked = resolve_picked_url("sftp://me@build.example/srv/work")
    assert picked.ok
    assert picked.path == os.path.realpath(mount / "work")


def test_gvfs_mount_resolves(monkeypatch, tmp_path) -> None:
    """GNOME sessions expose shares under $XDG_RUNTIME_DIR/gvfs."""
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [])
    runtime = tmp_path / "runtime"
    mount = runtime / "gvfs" / "smb-share:server=nas,share=projects" / "app"
    mount.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    picked = resolve_picked_url("smb://nas/projects/app")
    assert picked.ok
    assert picked.path == os.path.realpath(mount)


def test_gvfs_mount_with_user_resolves(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [])
    runtime = tmp_path / "runtime"
    mount = runtime / "gvfs" / "smb-share:server=nas,share=projects,user=ada" / "app"
    mount.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    picked = resolve_picked_url("smb://ada@nas/projects/app")
    assert picked.ok
    assert picked.path == os.path.realpath(mount)


def test_kio_fuse_mount_resolves(monkeypatch, tmp_path) -> None:
    """On Plasma, KIOFuse lays mounts out as <root>/<scheme>/<host>/<share>."""
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [])
    runtime = tmp_path / "runtime"
    mount = runtime / "kio-fuse" / "smb" / "nas" / "projects" / "app"
    mount.mkdir(parents=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    picked = resolve_picked_url("smb://nas/projects/app")
    assert picked.ok
    assert picked.path == os.path.realpath(mount)


def test_mounted_share_missing_subfolder_says_so(monkeypatch, tmp_path) -> None:
    """Reachable share, wrong folder: that is not a "go and mount it" problem."""
    mount = tmp_path / "mnt" / "projects"
    mount.mkdir(parents=True)
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [(str(mount), "//nas/projects")])
    picked = resolve_picked_url("smb://nas/projects/missing")
    assert not picked.ok
    assert "does not exist" in picked.error
    assert picked.help_text == ""


def test_windows_style_file_url_is_treated_as_smb(no_mounts) -> None:
    """``file://host/share`` is a UNC path written the long way round."""
    picked = resolve_picked_url("file://nas/projects/app")
    assert not picked.ok
    assert "smb://nas/projects" in picked.error


def test_locations_that_can_never_hold_a_repository(no_mounts) -> None:
    for url in ("trash:///", "recent:///", "https://example.com/repo"):
        picked = resolve_picked_url(url)
        assert not picked.ok, url
        assert "cannot hold a Git repository" in picked.error


def test_empty_url_is_a_no_op() -> None:
    assert resolve_picked_url("") == PickedFolder()


def test_mountinfo_parsing_handles_escaped_spaces(tmp_path, monkeypatch) -> None:
    """/proc/self/mountinfo escapes spaces in mount points as \\040."""
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "36 35 0:32 / /mnt/my\\040share rw,relatime - cifs //nas/my share rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(filepicker, "MOUNTINFO", str(mountinfo))
    points = filepicker._mount_points()
    assert ("/mnt/my share", "//nas/my") in points


def test_deepest_mount_wins(tmp_path, monkeypatch) -> None:
    """A nested mount must be preferred over the filesystem it sits on."""
    mountinfo = tmp_path / "mountinfo"
    mountinfo.write_text(
        "1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
        "2 1 0:2 / /mnt/nas rw - cifs //nas/projects rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(filepicker, "MOUNTINFO", str(mountinfo))
    assert filepicker._mount_points()[0][0] == "/mnt/nas"


def test_gvfs_candidate_names_are_ordered_most_specific_first() -> None:
    names = filepicker._gvfs_candidates("smb", "nas", "projects", "ada")
    assert names[0] == "smb-share:server=nas,share=projects,user=ada"
    assert "smb-share:server=nas,share=projects" in names


def test_network_url_without_a_host_is_rejected(no_mounts) -> None:
    picked = resolve_network_url("smb:///share")
    assert not picked.ok
    assert "not a location this app can open" in picked.error


def test_popup_bridge_reports_the_same_outcome(monkeypatch, tmp_path) -> None:
    """The QML side sees the resolution result, not a silent failure."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from github_desktop.store import AppStore
    from github_desktop.ui.popups import PopupBridge

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(filepicker, "_mount_points", lambda: [])
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "runtime"))
    bridge = PopupBridge(AppStore(), None)

    good = tmp_path / "repo"
    good.mkdir()
    resolved = bridge.resolveUrl(good.as_uri())
    assert resolved["path"] == os.path.realpath(good)
    assert resolved["error"] == ""

    failed = bridge.resolveUrl("smb://nas/projects/app")
    assert failed["path"] == ""
    assert "not mounted" in failed["error"]
    assert failed["help"] == NETWORK_HELP
    # The URL comes back so the dialog can offer to open it in the file manager.
    assert failed["url"] == "smb://nas/projects/app"
