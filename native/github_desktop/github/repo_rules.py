"""Repository rulesets: parse GitHub API rules and match commit/branch metadata.

Port of Desktop `app/src/models/repo-rules.ts` and `app/src/lib/helpers/repo-rules.ts`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Literal
from urllib.parse import quote

from ..endpoint_capabilities import supports_repo_rules
from ..models import Account, AheadBehind, GitHubRepository, Repository


RepoRulesMetadataStatus = Literal["pass", "fail", "bypass"]
RepoRuleEnforced = bool | Literal["bypass"]
RepoRulesMetadataMatcher = Callable[[str], bool]


@dataclass
class RepoRulesMetadataFailure:
    description: str
    ruleset_id: int


@dataclass
class RepoRulesMetadataFailures:
    failed: list[RepoRulesMetadataFailure] = field(default_factory=list)
    bypassed: list[RepoRulesMetadataFailure] = field(default_factory=list)

    @property
    def status(self) -> RepoRulesMetadataStatus:
        if not self.failed:
            return "bypass" if self.bypassed else "pass"
        return "fail"


@dataclass
class RepoRulesMetadataRule:
    enforced: RepoRuleEnforced
    matcher: RepoRulesMetadataMatcher
    human_description: str
    ruleset_id: int


class RepoRulesMetadataRules:
    def __init__(self) -> None:
        self.rules: list[RepoRulesMetadataRule] = []

    def push(self, rule: RepoRulesMetadataRule | None) -> None:
        if rule is not None:
            self.rules.append(rule)

    @property
    def has_rules(self) -> bool:
        return bool(self.rules)

    def get_failed_rules(self, to_match: str) -> RepoRulesMetadataFailures:
        failures = RepoRulesMetadataFailures()
        for rule in self.rules:
            if rule.matcher(to_match):
                continue
            item = RepoRulesMetadataFailure(rule.human_description, rule.ruleset_id)
            if rule.enforced == "bypass":
                failures.bypassed.append(item)
            else:
                failures.failed.append(item)
        return failures


@dataclass
class RepoRulesInfo:
    basic_commit_warning: RepoRuleEnforced = False
    creation_restricted: RepoRuleEnforced = False
    signed_commits_required: RepoRuleEnforced = False
    pull_request_required: RepoRuleEnforced = False
    commit_message_patterns: RepoRulesMetadataRules = field(default_factory=RepoRulesMetadataRules)
    commit_author_email_patterns: RepoRulesMetadataRules = field(default_factory=RepoRulesMetadataRules)
    committer_email_patterns: RepoRulesMetadataRules = field(default_factory=RepoRulesMetadataRules)
    branch_name_patterns: RepoRulesMetadataRules = field(default_factory=RepoRulesMetadataRules)


API_CREATION = "creation"
API_UPDATE = "update"
API_REQUIRED_DEPLOYMENTS = "required_deployments"
API_REQUIRED_SIGNATURES = "required_signatures"
API_REQUIRED_STATUS_CHECKS = "required_status_checks"
API_PULL_REQUEST = "pull_request"
API_COMMIT_MESSAGE_PATTERN = "commit_message_pattern"
API_COMMIT_AUTHOR_EMAIL_PATTERN = "commit_author_email_pattern"
API_COMMITTER_EMAIL_PATTERN = "committer_email_pattern"
API_BRANCH_NAME_PATTERN = "branch_name_pattern"

OP_STARTS_WITH = "starts_with"
OP_ENDS_WITH = "ends_with"
OP_CONTAINS = "contains"
OP_REGEX = "regex"


def rulesets_url_for_branch(repository: GitHubRepository | None, branch: str | None) -> str | None:
    """Desktop `RepoRulesetsForBranchLink`: ``{htmlURL}/rules/?ref=refs/heads/{branch}``."""
    if repository is None or not branch:
        return None
    html_url = (repository.html_url or "").rstrip("/")
    if not html_url:
        return None
    ref = quote(f"refs/heads/{branch}", safe="")
    return f"{html_url}/rules/?ref={ref}"


def ruleset_url(repository: GitHubRepository | None, ruleset_id: int) -> str | None:
    """Desktop `RepoRulesetLink`: ``{htmlURL}/rules/{rulesetId}``."""
    if repository is None or not ruleset_id:
        return None
    html_url = (repository.html_url or "").rstrip("/")
    if not html_url:
        return None
    return f"{html_url}/rules/{int(ruleset_id)}"


def repo_rules_failure_heading(leading_text: str, failures: RepoRulesMetadataFailures) -> str:
    """Desktop `RepoRulesMetadataFailureList` lead-in copy."""
    total = len(failures.failed) + len(failures.bypassed)
    if total == 0:
        return ""
    noun = "rule" if total == 1 else "rules"
    if failures.status == "bypass":
        pronoun = "it" if total == 1 else "them"
        return (
            f"{leading_text} fails {total} {noun}, but you can bypass {pronoun}. "
            "Proceed with caution!"
        )
    return f"{leading_text} fails {total} {noun}."


def use_repo_rules_logic(account: Account | None, repository: Repository) -> bool:
    """Client-side gate matching Desktop `useRepoRulesLogic`."""
    if account is None or repository is None or repository.github is None:
        return False
    gh = repository.github
    if not supports_repo_rules(gh.endpoint or account.endpoint):
        return False
    if account.login == gh.owner and (not account.plan or account.plan == "free") and gh.private:
        return False
    return True


def parse_repo_rules(
    rules: Iterable[dict],
    rulesets: dict[int, dict],
    *,
    gpg_sign_enabled: bool = False,
) -> RepoRulesInfo:
    info = RepoRulesInfo()
    for rule in rules:
        ruleset_id = int(rule.get("ruleset_id") or 0)
        ruleset = rulesets.get(ruleset_id)
        if ruleset is None:
            continue
        enforced: RepoRuleEnforced = "bypass" if ruleset.get("current_user_can_bypass") == "always" else True
        kind = rule.get("type")
        if kind in {API_UPDATE, API_REQUIRED_DEPLOYMENTS, API_REQUIRED_STATUS_CHECKS}:
            info.basic_commit_warning = True if info.basic_commit_warning is True else enforced
        elif kind == API_CREATION:
            info.creation_restricted = True if info.creation_restricted is True else enforced
        elif kind == API_REQUIRED_SIGNATURES:
            if not gpg_sign_enabled:
                info.signed_commits_required = True if info.signed_commits_required is True else enforced
        elif kind == API_PULL_REQUEST:
            info.pull_request_required = True if info.pull_request_required is True else enforced
        elif kind == API_COMMIT_MESSAGE_PATTERN:
            info.commit_message_patterns.push(_to_metadata_rule(rule, enforced))
        elif kind == API_COMMIT_AUTHOR_EMAIL_PATTERN:
            info.commit_author_email_patterns.push(_to_metadata_rule(rule, enforced))
        elif kind == API_COMMITTER_EMAIL_PATTERN:
            info.committer_email_patterns.push(_to_metadata_rule(rule, enforced))
        elif kind == API_BRANCH_NAME_PATTERN:
            info.branch_name_patterns.push(_to_metadata_rule(rule, enforced))
    return info


def _to_metadata_rule(rule: dict, enforced: RepoRuleEnforced) -> RepoRulesMetadataRule | None:
    params = rule.get("parameters")
    if not isinstance(params, dict):
        return None
    return RepoRulesMetadataRule(
        enforced=enforced,
        matcher=_to_matcher(params),
        human_description=_to_human_description(params),
        ruleset_id=int(rule.get("ruleset_id") or 0),
    )


def _to_human_description(params: dict) -> str:
    negate = bool(params.get("negate"))
    operator = params.get("operator")
    pattern = str(params.get("pattern") or "")
    description = "must not " if negate else "must "
    if operator == OP_REGEX:
        return f'{description}match the regular expression "{pattern}"'
    if operator == OP_STARTS_WITH:
        description += "start with "
    elif operator == OP_ENDS_WITH:
        description += "end with "
    elif operator == OP_CONTAINS:
        description += "contain "
    return f'{description}"{pattern}"'


def _to_matcher(params: dict) -> RepoRulesMetadataMatcher:
    operator = params.get("operator")
    pattern = str(params.get("pattern") or "")
    negate = bool(params.get("negate"))
    try:
        if operator == OP_STARTS_WITH:
            regex = re.compile("^" + re.escape(pattern))
        elif operator == OP_ENDS_WITH:
            regex = re.compile(re.escape(pattern) + "$")
        elif operator == OP_CONTAINS:
            regex = re.compile(".*" + re.escape(pattern) + ".*")
        elif operator == OP_REGEX:
            regex = re.compile(pattern)
        else:
            return lambda _value: False
    except re.error:
        return lambda _value: False

    def match(to_match: str) -> bool:
        found = regex.search(to_match) is not None
        return (not found) if negate else found

    return match


def commit_rule_warnings(
    info: RepoRulesInfo,
    *,
    message: str,
    author_email: str | None,
    branch: str | None,
    ahead_behind: AheadBehind | None,
    unpublished: bool,
) -> tuple[list[str], bool]:
    """Return (warning lines, hard_failure) matching Desktop commit-message rules UI."""
    warnings: list[str] = []
    hard = False
    msg_fail = info.commit_message_patterns.get_failed_rules(message)
    if msg_fail.status == "fail":
        descriptions = ", ".join(f.description for f in msg_fail.failed)
        warnings.append(f"The commit message {descriptions}.")
        hard = True
    elif msg_fail.status == "bypass":
        descriptions = ", ".join(f.description for f in msg_fail.bypassed)
        warnings.append(f"The commit message {descriptions}. You can bypass this rule.")

    if author_email:
        email_fail = info.commit_author_email_patterns.get_failed_rules(author_email)
        if email_fail.status == "fail":
            descriptions = ", ".join(f.description for f in email_fail.failed)
            warnings.append(f"The commit author email {descriptions}.")
            hard = True
        elif email_fail.status == "bypass":
            descriptions = ", ".join(f.description for f in email_fail.bypassed)
            warnings.append(f"The commit author email {descriptions}. You can bypass this rule.")

    if unpublished and branch:
        name_fail = info.branch_name_patterns.get_failed_rules(branch)
        if info.creation_restricted is True or name_fail.status == "fail":
            warnings.append(
                f"The branch '{branch}' cannot be published because repository rules restrict branch creation."
            )
            hard = True
        elif info.creation_restricted == "bypass" or name_fail.status == "bypass":
            warnings.append(
                f"The branch '{branch}' is restricted by repository rules. You can bypass this rule."
            )

    if info.signed_commits_required is True:
        warnings.append("This branch requires signed commits. Configure commit.gpgsign to push.")
        hard = True
    elif info.signed_commits_required == "bypass":
        warnings.append("This branch requires signed commits. You can bypass this rule.")

    if info.pull_request_required is True:
        warnings.append("This branch requires a pull request before changes can be merged.")
        hard = True
    elif info.pull_request_required == "bypass":
        warnings.append("This branch requires a pull request. You can bypass this rule.")

    if info.basic_commit_warning is True:
        warnings.append("The current branch has repository rules that may prevent pushing.")
        hard = True
    elif info.basic_commit_warning == "bypass":
        warnings.append("The current branch has repository rules. You can bypass this rule.")

    _ = ahead_behind
    return warnings, hard
