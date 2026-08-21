"""In-memory cloneable repository lists matching Desktop `ApiRepositoriesStore`."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Iterator

from .github.api import GitHubAPI
from .logging import get_logger
from .models import Account, GitHubRepository, account_equals

log = get_logger()

Listener = Callable[[], None]


@dataclass(frozen=True)
class AccountRepositories:
    """Desktop `IAccountRepositories`: cloneable repos plus loading flag."""

    repositories: list[GitHubRepository]
    loading: bool = False


def _marshal(fn: Callable[[], bool | None]) -> None:
    """Run ``fn`` on the GTK thread when a Gio.Application exists."""

    def tick() -> bool:
        fn()
        return False

    invoked = False
    try:
        from gi.repository import Gio, GLib

        if Gio.Application.get_default() is not None:
            GLib.idle_add(tick)
            invoked = True
    except Exception:
        invoked = False
    if not invoked:
        tick()


def _index_of(account: Account, items: list[tuple[Account, AccountRepositories]]) -> int:
    """Desktop `resolveAccount`: identity first, then endpoint + user id."""
    for index, (existing, _) in enumerate(items):
        if existing is account:
            return index
    for index, (existing, _) in enumerate(items):
        if account_equals(existing, account):
            return index
    return -1


class ApiRepositoriesStore:
    """Desktop `ApiRepositoriesStore`.

    Holds per-account cloneable repository lists so Clone and the empty-state
    view can show cached pages immediately and stream the rest off the UI thread.
    Callers render ``Loading repositories…`` until the first page arrives.
    """

    def __init__(self) -> None:
        self._items: list[tuple[Account, AccountRepositories]] = []
        self._listeners: list[Listener] = []

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:
                log.exception("ApiRepositoriesStore listener failed")

    def on_accounts_changed(self, accounts: list[Account]) -> None:
        """Drop cache for signed-out accounts; keep lists when Account details refresh."""
        new_items: list[tuple[Account, AccountRepositories]] = []
        for account in accounts:
            index = _index_of(account, self._items)
            if index >= 0:
                new_items.append((account, self._items[index][1]))
        self._items = new_items
        self.emit()

    def get_state(self) -> list[tuple[Account, AccountRepositories]]:
        return list(self._items)

    def get_account_state(self, account: Account) -> AccountRepositories | None:
        index = _index_of(account, self._items)
        if index < 0:
            return None
        return self._items[index][1]

    def _update_account(self, account: Account, **fields: Any) -> None:
        index = _index_of(account, self._items)
        if index < 0:
            current = AccountRepositories(repositories=[], loading=False)
        else:
            current = self._items[index][1]
        updated = replace(current, **fields)
        if index < 0:
            self._items = [*self._items, (account, updated)]
        else:
            self._items = [
                (account, updated) if i == index else item
                for i, item in enumerate(self._items)
            ]
        self.emit()

    def load_repositories(
        self,
        account: Account,
        run: Callable[[Callable[[], Any], Callable[..., None]], None],
    ) -> None:
        """Desktop `ApiRepositoriesStore.loadRepositories`.

        Skip when a refresh is already in flight. Stream pages into cache, then
        drop clone URLs that disappeared on the host.
        """
        current = self.get_account_state(account)
        if current is not None and current.loading:
            return
        self._update_account(account, loading=True)
        cached = list(current.repositories) if current else []

        def work() -> None:
            missing: dict[str, GitHubRepository] = {}
            repositories: dict[str, GitHubRepository] = {}
            for repo in cached:
                key = repo.clone_url or repo.full_name
                missing[key] = repo
                repositories[key] = repo

            def add_page(page: list[GitHubRepository]) -> None:
                for repo in page:
                    key = repo.clone_url or repo.full_name
                    repositories[key] = repo
                    missing.pop(key, None)
                snapshot = list(repositories.values())
                _marshal(lambda snap=snapshot: self._update_account(account, repositories=snap) or False)

            GitHubAPI.from_account(account).load_cloneable_repositories(add_page)
            if missing:
                for key in list(missing):
                    repositories.pop(key, None)
                snapshot = list(repositories.values())
                _marshal(lambda snap=snapshot: self._update_account(account, repositories=snap) or False)

        def done(exc: BaseException | None, _result: object = None) -> None:
            if exc:
                log.warn("loadRepositories: failed for %s", account.login, exc_info=exc)
            self._update_account(account, loading=False)

        run(work, done)


def iter_account_repositories(
    store: ApiRepositoriesStore,
) -> Iterator[tuple[Account, AccountRepositories]]:
    yield from store.get_state()
