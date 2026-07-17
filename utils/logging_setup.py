"""Privacy-conscious rotating logging."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from config import LoggingConfig
from utils.paths import LOG_DIR, ensure_runtime_directories


class ErrorOnlyFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= logging.ERROR


def setup_logging(config: LoggingConfig) -> None:
    """Configure normal and error logs without recording raw private payloads."""
    ensure_runtime_directories()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if config.debug else getattr(logging, config.level))
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    normal = RotatingFileHandler(
        LOG_DIR / "jarvis.log", maxBytes=config.max_bytes,
        backupCount=config.backup_count, encoding="utf-8",
    )
    normal.setFormatter(formatter)
    errors = RotatingFileHandler(
        LOG_DIR / "error.log", maxBytes=config.max_bytes,
        backupCount=config.backup_count, encoding="utf-8",
    )
    errors.setFormatter(formatter)
    errors.addFilter(ErrorOnlyFilter())
    root.addHandler(normal)
    root.addHandler(errors)
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(console)
