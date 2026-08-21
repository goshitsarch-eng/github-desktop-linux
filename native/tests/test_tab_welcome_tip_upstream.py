"""Desktop tabSizeDefault, welcome-flow helpers, getTipSha, and findUpstreamRemote."""

from __future__ import annotations

from github_desktop.find_upstream_remote import UpstreamRemoteName, find_upstream_remote
from github_desktop.models import (
    Branch,
    BranchType,
    GitHubRepository,
    Remote,
    TipState,
    UPSTREAM_REMOTE_NAME,
)
from github_desktop.settings import (
    Settings,
    commitSpellcheckEnabledDefault,
    commitSpellcheckEnabledKey,
    repositoryIndicatorsEnabledKey,
    showChangesFilterDefault,
    showChangesFilterKey,
    showDiffCheckMarksDefault,
    showDiffCheckMarksKey,
    tabSizeDefault,
    tabSizeKey,
    underlineLinksDefault,
    underlineLinksKey,
    useCustomEditorKey,
    useCustomShellKey,
)
from github_desktop.tip import Tip, get_tip_sha, tip_equals
from github_desktop.welcome import (
    HasShownWelcomeFlowKey,
    has_shown_welcome_flow,
    mark_welcome_flow_complete,
)
from github_desktop.store import AppStore
from github_desktop.models import WelcomeStep


def _branch(name: str = "main", sha: str = "abc1234") -> Branch:
    return Branch(
        name=name,
        upstream=None,
        tip_sha=sha,
        type=BranchType.LOCAL,
        ref=f"refs/heads/{name}",
    )


def test_tab_size_default_matches_desktop() -> None:
    assert tabSizeDefault == 8
    assert Settings().tab_size == 8
    assert tabSizeKey == "tab-size"
    assert useCustomEditorKey == "use-custom-editor"
    assert useCustomShellKey == "use-custom-shell"
    assert underlineLinksKey == "underline-links"
    assert underlineLinksDefault is True
    assert showDiffCheckMarksKey == "diff-check-marks-visible"
    assert showDiffCheckMarksDefault is True
    assert showChangesFilterKey == "show-changes-filter"
    assert showChangesFilterDefault is True
    assert commitSpellcheckEnabledKey == "commit-spellcheck-enabled"
    assert commitSpellcheckEnabledDefault is True
    assert repositoryIndicatorsEnabledKey == "enable-repository-indicators"


def test_has_shown_welcome_flow_local_storage_and_legacy(isolated_config) -> None:
    assert HasShownWelcomeFlowKey == "has-shown-welcome-flow"
    assert has_shown_welcome_flow() is False
    assert has_shown_welcome_flow(True) is True
    mark_welcome_flow_complete()
    assert has_shown_welcome_flow() is True
    assert has_shown_welcome_flow(False) is True


def test_finish_welcome_sets_local_storage(isolated_config) -> None:
    store = AppStore()
    assert store.welcome_step == WelcomeStep.START
    store.finish_welcome()
    assert store.welcome_step is None
    assert has_shown_welcome_flow() is True
    again = AppStore()
    assert again.welcome_step is None


def test_get_tip_sha_and_tip_equals() -> None:
    branch = _branch("main", "deadbeef")
    valid = Tip(kind=TipState.VALID, branch=branch)
    detached = Tip(kind=TipState.DETACHED, current_sha="cafebabe")
    unborn = Tip(kind=TipState.UNBORN, ref="refs/heads/main")
    unknown = Tip(kind=TipState.UNKNOWN)
    assert get_tip_sha(valid) == "deadbeef"
    assert get_tip_sha(detached) == "cafebabe"
    assert get_tip_sha(unborn) == "(unknown)"
    assert get_tip_sha(unknown) == "(unknown)"
    assert tip_equals(valid, Tip(kind=TipState.VALID, branch=_branch("main", "deadbeef")))
    assert not tip_equals(valid, detached)
    assert tip_equals(unborn, Tip(kind=TipState.UNBORN, ref="refs/heads/main"))
    assert not tip_equals(unborn, Tip(kind=TipState.UNBORN, ref="refs/heads/dev"))


def test_find_upstream_remote_matches_parent() -> None:
    parent = GitHubRepository(
        "desktop",
        "desktop",
        "https://github.com/desktop/desktop",
        "https://github.com/desktop/desktop.git",
    )
    remotes = [
        Remote("origin", "https://github.com/me/desktop.git"),
        Remote("upstream", "https://github.com/desktop/desktop.git"),
    ]
    assert UpstreamRemoteName == UPSTREAM_REMOTE_NAME == "upstream"
    found = find_upstream_remote(parent, remotes)
    assert found is not None
    assert found.name == "upstream"
    mismatch = [Remote("upstream", "https://github.com/other/other.git")]
    assert find_upstream_remote(parent, mismatch) is None
    assert find_upstream_remote(parent, [Remote("origin", parent.clone_url)]) is None
