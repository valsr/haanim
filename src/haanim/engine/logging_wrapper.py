"""Logging wrapper for HAAnim automations.

See "Logging" in the design. ``from haanim import logging`` and ``import
logging`` both give an automation this wrapper around its own logger, not the
standard library module.
"""

from __future__ import annotations

import logging
from typing import Any

# Automations log under this name, followed by a dot and their ID
AUTOMATION_LOGGER = "custom_components.haanim.automation"


def automation_logger(automation_id: str) -> logging.Logger:
    """Return the logger of an automation: ``custom_components.haanim.automation.<automation_id>``."""
    return logging.getLogger(f"{AUTOMATION_LOGGER}.{automation_id}")


class LoggerWrapper:
    """What an automation logs through: the level methods of its logger, and nothing else."""

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize the logger wrapper.

        Args:
            logger: The automation's logger.
        """
        self._logger = logger

    def debug(self, msg: Any, *args: Any) -> None:
        """Log a message at DEBUG level, with ``msg % args`` formatting."""
        self._logger.debug(msg, *args)

    def info(self, msg: Any, *args: Any) -> None:
        """Log a message at INFO level, with ``msg % args`` formatting."""
        self._logger.info(msg, *args)

    def warning(self, msg: Any, *args: Any) -> None:
        """Log a message at WARNING level, with ``msg % args`` formatting."""
        self._logger.warning(msg, *args)

    def error(self, msg: Any, *args: Any) -> None:
        """Log a message at ERROR level, with ``msg % args`` formatting."""
        self._logger.error(msg, *args)

    def critical(self, msg: Any, *args: Any) -> None:
        """Log a message at CRITICAL level, with ``msg % args`` formatting."""
        self._logger.critical(msg, *args)

    fatal = critical  # Alias

    def print(self, *values: Any, sep: str | None = " ", end: str | None = None, **_: Any) -> None:
        """Log what ``print`` would write, at INFO level. This is the automation's ``print``.

        Args:
            *values: What to print.
            sep: Put between the values; a space by default.
            end: Accepted and ignored: a log record is one entry.
            **_: The other arguments of ``print`` (``file``, ``flush``) are accepted and ignored.
        """
        self._logger.info("%s", (" " if sep is None else sep).join(str(value) for value in values))

    def __getattr__(self, name: str) -> Any:
        """Refuse everything else of the standard ``logging`` module."""
        raise AttributeError(
            f"logging.{name} is not available in an automation; "
            "use debug, info, warning, error or critical"
        )


def create_logger_wrapper(logger: logging.Logger) -> LoggerWrapper:
    """Create a logger wrapper for an automation.

    Args:
        logger: The underlying logger instance.

    Returns:
        LoggerWrapper instance.
    """
    return LoggerWrapper(logger)
