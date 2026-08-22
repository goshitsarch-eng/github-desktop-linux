"""Desktop copy: banners, file status labels, clone empty list, menus, trash."""

from __future__ import annotations

from pathlib import Path

import pytest

from github_desktop.git.progress import format_bytes
from github_desktop.models import (
    AppFileStatusKind,
    Banner,
    BannerType,
    FileStatus,
    PopupType,
    map_status,
    path_label,
)
from github_desktop.store import AppStore
from github_desktop.ui.dialogs import _clone_list_empty_title
from github_desktop.ui.diff_view import _image_two_up_footer, _image_two_up_summary
from github_desktop.ui.menus import (
    FileDoesNotExistOnDiskLabel,
    TrashNameLabel,
    committed_file_context_items,
    is_safe_file_extension,
    view_on_github_label,
)
from github_desktop.ui.window import format_banner_text


def test_map_status_and_path_label() -> None:
    assert map_status(FileStatus(kind=AppFileStatusKind.UNTRACKED)) == "New"
    assert map_status(FileStatus(kind=AppFileStatusKind.NEW)) == "New"
    resolved = FileStatus(kind=AppFileStatusKind.CONFLICTED, conflict_marker_count=0)
    assert map_status(resolved) == "Resolved"
    conflicted = FileStatus(kind=AppFileStatusKind.CONFLICTED, conflict_marker_count=3)
    assert map_status(conflicted) == "Conflicted"
    renamed = FileStatus(kind=AppFileStatusKind.RENAMED, old_path="old.txt")
    assert path_label("new.txt", renamed) == "old.txt → new.txt"
    assert path_label("keep.txt", FileStatus(kind=AppFileStatusKind.MODIFIED)) == "keep.txt"


def test_format_bytes_unfixed_matches_desktop_two_up() -> None:
    assert format_bytes(1024, 1) == "1.0 KiB"
    assert format_bytes(1024, 2, False) == "1 KiB"
    assert format_bytes(1536, 2, False) == "1.5 KiB"


def test_success_banner_copy() -> None:
    merge = Banner(BannerType.SUCCESSFUL_MERGE, our_branch="main", their_branch="feature")
    assert format_banner_text(BannerType.SUCCESSFUL_MERGE, merge) == "Successfully merged feature into main"
    merge_ours = Banner(BannerType.SUCCESSFUL_MERGE, our_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_MERGE, merge_ours) == "Successfully merged into main"
    rebase = Banner(BannerType.SUCCESSFUL_REBASE, target_branch="topic", their_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_REBASE, rebase) == "Successfully rebased topic onto main"
    cherry = Banner(BannerType.SUCCESSFUL_CHERRY_PICK, count=2, target_branch="main")
    assert format_banner_text(BannerType.SUCCESSFUL_CHERRY_PICK, cherry) == "Successfully copied 2 commits to main."
    squash = Banner(BannerType.SUCCESSFUL_SQUASH, count=1)
    assert format_banner_text(BannerType.SUCCESSFUL_SQUASH, squash) == "Successfully squashed 1 commit."
    merge_conflicts = Banner(BannerType.MERGE_CONFLICTS_FOUND, our_branch="main")
    assert format_banner_text(BannerType.MERGE_CONFLICTS_FOUND, merge_conflicts) == (
        "Resolve conflicts and commit to merge into main."
    )
    rebase_conflicts = Banner(BannerType.REBASE_CONFLICTS_FOUND, target_branch="topic")
    assert format_banner_text(BannerType.REBASE_CONFLICTS_FOUND, rebase_conflicts) == (
        "Resolve conflicts to continue rebasing topic."
    )
    cherry_conflicts = Banner(BannerType.CHERRY_PICK_CONFLICTS_FOUND, target_branch="main")
    assert format_banner_text(BannerType.CHERRY_PICK_CONFLICTS_FOUND, cherry_conflicts) == (
        "Resolve conflicts to continue cherry-picking onto main."
    )
    up_to_date = Banner(BannerType.BRANCH_ALREADY_UP_TO_DATE, our_branch="main", their_branch="origin/main")
    assert format_banner_text(BannerType.BRANCH_ALREADY_UP_TO_DATE, up_to_date) == (
        "main is already up to date with origin/main"
    )
    cherry_undone = Banner(BannerType.CHERRY_PICK_UNDONE, count=2, target_branch="main")
    assert "Cherry-pick undone. Successfully removed the 2 copied commits from main." in format_banner_text(
        BannerType.CHERRY_PICK_UNDONE, cherry_undone
    )
    squash_undone = Banner(BannerType.SQUASH_UNDONE, count=1)
    assert format_banner_text(BannerType.SQUASH_UNDONE, squash_undone) == "Squash of 1 commit undone."
    reorder = Banner(BannerType.SUCCESSFUL_REORDER, count=3)
    assert format_banner_text(BannerType.SUCCESSFUL_REORDER, reorder) == "Successfully reordered 3 commits."


def test_linux_file_and_view_menu_labels_match_desktop() -> None:
    from github_desktop.menu_update import (
        LINUX_FILE_QUIT_MNEMONIC,
        LINUX_GO_TO_SUMMARY_MNEMONIC,
        file_quit_label,
        go_to_summary_label,
    )

    assert LINUX_FILE_QUIT_MNEMONIC == "E&xit"
    assert file_quit_label() == "Exit"
    assert LINUX_GO_TO_SUMMARY_MNEMONIC == "Go to &Summary"
    assert go_to_summary_label() == "Go to Summary"


def test_linux_branch_group_labels_and_compare_placeholder() -> None:
    from github_desktop.models import Branch, BranchType
    from github_desktop.ui.branches import (
        branch_group_label,
        compare_placeholder_text,
        group_branches,
    )

    assert branch_group_label("default") == "Default branch"
    assert branch_group_label("recent") == "Recent branches"
    assert branch_group_label("other") == "Other branches"
    assert compare_placeholder_text(has_non_fork_branch=False, comparing=False) == "No branches to compare"
    assert compare_placeholder_text(has_non_fork_branch=True, comparing=False) == "Select branch to compare…"
    assert compare_placeholder_text(has_non_fork_branch=True, comparing=True) == "Filter branches"
    fork = Branch("github-desktop-octocat/topic", None, "abc", BranchType.REMOTE)
    extra = Branch("topic", None, "def", BranchType.LOCAL)
    titles = [title for title, items in group_branches([fork, extra], current=None, default_name=None, recent_names=[])]
    assert titles == ["Other branches"]
    assert [b.name for _title, items in group_branches([fork, extra], current=None, default_name=None, recent_names=[]) for b in items] == ["topic"]


