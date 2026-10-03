"""Logging wrapper for HAAnim automations.

Provides a safe logging interface for automations that redirects to the automation's logger.
"""

from __future__ import annotations

import logging
from typing import Any


class LoggerWrapper:
    """Wrapper around Python logger for safe use in automations."""

    def __init__(self, logger: logging.Logger) -> None:
        """Initialize the logger wrapper.

        Args:
            logger: The underlying logger instance.
        """
        self._logger = logger

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message.

        Args:
            msg: The message to log.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments for logging.
        """
        self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an info message.

        Args:
            msg: The message to log.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments for logging.
        """
        self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message.

        Args:
            msg: The message to log.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments for logging.
        """
        self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message.

        Args:
            msg: The message to log.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments for logging.
        """
        self._logger.error(msg, *args, **kwargs)

    def fatal(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a fatal error message.

        Args:
            msg: The message to log.
            *args: Positional arguments for string formatting.
            **kwargs: Keyword arguments for logging.
        """
        self._logger.fatal(msg, *args, **kwargs)

    critical = fatal  # Alias


def create_logger_wrapper(logger: logging.Logger) -> LoggerWrapper:
    """Create a logger wrapper for an automation.

    Args:
        logger: The underlying logger instance.

    Returns:
        LoggerWrapper instance.
    """
    return LoggerWrapper(logger)
