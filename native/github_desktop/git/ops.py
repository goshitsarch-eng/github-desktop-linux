"""High-level Git operations matching GitHub Desktop's lib/git API."""

from __future__ import annotations

import os
import re
import signal
import subprocess
from dataclasses import dataclass
from functools import cmp_to_key
from pathlib import Path
from threading import Event
from typing import Callable, Iterable, Mapping, Sequence

from ..compare import case_insensitive_compare
from ..format_commit_message import format_commit_message
from ..errors import (
    GitError,
    GitNotFoundError,
    NotARepositoryError,
    classify_git_error,
    get_description_for_error,
    is_auth_failure_error,
    parse_bad_config_value_error_info,
)
from ..logging import get_logger
from ..remove_remote_prefix import remove_remote_prefix
from ..models import (
    DESKTOP_STASH_MARKER,
    FORKED_REMOTE_PREFIX,
    IMAGE_EXTENSIONS,
    MAX_REASONABLE_DIFF_SIZE,
    RESERVED_BRANCH_REFS,
    AppFileStatusKind,
    AheadBehind,
    Author,
    BinaryDiff,
    Branch,
    BranchType,
    CherryPickResult,
    COMMIT_BATCH_SIZE,
    NULL_TREE_SHA,
    ChangesetData,
    Commit,
    CommitIdentity,
    CommitMessage,
    CommitOneLine,
    CommittedFileChange,
    ComputedAction,
    DiffSelection,
    DiffSelectionType,
    DiffType,
    FileDiff,
    FileStatus,
    GitStatusEntry,
    GitHubRepository,
    IStatusResult,
    ImageDiff,
    IndexStatus,
    LargeTextDiff,
    ManualConflictResolution,
    MergeResult,
    MergeTreeResult,
    PullRequest,
    RebaseInternalState,
    RebaseResult,
    Remote,
    Repository,
    StashEntry,
    SubmoduleDiff,
    SubmoduleStatus,
    TextDiff,
    TrackingBranch,
    UnrenderableDiff,
    UPSTREAM_REMOTE_NAME,
    ORIGIN_REMOTE_NAME,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
    format_as_local_ref,
    get_old_path_or_default,
)
from .delimiter import create_for_each_ref_parser, create_log_parser
from .diff import (
    format_discard_patch,
    format_partial_patch,
    get_media_type,
    is_buffer_too_large,
    is_diff_too_large,
    is_valid_buffer,
    parse_line_endings_warning,
    parse_unified_diff,
    selectable_line_indices,
)
from .progress import (
    CHECKOUT_STEPS,
    CLONE_STEPS,
    FETCH_STEPS,
    PULL_STEPS,
    PUSH_STEPS,
    REVERT_STEPS,
    GitCherryPickParser,
    GitProgress,
    GitProgressParser,
    GitRebaseParser,
    MultiCommitProgress,
    format_rebase_value,
)
from .runner import (
    GitResult,
    abort_git_process,
    env_for_proxy,
    env_for_remote,
    find_git,
    git,
    git_path_is_repository,
    git_user_agent,
    resolve_repository_root,
    _prepare_env,
)
from .status import (
    CONFLICT_STATUS_CODES,
    StatusEntry,
    StatusHeader,
    convert_to_app_status,
    parse_porcelain_status,
    parse_status_headers,
    should_skip_entry,
)

log = get_logger()

ProgressCb = Callable[[str, float], None]


@dataclass(frozen=True)
class SubmoduleEntry:
    sha: str
    path: str
    describe: str


def _progress_adapter(cb: ProgressCb) -> Callable[[GitProgress], None]:
    def on_event(event: GitProgress) -> None:
        text = event.details.text if event.details else event.text
        cb(text, event.percent)

    return on_event


def get_status(
    repo_path: str,
    include_untracked: bool = True,
    reject_on_error: bool = False,
) -> IStatusResult | None:
    """Desktop `getStatus`. `rejectOnError` uses successExitCodes `{0}` only."""
    if not os.path.isdir(repo_path):
        return IStatusResult(exists=False)
    args = ["--no-optional-locks", "status"]
    if include_untracked:
        args += ["--untracked-files=all"]
    args += ["--branch", "--porcelain=2", "-z"]
    success = {0} if reject_on_error else {0, 128}
    try:
        result = git(args, repo_path, success_exit_codes=success, name="getStatus", binary=True)
    except GitError:
        if reject_on_error:
            raise
        return None
    if result.exit_code == 128:
        return None
    parsed = parse_porcelain_status(result.stdout_bytes or result.stdout.encode("utf-8"))
    headers = [p for p in parsed if isinstance(p, StatusHeader)]
    entries = [p for p in parsed if isinstance(p, StatusEntry)]
    info = parse_status_headers(headers)
    files: dict[str, WorkingDirectoryFileChange] = {}
    conflicted = []
    marker_counts: dict[str, int] = {}
    binary_paths: set[str] = set()
    merge_head_found = _path_exists(repo_path, ".git/MERGE_HEAD")
    rebase_internal_state = get_rebase_internal_state(repo_path)
    conflicted_entries = [entry for entry in entries if entry.status_code in CONFLICT_STATUS_CODES]
    if conflicted_entries:
        try:
            marker_counts = get_files_with_conflict_markers(repo_path)
        except GitError:
            marker_counts = {}
        try:
            if merge_head_found:
                binary_ref = "MERGE_HEAD"
            elif rebase_internal_state is not None:
                binary_ref = "REBASE_HEAD"
            else:
                binary_ref = "HEAD"
            binary_paths = set(
                get_binary_paths(repo_path, binary_ref, [entry.path for entry in conflicted_entries])
            )
        except GitError:
            binary_paths = set()
    for entry in entries:
        if should_skip_entry(entry):
            continue
        if entry.status_code in CONFLICT_STATUS_CODES:
            conflicted.append(entry)
        if entry.status_code == "??":
            files.pop(entry.path, None)
        status = convert_to_app_status(entry)
        if status.kind == AppFileStatusKind.CONFLICTED:
            both_sides = entry.status_code in {"UU", "AA"} or entry.path in marker_counts
            if both_sides and entry.path not in binary_paths:
                status.conflict_marker_count = marker_counts.get(entry.path, 0)
            else:
                status.conflict_marker_count = None
        initial = DiffSelectionType.ALL
        if (
            status.kind == AppFileStatusKind.MODIFIED
            and status.submodule_status is not None
            and not status.submodule_status.commit_changed
        ):
            initial = DiffSelectionType.NONE
        files[entry.path] = WorkingDirectoryFileChange(
            entry.path,
            status,
            DiffSelection.from_initial_selection(initial),
        )
    file_list = list(files.values())
    file_list.sort(key=cmp_to_key(lambda a, b: case_insensitive_compare(a.path, b.path)))
    ab = info["ahead_behind"]
    ahead_behind = AheadBehind(*ab) if isinstance(ab, tuple) else None
    return IStatusResult(
        exists=True,
        current_branch=info["current_branch"],  # type: ignore[arg-type]
        current_upstream_branch=info["current_upstream_branch"],  # type: ignore[arg-type]
        current_tip=info["current_tip"],  # type: ignore[arg-type]
        branch_ahead_behind=ahead_behind,
        working_directory=WorkingDirectoryStatus.from_files(file_list),
        merge_head_found=merge_head_found,
        squash_msg_found=_path_exists(repo_path, ".git/SQUASH_MSG"),
        rebase_internal_state=rebase_internal_state,
        is_cherry_picking_head_found=_path_exists(repo_path, ".git/CHERRY_PICK_HEAD"),
        do_conflicted_files_exist=bool(conflicted),
    )


def _path_exists(repo: str, rel: str) -> bool:
    return os.path.exists(os.path.join(repo, rel))


def _git_dir(repo: str) -> str:
    result = git(["rev-parse", "--git-dir"], repo, name="gitDir")
    git_dir = result.stdout.strip()
    if not os.path.isabs(git_dir):
        git_dir = os.path.normpath(os.path.join(repo, git_dir))
    return git_dir


def _conflict_marker_count(repo: str, path: str) -> int:
    full = os.path.join(repo, path)
    try:
        with open(full, "rb") as fh:
            data = fh.read(2_000_000)
        text = data.decode("utf-8", errors="ignore")
        return len(re.findall(r"^<<<<<<< ", text, re.M))
    except OSError:
        return 0


def get_rebase_internal_state(repo_path: str) -> RebaseInternalState | None:
    try:
        git_dir = _git_dir(repo_path)
    except GitError:
        git_dir = os.path.join(repo_path, ".git")
    rebase_merge = os.path.join(git_dir, "rebase-merge")
    rebase_apply = os.path.join(git_dir, "rebase-apply")
    directory = rebase_merge if os.path.isdir(rebase_merge) else (
        rebase_apply if os.path.isdir(rebase_apply) else None
    )
    if directory is None:
        return None

    def read(name: str) -> str | None:
        p = os.path.join(directory, name)
        try:
            return Path(p).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    head_name = read("head-name") or read("onto") or ""
    head_name = head_name.replace("refs/heads/", "")
    orig = read("orig-head") or read("onto") or ""
    onto = read("onto") or orig
    if not head_name:
        return None
    return RebaseInternalState(head_name, onto, orig)


def get_rebase_snapshot(repo: str) -> dict[str, object] | None:
    """Desktop `getRebaseSnapshot`: msgnum/end progress plus commits being replayed."""
    try:
        git_dir = _git_dir(repo)
    except GitError:
        git_dir = os.path.join(repo, ".git")
    rebase_head = os.path.join(git_dir, "REBASE_HEAD")
    if not os.path.exists(rebase_head):
        if get_rebase_internal_state(repo) is None:
            return None
    directory = os.path.join(git_dir, "rebase-merge")
    if not os.path.isdir(directory):
        directory = os.path.join(git_dir, "rebase-apply")
    if not os.path.isdir(directory):
        return None

    def read(name: str) -> str | None:
        try:
            return Path(os.path.join(directory, name)).read_text(encoding="utf-8").strip()
        except OSError:
            return None

    next_text = read("msgnum") or read("next") or ""
    last_text = read("end") or read("last") or ""
    try:
        next_n = int(next_text)
        last_n = int(last_text)
    except ValueError:
        return None
    original = read("orig-head")
    onto = read("onto")
    if next_n <= 0 or last_n <= 0 or not original or not onto:
        return None
    commits = get_commits_between(repo, onto, original)
    if not commits:
        return None
    index = next_n - 1
    summary = commits[index].summary if 0 <= index < len(commits) else ""
    return {
        "commits": commits,
        "position": next_n,
        "total": last_n,
        "value": format_rebase_value(next_n / last_n),
        "current_commit_summary": summary,
        "progress": MultiCommitProgress(next_n, last_n, summary, format_rebase_value(next_n / last_n)),
    }


def is_binary_path(repo: str, path: str) -> bool:
    try:
        result = git(["diff", "--numstat", "HEAD", "--", path], repo, name="numstat")
        line = result.stdout.strip().splitlines()[:1]
        if line and line[0].startswith("-\t-\t"):
            return True
    except GitError:
        pass
    return False


_BINARY_LIST_RE = re.compile(r"-\t-\t(?:\0.+\0)?([^\0]*)", re.I)


def get_binary_paths(repo: str, ref: str, conflicted_paths: Sequence[str] = ()) -> list[str]:
    """Desktop `getBinaryPaths`: git-detected binaries plus `merge=binary` files."""
    result = git(["diff", "--numstat", "-z", ref], repo, success_exit_codes={0, 1}, name="getBinaryPaths")
    detected = [m.group(1) for m in _BINARY_LIST_RE.finditer(result.stdout)]
    using_binary_driver: list[str] = []
    paths = [p for p in conflicted_paths if p]
    if paths:
        check = git(
            ["check-attr", "--stdin", "-z", "merge"],
            repo,
            stdin="\0".join(paths) + "\0",
            name="getConflictedFilesUsingBinaryMergeDriver",
        )
        parser = create_log_parser({"path": "", "attr": "", "value": ""})
        using_binary_driver = [
            item["path"]
            for item in parser.parse(check.stdout)
            if item.get("attr") == "merge" and item.get("value") == "binary" and item.get("path")
        ]
    seen: set[str] = set()
    out: list[str] = []
    for path in [*detected, *using_binary_driver]:
        if path and path not in seen:
            seen.add(path)
            out.append(path)
    return out


def _diff_flags(hide_whitespace: bool = False, context_lines: int | None = None) -> list[str]:
    """Desktop working-directory / range diffs: `--patch-with-raw -z`."""
    args = ["diff", "--no-ext-diff", "--patch-with-raw", "-z", "--no-color"]
    if hide_whitespace:
        args.append("-w")
    if context_lines is not None:
        args.append(f"-U{int(context_lines)}")
    return args


def _append_old_path(args: list[str], path: str, status: FileStatus | None) -> None:
    old = get_old_path_or_default(path=path, status=status)
    if old and old != path:
        args.append(ensure_relative_path(old))


def ensure_relative_path(path: str) -> str:
    """Desktop `ensureRelativePath`: prefix absolute paths with `:(top,literal)`."""
    return f":(top,literal){path}" if os.path.isabs(path) else path


def get_working_directory_diff(
    repo: str,
    file: WorkingDirectoryFileChange,
    hide_whitespace: bool = False,
    context_lines: int | None = None,
) -> FileDiff:
    """Desktop `getWorkingDirectoryDiff`."""
    args = _diff_flags(hide_whitespace, context_lines)
    success = {0, 1}
    if file.status.kind in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED) and file.status.submodule_status is None:
        # `git diff --no-index` uses diff(1) exit codes: 0 none, 1 changes.
        success.add(1)
        args += ["--no-index", "--", "/dev/null", file.path]
    elif file.status.kind == AppFileStatusKind.RENAMED:
        args += ["--", ensure_relative_path(file.path)]
    else:
        args += ["HEAD", "--", ensure_relative_path(file.path)]
    result = git(args, repo, success_exit_codes=success, name="getWorkingDirectoryDiff")
    return _diff_from_result(repo, file.path, file.status, result, commitish=None)


MAX_PARTIAL_BLOB_BYTES = 256 * 1024


def get_blob_contents(repo: str, commitish: str, path: str) -> bytes:
    """Desktop `getBlobContents`: successExitCodes {0, 1}; exit 128 throws."""
    result = git(
        ["show", f"{commitish}:{path}"],
        repo,
        success_exit_codes={0, 1},
        name="getBlobContents",
        binary=True,
    )
    return result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")


def get_partial_blob_contents(
    repo: str,
    commitish: str,
    path: str,
    length: int = MAX_PARTIAL_BLOB_BYTES,
) -> bytes | None:
    """Desktop `getPartialBlobContents` always uses CatchPathNotInRef."""
    return get_partial_blob_contents_catch_path_not_in_ref(repo, commitish, path, length)