def test_linux_no_repositories_and_toolbar_labels_match_desktop() -> None:
    from github_desktop.ui.menus import (
        ADD_EXISTING_REPOSITORY_FROM_LOCAL_DRIVE,
        CREATE_NEW_REPOSITORY_ON_LOCAL_DRIVE,
        REPOSITORY_TOOLBAR_DESCRIPTION,
        repository_toolbar_title,
    )

    assert CREATE_NEW_REPOSITORY_ON_LOCAL_DRIVE == "Create a New Repository on your local drive…"
    assert ADD_EXISTING_REPOSITORY_FROM_LOCAL_DRIVE == "Add an Existing Repository from your local drive…"
    assert REPOSITORY_TOOLBAR_DESCRIPTION == "Current repository"
    assert repository_toolbar_title() == "No repositories"
    assert repository_toolbar_title(has_repositories=True) == "Select a repository"
    assert repository_toolbar_title(selected_name="desktop") == "desktop"
    assert repository_toolbar_title(cloning_name="desktop") == "Cloning desktop…"
    assert repository_toolbar_title(cloning_name="desktop", cloning_percent=40) == "Cloning desktop… 40%"


def test_author_input_and_diff_options_linux_copy() -> None:
    from github_desktop.models import Author
    from github_desktop.ui.author_input import (
        AUTHOR_INPUT_PLACEHOLDER,
        CO_AUTHORS_LABEL,
        author_handle_aria_label,
        author_handle_title,
        get_display_text_for_author,
        get_full_text_for_author,
        is_known_author,
    )
    from github_desktop.ui.diff_view import diff_options_label
    from github_desktop.ui.menus import (
        UPDATE_EMAIL_LABEL,
        YOUR_ACCOUNT_EMAILS,
        git_config_popover_copy,
        git_config_settings_name,
        open_git_settings_label,
    )

    assert CO_AUTHORS_LABEL == "Co-Authors"
    assert AUTHOR_INPUT_PLACEHOLDER == "@username"
    assert diff_options_label() == "Diff Options"
    assert open_git_settings_label() == "Open git settings"
    assert git_config_settings_name() == "options"
    assert YOUR_ACCOUNT_EMAILS == "Your Account Emails"
    assert UPDATE_EMAIL_LABEL == "Update email"
    assert git_config_popover_copy(local=False) == (
        "You can update your global git configuration  in your git options."
    )
    assert git_config_popover_copy(local=True) == (
        "You can update your local git configuration for your repository in your repository settings."
    )
    known = Author(name="The Octocat", email="octocat@github.com", username="octocat")
    assert is_known_author(known)
    assert get_display_text_for_author(known) == "@octocat"
    assert get_full_text_for_author(known) == "@octocat (The Octocat)"
    assert author_handle_title(known) is None
    nameless = Author(name="Jane Doe", email="jane@example.com")
    assert get_display_text_for_author(nameless) == "Jane Doe"
    unknown = Author(name="nobody", email="", username="nobody", unknown=True, state="error")
    assert get_display_text_for_author(unknown) == "@nobody"
    assert author_handle_title(unknown) == "Could not find user with username nobody"
    assert "user not found" in author_handle_aria_label(unknown)
    searching = Author(name="hubot", email="", username="hubot", unknown=True, state="searching")
    assert author_handle_title(searching) == "Searching for @hubot"
    assert "press backspace or delete to remove" in author_handle_aria_label(searching)


def test_commit_message_avatar_warning_type_and_aria() -> None:
    from github_desktop.ui.menus import (
        commit_message_avatar_aria_label,
        commit_message_avatar_choose_local_email_copy,
        commit_message_avatar_email_leading_text,
        commit_message_avatar_warning_type,
        committing_as_title,
    )

    assert commit_message_avatar_warning_type(
        email="dev@example.com",
        repo_rules_enabled=True,
        email_failures_status="fail",
        misattributed=True,
    ) == "disallowedEmail"
    assert commit_message_avatar_warning_type(
        email="dev@example.com",
        repo_rules_enabled=True,
        email_failures_status="bypass",
        misattributed=False,
    ) == "disallowedEmail"
    assert commit_message_avatar_warning_type(
        email="dev@example.com",
        repo_rules_enabled=False,
        email_failures_status="fail",
        misattributed=True,
    ) == "misattribution"
    assert commit_message_avatar_warning_type(
        email="dev@example.com",
        repo_rules_enabled=False,
        email_failures_status="pass",
        misattributed=False,
    ) == "none"
    assert commit_message_avatar_aria_label("none") == "View commit author information"
    assert commit_message_avatar_aria_label("misattribution") == (
        "Commit may be misattributed. View warning."
    )
    assert commit_message_avatar_aria_label("disallowedEmail") == (
        "Email address is disallowed. View warning."
    )
    assert commit_message_avatar_email_leading_text("a@b.com") == (
        "The email in your global Git config (a@b.com)"
    )
    assert "also choose" in commit_message_avatar_choose_local_email_copy(has_emails=True)
    assert committing_as_title(name="Ada", email="a@b.com") == "Committing as Ada"
    assert committing_as_title(name=None, email="a@b.com") == "Committing with a@b.com"
    assert committing_as_title(name=None, email=None) == "Unknown user"


def test_unknown_author_live_search_and_user_hits() -> None:
    from types import SimpleNamespace

    from github_desktop.models import Author
    from github_desktop.ui.author_input import (
        apply_unknown_author_search_result,
        author_from_user_hit,
        get_email_address_for_user,
        is_known_author,
        unknown_author_from_username,
        update_unknown_author,
    )
    from github_desktop.ui.autocompletion import (
        SEARCH_FOR_USER,
        CoAuthorAutocompletionProvider,
        autocomplete_item_filter,
        get_user_autocompletion_items,
        user_hit_display,
    )

    searching = unknown_author_from_username("hubot")
    assert searching.unknown is True
    assert searching.state == "searching"
    found = author_from_user_hit(
        {
            "kind": "known-user",
            "username": "hubot",
            "name": "Hubot",
            "email": "",
            "endpoint": "https://api.github.com",
        }
    )
    assert is_known_author(found)
    assert found.email == "hubot@users.noreply.github.com"
    assert get_email_address_for_user({"email": "a@b.com", "username": "x"}) == "a@b.com"
    resolved = apply_unknown_author_search_result([searching], searching, found)
    assert resolved[0].name == "Hubot"
    assert is_known_author(resolved[0])
    errored = apply_unknown_author_search_result([searching], searching, None)
    assert errored[0].state == "error"
    assert errored[0].unknown is True
    leftover = update_unknown_author(
        [Author(name="octocat", email="o@x", username="octocat")],
        Author(name="hubot", email="", username="hubot", unknown=True, state="error"),
    )
    assert leftover[0].username == "octocat"

    state = SimpleNamespace(
        mentionables=[{"login": "octocat", "name": "The Octocat", "email": "octocat@github.com"}],
        mentions=["octocat"],
    )
    known_only = get_user_autocompletion_items(state, "oc", include_unknown_user=False)
    assert [item["username"] for item in known_only] == ["octocat"]
    with_unknown = CoAuthorAutocompletionProvider().get_autocompletion_items(state, "nobody")
    assert any(item.get("kind") == "unknown-user" and item["username"] == "nobody" for item in with_unknown)
    assert SEARCH_FOR_USER in user_hit_display({"kind": "unknown-user", "username": "nobody"})
    assert autocomplete_item_filter(known_only[0], [Author(name="The Octocat", email="e", username="octocat")]) is False
    assert autocomplete_item_filter({"kind": "unknown-user", "username": "nobody"}, []) is True


