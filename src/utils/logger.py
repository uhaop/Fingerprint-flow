"""Structured logging setup for Fingerprint Flow."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from src.utils.constants import APP_NAME


def setup_logger(
    log_level: str = "INFO",
    log_file: str | None = None,
) -> logging.Logger:
    """Configure and return the application logger.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        log_file: Optional path to a log file. If None, logs only to console.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(APP_NAME)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    level = getattr(logging, log_level.upper(), logging.INFO)
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s.%(module)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def get_logger(module_name: str | None = None) -> logging.Logger:
    """Get a child logger for a specific module.

    Args:
        module_name: Dotted module name (e.g. 'core.scanner').

    Returns:
        Logger instance.
    """
    base = logging.getLogger(APP_NAME)
    if module_name:
        return base.getChild(module_name)
    return base
