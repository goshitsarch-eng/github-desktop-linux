"""Application logging to stderr and rotating files."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler

from .paths import log_dir

_LOGGER: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("github_desktop")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.setLevel(logging.INFO)
    stream.setFormatter(fmt)
    logger.addHandler(stream)
    try:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        file_handler = RotatingFileHandler(
            log_dir() / f"desktop.{stamp}.log",
            maxBytes=5_000_000,
            backupCount=8,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass
    _LOGGER = logger
    return logger
