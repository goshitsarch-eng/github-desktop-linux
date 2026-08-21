"""Desktop `lib/helpers/regex.ts` parsers for git error output."""

from __future__ import annotations

import re

# Desktop `getFileFromExceedsError`: keep the unescaped `.` in `100.00` so the
# JavaScript regex and this port match the same stderr snippets.
_END_REGEX = re.compile(
    r"(;\sthis\sexceeds\sGitHub's\sfile\ssize\slimit\sof\s100.00\sMB)",
    re.M,
)
_BEGIN_REGEX = re.compile(r"(^remote:\serror:\sFile\s)", re.M)


def get_file_from_exceeds_error(error: str) -> list[str]:
    """Desktop `getFileFromExceedsError`.

    Looks for ``remote: error: File `` and
    ``; this exceeds GitHub's file size limit of 100.00 MB`` and returns
    ``["name (size)", ...]`` slices from between those markers.

    Example: ``["LargeFile.exe (150.00 MB)", "AlsoTooLargeOfAFile.txt (1.00 GB)"]``.
    """
    begin_matches = list(_BEGIN_REGEX.finditer(error))
    end_matches = list(_END_REGEX.finditer(error))
    # Something went wrong and we didn't find the same amount of endings as we
    # did beginnings. Return an empty array as the output would look weird.
    if len(begin_matches) != len(end_matches):
        return []

    files: list[str] = []
    for begin_match, end_match in zip(begin_matches, end_matches):
        from_ = begin_match.start() + len(begin_match.group(0))
        to = end_match.start()
        file = error[from_:to]
        # JS String.replace without /g replaces only the first occurrence.
        file = file.replace("is ", "(", 1)
        file += ")"
        files.append(file)
    return files
