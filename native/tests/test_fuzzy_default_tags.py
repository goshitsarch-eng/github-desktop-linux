"""Desktop fuzzy-find, removeRemotePrefix, default-branch lookup, tags-to-push."""

from __future__ import annotations

from github_desktop.find_branch_name import find_remote_branch_name
from github_desktop.find_default_branch import (
    find_default_branch,
    is_forked_repository_contributing_to_parent,
)
from github_desktop.find_default_remote import find_default_remote
from github_desktop.fuzzy_find import filter_items, is_empty_or_whitespace, match
from github_desktop.models import (
    Branch,
    BranchType,
    ForkContributionTarget,
    GitHubRepository,
    Remote,
    Repository,
)
from github_desktop.remove_remote_prefix import remove_remote_prefix
from github_desktop.settings import Settings
from github_desktop.store import AppStore
from github_desktop.tags_to_push import (
    clear_tags_to_push,
    get_tags_to_push,
    store_tags_to_push,
    tags_to_push_key,
)
from github_desktop.ui.markdown import is_github_asset_video_url, markdown_to_pango


def _get_text(item: dict) -> list[str]:
    return list(item["text"])


_FUZZY_ITEMS = [
    {"id": "300", "text": ["add fix for ...", "opened 5 days ago by bob"]},
    {"id": "500", "text": ["add support", "#4653 opened 3 days ago by damaneice "]},
    {"id": "500", "text": ["add an awesome feature", "#7564 opened 10 days ago by ... "]},
]


def test_fuzzy_find_matches_desktop_table() -> None:
    by_number = match("4653", _FUZZY_ITEMS, _get_text)
    assert len(by_number) == 1
    assert "4653" in "".join(by_number[0].item["text"])

    by_author = match("damaneice", _FUZZY_ITEMS, _get_text)
    assert len(by_author) == 1
    assert "damaneice" in "".join(by_author[0].item["text"])

    by_title = match("awesome feature", _FUZZY_ITEMS, _get_text)
    assert len(by_title) == 1
    assert "awesome feature" in "".join(by_title[0].item["text"])

    assert match("$%^", _FUZZY_ITEMS, _get_text) == []
    assert is_empty_or_whitespace("  ")
    assert match("   ", _FUZZY_ITEMS, _get_text) == []
    assert filter_items("", _FUZZY_ITEMS, _get_text) == _FUZZY_ITEMS


def test_remove_remote_prefix_matches_desktop() -> None:
    assert remove_remote_prefix("origin/test") == "test"
    assert remove_remote_prefix("origin/test/name") == "test/name"
    assert remove_remote_prefix("name") is None


def test_branch_uses_remove_remote_prefix() -> None:
    remote = Branch("origin/test/name", "origin/other/ref", "abc", BranchType.REMOTE, remote="origin")
    assert remote.name_without_remote == "test/name"
    assert remote.upstream_without_remote == "other/ref"
    local = Branch("feature", None, "abc", BranchType.LOCAL)
    assert local.name_without_remote == "feature"
    assert local.upstream_without_remote is None


def test_find_default_remote_prefers_origin() -> None:
    github = Remote("github", "https://github.com/o/r.git")
    origin = Remote("origin", "https://github.com/o/r.git")
    assert find_default_remote([]) is None
    assert find_default_remote([github]) is github
    assert find_default_remote([github, origin]) is origin


def test_find_default_branch_prefers_tracking_then_name_then_remote() -> None:
    repo = Repository(1, "/tmp/r", "r")
    local_main = Branch("main", None, "aaa", BranchType.LOCAL)
    tracking = Branch("develop", "origin/main", "bbb", BranchType.LOCAL)
    remote = Branch("origin/main", None, "ccc", BranchType.REMOTE, remote="origin")
    assert (
        find_default_branch(repo, [local_main, tracking, remote], "origin", remote_head="main")
        is tracking
    )
    assert find_default_branch(repo, [local_main, remote], "origin", remote_head="main") is local_main
    assert find_default_branch(repo, [remote], "origin", remote_head="main") is remote
    named_tracking = Branch("main", "origin/main", "ddd", BranchType.LOCAL)
    other_tracking = Branch("topic", "origin/main", "eee", BranchType.LOCAL)
    assert (
        find_default_branch(
            repo, [other_tracking, named_tracking], "origin", remote_head="main"
        )
        is named_tracking
    )


