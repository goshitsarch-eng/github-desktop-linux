"""Parse `git --progress` stderr the way GitHub Desktop does."""

from __future__ import annotations

import math
import os
import tempfile
import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class ProgressStep:
    title: str
    weight: float


@dataclass(frozen=True)
class GitProgressInfo:
    title: str
    value: int
    text: str
    done: bool
    percent: int | None = None
    total: int | None = None


@dataclass(frozen=True)
class GitProgress:
    kind: str
    percent: float
    text: str
    details: GitProgressInfo | None = None


CLONE_STEPS: tuple[ProgressStep, ...] = (
    ProgressStep("remote: Compressing objects", 0.1),
    ProgressStep("Receiving objects", 0.6),
    ProgressStep("Resolving deltas", 0.1),
    ProgressStep("Checking out files", 0.2),
)

FETCH_STEPS: tuple[ProgressStep, ...] = (
    ProgressStep("remote: Compressing objects", 0.1),
    ProgressStep("Receiving objects", 0.7),
    ProgressStep("Resolving deltas", 0.2),
)

PULL_STEPS: tuple[ProgressStep, ...] = (
    ProgressStep("remote: Compressing objects", 0.1),
    ProgressStep("Receiving objects", 0.7),
    ProgressStep("Resolving deltas", 0.15),
    ProgressStep("Checking out files", 0.15),
)

PUSH_STEPS: tuple[ProgressStep, ...] = (
    ProgressStep("Compressing objects", 0.2),
    ProgressStep("Writing objects", 0.7),
    ProgressStep("remote: Resolving deltas", 0.1),
)

CHECKOUT_STEPS: tuple[ProgressStep, ...] = (ProgressStep("Checking out files", 1.0),)

REVERT_STEPS: tuple[ProgressStep, ...] = (ProgressStep("Checking out files", 1.0),)

_BYTE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")


def parse_carriage_return(text: str) -> str:
    """Desktop `parseCarriageReturn`: terminal-style ``\\r`` overwrite.

    Git (and many other CLI tools) use carriage returns to present progress.
    ``Downloading: 1%\\rDownloading: 2%\\r`` is perceived as the 1 changing to 2.
    """
    if "\r" not in text:
        return text
    rewritten: list[str] = []
    for line in text.split("\n"):
        buf = ""
        for cur in line.split("\r"):
            buf = cur if len(cur) >= len(buf) else cur + buf[len(cur) :]
        rewritten.append(buf)
    return "\n".join(rewritten)


def format_bytes(byte_count: int, decimals: int = 1, fixed: bool = True) -> str:
    """Desktop `formatBytes` (IEC units so LFS progress matches Git)."""
    if byte_count == 0:
        return f"{0:.{decimals}f} B" if fixed else "0 B"
    magnitude = min(int(math.log(abs(byte_count), 1024)), len(_BYTE_UNITS) - 1)
    value = abs(byte_count) / (1024**magnitude)
    sign = "-" if byte_count < 0 else ""
    if fixed:
        rendered = f"{value:.{decimals}f}"
    else:
        rendered = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{sign}{rendered} {_BYTE_UNITS[magnitude]}"


def create_lfs_progress_file() -> str:
    """Desktop `createLFSProgressFile`: empty file whose path is `GIT_LFS_PROGRESS`."""
    directory = tempfile.mkdtemp(prefix="GitHubDesktop-lfs-progress-")
    path = os.path.join(directory, "progress")
    with open(path, "wb"):
        pass
    return path

_PERCENT_RE = re.compile(r"^(\d{1,3})% \((\d+)/(\d+)\)$")
_VALUE_ONLY_RE = re.compile(r"^\d+$")
_LFS_LINE_RE = re.compile(r"^(.+?)\s(\d+)/(\d+)\s(\d+)/(\d+)\s(.+)$")


def parse_git_progress_line(line: str) -> GitProgressInfo | None:
    """Parse one Git progress line, or None if it is not progress output."""
    line = parse_carriage_return(line)
    title_length = line.rfind(": ")
    if title_length <= 0:
        return None
    if title_length - 2 >= len(line):
        return None
    title = line[:title_length]
    progress_text = line[title_length + 2 :].strip()
    if not progress_text:
        return None
    parts = progress_text.split(", ")
    if not parts:
        return None
    if _VALUE_ONLY_RE.match(parts[0]):
        value = int(parts[0])
        percent: int | None = None
        total: int | None = None
    else:
        match = _PERCENT_RE.match(parts[0])
        if not match:
            return None
        percent = int(match.group(1))
        value = int(match.group(2))
        total = int(match.group(3))
    done = any(part == "done." for part in parts[1:])
    return GitProgressInfo(title=title, value=value, text=line, done=done, percent=percent, total=total)


