"""NUL-delimited git `--format` parsers (Desktop `git-delimiter-parser` / `splitBuffer`)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


def split_buffer(buffer: bytes, delimiter: str | bytes) -> list[bytes]:
    """Desktop `splitBuffer`: keep empty trailing segments."""
    needle = delimiter.encode("utf-8") if isinstance(delimiter, str) else delimiter
    result: list[bytes] = []
    start = 0
    index = buffer.find(needle, start)
    while index != -1:
        result.append(buffer[start:index])
        start = index + len(needle)
        index = buffer.find(needle, start)
    if start <= len(buffer):
        result.append(buffer[start:])
    return result


@dataclass(frozen=True)
class GitFormatParser:
    """`format_args` to append to git, plus `parse` for stdout."""

    format_args: tuple[str, ...]
    keys: tuple[str, ...]
    kind: str

    def parse(self, value: str | bytes) -> list[dict[str, str]]:
        if isinstance(value, bytes):
            records = [chunk.decode("utf-8", errors="replace") for chunk in split_buffer(value, "\0")]
        else:
            records = value.split("\0")
        if self.kind == "log":
            return self._parse_log(records)
        return self._parse_ref(records)

    def _parse_log(self, records: Sequence[str]) -> list[dict[str, str]]:
        keys = self.keys
        entries: list[dict[str, str]] = []
        limit = len(records) - len(keys)
        for index in range(0, max(limit, 0), len(keys)):
            entry = {key: records[index + offset] for offset, key in enumerate(keys)}
            entries.append(entry)
        return entries

    def _parse_ref(self, records: Sequence[str]) -> list[dict[str, str]]:
        keys = self.keys
        entries: list[dict[str, str]] = []
        entry: dict[str, str] | None = None
        consumed = 0
        # Start at 1: first record is empty because `--format` begins with `%00`.
        for index in range(1, max(len(records) - 1, 1)):
            if index % (len(keys) + 1) == 0:
                if records[index] not in {"\n", ""}:
                    raise ValueError("Expected newline")
                continue
            entry = entry if entry is not None else {}
            key = keys[consumed % len(keys)]
            entry[key] = records[index]
            consumed += 1
            if consumed % len(keys) == 0:
                entries.append(entry)
                entry = None
        return entries


def create_log_parser(fields: Mapping[str, str]) -> GitFormatParser:
    """Desktop `createLogParser`: `git log -z --format=a%x00b`."""
    keys = tuple(fields.keys())
    fmt = "%x00".join(fields.values())
    return GitFormatParser(format_args=("-z", f"--format={fmt}"), keys=keys, kind="log")


def create_for_each_ref_parser(fields: Mapping[str, str]) -> GitFormatParser:
    """Desktop `createForEachRefParser`: `--format=%00a%00b%00`."""
    keys = tuple(fields.keys())
    fmt = "%00".join(fields.values())
    return GitFormatParser(format_args=(f"--format=%00{fmt}%00",), keys=keys, kind="ref")
