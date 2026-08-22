"""Desktop `lib/stores/helpers/tutorial-assessor.ts`."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .local_storage import get_boolean, remove_item, set_boolean
from .models import TutorialStep

if TYPE_CHECKING:
    from .store import RepositoryViewState

skipInstallEditorKey = "tutorial-install-editor-skipped"
pullRequestStepCompleteKey = "tutorial-pull-request-step-complete"
tutorialPausedKey = "tutorial-paused"


class OnboardingTutorialAssessor:
    """Determines the next onboarding tutorial step (Desktop `OnboardingTutorialAssessor`)."""

    def __init__(self, get_resolved_external_editor: Callable[[], str | None]) -> None:
        self._get_resolved_external_editor = get_resolved_external_editor
        self.install_editor_skipped = bool(get_boolean(skipInstallEditorKey, False))
        self.pr_step_complete = bool(get_boolean(pullRequestStepCompleteKey, False))
        self.tutorial_paused = bool(get_boolean(tutorialPausedKey, False))
        self.tutorial_announced = False

    def get_current_step(
        self,
        is_tutorial_repo: bool,
        state: RepositoryViewState | None,
        *,
        current_branch: str | None = None,
        default_branch: str | None = None,
    ) -> TutorialStep:
        """Desktop `OnboardingTutorialAssessor.getCurrentStep`."""
        if not is_tutorial_repo:
            if self.tutorial_paused:
                self.resume_tutorial()
            return TutorialStep.NOT_APPLICABLE
        if self.tutorial_paused:
            return TutorialStep.PAUSED
        if not self._is_editor_installed():
            return TutorialStep.PICK_EDITOR
        if not self._is_branch_checked_out(current_branch, default_branch):
            return TutorialStep.CREATE_BRANCH
        if not self._has_changed_file(state):
            return TutorialStep.EDIT_FILE
        if not self._has_multiple_commits(state):
            return TutorialStep.MAKE_COMMIT
        if not self._commit_pushed(state):
            return TutorialStep.PUSH_BRANCH
        if not self._pull_request_created(state):
            return TutorialStep.OPEN_PULL_REQUEST
        if not self.tutorial_announced:
            return TutorialStep.ALL_DONE
        return TutorialStep.ANNOUNCED

    def _is_editor_installed(self) -> bool:
        return self.install_editor_skipped or self._get_resolved_external_editor() is not None

    def _is_branch_checked_out(self, current_branch: str | None, default_branch: str | None) -> bool:
        return (
            current_branch is not None
            and default_branch is not None
            and current_branch != default_branch
        )

    def _has_changed_file(self, state: RepositoryViewState | None) -> bool:
        if self._has_multiple_commits(state):
            return True
        if state is None or state.status is None:
            return False
        return len(state.status.working_directory.files) > 0

    def _has_multiple_commits(self, state: RepositoryViewState | None) -> bool:
        if state is None:
            return False
        tip = state.status.current_tip if state.status else None
        if tip:
            commit = next((item for item in state.commits if item.sha == tip), None)
            if commit is not None:
                return any(parent for parent in commit.parent_shas)
        return False

    def _commit_pushed(self, state: RepositoryViewState | None) -> bool:
        if state is None or state.ahead_behind is None:
            return False
        return state.ahead_behind.ahead == 0

    def _pull_request_created(self, state: RepositoryViewState | None) -> bool:
        if state is not None and state.current_pull_request is not None:
            self.mark_pull_request_tutorial_step_as_complete()
        return self.pr_step_complete

    def skip_pick_editor(self) -> None:
        """Desktop `skipPickEditor`."""
        self.install_editor_skipped = True
        set_boolean(skipInstallEditorKey, True)

    def mark_pull_request_tutorial_step_as_complete(self) -> None:
        """Desktop `markPullRequestTutorialStepAsComplete`."""
        self.pr_step_complete = True
        set_boolean(pullRequestStepCompleteKey, True)

    def mark_tutorial_completion_as_announced(self) -> None:
        """Desktop `markTutorialCompletionAsAnnounced`."""
        self.tutorial_announced = True

    def on_new_tutorial_repository(self) -> None:
        """Desktop `onNewTutorialRepository`: reset skipped steps."""
        self.install_editor_skipped = False
        remove_item(skipInstallEditorKey)
        self.pr_step_complete = False
        remove_item(pullRequestStepCompleteKey)
        self.tutorial_paused = False
        remove_item(tutorialPausedKey)
        self.tutorial_announced = False

    def pause_tutorial(self) -> None:
        """Desktop `pauseTutorial`."""
        self.tutorial_paused = True
        set_boolean(tutorialPausedKey, True)

    def resume_tutorial(self) -> None:
        """Desktop `resumeTutorial`."""
        self.tutorial_paused = False
        set_boolean(tutorialPausedKey, False)