class GitProgressParser:
    """Weighted multi-step parser matching Desktop's `GitProgressParser`."""

    def __init__(self, steps: Sequence[ProgressStep]) -> None:
        if not steps:
            raise ValueError("must specify at least one step")
        total = sum(step.weight for step in steps)
        self.steps = tuple(ProgressStep(step.title, step.weight / total) for step in steps)
        self.step_index = 0
        self.last_percent = 0.0

    def parse(self, line: str) -> GitProgress:
        line = parse_carriage_return(line)
        progress = parse_git_progress_line(line)
        if progress is None:
            return GitProgress(kind="context", percent=self.last_percent, text=line)
        percent = 0.0
        for i, step in enumerate(self.steps):
            if i >= self.step_index and progress.title == step.title:
                if progress.total:
                    percent += step.weight * (progress.value / progress.total)
                self.step_index = i
                self.last_percent = percent
                return GitProgress(kind="progress", percent=percent, text=progress.text, details=progress)
            percent += step.weight
        return GitProgress(kind="context", percent=self.last_percent, text=line)


class GitLFSProgressParser:
    """Parse `GIT_LFS_PROGRESS` lines from git-lfs."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[int, int, bool]] = {}

    def parse(self, line: str) -> GitProgress:
        match = _LFS_LINE_RE.match(line)
        if not match:
            return GitProgress(kind="context", percent=0.0, text=line)
        direction, _cur, estimated, transferred_s, size_s, name = match.groups()
        try:
            estimated_count = int(estimated)
            transferred = int(transferred_s)
            size = int(size_s)
        except ValueError:
            return GitProgress(kind="context", percent=0.0, text=line)
        self.files[name] = (transferred, size, transferred == size)
        total_transferred = sum(item[0] for item in self.files.values())
        total_size = sum(item[1] for item in self.files.values())
        finished = sum(1 for item in self.files.values() if item[2])
        file_count = max(estimated_count, len(self.files))
        verb = {"download": "Downloading", "upload": "Uploading", "checkout": "Checking out"}.get(
            direction, "Downloading"
        )
        transfer = f"{format_bytes(total_transferred, 1)} / {format_bytes(total_size, 1)}"
        text = (
            f"{verb} {name} ({finished} out of an estimated {file_count} completed, {transfer})"
        )
        info = GitProgressInfo(
            title=f'{verb} "{name}"',
            value=total_transferred,
            total=total_size or None,
            percent=None,
            done=False,
            text=text,
        )
        ratio = (total_transferred / total_size) if total_size else 0.0
        return GitProgress(kind="progress", percent=ratio, text=text, details=info)


@dataclass(frozen=True)
class MultiCommitProgress:
    position: int
    total: int
    current_commit_summary: str
    value: float


def format_rebase_value(value: float) -> float:
    clamped = max(0.0, min(1.0, value))
    return round(clamped * 100) / 100


_REBASING_RE = re.compile(r"^Rebasing \((\d+)/(\d+)\)$")
_CHERRY_PICK_RE = re.compile(r"^\[(.*\s.*)\]")


class GitRebaseParser:
    """Parse `Rebasing (n/m)` lines from git rebase stderr."""

    def __init__(self, commits: Sequence[object] = ()) -> None:
        self.commits = list(commits)

    def parse(self, line: str) -> MultiCommitProgress | None:
        match = _REBASING_RE.match(line.strip())
        if match is None:
            return None
        position = int(match.group(1))
        total = int(match.group(2))
        summary = ""
        if 0 < position <= len(self.commits):
            commit = self.commits[position - 1]
            summary = str(getattr(commit, "summary", "") or "")
        value = format_rebase_value(position / total if total else 0)
        return MultiCommitProgress(position, total, summary, value)


class GitCherryPickParser:
    """Parse `[branch sha] summary` lines from git cherry-pick stdout."""

    def __init__(self, commits: Sequence[object] = (), count: int = 0) -> None:
        self.commits = list(commits)
        self.count = count

    def parse(self, line: str) -> MultiCommitProgress | None:
        if _CHERRY_PICK_RE.match(line) is None:
            return None
        self.count += 1
        total = len(self.commits) or self.count
        summary = ""
        if 0 < self.count <= len(self.commits):
            commit = self.commits[self.count - 1]
            summary = str(getattr(commit, "summary", "") or "")
        value = format_rebase_value(self.count / total if total else 0)
        return MultiCommitProgress(self.count, total, summary, value)
