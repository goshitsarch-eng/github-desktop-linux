"""GHES / ghe.com / github.com feature gates (Desktop `endpoint-capabilities`)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version

from .models import is_dotcom_endpoint, is_ghe_endpoint, is_ghes_endpoint
from .remote_parsing import get_endpoint_version

# Oldest still-supported GHES series when the version header is missing.
assumedGHESVersion = Version("3.1.0")

VersionConstraint = TypedDict(
    "VersionConstraint",
    {"dotcom": bool, "ghe": bool | None, "es": bool | str | None},
    total=False,
)

GetVersion = Callable[[str], Version | str | None]


def _as_version(value: Version | str | None) -> Version | None:
    if value is None:
        return None
    if isinstance(value, Version):
        return value
    try:
        return Version(str(value).lstrip("vV"))
    except InvalidVersion:
        return None


def check_constraint(
    ep_constraint: bool | str | None,
    ep_matches_type: bool,
    ep_version: Version | None = None,
) -> bool:
    """Desktop `checkConstraint`."""
    if ep_constraint is None or ep_constraint is False:
        return False
    if ep_constraint is True:
        return ep_matches_type
    if not ep_matches_type:
        return False
    if ep_version is None:
        raise AssertionError("Need to provide a version to compare against")
    spec = str(ep_constraint).strip()
    if not spec:
        return False
    try:
        return ep_version in SpecifierSet(spec, prereleases=True)
    except Exception:
        return False


def endpoint_satisfies(
    constraint: VersionConstraint,
    get_version: GetVersion | None = None,
) -> Callable[[str], bool]:
    """Desktop `endpointSatisfies`."""
    lookup = get_version or (lambda ep: get_endpoint_version(ep))
    dotcom = constraint.get("dotcom")
    ghe = constraint.get("ghe", None)
    if "ghe" not in constraint:
        ghe = dotcom
    es = constraint.get("es")

    def predicate(endpoint: str) -> bool:
        version = _as_version(lookup(endpoint)) or assumedGHESVersion
        return (
            check_constraint(dotcom, is_dotcom_endpoint(endpoint))
            or check_constraint(ghe, is_ghe_endpoint(endpoint))
            or check_constraint(es, is_ghes_endpoint(endpoint), version)
        )

    return predicate


def supports_avatars_api(endpoint: str) -> bool:
    """Desktop `supportsAvatarsAPI`: GHES `>= 3.0.0`."""
    return endpoint_satisfies({"es": ">= 3.0.0"})(endpoint)


def supports_rerunning_checks(endpoint: str) -> bool:
    """Desktop `supportsRerunningChecks`."""
    return endpoint_satisfies({"dotcom": True, "es": ">= 3.4.0"})(endpoint)


def supports_rerunning_individual_or_failed_checks(endpoint: str) -> bool:
    """Desktop `supportsRerunningIndividualOrFailedChecks`."""
    return endpoint_satisfies({"dotcom": True})(endpoint)


def supports_retrieve_action_workflow_by_check_suite_id(endpoint: str) -> bool:
    """Desktop `supportsRetrieveActionWorkflowByCheckSuiteId`."""
    return endpoint_satisfies({"dotcom": True})(endpoint)


def supports_alive_sessions(endpoint: str) -> bool:
    """Desktop `supportsAliveSessions` (REST notifications still used on Linux)."""
    return endpoint_satisfies({"dotcom": True})(endpoint)


def supports_repo_rules(endpoint: str) -> bool:
    """Desktop `supportsRepoRules`."""
    return endpoint_satisfies({"dotcom": True})(endpoint)
