"""End-to-end git operations against real repositories."""

from __future__ import annotations

from pathlib import Path

import pytest

from github_desktop.git.ops import (
    checkout_branch,
    clone_repository,
    create_branch,
    create_commit,
    create_tag,
    delete_local_branch,
    discard_paths,
    fetch,
    get_branches,
    get_changed_files,
    get_commits,
    get_remotes,
    get_status,
    get_working_directory_diff,
    init_repository,
    merge,
    push,
    rename_branch,
    reset,
    revert,
    stash_pop,
    stash_push,
    undo_commit,
)
from github_desktop.models import AppFileStatusKind, DiffSelectionType, MergeResult, TextDiff
from tests.conftest import run_git


def test_status_untracked_and_modified(git_repo: Path) -> None:
    (git_repo / "new.txt").write_text("n\n", encoding="utf-8")
    (git_repo / "README.md").write_text("hello world\n", encoding="utf-8")
    status = get_status(str(git_repo))
    assert status is not None
    assert status.current_branch == "main"
    kinds = {f.path: f.status.kind for f in status.working_directory.files}
    assert kinds["new.txt"] == AppFileStatusKind.UNTRACKED
    assert kinds["README.md"] == AppFileStatusKind.MODIFIED


def test_commit_selected_files_only(git_repo: Path) -> None:
    (git_repo / "a.txt").write_text("a\n", encoding="utf-8")
    (git_repo / "b.txt").write_text("b\n", encoding="utf-8")
    status = get_status(str(git_repo))
    assert status
    files = []
    for f in status.working_directory.files:
        if f.path == "a.txt":
            files.append(f.with_include(True))
        else:
            files.append(f.with_include(False))
    sha = create_commit(str(git_repo), "add a\n", files)
    assert sha
    status2 = get_status(str(git_repo))
    remaining = {f.path for f in status2.working_directory.files}
    assert "b.txt" in remaining
    assert "a.txt" not in remaining
    commits = get_commits(str(git_repo), limit=5)
    assert commits[0].summary == "add a"


def test_diff_contains_added_line(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("hello\nsecond\n", encoding="utf-8")
    status = get_status(str(git_repo))
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, TextDiff)
    assert any(line.text.startswith("+second") for hunk in diff.hunks for line in hunk.lines)


def test_branch_create_rename_delete_checkout(git_repo: Path) -> None:
    create_branch(str(git_repo), "topic")
    checkout_branch(str(git_repo), "topic")
    status = get_status(str(git_repo))
    assert status and status.current_branch == "topic"
    rename_branch(str(git_repo), "topic", "feature")
    checkout_branch(str(git_repo), "feature")
    names = {b.name for b in get_branches(str(git_repo))}
    assert "feature" in names
    checkout_branch(str(git_repo), "main")
    delete_local_branch(str(git_repo), "feature")
    names = {b.name for b in get_branches(str(git_repo))}
    assert "feature" not in names


