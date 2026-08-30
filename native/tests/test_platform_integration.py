"""The pieces that replaced GLib, libsecret and Gio in the Qt rewrite.

Trash, credential storage and main-thread dispatch used to come from GTK's
stack. They are now freedesktop-spec Python, KWallet/Secret Service, and a
small Qt shim, so they need their own coverage.
"""

from __future__ import annotations

import pytest

from github_desktop import mainloop, trash


# --- trash ----------------------------------------------------------------


@pytest.fixture
def home_trash(tmp_path, monkeypatch):
    data_home = tmp_path / "data"
    data_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    return data_home / "Trash"


def test_trashing_a_file_moves_it_and_records_where_from(home_trash, tmp_path) -> None:
    target = tmp_path / "work" / "notes.txt"
    target.parent.mkdir()
    target.write_text("hello", encoding="utf-8")

    assert trash.move_to_trash(str(target)) is True
    assert not target.exists()

    files = sorted((home_trash / "files").iterdir())
    assert [f.name for f in files] == ["notes.txt"]
    assert files[0].read_text(encoding="utf-8") == "hello"

    info = (home_trash / "info" / "notes.txt.trashinfo").read_text(encoding="utf-8")
    assert info.startswith("[Trash Info]")
    # Restoring depends on the original path being recorded.
    assert f"Path={target.absolute()}" in info
    assert "DeletionDate=" in info


def test_trashing_a_directory_takes_its_contents(home_trash, tmp_path) -> None:
    target = tmp_path / "build"
    (target / "nested").mkdir(parents=True)
    (target / "nested" / "a.o").write_text("x", encoding="utf-8")

    assert trash.move_to_trash(str(target)) is True
    assert not target.exists()
    assert (home_trash / "files" / "build" / "nested" / "a.o").read_text(encoding="utf-8") == "x"


def test_a_second_file_of_the_same_name_gets_a_distinct_slot(home_trash, tmp_path) -> None:
    for body in ("first", "second"):
        target = tmp_path / "notes.txt"
        target.write_text(body, encoding="utf-8")
        assert trash.move_to_trash(str(target)) is True

    names = sorted(f.name for f in (home_trash / "files").iterdir())
    assert len(names) == 2
    assert "notes.txt" in names
    # Both keep a matching .trashinfo, which is what makes them restorable.
    infos = sorted(f.name for f in (home_trash / "info").iterdir())
    assert [n + ".trashinfo" for n in names] == infos


def test_trashing_something_that_is_not_there_succeeds(home_trash, tmp_path) -> None:
    assert trash.move_to_trash(str(tmp_path / "gone.txt")) is True


def test_paths_with_spaces_and_percent_are_encoded(home_trash, tmp_path) -> None:
    target = tmp_path / "a file 100% real.txt"
    target.write_text("x", encoding="utf-8")
    assert trash.move_to_trash(str(target)) is True
    info = next((home_trash / "info").iterdir()).read_text(encoding="utf-8")
    assert "%20" in info and "%25" in info
    # Slashes stay readable, per the spec.
    assert info.count("/") >= 2


def test_symlink_is_trashed_without_following_it(home_trash, tmp_path) -> None:
    real = tmp_path / "real.txt"
    real.write_text("keep me", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(real)

    assert trash.move_to_trash(str(link)) is True
    assert real.exists(), "the link target must survive"
    assert (home_trash / "files" / "link.txt").is_symlink()


def test_git_ops_uses_the_trash(home_trash, tmp_path) -> None:
    """`move_item_to_trash` is what discard-changes calls."""
    from github_desktop.git.ops import move_item_to_trash

    target = tmp_path / "discard-me.txt"
    target.write_text("x", encoding="utf-8")
    assert move_item_to_trash(str(target)) is True
    assert not target.exists()
    assert (home_trash / "files" / "discard-me.txt").exists()


# --- credential storage ---------------------------------------------------


def test_keyring_backend_is_skipped_under_test(monkeypatch) -> None:
    """Tests must never write to the developer's real wallet."""
    from github_desktop import keyring

    keyring.reset_backend_cache()
    assert keyring.get_backend() is None
    assert keyring.backend_name() == "encrypted file"


def test_secrets_round_trip_through_the_file_store(isolated_config) -> None:
    from github_desktop import secrets

    secrets.set_password("svc", "ada", "s3cret")
    assert secrets.get_password("svc", "ada") == "s3cret"

    store = isolated_config / "github-desktop" / "secrets.json"
    assert store.exists()
    # Nobody else on the machine gets to read the fallback store.
    assert oct(store.stat().st_mode & 0o777) == "0o600"

    secrets.delete_password("svc", "ada")
    assert secrets.get_password("svc", "ada") is None


def test_account_tokens_use_desktops_key_layout(isolated_config) -> None:
    from github_desktop import secrets
    from github_desktop.auth import get_key_for_endpoint

    secrets.set_account_token("https://api.github.com", "ada", "token")
    assert secrets.get_account_token("https://api.github.com", "ada") == "token"
    assert secrets.get_password(get_key_for_endpoint("https://api.github.com"), "ada") == "token"

    secrets.delete_account_token("https://api.github.com", "ada")
    assert secrets.get_account_token("https://api.github.com", "ada") is None


def test_secret_tool_arguments_are_stable() -> None:
    """The attributes have to match between store, lookup and clear."""
    from github_desktop.keyring import SecretToolBackend

    assert SecretToolBackend._attributes("svc", "ada") == ["service", "svc", "account", "ada"]


# --- main-thread dispatch -------------------------------------------------


def test_dispatch_is_inline_without_a_gui() -> None:
    """Off the GUI, callbacks run where they are posted."""
    seen = []

    # post() declines and the caller is expected to run it itself...
    assert mainloop.post(lambda: seen.append("queued")) is False
    assert seen == []

    # ...which is exactly what post_or_call() does.
    mainloop.post_or_call(lambda: seen.append("inline"))
    assert seen == ["inline"]


def test_gui_predicates_are_false_under_test() -> None:
    """Even with a QApplication alive from another test, pytest runs inline."""
    assert mainloop.is_gui_running() is False
    assert mainloop.has_gui() is False


def test_mount_table_is_read_from_proc(monkeypatch) -> None:
    """A smoke check that we can parse the real /proc/self/mountinfo."""
    from github_desktop.ui import filepicker

    points = filepicker._mount_points()
    assert points, "expected at least the root filesystem"
    assert all(p.startswith("/") for p, _source in points)
