"""Desktop-parity git helpers: stash, tags, fast-forward, conflicts, merge-base."""

from __future__ import annotations

from pathlib import Path

from github_desktop.git.askpass import (
    GITHUB_RSA_FINGERPRINT,
    auto_answer,
    parse_askpass_prompt,
)
from github_desktop.git.ops import (
    check_patch,
    checkout_branch,
    create_branch,
    create_commit,
    create_desktop_stash_entry,
    create_tag,
    discard_paths,
    drop_desktop_stash_entry,
    fast_forward_branches,
    fetch_tags_to_push,
    find_forked_remotes_to_prune,
    format_as_local_ref,
    get_authors,
    get_branch_merge_base_changed_files,
    get_branch_merge_base_diff,
    get_branches_differing_from_upstream,
    get_branches_pointed_at,
    get_files_diff_text,
    get_index_changes,
    get_last_desktop_stash_entry_for_branch,
    get_merged_branches,
    get_rebase_snapshot,
    get_status,
    get_symbolic_ref,
    get_working_directory_diff,
    merge,
    move_stash_entry,
    rename_branch,
    stage_manual_resolution,
    stash_pop,
)
from github_desktop.models import (
    FORKED_REMOTE_PREFIX,
    AppFileStatusKind,
    Branch,
    BranchType,
    FileStatus,
    GitStatusEntry,
    IndexStatus,
    ManualConflictResolution,
    PullRequest,
    Remote,
    TextDiff,
    WorkingDirectoryFileChange,
    fork_pull_request_remote_name,
)
from tests.conftest import run_git


def test_askpass_parses_host_and_auto_accepts_github_rsa() -> None:
    prompt = (
        "The authenticity of host 'github.com (140.82.112.4)' can't be established.\n"
        f"RSA key fingerprint is {GITHUB_RSA_FINGERPRINT}."
    )
    parsed = parse_askpass_prompt(prompt)
    assert parsed.kind == "host"
    assert parsed.host == "github.com"
    assert auto_answer(parsed) == "yes"
    other = parse_askpass_prompt(
        "The authenticity of host 'evil.example (1.2.3.4)' can't be established.\n"
        "ED25519 key fingerprint is SHA256:abc."
    )
    assert other.kind == "host"
    assert auto_answer(other) is None
    key = parse_askpass_prompt("Enter passphrase for key '/home/me/.ssh/id_rsa': ")
    assert key.kind == "key" and key.key_path.endswith("id_rsa")
    user = parse_askpass_prompt("git@github.com's password: ")
    assert user.kind == "password" and user.username == "git@github.com"


def test_delete_most_recent_ssh_credential(isolated_config) -> None:
    from github_desktop import secrets
    from github_desktop.git.askpass import (
        SSH_SERVICE,
        delete_most_recent_ssh_credential,
        remove_most_recent_ssh_credential,
        set_most_recent_ssh_credential,
    )

    secrets.set_password(SSH_SERVICE, "/tmp/id_rsa", "wrong")
    set_most_recent_ssh_credential("/tmp/id_rsa")
    remove_most_recent_ssh_credential()
    assert secrets.get_password(SSH_SERVICE, "/tmp/id_rsa") == "wrong"
    set_most_recent_ssh_credential("/tmp/id_rsa")
    delete_most_recent_ssh_credential()
    assert secrets.get_password(SSH_SERVICE, "/tmp/id_rsa") is None


def test_git_ssh_auth_failure_deletes_recent_credential(isolated_config, monkeypatch) -> None:
    import subprocess

    import pytest

    from github_desktop import secrets
    from github_desktop.errors import GitError
    from github_desktop.git.askpass import SSH_SERVICE, set_most_recent_ssh_credential
    from github_desktop.git.runner import git

    secrets.set_password(SSH_SERVICE, "git@github.com", "bad")
    set_most_recent_ssh_credential("git@github.com")
    monkeypatch.setattr("github_desktop.git.runner.find_git", lambda: "/usr/bin/git")

    def fake_run(*_a, **_k):
        return subprocess.CompletedProcess(
            ["git", "fetch"],
            128,
            stdout=b"",
            stderr=b"Permission denied (publickey).\n",
        )

    monkeypatch.setattr("github_desktop.git.runner.subprocess.run", fake_run)
    with pytest.raises(GitError) as exc:
        git(["fetch"], "/tmp", name="fetch")
    assert exc.value.git_error == "SSHAuthenticationFailed"
    assert secrets.get_password(SSH_SERVICE, "git@github.com") is None


