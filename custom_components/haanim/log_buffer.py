"""The recent log records of each automation, for the card and the panel."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

LOGGER_PREFIX = "custom_components.haanim.automation"
"""The logger above every automation's logger."""

MAX_RECORDS = 200
"""How many records are kept per automation."""

LogListener = Callable[[dict[str, Any]], None]


class AutomationLogBuffer(logging.Handler):
    """Keeps the latest records of each automation's logger and passes new ones on to subscribers."""

    def __init__(self, max_records: int = MAX_RECORDS) -> None:
        """Initialize with no records.

        Args:
            max_records: How many records to keep per automation; the oldest go first.
        """
        super().__init__()
        self._max_records = max_records
        self._records: dict[str, deque[dict[str, Any]]] = {}
        self._listeners: dict[str, list[LogListener]] = {}

    def install(self) -> None:
        """Start receiving the records of all automations."""
        logging.getLogger(LOGGER_PREFIX).addHandler(self)

    def remove(self) -> None:
        """Stop receiving records."""
        logging.getLogger(LOGGER_PREFIX).removeHandler(self)

    def emit(self, record: logging.LogRecord) -> None:
        """Keep a record of an automation's logger and tell the automation's subscribers."""
        if not record.name.startswith(LOGGER_PREFIX + "."):
            return
        automation_id = record.name[len(LOGGER_PREFIX) + 1 :].split(".", 1)[0]
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["traceback"] = logging.Formatter().formatException(record.exc_info)
        self._records.setdefault(automation_id, deque(maxlen=self._max_records)).append(entry)
        for listener in list(self._listeners.get(automation_id, ())):
            listener(entry)

    def records(self, automation_id: str) -> list[dict[str, Any]]:
        """Return the kept records of an automation, oldest first."""
        return list(self._records.get(automation_id, ()))

    def subscribe(self, automation_id: str, listener: LogListener) -> Callable[[], None]:
        """Call ``listener(record)`` for every new record of an automation.

        Returns:
            A function that ends the subscription.
        """
        listeners = self._listeners.setdefault(automation_id, [])
        listeners.append(listener)
        return lambda: listeners.remove(listener) if listener in listeners else None
