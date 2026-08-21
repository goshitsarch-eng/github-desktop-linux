"""Desktop-parity checkout, revert, LFS progress, status, and email tests."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.ops import (
    checkout_branch,
    clone_repository,
    create_branch,
    fetch,
    get_commits,
    get_status,
    is_co_authored_by_trailer,
    revert,
)
from github_desktop.git.progress import GitLFSProgressParser, create_lfs_progress_file, format_bytes
from github_desktop.models import Account, AccountEmail, AppFileStatusKind, Branch, BranchType
from tests.conftest import run_git


def test_checkout_remote_creates_local_tracking_branch(git_repo: Path, tmp_path: Path) -> None:
    create_branch(str(git_repo), "remote-only")
    checkout_branch(str(git_repo), "remote-only")
    (git_repo / "r.txt").write_text("r\n", encoding="utf-8")
    run_git(git_repo, "add", "r.txt")
    run_git(git_repo, "commit", "-m", "on remote-only")
    checkout_branch(str(git_repo), "main")
    dest = tmp_path / "clone"
    clone_repository(str(git_repo), str(dest))
    try:
        run_git(dest, "branch", "-D", "remote-only")
    except Exception:
        pass
    fetch(str(dest), "origin")
    remote = Branch("origin/remote-only", None, "unused", BranchType.REMOTE, remote="origin")
    checkout_branch(str(dest), remote)
    status = get_status(str(dest))
    assert status and status.current_branch == "remote-only"


def test_revert_merge_commit_with_mainline(git_repo: Path) -> None:
    create_branch(str(git_repo), "topic")
    checkout_branch(str(git_repo), "topic")
    (git_repo / "t.txt").write_text("t\n", encoding="utf-8")
    run_git(git_repo, "add", "t.txt")
    run_git(git_repo, "commit", "-m", "topic")
    checkout_branch(str(git_repo), "main")
    run_git(git_repo, "merge", "--no-ff", "topic", "-m", "merge topic")
    merge_commit = get_commits(str(git_repo), limit=1)[0]
    assert merge_commit.is_merge_commit
    revert(str(git_repo), merge_commit.sha, mainline=1)
    latest = get_commits(str(git_repo), limit=1)[0]
    assert latest.summary.lower().startswith("revert")
    assert not (git_repo / "t.txt").exists()


def test_binary_conflict_omits_marker_count(git_repo: Path) -> None:
    create_branch(str(git_repo), "left")
    checkout_branch(str(git_repo), "left")
    (git_repo / "pic.bin").write_bytes(b"\x00\x01\x02\xff" * 16)
    run_git(git_repo, "add", "pic.bin")
    run_git(git_repo, "commit", "-m", "left bin")
    checkout_branch(str(git_repo), "main")
    create_branch(str(git_repo), "right")
    checkout_branch(str(git_repo), "right")
    (git_repo / "pic.bin").write_bytes(b"\xff\xfe\xfd\x00" * 16)
    run_git(git_repo, "add", "pic.bin")
    run_git(git_repo, "commit", "-m", "right bin")
    checkout_branch(str(git_repo), "main")
    run_git(git_repo, "merge", "left")
    run_git(git_repo, "merge", "right", check=False)
    status = get_status(str(git_repo))
    assert status and status.do_conflicted_files_exist
    conflicted = [f for f in status.working_directory.files if f.status.kind == AppFileStatusKind.CONFLICTED]
    assert conflicted
    pic = next(f for f in conflicted if f.path == "pic.bin")
    assert pic.status.conflict_marker_count is None


def test_lfs_progress_formats_iec_bytes(tmp_path: Path) -> None:
    parser = GitLFSProgressParser()
    event = parser.parse("download 1/2 512/1024 foo.bin")
    assert event.kind == "progress"
    assert "KiB" in event.text or "B" in event.text
    assert "Downloading foo.bin" in event.text
    path = create_lfs_progress_file()
    assert Path(path).is_file()
    assert Path(path).name.startswith("GitHubDesktop-lfs-progress-")
    Path(path).unlink()
    assert format_bytes(1024, 1) == "1.0 KiB"


def test_is_co_authored_by_trailer() -> None:
    assert is_co_authored_by_trailer(("Co-authored-by", "Ada <ada@example.com>"))
    assert is_co_authored_by_trailer("co-authored-by")
    assert not is_co_authored_by_trailer(("Signed-off-by", "Ada <ada@example.com>"))


def test_preferred_email_public_primary() -> None:
    from github_desktop.email import is_attributable_email_for, lookup_preferred_email

    account = Account(
        login="niik",
        endpoint="https://api.github.com",
        token="x",
        id=123,
        emails=[
            AccountEmail("secret@company.com", primary=True, verified=True, visibility="private"),
            AccountEmail("niik@users.noreply.github.com", verified=True),
            AccountEmail("public@github.com", primary=False, verified=True, visibility="public"),
        ],
    )
    assert lookup_preferred_email(account) == "niik@users.noreply.github.com"
    public_primary = Account(
        login="niik",
        endpoint="https://api.github.com",
        token="x",
        id=123,
        emails=[
            AccountEmail("public@github.com", primary=True, verified=True, visibility="public"),
            AccountEmail("niik@users.noreply.github.com", verified=True),
        ],
    )
    assert lookup_preferred_email(public_primary) == "public@github.com"
    assert is_attributable_email_for(account, "secret@company.com")
    unverified = Account(
        login="niik",
        endpoint="https://api.github.com",
        token="x",
        id=123,
        emails=[AccountEmail("hidden@example.com", verified=False)],
    )
    assert not is_attributable_email_for(unverified, "hidden@example.com")


def test_dds_decode_uncompressed() -> None:
    from github_desktop.ui.dds import decode_dds_rgba
    import struct

    # 1x1 uncompressed RGB888 DDS
    header = bytearray(128)
    struct.pack_into("<I", header, 0, 0x20534444)
    struct.pack_into("<I", header, 4, 124)
    struct.pack_into("<I", header, 12, 1)  # height
    struct.pack_into("<I", header, 16, 1)  # width
    struct.pack_into("<I", header, 84, 0x40)  # DDPF_RGB
    struct.pack_into("<I", header, 92, 24)
    struct.pack_into("<I", header, 96, 0x000000FF)
    struct.pack_into("<I", header, 100, 0x0000FF00)
    struct.pack_into("<I", header, 104, 0x00FF0000)
    data = bytes(header) + bytes([10, 20, 30])
    decoded = decode_dds_rgba(data)
    assert decoded is not None
    width, height, rgba = decoded
    assert (width, height) == (1, 1)
    assert rgba[0] == 10 and rgba[1] == 20 and rgba[2] == 30


def test_checkout_paths_resets_to_head_not_index(git_repo: Path) -> None:
    from github_desktop.git.ops import checkout_paths

    (git_repo / "README.md").write_text("staged\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    (git_repo / "README.md").write_text("workdir\n", encoding="utf-8")
    checkout_paths(str(git_repo), ["README.md"])
    assert (git_repo / "README.md").read_text(encoding="utf-8") == "hello\n"


def test_wide_line_classified_as_large_text(git_repo: Path) -> None:
    from github_desktop.git.ops import get_working_directory_diff
    from github_desktop.models import LargeTextDiff

    (git_repo / "README.md").write_text("x" * 6000 + "\n", encoding="utf-8")
    status = get_status(str(git_repo))
    assert status
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(str(git_repo), file)
    assert isinstance(diff, LargeTextDiff)
    assert diff.hunks
    assert any(len(line.text) > 5000 for hunk in diff.hunks for line in hunk.lines)
