"""Desktop AppError titles/body, getFileFromExceedsError, and errno wrapping."""

from __future__ import annotations

import errno

import pytest

from github_desktop.errno_exception import errno_code, is_errno_exception
from github_desktop.errors import CopilotError, GitError, GitNotFoundError
from github_desktop.git.runner import (
    coerce_to_buffer,
    coerce_to_string,
    git,
    is_max_buffer_exceeded_error,
)
from github_desktop.git_error_context import error_dialog_title, format_app_error_body
from github_desktop.http_status import HttpStatusCode
from github_desktop.models import PopupType, Repository, RetryAction, RetryActionType
from github_desktop.regex import get_file_from_exceeds_error
from github_desktop.store import AppStore


_TWO_FILE_STDERR = (
    "remote: error: File LargeFile.exe is 150.00 MB; this exceeds GitHub's file size limit of 100.00 MB\n"
    "remote: error: File AlsoTooLargeOfAFile.txt is 1.00 GB; this exceeds GitHub's file size limit of 100.00 MB\n"
)


def test_get_file_from_exceeds_error_desktop_example() -> None:
    assert get_file_from_exceeds_error(_TWO_FILE_STDERR) == [
        "LargeFile.exe (150.00 MB)",
        "AlsoTooLargeOfAFile.txt (1.00 GB)",
    ]


def test_get_file_from_exceeds_error_mismatch_returns_empty() -> None:
    only_begin = "remote: error: File LargeFile.exe is 150.00 MB\n"
    assert get_file_from_exceeds_error(only_begin) == []
    assert get_file_from_exceeds_error("") == []


def test_get_file_from_exceeds_error_replaces_first_is_only() -> None:
    stderr = (
        "remote: error: File weird is name.bin is 106.5 MB; this exceeds GitHub's file size limit of 100.00 MB\n"
    )
    # JS String.replace without /g replaces only the first `is `.
    assert get_file_from_exceeds_error(stderr) == ["weird (name.bin is 106.5 MB)"]


def test_error_dialog_title_matches_desktop_app_error() -> None:
    push = RetryAction(type=RetryActionType.PUSH, repo_id=1)
    clone = RetryAction(type=RetryActionType.CLONE, repo_id=1)
    assert error_dialog_title(copilot_quota=True) == "Quota exceeded"
    assert error_dialog_title(
        git_error="PushWithFileSizeExceedingLimit",
        retry_action=push,
        title="Failed to push",
    ) == "File size limit exceeded"
    assert error_dialog_title(retry_action=push) == "Failed to push"
    assert error_dialog_title(retry_clone=True) == "Clone failed"
    assert error_dialog_title(retry_action=clone) == "Clone failed"
    assert error_dialog_title(git_context={"kind": "create-repository"}) == "Failed creating repository"
    assert error_dialog_title() == "Error"


def test_format_app_error_body_lists_oversized_files() -> None:
    body = format_app_error_body(
        "The push operation includes a file which exceeds GitHub's file size restriction of 100MB. Please remove the file from history and try again.",
        git_error="PushWithFileSizeExceedingLimit",
        stderr=_TWO_FILE_STDERR,
    )
    assert "Files that exceed the limit" in body
    assert "LargeFile.exe (150.00 MB)" in body
    assert "AlsoTooLargeOfAFile.txt (1.00 GB)" in body
    assert "https://gh.io/lfs" in body
    assert "for more information on managing large files on GitHub" in body


def test_format_app_error_body_copilot_quota() -> None:
    body = format_app_error_body("You have reached your quota limit.", copilot_quota=True)
    assert "Upgrade to increase your limit." in body
    assert "https://github.com/features/copilot/plans" in body


def test_is_errno_exception_node_and_python() -> None:
    class NodeErrno(Exception):
        def __init__(self) -> None:
            super().__init__("spawn git ENOENT")
            self.code = "ENOENT"
            self.syscall = "spawn"

    assert is_errno_exception(NodeErrno())
    assert is_errno_exception(PermissionError(errno.EACCES, "Permission denied"))
    assert not is_errno_exception(Exception("nope"))
    assert not is_errno_exception("ENOENT")
    assert errno_code(PermissionError(errno.EACCES, "Permission denied")) == "EACCES"
    assert errno_code(NodeErrno()) == "ENOENT"


def test_coerce_to_string_and_buffer_and_max_buffer() -> None:
    assert coerce_to_string(b"abc") == "abc"
    assert coerce_to_string("abc") == "abc"
    assert coerce_to_buffer("abc") == b"abc"
    assert coerce_to_buffer(b"abc") == b"abc"
    class ExecError(Exception):
        code = "ERR_CHILD_PROCESS_STDIO_MAXBUFFER"
    assert is_max_buffer_exceeded_error(ExecError())
    assert not is_max_buffer_exceeded_error(GitError("nope"))


def test_git_wraps_oserror_as_failed_to_execute(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr("github_desktop.git.runner.subprocess.run", boom)
    with pytest.raises(RuntimeError, match=r"Failed to execute status: EACCES"):
        git(["status"], tmp_path, name="status")


def test_git_file_not_found_stays_git_not_found(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr("github_desktop.git.runner.subprocess.run", boom)
    with pytest.raises(GitNotFoundError):
        git(["status"], tmp_path, name="status")


def test_handle_remote_error_file_size_popup(isolated_config, tmp_path) -> None:
    store = AppStore()
    repo = Repository(id=1, path=str(tmp_path), name="x")
    store._retry_action = RetryAction(type=RetryActionType.PUSH, repo_id=1)
    store._handle_remote_error(
        repo,
        GitError(
            "too big",
            git_error="PushWithFileSizeExceedingLimit",
            stderr=_TWO_FILE_STDERR,
        ),
    )
    assert store.popup is not None and store.popup.type == PopupType.ERROR
    payload = store.popup.payload
    assert payload["git_error"] == "PushWithFileSizeExceedingLimit"
    assert "LargeFile.exe is 150.00 MB" in payload["stderr"]
    assert error_dialog_title(
        git_error=payload["git_error"],
        retry_action=payload["retry_action"],
    ) == "File size limit exceeded"


def test_popup_error_copilot_quota(isolated_config) -> None:
    store = AppStore()
    store._popup_error(CopilotError("You have reached your quota limit.", HttpStatusCode.PaymentRequired))
    assert store.popup is not None and store.popup.type == PopupType.ERROR
    assert store.popup.payload.get("copilot_quota") is True
    assert error_dialog_title(copilot_quota=True) == "Quota exceeded"
