"""Application actions and their keyboard shortcuts.

One table drives three things: the QML global drawer and menus, the
``Kirigami.Action`` shortcuts, and the enable/disable state the store computes
in :mod:`github_desktop.menu_update`. Keeping it declarative means the parity
tests can assert on the bindings without instantiating a window.

Shortcut strings are Qt's portable syntax (``QKeySequence``), so they render
as the platform expects and match what Plasma shows in its shortcut editor.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import PopupType


@dataclass(frozen=True)
class ActionSpec:
    """One invocable command: what it is called, and how to reach it."""

    name: str
    text: str
    shortcuts: tuple[str, ...] = ()
    icon: str = ""
    #: ``menu_update`` id this action mirrors, when it has one.
    menu_id: str = ""
    #: Group used to lay the global drawer out.
    group: str = "repository"
    separator_before: bool = False
    extra: dict = field(default_factory=dict)


# Desktop's Linux accelerators, translated to Qt key sequences.
ACTIONS: tuple[ActionSpec, ...] = (
    ActionSpec("new-repository", "New repository…", ("Ctrl+N",), "add", "create-repository", "file"),
    ActionSpec("add-local-repository", "Add local repository…", ("Ctrl+O",), "folder-open", "add-repository", "file"),
    ActionSpec("clone-repository", "Clone repository…", ("Ctrl+Shift+O",), "clone", "clone-repository", "file"),
    ActionSpec("preferences", "Settings…", ("Ctrl+,",), "settings", "preferences", "file", separator_before=True),
    ActionSpec("show-changes", "Changes", ("Ctrl+1",), "changes", "show-changes", "view"),
    ActionSpec("show-history", "History", ("Ctrl+2",), "history", "show-history", "view"),
    ActionSpec("choose-repository", "Repository list", ("Ctrl+T",), "repository", "choose-repository", "view"),
    ActionSpec("show-branches", "Branch list", ("Ctrl+B",), "branch", "show-branches", "view"),
    ActionSpec("go-to-commit-message", "Commit message", ("Ctrl+G",), "commit", "go-to-commit-message", "view"),
    ActionSpec(
        "generate-commit-message",
        "Generate commit message with Copilot",
        (),
        "lightbulb",
        "generate-commit-message",
        "view",
    ),
    ActionSpec("toggle-changes-filter", "Filter changed files", ("Ctrl+L",), "search", "toggle-changes-filter", "view"),
    ActionSpec("toggle-stash", "Stashed changes", ("Ctrl+H",), "stash", "toggle-stashed-changes", "view"),
    ActionSpec("zoom-in", "Zoom in", ("Ctrl+=", "Ctrl++"), "", "zoom-in", "view"),
    ActionSpec("zoom-out", "Zoom out", ("Ctrl+-",), "", "zoom-out", "view"),
    ActionSpec("zoom-reset", "Reset zoom", ("Ctrl+0",), "", "reset-zoom", "view"),
    ActionSpec("toggle-fullscreen", "Full screen", ("F11",), "", "toggle-full-screen", "view"),
    ActionSpec("push", "Push", ("Ctrl+P",), "push", "push", "repository"),
    ActionSpec("pull", "Pull", ("Ctrl+Shift+P",), "pull", "pull", "repository"),
    ActionSpec("fetch", "Fetch", ("Ctrl+Shift+T",), "fetch", "fetch", "repository"),
    ActionSpec("force-push", "Force push", (), "force-push", "force-push", "repository"),
    ActionSpec("remove-repository", "Remove repository…", ("Ctrl+Backspace",), "remove", "remove-repository", "repository"),
    ActionSpec("view-on-github", "View on GitHub", ("Ctrl+Shift+G",), "browser", "view-repository-on-github", "repository"),
    ActionSpec("open-in-shell", "Open in terminal", ("Ctrl+`",), "terminal", "open-in-shell", "repository"),
    ActionSpec("open-working-directory", "Show in file manager", ("Ctrl+Shift+F",), "folder-open", "open-working-directory", "repository"),
    ActionSpec("open-external-editor", "Open in editor", ("Ctrl+Shift+A",), "editor", "open-external-editor", "repository"),
    ActionSpec("create-issue", "Create issue on GitHub", ("Ctrl+I",), "add", "create-issue-in-repository-on-github", "repository"),
    ActionSpec("repository-settings", "Repository settings…", (), "settings", "show-repository-settings", "repository"),
    ActionSpec("create-branch", "New branch…", ("Ctrl+Shift+N",), "branch", "create-branch", "branch"),
    ActionSpec("rename-branch", "Rename branch…", ("Ctrl+Shift+R",), "", "rename-branch", "branch"),
    ActionSpec("delete-branch", "Delete branch…", ("Ctrl+Shift+D",), "delete", "delete-branch", "branch"),
    ActionSpec("discard-all", "Discard all changes…", ("Ctrl+Shift+Backspace",), "discard", "discard-all-changes", "branch"),
    ActionSpec("stash-all", "Stash all changes", ("Ctrl+Shift+S",), "stash", "stash-all-changes", "branch"),
    ActionSpec("update-from-default", "Update from default branch", ("Ctrl+Shift+U",), "pull", "update-branch-with-contribution-target-branch", "branch"),
    ActionSpec("compare-to-branch", "Compare to branch", ("Ctrl+Shift+B",), "diff", "compare-to-branch", "branch"),
    ActionSpec("merge-branch", "Merge into current branch…", ("Ctrl+Shift+M",), "merge", "merge-branch", "branch"),
    ActionSpec("squash-merge", "Squash and merge…", ("Ctrl+Shift+H",), "merge", "squash-and-merge-branch", "branch"),
    ActionSpec("rebase-branch", "Rebase current branch…", ("Ctrl+Shift+E",), "merge", "rebase-branch", "branch"),
    ActionSpec("compare-on-github", "Compare on GitHub", ("Ctrl+Shift+C",), "browser", "compare-on-github", "branch"),
    ActionSpec("branch-on-github", "View branch on GitHub", ("Ctrl+Alt+B",), "browser", "branch-on-github", "branch"),
    ActionSpec("open-pull-request", "Create pull request", ("Ctrl+R",), "pull-request", "open-pull-request", "branch"),
    ActionSpec("preview-pull-request", "Preview pull request", ("Alt+P",), "pull-request", "preview-pull-request", "branch"),
    # Desktop `exitAccelerator` is Ctrl+Q on Linux; the drawer's Quit entry
    # binds StandardKey.Quit, which resolves to the same sequence.
    ActionSpec("quit", "Quit", ("Ctrl+Q",), "close", "exit", "file"),
    ActionSpec("select-all", "Select all", ("Ctrl+A",), "", "select-all", "edit"),
    # Ctrl+Z is text undo in the commit message, never `git reset`. Undoing a
    # commit is a deliberate action from the Changes sidebar.
    ActionSpec("edit-undo", "Undo", ("Ctrl+Z",), "discard", "", "edit"),
    ActionSpec("edit-redo", "Redo", ("Ctrl+Shift+Z", "Ctrl+Y"), "", "", "edit"),
    ActionSpec("find", "Find", ("Ctrl+F",), "search", "", "edit"),
    ActionSpec("increase-resizable", "Widen sidebar", ("Ctrl+9",), "", "", "edit"),
    ActionSpec("decrease-resizable", "Narrow sidebar", ("Ctrl+8",), "", "", "edit"),
    ActionSpec("install-cli", "Install command line tool…", (), "terminal", "install-cli", "help"),
    ActionSpec("create-fork", "Create a fork", (), "branch", "create-fork", "branch"),
    ActionSpec("about", "About GitHub Desktop", (), "help", "about", "help"),
)

ACTIONS_BY_NAME = {action.name: action for action in ACTIONS}

# Actions that only open a dialog; the bridge routes the rest to the store.
POPUP_ACTIONS: dict[str, PopupType] = {
    "new-repository": PopupType.CREATE_REPOSITORY,
    "add-local-repository": PopupType.ADD_REPOSITORY,
    "clone-repository": PopupType.CLONE_REPOSITORY,
    "preferences": PopupType.PREFERENCES,
    "remove-repository": PopupType.REMOVE_REPOSITORY,
    "repository-settings": PopupType.REPOSITORY_SETTINGS,
    "create-branch": PopupType.CREATE_BRANCH,
    "rename-branch": PopupType.RENAME_BRANCH,
    "delete-branch": PopupType.DELETE_BRANCH,
    "about": PopupType.ABOUT,
}


def shortcuts_for(name: str) -> tuple[str, ...]:
    """Key sequences bound to ``name``."""
    action = ACTIONS_BY_NAME.get(name)
    return action.shortcuts if action else ()


def action_for_shortcut(sequence: str) -> str | None:
    """Reverse lookup: which action a key sequence triggers."""
    for action in ACTIONS:
        if sequence in action.shortcuts:
            return action.name
    return None


def actions_in_group(group: str) -> list[ActionSpec]:
    return [action for action in ACTIONS if action.group == group]
