"""``QAbstractListModel`` adapters between :class:`AppStore` and QML.

The store is a coarse-grained observable: it recomputes state and calls
``emit()``. Rather than teach it about per-row change notifications, each model
here takes a fresh snapshot on every refresh and diffs it against the rows it
already holds. Identical snapshots cost nothing, an in-place edit becomes a
``dataChanged`` (so the view keeps its scroll position and selection), and only
an insert or a delete triggers a full reset.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from PySide6.QtCore import QAbstractListModel, QByteArray, QModelIndex, Property, Qt, Signal, Slot

Row = dict[str, Any]

FIRST_ROLE = Qt.ItemDataRole.UserRole + 1


class SnapshotListModel(QAbstractListModel):
    """A list model fed whole snapshots of plain dicts.

    Subclasses declare ``roles``; every row must carry each of them so QML can
    bind to ``model.<role>`` without tripping over a missing key.
    """

    roles: tuple[str, ...] = ()

    countChanged = Signal()

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._rows: list[Row] = []
        self._role_names: dict[int, QByteArray] = {
            FIRST_ROLE + index: QByteArray(name.encode()) for index, name in enumerate(self.roles)
        }
        self._role_lookup: dict[int, str] = {
            FIRST_ROLE + index: name for index, name in enumerate(self.roles)
        }

    # -- QAbstractListModel ------------------------------------------------

    def roleNames(self) -> dict[int, QByteArray]:  # noqa: N802 - Qt API
        return self._role_names

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802 - Qt API
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        name = self._role_lookup.get(role)
        if name is None:
            return None
        return self._rows[index.row()].get(name)

    # -- snapshot plumbing -------------------------------------------------

    def set_rows(self, rows: Sequence[Row]) -> None:
        """Replace the model contents, doing the least disruptive update."""
        new_rows = list(rows)
        if new_rows == self._rows:
            return
        if len(new_rows) == len(self._rows):
            changed = [i for i, row in enumerate(new_rows) if row != self._rows[i]]
            self._rows = new_rows
            if changed:
                # One span covering every edit: cheaper than N signals and the
                # view only repaints delegates it actually has realized.
                top = self.index(changed[0], 0)
                bottom = self.index(changed[-1], 0)
                self.dataChanged.emit(top, bottom, list(self._role_names.keys()))
            return
        self.beginResetModel()
        self._rows = new_rows
        self.endResetModel()
        self.countChanged.emit()

    @property
    def rows(self) -> list[Row]:
        return self._rows

    # -- QML helpers -------------------------------------------------------

    @Property(int, notify=countChanged)
    def count(self) -> int:
        return len(self._rows)

    @Slot(int, result="QVariant")
    def get(self, row: int) -> Row | None:
        """Return a whole row as a JS object (QML cannot index a C++ model)."""
        if 0 <= row < len(self._rows):
            return dict(self._rows[row])
        return None

    @Slot(str, "QVariant", result=int)
    def indexOf(self, role: str, value: Any) -> int:  # noqa: N802 - QML style
        """First row whose ``role`` equals ``value``; -1 when absent."""
        for index, row in enumerate(self._rows):
            if row.get(role) == value:
                return index
        return -1


class CallbackListModel(SnapshotListModel):
    """A snapshot model whose rows come from a callable at refresh time."""

    def __init__(self, source: Callable[[], Iterable[Row]], parent: Any = None) -> None:
        super().__init__(parent)
        self._source = source

    def refresh(self) -> None:
        try:
            rows = list(self._source())
        except Exception:
            from ..logging import get_logger

            get_logger().exception("list model refresh failed")
            return
        self.set_rows(rows)


def make_model(roles: Sequence[str], source: Callable[[], Iterable[Row]]) -> CallbackListModel:
    """Build a one-off model class with ``roles`` and bind it to ``source``."""
    model_type = type(
        "GeneratedListModel",
        (CallbackListModel,),
        {"roles": tuple(roles)},
    )
    return model_type(source)
