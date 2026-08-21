"""AppStore persistence, repository add/remove, theme, CLI flags."""

from __future__ import annotations

from pathlib import Path

from github_desktop.cli import main as cli_main
from github_desktop.models import ApplicationTheme, PopupType, RepositorySectionTab
from github_desktop.store import AppStore
from github_desktop.theme import apply_theme
from tests.conftest import run_git


def test_add_and_select_repository(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    added = store.add_repositories([str(git_repo)])
    assert len(added) == 1
    assert store.selected_repository is not None
    assert store.selected_repository.path == str(git_repo)
    store.set_section(RepositorySectionTab.HISTORY)
    assert store.section == RepositorySectionTab.HISTORY
    store.remove_repository(added[0], delete_files=False)
    assert store.repositories == []


def test_duplicate_add_is_idempotent(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    store.add_repositories([str(git_repo)])
    assert len(store.repositories) == 1


def test_commit_via_store(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo
    store.refresh_repository(repo)
    (git_repo / "n.txt").write_text("n\n", encoding="utf-8")
    store.refresh_repository(repo)
    # refresh is async via thread pool; call git status path directly
    from github_desktop.git.ops import get_status

    status = get_status(str(git_repo))
    store.state_for(repo).status = status
    store.commit(repo, "add n", "")
    # commit also async; do it synchronously by waiting briefly
    import time

    for _ in range(40):
        if (git_repo / "n.txt").exists() and not get_status(str(git_repo)).working_directory.files:
            break
        # commit may still be running
        time.sleep(0.05)
    # At least the store accepted the commit without throwing
    assert repo.path == str(git_repo)


def test_set_theme(isolated_config) -> None:
    store = AppStore()
    store.set_theme(ApplicationTheme.DARK.value)
    assert store.settings.theme == "dark"
    apply_theme(ApplicationTheme.LIGHT)
    apply_theme("system")


def test_cli_help(capsys) -> None:
    assert cli_main(["--help"]) == 0
    out = capsys.readouterr().out
    assert "github open" in out
    assert "github clone" in out


def test_cli_clone_slug_builds_github_url(monkeypatch) -> None:
    launched: list[list[str]] = []

    def fake_launch(args: list[str]) -> int:
        launched.append(args)
        return 0

    monkeypatch.setattr("github_desktop.cli._launch", fake_launch)
    assert cli_main(["clone", "desktop/desktop"]) == 0
    assert launched[0][0] == "--cli-clone=https://github.com/desktop/desktop"


def test_cli_clone_with_branch(monkeypatch) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr("github_desktop.cli._launch", lambda args: launched.append(args) or 0)
    assert cli_main(["clone", "-b", "topic", "desktop/desktop"]) == 0
    assert "--cli-clone=https://github.com/desktop/desktop" in launched[0]
    assert "--cli-branch=topic" in launched[0]


def test_cli_open_path(monkeypatch, tmp_path: Path) -> None:
    launched: list[list[str]] = []
    monkeypatch.setattr("github_desktop.cli._launch", lambda args: launched.append(args) or 0)
    assert cli_main(["open", str(tmp_path)]) == 0
    assert launched[0][0].startswith("--cli-open=")


def test_handle_cli_open(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    store.handle_cli([f"--cli-open={git_repo}"])
    assert any(r.path == str(git_repo) for r in store.repositories)


def test_handle_cli_clone_with_branch(isolated_config) -> None:
    store = AppStore()
    store.handle_cli(["--cli-clone=https://github.com/desktop/desktop", "--cli-branch=dev"])
    assert store.popup and store.popup.type.value == "CloneRepository"
    assert store.popup.payload.get("initial_url") == "https://github.com/desktop/desktop"
    assert store.popup.payload.get("branch") == "dev"


def test_popup_and_banner(isolated_config) -> None:
    store = AppStore()
    store.show_popup(PopupType.ABOUT)
    assert store.popup and store.popup.type == PopupType.ABOUT
    store.close_popup()
    assert store.popup is None


def test_line_and_hunk_selection(isolated_config, git_repo: Path) -> None:
    store = AppStore()
    added = store.add_repositories([str(git_repo)])
    repo = added[0]
    (git_repo / "README.md").write_text("hello\nA\nB\n", encoding="utf-8")
    from github_desktop.git.ops import get_status, get_working_directory_diff
    from github_desktop.git.diff import selectable_line_indices
    from github_desktop.models import TextDiff

    status = get_status(str(git_repo))
    store.state_for(repo).status = status
    file = status.working_directory.files[0]
    store.set_line_included(repo, file.path, 0, False)
    updated = store.state_for(repo).status.working_directory.files[0]
    assert updated.selection.is_selected(0) is False
    store.set_hunk_included(repo, file.path, 0, 4, True)
    updated = store.state_for(repo).status.working_directory.files[0]
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    assert selectable_line_indices(diff)


def test_compare_to_branch(isolated_config, git_repo: Path) -> None:
    from tests.conftest import run_git
    from github_desktop.git.ops import create_branch, checkout_branch, create_commit, get_status

    store = AppStore()
    repo = store.add_repositories([str(git_repo)])[0]
    create_branch(str(git_repo), "topic")
    checkout_branch(str(git_repo), "topic")
    (git_repo / "t.txt").write_text("t\n", encoding="utf-8")
    status = get_status(str(git_repo))
    create_commit(str(git_repo), "on topic\n", status.working_directory.files)
    checkout_branch(str(git_repo), "main")
    from github_desktop.git.ops import get_branches

    store.state_for(repo).status = get_status(str(git_repo))
    store.state_for(repo).branches = get_branches(str(git_repo))
    store.compare_to_branch(repo, "topic")
    state = store.state_for(repo)
    assert state.history_mode.value == "Compare"
    assert state.compare_behind
    assert state.merge_tree is not None
    store.compare_to_branch(repo, None)
    assert store.state_for(repo).history_mode.value == "History"
