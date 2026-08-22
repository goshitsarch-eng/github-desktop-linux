"""Persist unpushed tags (Desktop `tags-to-push-storage`)."""

from __future__ import annotations

from typing import Sequence

from .models import Repository
from .settings import Settings


def tags_to_push_key(repository: Repository) -> str:
    """Desktop `getTagsToPushKey`: `tags-to-push-${repository.id}`."""
    return f"tags-to-push-{repository.id}"


def get_tags_to_push(settings: Settings, repository: Repository) -> list[str]:
    """Desktop `getTagsToPush`."""
    key = tags_to_push_key(repository)
    stored = settings.tags_to_push.get(key)
    if stored is None:
        stored = settings.tags_to_push.get(str(repository.id), [])
    return list(stored)


def store_tags_to_push(settings: Settings, repository: Repository, tags: Sequence[str]) -> None:
    """Desktop `storeTagsToPush`."""
    key = tags_to_push_key(repository)
    names = [str(tag) for tag in tags if tag]
    settings.tags_to_push.pop(str(repository.id), None)
    if not names:
        settings.tags_to_push.pop(key, None)
    else:
        settings.tags_to_push[key] = names


def clear_tags_to_push(settings: Settings, repository: Repository) -> None:
    """Desktop `clearTagsToPush`."""
    settings.tags_to_push.pop(tags_to_push_key(repository), None)
    settings.tags_to_push.pop(str(repository.id), None)