def get_partial_blob_contents_catch_path_not_in_ref(
    repo: str,
    commitish: str,
    path: str,
    length: int = MAX_PARTIAL_BLOB_BYTES,
) -> bytes | None:
    """Desktop `getPartialBlobContentsCatchPathNotInRef`: None when the path is not in the ref."""
    from ..errors import classify_git_error

    cmd = [find_git(), "show", f"{commitish}:{path}"]
    proc = subprocess.Popen(
        cmd,
        cwd=str(repo),
        env=_prepare_env(None),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    chunks: list[bytes] = []
    total = 0
    stderr_bytes = b""
    try:
        stdout = proc.stdout
        assert stdout is not None
        while total < length:
            chunk = stdout.read(min(65536, length - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if proc.poll() is None:
            abort_git_process(proc)
        else:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                abort_git_process(proc)
    finally:
        if proc.stderr is not None:
            try:
                stderr_bytes = proc.stderr.read()
            except Exception:
                pass
        if proc.poll() is None:
            abort_git_process(proc)
    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    if classify_git_error(stderr_text) == "PathExistsButNotInRef":
        return None
    data = b"".join(chunks)[:length]
    code = proc.returncode
    # Truncation aborts the process (Desktop maxBuffer); keep the bytes we have.
    if code in {0, None, -signal.SIGTERM, -signal.SIGKILL, 1}:
        return data
    raise GitError(
        stderr_text or "getPartialBlobContents failed",
        args=cmd[1:],
        exit_code=code,
        stderr=stderr_text,
        git_error=classify_git_error(stderr_text),
        path=str(repo),
    )


def get_working_directory_lines(repo: str, path: str) -> list[str]:
    from ..file_system import read_partial_file

    full = os.path.join(repo, path)
    try:
        data = read_partial_file(full, 0, MAX_PARTIAL_BLOB_BYTES - 1)
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def get_blob_lines(repo: str, commitish: str, path: str) -> list[str]:
    try:
        data = get_blob_contents(repo, commitish, path)
    except GitError:
        return []
    if not data:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def get_partial_blob_lines(
    repo: str,
    commitish: str,
    path: str,
    length: int = MAX_PARTIAL_BLOB_BYTES,
) -> list[str]:
    try:
        data = get_partial_blob_contents(repo, commitish, path, length)
    except GitError:
        return []
    if not data:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def get_commit_diff(
    repo: str,
    path: str,
    commitish: str,
    status: FileStatus | None = None,
    hide_whitespace: bool = False,
    context_lines: int | None = None,
) -> FileDiff:
    """Desktop `getCommitDiff`: `git log -m -1 --first-parent --patch-with-raw`."""
    args = ["log", commitish]
    if hide_whitespace:
        args.append("-w")
    args += ["-m", "-1", "--first-parent", "--patch-with-raw", "--format=", "-z", "--no-color"]
    if context_lines is not None:
        args.append(f"-U{int(context_lines)}")
    args += ["--", ensure_relative_path(path)]
    _append_old_path(args, path, status)
    result = git(args, repo, success_exit_codes={0, 1}, name="getCommitDiff")
    return _diff_from_result(repo, path, status or FileStatus(AppFileStatusKind.MODIFIED), result, commitish)


def diff_from_raw_diff_output(output: str) -> str:
    """Desktop `diffFromRawDiffOutput`: last NUL-delimited piece is the unified patch."""
    if not output:
        return output
    pieces = output.split("\0")
    last = pieces[-1]
    if last:
        return last
    for piece in reversed(pieces[:-1]):
        if piece:
            return piece
    return output


def _diff_from_result(
    repo: str,
    path: str,
    status: FileStatus,
    result: GitResult,
    commitish: str | None,
) -> FileDiff:
    data = result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")
    if not is_valid_buffer(data):
        return UnrenderableDiff()
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return _image_diff(repo, path, status, commitish)
    if status.submodule_status is not None:
        return _submodule_diff(repo, path, status.submodule_status)
    text = result.stdout or data.decode("utf-8", errors="replace")
    patch = diff_from_raw_diff_output(text)
    parsed = parse_unified_diff(patch)
    if parsed.is_binary or ("Binary files" in patch or "GIT binary patch" in patch):
        if ext in IMAGE_EXTENSIONS:
            return _image_diff(repo, path, status, commitish)
        return BinaryDiff()
    endings = parse_line_endings_warning(result.stderr)
    if endings:
        parsed.line_endings_change = endings
    if is_buffer_too_large(data) or is_diff_too_large(parsed):
        return LargeTextDiff(
            text=parsed.text,
            hunks=parsed.hunks,
            line_endings_change=parsed.line_endings_change,
            max_line_number=parsed.max_line_number,
            has_hidden_bidi_chars=parsed.has_hidden_bidi_chars,
        )
    return parsed


def _show_blob(repo: str, spec: str, name: str) -> bytes | None:
    """Desktop `getBlobImage` uses `getBlobContents` ({0, 1}; 128 throws)."""
    result = git(["show", spec], repo, name=name, success_exit_codes={0, 1}, binary=True)
    return result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")


def _image_diff(repo: str, path: str, status: FileStatus, commitish: str | None) -> ImageDiff:
    previous = current = None
    full = os.path.join(repo, path)
    old_path = get_old_path_or_default(path=path, status=status)
    if commitish:
        if status.kind != AppFileStatusKind.DELETED:
            current = _show_blob(repo, f"{commitish}:{path}", "showImageNew")
        if status.kind == AppFileStatusKind.DELETED:
            previous = _show_blob(repo, f"{commitish}^:{old_path}", "showImage")
        elif status.kind not in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
            previous = _show_blob(repo, f"{commitish}^:{old_path}", "showImage")
    else:
        if status.kind not in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
            previous = _show_blob(repo, f"HEAD:{old_path}", "showImage")
        if status.kind != AppFileStatusKind.DELETED:
            try:
                with open(full, "rb") as fh:
                    current = fh.read()
            except OSError:
                current = None
    media = get_media_type(os.path.splitext(path)[1])
    return ImageDiff(previous=previous, current=current, previous_media_type=media, current_media_type=media)


def _submodule_diff(repo: str, path: str, status: SubmoduleStatus) -> SubmoduleDiff:
    old_sha = new_sha = url = None
    try:
        result = git(["diff", "HEAD", "--", path], repo, success_exit_codes={0, 1}, name="subDiff")
        for line in result.stdout.splitlines():
            if line.startswith("-Subproject commit "):
                old_sha = line.split()[-1]
            if line.startswith("+Subproject commit "):
                new_sha = line.split()[-1].replace("-dirty", "")
        cfg = git(["config", "-f", ".gitmodules", "--get", f"submodule.{path}.url"], repo, success_exit_codes={0, 1}, name="subUrl")
        url = cfg.stdout.strip() or None
    except GitError:
        pass
    return SubmoduleDiff(full_path=os.path.join(repo, path), path=path, status=status, old_sha=old_sha, new_sha=new_sha, url=url)


def unstage_all(repo: str) -> None:
    """Desktop `unstageAll`: `git reset -- .`. Accept 128 for unborn HEAD."""
    git(["reset", "--", "."], repo, success_exit_codes={0, 128}, name="unstageAll")


def unstage_all_files(repo: str) -> None:
    """Remove every path from the index, leaving the working tree intact.

    Desktop `unstageAllFiles`: `git rm --cached -r -f .`. Mixed reset cannot
    walk `HEAD` after the first commit is deleted.
    """
    git(
        ["rm", "--cached", "-r", "-f", "."],
        repo,
        success_exit_codes={0, 1, 128},
        name="unstageAllFiles",
    )


def update_index(
    repo: str,
    paths: Sequence[str],
    *,
    add: bool = True,
    remove: bool = True,
    force_remove: bool = False,
    replace: bool = True,
) -> None:
    if not paths:
        return
    args = ["update-index"]
    if add:
        args.append("--add")
    if remove or force_remove:
        args.append("--remove")
    if force_remove:
        args.append("--force-remove")
    if replace:
        args.append("--replace")
    args += ["-z", "--stdin"]
    git(args, repo, stdin="\0".join(paths), name="updateIndex")


def apply_patch_to_index(repo: str, file: WorkingDirectoryFileChange) -> None:
    if file.status.kind == AppFileStatusKind.RENAMED and file.status.old_path:
        git(["add", "--u", "--", file.status.old_path], repo, name="applyRenameOld")
        ls = git(["ls-tree", "HEAD", "--", file.status.old_path], repo, name="lsTree")
        if ls.stdout.strip():
            info = ls.stdout.split("\t", 1)[0]
            parts = info.split()
            if len(parts) >= 3:
                mode, _typ, oid = parts[0], parts[1], parts[2]
                git(
                    ["update-index", "--add", "--cacheinfo", mode, oid, file.path],
                    repo,
                    name="cacheinfo",
                )
    diff = get_working_directory_diff(repo, file)
    if isinstance(diff, UnrenderableDiff):
        raise GitError(f"File diff is too large to generate a partial commit: {file.path}")
    if not isinstance(diff, (TextDiff, LargeTextDiff)):
        raise GitError(f"Can't create partial commit in binary file: {file.path}")
    if isinstance(diff, LargeTextDiff):
        diff = TextDiff(
            text=diff.text,
            hunks=diff.hunks,
            line_endings_change=diff.line_endings_change,
            max_line_number=diff.max_line_number,
            has_hidden_bidi_chars=diff.has_hidden_bidi_chars,
        )
    from_path = None if file.status.kind in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED) else file.path
    to_path = None if file.status.kind == AppFileStatusKind.DELETED else file.path
    selectable = set(selectable_line_indices(diff))
    selection = file.selection.with_selectable_lines(selectable)

    def selected(idx: int) -> bool:
        return selection.is_selected(idx)

    patch = format_partial_patch(diff, from_path, to_path, selected)
    if not patch.strip():
        return
    git(
        ["apply", "--cached", "--unidiff-zero", "--whitespace=nowarn", "-"],
        repo,
        stdin=patch,
        name="applyCached",
    )


def stage_files(repo: str, files: Sequence[WorkingDirectoryFileChange]) -> None:
    normal: list[str] = []
    old_renamed: list[str] = []
    deleted: list[str] = []
    partial: list[WorkingDirectoryFileChange] = []
    for file in files:
        if file.selection.get_selection_type() == DiffSelectionType.ALL:
            normal.append(file.path)
            if file.status.kind == AppFileStatusKind.RENAMED and file.status.old_path:
                old_renamed.append(file.status.old_path)
            elif file.status.kind == AppFileStatusKind.DELETED:
                deleted.append(file.path)
        elif file.selection.get_selection_type() != DiffSelectionType.NONE:
            partial.append(file)
    update_index(repo, old_renamed, force_remove=True)
    update_index(repo, normal)
    update_index(repo, deleted, force_remove=True)
    for file in partial:
        apply_patch_to_index(repo, file)


def create_commit(
    repo: str,
    message: str,
    files: Sequence[WorkingDirectoryFileChange],
    *,
    amend: bool = False,
) -> str:
    unstage_all(repo)
    stage_files(repo, files)
    args = ["commit", "-F", "-"]
    if amend:
        args.append("--amend")
    result = git(args, repo, stdin=message, name="createCommit")
    return _parse_commit_sha(result, repo)


def create_merge_commit(repo: str, files: Sequence[WorkingDirectoryFileChange], resolutions: dict[str, ManualConflictResolution] | None = None) -> str:
    resolutions = resolutions or {}
    for path, resolution in resolutions.items():
        stage_manual_resolution(repo, path, resolution)
    remaining = [f for f in files if f.path not in resolutions]
    stage_files(repo, remaining)
    result = git(["commit", "--no-edit", "--cleanup=strip"], repo, name="mergeCommit")
    return _parse_commit_sha(result, repo)


def stage_manual_resolution(
    repo: str,
    path: str | WorkingDirectoryFileChange,
    resolution: ManualConflictResolution,
    status: FileStatus | None = None,
) -> None:
    """Desktop `stageManualConflictResolution` including add/delete sides."""
    file: WorkingDirectoryFileChange | None = path if isinstance(path, WorkingDirectoryFileChange) else None
    file_path = file.path if file else str(path)
    file_status = status or (file.status if file else None)
    chosen: GitStatusEntry | None = None
    added_in_both = False
    if file_status is not None:
        chosen = file_status.them if resolution == ManualConflictResolution.THEIRS else file_status.us
        added_in_both = file_status.us == GitStatusEntry.ADDED and file_status.them == GitStatusEntry.ADDED
        if (
            file_status.has_conflict_markers
            and file_status.conflict_marker_count == 0
        ):
            return
    if chosen in (GitStatusEntry.UPDATED_BUT_UNMERGED, None) or added_in_both:
        checkout_conflicted_file(repo, file_path, resolution)
        if chosen is None and not added_in_both:
            git(["add", "--", file_path], repo, name="addResolved")
            return
    if chosen == GitStatusEntry.DELETED:
        remove_conflicted_file(repo, file_path)
        return
    add_conflicted_file(repo, file_path)


def add_conflicted_file(repo: str, file: str | WorkingDirectoryFileChange) -> None:
    """Desktop `addConflictedFile`."""
    path = file.path if isinstance(file, WorkingDirectoryFileChange) else file
    git(["add", "--", path], repo, name="addConflictedFile")


def checkout_conflicted_file(
    repo: str,
    file: str | WorkingDirectoryFileChange,
    resolution: ManualConflictResolution,
) -> None:
    """Desktop `checkoutConflictedFile` (`--ours` / `--theirs`)."""
    path = file.path if isinstance(file, WorkingDirectoryFileChange) else file
    git(["checkout", f"--{resolution.value}", "--", path], repo, name="checkoutConflictedFile")


def remove_conflicted_file(repo: str, file: str | WorkingDirectoryFileChange) -> None:
    """Desktop `removeConflictedFile`."""
    path = file.path if isinstance(file, WorkingDirectoryFileChange) else file
    git(["rm", "--", path], repo, name="removeConflictedFile")


def parse_commit_sha(result: GitResult, repo: str | None = None) -> str:
    """Desktop `parseCommitSHA`."""
    return _parse_commit_sha(result, repo)


def _parse_commit_sha(result: GitResult, repo: str | None = None) -> str:
    match = re.search(r"\[(?:.+\s+)?([0-9a-f]{7,40})\]", result.stdout)
    if match:
        return match.group(1)
    match = re.search(r"([0-9a-f]{7,40})", result.stdout)
    if match:
        return match.group(1)
    cwd = repo or os.getcwd()
    show = git(["rev-parse", "HEAD"], cwd, name="revParseHead")
    return show.stdout.strip()


def get_trailer_separator_characters(repo: str) -> str:
    """Desktop `getTrailerSeparatorCharacters` (default ``:``)."""
    return get_config_value(repo, "trailer.separators") or ":"


def is_co_authored_by_trailer(trailer: tuple[str, str] | str) -> bool:
    """Desktop `isCoAuthoredByTrailer`."""
    token = trailer[0] if isinstance(trailer, tuple) else trailer
    return token.lower() == "co-authored-by"


def parse_trailers(repo: str, commit_message: str) -> list[tuple[str, str]]:
    result = git(
        ["interpret-trailers", "--parse"],
        repo,
        stdin=commit_message,
        name="parseTrailers",
    )
    separators = get_trailer_separator_characters(repo)
    return parse_raw_unfolded_trailers(result.stdout, separators)


def parse_raw_unfolded_trailers(text: str, separators: str = ":") -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for line in text.splitlines():
        trailer = parse_single_unfolded_trailer(line, separators)
        if trailer:
            parsed.append(trailer)
    return parsed


def parse_single_unfolded_trailer(line: str, separators: str = ":") -> tuple[str, str] | None:
    for separator in separators:
        idx = line.find(separator)
        if idx > 0:
            return line[:idx].strip(), line[idx + 1 :].strip()
    return None


def merge_trailers(
    repo: str,
    commit_message: str,
    trailers: Sequence[tuple[str, str]] = (),
    *,
    unfold: bool = False,
) -> str:
    args = ["interpret-trailers", "--no-divider"]
    if unfold:
        args.append("--unfold")
    for token, value in trailers:
        args += ["--trailer", f"{token}={value}"]
    result = git(args, repo, stdin=commit_message, name="mergeTrailers")
    return result.stdout


def format_patch(repo: str, base: str, head: str) -> str:
    range_spec = f"{base}..{head}"
    result = git(
        ["format-patch", "--unified=1", "--minimal", "--stdout", range_spec],
        repo,
        name="formatPatch",
    )
    return result.stdout


def co_author_trailers(authors: Sequence[Author]) -> list[tuple[str, str]]:
    return [("Co-authored-by", f"{a.name} <{a.email}>") for a in authors]


# Desktop getCommits truncates summary/body with `subarray(0, 100 * 1024)`.
COMMIT_MESSAGE_MAX_BYTES = 100 * 1024


def get_commits(
    repo: str,
    revision_range: str | None = None,
    limit: int | None = COMMIT_BATCH_SIZE,
    skip: int | None = None,
    extra: Sequence[str] = (),
) -> list[Commit]:
    parser = create_log_parser(
        {
            "sha": "%H",
            "shortSha": "%h",
            "summary": "%s",
            "body": "%b",
            "author": "%an <%ae> %ad",
            "committer": "%cn <%ce> %cd",
            "parents": "%P",
            "trailers": "%(trailers:unfold,only)",
            "refs": "%D",
        }
    )
    args = ["log"]
    if revision_range:
        args.append(revision_range)
    args.append("--date=raw")
    if limit is not None:
        args.append(f"--max-count={limit}")
    if skip is not None:
        args.append(f"--skip={skip}")
    args += [*parser.format_args, "--no-show-signature", "--no-color", *extra, "--"]
    result = git(args, repo, success_exit_codes={0, 128}, name="getCommits")
    if result.exit_code == 128:
        return []
    commits: list[Commit] = []
    for entry in parser.parse(result.stdout):
        sha = entry.get("sha") or ""
        if not sha:
            continue
        tags: list[str] = []
        for part in (entry.get("refs") or "").split(", "):
            part = part.strip()
            if part.startswith("tag: "):
                tags.append(part[5:])
        parents = entry.get("parents") or ""
        commits.append(
            Commit(
                sha=sha,
                short_sha=entry.get("shortSha") or "",
                summary=(entry.get("summary") or "")[:COMMIT_MESSAGE_MAX_BYTES],
                body=((entry.get("body") or "")[:COMMIT_MESSAGE_MAX_BYTES]).strip(),
                author=CommitIdentity.parse_raw(entry.get("author") or ""),
                committer=CommitIdentity.parse_raw(entry.get("committer") or ""),
                parent_shas=parents.split() if parents else [],
                trailers=parse_raw_unfolded_trailers(entry.get("trailers") or "", ":"),
                tags=tags,
            )
        )
    return commits


def get_commit(repo: str, sha: str) -> Commit | None:
    commits = get_commits(repo, sha, limit=1)
    return commits[0] if commits else None


def get_changed_files(repo: str, sha: str) -> list[CommittedFileChange]:
    return get_changeset_data(repo, sha).files


SUBMODULE_FILE_MODE = "160000"


def map_submodule_status_file_modes(status: str, src_mode: str, dst_mode: str) -> SubmoduleStatus | None:
    """Desktop `mapSubmoduleStatusFileModes` for `git log --raw` file modes."""
    if src_mode == SUBMODULE_FILE_MODE and dst_mode == SUBMODULE_FILE_MODE and status == "M":
        return SubmoduleStatus(commit_changed=True, untracked_changes=False, modified_changes=False)
    if (src_mode == SUBMODULE_FILE_MODE and status == "D") or (dst_mode == SUBMODULE_FILE_MODE and status == "A"):
        return SubmoduleStatus(commit_changed=False, untracked_changes=False, modified_changes=False)
    return None


def map_raw_log_status(
    raw_status: str,
    old_path: str | None,
    src_mode: str,
    dst_mode: str,
) -> FileStatus:
    """Desktop `mapStatus` for `--raw` status letters plus R/C similarity scores."""
    status = raw_status.strip()
    sub = map_submodule_status_file_modes(status, src_mode, dst_mode)
    if status == "M":
        return FileStatus(AppFileStatusKind.MODIFIED, submodule_status=sub)
    if status == "A":
        return FileStatus(AppFileStatusKind.NEW, submodule_status=sub)
    if status == "?":
        return FileStatus(AppFileStatusKind.UNTRACKED, submodule_status=sub)
    if status == "D":
        return FileStatus(AppFileStatusKind.DELETED, submodule_status=sub)
    if status == "R" and old_path is not None:
        return FileStatus(
            AppFileStatusKind.RENAMED,
            old_path=old_path,
            submodule_status=sub,
            rename_includes_modifications=False,
        )
    if status == "C" and old_path is not None:
        return FileStatus(
            AppFileStatusKind.COPIED,
            old_path=old_path,
            submodule_status=sub,
            rename_includes_modifications=False,
        )
    if re.fullmatch(r"R[0-9]+", status) and old_path is not None:
        return FileStatus(
            AppFileStatusKind.RENAMED,
            old_path=old_path,
            submodule_status=sub,
            rename_includes_modifications=status != "R100",
        )
    if re.fullmatch(r"C[0-9]+", status) and old_path is not None:
        return FileStatus(
            AppFileStatusKind.COPIED,
            old_path=old_path,
            submodule_status=sub,
            rename_includes_modifications=False,
        )
    return FileStatus(AppFileStatusKind.MODIFIED, submodule_status=sub)


def parse_raw_log_with_numstat(stdout: str, sha: str, parent_commitish: str) -> ChangesetData:
    """Desktop `parseRawLogWithNumstat` for `-z --raw --numstat`."""
    files: list[CommittedFileChange] = []
    lines_added = 0
    lines_deleted = 0
    num_stat_count = 0
    lines = stdout.split("\0")
    index = 0
    while index < len(lines) - 1:
        line = lines[index]
        if line.startswith(":"):
            parts = line.split(" ")
            src_mode = (parts[0].replace(":", "") if parts else "") or ""
            dst_mode = parts[1] if len(parts) > 1 else ""
            status = parts[-1] if parts else ""
            old_path = None
            if status.startswith("R") or status.startswith("C"):
                index += 1
                old_path = lines[index] if index < len(lines) else None
            index += 1
            path = lines[index] if index < len(lines) else ""
            files.append(
                CommittedFileChange(
                    path=path,
                    status=map_raw_log_status(status, old_path, src_mode, dst_mode),
                    commitish=sha,
                    parent_commitish=parent_commitish,
                )
            )
        elif line:
            match = re.match(r"^(\d+|-)\t(\d+|-)\t", line)
            if match is None:
                index += 1
                continue
            added, deleted = match.group(1), match.group(2)
            lines_added += 0 if added == "-" else int(added)
            lines_deleted += 0 if deleted == "-" else int(deleted)
            if num_stat_count < len(files) and files[num_stat_count].status.kind in {
                AppFileStatusKind.COPIED,
                AppFileStatusKind.RENAMED,
            }:
                index += 2
            num_stat_count += 1
        index += 1
    return ChangesetData(files=files, lines_added=lines_added, lines_deleted=lines_deleted)


def get_changeset_data(repo: str, sha: str) -> ChangesetData:
    args = [
        "log",
        sha,
        "-C",
        "-M",
        "-m",
        "-1",
        "--no-show-signature",
        "--first-parent",
        "--raw",
        "--format=format:",
        "--numstat",
        "-z",
        "--",
    ]
    result = git(args, repo, name="getChangesFiles")
    return parse_raw_log_with_numstat(result.stdout, sha, f"{sha}^")


def get_commit_range_changed_files(
    repo: str,
    oldest_sha: str,
    newest_sha: str,
    *,
    use_null_tree: bool = False,
) -> ChangesetData:
    parent = NULL_TREE_SHA if use_null_tree else f"{oldest_sha}^"
    result = git(
        ["diff", "-C", "-M", "-z", "--raw", "--numstat", parent, newest_sha, "--"],
        repo,
        success_exit_codes={0, 1},
        expected_errors={"BadRevision"},
        name="getCommitRangeChangedFiles",
    )
    if result.git_error == "BadRevision" and not use_null_tree:
        return get_commit_range_changed_files(repo, oldest_sha, newest_sha, use_null_tree=True)
    return parse_raw_log_with_numstat(result.stdout, newest_sha, parent)


def get_commit_range_diff(
    repo: str,
    path: str,
    oldest_sha: str,
    newest_sha: str,
    status: FileStatus | None = None,
    hide_whitespace: bool = False,
    context_lines: int | None = None,
    *,
    use_null_tree: bool = False,
) -> FileDiff:
    parent = NULL_TREE_SHA if use_null_tree else f"{oldest_sha}^"
    args = _diff_flags(hide_whitespace, context_lines) + [
        parent,
        newest_sha,
        "--",
        ensure_relative_path(path),
    ]
    _append_old_path(args, path, status)
    result = git(
        args,
        repo,
        success_exit_codes={0, 1},
        expected_errors={"BadRevision"},
        name="commitRangeDiff",
    )
    if result.git_error == "BadRevision" and not use_null_tree:
        return get_commit_range_diff(
            repo, path, oldest_sha, newest_sha, status, hide_whitespace, context_lines, use_null_tree=True
        )
    return _diff_from_result(repo, path, status or FileStatus(AppFileStatusKind.MODIFIED), result, newest_sha)


def _parse_name_status_z(stdout: str, sha: str, parent: str | None) -> list[CommittedFileChange]:
    tokens = [t for t in stdout.split("\0") if t]
    files: list[CommittedFileChange] = []
    i = 0
    while i < len(tokens):
        status = tokens[i].strip()
        i += 1
        if not status:
            continue
        kind_ch = status[0]
        old_path = None
        if kind_ch in "RC" and i < len(tokens):
            old_path = tokens[i]
            i += 1
            path = tokens[i] if i < len(tokens) else old_path
            i += 1
        else:
            path = tokens[i] if i < len(tokens) else ""
            i += 1
        kind = {
            "A": AppFileStatusKind.NEW,
            "M": AppFileStatusKind.MODIFIED,
            "D": AppFileStatusKind.DELETED,
            "R": AppFileStatusKind.RENAMED,
            "C": AppFileStatusKind.COPIED,
            "?": AppFileStatusKind.UNTRACKED,
        }.get(kind_ch, AppFileStatusKind.MODIFIED)
        files.append(
            CommittedFileChange(
                path=path,
                status=FileStatus(
                    kind,
                    old_path=old_path,
                    rename_includes_modifications=kind_ch.startswith("R") and status != "R100",
                ),
                commitish=sha,
                parent_commitish=parent,
            )
        )
    return files


def _numstat_totals(repo: str, rev_args: Sequence[str]) -> tuple[int, int]:
    result = git(
        ["diff", "--numstat", *rev_args, "--"],
        repo,
        success_exit_codes={0, 1, 128},
        name="numstat",
    )
    if result.exit_code == 128:
        return 0, 0
    return _parse_numstat(result.stdout)


def _numstat_totals_show(repo: str, sha: str) -> tuple[int, int]:
    result = git(
        ["show", "--numstat", "--format=", "-C", "-M", sha, "--"],
        repo,
        success_exit_codes={0, 128},
        name="showNumstat",
    )
    if result.exit_code == 128:
        return 0, 0
    return _parse_numstat(result.stdout)


def _parse_numstat(stdout: str) -> tuple[int, int]:
    added = deleted = 0
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        a, d = parts[0], parts[1]
        if a.isdigit():
            added += int(a)
        if d.isdigit():
            deleted += int(d)
    return added, deleted


def lfs_ls_files(repo: str) -> list[str]:
    result = git(["lfs", "ls-files", "-n"], repo, success_exit_codes={0, 1, 128}, name="lfsLsFiles")
    if result.exit_code != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def lfs_patterns_from_gitattributes(repo: str) -> list[str]:
    path = Path(repo) / ".gitattributes"
    if not path.is_file():
        return []
    patterns: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "filter=lfs" in stripped:
            patterns.append(stripped.split()[0])
    return patterns


def get_branches(repo: str, *prefixes: str) -> list[Branch]:
    prefixes = prefixes or ("refs/heads", "refs/remotes")
    parser = create_for_each_ref_parser(
        {
            "refname": "%(refname)",
            "short": "%(refname:short)",
            "upstream": "%(upstream:short)",
            "sha": "%(objectname)",
            "symref": "%(symref)",
        }
    )
    result = git(
        ["for-each-ref", *parser.format_args, *prefixes],
        repo,
        expected_errors={"NotAGitRepository"},
        name="getBranches",
    )
    if result.git_error == "NotAGitRepository":
        return []
    branches: list[Branch] = []
    for entry in parser.parse(result.stdout):
        full = entry.get("refname") or ""
        short = entry.get("short") or ""
        upstream = entry.get("upstream") or ""
        sha = entry.get("sha") or ""
        symref = entry.get("symref") or ""
        if not full or symref:
            continue
        if full.startswith("refs/heads/"):
            btype = BranchType.LOCAL
            remote = None
            ref = full
        elif full.startswith("refs/remotes/"):
            btype = BranchType.REMOTE
            rest = full[len("refs/remotes/") :]
            remote = rest.split("/", 1)[0]
            ref = full
        else:
            continue
        branches.append(
            Branch(
                name=short,
                upstream=upstream or None,
                tip_sha=sha,
                type=btype,
                remote=remote,
                upstream_without_remote=remove_remote_prefix(upstream) if upstream else None,
                ref=ref,
            )
        )
    return branches


def git_rebase_arguments() -> list[str]:
    """Desktop `gitRebaseArguments`: force the merge rebase backend."""
    return list(GIT_REBASE_ARGUMENTS)


def env_for_authentication() -> dict[str, str]:
    """Desktop `envForAuthentication`."""
    from ..local_storage import get_item

    return {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_TRACE": get_item("git-trace") or os.environ.get("GIT_TRACE") or "0",
        "GIT_USER_AGENT": git_user_agent(),
    }


# Desktop `AuthenticationErrors` (expectedErrors for checkout / network ops).
AUTHENTICATION_ERRORS = frozenset(
    {
        "HTTPSAuthenticationFailed",
        "SSHAuthenticationFailed",
        "HTTPSRepositoryNotFound",
        "SSHRepositoryNotFound",
    }
)


def env_for_remote_operation(remote_url: str) -> dict[str, str]:
    """Desktop `envForRemoteOperation`: auth defaults plus proxy env."""
    env = env_for_authentication()
    env.update(env_for_proxy(remote_url))
    return env


def get_fallback_url_for_proxy_resolve(repo: str | None = None, remote_url: str | None = None) -> str:
    """Desktop `getFallbackUrlForProxyResolve`."""
    if remote_url:
        return remote_url
    if repo:
        try:
            remotes = get_remotes(repo)
            if remotes:
                return remotes[0].url
        except Exception:
            pass
    return "https://github.com"


def create_branch(repo: str, name: str, start_point: str | None = None, no_track: bool = False) -> None:
    args = ["branch", name] if not start_point else ["branch", name, start_point]
    # Desktop: when branching from a remote (fork upstream), `--no-track` so we
    # don't push to the upstream default.
    if no_track:
        args.append("--no-track")
    git(args, repo, name="createBranch")


def rename_branch(repo: str, old: str, new: str) -> None:
    git(["branch", "-m", old, new], repo, name="renameBranch")


def delete_local_branch(repo: str, name: str) -> None:
    git(["branch", "-D", "--", name], repo, name="deleteLocalBranch")


def delete_remote_branch(repo: str, remote: str, name: str, env: dict[str, str] | None = None) -> None:
    """Desktop `deleteRemoteBranch`: `git push <remote> :<branch>`.

    If the remote ref is already gone (`BranchDeletionFailed`), drop the local
    remote-tracking ref the way a successful delete would have.
    """
    result = git(
        ["push", remote, f":{name}"],
        repo,
        env=env,
        expected_errors={"BranchDeletionFailed"},
        name="deleteRemoteBranch",
    )
    if result.git_error == "BranchDeletionFailed":
        delete_ref(repo, f"refs/remotes/{remote}/{name}")


def checkout_branch(
    repo: str,
    name: str | Branch,
    *,
    progress: ProgressCb | None = None,
    env: dict[str, str] | None = None,
    recurse_submodules: bool = True,
) -> None:
    """Desktop `checkoutBranch`: remotes use `-b nameWithoutRemote` plus submodules."""
    branch = name if isinstance(name, Branch) else None
    args = ["checkout"]
    kwargs: dict = {"name": "checkoutBranch", "env": env}
    if progress:
        args.append("--progress")
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(CHECKOUT_STEPS)
        target = branch.name if branch is not None else str(name)
        progress(f"Switching to {target}", 0.0)
    if branch is not None:
        args.append(branch.name)
        if branch.type == BranchType.REMOTE:
            args.extend(["-b", branch.name_without_remote])
    else:
        args.append(str(name))
    if recurse_submodules:
        args.append("--recurse-submodules")
    args.append("--")
    kwargs["expected_errors"] = AUTHENTICATION_ERRORS
    git(args, repo, **kwargs)


def checkout_commit(
    repo: str,
    sha: str,
    *,
    progress: ProgressCb | None = None,
    env: dict[str, str] | None = None,
) -> None:
    args = ["checkout"]
    kwargs: dict = {"name": "checkoutCommit", "env": env}
    if progress:
        args.append("--progress")
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(CHECKOUT_STEPS)
        progress(f"Checking out commit {sha[:7]}", 0.0)
    args.append(sha)
    kwargs["expected_errors"] = AUTHENTICATION_ERRORS
    git(args, repo, **kwargs)


def checkout_paths(repo: str, paths: Sequence[str]) -> None:
    if not paths:
        return
    git(["checkout", "HEAD", "--", *paths], repo, name="checkoutPaths")


def get_remotes(repo: str) -> list[Remote]:
    result = git(
        ["remote", "-v"],
        repo,
        name="getRemotes",
        expected_errors={"NotAGitRepository"},
    )
    if result.git_error == "NotAGitRepository":
        return []
    remotes: dict[str, Remote] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = Remote(parts[0], parts[1])
    return list(remotes.values())


def add_remote(repo: str, name: str, url: str) -> None:
    git(["remote", "add", name, url], repo, name="addRemote")


def remove_remote(repo: str, name: str) -> None:
    """Desktop `removeRemote`: missing remotes are success (exit 2 or 128)."""
    git(["remote", "remove", name], repo, success_exit_codes={0, 2, 128}, name="removeRemote")


def set_remote_url(repo: str, name: str, url: str) -> None:
    git(["remote", "set-url", name, url], repo, name="setRemoteUrl")


def update_remote_url(
    repo: str,
    github: GitHubRepository,
    api_repo: GitHubRepository,
    remotes: Sequence[Remote] | None = None,
) -> bool:
    """Desktop `updateRemoteUrl`: retarget origin after a GitHub rename if the user hasn't customized it."""
    from ..remote_parsing import parse_remote

    known = list(remotes) if remotes is not None else get_remotes(repo)
    default = next((item for item in known if item.name == ORIGIN_REMOTE_NAME), known[0] if known else None)
    if default is None:
        return False
    remote_parsed = parse_remote(default.url)
    updated_parsed = parse_remote(api_repo.clone_url)
    recorded = parse_remote(github.clone_url)
    if remote_parsed is None or updated_parsed is None or recorded is None:
        return False
    # Desktop skips scp-like SSH remotes (URL.parse protocol is null). Match protocols.
    if remote_parsed.protocol != updated_parsed.protocol:
        return False
    remote_url_unchanged = (
        remote_parsed.hostname.lower() == recorded.hostname.lower()
        and remote_parsed.owner.lower() == recorded.owner.lower()
        and remote_parsed.name.lower() == recorded.name.lower()
    )
    urls_match = (
        remote_parsed.hostname.lower() == updated_parsed.hostname.lower()
        and remote_parsed.owner.lower() == updated_parsed.owner.lower()
        and remote_parsed.name.lower() == updated_parsed.name.lower()
    )
    if remote_url_unchanged and not urls_match:
        set_remote_url(repo, default.name, api_repo.clone_url)
        return True
    return False


def ensure_upstream_remote(repo: str, parent_url: str) -> tuple[str, Remote | None]:
    """Add `upstream` for a fork parent. Returns ('ok'|'added'|'mismatch', remote)."""
    from ..remote_parsing import url_matches_remote

    if not parent_url:
        return "ok", None
    remotes = get_remotes(repo)
    existing = next((r for r in remotes if r.name == UPSTREAM_REMOTE_NAME), None)
    matching = next((r for r in remotes if url_matches_remote(parent_url, r)), None)
    if matching is not None and matching.name == UPSTREAM_REMOTE_NAME:
        return "ok", matching
    if existing is not None:
        if url_matches_remote(parent_url, existing):
            return "ok", existing
        return "mismatch", existing
    add_remote(repo, UPSTREAM_REMOTE_NAME, parent_url)
    remotes = get_remotes(repo)
    added = next((r for r in remotes if r.name == UPSTREAM_REMOTE_NAME), None)
    return "added", added


def init_repository(path: str, default_branch: str = "main") -> None:
    os.makedirs(path, exist_ok=True)
    git(["-c", f"init.defaultBranch={default_branch}", "init"], path, name="init")


def clone_repository(
    url: str,
    path: str,
    *,
    branch: str | None = None,
    default_branch: str = "main",
    env: dict[str, str] | None = None,
    progress: ProgressCb | None = None,
    process_holder: list | None = None,
    cancel_event: Event | None = None,
) -> None:
    args = ["-c", f"init.defaultBranch={default_branch}", "clone", "--recursive"]
    if progress:
        args.append("--progress")
    if branch:
        args += ["-b", branch]
    args += ["--", url, path]
    merged = {"GIT_CLONE_PROTECTION_ACTIVE": "false"}
    if env:
        merged.update(env)
    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    kwargs: dict = {
        "env": merged,
        "name": "clone",
        "process_holder": process_holder,
        "cancel_event": cancel_event,
    }
    if progress:
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(CLONE_STEPS)
        progress(f"Cloning into {path}", 0.0)
    git(args, parent, **kwargs)


def fetch(
    repo: str,
    remote: str = "origin",
    *,
    env: dict[str, str] | None = None,
    progress: ProgressCb | None = None,
) -> None:
    args = ["fetch"]
    if progress:
        args.append("--progress")
    args.extend(["--prune", "--recurse-submodules=on-demand", remote])
    kwargs: dict = {"env": env, "name": "fetch"}
    if progress:
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(FETCH_STEPS)
        progress(f"Fetching {remote}", 0.0)
    git(args, repo, **kwargs)


def fetch_refspec(
    repo: str,
    remote: str,
    refspec: str,
    *,
    env: dict[str, str] | None = None,
) -> None:
    git(
        ["fetch", remote, refspec],
        repo,
        env=env,
        success_exit_codes={0, 128},
        name="fetchRefspec",
    )


def get_branches_differing_from_upstream(repo: str) -> list[TrackingBranch]:
    """Local branches whose tip SHA differs from their upstream (excludes HEAD)."""
    parser = create_for_each_ref_parser(
        {
            "fullName": "%(refname)",
            "sha": "%(objectname)",
            "upstream": "%(upstream)",
            "symref": "%(symref)",
            "head": "%(HEAD)",
        }
    )
    result = git(
        ["for-each-ref", *parser.format_args, "refs/heads", "refs/remotes"],
        repo,
        expected_errors={"NotAGitRepository"},
        name="getBranchesDifferingFromUpstream",
    )
    if result.git_error == "NotAGitRepository":
        return []
    local: list[tuple[str, str, str]] = []
    remote_shas: dict[str, str] = {}
    for entry in parser.parse(result.stdout):
        full = entry.get("fullName") or ""
        sha = entry.get("sha") or ""
        upstream = entry.get("upstream") or ""
        if not full or entry.get("symref") or entry.get("head") == "*":
            continue
        if full.startswith("refs/heads"):
            if upstream:
                local.append((full, sha, upstream))
        else:
            remote_shas[full] = sha
    eligible: list[TrackingBranch] = []
    for ref, sha, upstream in local:
        remote_sha = remote_shas.get(upstream)
        if remote_sha and remote_sha != sha:
            eligible.append(TrackingBranch(ref=ref, sha=sha, upstream_ref=upstream, upstream_sha=remote_sha))
    return eligible


def fast_forward_branches(repo: str, branches: Sequence[TrackingBranch]) -> None:
    """Desktop `fastForwardBranches`: `git fetch . --stdin` with upstream:local pairs."""
    if not branches:
        return
    stdin = "\n".join(f"{b.upstream_ref}:{b.ref}" for b in branches)
    git(
        ["fetch", ".", "--show-forced-updates", "--no-write-fetch-head", "--stdin"],
        repo,
        stdin=stdin,
        success_exit_codes={0, 1},
        env={"GIT_REFLOG_ACTION": "pull"},
        name="fastForwardBranches",
    )


def fetch_tags_to_push(repo: str, remote: str, branch_name: str, *, env: dict[str, str] | None = None) -> list[str]:
    """Dry-run `git push --follow-tags --porcelain` and collect `[new tag]` lines."""
    result = git(
        ["push", remote, branch_name, "--follow-tags", "--dry-run", "--no-verify", "--porcelain"],
        repo,
        env=env,
        success_exit_codes={0, 1},
        timeout=45,
        name="fetchTagsToPush",
    )
    tags: list[str] = []
    lines = result.stdout.splitlines()
    for line in lines[1:]:
        if line == "Done":
            break
        parts = line.split("\t")
        if len(parts) >= 3 and parts[0] == "*" and parts[2] == "[new tag]":
            tag = parts[1].split(":", 1)[0].replace("refs/tags/", "", 1)
            if tag:
                tags.append(tag)
    return tags


GIT_REBASE_ARGUMENTS = ["-c", "rebase.backend=merge"]


def pull(
    repo: str,
    remote: str = "origin",
    branch: str | None = None,
    *,
    env: dict[str, str] | None = None,
    progress: ProgressCb | None = None,
) -> None:
    """Pull matching Desktop: honor pull.rebase / pull.ff, recurse submodules."""
    args = [*GIT_REBASE_ARGUMENTS, "pull"]
    if get_config_value(repo, "pull.ff") is None:
        args.append("--ff")
    args.append("--recurse-submodules")
    if progress:
        args.append("--progress")
    args.append(remote)
    if branch:
        args.append(branch)
    kwargs: dict = {"env": env, "name": "pull"}
    if progress:
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(PULL_STEPS)
        progress(f"Pulling {remote}", 0.0)
    git(args, repo, **kwargs)


def push(
    repo: str,
    remote: str,
    local_branch: str,
    remote_branch: str | None = None,
    *,
    tags: Sequence[str] | None = None,
    force_with_lease: bool = False,
    set_upstream: bool = False,
    env: dict[str, str] | None = None,
    progress: ProgressCb | None = None,
) -> None:
    refspec = f"{local_branch}:{remote_branch}" if remote_branch else local_branch
    args = ["push", remote, refspec]
    if tags:
        args += list(tags)
    # Desktop `push`: `--set-upstream` when there is no remote branch, else `--force-with-lease`.
    if not remote_branch:
        args.append("--set-upstream")
    elif force_with_lease:
        args.append("--force-with-lease")
    kwargs: dict = {"env": env, "name": "push"}
    if progress:
        args.append("--progress")
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(PUSH_STEPS)
        progress(f"Pushing to {remote}", 0.0)
    git(args, repo, **kwargs)


def merge(
    repo: str,
    branch: str,
    *,
    squash: bool = False,
    no_commit: bool = False,
) -> MergeResult:
    args = ["merge"]
    if squash:
        args.append("--squash")
    if no_commit:
        args.append("--no-commit")
    args += ["--no-edit", branch]
    try:
        result = git(args, repo, name="merge", expected_errors={"MergeConflicts"})
        if result.exit_code != 0:
            return MergeResult.FAILED
        if "Already up to date" in result.stdout:
            return MergeResult.ALREADY_UP_TO_DATE
        if squash:
            # Desktop `merge`: successful `--squash` is committed immediately.
            try:
                git(["commit", "--no-edit"], repo, name="createSquashMergeCommit")
            except GitError:
                return MergeResult.FAILED
        return MergeResult.SUCCESS
    except GitError as exc:
        if (
            exc.is_conflicts
            or _path_exists(repo, ".git/MERGE_HEAD")
            or _path_exists(repo, ".git/SQUASH_MSG")
        ):
            return MergeResult.FAILED
        raise


def abort_merge(repo: str) -> None:
    git(["merge", "--abort"], repo, name="abortMerge")


def abort_squash_merge(repo: str) -> None:
    """Desktop `_abortSquashMerge` outcome: restore the pre-squash working tree.

    `git merge --abort` does not work for `--squash` (no `MERGE_HEAD`). Squash
    leaves HEAD on the original commit, so a hard reset clears `SQUASH_MSG`
    and conflicted index state. Electron commits `SQUASH_MSG` then resets to
    that same tip; the visible result is identical.
    """
    status = get_status(repo)
    tip = status.current_tip if status else None
    if not tip:
        return
    reset(repo, tip, "hard")


def rebase(
    repo: str,
    base_branch: str,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
    commits: Sequence[object] = (),
) -> RebaseResult:
    kwargs: dict = {"name": "rebase"}
    if progress is not None:
        parser = GitRebaseParser(commits)

        def on_line(line: str) -> None:
            event = parser.parse(line)
            if event is not None:
                progress(event)

        kwargs["on_stderr_line"] = on_line
    kwargs["expected_errors"] = {"RebaseConflicts"}
    try:
        result = git(
            [*GIT_REBASE_ARGUMENTS, "rebase", base_branch],
            repo,
            **kwargs,
        )
        if result.exit_code != 0:
            if get_rebase_internal_state(repo) is not None:
                return RebaseResult.CONFLICTS_ENCOUNTERED
            return RebaseResult.ERROR
        if "is up to date" in result.stdout.lower() or "up to date" in result.stderr.lower():
            return RebaseResult.ALREADY_UP_TO_DATE
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError as exc:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        if "no rebase in progress" in (exc.stderr + exc.stdout).lower():
            return RebaseResult.ERROR
        return RebaseResult.ERROR


def continue_rebase(
    repo: str,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
    commits: Sequence[object] = (),
) -> RebaseResult:
    status = get_status(repo)
    if status and any(f.status.kind == AppFileStatusKind.CONFLICTED for f in status.working_directory.files):
        return RebaseResult.CONFLICTS_ENCOUNTERED
    kwargs: dict = {"name": "rebaseContinue"}
    if progress is not None:
        parser = GitRebaseParser(commits)

        def on_line(line: str) -> None:
            event = parser.parse(line)
            if event is not None:
                progress(event)

        kwargs["on_stderr_line"] = on_line
    kwargs["expected_errors"] = {"RebaseConflicts", "UnresolvedConflicts"}
    try:
        result = git(["-c", "core.editor=true", "rebase", "--continue"], repo, **kwargs)
        if result.exit_code != 0:
            if get_rebase_internal_state(repo) is not None:
                return RebaseResult.CONFLICTS_ENCOUNTERED
            return RebaseResult.ERROR
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        return RebaseResult.ERROR


def abort_rebase(repo: str) -> None:
    git(["rebase", "--abort"], repo, name="abortRebase")


def cherry_pick(
    repo: str,
    shas: Sequence[str],
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
    commits: Sequence[object] = (),
) -> CherryPickResult:
    if not shas:
        return CherryPickResult.UNABLE_TO_START
    kwargs: dict = {"name": "cherryPick"}
    if progress is not None:
        parser = GitCherryPickParser(commits or [CommitOneLine(sha=s, summary="") for s in shas])

        def on_line(line: str) -> None:
            event = parser.parse(line)
            if event is not None:
                progress(event)

        kwargs["on_stdout_line"] = on_line
    kwargs["expected_errors"] = {"MergeConflicts", "ConflictModifyDeletedInBranch"}
    try:
        result = git(["cherry-pick", *shas], repo, **kwargs)
        return _parse_cherry_pick_result(repo, result)
    except GitError:
        if _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
            return CherryPickResult.CONFLICTS_ENCOUNTERED
        return CherryPickResult.ERROR


def continue_cherry_pick(
    repo: str,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
    commits: Sequence[object] = (),
) -> CherryPickResult:
    kwargs: dict = {"name": "cherryContinue"}
    if progress is not None:
        parser = GitCherryPickParser(commits)

        def on_line(line: str) -> None:
            event = parser.parse(line)
            if event is not None:
                progress(event)

        kwargs["on_stdout_line"] = on_line
    kwargs["expected_errors"] = {
        "MergeConflicts",
        "ConflictModifyDeletedInBranch",
        "UnresolvedConflicts",
    }
    try:
        result = git(["-c", "core.editor=true", "cherry-pick", "--continue"], repo, **kwargs)
        return _parse_cherry_pick_result(repo, result)
    except GitError:
        if _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
            return CherryPickResult.CONFLICTS_ENCOUNTERED
        return CherryPickResult.ERROR


def _parse_cherry_pick_result(repo: str, result: GitResult) -> CherryPickResult:
    """Desktop `parseCherryPickResult`."""
    if result.exit_code == 0:
        return CherryPickResult.COMPLETED_WITHOUT_ERROR
    if result.git_error in {"MergeConflicts", "ConflictModifyDeletedInBranch"}:
        return CherryPickResult.CONFLICTS_ENCOUNTERED
    if result.git_error == "UnresolvedConflicts":
        return CherryPickResult.OUTSTANDING_FILES_NOT_STAGED
    if _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
        return CherryPickResult.CONFLICTS_ENCOUNTERED
    return CherryPickResult.ERROR


def abort_cherry_pick(repo: str) -> None:
    git(["cherry-pick", "--abort"], repo, name="abortCherry")


def get_cherry_pick_snapshot(repo: str) -> dict[str, object] | None:
    """Desktop `getCherryPickSnapshot` for resume progress after conflicts."""
    if not _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
        return None
    sequencer = os.path.join(repo, ".git", "sequencer")

    def _read(name: str) -> str:
        try:
            return Path(os.path.join(sequencer, name)).read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    abort_safety = _read("abort-safety")
    head_sha = _read("head")
    remaining_raw = _read("todo")
    remaining: list[CommitOneLine] = []
    if remaining_raw:
        for line in remaining_raw.splitlines():
            line = re.sub(r"^pick ", "", line).strip()
            if " " not in line:
                continue
            sha, summary = line.split(" ", 1)
            remaining.append(CommitOneLine(sha=sha, summary=summary))
    if remaining:
        already: list[CommitOneLine] = []
        if abort_safety and head_sha and abort_safety != head_sha:
            between = get_commits_between(repo, head_sha, abort_safety) or []
            already = list(between)
        commits = [*already, *remaining]
        position = len(already) + 1
        total = len(commits) or 1
        return {
            "commits": commits,
            "remaining": remaining,
            "position": position,
            "total": total,
            "value": format_rebase_value(position / total),
            "current_commit_summary": remaining[0].summary,
        }
    try:
        sha = Path(os.path.join(repo, ".git", "CHERRY_PICK_HEAD")).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    commit = get_commit(repo, sha)
    summary = commit.summary if commit else ""
    return {
        "commits": [CommitOneLine(sha=sha, summary=summary)],
        "remaining": [],
        "position": 1,
        "total": 1,
        "value": 1.0,
        "current_commit_summary": summary,
    }


def revert(
    repo: str,
    sha: str,
    *,
    mainline: int | None = None,
    progress: ProgressCb | None = None,
    env: dict[str, str] | None = None,
) -> None:
    """Desktop `revertCommit`: merge commits pass `-m 1`."""
    args = ["revert"]
    if mainline is not None:
        args.extend(["-m", str(mainline)])
    args.extend(["--no-edit", sha])
    kwargs: dict = {"env": env, "name": "revert"}
    if progress:
        kwargs["progress"] = _progress_adapter(progress)
        kwargs["progress_parser"] = GitProgressParser(REVERT_STEPS)
        progress("Reverting commit", 0.0)
    git(args, repo, **kwargs)


def reset(repo: str, sha: str, mode: str = "mixed") -> None:
    git(["reset", f"--{mode}", sha], repo, name="reset")


def delete_ref(repo: str, ref: str, reason: str | None = None) -> None:
    args = ["update-ref", "-d", ref]
    if reason:
        args.extend(["-m", reason])
    git(args, repo, name="deleteRef")


def update_ref(repo: str, ref: str, old_value: str, new_value: str, reason: str) -> None:
    """Desktop `updateRef`: compare-and-swap a fully qualified ref."""
    git(["update-ref", ref, new_value, old_value, "-m", reason], repo, name="updateRef")


def undo_first_commit(repo: str) -> None:
    """Undo the initial commit: restore deleted paths, drop HEAD, unstage all.

    Matches Desktop `GitStore.undoFirstCommit`: a mixed/soft reset cannot
    walk `HEAD~1` on an unborn-after-undo branch, and deleted working-tree
    files must be checked out first so they survive `update-ref -d HEAD`.
    """
    status = get_status(repo)
    if status is None:
        raise GitError(
            "Unable to undo commit because there are too many files in your repository's working directory.",
            args=["status"],
            git_error="Busy",
        )
    deleted = [f.path for f in status.working_directory.files if f.status.kind == AppFileStatusKind.DELETED]
    checkout_paths(repo, deleted)
    delete_ref(repo, "HEAD", "Reverting first commit")
    unstage_all_files(repo)


def undo_commit(repo: str, parent_shas: Sequence[str] | None = None) -> None:
    """Undo HEAD. First commits drop the ref; later commits mixed-reset to the parent."""
    parents: list[str]
    if parent_shas is None:
        commit = get_commit(repo, "HEAD")
        parents = list(commit.parent_shas) if commit else []
    else:
        parents = list(parent_shas)
    if not parents:
        undo_first_commit(repo)
        return
    reset(repo, parents[0], "mixed")


def do_merge_commits_exist_after_commit(repo: str, commit_ref: str | None) -> bool:
    """True when `commit_ref..HEAD` (or all of HEAD) contains a merge commit."""
    revision = "HEAD" if commit_ref is None else rev_range(commit_ref, "HEAD")
    result = git(
        ["rev-list", "-1", "--merges", revision, "--"],
        repo,
        success_exit_codes={0, 128},
        name="doMergeCommitsExistAfterCommit",
    )
    return bool(result.stdout.strip())


def get_last_fetched(repo: str) -> float | None:
    """mtime of `.git/FETCH_HEAD` when the file is non-empty, else None."""
    try:
        path = os.path.join(_git_dir(repo), "FETCH_HEAD")
        st = os.stat(path)
    except (OSError, GitError):
        return None
    if st.st_size > 0:
        return st.st_mtime
    return None


def discard_changes_from_selection(
    repo: str,
    file_path: str,
    diff: TextDiff,
    selection: DiffSelection,
) -> None:
    kind = selection.get_selection_type()
    if kind == DiffSelectionType.NONE:
        return
    if kind == DiffSelectionType.ALL:
        discard_paths(repo, [file_path])
        return
    patch = format_discard_patch(file_path, diff, selection.is_selected)
    if not patch:
        return
    if not check_patch(repo, patch):
        raise GitError("Patch does not apply", args=["apply", "--check"], git_error="PatchDoesNotApply")
    git(
        ["apply", "--unidiff-zero", "--whitespace=nowarn", "-"],
        repo,
        stdin=patch,
        name="discardSelection",
    )


def check_patch(repo: str, patch: str) -> bool:
    """Desktop `checkPatch`: `git apply --check`."""
    result = git(
        ["apply", "--check", "-"],
        repo,
        stdin=patch,
        success_exit_codes={0, 1},
        expected_errors={"PatchDoesNotApply"},
        name="checkPatch",
    )
    return result.exit_code == 0


def get_index_changes(repo: str) -> dict[str, IndexStatus]:
    """Desktop `getIndexChanges`: cached index vs HEAD, no rename detection."""
    args = ["diff-index", "--cached", "--name-status", "--no-renames", "-z"]
    result = git([*args, "HEAD", "--"], repo, success_exit_codes={0, 128}, name="getIndexChanges")
    if result.exit_code == 128:
        result = git([*args, NULL_TREE_SHA], repo, name="getIndexChanges")
    mapping = {
        "A": IndexStatus.ADDED,
        "D": IndexStatus.DELETED,
        "M": IndexStatus.MODIFIED,
        "T": IndexStatus.TYPE_CHANGED,
        "U": IndexStatus.UNMERGED,
        "X": IndexStatus.UNKNOWN,
    }
    out: dict[str, IndexStatus] = {}
    pieces = result.stdout.split("\0")
    for i in range(0, len(pieces) - 1, 2):
        status, path = pieces[i], pieces[i + 1]
        if not path:
            continue
        out[path] = mapping.get(status[:1], IndexStatus.UNKNOWN)
    return out


def reset_paths(repo: str, ref: str, paths: Sequence[str], mode: str = "mixed") -> None:
    if not paths:
        return
    git(["reset", f"--{mode}", ref, "--", *paths], repo, name="resetPaths")


def checkout_index(repo: str, paths: Sequence[str]) -> None:
    if not paths:
        return
    git(
        ["checkout-index", "-f", "-u", "-q", "--stdin", "-z"],
        repo,
        stdin="\0".join(paths),
        success_exit_codes={0, 1},
        name="checkoutIndex",
    )


def _delete_working_path(path: str) -> bool:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            import shutil

            shutil.rmtree(path)
        elif os.path.lexists(path):
            os.remove(path)
        return True
    except OSError as exc:
        log.warning("Failed to discard %s: %s", path, exc)
        return False


def move_item_to_trash(path: str) -> bool:
    """Desktop `moveItemToTrash`. Permanently deletes if no trash backend exists."""
    if not os.path.lexists(path):
        return True
    try:
        from gi.repository import Gio
    except Exception:
        return _delete_working_path(path)
    try:
        Gio.File.new_for_path(path).trash(None)
        return True
    except Exception:
        return False


def discard_working_files(
    repo: str,
    files: Sequence[WorkingDirectoryFileChange],
    *,
    move_to_trash: bool = True,
    ask_permanent: bool = False,
) -> None:
    """Desktop `discardChanges`: trash working copies, reset index paths, then checkout-index."""
    from ..errors import DiscardChangesError

    if not files:
        return
    submodules = set(get_submodules(repo))
    paths_to_checkout: list[str] = []
    paths_to_reset: list[str] = []
    untracked: list[str] = []

    def remove_wt(rel: str, *, untracked_file: bool = False) -> None:
        full = os.path.join(repo, rel)
        if move_to_trash:
            if move_item_to_trash(full):
                return
            if ask_permanent:
                raise DiscardChangesError(
                    f"Failed to discard changes to Trash for {rel}",
                    files=list(files),
                )
            if not untracked_file:
                return
        _delete_working_path(full)

    for file in files:
        if file.status.kind == AppFileStatusKind.UNTRACKED:
            untracked.append(file.path)
            continue
        if file.status.kind != AppFileStatusKind.DELETED and file.path not in submodules:
            remove_wt(file.path)
        if file.status.kind in (AppFileStatusKind.COPIED, AppFileStatusKind.RENAMED) and file.status.old_path:
            paths_to_reset.append(file.path)
            paths_to_checkout.append(file.status.old_path)
            paths_to_reset.append(file.status.old_path)
        else:
            paths_to_checkout.append(file.path)
            paths_to_reset.append(file.path)
    for path in untracked:
        remove_wt(path, untracked_file=True)
    changed = get_index_changes(repo)
    necessary_reset = [p for p in paths_to_reset if p in changed]
    submodule_paths = [p for p in paths_to_checkout if p in submodules]
    necessary_checkout = [
        p
        for p in paths_to_checkout
        if p not in submodule_paths or changed.get(p) != IndexStatus.ADDED
    ]
    if necessary_reset:
        reset_paths(repo, "HEAD", necessary_reset)
    checkout_index(repo, necessary_checkout)


def discard_paths(repo: str, paths: Sequence[str]) -> None:
    if not paths:
        return
    tracked = []
    untracked = []
    for path in paths:
        result = git(["ls-files", "--", path], repo, name="lsFiles")
        if result.stdout.strip():
            tracked.append(path)
        else:
            untracked.append(path)
    files: list[WorkingDirectoryFileChange] = []
    for path in tracked:
        files.append(
            WorkingDirectoryFileChange(path, FileStatus(kind=AppFileStatusKind.MODIFIED))
        )
    for path in untracked:
        files.append(
            WorkingDirectoryFileChange(path, FileStatus(kind=AppFileStatusKind.UNTRACKED))
        )
    discard_working_files(repo, files)


def stash_push(repo: str, branch_name: str, paths: Sequence[str] | None = None) -> None:
    create_desktop_stash_entry(repo, branch_name, paths=paths)


def create_desktop_stash_entry(
    repo: str,
    branch_name: str,
    untracked_files: Sequence[WorkingDirectoryFileChange] = (),
    paths: Sequence[str] | None = None,
) -> bool:
    """Desktop `createDesktopStashEntry`: stage untracked files, then stash push."""
    if untracked_files:
        fully = [f.with_include(True) if hasattr(f, "with_include") else f for f in untracked_files]
        update_index(repo, [f.path for f in fully])
    message = f"{DESKTOP_STASH_MARKER}<{branch_name}>"
    args = ["stash", "push", "-m", message]
    if paths:
        args += ["--"] + list(paths)
    try:
        result = git(args, repo, success_exit_codes={0, 1}, name="createStashEntry")
    except GitError:
        raise
    if result.exit_code == 1 and re.search(r"^error: ", result.stderr, re.M):
        raise GitError(result.stderr or "stash failed", args=args, exit_code=1, stderr=result.stderr, stdout=result.stdout)
    if result.exit_code == 1:
        log.info(
            "[createDesktopStashEntry] a stash was created successfully but exit code %s reported. stderr: %s",
            result.exit_code,
            result.stderr,
        )
    if result.stdout.strip() == "No local changes to save":
        return False
    return True


def stash_pop(repo: str, stash_ref: str = "stash@{0}") -> None:
    """Desktop `popStashEntry`: `MergeConflicts` is expected; empty-stderr exit 1 still drops."""
    entries, _total = get_stashes(repo)
    match = next((entry for entry in entries if entry.name == stash_ref or entry.stash_sha == stash_ref), None)
    if match is None:
        return
    try:
        git(
            ["stash", "pop", "--quiet", match.name],
            repo,
            expected_errors={"MergeConflicts"},
            name="popStashEntry",
        )
    except GitError as exc:
        blob = f"{exc.stdout}\n{exc.stderr}".lower()
        # Git already kept the stash (newer `--quiet` omits "merge conflict").
        if "stash entry is kept" in blob:
            return
        if exc.exit_code == 1 and not (exc.stderr or "").strip():
            log.info(
                "[popStashEntry] a stash was popped successfully but exit code %s reported.",
                exc.exit_code,
            )
            drop_desktop_stash_entry(repo, match.stash_sha)
            return
        raise


def stash_drop(repo: str, stash_ref: str) -> None:
    git(["stash", "drop", stash_ref], repo, name="stashDrop")


def get_stashes(repo: str) -> tuple[list[StashEntry], int]:
    parser = create_log_parser(
        {
            "name": "%gD",
            "stashSha": "%H",
            "message": "%gs",
            "tree": "%T",
            "parents": "%P",
        }
    )
    result = git(
        ["log", "-g", *parser.format_args, "refs/stash", "--"],
        repo,
        success_exit_codes={0, 128},
        name="getStashes",
    )
    if result.exit_code == 128:
        return [], 0
    entries: list[StashEntry] = []
    marker_re = re.compile(r"!!GitHub_Desktop<(.+)>$")
    parsed = parser.parse(result.stdout)
    for entry in parsed:
        match = marker_re.search(entry.get("message") or "")
        if match:
            parents = entry.get("parents") or ""
            entries.append(
                StashEntry(
                    name=entry.get("name") or "",
                    stash_sha=entry.get("stashSha") or "",
                    branch_name=match.group(1),
                    tree=entry.get("tree") or "",
                    parents=parents.split() if parents else [],
                )
            )
    return entries, len(parsed)


def get_stashed_files(repo: str, stash_sha: str) -> list[CommittedFileChange]:
    """Desktop `getStashedFiles`: files changed in a stash commit."""
    result = git(
        [
            "stash",
            "show",
            stash_sha,
            "--raw",
            "--numstat",
            "-z",
            "--format=format:",
            "--no-show-signature",
            "--",
        ],
        repo,
        success_exit_codes={0, 1, 128},
        name="getStashedFiles",
    )
    if result.exit_code == 128:
        return []
    return parse_raw_log_with_numstat(result.stdout, stash_sha, f"{stash_sha}^").files


def get_last_desktop_stash_entry_for_branch(repo: str, branch: str) -> StashEntry | None:
    entries, _total = get_stashes(repo)
    return next((entry for entry in entries if entry.branch_name == branch), None)


def drop_desktop_stash_entry(repo: str, stash_sha: str) -> None:
    entries, _total = get_stashes(repo)
    match = next((entry for entry in entries if entry.stash_sha == stash_sha), None)
    if match:
        stash_drop(repo, match.name)


def move_stash_entry(repo: str, entry: StashEntry, branch_name: str) -> None:
    """Desktop `moveStashEntry`: commit-tree + stash store, then drop the old entry."""
    message = f"On {branch_name}: {DESKTOP_STASH_MARKER}<{branch_name}>"
    parent_args: list[str] = []
    for parent in entry.parents:
        parent_args += ["-p", parent]
    result = git(
        ["commit-tree", *parent_args, "-m", message, "--no-gpg-sign", entry.tree],
        repo,
        name="moveStashEntryToBranch",
    )
    commit_id = result.stdout.strip()
    git(["stash", "store", "-m", message, commit_id], repo, name="moveStashEntryToBranch")
    drop_desktop_stash_entry(repo, entry.stash_sha)


def create_tag(repo: str, name: str, sha: str) -> None:
    """Desktop `createTag`: annotated tag with an empty message."""
    git(["tag", "-a", "-m", "", name, sha], repo, name="createTag")


def delete_tag(repo: str, name: str) -> None:
    git(["tag", "-d", name], repo, name="deleteTag")


def get_all_tags(repo: str) -> dict[str, str]:
    result = git(["show-ref", "--tags", "-d"], repo, success_exit_codes={0, 1}, name="showRefTags")
    tags: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ref = parts
        name = ref[len("refs/tags/") :]
        if name.endswith("^{}"):
            name = name[:-3]
        tags[name] = sha
    return tags


def get_config_value(
    repo: str | None, key: str, global_only: bool = False, local_only: bool = False
) -> str | None:
    args = ["config"]
    if global_only or not repo:
        args.append("--global")
    elif local_only:
        args.append("--local")
    args += ["--get", key]
    cwd = repo or os.path.expanduser("~")
    result = git(args, cwd, success_exit_codes={0, 1}, name="getConfig")
    value = result.stdout.strip()
    return value or None


def get_boolean_config_value(repo: str | None, key: str, global_only: bool = False) -> bool | None:
    """Desktop getBooleanConfigValue: git config --bool, None when unset."""
    args = ["config", "--bool"]
    if global_only or not repo:
        args.append("--global")
    args += ["--get", key]
    cwd = repo or os.path.expanduser("~")
    result = git(args, cwd, success_exit_codes={0, 1}, name="getBoolConfig")
    value = result.stdout.strip().lower()
    if not value:
        return None
    return value != "false"


def get_global_config_value(key: str) -> str | None:
    """Desktop `getGlobalConfigValue`."""
    return get_config_value(None, key, global_only=True)


def set_global_config_value(key: str, value: str) -> None:
    """Desktop `setGlobalConfigValue`."""
    set_config_value(None, key, value, global_only=True)


def remove_global_config_value(key: str) -> None:
    """Desktop `removeGlobalConfigValue`."""
    remove_config_value(None, key, global_only=True)


def get_global_boolean_config_value(key: str) -> bool | None:
    """Desktop `getGlobalBooleanConfigValue`."""
    return get_boolean_config_value(None, key, global_only=True)


def warn_about_remote_commits(repo: str, branch: Branch, oldest_ref: str | None) -> bool:
    """True when rewriting this published branch would require a force push.

    Port of Desktop dispatcher.warnAboutRemoteCommits.
    """
    if not branch.upstream:
        return False
    matching = get_branches(repo, f"refs/remotes/{branch.upstream}")
    if not matching:
        return False
    if oldest_ref is None:
        return True
    remote_commits = get_commits_between(repo, oldest_ref, branch.upstream)
    return remote_commits is not None and len(remote_commits) > 0


_CONFIG_LOCK_RE = re.compile(r"^error: could not lock config file (.+?): File exists$", re.M)


def is_config_file_lock_error(error: BaseException) -> bool:
    """Desktop `isConfigFileLockError`: git could not lock a config file."""
    if not isinstance(error, GitError):
        return False
    if error.git_error == "ConfigLockFileAlreadyExists":
        return True
    blob = f"{error.stderr}\n{error}"
    return bool(_CONFIG_LOCK_RE.search(blob))


def parse_config_lock_file_path_from_error(
    error: GitError | GitResult, cwd: str | None = None
) -> str | None:
    """Desktop `parseConfigLockFilePathFromError`.

    Git prints the config path without the ``.lock`` suffix; the lock file is
    ``{normalized}.lock`` resolved against the command cwd (`IGitResult.path`).
    """
    stderr = getattr(error, "stderr", "") or ""
    if not stderr and isinstance(error, BaseException):
        stderr = str(error)
    match = _CONFIG_LOCK_RE.search(stderr)
    if not match:
        return None
    normalized = match.group(1)
    if os.name == "nt":
        normalized = normalized.replace("/", "\\")
    base = cwd or getattr(error, "path", None) or os.path.expanduser("~")
    return os.path.abspath(os.path.join(base, f"{normalized}.lock"))


def set_config_value(repo: str | None, key: str, value: str, global_only: bool = False) -> None:
    args = ["config"]
    if global_only or not repo:
        args.append("--global")
    args += [key, value]
    cwd = repo or os.path.expanduser("~")
    git(args, cwd, name="setConfig")


def remove_config_value(repo: str | None, key: str, global_only: bool = False) -> None:
    args = ["config"]
    if global_only or not repo:
        args.append("--global")
    args += ["--unset-all", key]
    cwd = repo or os.path.expanduser("~")
    git(args, cwd, success_exit_codes={0, 5}, name="unsetConfig")


def read_gitignore_at_root(repo: str) -> str | None:
    """Desktop `readGitIgnoreAtRoot`: ``None`` when `.gitignore` is missing.

    Reads with ``newline=""`` so CRLF from ``formatGitIgnoreContents`` is not
    normalized the way ``Path.read_text`` (universal newlines) would.
    """
    path = os.path.join(repo, ".gitignore")
    try:
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None


def read_gitignore(repo: str) -> str:
    return read_gitignore_at_root(repo) or ""


def format_gitignore_contents(text: str, repo: str) -> str:
    """Desktop `formatGitIgnoreContents` (`core.autocrlf` / `core.safecrlf`)."""
    autocrlf = get_config_value(repo, "core.autocrlf")
    safecrlf = get_config_value(repo, "core.safecrlf")
    if autocrlf == "true" and safecrlf == "true":
        normalized = re.sub(r"\r\n|\n\r|\n|\r", "\r\n", text)
        return normalized + "\r\n"
    if text == "" or text.endswith("\n"):
        return text
    if autocrlf is None:
        return f"{text}\n"
    if autocrlf == "true":
        return f"{text}\n"
    return f"{text}\r\n"


def write_gitignore(repo: str, text: str) -> None:
    """Desktop `saveGitIgnore`: empty text removes `.gitignore`."""
    save_gitignore(repo, text)


def save_gitignore(repo: str, text: str) -> None:
    """Desktop `saveGitIgnore`."""
    ignore_path = os.path.join(repo, ".gitignore")
    if text == "":
        try:
            os.unlink(ignore_path)
        except FileNotFoundError:
            pass
        return
    with open(ignore_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(format_gitignore_contents(text, repo))


def append_ignore_rule(repo: str, pattern: str | Sequence[str]) -> None:
    """Desktop `appendIgnoreRule`."""
    text = read_gitignore_at_root(repo) or ""
    current = format_gitignore_contents(text, repo)
    new_pattern = "\n".join(pattern) if not isinstance(pattern, str) else pattern
    save_gitignore(repo, format_gitignore_contents(f"{current}{new_pattern}", repo))


_GITIGNORE_SPECIAL_RE = re.compile(r"[\[\]!*#?]")


def escape_git_special_characters(pattern: str) -> str:
    """Desktop `escapeGitSpecialCharacters` for .gitignore paths."""
    return _GITIGNORE_SPECIAL_RE.sub(lambda match: "\\" + match.group(0), pattern)


def append_ignore_file(repo: str, file_path: str | Sequence[str]) -> None:
    """Desktop `appendIgnoreFile`: escape gitignore specials, then append."""
    paths = [file_path] if isinstance(file_path, str) else list(file_path)
    append_ignore_rule(repo, [escape_git_special_characters(path) for path in paths])


def lfs_track(repo: str, patterns: Sequence[str]) -> None:
    install_lfs_hooks(repo)
    for pattern in patterns:
        git(["lfs", "track", pattern], repo, name="lfsTrack")


def install_global_lfs_filters(force: bool = False) -> None:
    args = ["lfs", "install", "--skip-repo"]
    if force:
        args.append("--force")
    try:
        git(args, os.path.expanduser("~"), name="installGlobalLFSFilter")
    except GitError as exc:
        if _lfs_missing(exc):
            return
        raise


def install_lfs_hooks(repo: str, force: bool = False) -> None:
    args = ["lfs", "install"]
    if force:
        args.append("--force")
    try:
        git(args, repo, name="installLFSHooks")
    except GitError as exc:
        if _lfs_missing(exc):
            return
        raise


def _lfs_missing(exc: GitError) -> bool:
    text = f"{exc.stderr}\n{exc.stdout}\n{exc}".lower()
    return "is not a git command" in text or ("git-lfs" in text and "not found" in text)


def is_using_lfs(repo: str) -> bool:
    """Desktop `isUsingLFS`; callers catch GitError (AppStore returns false)."""
    result = git(
        ["lfs", "track"],
        repo,
        env={"GIT_LFS_TRACK_NO_INSTALL_HOOKS": "1"},
        name="isUsingLFS",
    )
    return bool(result.stdout.strip())


def is_tracked_by_lfs(repo: str, path: str) -> bool:
    result = git(["check-attr", "filter", "--", path], repo, name="checkAttrForLFS")
    return bool(re.search(r": filter: lfs\b", result.stdout))


def files_not_tracked_by_lfs(repo: str, paths: Sequence[str]) -> list[str]:
    return [path for path in paths if not is_tracked_by_lfs(repo, path)]


def is_lfs_repo(repo: str) -> bool:
    result = git(["lfs", "ls-files"], repo, success_exit_codes={0, 1, 128}, name="lfsLs")
    return result.exit_code == 0 and bool(result.stdout.strip())


def get_submodules(repo: str) -> list[str]:
    return [entry.path for entry in list_submodules(repo)]


def list_submodules(repo: str) -> list[SubmoduleEntry]:
    """Desktop `listSubmodules`: top-level submodule status entries."""
    gitmodules = os.path.join(repo, ".gitmodules")
    modules_dir = os.path.join(repo, ".git", "modules")
    if not os.path.exists(gitmodules) and not os.path.isdir(modules_dir):
        return []
    result = git(
        ["submodule", "status", "--"],
        repo,
        success_exit_codes={0, 128},
        name="listSubmodules",
    )
    if result.exit_code == 128:
        return []
    entries: list[SubmoduleEntry] = []
    for match in re.finditer(r"^.([^ ]+) (.+) \((.+?)\)$", result.stdout, re.M):
        entries.append(SubmoduleEntry(sha=match.group(1), path=match.group(2), describe=match.group(3)))
    return entries


def reset_submodule_paths(repo: str, paths: Sequence[str]) -> None:
    """Desktop `resetSubmodulePaths`: `git submodule update --recursive --force`."""
    if not paths:
        return
    git(
        ["submodule", "update", "--recursive", "--force", "--", *paths],
        repo,
        name="updateSubmodule",
    )


def update_submodules(repo: str) -> None:
    git(["submodule", "update", "--init", "--recursive"], repo, name="subUpdate")


def interactive_rebase_todo(
    repo: str,
    last_retained: str | None,
    todo_lines: Sequence[str],
    message_path: str | None = None,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
    todo_name: str = "rebaseTodo",
) -> RebaseResult:
    """Run `git rebase -i` with a pre-written todo list (squash / reorder)."""
    from ..file_system import get_temp_file_path

    git_dir = _git_dir(repo)
    todo_file = get_temp_file_path(todo_name)
    Path(todo_file).write_text("\n".join(todo_lines) + "\n", encoding="utf-8")
    seq_editor = os.path.join(git_dir, "desktop-sequence-editor.sh")
    Path(seq_editor).write_text(f"#!/bin/sh\ncp '{todo_file}' \"$1\"\n", encoding="utf-8")
    os.chmod(seq_editor, 0o755)
    env = {
        "GIT_SEQUENCE_EDITOR": seq_editor,
        "GIT_EDITOR": "true",
        "EDITOR": "true",
        "VISUAL": "true",
    }
    if message_path:
        msg_editor = os.path.join(git_dir, "desktop-message-editor.sh")
        Path(msg_editor).write_text(f"#!/bin/sh\ncp '{message_path}' \"$1\"\n", encoding="utf-8")
        os.chmod(msg_editor, 0o755)
        env["GIT_EDITOR"] = msg_editor
    args = ["rebase", "-i"]
    if last_retained:
        args.append(last_retained)
    else:
        args.append("--root")
    kwargs: dict = {"env": env, "name": "rebaseInteractive", "timeout": 60}
    if progress is not None:
        commits = []
        for line in todo_lines:
            parts = line.split(" ", 2)
            if len(parts) >= 3:
                commits.append(CommitOneLine(sha=parts[1], summary=parts[2]))
        parser = GitRebaseParser(commits)

        def on_line(line: str) -> None:
            event = parser.parse(line)
            if event is not None:
                progress(event)

        kwargs["on_stderr_line"] = on_line
    kwargs["expected_errors"] = {"RebaseConflicts"}
    try:
        result = git(args, repo, **kwargs)
        if result.exit_code != 0:
            if get_rebase_internal_state(repo) is not None:
                return RebaseResult.CONFLICTS_ENCOUNTERED
            return RebaseResult.ERROR
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        return RebaseResult.ERROR
    finally:
        try:
            os.remove(todo_file)
        except OSError:
            pass


def squash_commits(
    repo: str,
    to_squash: Sequence[Commit],
    squash_onto: Commit,
    last_retained: str | None,
    message: str,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
) -> RebaseResult:
    if not to_squash:
        raise GitError("No commits provided to squash.")
    squash_shas = {c.sha for c in to_squash}
    if squash_onto.sha in squash_shas:
        raise GitError("The commits to squash cannot contain the commit to squash onto.")
    rev = f"{last_retained}..HEAD" if last_retained else None
    commits = get_commits(repo, rev, limit=None)
    if not commits:
        raise GitError("Could not find commits in log for last retained commit ref.")
    todo: list[str] = []
    found = False
    after: list[str] = []
    at_squash: list[str] = []
    for commit in reversed(commits):  # oldest first
        if commit.sha == squash_onto.sha:
            found = True
            todo.append(f"pick {commit.sha} {commit.summary}")
            for extra in at_squash:
                todo.append(extra)
            at_squash.clear()
            continue
        if commit.sha in squash_shas:
            line = f"squash {commit.sha} {commit.summary}"
            if found:
                todo.append(line)
            else:
                at_squash.append(line)
            continue
        line = f"pick {commit.sha} {commit.summary}"
        if found:
            todo.append(line)
        else:
            todo.append(line)
    if not found:
        raise GitError("The commit to squash onto was not found in the log.")
    from ..file_system import get_temp_file_path

    msg_path = None
    if message.strip():
        msg_path = get_temp_file_path("squashCommitMessage")
        Path(msg_path).write_text(message, encoding="utf-8")
    try:
        # Rewrite first pick of squash group: after pick onto, subsequent squash
        # Use GIT_EDITOR to set the combined message when squash stops
        result = interactive_rebase_todo(
            repo, last_retained, todo, msg_path, progress=progress, todo_name="squashTodo"
        )
        return result
    finally:
        if msg_path:
            try:
                os.remove(msg_path)
            except OSError:
                pass


def reorder_commits(
    repo: str,
    to_move: Sequence[Commit],
    before: Commit | None,
    last_retained: str | None,
    *,
    progress: Callable[[MultiCommitProgress], None] | None = None,
) -> RebaseResult:
    move_shas = {c.sha for c in to_move}
    rev = f"{last_retained}..HEAD" if last_retained else None
    commits = get_commits(repo, rev, limit=None)
    ordered = list(reversed(commits))
    remaining = [c for c in ordered if c.sha not in move_shas]
    insertion = []
    inserted = False
    for commit in remaining:
        if before and commit.sha == before.sha and not inserted:
            insertion.extend(to_move)
            inserted = True
        insertion.append(commit)
    if not inserted:
        insertion.extend(to_move)
    todo = [f"pick {c.sha} {c.summary}" for c in insertion]
    return interactive_rebase_todo(repo, last_retained, todo, progress=progress, todo_name="reorderTodo")


def get_ahead_behind(repo: str, upstream: str, branch: str | None = None) -> AheadBehind | None:
    left = branch or "HEAD"
    return get_ahead_behind_range(repo, f"{upstream}...{left}", swap=True)


def get_ahead_behind_range(repo: str, range_spec: str, *, swap: bool = False) -> AheadBehind | None:
    """Desktop getAheadBehind: left count is ahead, right count is behind.

    `swap=True` matches the older local-vs-upstream helper where the first ref is the upstream.
    """
    result = git(
        ["rev-list", "--left-right", "--count", range_spec, "--"],
        repo,
        expected_errors={"BadRevision"},
        name="getAheadBehind",
    )
    if result.git_error == "BadRevision" or result.exit_code != 0:
        return None
    parts = result.stdout.strip().replace("\t", " ").split()
    if len(parts) != 2:
        return None
    left, right = int(parts[0]), int(parts[1])
    if swap:
        return AheadBehind(ahead=right, behind=left)
    return AheadBehind(ahead=left, behind=right)


def get_branch_ahead_behind(repo: str, branch: Branch) -> AheadBehind | None:
    """Desktop `getBranchAheadBehind` using the symmetric difference vs upstream."""
    if branch.type == BranchType.REMOTE or not branch.upstream:
        return None
    return get_ahead_behind_range(repo, rev_symmetric_difference(branch.name, branch.upstream))


def get_commits_in_range(repo: str, range_spec: str) -> list[CommitOneLine] | None:
    """Desktop `getCommitsInRange`: commits in a rev-list range, oldest first."""
    result = git(
        ["rev-list", range_spec, "--reverse", "--oneline", "--no-abbrev-commit", "--"],
        repo,
        expected_errors={"BadRevision"},
        name="getCommitsInRange",
    )
    if result.git_error == "BadRevision" or result.exit_code != 0:
        return None
    commits: list[CommitOneLine] = []
    for line in result.stdout.splitlines():
        sha, _, summary = line.partition(" ")
        if sha:
            commits.append(CommitOneLine(sha=sha, summary=summary))
    return commits


def get_commits_between(repo: str, base_sha: str, target_sha: str) -> list[CommitOneLine] | None:
    """Commits reachable from target but not base, oldest first (Desktop getCommitsBetweenCommits)."""
    return get_commits_in_range(repo, rev_range(base_sha, target_sha))


_RECENT_BRANCH_RE = re.compile(
    r".*? (renamed|checkout)(?:: moving from|\s*) (?:refs/heads/|\s*)(.*?) to (?:refs/heads/|\s*)(.*?)$",
    re.I,
)
_BRANCH_CHECKOUT_RE = re.compile(
    r"^[a-f0-9]{40}\sHEAD@{(.*)}\scheckout: moving from\s.*\sto\s(.*)$"
)
_NO_COMMITS_ON_BRANCH_RE = re.compile(
    r"fatal: your current branch '.*' does not have any commits yet"
)
_CONFLICT_MARKER_RE = re.compile(r"^(.+):\d+: leftover conflict marker", re.M)
_CREDENTIAL_INDEX_RE = re.compile(r"\[\d+\]$")


def get_recent_branches(repo: str, limit: int = 5) -> list[str]:
    """Newest reflog checkouts first, matching Desktop `getRecentBranches`."""
    result = git(
        ["log", "-g", "--no-abbrev-commit", "--pretty=oneline", "HEAD", "-n", "2500", "--"],
        repo,
        success_exit_codes={0, 128},
        name="getRecentBranches",
    )
    if result.exit_code == 128:
        return []
    names: list[str] = []
    seen: set[str] = set()
    excluded: set[str] = set()
    for line in result.stdout.splitlines():
        match = _RECENT_BRANCH_RE.search(line)
        if match is None:
            continue
        operation, exclude_name, branch_name = match.group(1), match.group(2), match.group(3)
        if operation.lower() == "renamed":
            excluded.add(exclude_name)
        if branch_name in excluded or branch_name in seen:
            continue
        seen.add(branch_name)
        names.append(branch_name)
        if len(names) >= limit:
            break
    return names


def get_branch_checkouts(repo: str, after) -> dict[str, str]:
    """Distinct branch checkouts on or after `after` (Desktop `getBranchCheckouts`)."""
    stamp = after.isoformat() if hasattr(after, "isoformat") else str(after)
    result = git(
        [
            "reflog",
            "--date=iso",
            f'--after="{stamp}"',
            "--pretty=%H %gd %gs",
            "--grep-reflog=checkout: moving from .* to .*$",
            "--",
        ],
        repo,
        success_exit_codes={0, 128},
        name="getCheckoutsAfterDate",
    )
    checkouts: dict[str, str] = {}
    if result.exit_code == 128 and _NO_COMMITS_ON_BRANCH_RE.search(result.stderr):
        return checkouts
    for line in result.stdout.splitlines():
        parsed = _BRANCH_CHECKOUT_RE.match(line)
        if parsed is None:
            continue
        timestamp, branch_name = parsed.group(1), parsed.group(2)
        if branch_name not in checkouts:
            checkouts[branch_name] = timestamp
    return checkouts


def get_files_with_conflict_markers(repo: str) -> dict[str, int]:
    """Paths with leftover conflict-marker counts (Desktop `getFilesWithConflictMarkers`)."""
    result = git(
        ["diff", "--check"],
        repo,
        success_exit_codes={0, 2},
        name="getFilesWithConflictMarkers",
    )
    files: dict[str, int] = {}
    for match in _CONFLICT_MARKER_RE.finditer(result.stdout):
        path = match.group(1)
        files[path] = files.get(path, 0) + 1
    return files


def parse_credential(value: str) -> dict[str, str]:
    """Parse Git credential helper stdin (Desktop `parseCredential`)."""
    cred: dict[str, str] = {}
    for line in re.split(r"\r?\n", value):
        eq = line.find("=")
        if eq < 0:
            continue
        key, val = line[:eq], line[eq + 1 :]
        if key.endswith("[]"):
            index = 0
            new_key = f"{key[:-2]}[{index}]"
            while new_key in cred:
                index += 1
                new_key = f"{key[:-2]}[{index}]"
            cred[new_key] = val
        else:
            cred[key] = val
    return cred


def format_credential(credential: dict[str, str]) -> str:
    """Serialize a credential map for Git helper stdin (Desktop `formatCredential`)."""
    lines: list[str] = []
    for key, val in credential.items():
        if "\n" in val or "\0" in val:
            raise GitError(f"forbidden characters in credential value: {key}")
        lines.append(f"{_CREDENTIAL_INDEX_RE.sub('[]', key)}={val}\n")
    return "".join(lines)


def _credential_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    merged = {"GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "TERM": "dumb"}
    if env:
        merged.update({key: value for key, value in env.items() if value is not None})
    return merged


def _exec_credential(
    action: str,
    credential: dict[str, str],
    path: str,
    env: Mapping[str, str] | None = None,
    *,
    helper: str | None = None,
) -> dict[str, str]:
    """Run `git credential fill|approve|reject` without forcing Git Credential Manager."""
    args: list[str] = []
    if helper is not None:
        args += ["-c", "credential.helper=", "-c", f"credential.helper={helper}"]
    args += ["credential", action]
    result = git(
        args,
        path,
        stdin=format_credential(credential),
        env=_credential_env(env),
        name=f"{action}Credential",
    )
    parsed = parse_credential(result.stdout)
    return parsed or dict(credential)


def fill_credential(
    credential: dict[str, str],
    path: str,
    env: Mapping[str, str] | None = None,
    *,
    helper: str | None = None,
) -> dict[str, str]:
    """Desktop `fillCredential`. Uses configured helpers (not `credential.helper=manager`)."""
    return _exec_credential("fill", credential, path, env, helper=helper)


def approve_credential(
    credential: dict[str, str],
    path: str,
    env: Mapping[str, str] | None = None,
    *,
    helper: str | None = None,
) -> dict[str, str]:
    """Desktop `approveCredential`."""
    return _exec_credential("approve", credential, path, env, helper=helper)


def reject_credential(
    credential: dict[str, str],
    path: str,
    env: Mapping[str, str] | None = None,
    *,
    helper: str | None = None,
) -> dict[str, str]:
    """Desktop `rejectCredential`."""
    return _exec_credential("reject", credential, path, env, helper=helper)


def determine_mergeability(repo: str, ours_sha: str, theirs_sha: str) -> MergeTreeResult:
    """Port of Desktop determineMergeability using `git merge-tree --write-tree`."""
    result = git(
        [
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--no-messages",
            "-z",
            ours_sha,
            theirs_sha,
        ],
        repo,
        success_exit_codes={0, 1},
        expected_errors={"CannotMergeUnrelatedHistories"},
        name="determineMergeability",
    )
    if result.git_error == "CannotMergeUnrelatedHistories":
        return MergeTreeResult(kind=ComputedAction.INVALID)
    blob = f"{result.stderr}\n{result.stdout}".lower()
    if "unrelated histories" in blob:
        return MergeTreeResult(kind=ComputedAction.INVALID)
    if result.exit_code not in {0, 1}:
        return MergeTreeResult(kind=ComputedAction.CLEAN)
    conflicted = max(0, result.stdout.count("\0") - 1)
    if conflicted > 0:
        return MergeTreeResult(kind=ComputedAction.CONFLICTS, conflicted_files=conflicted)
    return MergeTreeResult(kind=ComputedAction.CLEAN)


def get_merge_base(repo: str, a: str, b: str) -> str | None:
    result = git(["merge-base", a, b], repo, success_exit_codes={0, 1, 128}, name="mergeBase")
    sha = result.stdout.strip()
    return sha or None


def get_branch_merge_base_changed_files(
    repo: str,
    base_branch: str,
    comparison_branch: str,
    latest_sha: str,
) -> ChangesetData | None:
    """Desktop `getBranchMergeBaseChangedFiles`."""
    merge_base = get_merge_base(repo, base_branch, comparison_branch)
    if not merge_base:
        return None
    result = git(
        ["diff", "--merge-base", base_branch, comparison_branch, "-C", "-M", "-z", "--raw", "--numstat", "--"],
        repo,
        success_exit_codes={0, 1, 128},
        name="getBranchMergeBaseChangedFiles",
    )
    if result.exit_code == 128:
        return None
    return parse_raw_log_with_numstat(result.stdout, latest_sha, merge_base)


def get_branch_merge_base_diff(
    repo: str,
    path: str,
    base_branch: str,
    comparison_branch: str,
    status: FileStatus | None = None,
    hide_whitespace: bool = False,
    context_lines: int | None = None,
    latest_sha: str | None = None,
) -> FileDiff:
    """Desktop `getBranchMergeBaseDiff`."""
    args = ["diff", "--merge-base", base_branch, comparison_branch]
    if hide_whitespace:
        args.append("-w")
    args += ["--patch-with-raw", "-z", "--no-color"]
    if context_lines is not None:
        args.append(f"-U{int(context_lines)}")
    args += ["--", ensure_relative_path(path)]
    _append_old_path(args, path, status)
    result = git(args, repo, success_exit_codes={0, 1}, name="getBranchMergeBaseDiff")
    commitish = latest_sha or comparison_branch
    return _diff_from_result(repo, path, status or FileStatus(AppFileStatusKind.MODIFIED), result, commitish)


def get_files_diff_text(
    repo: str,
    files: Sequence[WorkingDirectoryFileChange],
    commitish: str | None = None,
) -> str:
    """Desktop `getFilesDiffText`: stage selected files, then `git diff --staged`."""
    unstage_all(repo)
    stage_files(repo, files)
    args = ["diff", "--no-ext-diff", "--patch-with-raw", "--no-color", "--staged"]
    if commitish:
        args.append(commitish)
    try:
        result = git(args, repo, name="getFilesDiffText", binary=True)
    finally:
        unstage_all(repo)
    data = result.stdout_bytes or result.stdout.encode("utf-8", errors="replace")
    if len(data) > 10 * 1024 * 1024:
        raise GitError("Diff is too large to render", args=args)
    return data.decode("utf-8", errors="replace")


def get_authors(repo: str, shas: Sequence[str]) -> list[CommitIdentity]:
    if not shas:
        return []
    result = git(
        ["log", "--format=format:%an <%ae> %ad", "--no-walk=unsorted", "--date=raw", "-z", "--stdin"],
        repo,
        stdin="\n".join(shas),
        name="getAuthors",
    )
    authors = [CommitIdentity.parse_raw(chunk) for chunk in result.stdout.split("\0") if chunk.strip()]
    return authors


def get_branches_pointed_at(repo: str, commitish: str) -> list[str] | None:
    result = git(
        ["branch", f"--points-at={commitish}", "--format=%(refname:short)"],
        repo,
        success_exit_codes={0, 1, 129},
        name="branchPointedAt",
    )
    if result.exit_code in {1, 129}:
        return None
    return [line for line in result.stdout.splitlines() if line]


def get_merged_branches(repo: str, branch_name: str) -> dict[str, str]:
    canonical = format_as_local_ref(branch_name)
    parser = create_for_each_ref_parser(
        {
            "sha": "%(objectname)",
            "canonicalRef": "%(refname)",
        }
    )
    result = git(
        ["branch", *parser.format_args, "--merged", branch_name],
        repo,
        name="mergedBranches",
    )
    merged: dict[str, str] = {}
    for entry in parser.parse(result.stdout):
        ref = entry.get("canonicalRef") or ""
        if ref and ref != canonical:
            merged[ref] = entry.get("sha") or ""
    return merged


def get_symbolic_ref(repo: str, ref: str) -> str | None:
    result = git(
        ["symbolic-ref", "-q", ref],
        repo,
        success_exit_codes={0, 1, 128},
        name="getSymbolicRef",
    )
    if result.exit_code in {1, 128}:
        return None
    return result.stdout.strip() or None


def update_remote_head(repo: str, remote: str, *, env: dict[str, str] | None = None) -> None:
    """Desktop `updateRemoteHEAD`: `git remote set-head -a <remote>`."""
    git(
        ["remote", "set-head", "-a", remote],
        repo,
        env=env,
        success_exit_codes={0, 1, 128},
        name="updateRemoteHEAD",
    )


def get_remote_head(repo: str, remote: str) -> str | None:
    """Desktop `getRemoteHEAD`: local branch name of `refs/remotes/<remote>/HEAD`."""
    prefix = f"refs/remotes/{remote}/"
    match = get_symbolic_ref(repo, f"{prefix}HEAD")
    if match and match.startswith(prefix) and len(match) > len(prefix):
        return match[len(prefix) :]
    return None


def find_forked_remotes_to_prune(
    remotes: Sequence[Remote],
    open_prs: Sequence[PullRequest],
    branches: Sequence[Branch],
) -> list[Remote]:
    pr_urls = {pr.head_clone_url for pr in open_prs if pr.head_clone_url}
    branch_remotes = {b.upstream_remote_name for b in branches if b.upstream_remote_name}
    return [
        remote
        for remote in remotes
        if remote.name.startswith(FORKED_REMOTE_PREFIX)
        and remote.url not in pr_urls
        and remote.name not in branch_remotes
    ]


def prune_forked_remotes(
    repo: str,
    open_prs: Sequence[PullRequest],
    branches: Sequence[Branch] | None = None,
) -> list[str]:
    remotes = get_remotes(repo)
    all_branches = list(branches) if branches is not None else get_branches(repo)
    removed: list[str] = []
    for remote in find_forked_remotes_to_prune(remotes, open_prs, all_branches):
        try:
            remove_remote(repo, remote.name)
            removed.append(remote.name)
        except GitError as exc:
            log.debug("Failed to prune fork remote %s: %s", remote.name, exc)
    return removed


def get_upstream_ref_for_local_branch_ref(
    ref: str,
    all_branches: Sequence[Branch],
) -> str | None:
    """Desktop `getUpstreamRefForLocalBranchRef`."""
    branch = next((b for b in all_branches if format_as_local_ref(b.name) == ref), None)
    if branch is None or not branch.upstream:
        return None
    return format_as_local_ref(branch.upstream)


def prune_merged_branches(
    repo: str,
    default_branch: str,
    branches: Sequence[Branch],
    *,
    delete: bool = True,
) -> list[str]:
    """Desktop BranchPruner: delete merged local branches whose upstream is gone."""
    from datetime import datetime, timezone

    from ..offset_from import offset_from_now

    merged = get_merged_branches(repo, default_branch)
    current = get_symbolic_ref(repo, "HEAD")
    if current:
        merged.pop(current, None)
    two_weeks = datetime.fromtimestamp(offset_from_now(-14, "days") / 1000.0, tz=timezone.utc)
    recent = {format_as_local_ref(name) for name in get_branch_checkouts(repo, two_weeks)}
    remote_local_refs = {format_as_local_ref(b.name) for b in get_branches(repo, "refs/remotes/")}
    ready: list[str] = []
    for ref in merged:
        if ref in RESERVED_BRANCH_REFS or ref in recent:
            continue
        upstream_ref = get_upstream_ref_for_local_branch_ref(ref, branches)
        if upstream_ref is None or upstream_ref in remote_local_refs:
            continue
        ready.append(ref)
    deleted: list[str] = []
    for ref in ready:
        if not ref.startswith("refs/heads/"):
            continue
        name = ref[len("refs/heads/") :]
        if delete:
            try:
                delete_local_branch(repo, name)
                deleted.append(name)
            except GitError as exc:
                log.debug("Failed to prune merged branch %s: %s", name, exc)
        else:
            deleted.append(name)
    return deleted


def rev_range(from_ref: str, to_ref: str) -> str:
    return f"{from_ref}..{to_ref}"


def rev_range_inclusive(from_ref: str, to_ref: str) -> str:
    """Desktop `revRangeInclusive`: include the `from` commit."""
    return f"{from_ref}^..{to_ref}"


def rev_symmetric_difference(from_ref: str, to_ref: str) -> str:
    """Desktop `revSymmetricDifference`."""
    return f"{from_ref}...{to_ref}"


def get_default_branch() -> str:
    value = get_config_value(None, "init.defaultBranch", global_only=True)
    return value or "main"


def set_default_branch(name: str) -> None:
    set_config_value(None, "init.defaultBranch", name, global_only=True)


def get_author_identity(repo: str | None = None) -> tuple[str | None, str | None]:
    """Desktop `getAuthorIdentity` via `git var GIT_AUTHOR_IDENT`.

    Exit 128 (`user.useConfigOnly` with missing name/email) or a parse failure
    returns ``(None, None)``. There is no ``user.name`` / ``user.email`` fallback.
    """
    cwd = repo or os.path.expanduser("~")
    try:
        result = git(
            ["var", "GIT_AUTHOR_IDENT"],
            cwd,
            success_exit_codes={0, 128},
            name="getAuthorIdentity",
        )
    except (GitError, GitNotFoundError, OSError):
        return None, None
    if result.exit_code == 128:
        return None, None
    try:
        ident = CommitIdentity.parse_identity(result.stdout)
    except ValueError:
        return None, None
    return ident.name, ident.email


def get_global_config_path() -> str:
    result = git(
        ["config", "--edit", "--global"],
        os.path.expanduser("~"),
        env={"GIT_EDITOR": "printf %s"},
        name="getGlobalConfigPath",
    )
    return os.path.normpath(result.stdout.strip() or os.path.expanduser("~/.gitconfig"))


# Desktop DefaultGitDescription
DEFAULT_GIT_DESCRIPTION = "Unnamed repository; edit this file 'description' to name the repository.\n"


def write_description(repo: str, description: str) -> None:
    git_dir = _git_dir(repo)
    Path(os.path.join(git_dir, "description")).write_text(description, encoding="utf-8")


def read_description(repo: str) -> str:
    """Desktop `getGitDescription`: empty only when the file is the default text."""
    git_dir = _git_dir(repo)
    try:
        text = Path(os.path.join(git_dir, "description")).read_text(encoding="utf-8")
        if text == DEFAULT_GIT_DESCRIPTION:
            return ""
        return text
    except OSError:
        return ""


def get_git_description(repo: str) -> str:
    """Desktop `getGitDescription`."""
    return read_description(repo)


def write_git_description(repo: str, description: str) -> None:
    """Desktop `writeGitDescription`."""
    write_description(repo, description)


def list_worktree_files(repo: str) -> list[str]:
    result = git(["ls-files", "-z"], repo, name="lsFilesAll")
    return [p for p in result.stdout.split("\0") if p]


def ensure_repository(path: str) -> str:
    root = resolve_repository_root(path)
    if not root:
        raise NotARepositoryError(f"{path} is not a Git repository")
    return root


def get_repository_type(path: str) -> dict[str, str]:
    """Desktop `getRepositoryType`: bare / regular (+ toplevel) / unsafe / missing."""
    from ..directory_exists import directory_exists

    if not path or not directory_exists(path):
        return {"kind": "missing"}
    try:
        result = git(
            ["rev-parse", "--is-bare-repository", "--show-cdup"],
            path,
            success_exit_codes={0, 128},
            name="getRepositoryType",
        )
    except GitError:
        return {"kind": "missing"}
    if result.exit_code == 0:
        lines = result.stdout.split("\n", 2)
        is_bare = (lines[0] if lines else "").strip()
        cdup = lines[1].strip() if len(lines) > 1 else ""
        if is_bare == "true":
            return {"kind": "bare"}
        top = os.path.abspath(os.path.join(path, cdup if cdup else "."))
        return {"kind": "regular", "topLevelWorkingDirectory": top}
    combined = f"{result.stderr}\n{result.stdout}"
    match = re.search(r"fatal: detected dubious ownership in repository at '(.+)'", combined)
    if match:
        return {"kind": "unsafe", "path": match.group(1)}
    lowered = combined.lower()
    if "dubious ownership" in lowered or "safe.directory" in lowered:
        return {"kind": "unsafe", "path": path}
    return {"kind": "missing"}


def get_repository_kind(path: str) -> str:
    """Return 'regular', 'bare', 'missing', or 'unsafe' (dubious ownership / safe.directory)."""
    return get_repository_type(path).get("kind") or "missing"


def is_merge_head_set(repo: str) -> bool:
    """Desktop `isMergeHeadSet`."""
    return _path_exists(repo, ".git/MERGE_HEAD")


def is_squash_msg_set(repo: str) -> bool:
    """Desktop `isSquashMsgSet`."""
    return _path_exists(repo, ".git/SQUASH_MSG")


def is_cherry_pick_head_found(repo: str) -> bool:
    """Desktop `isCherryPickHeadFound`."""
    return _path_exists(repo, ".git/CHERRY_PICK_HEAD")


def get_remote_url(repo: str, name: str) -> str | None:
    """Desktop `getRemoteURL`."""
    result = git(
        ["remote", "get-url", name],
        repo,
        success_exit_codes={0, 2, 128},
        name="getRemoteURL",
    )
    if result.exit_code != 0:
        return None
    return result.stdout.strip() or None


def get_upstream_ref_for_ref(path: str, ref: str | None = None) -> str | None:
    """Desktop `getUpstreamRefForRef`."""
    rev = f"{ref or ''}@{{upstream}}"
    result = git(
        ["rev-parse", "--symbolic-full-name", rev],
        path,
        success_exit_codes={0, 128},
        name="getUpstreamRefForRef",
    )
    if result.exit_code != 0:
        return None
    return result.stdout.strip() or None


def get_upstream_remote_name_for_ref(path: str, ref: str | None = None) -> str | None:
    """Desktop `getUpstreamRemoteNameForRef`."""
    remote_ref = get_upstream_ref_for_ref(path, ref)
    if not remote_ref:
        return None
    match = re.match(r"^refs/remotes/([^/]+)/", remote_ref)
    return match.group(1) if match else None


def get_current_upstream_ref(path: str) -> str | None:
    """Desktop `getCurrentUpstreamRef`."""
    return get_upstream_ref_for_ref(path)


def get_current_upstream_remote_name(path: str) -> str | None:
    """Desktop `getCurrentUpstreamRemoteName`."""
    return get_upstream_remote_name_for_ref(path)


def add_global_config_value(name: str, value: str) -> None:
    git(
        ["config", "--global", "--add", name, value],
        os.path.expanduser("~"),
        name="addGlobalConfigValue",
    )


def add_global_config_value_if_missing(name: str, value: str) -> None:
    """Desktop `addGlobalConfigValueIfMissing`."""
    result = git(
        ["config", "--global", "-z", "--get-all", name, value],
        os.path.expanduser("~"),
        success_exit_codes={0, 1},
        name="addGlobalConfigValue",
    )
    existing = [item for item in result.stdout.split("\0") if item]
    if result.exit_code == 1 or value not in existing:
        add_global_config_value(name, value)


def add_safe_directory(path: str) -> None:
    add_global_config_value_if_missing("safe.directory", path)
