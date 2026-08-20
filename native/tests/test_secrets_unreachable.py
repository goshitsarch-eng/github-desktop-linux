"""Secret-scanning push output and unreachable-commit selection."""

from __future__ import annotations

from github_desktop.errors import extract_secret_scanning_results, remote_message
from github_desktop.store import AppStore, _commits_are_contiguous
from github_desktop.git.ops import get_commits
from tests.conftest import run_git


SAMPLE = """
remote: —— GitHub Personal Access Token ——————————————————————————————————
remote:   locations:
remote:   - commit: abcdefabcdefabcdefabcdefabcdefabcdefabcd
remote:     path: config.env:12
remote:   https://github.com/example/repo/security/secret-scanning/unblock-secret/ABC123
remote:  ——
"""


def test_extract_secret_scanning_results() -> None:
    secrets = extract_secret_scanning_results(SAMPLE)
    assert secrets
    assert "Personal Access Token" in secrets[0].description
    assert secrets[0].locations
    assert secrets[0].locations[0].path == "config.env"
    assert secrets[0].locations[0].line_number == 12
    assert secrets[0].bypass_url.endswith("ABC123")


def test_remote_message_strips_prefix() -> None:
    assert remote_message("remote: hello\nnot remote\nremote: world") == "hello\nworld"


def test_noncontiguous_commits_are_unreachable(isolated_config, git_repo) -> None:
    for i in range(4):
        (git_repo / "n.txt").write_text(f"{i}\n", encoding="utf-8")
        run_git(git_repo, "add", "n.txt")
        run_git(git_repo, "commit", "-m", f"c{i}")
    commits = get_commits(str(git_repo), limit=5)
    # newest, skip one, then older — not contiguous
    selected = [commits[0], commits[2]]
    assert not _commits_are_contiguous(selected, commits)
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    state = store.state_for(repo)
    state.commits = commits
    store.select_commits(repo, selected)
    assert state.shas_in_diff == [commits[0].sha]
    assert commits[2].sha not in state.shas_in_diff
