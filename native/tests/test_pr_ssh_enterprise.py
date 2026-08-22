"""Desktop findAssociatedPullRequest, getFileHash / SSH stores, validateURL."""

from __future__ import annotations

import hashlib

import pytest

from github_desktop.enterprise import (
    INVALID_PROTOCOL_ERROR_NAME,
    INVALID_URL_ERROR_NAME,
    EnterpriseURLError,
    is_github_dotcom_address,
    validate_url,
)
from github_desktop.get_file_hash import get_file_hash
from github_desktop.models import Branch, BranchType, PullRequest, Remote, SignInStep
from github_desktop.pull_request_matching import (
    find_associated_pull_request,
    is_pull_request_associated_with_branch,
)
from github_desktop.ssh_credentials import (
    SSH_KEY_PASSPHRASE_STORE,
    SSH_USER_PASSWORD_STORE,
    get_ssh_credential_store_key,
    get_ssh_key_passphrase,
    get_ssh_user_password,
    set_ssh_key_passphrase,
    set_ssh_user_password,
)
from github_desktop.store import AppStore


def _pr(*, head_ref: str, clone_url: str, number: int = 1) -> PullRequest:
    return PullRequest(
        number=number,
        title="Fix",
        body="",
        created_at="",
        author="me",
        draft=False,
        head_ref=head_ref,
        head_sha="abc",
        base_ref="main",
        html_url="https://github.com/o/r/pull/1",
        head_clone_url=clone_url,
    )


def test_find_associated_pull_request_matches_upstream_and_remote() -> None:
    branch = Branch(
        name="my-feature",
        upstream="origin/feature",
        tip_sha="abc",
        type=BranchType.LOCAL,
        remote="origin",
        upstream_without_remote="feature",
    )
    remote = Remote("origin", "https://github.com/o/r.git")
    fork = _pr(head_ref="feature", clone_url="https://github.com/fork/r.git", number=2)
    own = _pr(head_ref="feature", clone_url="https://github.com/o/r.git", number=1)
    assert find_associated_pull_request(branch, [fork, own], remote) is own
    assert is_pull_request_associated_with_branch(branch, own, remote)
    assert not is_pull_request_associated_with_branch(branch, fork, remote)
    untracked = Branch(name="feature", upstream=None, tip_sha="abc", type=BranchType.LOCAL)
    assert find_associated_pull_request(untracked, [own], remote) is None


def test_get_file_hash_and_ssh_key_passphrase(isolated_config, tmp_path) -> None:
    key = tmp_path / "id_ed25519"
    key.write_bytes(b"ssh-key-bytes")
    digest = hashlib.sha256(b"ssh-key-bytes").hexdigest()
    assert get_file_hash(str(key), "sha256") == digest
    assert get_ssh_credential_store_key("SSH key passphrases") == "GitHub Desktop - SSH key passphrases"
    assert get_ssh_credential_store_key("SSH user password") == "GitHub Desktop - SSH user password"
    store, account = set_ssh_key_passphrase(str(key), "hunter2")
    assert store == SSH_KEY_PASSPHRASE_STORE
    assert account == digest
    assert get_ssh_key_passphrase(str(key)) == "hunter2"
    user_store, user_key = set_ssh_user_password("git@github.com", "pw")
    assert user_store == SSH_USER_PASSWORD_STORE
    assert user_key == "git@github.com"
    assert get_ssh_user_password("git@github.com") == "pw"


def test_validate_url_matches_desktop() -> None:
    assert validate_url("ghe.io") == "https://ghe.io"
    assert validate_url("https://github.example.com") == "https://github.example.com"
    with pytest.raises(EnterpriseURLError) as empty:
        validate_url("   ")
    assert empty.value.name == INVALID_URL_ERROR_NAME
    with pytest.raises(EnterpriseURLError) as proto:
        validate_url("http://github.example.com")
    assert proto.value.name == INVALID_PROTOCOL_ERROR_NAME
    assert is_github_dotcom_address("github.com")
    assert is_github_dotcom_address("https://api.github.com")
    assert not is_github_dotcom_address("github.example.com")


def test_set_sign_in_endpoint_validates_and_redirects_dotcom(isolated_config) -> None:
    store = AppStore()
    store.begin_sign_in(enterprise=True)
    store.set_sign_in_endpoint("http://github.example.com")
    assert store.sign_in_error and "Only https is supported" in store.sign_in_error
    assert store.sign_in_step == SignInStep.ENDPOINT_ENTRY
    store.set_sign_in_endpoint("")
    assert store.sign_in_error and "valid URL" in store.sign_in_error
    store.set_sign_in_endpoint("github.example.com")
    assert store.sign_in_error is None
    assert store.sign_in_endpoint == "https://github.example.com/api/v3"
    assert store.sign_in_step == SignInStep.AUTHENTICATION
    store.set_sign_in_endpoint("https://github.com")
    assert store.sign_in_endpoint == "https://api.github.com"
    assert store.sign_in_step == SignInStep.AUTHENTICATION
