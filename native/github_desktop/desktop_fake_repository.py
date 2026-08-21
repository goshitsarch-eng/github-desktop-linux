"""Desktop `lib/desktop-fake-repository.ts`.

HACK: This is needed because the `RichText` component needs to know what
repo to link issues against. Used when we can't rely on the repo info we keep
in state because we it need Desktop specific, so we've stubbed out this repo.
"""

from __future__ import annotations

from .github.api import get_dotcom_api_endpoint
from .models import GitHubRepository, Repository

desktop_url = "https://github.com/desktop/desktop"

DesktopFakeRepository = Repository(
    id=-1,
    path="",
    name="desktop",
    is_missing=True,
    github=GitHubRepository(
        name="desktop",
        owner="desktop",
        html_url=desktop_url,
        clone_url=f"{desktop_url}.git",
        endpoint=get_dotcom_api_endpoint(),
        db_id=-1,
        private=False,
    ),
)
