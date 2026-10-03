"""Home Assistant state integration for HAAnim.

This module provides state access, manipulation, and change notifications
for use within HAAnim automations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State as HAState, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)


@dataclass
class StateChangedEvent:
    """Data class representing a state changed event.

    Used for strongly typed state change notifications in queues.
    """

    entity_id: str
    old_state: StateVal | None
    new_state: StateVal


class StateVal:
    """Wrapper class for Home Assistant entity states.

    Provides convenient access to entity state values and attributes,
    with helper methods for type conversion.
    """

    def __init__(self, state: HAState | None, entity_id: str | None = None) -> None:
        """Initialize a StateVal wrapper.

        Args:
            state: The Home Assistant State object, or None if entity not found.
            entity_id: The entity ID (used when state is None).
        """
        self._state = state
        self._entity_id = entity_id or (state.entity_id if state else None)

    @property
    def state(self) -> str | None:
        """Get the state value as a string.

        Returns:
            The state value, or None if unavailable.
        """
        if self._state is None:
            return None
        return self._state.state

    @property
    def entity_id(self) -> str | None:
        """Get the entity ID.

        Returns:
            The entity ID.
        """
        return self._entity_id

    @property
    def attributes(self) -> dict[str, Any]:
        """Get all state attributes.

        Returns:
            Dictionary of attributes.
        """
        if self._state is None:
            return {}
        return dict(self._state.attributes)

    @property
    def last_changed(self) -> datetime | None:
        """Get the time the state last changed.

        Returns:
            Datetime of last change.
        """
        if self._state is None:
            return None
        return self._state.last_changed

    @property
    def last_updated(self) -> datetime | None:
        """Get the time the state was last updated.

        Returns:
            Datetime of last update.
        """
        if self._state is None:
            return None
        return self._state.last_updated

    def __str__(self) -> str:
        """Get string representation (the state value).

        Returns:
            The state value as string.
        """
        return self.state or ""

    def __repr__(self) -> str:
        """Get detailed representation.

        Returns:
            Detailed string representation.
        """
        return f"StateVal({self._entity_id}={self.state})"

    def __eq__(self, other: Any) -> bool:
        """Compare state value equality.

        Args:
            other: Value to compare with.

        Returns:
            True if state equals other.
        """
        if isinstance(other, StateVal):
            return self.state == other.state
        return self.state == str(other)

    def __bool__(self) -> bool:
        """Boolean evaluation of state.

        Returns:
            True if state is truthy (not None, unavailable, unknown, off, false, 0).
        """
        if self._state is None:
            return False
        state = self.state
        if state in (None, STATE_UNAVAILABLE, STATE_UNKNOWN, "off", "false", "0", ""):
            return False
        return True

    def __getattr__(self, name: str) -> Any:
        """Get a state attribute by name.

        Args:
            name: Attribute name.

        Returns:
            Attribute value.

        Raises:
            AttributeError: If attribute not found.
        """
        if name.startswith("_"):
            raise AttributeError(f"'{type(self).__name__}' has no attribute '{name}'")
        if self._state is None:
            raise AttributeError(f"Entity '{self._entity_id}' not found")
        if name in self._state.attributes:
            return self._state.attributes[name]
        raise AttributeError(f"Entity '{self._entity_id}' has no attribute '{name}'")

    def get(self, attr: str, default: Any = None) -> Any:
        """Get an attribute with a default value.

        Args:
            attr: Attribute name.
            default: Default value if not found.

        Returns:
            Attribute value or default.
        """
        if self._state is None:
            return default
        return self._state.attributes.get(attr, default)

    def as_int(self, default: int = 0) -> int:
        """Convert state to integer.

        Args:
            default: Default value if conversion fails.

        Returns:
            State as integer.
        """
        try:
            return int(float(self.state or default))
        except (ValueError, TypeError):
            return default

    def as_float(self, default: float = 0.0) -> float:
        """Convert state to float.

        Args:
            default: Default value if conversion fails.

        Returns:
            State as float.
        """
        try:
            return float(self.state or default)
        except (ValueError, TypeError):
            return default

    def as_bool(self) -> bool:
        """Convert state to boolean.

        Returns:
            State as boolean.
        """
        if self.state in ("on", "true", "yes", "1", "home", "open"):
            return True
        return False

    def as_datetime(self) -> datetime | None:
        """Convert state to datetime.

        Returns:
            State as datetime, or None if conversion fails.
        """
        try:
            return dt_util.parse_datetime(self.state or "")
        except (ValueError, TypeError):
            return None

    def is_available(self) -> bool:
        """Check if the entity state is available.

        Returns:
            True if state is not unavailable or unknown.
        """
        return self.state not in (None, STATE_UNAVAILABLE, STATE_UNKNOWN)


class StateManager:
    """Manages state access and change notifications for HAAnim automations.

    Provides methods to get, set, and watch entity states, with notification
    queues for trigger evaluation.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the state manager.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._listeners: dict[str, list[asyncio.Queue[StateChangedEvent | None]]] = {}
        self._global_listeners: list[asyncio.Queue[StateChangedEvent | None]] = []
        self._unsub_state_changed: Callable[[], None] | None = None

    async def async_setup(self) -> None:
        """Set up state change listening."""
        self._unsub_state_changed = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED,
            self._handle_state_changed,
        )
        _LOGGER.debug("State manager set up")

    async def async_teardown(self) -> None:
        """Tear down state change listening."""
        if self._unsub_state_changed:
            self._unsub_state_changed()
            self._unsub_state_changed = None

        # Clear all queues
        for queues in self._listeners.values():
            for queue in queues:
                # Put None to signal shutdown
                await queue.put(None)
        self._listeners.clear()

        for queue in self._global_listeners:
            await queue.put(None)
        self._global_listeners.clear()

    @callback
    def _handle_state_changed(self, event: Event) -> None:
        """Handle a state changed event.

        Args:
            event: The state changed event.
        """
        entity_id = event.data.get("entity_id")
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")

        if entity_id is None or new_state is None:
            return

        # Create StateVal wrappers
        old_val = StateVal(old_state, entity_id) if old_state else None
        new_val = StateVal(new_state, entity_id)

        notification = StateChangedEvent(
            entity_id=entity_id,
            old_state=old_val,
            new_state=new_val,
        )

        # Notify entity-specific listeners
        if entity_id in self._listeners:
            for queue in self._listeners[entity_id]:
                try:
                    queue.put_nowait(notification)
                except asyncio.QueueFull:
                    _LOGGER.warning("State notification queue full for %s", entity_id)

        # Notify global listeners
        for queue in self._global_listeners:
            try:
                queue.put_nowait(notification)
            except asyncio.QueueFull:
                _LOGGER.warning("Global state notification queue full")

    def get(self, entity_id: str) -> StateVal:
        """Get the current state of an entity.

        Args:
            entity_id: The entity ID.

        Returns:
            StateVal wrapper for the entity state.
        """
        state = self.hass.states.get(entity_id)
        return StateVal(state, entity_id)

    def get_all(self, domain: str | None = None) -> list[StateVal]:
        """Get all entity states, optionally filtered by domain.

        Args:
            domain: Optional domain to filter by.

        Returns:
            List of StateVal wrappers.
        """
        if domain:
            states = self.hass.states.async_all(domain)
        else:
            states = self.hass.states.async_all()

        return [StateVal(state) for state in states]

    async def async_set(
        self,
        entity_id: str,
        state: str,
        attributes: dict[str, Any] | None = None,
        force_update: bool = False,
    ) -> None:
        """Set the state of an entity.

        Args:
            entity_id: The entity ID.
            state: The new state value.
            attributes: Optional attributes to set.
            force_update: If True, update even if state unchanged.
        """
        self.hass.states.async_set(
            entity_id,
            state,
            attributes,
            force_update=force_update,
        )

    def subscribe(self, entity_id: str | None = None) -> asyncio.Queue[StateChangedEvent | None]:
        """Subscribe to state changes for an entity or all entities.

        Args:
            entity_id: Entity ID to watch, or None for all entities.

        Returns:
            Queue that receives state change notifications (StateChangedEvent or None on shutdown).
        """
        queue: asyncio.Queue[StateChangedEvent | None] = asyncio.Queue(maxsize=100)

        if entity_id:
            if entity_id not in self._listeners:
                self._listeners[entity_id] = []
            self._listeners[entity_id].append(queue)
        else:
            self._global_listeners.append(queue)

        return queue

    def unsubscribe(
        self, queue: asyncio.Queue[StateChangedEvent | None], entity_id: str | None = None
    ) -> None:
        """Unsubscribe from state changes.

        Args:
            queue: The queue to remove.
            entity_id: Entity ID if subscribed to specific entity.
        """
        if entity_id and entity_id in self._listeners:
            try:
                self._listeners[entity_id].remove(queue)
            except ValueError:
                pass
        else:
            try:
                self._global_listeners.remove(queue)
            except ValueError:
                pass

    def exists(self, entity_id: str) -> bool:
        """Check if an entity exists.

        Args:
            entity_id: The entity ID.

        Returns:
            True if the entity exists.
        """
        return self.hass.states.get(entity_id) is not None

    def get_entity_info(self, entity_id: str) -> dict[str, Any] | None:
        """Get registry information about an entity.

        Args:
            entity_id: The entity ID.

        Returns:
            Dictionary with entity info, or None if not found.
        """
        registry = er.async_get(self.hass)
        entry = registry.async_get(entity_id)

        if entry is None:
            return None

        return {
            "entity_id": entry.entity_id,
            "unique_id": entry.unique_id,
            "platform": entry.platform,
            "name": entry.name or entry.original_name,
            "icon": entry.icon or entry.original_icon,
            "device_id": entry.device_id,
            "area_id": entry.area_id,
            "disabled": entry.disabled,
        }


# Convenience functions for use in automations


def state_get(hass: HomeAssistant, entity_id: str) -> StateVal:
    """Get the state of an entity.

    Args:
        hass: Home Assistant instance.
        entity_id: The entity ID.

    Returns:
        StateVal wrapper for the entity state.
    """
    state = hass.states.get(entity_id)
    return StateVal(state, entity_id)


async def state_set(
    hass: HomeAssistant,
    entity_id: str,
    state: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    """Set the state of an entity.

    Args:
        hass: Home Assistant instance.
        entity_id: The entity ID.
        state: The new state value.
        attributes: Optional attributes to set.
    """
    hass.states.async_set(entity_id, state, attributes)
