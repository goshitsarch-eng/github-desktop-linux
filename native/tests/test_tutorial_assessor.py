"""Desktop OnboardingTutorialAssessor localStorage keys and step machine."""

from __future__ import annotations

from datetime import datetime, timezone

from github_desktop.local_storage import get_boolean
from github_desktop.models import (
    AheadBehind,
    AppFileStatusKind,
    Commit,
    CommitIdentity,
    FileStatus,
    IStatusResult,
    TutorialStep,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
    is_valid_tutorial_step,
)
from github_desktop.store import AppStore, RepositoryViewState
from github_desktop.tutorial_assessor import (
    OnboardingTutorialAssessor,
    pullRequestStepCompleteKey,
    skipInstallEditorKey,
    tutorialPausedKey,
)


def _state(
    *,
    branch: str | None = "main",
    files: int = 0,
    commits: int = 1,
    ahead: int | None = None,
    pr: bool = False,
) -> RepositoryViewState:
    ident = CommitIdentity("T", "t@example.com", datetime.now(timezone.utc))
    commit_list: list[Commit] = []
    parent = ""
    for index in range(commits):
        sha = f"{index:040d}"
        commit_list.append(
            Commit(
                sha=sha,
                short_sha=sha[:7],
                summary=f"c{index}",
                body="",
                author=ident,
                committer=ident,
                parent_shas=[parent] if parent else [],
            )
        )
        parent = sha
    wd_files = [
        WorkingDirectoryFileChange("README.md", FileStatus(AppFileStatusKind.MODIFIED))
        for _ in range(files)
    ]
    state = RepositoryViewState()
    state.status = IStatusResult(
        current_branch=branch,
        current_tip=commit_list[-1].sha if commit_list else None,
        working_directory=WorkingDirectoryStatus.from_files(wd_files),
    )
    state.commits = commit_list
    if ahead is not None:
        state.ahead_behind = AheadBehind(ahead=ahead, behind=0)
    if pr:
        state.current_pull_request = type("PR", (), {})()
    return state


def test_tutorial_assessor_steps_and_local_storage(isolated_config) -> None:
    assessor = OnboardingTutorialAssessor(lambda: None)
    assert assessor.get_current_step(False, None) == TutorialStep.NOT_APPLICABLE
    assert assessor.get_current_step(True, _state()) == TutorialStep.PICK_EDITOR

    assessor.skip_pick_editor()
    assert get_boolean(skipInstallEditorKey) is True
    assert (
        assessor.get_current_step(True, _state(branch="main"), current_branch="main", default_branch="main")
        == TutorialStep.CREATE_BRANCH
    )
    assert (
        assessor.get_current_step(
            True,
            _state(branch="tutorial", files=0, commits=1),
            current_branch="tutorial",
            default_branch="main",
        )
        == TutorialStep.EDIT_FILE
    )
    changed = _state(branch="tutorial", files=1, commits=1)
    assert (
        assessor.get_current_step(True, changed, current_branch="tutorial", default_branch="main")
        == TutorialStep.MAKE_COMMIT
    )
    two = _state(branch="tutorial", files=0, commits=2)
    assert (
        assessor.get_current_step(True, two, current_branch="tutorial", default_branch="main")
        == TutorialStep.PUSH_BRANCH
    )
    pushed = _state(branch="tutorial", files=0, commits=2, ahead=0)
    assert (
        assessor.get_current_step(True, pushed, current_branch="tutorial", default_branch="main")
        == TutorialStep.OPEN_PULL_REQUEST
    )
    assessor.mark_pull_request_tutorial_step_as_complete()
    assert get_boolean(pullRequestStepCompleteKey) is True
    done = _state(branch="tutorial", files=0, commits=2, ahead=0)
    assert assessor.get_current_step(True, done, current_branch="tutorial", default_branch="main") == TutorialStep.ALL_DONE
    assessor.mark_tutorial_completion_as_announced()
    assert assessor.get_current_step(True, done, current_branch="tutorial", default_branch="main") == TutorialStep.ANNOUNCED

    assessor.pause_tutorial()
    assert get_boolean(tutorialPausedKey) is True
    assert assessor.get_current_step(True, done, current_branch="tutorial", default_branch="main") == TutorialStep.PAUSED
    assessor.resume_tutorial()
    assert get_boolean(tutorialPausedKey) is False

    assessor.on_new_tutorial_repository()
    assert get_boolean(skipInstallEditorKey, False) is False
    assert get_boolean(pullRequestStepCompleteKey, False) is False
    assert is_valid_tutorial_step(TutorialStep.ALL_DONE)
    assert not is_valid_tutorial_step(TutorialStep.PAUSED)
    assert TutorialStep.ALL_COMPLETE is TutorialStep.ALL_DONE


def test_skip_editor_persists_across_store(isolated_config, git_repo) -> None:
    store = AppStore()
    store.add_repositories([str(git_repo)])
    repo = store.selected_repository
    assert repo is not None
    repo.tutorial = True
    store.complete_tutorial_editor_step()
    assert get_boolean(skipInstallEditorKey) is True
    assert store.tutorial_step != TutorialStep.PICK_EDITOR
    store.pause_tutorial()
    assert store.tutorial_step == TutorialStep.PAUSED
    assert store.settings.tutorial_paused is True
    store.resume_tutorial()
    assert store.tutorial_step != TutorialStep.PAUSED
    assert store.settings.tutorial_paused is False