def test_forked_remote_prune_keeps_pr_and_branch_remotes() -> None:
    remotes = [
        Remote("origin", "https://github.com/desktop/desktop.git"),
        Remote(f"{FORKED_REMOTE_PREFIX}niik", "https://github.com/niik/desktop.git"),
        Remote(f"{FORKED_REMOTE_PREFIX}shiftkey", "https://github.com/shiftkey/desktop.git"),
    ]
    prs = [
        PullRequest(
            1, "pr", "", "", "niik", False, "topic", "abc", "main",
            "https://github.com/desktop/desktop/pull/1",
            head_clone_url="https://github.com/niik/desktop.git",
            head_owner="niik",
        )
    ]
    branches = [Branch("topic", f"{FORKED_REMOTE_PREFIX}shiftkey/topic", "def", BranchType.LOCAL)]
    pruned = find_forked_remotes_to_prune(remotes, prs, branches)
    assert {r.name for r in pruned} == set()
    pruned = find_forked_remotes_to_prune(remotes, [], [])
    assert {r.name for r in pruned} == {f"{FORKED_REMOTE_PREFIX}niik", f"{FORKED_REMOTE_PREFIX}shiftkey"}


def test_stash_overwrite_is_branch_scoped(git_repo: Path) -> None:
    repo = str(git_repo)
    (git_repo / "README.md").write_text("first\n", encoding="utf-8")
    assert create_desktop_stash_entry(repo, "main")
    first = get_last_desktop_stash_entry_for_branch(repo, "main")
    assert first is not None
    (git_repo / "README.md").write_text("second\n", encoding="utf-8")
    assert create_desktop_stash_entry(repo, "main")
    drop_desktop_stash_entry(repo, first.stash_sha)
    latest = get_last_desktop_stash_entry_for_branch(repo, "main")
    assert latest is not None
    assert latest.stash_sha != first.stash_sha
    stash_pop(repo, latest.name)
    assert (git_repo / "README.md").read_text(encoding="utf-8") == "second\n"


def test_move_stash_entry_on_rename(git_repo: Path) -> None:
    repo = str(git_repo)
    create_branch(repo, "topic")
    checkout_branch(repo, "topic")
    (git_repo / "README.md").write_text("stashed-on-topic\n", encoding="utf-8")
    assert create_desktop_stash_entry(repo, "topic")
    entry = get_last_desktop_stash_entry_for_branch(repo, "topic")
    assert entry is not None
    rename_branch(repo, "topic", "feature")
    move_stash_entry(repo, entry, "feature")
    assert get_last_desktop_stash_entry_for_branch(repo, "topic") is None
    moved = get_last_desktop_stash_entry_for_branch(repo, "feature")
    assert moved is not None
    assert moved.branch_name == "feature"


