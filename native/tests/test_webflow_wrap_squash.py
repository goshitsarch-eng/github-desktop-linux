"""Web-flow committers, wrap-72 summaries, squash co-authors, Flatpak, old paths."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from github_desktop.linux import (
    convert_to_flatpak_path,
    format_path_for_flatpak,
    format_working_directory_for_flatpak,
    is_flatpak_build,
    path_exists,
    spawn,
)
from github_desktop.models import (
    AppFileStatusKind,
    Author,
    Commit,
    CommitIdentity,
    FileStatus,
    GitHubRepository,
    WorkingDirectoryFileChange,
    format_commit_attribution,
    get_old_path_or_default,
    get_squashed_commit_description,
    get_unique_coauthors_as_authors,
    is_web_flow_committer,
)
from github_desktop.text_tokens import (
    MaxSummaryLength,
    TokenType,
    Tokenizer,
    wrap_rich_text_commit_message,
)
from github_desktop.ui.menus import (
    CopyFilePathLabel,
    CopyRelativeFilePathLabel,
    CopySelectedRelativePathsLabel,
    RevealInFileManagerLabel,
    alias_verb,
    open_in_editor_label,
    open_in_shell_label,
    remove_repository_label,
)


def _when() -> datetime:
    return datetime(2024, 1, 2, tzinfo=timezone.utc)


def _identity(name: str = "test", email: str = "test") -> CommitIdentity:
    return CommitIdentity(name, email, _when())


def _commit(
    summary: str = "test",
    body: str = "test",
    trailers: list[tuple[str, str]] | None = None,
    *,
    author: CommitIdentity | None = None,
    committer: CommitIdentity | None = None,
) -> Commit:
    who = author or _identity()
    return Commit(
        sha="test",
        short_sha="test",
        summary=summary,
        body=body,
        author=who,
        committer=committer or who,
        trailers=list(trailers or []),
    )


def _github(*, endpoint: str = "https://api.github.com", owner: str = "niik", name: str = "commit-summary-wrap-tests") -> GitHubRepository:
    html = "https://github.com" if "api.github.com" in endpoint else endpoint.replace("/api/v3", "")
    return GitHubRepository(
        name=name,
        owner=owner,
        html_url=f"{html}/{owner}/{name}",
        clone_url=f"{html}/{owner}/{name}.git",
        endpoint=endpoint,
    )


def test_is_web_flow_committer_dotcom_and_enterprise() -> None:
    author = _identity("Ada", "ada@example.com")
    web = _commit(author=author, committer=_identity("GitHub", "noreply@github.com"))
    other = _commit(author=author, committer=_identity("Grace", "grace@example.com"))
    enterprise = _commit(author=author, committer=_identity("GitHub Enterprise", "noreply@ghe.example"))
    dotcom = _github()
    ghes = _github(endpoint="https://ghe.example/api/v3", owner="acme", name="app")
    assert is_web_flow_committer(web, dotcom)
    assert not is_web_flow_committer(other, dotcom)
    assert not is_web_flow_committer(web, None)
    assert is_web_flow_committer(enterprise, ghes)
    assert not is_web_flow_committer(web, ghes)
    assert format_commit_attribution(web) == "Ada, GitHub"
    assert format_commit_attribution(web, dotcom) == "Ada"


def test_get_unique_coauthors_as_authors() -> None:
    signed = [("Signed-Off-By", "test <test@github.com>")]
    assert get_unique_coauthors_as_authors([_commit(trailers=signed), _commit(trailers=[]), _commit(trailers=signed)]) == []
    email = "tidy-dev@github.com"
    name = "tidy-dev"
    trailer = [("Co-Authored-By", f"{name} <{email}>")]
    authors = get_unique_coauthors_as_authors([_commit(trailers=trailer)])
    assert len(authors) == 1
    assert authors[0].email == email
    assert authors[0].name == name
    assert len(get_unique_coauthors_as_authors([_commit(trailers=trailer)] * 3)) == 1
    other_name = [("Co-Authored-By", f"{name}hello <{email}>")]
    assert len(get_unique_coauthors_as_authors([_commit(trailers=trailer), _commit(trailers=trailer), _commit(trailers=other_name)])) == 2
    other_email = [("Co-Authored-By", f"{name} <sergiou87@github.com>")]
    assert len(get_unique_coauthors_as_authors([_commit(trailers=trailer), _commit(trailers=trailer), _commit(trailers=other_email)])) == 2
    first = [("Co-Authored-By", "tidy-dev <tidy-dev@github.com>")]
    second = [("Co-Authored-By", "Sergio <sergiou87@github.com>")]
    emails = {a.email for a in get_unique_coauthors_as_authors([_commit(trailers=first), _commit(trailers=[]), _commit(trailers=second)])}
    assert emails == {"tidy-dev@github.com", "sergiou87@github.com"}


def test_get_squashed_commit_description() -> None:
    mock = [("Co-Authored-By", "test <test>")]
    commits = [_commit("summary1", "desc1", []), _commit("summary2", "desc2", [])]
    onto = _commit("ontoSummary", "ontoDesc", [])
    assert get_squashed_commit_description(commits, onto) == "ontoDesc\n\nsummary1\n\ndesc1\n\nsummary2\n\ndesc2"
    commits = [_commit("summary1", "desc1", mock), _commit("summary2", "desc2", mock)]
    onto = _commit("ontoSummary", "ontoDesc", mock)
    assert get_squashed_commit_description(commits, onto) == "ontoDesc\n\nsummary1\n\ndesc1\n\nsummary2\n\ndesc2"
    commits = [_commit("summary1    ", "desc1   ", mock), _commit("summary2\n", "desc2\n", mock)]
    onto = _commit("ontoSummary", "ontoDesc  \n", mock)
    assert get_squashed_commit_description(commits, onto) == "ontoDesc\n\nsummary1\n\ndesc1\n\nsummary2\n\ndesc2"


def test_wrap_rich_text_commit_message() -> None:
    github = _github()
    tokenizer = Tokenizer(github=github)

    def wrap(summary: str, body: str = ""):
        return wrap_rich_text_commit_message(summary, body, tokenizer)

    exact = "weshouldnothardwrapthislongsummarywhichisexactly72charactersyeswetotally"
    wrapped = wrap(exact)
    assert MaxSummaryLength == 72
    assert len(wrapped.summary) == 1
    assert wrapped.body == []
    assert wrapped.summary[0].kind is TokenType.TEXT
    assert wrapped.summary[0].text == exact

    long_text = "weshouldabsolutelyhardwrapthislongsummarywhichexceeds72charactersyeswetotallyshould"
    wrapped = wrap(long_text)
    assert len(wrapped.summary) == 2
    assert len(wrapped.body) == 2
    assert wrapped.summary[0].text == long_text[:72]
    assert wrapped.summary[1].text == "…"
    assert wrapped.body[0].text == "…"
    assert wrapped.body[1].text == long_text[72:]

    wrapped = wrap(long_text, "oh hi")
    assert len(wrapped.summary) == 2
    assert len(wrapped.body) == 4
    assert wrapped.body[0].text == "…"
    assert wrapped.body[1].text == long_text[72:]
    assert wrapped.body[2].text == "\n\n"
    assert wrapped.body[3].text == "oh hi"

    issue_exact = "This issue summary should be exactly 72 chars including the issue no: https://github.com/niik/commit-summary-wrap-tests/issues/1"
    wrapped = wrap(issue_exact)
    assert len(wrapped.summary) == 2
    assert wrapped.body == []
    assert wrapped.summary[0].text == "This issue summary should be exactly 72 chars including the issue no: "
    assert wrapped.summary[1].kind is TokenType.LINK
    assert wrapped.summary[1].text == "#1"

    issue = "This issue link should be shortened to well under 72 characters: https://github.com/niik/commit-summary-wrap-tests/issues/1"
    wrapped = wrap(issue)
    assert wrapped.summary[1].text == "#1"
    assert wrapped.summary[1].url == "https://github.com/niik/commit-summary-wrap-tests/issues/1"

    many = "Multiple links are fine https://github.com/niik/commit-summary-wrap-tests/issues/1 https://github.com/niik/commit-summary-wrap-tests/issues/2 https://github.com/niik/commit-summary-wrap-tests/issues/3 https://github.com/niik/commit-summary-wrap-tests/issues/4"
    wrapped = wrap(many)
    assert len(wrapped.summary) == 8
    assert "".join(token.text for token in wrapped.summary) == "Multiple links are fine #1 #2 #3 #4"

    truncated = "Link should be truncated but open our release notes https://desktop.github.com/release-notes/"
    wrapped = wrap(truncated)
    assert len(wrapped.summary) == 3
    assert len(wrapped.body) == 2
    assert wrapped.summary[0].text == "Link should be truncated but open our release notes "
    assert wrapped.summary[1].kind is TokenType.LINK
    assert wrapped.summary[1].text == "https://desktop.gith"
    assert wrapped.summary[1].url == "https://desktop.github.com/release-notes/"
    assert wrapped.summary[2].text == "…"
    assert wrapped.body[0].text == "…"
    assert wrapped.body[1].kind is TokenType.LINK
    assert wrapped.body[1].text == "ub.com/release-notes/"
    assert wrapped.body[1].url == "https://desktop.github.com/release-notes/"


def test_get_old_path_or_default() -> None:
    renamed = WorkingDirectoryFileChange("new.txt", FileStatus(AppFileStatusKind.RENAMED, old_path="old.txt"))
    copied = WorkingDirectoryFileChange("copy.txt", FileStatus(AppFileStatusKind.COPIED, old_path="src.txt"))
    modified = WorkingDirectoryFileChange("file.txt", FileStatus(AppFileStatusKind.MODIFIED))
    assert get_old_path_or_default(renamed) == "old.txt"
    assert get_old_path_or_default(copied) == "src.txt"
    assert get_old_path_or_default(modified) == "file.txt"
    assert get_old_path_or_default(path="new.txt", status=renamed.status) == "old.txt"


def test_linux_flatpak_helpers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("FLATPAK_HOST", raising=False)
    assert is_flatpak_build() is False
    monkeypatch.setenv("FLATPAK_HOST", "1")
    assert is_flatpak_build() is True
    assert convert_to_flatpak_path("/opt/foo") == "/opt/foo"
    assert convert_to_flatpak_path("/var/lib/flatpak/app/x") == "/var/lib/flatpak/app/x"
    assert convert_to_flatpak_path("/usr/bin/code") == "/usr/bin/code"
    assert convert_to_flatpak_path("usr/bin/code") == "/var/run/host/usr/bin/code"
    assert format_path_for_flatpak("/var/lib/flatpak/app/com.visualstudio.code/bin") == "com.visualstudio.code/bin"
    assert format_working_directory_for_flatpak("/tmp/my dir") == "/tmp/my dir"
    missing = tmp_path / "nope"
    assert path_exists(str(missing)) is False
    present = tmp_path / "yes"
    present.write_text("ok", encoding="utf-8")
    monkeypatch.delenv("FLATPAK_HOST", raising=False)
    assert path_exists(str(present)) is True
    calls: list[list[str]] = []

    def fake_popen(cmd, **_kwargs):
        calls.append(list(cmd))

        class Proc:
            pass

        return Proc()

    monkeypatch.setattr("github_desktop.linux.subprocess.Popen", fake_popen)
    monkeypatch.setenv("FLATPAK_HOST", "1")
    spawn("/usr/bin/code", ["--wait", "/tmp/repo"])
    assert calls[-1][:3] == ["flatpak-spawn", "--host", "/usr/bin/code"]
    monkeypatch.delenv("FLATPAK_HOST", raising=False)
    spawn("/usr/bin/code", ["--wait"])
    assert calls[-1] == ["/usr/bin/code", "--wait"]


def test_linux_context_menu_labels() -> None:
    assert CopyFilePathLabel == "Copy file path"
    assert CopyRelativeFilePathLabel == "Copy relative file path"
    assert CopySelectedRelativePathsLabel == "Copy relative paths"
    assert RevealInFileManagerLabel == "Show in your File Manager"
    assert open_in_editor_label("Visual Studio Code") == "Open in Visual Studio Code"
    assert open_in_editor_label(None) == "Open in external editor"
    assert open_in_shell_label("GNOME Terminal") == "Open in GNOME Terminal"
    assert open_in_shell_label(None) == "Open in shell"
    assert remove_repository_label(True) == "Remove…"
    assert remove_repository_label(False) == "Remove"
    assert alias_verb(None) == "Create"
    assert alias_verb("work") == "Change"
    from github_desktop.models import Author as CoAuthor

    assert isinstance(CoAuthor("a", "b"), Author)


def test_ignore_folder_labels_deepest_first() -> None:
    from github_desktop.ui.menus import GitIgnoreFileName, ignore_extension_globs, ignore_folder_labels

    assert GitIgnoreFileName == ".gitignore"
    assert ignore_folder_labels("src/ui/file.ts") == ["/src/ui", "/src"]
    assert ignore_folder_labels("file.ts") == []
    assert ignore_extension_globs(["a.ts", "b.ts", "c.py", "d.md", "e.css", "f.json", "g.sh"]) == [
        ".ts",
        ".py",
        ".md",
        ".css",
        ".json",
    ]
    assert ignore_extension_globs(["README", ".gitignore"]) == []


def test_rebase_changed_file_menu_hides_ignore() -> None:
    from github_desktop.models import AppFileStatusKind
    from github_desktop.ui.menus import (
        changes_list_context_menu_blocked,
        discard_changes_item_label,
        rebase_changed_file_menu_labels,
    )

    assert discard_changes_item_label(["a.txt"], confirm=True) == "Discard changes…"
    assert discard_changes_item_label(["a.txt", "b.txt"], confirm=False) == "Discard 2 selected changes"
    assert changes_list_context_menu_blocked(committing=True, rebasing=False)
    assert changes_list_context_menu_blocked(committing=False, rebasing=True)
    assert not changes_list_context_menu_blocked(committing=False, rebasing=False)
    tracked = rebase_changed_file_menu_labels(
        AppFileStatusKind.MODIFIED, confirm_discard=True, editor_label="Open in external editor"
    )
    assert "Ignore file (add to .gitignore)" not in tracked
    assert "Discard changes…" not in tracked
    assert "Copy file path" in tracked
    untracked = rebase_changed_file_menu_labels(
        AppFileStatusKind.UNTRACKED, confirm_discard=True, editor_label="Open in external editor"
    )
    assert untracked[0] == "Discard changes…"
    assert "Ignore file (add to .gitignore)" not in untracked


def test_commit_message_context_menu_labels() -> None:
    from github_desktop.ui.menus import (
        GENERATE_COMMIT_MESSAGE_WITH_COPILOT,
        add_remove_co_authors_label,
        commit_message_shared_menu_specs,
        commit_spellcheck_menu_label,
        generate_commit_message_menu_item,
        generate_commit_message_menu_item_enabled,
    )

    assert add_remove_co_authors_label(showing=False) == "Add co-authors"
    assert add_remove_co_authors_label(showing=True) == "Remove co-authors"
    assert GENERATE_COMMIT_MESSAGE_WITH_COPILOT == "Generate commit message with Copilot"
    assert commit_spellcheck_menu_label(enabled=True) == "Disable commit spellcheck"
    assert commit_spellcheck_menu_label(enabled=False) == "Enable commit spellcheck"
    assert generate_commit_message_menu_item(accounts_can_generate=False, is_committing=False, is_generating=False, commit_to_amend=False, files_selected=True) is None
    item = generate_commit_message_menu_item(
        accounts_can_generate=True,
        is_committing=False,
        is_generating=False,
        commit_to_amend=False,
        files_selected=True,
    )
    assert item == (GENERATE_COMMIT_MESSAGE_WITH_COPILOT, True)
    assert generate_commit_message_menu_item_enabled(
        is_committing=False, is_generating=False, commit_to_amend=False, files_selected=False
    ) is False
    assert generate_commit_message_menu_item_enabled(
        is_committing=False, is_generating=False, commit_to_amend=True, files_selected=False
    ) is True
    assert generate_commit_message_menu_item_enabled(
        is_committing=True, is_generating=False, commit_to_amend=False, files_selected=True
    ) is False
    assert generate_commit_message_menu_item_enabled(
        is_committing=False, is_generating=True, commit_to_amend=False, files_selected=True
    ) is False
    chrome = commit_message_shared_menu_specs(
        showing_co_authors=False,
        github_repository=True,
        is_committing=False,
        accounts_can_generate=True,
        is_generating=False,
        commit_to_amend=False,
        files_selected=True,
    )
    assert chrome[0] == ("Add co-authors", True)
    assert chrome[1] == (GENERATE_COMMIT_MESSAGE_WITH_COPILOT, True)
    disabled_co = commit_message_shared_menu_specs(
        showing_co_authors=True,
        github_repository=False,
        is_committing=False,
        accounts_can_generate=False,
        is_generating=False,
        commit_to_amend=False,
        files_selected=False,
    )
    assert disabled_co == [("Remove co-authors", False)]
    committing = commit_message_shared_menu_specs(
        showing_co_authors=False,
        github_repository=True,
        is_committing=True,
        accounts_can_generate=True,
        is_generating=False,
        commit_to_amend=False,
        files_selected=True,
    )
    assert committing[0] == ("Add co-authors", False)
    assert committing[1][1] is False


def test_generate_repository_list_context_menu_specs() -> None:
    from github_desktop.ui.menus import (
        RevealInFileManagerLabel,
        generate_repository_list_context_menu_specs,
    )

    local = generate_repository_list_context_menu_specs(
        alias=None,
        missing=False,
        github=False,
        shell_label="Open in GNOME Terminal",
        editor_label="Open in Visual Studio Code",
        confirm_remove=True,
    )
    assert local[0] == ("Create alias", True)
    assert "Remove alias" not in [label for label, _enabled in local]
    assert ("Copy repo name", True) in local
    assert ("View on GitHub", False) in local
    assert ("Open in GNOME Terminal", True) in local
    assert (RevealInFileManagerLabel, True) in local
    assert ("Remove…", True) in local

    aliased = generate_repository_list_context_menu_specs(
        alias="work",
        missing=True,
        github=True,
        shell_label="Open in shell",
        editor_label="Open in external editor",
        confirm_remove=False,
    )
    assert aliased[0] == ("Change alias", True)
    assert aliased[1] == ("Remove alias", True)
    assert ("View on GitHub", True) in aliased
    assert ("Open in shell", False) in aliased
    assert (RevealInFileManagerLabel, False) in aliased
    assert ("Open in external editor", False) in aliased
    assert ("Remove", True) in aliased

    cloning = generate_repository_list_context_menu_specs(
        alias=None,
        missing=False,
        github=False,
        shell_label="Open in shell",
        editor_label="Open in external editor",
        confirm_remove=True,
        is_repository=False,
    )
    assert cloning[0] == ("Copy repo name", True)
    assert "Create alias" not in [label for label, _enabled in cloning]