def test_no_changes_editor_linux_copy_and_availability() -> None:
    from github_desktop.ui.menus import (
        OPEN_THE_REPOSITORY_IN_YOUR_EXTERNAL_EDITOR,
        SELECT_YOUR_EDITOR_IN_OPTIONS,
        is_external_editor_available,
        open_in_editor_label,
    )

    assert OPEN_THE_REPOSITORY_IN_YOUR_EXTERNAL_EDITOR == "Open the repository in your external editor"
    assert SELECT_YOUR_EDITOR_IN_OPTIONS == "Select your editor in Options"
    assert is_external_editor_available(use_custom_editor=False, selected_external_editor=None) is False
    assert is_external_editor_available(use_custom_editor=True, selected_external_editor=None) is True
    assert is_external_editor_available(use_custom_editor=False, selected_external_editor="Visual Studio Code") is True
    assert open_in_editor_label("Visual Studio Code") == "Open in Visual Studio Code"
    assert open_in_editor_label(None) == "Open in external editor"


def test_branch_toolbar_linux_copy_matches_desktop() -> None:
    from github_desktop.ui.menus import (
        BRANCH_TOOLBAR_DESCRIPTION,
        CURRENTLY_ON_A_DETACHED_HEAD,
        DETACHED_HEAD_DESCRIPTION,
        REBASING_BRANCH_DESCRIPTION,
        REFRESHING_REPOSITORY,
        branch_toolbar_chrome,
    )

    assert BRANCH_TOOLBAR_DESCRIPTION == "Current branch"
    assert DETACHED_HEAD_DESCRIPTION == "Detached HEAD"
    assert REBASING_BRANCH_DESCRIPTION == "Rebasing branch"
    assert REFRESHING_REPOSITORY == "Refreshing repository"
    assert CURRENTLY_ON_A_DETACHED_HEAD == "Currently on a detached HEAD"
    title, description, tooltip, sensitive = branch_toolbar_chrome(branch_name="main", current_tip="abcdef1")
    assert (title, description, tooltip, sensitive) == ("main", "Current branch", "main", True)
    title, description, tooltip, sensitive = branch_toolbar_chrome(branch_name="topic", current_tip=None)
    assert title == "topic"
    assert description == "Current branch"
    assert tooltip == "Current branch is topic"
    title, description, tooltip, sensitive = branch_toolbar_chrome(current_tip="abcdef1234567")
    assert title == "On abcdef1"
    assert description == "Detached HEAD"
    assert tooltip == "Currently on a detached HEAD"
    title, description, tooltip, sensitive = branch_toolbar_chrome(
        checkout=True, checkout_title="Checking out main", checkout_value=0.4
    )
    assert title == "main"
    assert description == "Checking out (40%)"
    assert tooltip == "Checking out main"
    assert sensitive is False
    title, description, tooltip, sensitive = branch_toolbar_chrome(rebasing_target="topic")
    assert (title, description, tooltip, sensitive) == ("topic", "Rebasing branch", "Rebasing topic", False)
    title, description, tooltip, _ = branch_toolbar_chrome(
        checkout=True, checkout_title="Refreshing repository", checkout_value=1
    )
    assert title == "Refreshing repository"
    assert description == "Checking out (100%)"
    title, description, tooltip, _ = branch_toolbar_chrome(
        checkout=True,
        checkout_title="Refreshing repository",
        checkout_value=1,
        checkout_target="main",
        checkout_description="Checking out",
    )
    assert title == "main"
    assert description == "Checking out (100%)"
    assert tooltip == "Checking out main"


def test_refresh_after_checkout_matches_desktop(isolated_config, git_repo: Path) -> None:
    from github_desktop.push_pull import CHECKING_OUT, REFRESHING_REPOSITORY
    from github_desktop.store import AppStore

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    seen: list[tuple] = []

    def fake_refresh(_repo, on_complete=None):
        seen.append(
            (
                store.progress_kind,
                store.progress_title,
                store.progress_description,
                store.progress_value,
                store.progress_target,
            )
        )
        if on_complete is not None:
            on_complete(None)

    store.refresh_repository = fake_refresh  # type: ignore[method-assign]
    store.refreshAfterCheckout(repo, "main")
    assert seen == [("checkout", REFRESHING_REPOSITORY, CHECKING_OUT, 1.0, "main")]
    assert store.progress_kind is None
    assert store.progress_title == ""
    assert store.progress_target == ""


def test_refresh_after_push_pull_shows_fast_forwarding(isolated_config, git_repo: Path) -> None:
    from github_desktop.push_pull import (
        FAST_FORWARDING_BRANCHES,
        HANG_ON,
        REFRESHING_REPOSITORY,
        network_progress_chrome,
        progressButton,
    )
    from github_desktop.store import AppStore

    label, subtitle, tooltip = network_progress_chrome(
        title=REFRESHING_REPOSITORY,
        description=FAST_FORWARDING_BRANCHES,
        value=0.9,
    )
    assert label == "Refreshing repository 90%"
    assert subtitle == FAST_FORWARDING_BRANCHES
    assert tooltip == FAST_FORWARDING_BRANCHES
    hang_label, hang_sub, hang_tip = progressButton(title="Pushing to origin")
    assert hang_label == "Pushing to origin"
    assert hang_sub == hang_tip == HANG_ON

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    seen: list[tuple] = []

    def fake_refresh(_repo, on_complete=None):
        seen.append((store.progress_kind, store.progress_title, store.progress_description))
        if on_complete is not None:
            on_complete(None)

    store.refresh_repository = fake_refresh  # type: ignore[method-assign]
    store._refresh_after_push_pull_fetch(repo)
    assert seen == [("generic", REFRESHING_REPOSITORY, FAST_FORWARDING_BRANCHES)]
    assert store.progress_kind is None


