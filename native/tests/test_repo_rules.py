"""Repository ruleset parsing and metadata matchers (Desktop repo-rules helpers)."""

from __future__ import annotations

from github_desktop.github.repo_rules import (
    RepoRulesInfo,
    commit_rule_warnings,
    parse_repo_rules,
    use_repo_rules_logic,
)
from github_desktop.models import Account, GitHubRepository, Repository


def _repo(private: bool = False, owner: str = "octocat") -> Repository:
    gh = GitHubRepository(
        name="hello",
        owner=owner,
        html_url="https://github.com/octocat/hello",
        clone_url="https://github.com/octocat/hello.git",
        private=private,
        endpoint="https://api.github.com",
    )
    return Repository(id=1, path="/tmp/hello", name="hello", github=gh)


def test_use_repo_rules_logic_skips_free_private_owner() -> None:
    account = Account(login="octocat", endpoint="https://api.github.com", token="x", plan="free")
    assert use_repo_rules_logic(account, _repo(private=True)) is False
    assert use_repo_rules_logic(account, _repo(private=False)) is True
    pro = Account(login="octocat", endpoint="https://api.github.com", token="x", plan="pro")
    assert use_repo_rules_logic(pro, _repo(private=True)) is True
    collaborator = Account(login="friend", endpoint="https://api.github.com", token="x", plan="free")
    assert use_repo_rules_logic(collaborator, _repo(private=True)) is True
    assert use_repo_rules_logic(None, _repo()) is False
    ghes = Account(login="octocat", endpoint="https://ghe.io/api/v3", token="x", plan="pro")
    ghes_repo = _repo()
    ghes_repo.github.endpoint = "https://ghe.io/api/v3"
    assert use_repo_rules_logic(ghes, ghes_repo) is False


def test_parse_commit_message_and_branch_patterns() -> None:
    rulesets = {7: {"id": 7, "current_user_can_bypass": "never"}}
    rules = [
        {
            "ruleset_id": 7,
            "type": "commit_message_pattern",
            "parameters": {"negate": False, "operator": "starts_with", "pattern": "feat:"},
        },
        {
            "ruleset_id": 7,
            "type": "branch_name_pattern",
            "parameters": {"negate": True, "operator": "contains", "pattern": "wip"},
        },
        {"ruleset_id": 7, "type": "required_signatures"},
        {"ruleset_id": 7, "type": "pull_request"},
        {"ruleset_id": 7, "type": "update"},
    ]
    info = parse_repo_rules(rules, rulesets, gpg_sign_enabled=False)
    assert info.signed_commits_required is True
    assert info.pull_request_required is True
    assert info.basic_commit_warning is True
    assert info.commit_message_patterns.get_failed_rules("feat: hello").status == "pass"
    assert info.commit_message_patterns.get_failed_rules("fix: hello").status == "fail"
    assert info.branch_name_patterns.get_failed_rules("feature").status == "pass"
    assert info.branch_name_patterns.get_failed_rules("wip-login").status == "fail"
    signed = parse_repo_rules(rules, rulesets, gpg_sign_enabled=True)
    assert signed.signed_commits_required is False


def test_bypassable_rules_and_missing_ruleset() -> None:
    rulesets = {3: {"id": 3, "current_user_can_bypass": "always"}}
    rules = [
        {"ruleset_id": 3, "type": "creation"},
        {"ruleset_id": 99, "type": "update"},
        {
            "ruleset_id": 3,
            "type": "commit_author_email_pattern",
            "parameters": {"negate": False, "operator": "ends_with", "pattern": "@github.com"},
        },
    ]
    info = parse_repo_rules(rules, rulesets)
    assert info.creation_restricted == "bypass"
    assert info.basic_commit_warning is False
    fail = info.commit_author_email_patterns.get_failed_rules("ada@example.com")
    assert fail.status == "bypass"
    ok = info.commit_author_email_patterns.get_failed_rules("ada@github.com")
    assert ok.status == "pass"


def test_regex_and_commit_rule_warnings() -> None:
    rulesets = {1: {"id": 1, "current_user_can_bypass": "never"}}
    rules = [
        {
            "ruleset_id": 1,
            "type": "commit_message_pattern",
            "parameters": {"negate": False, "operator": "regex", "pattern": r"^JIRA-\d+"},
        }
    ]
    info = parse_repo_rules(rules, rulesets)
    warnings, hard = commit_rule_warnings(
        info,
        message="not a ticket",
        author_email="dev@example.com",
        branch="main",
        ahead_behind=None,
        unpublished=False,
    )
    assert hard is True
    assert any("regular expression" in line for line in warnings)
    ok, ok_hard = commit_rule_warnings(
        info,
        message="JIRA-12 ship it",
        author_email="dev@example.com",
        branch="main",
        ahead_behind=None,
        unpublished=False,
    )
    assert ok_hard is False
    assert ok == []
    empty = RepoRulesInfo()
    none, none_hard = commit_rule_warnings(
        empty, message="x", author_email=None, branch=None, ahead_behind=None, unpublished=False
    )
    assert none == []
    assert none_hard is False


def test_commit_message_dialog_hides_message_failures_inline() -> None:
    from github_desktop.github.repo_rules import (
        RepoRulesMetadataFailure,
        RepoRulesMetadataFailures,
        inline_commit_rule_warning_lines,
        show_commit_message_rule_failure_hint,
    )

    lines = [
        "The commit message must start with feat.",
        "The commit author email must end with @github.com.",
        "This branch requires signed commits. Configure commit.gpgsign to push.",
    ]
    assert inline_commit_rule_warning_lines(lines) == lines[1:]
    fail = RepoRulesMetadataFailures(failed=[RepoRulesMetadataFailure("must start with feat", 1)])
    assert (
        show_commit_message_rule_failure_hint(
            repo_rules_enabled=True, branch="main", github=True, failures=fail
        )
        is True
    )
    assert (
        show_commit_message_rule_failure_hint(
            repo_rules_enabled=True,
            branch="main",
            github=True,
            failures=RepoRulesMetadataFailures(),
        )
        is False
    )


def test_rulesets_url_for_branch() -> None:
    from github_desktop.github.repo_rules import rulesets_url_for_branch

    repo = _repo()
    url = rulesets_url_for_branch(repo.github, "main")
    assert url == "https://github.com/octocat/hello/rules/?ref=refs%2Fheads%2Fmain"
    assert rulesets_url_for_branch(None, "main") is None
    assert rulesets_url_for_branch(repo.github, None) is None
