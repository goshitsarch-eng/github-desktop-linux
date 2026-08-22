"""XDG-compliant paths for config, state, cache, and logs."""

from __future__ import annotations

import os
from pathlib import Path

from .version import APP_ID


def _xdg(env: str, fallback: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw).expanduser() if raw else fallback


def config_dir() -> Path:
    path = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "github-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def data_dir() -> Path:
    path = _xdg("XDG_DATA_HOME", Path.home() / ".local" / "share") / "github-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _xdg("XDG_CACHE_HOME", Path.home() / ".cache") / "github-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    path = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "github-desktop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return config_dir() / "settings.json"


def repositories_path() -> Path:
    return config_dir() / "repositories.json"


def accounts_path() -> Path:
    return config_dir() / "accounts.json"


def schema_path() -> Path:
    return config_dir() / "gschema-overrides.ini"


APP_ID_PATH = APP_ID
