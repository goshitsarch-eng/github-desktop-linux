"""Desktop `lib/format-commit-message.ts`."""

from __future__ import annotations

import re
from typing import Sequence

from .errors import GitError


def format_commit_message(
    summary: str,
    description: str | None = "",
    trailers: Sequence[tuple[str, str]] = (),
    *,
    repo: str | None = None,
) -> str:
    """Desktop `formatCommitMessage`.

    Git always trim whitespace at the end of commit messages so we concatenate
    the summary with the description, ensuring that they're separated by two
    newlines. If we don't have a description or if it consists solely of
    whitespace that'll all get trimmed away and replaced with a single newline
    (since all commit messages needs to end with a newline for git
    interpret-trailers to work).

    Always returns a commit message with a trailing newline.
    """
    message = f"{summary}\n\n{description or ''}\n"
    message = re.sub(r"\s+$", "\n", message)
    if trailers:
        if repo:
            from .git.ops import merge_trailers

            try:
                return merge_trailers(repo, message, trailers)
            except GitError:
                pass
        extra = "\n".join(f"{token}: {value}" for token, value in trailers)
        return f"{message}\n{extra}\n"
    return message
