"""Desktop `ApiRepositoriesStore` cache, skip-in-flight, and prune-on-refresh."""

from __future__ import annotations

from github_desktop.api_repositories import ApiRepositoriesStore
from github_desktop.github.api import GitHubAPI
from github_desktop.models import Account, GitHubRepository, account_equals


def _account(login: str = "octocat", account_id: int = 7, token: str = "tok") -> Account:
    return Account(
        login=login,
        endpoint="https://api.github.com",
        token=token,
        id=account_id,
        name="Octo",
        plan="free",
    )


def _repo(name: str, owner: str = "octocat") -> GitHubRepository:
    return GitHubRepository(
        name=name,
        owner=owner,
        html_url=f"https://github.com/{owner}/{name}",
        clone_url=f"https://github.com/{owner}/{name}.git",
    )


def _sync_run(work, done) -> None:
    err = None
    result = None
    try:
        result = work()
    except BaseException as exc:
        err = exc
    try:
        done(err, result)
    except TypeError:
        done(err)


def test_account_equals_uses_endpoint_and_id() -> None:
    left = _account(token="old")
    right = _account(token="new")
    assert account_equals(left, right)
    assert not account_equals(left, _account(account_id=8))
    assert not account_equals(left, Account(login="octocat", endpoint="https://ghe.example/api/v3", token="tok", id=7))


def test_load_repositories_caches_pages_and_resolves_updated_account(monkeypatch) -> None:
    store = ApiRepositoriesStore()
    account = _account()
    pages = [[_repo("alpha"), _repo("beta")]]

    def fake_load(self, callback) -> None:
        for page in pages:
            callback(page)

    monkeypatch.setattr(GitHubAPI, "load_cloneable_repositories", fake_load)
    store.load_repositories(account, _sync_run)
    state = store.get_account_state(account)
    assert state is not None
    assert not state.loading
    assert {item.name for item in state.repositories} == {"alpha", "beta"}

    refreshed = _account(token="rotated")
    assert store.get_account_state(refreshed) is state
    store.on_accounts_changed([refreshed])
    remapped = store.get_account_state(refreshed)
    assert remapped is not None
    assert {item.name for item in remapped.repositories} == {"alpha", "beta"}
    assert store.get_account_state(_account(account_id=99)) is None


def test_load_repositories_skips_when_already_loading(monkeypatch) -> None:
    store = ApiRepositoriesStore()
    account = _account()
    calls: list[int] = []

    def fake_load(self, callback) -> None:
        calls.append(1)
        callback([_repo("one")])

    monkeypatch.setattr(GitHubAPI, "load_cloneable_repositories", fake_load)
    store._update_account(account, loading=True)
    store.load_repositories(account, _sync_run)
    assert calls == []


def test_load_repositories_prunes_clone_urls_removed_on_host(monkeypatch) -> None:
    store = ApiRepositoriesStore()
    account = _account()
    first = [_repo("keep"), _repo("gone")]
    second = [_repo("keep"), _repo("new")]
    payloads = [first, second]

    def fake_load(self, callback) -> None:
        callback(payloads.pop(0))

    monkeypatch.setattr(GitHubAPI, "load_cloneable_repositories", fake_load)
    store.load_repositories(account, _sync_run)
    store.load_repositories(account, _sync_run)
    names = {item.name for item in store.get_account_state(account).repositories}
    assert names == {"keep", "new"}