def test_fetch_remotes_after_push_matches_desktop(isolated_config, git_repo: Path, monkeypatch) -> None:
    import inspect

    from github_desktop.models import Remote
    from github_desktop.store import AppStore

    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    fetched: list[str] = []

    def fake_fetch(path: str, remote: str, **_kwargs) -> None:
        fetched.append(remote)

    monkeypatch.setattr("github_desktop.store.fetch", fake_fetch)
    monkeypatch.setattr("github_desktop.store.update_remote_head", lambda *_a, **_k: None)
    store.fetchRemotes(repo, [Remote(name="origin", url="https://example.com/r.git")])
    assert fetched == ["origin"]
    src = inspect.getsource(AppStore.push_repo)
    assert "fetch_remotes" in src
    assert "fast_forward_branches_for_repo" in src
    assert src.index("fetch_remotes") < src.index("fast_forward_branches_for_repo")


def test_clone_list_empty_copy() -> None:
    class Account:
        login = "hubot"
        friendly_endpoint = "GitHub.com"

    assert (
        _clone_list_empty_title(Account(), "desktop")
        == "Sorry, I can't find any repository matching desktop"
    )
    assert (
        _clone_list_empty_title(Account(), "")
        == "Looks like there are no repositories for hubot on GitHub.com."
    )


def test_image_two_up_copy() -> None:
    footer = _image_two_up_footer(None, b"x" * 1024)
    assert footer.startswith("W: 0px | H: 0px | Size: ")
    assert "KiB" in footer
    assert _image_two_up_summary(b"a" * 100, b"a" * 100) == "Diff: No size difference"
    bigger = _image_two_up_summary(b"a" * 1000, b"a" * 2000)
    assert bigger.startswith("Diff: +")
    assert "(200%)" in bigger


def test_committed_file_menu_missing_and_github_enterprise() -> None:
    assert is_safe_file_extension(".sh")
    assert view_on_github_label(enterprise=True) == "View on GitHub Enterprise"
    assert view_on_github_label(enterprise=False) == "View on GitHub"
    missing = committed_file_context_items(
        full_path="/tmp/missing.txt",
        relative_path="missing.txt",
        exists=False,
        editor_label="Open in external editor",
        on_reveal=lambda: None,
        on_open_editor=lambda: None,
        on_open_default=lambda: None,
        view_github_label="View on GitHub",
        on_view_github=lambda: None,
        view_github_enabled=False,
    )
    assert missing == [(FileDoesNotExistOnDiskLabel, missing[0][1], False)]
    present = committed_file_context_items(
        full_path="/tmp/file.txt",
        relative_path="file.txt",
        exists=True,
        editor_label="Open in Code",
        on_reveal=lambda: None,
        on_open_editor=lambda: None,
        on_open_default=lambda: None,
        view_github_label="View on GitHub Enterprise",
        on_view_github=lambda: None,
        view_github_enabled=False,
    )
    labels = [item[0] for item in present if item is not None]
    assert labels[0] == "Show in your File Manager"
    assert "Copy file path" in labels
    assert "Copy relative file path" in labels
    assert "View on GitHub Enterprise" in labels


