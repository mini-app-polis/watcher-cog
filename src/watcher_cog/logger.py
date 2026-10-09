"""Logging setup for watcher-cog."""

from __future__ import annotations

import logging
import os

LOGGER_NAME = "watcher_cog"
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _build_logger() -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    level_name = os.getenv("LOGGING_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)

    logger.propagate = False
    return logger


log = _build_logger()