def test_index_changes_and_discard(git_repo: Path) -> None:
    repo = str(git_repo)
    (git_repo / "README.md").write_text("staged\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    (git_repo / "README.md").write_text("staged-and-unstaged\n", encoding="utf-8")
    changes = get_index_changes(repo)
    assert changes["README.md"] == IndexStatus.MODIFIED
    discard_paths(repo, ["README.md"])
    assert (git_repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert "README.md" not in get_index_changes(repo)


def test_check_patch_and_files_diff_text(git_repo: Path) -> None:
    repo = str(git_repo)
    (git_repo / "README.md").write_text("hello\nextra\n", encoding="utf-8")
    status = get_status(repo)
    file = next(f for f in status.working_directory.files if f.path == "README.md")
    diff = get_working_directory_diff(repo, file)
    assert isinstance(diff, TextDiff)
    text = get_files_diff_text(repo, [file])
    assert "+extra" in text
    assert check_patch(repo, "diff --git a/nope b/nope\n--- a/nope\n+++ b/nope\n@@ -0,0 +1 @@\n+x\n") is False


def test_merge_base_diff_and_pointed_at(git_repo: Path) -> None:
    repo = str(git_repo)
    create_branch(repo, "topic")
    checkout_branch(repo, "topic")
    (git_repo / "topic.txt").write_text("t\n", encoding="utf-8")
    run_git(git_repo, "add", "topic.txt")
    run_git(git_repo, "commit", "-m", "topic")
    checkout_branch(repo, "main")
    (git_repo / "README.md").write_text("hello\nmain\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "mainline")
    tip = run_git(git_repo, "rev-parse", "topic").stdout.strip()
    changed = get_branch_merge_base_changed_files(repo, "main", "topic", tip)
    assert changed is not None
    assert any(f.path == "topic.txt" for f in changed.files)
    diff = get_branch_merge_base_diff(repo, "topic.txt", "main", "topic", latest_sha=tip)
    assert isinstance(diff, TextDiff)
    pointed = get_branches_pointed_at(repo, "HEAD")
    assert pointed is not None
    assert "main" in pointed
    assert get_symbolic_ref(repo, "HEAD") == "refs/heads/main"
    merged = get_merged_branches(repo, "main")
    assert format_as_local_ref("main") not in merged


def test_fast_forward_local_branch(git_repo: Path) -> None:
    repo = str(git_repo)
    create_branch(repo, "topic")
    run_git(git_repo, "remote", "add", "origin", str(git_repo))
    run_git(git_repo, "update-ref", "refs/remotes/origin/topic", "HEAD")
    run_git(git_repo, "config", "branch.topic.remote", "origin")
    run_git(git_repo, "config", "branch.topic.merge", "refs/heads/topic")
    (git_repo / "README.md").write_text("hello\nff\n", encoding="utf-8")
    run_git(git_repo, "add", "README.md")
    run_git(git_repo, "commit", "-m", "ahead on main")
    run_git(git_repo, "update-ref", "refs/remotes/origin/topic", "HEAD")
    eligible = get_branches_differing_from_upstream(repo)
    assert any(b.ref == "refs/heads/topic" for b in eligible)
    fast_forward_branches(repo, eligible)
    topic_sha = run_git(git_repo, "rev-parse", "topic").stdout.strip()
    origin_sha = run_git(git_repo, "rev-parse", "refs/remotes/origin/topic").stdout.strip()
    assert topic_sha == origin_sha
    assert get_rebase_snapshot(repo) is None
    assert get_authors(repo, [topic_sha])[0].email == "test@example.com"


def test_fetch_tags_to_push_local_remote(git_repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    run_git(tmp_path, "init", "--bare", str(remote))
    run_git(git_repo, "remote", "add", "origin", str(remote))
    run_git(git_repo, "push", "-u", "origin", "main")
    create_tag(str(git_repo), "v1.0", run_git(git_repo, "rev-parse", "HEAD").stdout.strip())
    tags = fetch_tags_to_push(str(git_repo), "origin", "main")
    assert "v1.0" in tags


def test_delete_add_conflict_resolution(git_repo: Path) -> None:
    repo = str(git_repo)
    (git_repo / "gone.txt").write_text("keep\n", encoding="utf-8")
    run_git(git_repo, "add", "gone.txt")
    run_git(git_repo, "commit", "-m", "add gone")
    create_branch(repo, "delete-it")
    create_branch(repo, "keep-it")
    checkout_branch(repo, "delete-it")
    run_git(git_repo, "rm", "gone.txt")
    run_git(git_repo, "commit", "-m", "delete")
    checkout_branch(repo, "keep-it")
    (git_repo / "gone.txt").write_text("changed\n", encoding="utf-8")
    run_git(git_repo, "add", "gone.txt")
    run_git(git_repo, "commit", "-m", "modify")
    result = merge(repo, "delete-it")
    from github_desktop.models import MergeResult

    assert result == MergeResult.FAILED
    status = get_status(repo)
    conflicted = next(f for f in status.working_directory.files if f.path == "gone.txt")
    assert conflicted.status.kind == AppFileStatusKind.CONFLICTED
    stage_manual_resolution(repo, conflicted, ManualConflictResolution.THEIRS)
    status2 = get_status(repo)
    remaining = [f for f in status2.working_directory.files if f.path == "gone.txt" and f.status.is_conflicted]
    assert remaining == []


def test_fork_remote_name() -> None:
    assert fork_pull_request_remote_name("octocat") == "github-desktop-octocat"
    file = WorkingDirectoryFileChange("a", FileStatus(AppFileStatusKind.CONFLICTED, us=GitStatusEntry.DELETED, them=GitStatusEntry.MODIFIED))
    assert file.status.us == GitStatusEntry.DELETED


def test_rev_helpers_and_update_ref(git_repo: Path) -> None:
    from github_desktop.git.ops import (
        get_branch_ahead_behind,
        get_commits_between,
        get_commits_in_range,
        rev_range,
        rev_range_inclusive,
        rev_symmetric_difference,
        update_ref,
    )

    assert rev_range("abc", "def") == "abc..def"
    assert rev_range_inclusive("abc", "def") == "abc^..def"
    assert rev_symmetric_difference("abc", "def") == "abc...def"
    old = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    run_git(git_repo, "checkout", "-b", "topic")
    (git_repo / "topic.txt").write_text("topic\n", encoding="utf-8")
    run_git(git_repo, "add", "topic.txt")
    run_git(git_repo, "commit", "-m", "topic")
    new = run_git(git_repo, "rev-parse", "HEAD").stdout.strip()
    between = get_commits_between(str(git_repo), old, new)
    assert between is not None
    assert any(c.sha == new for c in between)
    ranged = get_commits_in_range(str(git_repo), rev_range(old, new))
    assert ranged == between
    branch = Branch("topic", "main", new, BranchType.LOCAL)
    ab = get_branch_ahead_behind(str(git_repo), branch)
    assert ab is not None
    assert ab.ahead == 1
    assert ab.behind == 0
    update_ref(str(git_repo), "refs/heads/topic", new, old, "rewind topic")
    assert run_git(git_repo, "rev-parse", "refs/heads/topic").stdout.strip() == old


def test_fill_credential_with_helper(git_repo: Path, tmp_path: Path) -> None:
    from github_desktop.git.ops import approve_credential, fill_credential, reject_credential

    helper = tmp_path / "cred-helper.sh"
    helper.write_text(
        "#!/bin/sh\n"
        "case \"$1\" in\n"
        "get) printf 'username=alice\\npassword=s3cret\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    helper.chmod(0o755)
    filled = fill_credential(
        {"protocol": "https", "host": "example.com"},
        str(git_repo),
        helper=str(helper),
    )
    assert filled.get("username") == "alice"
    assert filled.get("password") == "s3cret"
    stored = approve_credential(filled, str(git_repo), helper=str(helper))
    assert stored.get("username") == "alice"
    reject_credential(filled, str(git_repo), helper=str(helper))


def test_global_config_value_wrappers(tmp_path: Path, monkeypatch) -> None:
    from github_desktop.git.ops import (
        get_global_boolean_config_value,
        get_global_config_value,
        remove_global_config_value,
        set_global_config_value,
    )

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    set_global_config_value("desktop.testuser", "Ada")
    assert get_global_config_value("desktop.testuser") == "Ada"
    set_global_config_value("desktop.testflag", "true")
    assert get_global_boolean_config_value("desktop.testflag") is True
    remove_global_config_value("desktop.testuser")
    assert get_global_config_value("desktop.testuser") is None


def test_update_remote_url_retargets_origin_after_rename(git_repo: Path) -> None:
    from github_desktop.git.ops import add_remote, get_remotes, update_remote_url
    from github_desktop.models import GitHubRepository
    from github_desktop.remote_parsing import parse_remote

    add_remote(str(git_repo), "origin", "https://github.com/octocat/old.git")
    old = GitHubRepository(
        name="old",
        owner="octocat",
        html_url="https://github.com/octocat/old",
        clone_url="https://github.com/octocat/old.git",
    )
    renamed = GitHubRepository(
        name="new",
        owner="octocat",
        html_url="https://github.com/octocat/new",
        clone_url="https://github.com/octocat/new.git",
    )
    assert update_remote_url(str(git_repo), old, renamed) is True
    remotes = get_remotes(str(git_repo))
    parsed = parse_remote(remotes[0].url)
    assert parsed is not None
    assert parsed.owner == "octocat"
    assert parsed.name == "new"


def test_update_remote_url_skips_customized_and_ssh(git_repo: Path) -> None:
    from github_desktop.git.ops import add_remote, get_remotes, update_remote_url
    from github_desktop.models import GitHubRepository, Remote
    from github_desktop.remote_parsing import parse_remote

    add_remote(str(git_repo), "origin", "https://github.com/me/fork.git")
    recorded = GitHubRepository(
        name="old",
        owner="octocat",
        html_url="https://github.com/octocat/old",
        clone_url="https://github.com/octocat/old.git",
    )
    api_repo = GitHubRepository(
        name="new",
        owner="octocat",
        html_url="https://github.com/octocat/new",
        clone_url="https://github.com/octocat/new.git",
    )
    assert update_remote_url(str(git_repo), recorded, api_repo) is False
    fork = parse_remote(get_remotes(str(git_repo))[0].url)
    assert fork is not None
    assert fork.owner == "me"
    assert fork.name == "fork"

    ssh_remote = Remote(name="origin", url="git@github.com:octocat/old.git")
    assert update_remote_url(str(git_repo), recorded, api_repo, remotes=[ssh_remote]) is False
