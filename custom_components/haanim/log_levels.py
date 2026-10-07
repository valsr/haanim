"""The log level of each automation, as set in the panel or with ``haanim.set_log_level``.

A level set here is put on the automation's logger and kept across restarts.
An automation without one follows Home Assistant's ``logger`` configuration.
"""

from __future__ import annotations

import logging

from custom_components.haanim.log_buffer import LOGGER_PREFIX
from haanim.interfaces import StorageBackend

LOG_LEVELS = ("debug", "info", "warning", "error", "critical")
"""The levels an automation's logger can be set to, from the most to the least it lets through."""

DEFAULT_LEVEL = "default"
"""Stands for no level of HAAnim's own: the logger follows Home Assistant's configuration."""

STORAGE_KEY = "log_levels"


class AutomationLogLevels:
    """Keeps the log level set for each automation and puts it on the automation's logger."""

    def __init__(self, storage: StorageBackend) -> None:
        """Initialize with no levels.

        Args:
            storage: Where the levels are kept across restarts.
        """
        self._storage = storage
        self._levels: dict[str, str] = {}

    @staticmethod
    def _logger(automation_id: str) -> logging.Logger:
        """Return the logger of an automation."""
        return logging.getLogger(f"{LOGGER_PREFIX}.{automation_id}")

    async def async_load(self) -> None:
        """Read the stored levels and put them on the loggers."""
        stored = await self._storage.load(STORAGE_KEY)
        levels = stored if isinstance(stored, dict) else {}
        self._levels = {str(name): level for name, level in levels.items() if level in LOG_LEVELS}
        for automation_id, level in self._levels.items():
            self._logger(automation_id).setLevel(level.upper())

    def level(self, automation_id: str) -> str | None:
        """Return the level set for an automation, or None if it follows Home Assistant's configuration."""
        return self._levels.get(automation_id)

    def effective(self, automation_id: str) -> str:
        """Return the level in effect for an automation: what its logger lets through."""
        return logging.getLevelName(self._logger(automation_id).getEffectiveLevel()).lower()

    async def async_set(self, automation_id: str, level: str | None) -> None:
        """Set the level of an automation and keep it; None or ``default`` takes HAAnim's level away.

        Raises:
            ValueError: If the level is not one of ``LOG_LEVELS``.
        """
        if level in (None, DEFAULT_LEVEL):
            self._levels.pop(automation_id, None)
            self._logger(automation_id).setLevel(logging.NOTSET)
        elif level in LOG_LEVELS:
            self._levels[automation_id] = level
            self._logger(automation_id).setLevel(level.upper())
        else:
            raise ValueError(
                f"Invalid log level {level!r}: use one of {', '.join(LOG_LEVELS)} or {DEFAULT_LEVEL}"
            )
        await self._storage.save(STORAGE_KEY, dict(self._levels))

    def remove(self) -> None:
        """Take HAAnim's levels off the loggers: the integration is being unloaded."""
        for automation_id in self._levels:
            self._logger(automation_id).setLevel(logging.NOTSET)
