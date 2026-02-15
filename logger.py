"""
Centralized logging for the Cambridge/Wiktionary Fetcher add-on.

Uses Python's standard ``logging`` module with a ``RotatingFileHandler`` so
that log files never grow without bound.

Default log level is **WARNING** — only warnings and errors are recorded.
Switch to DEBUG or INFO via *Tools → Dictionary Fetch — Settings* to get
detailed diagnostics when something goes wrong.

Log files are stored next to the add-on code:
    ``cambridge_fetch/logs/cambridge_fetch.log``
    (rotated to .log.1, .log.2, … up to ``BACKUP_COUNT`` backups)
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ADDON_DIR = Path(os.path.dirname(__file__))
LOG_DIR = ADDON_DIR / "logs"
LOG_FILE = LOG_DIR / "cambridge_fetch.log"
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_BYTES = 1 * 1024 * 1024  # 1 MB per file
BACKUP_COUNT = 2  # keep up to 3 files total (current + 2 backups)
DEFAULT_LOG_LEVEL = "WARNING"
VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Root logger name for the entire add-on.  Every module should call
#     logger = get_logger(__name__)
# which produces loggers like ``cambridge_fetch.config``,
# ``cambridge_fetch.fetchers.cambridge``, etc.
_ROOT_LOGGER_NAME = "cambridge_fetch"

# Singleton state
_initialized = False


def _ensure_log_dir() -> None:
    """Create the logs directory if it does not exist."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _setup_root_logger(level: str = DEFAULT_LOG_LEVEL) -> logging.Logger:
    """Configure the root add-on logger (idempotent)."""
    global _initialized

    root = logging.getLogger(_ROOT_LOGGER_NAME)

    if _initialized:
        # Already set up — just update the level.
        root.setLevel(_resolve_level(level))
        return root

    _ensure_log_dir()

    root.setLevel(_resolve_level(level))
    # Prevent messages from bubbling up to Anki's own root logger.
    root.propagate = False

    # File handler with rotation.
    try:
        fh = RotatingFileHandler(
            str(LOG_FILE),
            maxBytes=MAX_BYTES,
            backupCount=BACKUP_COUNT,
            encoding="utf-8",
        )
        fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
        root.addHandler(fh)
    except OSError:
        # If we can't write logs, silently degrade — the add-on should
        # still work without logging.
        pass

    _initialized = True
    return root


def _resolve_level(level: str) -> int:
    """Convert a level name to a ``logging`` constant, defaulting to WARNING."""
    name = (level or DEFAULT_LOG_LEVEL).upper().strip()
    return getattr(logging, name, logging.WARNING)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger for the given module name.

    Typical usage at the top of each module::

        from .logger import get_logger
        logger = get_logger(__name__)

    The first call triggers root-logger initialisation with the default
    level.  Call :func:`set_log_level` later (once config is loaded) to
    adjust.
    """
    _setup_root_logger()  # idempotent
    if name and name.startswith(_ROOT_LOGGER_NAME):
        return logging.getLogger(name)
    if name:
        return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{name}")
    return logging.getLogger(_ROOT_LOGGER_NAME)


def set_log_level(level: str) -> None:
    """Change the effective log level for the entire add-on at runtime.

    Called when config is loaded or settings are saved.
    """
    root = _setup_root_logger(level)
    root.setLevel(_resolve_level(level))
    root.info("Log level changed to %s", level.upper())
