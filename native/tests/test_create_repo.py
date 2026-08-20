"""Create-repository helpers and AppStore.create_repository Desktop parity."""

from __future__ import annotations

from pathlib import Path

from github_desktop.create_repo import (
    classify_create_path,
    sanitized_repository_name,
    write_default_readme,
)
from github_desktop.git.ops import get_commits, get_status
from github_desktop.store import AppStore


def test_sanitized_repository_name_matches_desktop() -> None:
    assert sanitized_repository_name("My Repo 🎉") == "My-Repo--"
    assert sanitized_repository_name("already-ok") == "already-ok"
    assert sanitized_repository_name("foo_bar.git") == "foo_bar.git"
    assert sanitized_repository_name("") == ""


def test_write_default_readme_includes_empty_description(tmp_path: Path) -> None:
    write_default_readme(str(tmp_path), "Demo", "")
    text = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert text == "# Demo\n\n"


def test_classify_create_path_detects_repo_and_subfolder(git_repo: Path, tmp_path: Path) -> None:
    is_repo, is_sub = classify_create_path(str(git_repo))
    assert is_repo is True
    assert is_sub is False
    nested = git_repo / "inside"
    nested.mkdir()
    is_repo, is_sub = classify_create_path(str(nested))
    assert is_repo is False
    assert is_sub is True
    missing = tmp_path / "nope"
    is_repo, is_sub = classify_create_path(str(missing))
    assert is_repo is False
    assert is_sub is False


def test_create_repository_writes_templates_and_initial_commit(
    isolated_config, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test User")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    parent = tmp_path / "GitHub"
    parent.mkdir()
    dest = parent / "demo-app"
    store = AppStore()
    repo = store.create_repository(
        str(dest),
        "A sample project",
        name="demo-app",
        create_readme=True,
        gitignore="Python",
        license_name="MIT License",
    )
    assert repo.path == str(dest)
    assert (dest / "README.md").read_text(encoding="utf-8") == "# demo-app\nA sample project\n"
    ignore = (dest / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__/" in ignore
    license_text = (dest / "LICENSE").read_text(encoding="utf-8")
    assert "MIT License" in license_text
    assert (dest / ".gitattributes").read_text(encoding="utf-8").startswith("# Auto detect")
    description = (dest / ".git" / "description").read_text(encoding="utf-8").strip()
    assert description == "A sample project"
    status = get_status(str(dest))
    assert status is not None
    assert not status.working_directory.files
    commits = get_commits(str(dest), limit=5)
    assert commits
    assert commits[0].summary == "Initial commit"
    assert store.settings.clone_default_directory == str(parent)


def test_gitignore_names_include_desktop_github_templates() -> None:
    from github_desktop.create_repo import gitignore_names

    names = gitignore_names()
    assert "Python" in names
    assert "Node" in names
    assert "VisualStudio" in names
    assert "Go" in names
    assert "Rust" in names
    assert len(names) >= 100


def test_create_repository_skips_readme_by_default(isolated_config, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test User")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test User")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    dest = tmp_path / "empty-ish"
    store = AppStore()
    store.create_repository(str(dest), "")
    assert not (dest / "README.md").exists()
    assert (dest / ".gitattributes").exists()


def test_abort_clone_drops_in_flight_entry(isolated_config) -> None:
    from github_desktop.models import CloningRepository

    store = AppStore()
    cloning = CloningRepository(id=-42, path="/tmp/x", url="https://example.com/x.git")
    store.cloning.append(cloning)
    store.abort_clone(-42)
    assert store.cloning == []
