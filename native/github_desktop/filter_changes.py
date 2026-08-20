"""Desktop `filter-changes-logic`: AND filters, hidden-commit warning, no-results copy."""

from __future__ import annotations

from dataclasses import dataclass

from .models import (
    AppFileStatusKind,
    ChangesListFilter,
    DiffSelectionType,
    WorkingDirectoryFileChange,
)


@dataclass(frozen=True)
class FileListFilterState:
    """Desktop `IFileListFilterState`."""

    filter_text: str = ""
    is_included_in_commit: bool = False
    is_excluded_from_commit: bool = False
    is_new_file: bool = False
    is_modified_file: bool = False
    is_deleted_file: bool = False


def file_list_filter_state_from_view(state) -> FileListFilterState:
    """Build filter options from a repository view state."""
    mode = getattr(state, "file_filter", ChangesListFilter.ALL.value)
    return FileListFilterState(
        filter_text=str(getattr(state, "filter_text", "") or ""),
        is_included_in_commit=mode == ChangesListFilter.INCLUDED.value,
        is_excluded_from_commit=mode == ChangesListFilter.EXCLUDED.value,
        is_new_file=bool(getattr(state, "filter_new", False)),
        is_modified_file=bool(getattr(state, "filter_modified", False)),
        is_deleted_file=bool(getattr(state, "filter_deleted", False)),
    )


def count_active_filter_options(filters: FileListFilterState) -> int:
    """Desktop `countActiveFilterOptions` (does not include filter text)."""
    return sum(
        [
            filters.is_included_in_commit,
            filters.is_new_file,
            filters.is_modified_file,
            filters.is_deleted_file,
            filters.is_excluded_from_commit,
        ]
    )


def has_active_filters(filters: FileListFilterState) -> bool:
    """Desktop `hasActiveFilters`."""
    return bool(filters.filter_text) or count_active_filter_options(filters) > 0


def apply_filter_options(file: WorkingDirectoryFileChange, filters: FileListFilterState) -> bool:
    """Desktop `applyFilterOptions`: file must satisfy every active option."""
    if count_active_filter_options(filters) == 0:
        return True
    if filters.is_included_in_commit and not file.is_included_in_commit():
        return False
    if filters.is_excluded_from_commit and not file.is_excluded_from_commit():
        return False
    if filters.is_new_file and not file.is_new() and not file.is_untracked():
        return False
    if filters.is_modified_file and not file.is_modified():
        return False
    if filters.is_deleted_file and not file.is_deleted():
        return False
    return True


def apply_filters(file: WorkingDirectoryFileChange, filters: FileListFilterState) -> bool:
    """Apply text plus option filters (Desktop `applyFilters` + filterText)."""
    needle = filters.filter_text.strip().lower()
    if needle and needle not in file.path.lower():
        return False
    return apply_filter_options(file, filters)


def filter_changed_files(
    files: list[WorkingDirectoryFileChange], filters: FileListFilterState
) -> list[WorkingDirectoryFileChange]:
    return [file for file in files if apply_filters(file, filters)]


def is_committing_file_hidden_by_filter(
    included_paths: list[str],
    visible_paths: list[str],
    file_count: int,
    filters: FileListFilterState,
) -> bool:
    """Desktop `isCommittingFileHiddenByFilter`."""
    if not has_active_filters(filters) or len(visible_paths) == file_count:
        return False
    if len(included_paths) > len(visible_paths):
        return True
    visible = set(visible_paths)
    return any(path not in visible for path in included_paths)


def get_no_results_message(filters: FileListFilterState) -> str | None:
    """Desktop `getNoResultsMessage`."""
    if not has_active_filters(filters):
        return None
    active: list[str] = []
    text = filters.filter_text.strip()
    if text:
        active.append(f'"{text}"')
    if filters.is_included_in_commit:
        active.append("Included in commit")
    if filters.is_excluded_from_commit:
        active.append("Excluded from commit")
    if filters.is_new_file:
        active.append("New files")
    if filters.is_modified_file:
        active.append("Modified files")
    if filters.is_deleted_file:
        active.append("Deleted files")
    if not active:
        return None
    if len(active) == 1:
        filter_list = active[0]
    elif len(active) == 2:
        filter_list = f"{active[0]} and {active[1]}"
    else:
        filter_list = f"{', '.join(active[:-1])}, and {active[-1]}"
    return f"Sorry, I can't find any changed files matching the following filters: {filter_list}"