def test_find_default_branch_uses_upstream_remote_for_forks() -> None:
    parent = GitHubRepository(
        name="r",
        owner="upstream-owner",
        html_url="https://github.com/upstream-owner/r",
        clone_url="https://github.com/upstream-owner/r.git",
    )
    fork = GitHubRepository(
        name="r",
        owner="me",
        html_url="https://github.com/me/r",
        clone_url="https://github.com/me/r.git",
        fork=True,
        parent=parent,
    )
    repo = Repository(1, "/tmp/r", "r", github=fork)
    assert is_forked_repository_contributing_to_parent(repo)
    origin_tracking = Branch("main", "origin/main", "aaa", BranchType.LOCAL)
    upstream_tracking = Branch("from-parent", "upstream/main", "bbb", BranchType.LOCAL)
    found = find_default_branch(
        repo,
        [origin_tracking, upstream_tracking],
        "origin",
        remote_head="main",
    )
    assert found is upstream_tracking
    self_target = Repository(
        2,
        "/tmp/r",
        "r",
        github=fork,
        workflow_preferences={"fork_target": ForkContributionTarget.SELF.value},
    )
    assert not is_forked_repository_contributing_to_parent(self_target)
    assert (
        find_default_branch(
            self_target,
            [origin_tracking, upstream_tracking],
            "origin",
            remote_head="main",
        )
        is origin_tracking
    )


def test_find_remote_branch_name_uses_upstream_when_remote_matches() -> None:
    github = GitHubRepository(
        name="r",
        owner="o",
        html_url="https://github.com/o/r",
        clone_url="https://github.com/o/r.git",
    )
    matching = Remote("origin", "https://github.com/o/r.git")
    fork_remote = Remote("origin", "https://github.com/fork/r.git")
    branch = Branch(
        "local-name",
        "origin/feature",
        "abc",
        BranchType.LOCAL,
        remote="origin",
        upstream_without_remote="feature",
    )
    assert find_remote_branch_name(branch, matching, github) == "feature"
    assert find_remote_branch_name(branch, fork_remote, github) == "local-name"
    assert find_remote_branch_name(None, matching, github) is None
    untracked = Branch("local-name", None, "abc", BranchType.LOCAL)
    assert find_remote_branch_name(untracked, matching, github) == "local-name"


def test_store_tags_to_push_persists_across_appstore(isolated_config, git_repo) -> None:
    repo = Repository(7, str(git_repo), "repo")
    settings = Settings()
    assert tags_to_push_key(repo) == "tags-to-push-7"
    store_tags_to_push(settings, repo, ["v1.0.0", "v1.0.1"])
    assert get_tags_to_push(settings, repo) == ["v1.0.0", "v1.0.1"]
    store_tags_to_push(settings, repo, [])
    assert get_tags_to_push(settings, repo) == []
    store_tags_to_push(settings, repo, ["v2"])
    clear_tags_to_push(settings, repo)
    assert get_tags_to_push(settings, repo) == []

    store = AppStore()
    added = store.add_repositories([str(git_repo)])[0]
    store.remember_tag_to_push(added, "v1.0.0")
    store.remember_tag_to_push(added, "v1.0.0")
    assert store.state_for(added).local_tags_to_push == ["v1.0.0"]
    reloaded = AppStore()
    loaded = reloaded.repositories[0]
    assert reloaded.state_for(loaded).local_tags_to_push == ["v1.0.0"]
    reloaded.forget_tag_to_push(loaded, "v1.0.0")
    assert reloaded.state_for(loaded).local_tags_to_push == []
    third = AppStore()
    assert third.state_for(third.repositories[0]).local_tags_to_push == []


def test_github_asset_video_filter() -> None:
    url = "https://user-images.githubusercontent.com/1/clip.mp4"
    assert is_github_asset_video_url(url)
    assert not is_github_asset_video_url("https://user-images.githubusercontent.com/1/clip.png")
    linked = markdown_to_pango(f"[clip]({url})")
    assert ">Video</a>" in linked
    assert url in linked
    auto = markdown_to_pango(url)
    assert ">Video</a>" in auto
    stripped = markdown_to_pango('<video src="https://example.com/x.mp4"></video>Hello')
    assert "<video" not in stripped
    assert "Hello" in stripped
