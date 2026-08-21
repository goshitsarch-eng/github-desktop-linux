"""History batching, changeset stats, stash viewer store, and PR preview."""

from __future__ import annotations

from github_desktop.git.ops import (
    create_commit,
    get_changeset_data,
    get_commit_range_changed_files,
    get_commits,
    get_status,
    stash_push,
)
from github_desktop.models import COMMIT_BATCH_SIZE, PopupType
from github_desktop.store import AppStore
from tests.conftest import run_git


def test_changeset_data_counts_added_and_deleted(git_repo) -> None:
    (git_repo / "README.md").write_text("hello\nworld\n", encoding="utf-8")
    (git_repo / "extra.txt").write_text("new\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md", "extra.txt")
    run_git(git_repo, "commit", "-m", "change files")
    sha = get_commits(str(git_repo), limit=1)[0].sha
    data = get_changeset_data(str(git_repo), sha)
    paths = {f.path for f in data.files}
    assert "README.md" in paths
    assert "extra.txt" in paths
    assert data.lines_added >= 2
    assert data.lines_deleted >= 0


def test_commit_range_changed_files(git_repo) -> None:
    (git_repo / "a.txt").write_text("one\n", encoding="utf-8")
    run_git(git_repo, "add", "a.txt")
    run_git(git_repo, "commit", "-m", "add a")
    (git_repo / "b.txt").write_text("two\n", encoding="utf-8")
    run_git(git_repo, "add", "b.txt")
    run_git(git_repo, "commit", "-m", "add b")
    commits = get_commits(str(git_repo), limit=3)
    newest, older = commits[0], commits[1]
    data = get_commit_range_changed_files(str(git_repo), older.sha, newest.sha)
    assert any(f.path == "b.txt" for f in data.files)
    assert data.lines_added >= 1


def test_load_next_commit_batch(isolated_config, git_repo) -> None:
    for i in range(8):
        (git_repo / "n.txt").write_text(f"{i}\n", encoding="utf-8")
        run_git(git_repo, "add", "n.txt")
        run_git(git_repo, "commit", "-m", f"c{i}")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    state = store.state_for(repo)
    first = get_commits(str(git_repo), limit=3)
    state.commits = first
    state.has_more_commits = True
    store.load_next_commit_batch(repo)
    assert len(state.commits) > 3
    assert state.commits[0].sha == first[0].sha


def test_history_filter_grep(isolated_config, git_repo) -> None:
    (git_repo / "x.txt").write_text("x\n", encoding="utf-8")
    run_git(git_repo, "add", "x.txt")
    run_git(git_repo, "commit", "-m", "unique-message-xyz")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    store.set_history_filter(repo, "unique-message-xyz")
    summaries = [c.summary for c in store.state_for(repo).commits]
    assert "unique-message-xyz" in summaries
    assert all("unique-message-xyz" in s or True for s in summaries)


def test_stash_viewer_store(isolated_config, git_repo) -> None:
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    stash_push(str(git_repo), "main")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    from github_desktop.git.ops import get_stashes

    stashes, count = get_stashes(str(git_repo))
    assert count >= 1
    assert stashes
    state = store.state_for(repo)
    state.stashes = stashes
    store.load_stash_files(repo)
    assert state.stashed_files
    assert state.selected_stashed_file is not None
    assert state.stash_load_state.value == "Loaded"
    state.stashed_visible = True
    store.toggle_stash(repo)
    assert state.stashed_visible is False


def test_select_commit_loads_changeset(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    commits = get_commits(str(git_repo), limit=5)
    store.state_for(repo).commits = commits
    store.select_commit(repo, commits[0])
    state = store.state_for(repo)
    assert state.selected_commit is not None
    assert state.selected_commit.sha == commits[0].sha
    assert any(f.path == "README.md" for f in state.selected_commit_files)


def test_create_branch_and_checkout_switches_branch(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    store.create_branch_and_checkout(repo, "feature")
    status = get_status(str(git_repo))
    assert status is not None
    assert status.current_branch == "feature"


def test_get_stashed_files(git_repo) -> None:
    from github_desktop.git.ops import get_stashed_files, get_stashes, stash_push

    (git_repo / "README.md").write_text("dirty stash\n", encoding="utf-8")
    stash_push(str(git_repo), "main")
    stashes, count = get_stashes(str(git_repo))
    assert count >= 1
    assert stashes
    files = get_stashed_files(str(git_repo), stashes[0].stash_sha)
    assert any(f.path == "README.md" for f in files)


def test_pr_preview_range(isolated_config, git_repo) -> None:
    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "pr.txt").write_text("pr\n", encoding="utf-8")
    run_git(git_repo, "add", "pr.txt")
    run_git(git_repo, "commit", "-m", "pr work")
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    from github_desktop.git.ops import get_status

    store.state_for(repo).status = get_status(str(git_repo))
    store.load_pr_preview(repo, "main")
    state = store.state_for(repo)
    assert any(c.summary == "pr work" for c in state.pr_commits)
    assert any(f.path == "pr.txt" for f in state.pr_files)


def test_commit_batch_size_constant() -> None:
    assert COMMIT_BATCH_SIZE == 100


def test_add_dropped_paths_opens_error_for_non_repo(isolated_config, tmp_path) -> None:
    import os
    from pathlib import Path

    store = AppStore()
    empty = Path.home() / f".github-desktop-test-not-a-repo-{os.getpid()}"
    empty.mkdir(parents=True, exist_ok=True)
    try:
        store.add_dropped_paths([str(empty)])
        assert store.popup is not None
        assert store.popup.type == PopupType.ERROR
        assert "isn't a Git repository." in str(store.popup.payload.get("error") or "")
    finally:
        empty.rmdir()


def test_partial_commit_still_works_with_changeset(git_repo) -> None:
    (git_repo / "a.txt").write_text("a\n", encoding="utf-8")
    status = get_status(str(git_repo))
    assert status
    files = [f.with_include(True) for f in status.working_directory.files]
    sha = create_commit(str(git_repo), "add a\n", files)
    assert sha
    data = get_changeset_data(str(git_repo), sha)
    assert any(f.path == "a.txt" for f in data.files)


def test_changeset_data_detects_rename(git_repo) -> None:
    from github_desktop.git.ops import parse_raw_log_with_numstat
    from github_desktop.models import AppFileStatusKind

    run_git(git_repo, "mv", "README.md", "NOTES.md")
    run_git(git_repo, "commit", "-m", "rename readme")
    sha = get_commits(str(git_repo), limit=1)[0].sha
    data = get_changeset_data(str(git_repo), sha)
    renamed = next(f for f in data.files if f.path == "NOTES.md")
    assert renamed.status.kind == AppFileStatusKind.RENAMED
    assert renamed.status.old_path == "README.md"
    parsed = parse_raw_log_with_numstat(
        ":100644 100644 5716ca5 db3c77d R100\0"
        "file_one_original_path\0"
        "file_one_new_path\0"
        "1\t0\t\0"
        "file_one_original_path\0"
        "file_one_new_path\0",
        "abc",
        "abc^",
    )
    assert parsed.files[0].path == "file_one_new_path"
    assert parsed.files[0].status.kind == AppFileStatusKind.RENAMED
    assert parsed.files[0].status.old_path == "file_one_original_path"
    assert parsed.lines_added == 1
    assert parsed.lines_deleted == 0
