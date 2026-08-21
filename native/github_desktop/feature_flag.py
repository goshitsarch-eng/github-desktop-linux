"""Desktop `lib/feature-flag.ts` production flags that are always on for Linux."""

from __future__ import annotations


def enable_recurse_submodules_flag() -> bool:
    """Desktop `enableRecurseSubmodulesFlag`."""
    return True


def enable_reset_to_commit() -> bool:
    """Desktop `enableResetToCommit`."""
    return True


def enable_checkout_commit() -> bool:
    """Desktop `enableCheckoutCommit`."""
    return True


def enable_custom_integration() -> bool:
    """Desktop `enableCustomIntegration`."""
    return True


def enable_resizing_toolbar_buttons() -> bool:
    """Desktop `enableResizingToolbarButtons`."""
    return True


def enable_filtered_changes_list() -> bool:
    """Desktop `enableFilteredChangesList`."""
    return True


def enable_multiple_enterprise_accounts() -> bool:
    """Desktop `enableMultipleEnterpriseAccounts`."""
    return True
