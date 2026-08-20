"""Popup stack matching Desktop `lib/popup-manager.ts`."""

from __future__ import annotations

from .logging import get_logger
from .models import Popup, PopupType

log = get_logger()

DEFAULT_POPUP_STACK_LIMIT = 50


class PopupManager:
    """Desktop `PopupManager`.

    Only one popup of a given type may be open at a time, except `Error`.
    Error popups stay at the top of the stack so they are viewed first.
    """

    def __init__(self, popup_limit: int = DEFAULT_POPUP_STACK_LIMIT) -> None:
        self._stack: list[Popup] = []
        self.popup_limit = popup_limit

    @property
    def current_popup(self) -> Popup | None:
        return self._stack[-1] if self._stack else None

    @property
    def all_popups(self) -> list[Popup]:
        return list(self._stack)

    @property
    def is_a_popup_open(self) -> bool:
        return self.current_popup is not None

    def get_popups_of_type(self, popup_type: PopupType) -> list[Popup]:
        return [item for item in self._stack if item.type == popup_type]

    def are_there_popups_of_type(self, popup_type: PopupType) -> bool:
        return any(item.type == popup_type for item in self._stack)

    def add_popup(self, popup: Popup) -> Popup:
        if popup.type == PopupType.ERROR:
            return self.add_error_popup(popup)
        existing = self.get_popups_of_type(popup.type)
        if existing:
            log.warn("Attempted to add a popup of already existing type - %s.", popup.type)
            return existing[0]
        self._insert_before_error_popups(popup)
        self._check_stack_length()
        return popup

    def add_error_popup(self, popup: Popup) -> Popup:
        if popup.type != PopupType.ERROR:
            popup = Popup(PopupType.ERROR, popup.payload, id=popup.id)
        self._stack.append(popup)
        self._check_stack_length()
        return popup

    def _insert_before_error_popups(self, popup: Popup) -> None:
        if not self._stack or self._stack[-1].type != PopupType.ERROR:
            self._stack.append(popup)
            return
        errors = self.get_popups_of_type(PopupType.ERROR)
        non_errors = [item for item in self._stack if item.type != PopupType.ERROR]
        self._stack = [*non_errors, popup, *errors]

    def _check_stack_length(self) -> None:
        if len(self._stack) <= self.popup_limit:
            return
        oldest = self._stack[0]
        oldest_error = ""
        if oldest.type == PopupType.ERROR:
            oldest_error = f": {oldest.payload.get('error') or ''}"
        current = self.current_popup
        just_added = ""
        if current is not None and current.type == PopupType.ERROR:
            just_added = f" Just added another Error: {current.payload.get('error') or ''}."
        log.warn(
            "TooManyPopups: Max number of %s popups reached while adding popup of type %s. "
            "Removing last popup from the stack. Type %s%s.%s",
            self.popup_limit,
            current.type if current else None,
            oldest.type,
            oldest_error,
            just_added,
        )
        self._stack = self._stack[1:]

    def update_popup(self, popup: Popup) -> None:
        if not popup.id:
            log.warn("Attempted to update a popup without an id.")
            return
        index = next((i for i, item in enumerate(self._stack) if item.id == popup.id), -1)
        if index < 0:
            log.warn("Attempted to update a popup not in the stack.")
            return
        self._stack = [*self._stack[:index], popup, *self._stack[index + 1 :]]

    def remove_popup(self, popup: Popup) -> None:
        if not popup.id:
            log.warn("Attempted to remove a popup without an id.")
            return
        self.remove_popup_by_id(popup.id)

    def remove_popup_by_type(self, popup_type: PopupType) -> None:
        self._stack = [item for item in self._stack if item.type != popup_type]

    def remove_popup_by_id(self, popup_id: str) -> None:
        self._stack = [item for item in self._stack if item.id != popup_id]

    def clear(self) -> list[Popup]:
        pending = list(self._stack)
        self._stack.clear()
        return pending
