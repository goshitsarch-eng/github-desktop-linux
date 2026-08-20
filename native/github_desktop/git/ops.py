"""High-level Git operations matching GitHub Desktop's lib/git API."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Sequence

from ..errors import GitError, NotARepositoryError
from ..logging import get_logger
from ..models import (
    DESKTOP_STASH_MARKER,
    IMAGE_EXTENSIONS,
    MAX_REASONABLE_DIFF_SIZE,
    AppFileStatusKind,
    AheadBehind,
    Author,
    BinaryDiff,
    Branch,
    BranchType,
    CherryPickResult,
    Commit,
    CommitIdentity,
    CommitMessage,
    CommittedFileChange,
    DiffSelection,
    DiffSelectionType,
    DiffType,
    FileDiff,
    FileStatus,
    IStatusResult,
    ImageDiff,
    LargeTextDiff,
    ManualConflictResolution,
    MergeResult,
    RebaseInternalState,
    RebaseResult,
    Remote,
    Repository,
    StashEntry,
    SubmoduleDiff,
    SubmoduleStatus,
    TextDiff,
    UnrenderableDiff,
    WorkingDirectoryFileChange,
    WorkingDirectoryStatus,
)
from .diff import (
    format_partial_patch,
    is_buffer_too_large,
    is_valid_buffer,
    parse_unified_diff,
    selectable_line_indices,
)
from .runner import GitResult, env_for_remote, git, git_path_is_repository, resolve_repository_root
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


def get_status(repo_path: str, include_untracked: bool = True) -> IStatusResult | None:
    if not os.path.isdir(repo_path):
        return IStatusResult(exists=False)
    args = ["--no-optional-locks", "status"]
    if include_untracked:
        args += ["--untracked-files=all"]
    args += ["--branch", "--porcelain=2", "-z"]
    try:
        result = git(args, repo_path, success_exit_codes={0, 128}, name="getStatus", binary=True)
    except GitError:
        return None
    if result.exit_code == 128:
        return None
    parsed = parse_porcelain_status(result.stdout_bytes or result.stdout.encode("utf-8"))
    headers = [p for p in parsed if isinstance(p, StatusHeader)]
    entries = [p for p in parsed if isinstance(p, StatusEntry)]
    info = parse_status_headers(headers)
    files: dict[str, WorkingDirectoryFileChange] = {}
    conflicted = []
    for entry in entries:
        if should_skip_entry(entry):
            continue
        if entry.status_code in CONFLICT_STATUS_CODES:
            conflicted.append(entry)
        if entry.status_code == "??":
            files.pop(entry.path, None)
        status = convert_to_app_status(entry)
        if status.kind == AppFileStatusKind.CONFLICTED:
            status.conflict_marker_count = _conflict_marker_count(repo_path, entry.path)
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
    ab = info["ahead_behind"]
    ahead_behind = AheadBehind(*ab) if isinstance(ab, tuple) else None
    return IStatusResult(
        exists=True,
        current_branch=info["current_branch"],  # type: ignore[arg-type]
        current_upstream_branch=info["current_upstream_branch"],  # type: ignore[arg-type]
        current_tip=info["current_tip"],  # type: ignore[arg-type]
        branch_ahead_behind=ahead_behind,
        working_directory=WorkingDirectoryStatus.from_files(list(files.values())),
        merge_head_found=_path_exists(repo_path, ".git/MERGE_HEAD"),
        squash_msg_found=_path_exists(repo_path, ".git/SQUASH_MSG"),
        rebase_internal_state=get_rebase_internal_state(repo_path),
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


def is_binary_path(repo: str, path: str) -> bool:
    try:
        result = git(["diff", "--numstat", "HEAD", "--", path], repo, name="numstat")
        line = result.stdout.strip().splitlines()[:1]
        if line and line[0].startswith("-\t-\t"):
            return True
    except GitError:
        pass
    return False


def get_working_directory_diff(
    repo: str,
    file: WorkingDirectoryFileChange,
    hide_whitespace: bool = False,
) -> FileDiff:
    args = ["diff", "--no-ext-diff", "--patch", "--no-color"]
    if hide_whitespace:
        args.append("-w")
    if file.status.kind in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
        args = ["diff", "--no-ext-diff", "--no-index", "--patch", "--no-color", "--", "/dev/null", file.path]
        result = git(args, repo, success_exit_codes={0, 1, 2}, name="diffNew")
    elif file.status.kind == AppFileStatusKind.RENAMED and file.status.old_path:
        args += ["HEAD", "--", file.status.old_path, file.path]
        result = git(args, repo, success_exit_codes={0, 1}, name="diffRename")
    else:
        args += ["HEAD", "--", file.path]
        result = git(args, repo, success_exit_codes={0, 1}, name="diffWd")
    return _diff_from_result(repo, file.path, file.status, result, commitish=None)


def get_commit_diff(
    repo: str,
    path: str,
    commitish: str,
    status: FileStatus | None = None,
    hide_whitespace: bool = False,
) -> FileDiff:
    args = ["diff", "--no-ext-diff", "--patch", "--no-color"]
    if hide_whitespace:
        args.append("-w")
    args += [f"{commitish}^", commitish, "--", path]
    result = git(args, repo, success_exit_codes={0, 1, 128}, name="commitDiff")
    if result.exit_code == 128:
        # root commit
        result = git(
            ["show", "--no-ext-diff", "--patch", "--no-color", "--format=", commitish, "--", path],
            repo,
            success_exit_codes={0, 1},
            name="rootCommitDiff",
        )
    return _diff_from_result(repo, path, status or FileStatus(AppFileStatusKind.MODIFIED), result, commitish)


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
    if is_buffer_too_large(data):
        return LargeTextDiff(text=result.stdout[:50_000])
    parsed = parse_unified_diff(result.stdout)
    if parsed.is_binary or (
        "Binary files" in result.stdout or "GIT binary patch" in result.stdout
    ):
        if ext in IMAGE_EXTENSIONS:
            return _image_diff(repo, path, status, commitish)
        return BinaryDiff()
    return parsed


def _image_diff(repo: str, path: str, status: FileStatus, commitish: str | None) -> ImageDiff:
    previous = current = None
    full = os.path.join(repo, path)
    if status.kind not in (AppFileStatusKind.NEW, AppFileStatusKind.UNTRACKED):
        spec = f"{commitish or 'HEAD'}:{path}"
        try:
            previous = git(["show", spec], repo, name="showImage", success_exit_codes={0, 128}).stdout_bytes
        except GitError:
            previous = None
    if status.kind != AppFileStatusKind.DELETED:
        try:
            with open(full, "rb") as fh:
                current = fh.read()
        except OSError:
            if commitish:
                try:
                    current = git(["show", f"{commitish}:{path}"], repo, name="showImageNew").stdout_bytes
                except GitError:
                    current = None
    media = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
        ".avif": "image/avif",
    }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
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
    git(["reset", "--mixed", "HEAD"], repo, success_exit_codes={0, 128}, name="unstageAll")


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
    if not isinstance(diff, TextDiff):
        # Full-file stage for binary/image/submodule
        update_index(repo, [file.path])
        return
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


def stage_manual_resolution(repo: str, path: str, resolution: ManualConflictResolution) -> None:
    checkout_arg = "--ours" if resolution == ManualConflictResolution.OURS else "--theirs"
    git(["checkout", checkout_arg, "--", path], repo, name="checkoutConflict")
    git(["add", "--", path], repo, name="addResolved")


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


def format_commit_message(
    summary: str,
    description: str = "",
    trailers: Sequence[tuple[str, str]] = (),
) -> str:
    parts = [summary.strip()]
    if description.strip():
        parts.append("")
        parts.append(description.strip())
    if trailers:
        parts.append("")
        for token, value in trailers:
            parts.append(f"{token}: {value}")
    return "\n".join(parts) + "\n"


def co_author_trailers(authors: Sequence[Author]) -> list[tuple[str, str]]:
    return [("Co-authored-by", f"{a.name} <{a.email}>") for a in authors]


def get_commits(
    repo: str,
    revision_range: str | None = None,
    limit: int | None = 100,
    skip: int | None = None,
    extra: Sequence[str] = (),
) -> list[Commit]:
    fields = ["%H", "%h", "%s", "%b", "%an <%ae> %ad", "%cn <%ce> %cd", "%P", "%(trailers:unfold,only)", "%D"]
    fmt = "%x00".join(fields)
    args = ["log"]
    if revision_range:
        args.append(revision_range)
    args += ["--date=raw", "-z", f"--format={fmt}", "--no-show-signature", "--no-color"]
    if limit is not None:
        args.append(f"--max-count={limit}")
    if skip is not None:
        args.append(f"--skip={skip}")
    args += list(extra)
    args.append("--")
    result = git(args, repo, success_exit_codes={0, 128}, name="getCommits")
    if result.exit_code == 128:
        return []
    return _parse_log(result.stdout)


def _parse_log(stdout: str) -> list[Commit]:
    records = stdout.split("\0")
    keys = 9
    commits: list[Commit] = []
    # Drop leading empty
    if records and records[0] == "":
        records = records[1:]
    for i in range(0, len(records) - keys + 1, keys):
        chunk = records[i : i + keys]
        if len(chunk) < keys:
            break
        sha, short, summary, body, author, committer, parents, trailers, refs = chunk
        if not sha:
            continue
        tags = []
        for part in refs.split(", "):
            part = part.strip()
            if part.startswith("tag: "):
                tags.append(part[5:])
        trailer_pairs: list[tuple[str, str]] = []
        for line in trailers.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                trailer_pairs.append((k.strip(), v.strip()))
        commits.append(
            Commit(
                sha=sha,
                short_sha=short,
                summary=summary,
                body=body.strip(),
                author=CommitIdentity.parse_raw(author),
                committer=CommitIdentity.parse_raw(committer),
                parent_shas=parents.split() if parents else [],
                trailers=trailer_pairs,
                tags=tags,
            )
        )
    return commits


def get_commit(repo: str, sha: str) -> Commit | None:
    commits = get_commits(repo, sha, limit=1)
    return commits[0] if commits else None


def get_changed_files(repo: str, sha: str) -> list[CommittedFileChange]:
    args = ["log", sha, "-1", "--name-status", "-M", "-C", "--format=", "-z"]
    result = git(args, repo, name="nameStatus")
    tokens = [t for t in result.stdout.split("\0") if t]
    files: list[CommittedFileChange] = []
    i = 0
    parents = get_commit(repo, sha)
    parent = parents.parent_shas[0] if parents and parents.parent_shas else None
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
                status=FileStatus(kind, old_path=old_path, rename_includes_modifications=kind_ch.startswith("R") and status != "R100"),
                commitish=sha,
                parent_commitish=parent,
            )
        )
    return files


def get_branches(repo: str, *prefixes: str) -> list[Branch]:
    prefixes = prefixes or ("refs/heads", "refs/remotes")
    fmt = "%00".join(
        ["%(refname)", "%(refname:short)", "%(upstream:short)", "%(objectname)", "%(symref)"]
    )
    result = git(
        ["for-each-ref", f"--format=%00{fmt}%00", *prefixes],
        repo,
        success_exit_codes={0, 128},
        name="getBranches",
    )
    if result.exit_code == 128:
        return []
    records = result.stdout.split("\0")
    branches: list[Branch] = []
    # format starts with %00 so first record is empty
    i = 1
    fields = 5
    while i + fields <= len(records):
        full, short, upstream, sha, symref = records[i : i + fields]
        i += fields + 1  # skip newline record
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
                upstream_without_remote=upstream.split("/", 1)[-1] if upstream else None,
                ref=ref,
            )
        )
    return branches


def create_branch(repo: str, name: str, start_point: str | None = None) -> None:
    args = ["branch", "--", name]
    if start_point:
        args = ["branch", "--", name, start_point]
    git(args, repo, name="createBranch")


def rename_branch(repo: str, old: str, new: str) -> None:
    git(["branch", "-m", old, new], repo, name="renameBranch")


def delete_local_branch(repo: str, name: str) -> None:
    git(["branch", "-D", "--", name], repo, name="deleteLocalBranch")


def delete_remote_branch(repo: str, remote: str, name: str, env: dict[str, str] | None = None) -> None:
    git(["push", remote, "--delete", name], repo, env=env, name="deleteRemoteBranch")


def checkout_branch(repo: str, name: str) -> None:
    git(["checkout", "--", name] if False else ["checkout", name], repo, name="checkout")


def checkout_commit(repo: str, sha: str) -> None:
    git(["checkout", sha], repo, name="checkoutCommit")


def checkout_paths(repo: str, paths: Sequence[str]) -> None:
    if not paths:
        return
    git(["checkout", "--", *paths], repo, name="checkoutPaths")


def get_remotes(repo: str) -> list[Remote]:
    result = git(["remote", "-v"], repo, name="getRemotes")
    remotes: dict[str, Remote] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] not in remotes:
            remotes[parts[0]] = Remote(parts[0], parts[1])
    return list(remotes.values())


def add_remote(repo: str, name: str, url: str) -> None:
    git(["remote", "add", name, url], repo, name="addRemote")


def remove_remote(repo: str, name: str) -> None:
    git(["remote", "remove", name], repo, name="removeRemote")


def set_remote_url(repo: str, name: str, url: str) -> None:
    git(["remote", "set-url", name, url], repo, name="setRemoteUrl")


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
    git(args, parent, env=merged, name="clone")


def fetch(
    repo: str,
    remote: str = "origin",
    *,
    env: dict[str, str] | None = None,
) -> None:
    git(["fetch", "--prune", remote], repo, env=env, name="fetch")


def pull(
    repo: str,
    remote: str = "origin",
    branch: str | None = None,
    *,
    env: dict[str, str] | None = None,
) -> None:
    args = ["pull", "--ff", "--no-rebase", remote]
    if branch:
        args.append(branch)
    git(args, repo, env=env, name="pull")


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
) -> None:
    refspec = f"{local_branch}:{remote_branch}" if remote_branch else local_branch
    args = ["push", remote, refspec]
    if tags:
        args += list(tags)
    if set_upstream or not remote_branch:
        args.append("--set-upstream")
    if force_with_lease:
        args.append("--force-with-lease")
    git(args, repo, env=env, name="push")


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
        result = git(args, repo, name="merge")
        if "Already up to date" in result.stdout:
            return MergeResult.ALREADY_UP_TO_DATE
        return MergeResult.SUCCESS
    except GitError as exc:
        if exc.is_conflicts or _path_exists(repo, ".git/MERGE_HEAD"):
            return MergeResult.FAILED
        raise


def abort_merge(repo: str) -> None:
    git(["merge", "--abort"], repo, name="abortMerge")


def rebase(repo: str, base_branch: str) -> RebaseResult:
    try:
        result = git(["rebase", base_branch], repo, name="rebase")
        if "is up to date" in result.stdout.lower() or "up to date" in result.stderr.lower():
            return RebaseResult.ALREADY_UP_TO_DATE
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError as exc:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        if "no rebase in progress" in (exc.stderr + exc.stdout).lower():
            return RebaseResult.ERROR
        return RebaseResult.ERROR


def continue_rebase(repo: str) -> RebaseResult:
    status = get_status(repo)
    if status and any(f.status.kind == AppFileStatusKind.CONFLICTED for f in status.working_directory.files):
        return RebaseResult.CONFLICTS_ENCOUNTERED
    try:
        git(["-c", "core.editor=true", "rebase", "--continue"], repo, name="rebaseContinue")
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        return RebaseResult.ERROR


def abort_rebase(repo: str) -> None:
    git(["rebase", "--abort"], repo, name="abortRebase")


def cherry_pick(repo: str, shas: Sequence[str]) -> CherryPickResult:
    if not shas:
        return CherryPickResult.UNABLE_TO_START
    try:
        git(["cherry-pick", *shas], repo, name="cherryPick")
        return CherryPickResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
            return CherryPickResult.CONFLICTS_ENCOUNTERED
        return CherryPickResult.ERROR


def continue_cherry_pick(repo: str) -> CherryPickResult:
    try:
        git(["-c", "core.editor=true", "cherry-pick", "--continue"], repo, name="cherryContinue")
        return CherryPickResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if _path_exists(repo, ".git/CHERRY_PICK_HEAD"):
            return CherryPickResult.CONFLICTS_ENCOUNTERED
        return CherryPickResult.ERROR


def abort_cherry_pick(repo: str) -> None:
    git(["cherry-pick", "--abort"], repo, name="abortCherry")


def revert(repo: str, sha: str) -> None:
    git(["revert", "--no-edit", sha], repo, name="revert")


def reset(repo: str, sha: str, mode: str = "mixed") -> None:
    git(["reset", f"--{mode}", sha], repo, name="reset")


def undo_commit(repo: str) -> None:
    git(["reset", "--soft", "HEAD~1"], repo, name="undoCommit")


def discard_paths(repo: str, paths: Sequence[str]) -> None:
    if not paths:
        return
    tracked = []
    untracked = []
    for path in paths:
        full = os.path.join(repo, path)
        # If the file is untracked, delete it
        result = git(["ls-files", "--", path], repo, name="lsFiles")
        if result.stdout.strip():
            tracked.append(path)
        else:
            untracked.append(path)
    if tracked:
        git(["checkout", "--", *tracked], repo, name="discardTracked")
        git(["clean", "-f", "--", *tracked], repo, success_exit_codes={0, 1}, name="cleanTracked")
    for path in untracked:
        full = os.path.join(repo, path)
        try:
            if os.path.isdir(full) and not os.path.islink(full):
                import shutil

                shutil.rmtree(full)
            elif os.path.exists(full):
                os.remove(full)
        except OSError as exc:
            log.warning("Failed to discard %s: %s", path, exc)


def stash_push(repo: str, branch_name: str, paths: Sequence[str] | None = None) -> None:
    message = f"{DESKTOP_STASH_MARKER}<{branch_name}>"
    args = ["stash", "push", "-m", message]
    if paths:
        args += ["--"] + list(paths)
    git(args, repo, name="stashPush")


def stash_pop(repo: str, stash_ref: str = "stash@{0}") -> None:
    git(["stash", "pop", "--", stash_ref] if False else ["stash", "pop", stash_ref], repo, name="stashPop")


def stash_drop(repo: str, stash_ref: str) -> None:
    git(["stash", "drop", stash_ref], repo, name="stashDrop")


def get_stashes(repo: str) -> tuple[list[StashEntry], int]:
    fields = ["%gD", "%H", "%gs", "%T", "%P"]
    fmt = "%x00".join(fields)
    result = git(
        ["log", "-g", "-z", f"--format={fmt}", "refs/stash", "--"],
        repo,
        success_exit_codes={0, 128},
        name="getStashes",
    )
    if result.exit_code == 128:
        return [], 0
    records = [r for r in result.stdout.split("\0")]
    if records and records[0] == "":
        records = records[1:]
    entries: list[StashEntry] = []
    total = 0
    marker_re = re.compile(r"!!GitHub_Desktop<(.+)>$")
    for i in range(0, len(records) - 4, 5):
        name, sha, message, tree, parents = records[i : i + 5]
        if not name:
            continue
        total += 1
        match = marker_re.search(message)
        if match:
            entries.append(
                StashEntry(
                    name=name,
                    stash_sha=sha,
                    branch_name=match.group(1),
                    tree=tree,
                    parents=parents.split() if parents else [],
                )
            )
    return entries, total


def create_tag(repo: str, name: str, sha: str) -> None:
    git(["tag", "-a", name, "-m", name, sha], repo, name="createTag")


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


def get_config_value(repo: str | None, key: str, global_only: bool = False) -> str | None:
    args = ["config"]
    if global_only or not repo:
        args.append("--global")
    args += ["--get", key]
    cwd = repo or os.path.expanduser("~")
    result = git(args, cwd, success_exit_codes={0, 1}, name="getConfig")
    value = result.stdout.strip()
    return value or None


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
    args += ["--unset", key]
    cwd = repo or os.path.expanduser("~")
    git(args, cwd, success_exit_codes={0, 5}, name="unsetConfig")


def read_gitignore(repo: str) -> str:
    path = os.path.join(repo, ".gitignore")
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


def write_gitignore(repo: str, text: str) -> None:
    Path(os.path.join(repo, ".gitignore")).write_text(text, encoding="utf-8")


def append_ignore_rule(repo: str, pattern: str) -> None:
    current = read_gitignore(repo)
    if not current.endswith("\n") and current:
        current += "\n"
    current += pattern.rstrip("\n") + "\n"
    write_gitignore(repo, current)


def lfs_track(repo: str, patterns: Sequence[str]) -> None:
    git(["lfs", "install"], repo, name="lfsInstall")
    for pattern in patterns:
        git(["lfs", "track", pattern], repo, name="lfsTrack")


def is_lfs_repo(repo: str) -> bool:
    result = git(["lfs", "ls-files"], repo, success_exit_codes={0, 1, 128}, name="lfsLs")
    return result.exit_code == 0 and bool(result.stdout.strip())


def get_submodules(repo: str) -> list[str]:
    result = git(["submodule", "status"], repo, success_exit_codes={0, 128}, name="submodules")
    paths = []
    for line in result.stdout.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2:
            paths.append(parts[1])
    return paths


def update_submodules(repo: str) -> None:
    git(["submodule", "update", "--init", "--recursive"], repo, name="subUpdate")


def interactive_rebase_todo(
    repo: str,
    last_retained: str | None,
    todo_lines: Sequence[str],
    message_path: str | None = None,
) -> RebaseResult:
    """Run `git rebase -i` with a pre-written todo list (squash / reorder)."""
    git_dir = _git_dir(repo)
    todo_file = os.path.join(git_dir, "desktop-rebase-todo")
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
    args = ["rebase", "-i", "--autosquash"]
    args = ["rebase", "-i"]
    if last_retained:
        args.append(last_retained)
    else:
        args.append("--root")
    try:
        git(args, repo, env=env, name="rebaseInteractive", timeout=60)
        return RebaseResult.COMPLETED_WITHOUT_ERROR
    except GitError:
        if get_rebase_internal_state(repo) is not None:
            return RebaseResult.CONFLICTS_ENCOUNTERED
        return RebaseResult.ERROR


def squash_commits(
    repo: str,
    to_squash: Sequence[Commit],
    squash_onto: Commit,
    last_retained: str | None,
    message: str,
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
    fd, msg_path = tempfile.mkstemp(prefix="desktop-squash-msg-")
    os.write(fd, message.encode("utf-8"))
    os.close(fd)
    try:
        # Rewrite first pick of squash group: after pick onto, subsequent squash
        # Use GIT_EDITOR to set the combined message when squash stops
        env_editor_file = msg_path
        result = interactive_rebase_todo(repo, last_retained, todo, env_editor_file)
        return result
    finally:
        try:
            os.remove(msg_path)
        except OSError:
            pass


def reorder_commits(
    repo: str,
    to_move: Sequence[Commit],
    before: Commit | None,
    last_retained: str | None,
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
    return interactive_rebase_todo(repo, last_retained, todo)


def get_ahead_behind(repo: str, upstream: str, branch: str | None = None) -> AheadBehind | None:
    left = branch or "HEAD"
    result = git(
        ["rev-list", "--left-right", "--count", f"{upstream}...{left}"],
        repo,
        success_exit_codes={0, 128},
        name="aheadBehind",
    )
    if result.exit_code != 0:
        return None
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return None
    behind, ahead = int(parts[0]), int(parts[1])
    return AheadBehind(ahead=ahead, behind=behind)


def get_merge_base(repo: str, a: str, b: str) -> str | None:
    result = git(["merge-base", a, b], repo, success_exit_codes={0, 1, 128}, name="mergeBase")
    sha = result.stdout.strip()
    return sha or None


def rev_range(from_ref: str, to_ref: str) -> str:
    return f"{from_ref}..{to_ref}"


def get_default_branch() -> str:
    value = get_config_value(None, "init.defaultBranch", global_only=True)
    return value or "main"


def set_default_branch(name: str) -> None:
    set_config_value(None, "init.defaultBranch", name, global_only=True)


def get_author_identity(repo: str | None = None) -> tuple[str | None, str | None]:
    name = get_config_value(repo, "user.name")
    email = get_config_value(repo, "user.email")
    return name, email


def write_description(repo: str, description: str) -> None:
    git_dir = _git_dir(repo)
    Path(os.path.join(git_dir, "description")).write_text(description, encoding="utf-8")


def read_description(repo: str) -> str:
    git_dir = _git_dir(repo)
    try:
        text = Path(os.path.join(git_dir, "description")).read_text(encoding="utf-8").strip()
        if text.startswith("Unnamed repository"):
            return ""
        return text
    except OSError:
        return ""


def list_worktree_files(repo: str) -> list[str]:
    result = git(["ls-files", "-z"], repo, name="lsFilesAll")
    return [p for p in result.stdout.split("\0") if p]


def ensure_repository(path: str) -> str:
    root = resolve_repository_root(path)
    if not root:
        raise NotARepositoryError(f"{path} is not a Git repository")
    return root