def test_stash_roundtrip(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("stashed\n", encoding="utf-8")
    stash_push(str(git_repo), "main")
    status = get_status(str(git_repo))
    assert status and not status.working_directory.files
    from github_desktop.git.ops import get_stashes

    entries, total = get_stashes(str(git_repo))
    assert total >= 1
    assert entries and entries[0].branch_name == "main"
    stash_pop(str(git_repo), entries[0].name)
    status = get_status(str(git_repo))
    assert any(f.path == "README.md" for f in status.working_directory.files)


def test_merge_and_up_to_date(git_repo: Path) -> None:
    create_branch(str(git_repo), "other")
    checkout_branch(str(git_repo), "other")
    (git_repo / "other.txt").write_text("x\n", encoding="utf-8")
    run_git(git_repo, "add", "other.txt")
    run_git(git_repo, "commit", "-m", "other")
    checkout_branch(str(git_repo), "main")
    result = merge(str(git_repo), "other")
    assert result == MergeResult.SUCCESS
    assert (git_repo / "other.txt").exists()
    assert merge(str(git_repo), "other") == MergeResult.ALREADY_UP_TO_DATE


def test_merge_conflicts(git_repo: Path) -> None:
    create_branch(str(git_repo), "left")
    create_branch(str(git_repo), "right")
    checkout_branch(str(git_repo), "left")
    (git_repo / "README.md").write_text("left\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "left")
    checkout_branch(str(git_repo), "right")
    (git_repo / "README.md").write_text("right\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "right")
    result = merge(str(git_repo), "left")
    assert result == MergeResult.FAILED
    status = get_status(str(git_repo))
    assert status and status.merge_head_found
    assert any(f.status.kind == AppFileStatusKind.CONFLICTED for f in status.working_directory.files)


def test_undo_commit_keeps_changes(git_repo: Path) -> None:
    (git_repo / "x.txt").write_text("x\n", encoding="utf-8")
    status = get_status(str(git_repo))
    files = [f.with_include(True) for f in status.working_directory.files]
    create_commit(str(git_repo), "add x\n", files)
    undo_commit(str(git_repo))
    status = get_status(str(git_repo))
    assert any(f.path == "x.txt" for f in status.working_directory.files)
    cached = run_git(git_repo, "diff", "--cached", "--name-only").stdout
    assert "x.txt" not in cached
    assert (git_repo / "x.txt").exists()


def test_undo_first_commit_restores_deleted_files(tmp_path: Path) -> None:
    repo = tmp_path / "first"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    run_git(repo, "config", "user.name", "Test User")
    run_git(repo, "config", "user.email", "test@example.com")
    (repo / "only.txt").write_text("only\n", encoding="utf-8")
    run_git(repo, "add", "only.txt")
    run_git(repo, "commit", "-m", "first")
    (repo / "only.txt").unlink()
    undo_commit(str(repo))
    assert (repo / "only.txt").exists()
    status = get_status(str(repo))
    assert status
    assert status.current_tip is None
    assert any(f.path == "only.txt" for f in status.working_directory.files)


def test_discard_untracked_and_modified(git_repo: Path) -> None:
    (git_repo / "gone.txt").write_text("g\n", encoding="utf-8")
    (git_repo / "README.md").write_text("changed\n", encoding="utf-8")
    discard_paths(str(git_repo), ["gone.txt", "README.md"])
    assert not (git_repo / "gone.txt").exists()
    assert (git_repo / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_tag_and_log_files(git_repo: Path) -> None:
    commits = get_commits(str(git_repo), limit=1)
    create_tag(str(git_repo), "v1.0.0", commits[0].sha)
    from github_desktop.git.ops import get_all_tags

    tags = get_all_tags(str(git_repo))
    assert "v1.0.0" in tags
    files = get_changed_files(str(git_repo), commits[0].sha)
    assert any(f.path == "README.md" for f in files)


def test_clone_and_remotes(git_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "clone"
    clone_repository(str(git_repo), str(dest))
    remotes = get_remotes(str(dest))
    assert remotes and remotes[0].name == "origin"
    status = get_status(str(dest))
    assert status and status.current_branch == "main"


def test_init_empty_repo(tmp_path: Path) -> None:
    path = tmp_path / "fresh"
    init_repository(str(path), "trunk")
    status = get_status(str(path))
    assert status and status.current_branch == "trunk"


def test_revert_creates_new_commit(git_repo: Path) -> None:
    (git_repo / "z.txt").write_text("z\n", encoding="utf-8")
    run_git(git_repo, "add", "z.txt")
    run_git(git_repo, "commit", "-m", "add z")
    sha = get_commits(str(git_repo), limit=1)[0].sha
    revert(str(git_repo), sha)
    assert not (git_repo / "z.txt").exists()
    assert get_commits(str(git_repo), limit=1)[0].summary.lower().startswith("revert")


def test_clone_reports_initial_progress(git_repo: Path, tmp_path: Path) -> None:
    dest = tmp_path / "clone-progress"
    seen: list[tuple[str, float]] = []
    clone_repository(str(git_repo), str(dest), progress=lambda text, value: seen.append((text, value)))
    assert dest.is_dir()
    assert seen
    assert seen[0][1] == 0.0


def test_format_patch_and_trailers(git_repo: Path) -> None:
    from github_desktop.git.ops import format_patch, merge_trailers, parse_trailers, read_description, write_description

    (git_repo / "p.txt").write_text("p\n", encoding="utf-8")
    run_git(git_repo, "add", "p.txt")
    run_git(git_repo, "commit", "-m", "add p")
    commits = get_commits(str(git_repo), limit=2)
    patch = format_patch(str(git_repo), commits[1].sha, commits[0].sha)
    assert "add p" in patch or "p.txt" in patch
    merged = merge_trailers(str(git_repo), "summary\n\nbody\n", [("Co-authored-by", "Ada <ada@example.com>")])
    assert "Co-authored-by" in merged
    parsed = parse_trailers(str(git_repo), merged)
    assert any(token.lower() == "co-authored-by" for token, _value in parsed)
    write_description(str(git_repo), "A test repository")
    assert read_description(str(git_repo)) == "A test repository"


def test_is_tracked_by_lfs_unspecified(git_repo: Path) -> None:
    from github_desktop.git.ops import get_global_config_path, is_tracked_by_lfs

    assert is_tracked_by_lfs(str(git_repo), "README.md") is False


def test_get_global_config_path_creates_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from github_desktop.git.ops import get_global_config_path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path = get_global_config_path()
    assert "gitconfig" in path.lower()


def test_conflict_markers_and_credentials(git_repo: Path) -> None:
    from github_desktop.git.ops import (
        format_credential,
        get_files_with_conflict_markers,
        parse_credential,
    )

    (git_repo / "README.md").write_text("<<<<<<< HEAD\na\n=======\nb\n>>>>>>> topic\n", encoding="utf-8")
    counts = get_files_with_conflict_markers(str(git_repo))
    assert counts.get("README.md", 0) >= 1
    parsed = parse_credential("wwwauth[]=foo\nwwwauth[]=bar\nusername=octocat\n")
    assert parsed["wwwauth[0]"] == "foo"
    assert parsed["wwwauth[1]"] == "bar"
    assert parsed["username"] == "octocat"
    formatted = format_credential({"wwwauth[0]": "foo", "wwwauth[1]": "bar"})
    assert formatted == "wwwauth[]=foo\nwwwauth[]=bar\n"


def test_recent_branches_from_reflog(git_repo: Path) -> None:
    from github_desktop.git.ops import checkout_branch, create_branch, get_recent_branches

    create_branch(str(git_repo), "branch-1")
    checkout_branch(str(git_repo), "branch-1")
    create_branch(str(git_repo), "branch-2")
    checkout_branch(str(git_repo), "branch-2")
    create_branch(str(git_repo), "branch-3")
    checkout_branch(str(git_repo), "branch-3")
    recent = get_recent_branches(str(git_repo), 2)
    assert len(recent) == 2
    assert "branch-3" in recent
    assert "branch-2" in recent
    limited = get_recent_branches(str(git_repo), 10)
    assert "branch-1" in limited
    assert "branch-2" in limited


def test_binary_paths_and_fetch_refspec(git_repo: Path) -> None:
    from github_desktop.git.ops import fetch_refspec, get_binary_paths, get_cherry_pick_snapshot

    assert get_binary_paths(str(git_repo), "HEAD") == []
    assert get_cherry_pick_snapshot(str(git_repo)) is None
    fetch_refspec(str(git_repo), "origin", "refs/heads/main")


def test_get_and_update_remote_head(git_repo: Path, tmp_path: Path) -> None:
    from github_desktop.git.ops import get_remote_head, get_remote_url, update_remote_head

    dest = tmp_path / "clone"
    clone_repository(str(git_repo), str(dest))
    url = get_remote_url(str(dest), "origin")
    assert url
    parsed = url.rstrip("/")
    assert parsed.endswith("repo") or "repo" in parsed
    update_remote_head(str(dest), "origin")
    assert get_remote_head(str(dest), "origin") == "main"


def test_merge_head_helpers_and_submodules(git_repo: Path) -> None:
    from github_desktop.git.ops import (
        is_cherry_pick_head_found,
        is_merge_head_set,
        is_squash_msg_set,
        list_submodules,
        reset_submodule_paths,
    )

    assert is_merge_head_set(str(git_repo)) is False
    assert is_squash_msg_set(str(git_repo)) is False
    assert is_cherry_pick_head_found(str(git_repo)) is False
    assert list_submodules(str(git_repo)) == []
    reset_submodule_paths(str(git_repo), [])


def test_abort_git_process_kills_child() -> None:
    import subprocess
    import time

    from github_desktop.git.runner import abort_git_process

    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    abort_git_process(proc)
    for _ in range(20):
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    assert proc.poll() is not None


def test_discard_untracked_file_permanently(git_repo: Path) -> None:
    from github_desktop.git.ops import discard_working_files, get_status

    target = git_repo / "gone.txt"
    target.write_text("x\n", encoding="utf-8")
    status = get_status(str(git_repo))
    assert status is not None
    files = [f for f in status.working_directory.files if f.path == "gone.txt"]
    assert files
    discard_working_files(str(git_repo), files, move_to_trash=False)
    assert not target.exists()

