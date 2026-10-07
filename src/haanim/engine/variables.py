"""Persistent variables: the key/value store of one automation.

See "Persistent Storage" in the design. The store is kept in memory and read
and changed synchronously. Changes are written to the storage backend shortly
afterwards, several of them together, and always when the automation stops.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from haanim.interfaces import Clock, StorageBackend, TimerHandle

_LOGGER = logging.getLogger(__name__)

# How long after a change the store is written; changes within that time are written together.
SAVE_DELAY_SECONDS = 1.0


def storage_key(automation_id: str) -> str:
    """Return the key an automation's variables are stored under."""
    return f"automation.{automation_id}"


def _check_json(value: Any, where: str) -> None:
    """Raise TypeError unless a value is JSON: str, number, bool, None, list, or dict with string keys."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _check_json(item, f"{where}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{where}: a dictionary key must be a string, not {type(key).__name__}")
            _check_json(item, f"{where}[{key!r}]")
        return
    raise TypeError(f"{where}: {type(value).__name__} is not a JSON value")


class VariableStore:
    """The persistent variables of one automation."""

    def __init__(self, automation_id: str, backend: StorageBackend, clock: Clock) -> None:
        """Initialize an empty store. ``load()`` reads what was saved before.

        Args:
            automation_id: ID of the automation the variables belong to.
            backend: Where the store is saved.
            clock: The clock the delayed write runs on.
        """
        self._automation_id = automation_id
        self._key = storage_key(automation_id)
        self._backend = backend
        self._clock = clock
        self._values: dict[str, Any] = {}
        self._dirty = False
        self._timer: TimerHandle | None = None
        self._writes: set[asyncio.Future[None]] = set()

    async def load(self) -> None:
        """Read the saved variables into memory, replacing what is there."""
        saved = await self._backend.load(self._key)
        self._values = dict(saved) if isinstance(saved, dict) else {}
        self._dirty = False

    # --- The synchronous API ------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Store a copy of a value.

        Raises:
            TypeError: If the key is not a string or the value is not a JSON
                value. Nothing is stored in that case.
        """
        if not isinstance(key, str):
            raise TypeError(f"a variable name must be a string, not {type(key).__name__}")
        _check_json(value, f"variable '{key}'")
        # Through JSON: a copy, with tuples as lists, exactly as it will read back
        self._values[key] = json.loads(json.dumps(value))
        self._changed()

    def get(self, key: str, default: Any = None) -> Any:
        """Return a copy of a value, or ``default`` if the key is not set."""
        if key not in self._values:
            return default
        return json.loads(json.dumps(self._values[key]))

    def unset(self, key: str) -> None:
        """Remove one variable; does nothing if it is not set."""
        if key in self._values:
            del self._values[key]
            self._changed()

    def clear(self) -> None:
        """Remove every variable."""
        if self._values:
            self._values.clear()
            self._changed()

    def keys(self) -> list[str]:
        """Return the names of the variables that are set."""
        return list(self._values)

    # --- Writing ------------------------------------------------------------------

    @property
    def is_dirty(self) -> bool:
        """Whether there are changes that have not been written yet."""
        return self._dirty

    def _changed(self) -> None:
        """Note a change and make sure a write is scheduled."""
        self._dirty = True
        if self._timer is None:
            self._timer = self._clock.call_later(SAVE_DELAY_SECONDS, self._write_later)

    def _write_later(self) -> None:
        """The delay has passed: write in the background."""
        self._timer = None
        write = asyncio.ensure_future(self._write())
        self._writes.add(write)
        write.add_done_callback(self._writes.discard)

    async def _write(self) -> None:
        """Write the store if it has changes. A failure is logged and the changes stay pending."""
        if not self._dirty:
            return
        self._dirty = False
        try:
            await self._backend.save(self._key, self._values)
        except Exception as err:  # pylint: disable=broad-exception-caught
            self._dirty = True
            _LOGGER.error("Failed to save the variables of '%s': %s", self._automation_id, err)

    async def flush(self) -> None:
        """Write pending changes now. Called when the automation stops."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        if self._writes:
            await asyncio.gather(*self._writes, return_exceptions=True)
        await self._write()
