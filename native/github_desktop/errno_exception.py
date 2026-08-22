"""Desktop `lib/errno-exception.ts` plus a Python OSError equivalent."""

from __future__ import annotations

import errno


def is_errno_exception(err: object) -> bool:
    """Desktop `isErrnoException`.

    Node.js low-level errors expose string ``code`` and ``syscall`` fields.
    Python ``OSError`` (and subclasses) expose integer ``errno`` instead.
    """
    if isinstance(err, OSError) and err.errno is not None:
        return True
    if isinstance(err, Exception):
        code = getattr(err, "code", None)
        syscall = getattr(err, "syscall", None)
        return isinstance(code, str) and isinstance(syscall, str)
    return False


def errno_code(err: BaseException) -> str:
    """Node ``err.code`` (``ENOENT``) or Python ``errno.errorcode``."""
    code = getattr(err, "code", None)
    if isinstance(code, str):
        return code
    if isinstance(err, OSError) and err.errno is not None:
        return errno.errorcode.get(err.errno, str(err.errno))
    return "Error"