def test_remove_repository_trash_failure_keeps_repo(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    monkeypatch.setattr("github_desktop.store.move_item_to_trash", lambda _path: False)
    store.remove_repository(repo, True)
    assert any(item.id == repo.id for item in store.repositories)
    assert store.popup is not None
    assert store.popup.type == PopupType.ERROR
    assert f"Failed to move the repository directory to {TrashNameLabel}." in store.popup.payload["error"]


def test_remove_repository_trash_success(isolated_config, git_repo, monkeypatch) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    repo = repos[0]
    monkeypatch.setattr("github_desktop.store.move_item_to_trash", lambda _path: True)
    store.remove_repository(repo, True)
    assert all(item.id != repo.id for item in store.repositories)
    assert git_repo.exists()


def test_commit_autocompletion_matches_desktop() -> None:
    from types import SimpleNamespace

    from github_desktop.ui.autocompletion import (
        SUMMARY_LENGTH_HINT,
        UNREACHABLE_COMMITS_LEARN_MORE,
        completion_insert_text,
        completion_matches,
        summary_length_hint,
        token_before_cursor,
        unreachable_commits_message,
    )
    from github_desktop.ui.emoji import matching_shortcodes

    assert token_before_cursor("Fix #12", 7) == "#12"
    assert token_before_cursor("hey @octo", 9) == "@octo"
    assert completion_insert_text("#42 Fix login") == "#42"
    assert completion_insert_text("@hubot") == "@hubot"
    assert completion_insert_text(":rocket:") == "🚀"
    state = SimpleNamespace(
        issues=[(1, "First"), (42, "Fix login"), (12, "Docs")],
        mentions=["octocat", "hubot"],
        mentionables=[{"login": "octocat", "name": "The Octocat"}],
        current_branch_protected=True,
        status=SimpleNamespace(current_branch="main"),
    )
    issues = completion_matches(state, "#1")
    assert "#12 Docs" in issues
    assert "#1 First" in issues
    assert "#42 Fix login" not in issues
    users = completion_matches(state, "@oc")
    assert any(item.startswith("@octocat") for item in users)
    assert ":tada:" in matching_shortcodes("tad")
    assert matching_shortcodes(":")
    assert summary_length_hint("x" * 51, True) == SUMMARY_LENGTH_HINT
    assert summary_length_hint("short", True) is None
    assert "not in the ancestry path" in unreachable_commits_message(unreachable_tab=True, count=2)
    assert "Learn more" not in unreachable_commits_message(unreachable_tab=False, count=1)
    assert "unreachable-commits.md" in UNREACHABLE_COMMITS_LEARN_MORE


def test_commit_warning_links_and_status_message() -> None:
    from types import SimpleNamespace

    from github_desktop.github.repo_rules import RepoRulesInfo
    from github_desktop.models import FoldoutType, GitHubRepository, PopupType, Repository
    from github_desktop.ui.autocompletion import (
        branch_protections_repo_rules_commit_warning_markups,
        committing_just_now_message,
        get_button_title,
        handle_commit_warning_uri,
        protected_branch_warning_markup,
        write_access_warning_markup,
    )

    github = GitHubRepository(
        name="hello",
        owner="octocat",
        html_url="https://github.com/octocat/hello",
        clone_url="https://github.com/octocat/hello.git",
        permissions="read",
    )
    repo = Repository(1, "/tmp/hello", "hello", github=github)
    fork = write_access_warning_markup(repo)
    assert fork is not None
    assert 'href="fork"' in fork
    assert "create a fork" in fork
    assert branch_protections_repo_rules_commit_warning_markups(repo, None) == [fork]

    state = SimpleNamespace(
        current_branch_protected=True,
        status=SimpleNamespace(current_branch="topic"),
        repo_rules=RepoRulesInfo(),
        ahead_behind=None,
    )
    assert branch_protections_repo_rules_commit_warning_markups(repo, state) == [fork]

    writable = Repository(
        1,
        "/tmp/hello",
        "hello",
        github=GitHubRepository(
            name="hello",
            owner="octocat",
            html_url="https://github.com/octocat/hello",
            clone_url="https://github.com/octocat/hello.git",
            permissions="write",
        ),
    )
    protected = protected_branch_warning_markup(state)
    assert protected is not None
    assert 'href="switch"' in protected
    assert "switch branches" in protected
    assert branch_protections_repo_rules_commit_warning_markups(writable, state) == [protected]

    signed_state = SimpleNamespace(
        current_branch_protected=False,
        status=SimpleNamespace(current_branch="topic"),
        repo_rules=RepoRulesInfo(signed_commits_required=True),
        ahead_behind=object(),
    )
    signed = branch_protections_repo_rules_commit_warning_markups(writable, signed_state)
    assert signed
    assert "Learn more about commit signing" in signed[0]
    assert 'href="rulesets"' in signed[0]

    assert committing_just_now_message("Fix login", "abc1234") == (
        "Committed Just now - Fix login (Sha: abc1234)"
    )
    assert get_button_title(committing=True, branch="main") == "Committing to main"
    assert get_button_title(amending=True, committing=False) == "Amend last commit"

    class Store:
        def __init__(self) -> None:
            self.popup = None
            self.foldout = None

        def show_popup(self, kind, **_kwargs):
            self.popup = kind

        def show_foldout(self, kind) -> None:
            self.foldout = kind

        selected_repository = None

    store = Store()
    assert handle_commit_warning_uri(store, "fork") is True
    assert store.popup == PopupType.CREATE_FORK
    assert handle_commit_warning_uri(store, "switch") is True
    assert store.foldout == FoldoutType.BRANCH


def test_refresh_issues_is_noop_without_github(isolated_config, git_repo) -> None:
    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    store.refresh_issues(repos[0])
    assert store.state_for(repos[0]).issues == []


def test_commit_summary_placeholder_matches_desktop() -> None:
    from github_desktop.models import (
        AppFileStatusKind,
        DiffSelection,
        DiffSelectionType,
        FileStatus,
        WorkingDirectoryFileChange,
        commit_summary_placeholder,
    )

    created = WorkingDirectoryFileChange(
        "src/app.py",
        FileStatus(kind=AppFileStatusKind.NEW),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    deleted = WorkingDirectoryFileChange(
        "gone.txt",
        FileStatus(kind=AppFileStatusKind.DELETED),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    modified = WorkingDirectoryFileChange(
        "readme.md",
        FileStatus(kind=AppFileStatusKind.MODIFIED),
        DiffSelection.from_initial_selection(DiffSelectionType.ALL),
    )
    excluded = WorkingDirectoryFileChange(
        "skip.py",
        FileStatus(kind=AppFileStatusKind.MODIFIED),
        DiffSelection.from_initial_selection(DiffSelectionType.NONE),
    )
    assert commit_summary_placeholder([created]) == "Create app.py"
    assert commit_summary_placeholder([deleted]) == "Delete gone.txt"
    assert commit_summary_placeholder([modified]) == "Update readme.md"
    assert commit_summary_placeholder([created, modified]) == "Summary (required)"
    assert commit_summary_placeholder([created], tutorial=True) == "Summary (required)"
    assert commit_summary_placeholder([created, excluded]) == "Create app.py"


def test_history_tokens_markup_links_issues() -> None:
    from github_desktop.text_tokens import Tokenizer, tokens_as_markup

    markup = tokens_as_markup(Tokenizer().tokenize("See https://example.com"))
    assert 'href="https://example.com"' in markup
    assert "See " in markup


def test_delete_oauth_token_skips_empty_token() -> None:
    from github_desktop.github.api import delete_oauth_token
    from github_desktop.models import Account

    account = Account(login="hubot", endpoint="https://api.github.com", token="")
    assert delete_oauth_token(account) is False


def test_get_discard_label_matches_desktop_linux() -> None:
    from github_desktop.git.diff import DiffRangeType
    from github_desktop.ui.diff_view import get_discard_label

    assert get_discard_label(DiffRangeType.ADDITIONS, 1) == "Discard added line…"
    assert get_discard_label(DiffRangeType.DELETIONS, 2) == "Discard removed lines…"
    assert get_discard_label(DiffRangeType.MIXED, 1, confirm=False) == "Discard modified line"
    assert get_discard_label(DiffRangeType.ADDITIONS, 2, confirm=False) == "Discard added lines"


def test_seamless_diff_switcher_loading_helpers() -> None:
    from github_desktop.models import BinaryDiff, TextDiff
    from github_desktop.ui.diff_view import (
        SlowDiffLoadingThreshold,
        isLoadingDiff,
        isLoadingSlow,
        is_loading_diff,
        is_seamless_file_loading,
        is_text_diff,
    )

    assert SlowDiffLoadingThreshold == 150
    assert is_loading_diff(None) is True
    assert isLoadingDiff is is_loading_diff
    assert is_seamless_file_loading(None, "README.md") is True
    assert is_seamless_file_loading(None, "") is False
    assert is_seamless_file_loading(None, "", loading=True) is True
    text = TextDiff()
    assert is_text_diff(text) is True
    assert is_loading_diff(text) is False
    assert is_loading_diff(text, file_contents=None) is True
    assert is_seamless_file_loading(text, "README.md") is False
    assert is_text_diff(BinaryDiff()) is False
    assert is_loading_diff(BinaryDiff()) is False
    assert isLoadingSlow(True, 149) is False
    assert isLoadingSlow(True, 150) is True
    assert isLoadingSlow(False, 999) is False


def test_open_pull_request_copy_matches_desktop() -> None:
    from github_desktop.models import ComputedAction
    from github_desktop.ui.dialogs import (
        COULD_NOT_FIND_DEFAULT_BRANCH,
        SELECT_A_BASE_BRANCH_ABOVE,
        THERE_ARE_NO_CHANGES,
        open_pull_request_no_changes_body,
        open_pull_request_ok_label,
        open_pull_request_ok_title,
        pull_request_merge_status_text,
    )

    assert THERE_ARE_NO_CHANGES == "There are no changes."
    assert COULD_NOT_FIND_DEFAULT_BRANCH.startswith("Could not find a default branch")
    assert SELECT_A_BASE_BRANCH_ABOVE == "Select a base branch above."
    assert open_pull_request_no_changes_body(
        has_merge_base=True, base="main", current="topic"
    ) == "main is up to date with all commits from topic."
    assert open_pull_request_no_changes_body(
        has_merge_base=False, base="main", current="topic"
    ) == "main and topic are entirely different commit histories."
    assert pull_request_merge_status_text(ComputedAction.LOADING).startswith("Checking mergeability")
    assert "These branches can be automatically merged." in pull_request_merge_status_text(
        ComputedAction.CLEAN
    )
    assert pull_request_merge_status_text(ComputedAction.CLEAN).startswith("Able to merge.")
    assert "Error checking merge status." in pull_request_merge_status_text(ComputedAction.INVALID)
    conflicts = pull_request_merge_status_text(ComputedAction.CONFLICTS)
    assert "Can't automatically merge." in conflicts
    assert "still create the pull request" in conflicts
    assert open_pull_request_ok_label(has_pull_request=False) == "Create pull request"
    assert open_pull_request_ok_label(has_pull_request=True) == "View pull request"
    assert open_pull_request_ok_title(has_pull_request=False) == "Create pull request on GitHub."
    assert (
        open_pull_request_ok_title(has_pull_request=True, enterprise=True)
        == "View pull request on GitHub Enterprise."
    )


def test_ci_check_run_no_steps_copy_matches_desktop() -> None:
    from github_desktop.github.ci_checks import (
        THERE_ARE_NO_STEPS,
        VIEW_CHECK_DETAILS,
        areNoSteps,
        are_no_check_steps,
        view_check_details_url,
    )
    from github_desktop.models import CheckStep, RefCheck

    assert THERE_ARE_NO_STEPS == "There are no steps to display for this check."
    assert VIEW_CHECK_DETAILS == "View check details"
    empty = RefCheck(id=1, name="build", description="", status="completed", conclusion="failure")
    assert empty.actionJobSteps is None
    assert are_no_check_steps(empty) is True
    assert areNoSteps is are_no_check_steps
    assert view_check_details_url(empty) is None
    empty.html_url = "https://github.com/o/r/runs/1"
    assert view_check_details_url(empty) == "https://github.com/o/r/runs/1"
    empty.html_url = None
    assert (
        view_check_details_url(empty, repo_html_url="https://github.com/o/r", pr_number=12)
        == "https://github.com/o/r/pull/12"
    )
    with_steps = RefCheck(
        id=2,
        name="linux",
        description="",
        status="completed",
        conclusion="success",
        steps=[CheckStep(name="Set up job", number=1, status="completed", conclusion="success")],
    )
    assert with_steps.actionJobSteps is not None
    assert are_no_check_steps(with_steps) is False


def test_get_hunk_handle_label_matches_desktop() -> None:
    from github_desktop.git.diff import DiffRange, DiffRangeType
    from github_desktop.ui.diff_view import get_hunk_handle_label, is_only_one_check_in_row

    assert get_hunk_handle_label(DiffRangeType.ADDITIONS, 10, 14) == "Lines 10 to 14 added"
    assert get_hunk_handle_label(DiffRangeType.DELETIONS, 3, 5) == "Lines 3 to 5 deleted"
    assert get_hunk_handle_label(DiffRangeType.MIXED, 1, 2) == "Lines 1 to 2 modified"
    assert is_only_one_check_in_row(None) is True
    assert is_only_one_check_in_row(DiffRange(4, 4, DiffRangeType.ADDITIONS)) is True
    assert is_only_one_check_in_row(DiffRange(4, 7, DiffRangeType.ADDITIONS)) is False


def test_build_expand_menu_item_matches_desktop() -> None:
    from types import SimpleNamespace

    from github_desktop.models import DiffHunkExpansionType
    from github_desktop.ui.diff_view import build_expand_menu_item, hunks_expand_whole_file_enabled

    none = SimpleNamespace(expansion_type=DiffHunkExpansionType.NONE)
    up = SimpleNamespace(expansion_type=DiffHunkExpansionType.UP)
    assert build_expand_menu_item(can_expand_diff=False, is_expanded=False, hunks=[up]) is None
    assert build_expand_menu_item(can_expand_diff=True, is_expanded=True, hunks=[up]) == (
        "Collapse expanded lines",
        True,
    )
    assert build_expand_menu_item(can_expand_diff=True, is_expanded=False, hunks=[none]) == (
        "Expand whole file",
        False,
    )
    assert build_expand_menu_item(can_expand_diff=True, is_expanded=False, hunks=[up]) == (
        "Expand whole file",
        True,
    )
    assert hunks_expand_whole_file_enabled([none, up]) is True
    assert hunks_expand_whole_file_enabled([]) is False


def test_keyboard_reorder_copy() -> None:
    from github_desktop.ui.window import keyboard_reorder_insert_message, keyboard_reorder_intro_message

    assert keyboard_reorder_intro_message(1) == (
        "Use the Up and Down arrow keys to choose a new location for the selected commit, "
        "then press Enter to confirm or Escape to cancel."
    )
    assert "selected commits" in keyboard_reorder_intro_message(2)
    assert keyboard_reorder_insert_message(1, 0, 5) == (
        "Press Enter to insert the selected commit before commit 1 or Escape to cancel."
    )
    assert keyboard_reorder_insert_message(2, 5, 5) == (
        "Press Enter to insert the selected commits after commit 5 or Escape to cancel."
    )


def test_enable_commit_message_generation_requires_flag_and_entitlement() -> None:
    from github_desktop.models import Account, enable_commit_message_generation

    none = Account(login="hubot", endpoint="https://api.github.com", token="t")
    assert enable_commit_message_generation(none) is False
    assert enable_commit_message_generation(None) is False
    flagged = Account(
        login="hubot",
        endpoint="https://api.github.com",
        token="t",
        features=["desktop_copilot_generate_commit_message"],
        is_copilot_desktop_enabled=False,
    )
    assert enable_commit_message_generation(flagged) is False
    entitled = Account(
        login="hubot",
        endpoint="https://api.github.com",
        token="t",
        features=["desktop_copilot_generate_commit_message"],
        is_copilot_desktop_enabled=True,
    )
    assert enable_commit_message_generation(entitled) is True


def test_push_protection_bypass_uses_secret_scanning_path() -> None:
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []
    posted: list[dict] = []

    def fake_post(path, body=None, **kwargs):
        seen.append(path)
        posted.append(body or {})
        return {"id": 1}

    api.post = fake_post  # type: ignore[method-assign]
    api.create_push_protection_bypass("desktop", "desktop", "false_positive", "ph")
    assert seen == ["/repos/desktop/desktop/secret-scanning/push-protection-bypasses"]
    assert posted == [{"reason": "false_positive", "placeholder_id": "ph"}]


def test_create_push_protection_bypass_includes_retry_url() -> None:
    from github_desktop.errors import APIError
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")

    def boom(path, body=None, **kwargs):
        raise APIError("nope", status=403)

    api.post = boom  # type: ignore[method-assign]
    try:
        api.create_push_protection_bypass(
            "desktop",
            "desktop",
            "used_in_tests",
            placeholder_id="ph",
            bypass_url="https://github.com/desktop/desktop/security/secret-scanning/unblock-secret/ABC",
        )
        raise AssertionError("expected APIError")
    except APIError as exc:
        text = str(exc)
        assert "Unable to create push protection bypass" in text
        assert "Repository: desktop/desktop" in text
        assert "Reason: used_in_tests" in text
        assert "Placeholder Id: ph." in text
        assert "Try again at: https://github.com/desktop/desktop/security/secret-scanning/unblock-secret/ABC" in text


def test_merge_updated_pull_requests_and_issues() -> None:
    from github_desktop.github.api import merge_updated_issues, merge_updated_pull_requests
    from github_desktop.models import Issue, PullRequest

    open_pr = PullRequest(
        number=1,
        title="open",
        body="",
        created_at="2026-01-01T00:00:00Z",
        author="hubot",
        draft=False,
        head_ref="head",
        head_sha="abc",
        base_ref="main",
        html_url="https://github.com/o/r/pull/1",
        state="open",
        updated_at="2026-01-01T00:00:00Z",
    )
    closed = PullRequest(
        number=1,
        title="closed",
        body="",
        created_at="2026-01-01T00:00:00Z",
        author="hubot",
        draft=False,
        head_ref="head",
        head_sha="abc",
        base_ref="main",
        html_url="https://github.com/o/r/pull/1",
        state="closed",
        updated_at="2026-02-01T00:00:00Z",
    )
    other = PullRequest(
        number=2,
        title="new",
        body="",
        created_at="2026-02-01T00:00:00Z",
        author="hubot",
        draft=False,
        head_ref="other",
        head_sha="def",
        base_ref="main",
        html_url="https://github.com/o/r/pull/2",
        state="open",
        updated_at="2026-02-01T00:00:00Z",
    )
    merged = merge_updated_pull_requests([open_pr], [closed, other])
    assert [pr.number for pr in merged] == [2]
    issues = merge_updated_issues(
        [Issue(number=3, title="old", state="open")],
        [Issue(number=3, title="old", state="closed"), Issue(number=4, title="fresh")],
    )
    assert [issue.number for issue in issues] == [4]


def test_fetch_updated_pull_requests_raises_max_results() -> None:
    from github_desktop.errors import MaxResultsError
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")

    def fake_request(method, path, **kwargs):
        items = [
            {
                "number": i,
                "title": str(i),
                "updated_at": "2026-08-01T00:00:00Z",
                "created_at": "2026-08-01T00:00:00Z",
                "user": {},
                "head": {},
                "base": {},
                "html_url": "",
            }
            for i in range(10)
        ]
        headers = {"link": '</repos/o/r/pulls?per_page=10&page=2>; rel="next"'}
        if kwargs.get("return_headers"):
            return items, headers
        return items

    api.request = fake_request  # type: ignore[method-assign]
    with pytest.raises(MaxResultsError):
        api.fetch_updated_pull_requests("o", "r", "2020-01-01T00:00:00Z", max_results=5)


def test_actions_and_ruleset_api_paths() -> None:
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[tuple[str, dict]] = []

    def fake_get(path, **kwargs):
        seen.append((path, kwargs.get("query") or {}))
        if "rulesets" in path and path.endswith("rulesets"):
            return [{"id": 7}]
        if "actions/runs" in path:
            return {"workflow_runs": [{"id": 3, "name": "CI", "event": "pull_request", "check_suite_id": 11}]}
        return {}

    api.get = fake_get  # type: ignore[method-assign]
    assert api.fetch_all_repo_rulesets("o", "r") == [{"id": 7}]
    runs = api.fetch_pr_workflow_runs_by_branch_name("o", "r", "feature")
    assert runs[0]["id"] == 3
    assert seen[1][1]["event"] == "pull_request"
    assert seen[1][1]["branch"] == "feature"
    run = api.fetch_pr_action_workflow_run_by_check_suite_id("o", "r", 11)
    assert run and run["id"] == 3


def test_fetch_mentionables_honors_not_modified() -> None:
    from github_desktop.errors import APIError
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")

    def not_modified(*_a, **_k):
        raise APIError("not modified", status=304)

    api.request = not_modified  # type: ignore[method-assign]
    users, etag = api.fetch_mentionables("o", "r", etag='"abc"')
    assert users is None
    assert etag == '"abc"'


def test_fetch_notification_subject_uses_typed_endpoints() -> None:
    from github_desktop.github.api import GitHubAPI

    api = GitHubAPI("https://api.github.com", "tok")
    seen: list[str] = []

    def fake_get(path, **kwargs):
        seen.append(path)
        return {"id": 1, "body": "hi"}

    api.get = fake_get  # type: ignore[method-assign]
    api.fetch_notification_subject("https://api.github.com/repos/o/r/issues/comments/9")
    api.fetch_notification_subject("https://api.github.com/repos/o/r/pulls/comments/8")
    api.fetch_notification_subject("https://api.github.com/repos/o/r/pulls/3/reviews/7")
    assert seen == [
        "/repos/o/r/issues/comments/9",
        "/repos/o/r/pulls/comments/8",
        "/repos/o/r/pulls/3/reviews/7",
    ]


def test_create_push_protection_bypass_logs_without_github_repo(isolated_config, git_repo, caplog) -> None:
    import logging

    from github_desktop.models import GitHubRepository
    from github_desktop.store import AppStore

    store = AppStore()
    repos = store.add_repositories([str(git_repo)])
    store.selected_repository_id = repos[0].id
    with caplog.at_level(logging.ERROR, logger="github_desktop"):
        assert store.create_push_protection_bypass("false_positive", "ph", "https://example") is None
    assert "[_createPushProtectionBypass] - No GitHub repository selected" in caplog.text

    repos[0].github = GitHubRepository(
        name="hello",
        owner="octocat",
        html_url="https://github.com/octocat/hello",
        clone_url="https://github.com/octocat/hello.git",
        endpoint="https://api.github.com",
    )
    store.accounts = []
    caplog.clear()
    with caplog.at_level(logging.ERROR, logger="github_desktop"):
        assert store.create_push_protection_bypass("false_positive", "ph", "https://example") is None
    assert "[_createPushProtectionBypass] - No account found for endpoint - https://api.github.com" in caplog.text


def test_resolve_co_authors_uses_stealth_email(isolated_config, monkeypatch) -> None:
    from github_desktop.models import Account, Author
    from github_desktop.store import AppStore

    store = AppStore()
    store.accounts = [Account(login="me", endpoint="https://api.github.com", token="t")]

    def fake_user(self, login):
        if login == "github":
            return {"login": "github", "id": 2, "type": "Organization"}
        return {"login": login, "name": "The Octocat", "id": 1, "type": "User", "email": None}

    monkeypatch.setattr("github_desktop.github.api.GitHubAPI.fetch_user_by_login", fake_user)
    resolved, unknown = store.resolve_co_authors(
        [Author(name="octocat", email="", username="octocat")]
    )
    assert unknown == []
    assert resolved[0].email == "1+octocat@users.noreply.github.com"
    assert resolved[0].name == "The Octocat"
    _, org_unknown = store.resolve_co_authors([Author(name="github", email="", username="github")])
    assert [author.username for author in org_unknown] == ["github"]


def test_get_by_login_matches_desktop_exact_match(isolated_config, monkeypatch) -> None:
    from github_desktop.models import Account
    from github_desktop.store import AppStore

    store = AppStore()
    store.accounts = [Account(login="me", endpoint="https://api.github.com", token="t")]

    def fake_user(self, login):
        if login == "missing":
            return None
        return {"login": login, "name": "The Octocat", "id": 1, "type": "User", "email": None, "avatar_url": "https://n"}

    monkeypatch.setattr("github_desktop.github.api.GitHubAPI.fetch_user_by_login", fake_user)
    hit = store.get_by_login(store.accounts[0], "octocat")
    assert hit is not None
    assert hit["kind"] == "known-user"
    assert hit["email"] == "1+octocat@users.noreply.github.com"
    assert store.exact_match("octocat") is None
    assert store.get_by_login(store.accounts[0], "missing") is None


def test_tutorial_nudge_arrows_match_desktop() -> None:
    from github_desktop.models import TutorialStep
    from github_desktop.ui.tutorial import (
        apply_nudge_arrow_classes,
        nudge_arrow_frame,
        publishBranchButton,
        shouldNudge,
        shouldNudgeToCommit,
    )

    assert shouldNudge(TutorialStep.CREATE_BRANCH, "branch") is True
    assert shouldNudge(TutorialStep.PUSH_BRANCH, "push") is True
    assert shouldNudge(TutorialStep.MAKE_COMMIT, "branch") is False
    assert shouldNudgeToCommit(TutorialStep.MAKE_COMMIT) is True
    assert shouldNudgeToCommit(TutorialStep.CREATE_BRANCH) is False
    assert publishBranchButton(
        remote_name="origin",
        current_branch="tutorial",
        current_tip="abc",
        has_upstream=False,
    )
    assert not publishBranchButton(
        remote_name="origin",
        current_branch="tutorial",
        current_tip="abc",
        has_upstream=True,
    )
    assert not publishBranchButton(
        remote_name="origin",
        current_branch="tutorial",
        current_tip="abc",
        has_upstream=False,
        progress=True,
    )
    assert not publishBranchButton(
        remote_name=None,
        current_branch="tutorial",
        current_tip="abc",
        has_upstream=False,
    )
    opacity, offset = nudge_arrow_frame(0, direction="up")
    assert opacity == 0.0
    assert offset == 55
    opacity, offset = nudge_arrow_frame(6600, direction="up")
    assert opacity == 1.0
    assert offset == 40
    left_opacity, left_offset = nudge_arrow_frame(0, direction="left")
    assert left_opacity == 0.0
    assert left_offset == 65

    class FakeWidget:
        def __init__(self) -> None:
            self.classes: set[str] = set()

        def has_css_class(self, name: str) -> bool:
            return name in self.classes

        def add_css_class(self, name: str) -> None:
            self.classes.add(name)

        def remove_css_class(self, name: str) -> None:
            self.classes.discard(name)

    branch = FakeWidget()
    apply_nudge_arrow_classes(branch, should_nudge=True, direction="up", base=True)
    assert branch.classes == {"nudge-arrow", "nudge-arrow-up"}
    apply_nudge_arrow_classes(branch, should_nudge=False, direction="up", base=True)
    assert branch.classes == {"nudge-arrow"}
    summary = FakeWidget()
    apply_nudge_arrow_classes(summary, should_nudge=True, direction="left", base=True)
    assert summary.classes == {"nudge-arrow", "nudge-arrow-left"}
    publish = FakeWidget()
    apply_nudge_arrow_classes(publish, should_nudge=True, direction="up", base=False)
    assert publish.classes == set()


def test_summary_length_hint_lightbulb_matches_desktop() -> None:
    from github_desktop.text_tokens import IdealSummaryLength
    from github_desktop.ui.autocompletion import SUMMARY_LENGTH_HINT, summary_length_hint
    from github_desktop.ui.length_hint import (
        LENGTH_HINT,
        LENGTH_HINT_TOOLTIP,
        OPEN_SUMMARY_LENGTH_INFO,
        SUMMARY_LENGTH_HINT_DESCRIPTION,
        SUMMARY_LENGTH_HINT_TITLE,
        show_summary_length_hint,
    )

    assert IdealSummaryLength == 50
    assert summary_length_hint("x" * 51, True) == SUMMARY_LENGTH_HINT
    assert summary_length_hint("x" * 50, True) is None
    assert SUMMARY_LENGTH_HINT_TITLE in SUMMARY_LENGTH_HINT
    assert SUMMARY_LENGTH_HINT_DESCRIPTION in SUMMARY_LENGTH_HINT
    assert OPEN_SUMMARY_LENGTH_INFO == "Open Summary Length Info"
    assert LENGTH_HINT == "length-hint"
    assert LENGTH_HINT_TOOLTIP == "length-hint-tooltip"
    assert show_summary_length_hint("x" * 51, True, rule_hint=False) is True
    assert show_summary_length_hint("x" * 51, True, rule_hint=True) is False
    assert show_summary_length_hint("short", True, rule_hint=False) is False
    assert show_summary_length_hint("x" * 51, False, rule_hint=False) is False

