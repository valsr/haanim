"""Home Assistant state integration for HAAnim.

This module provides state access, manipulation, and change notifications
for use within HAAnim automations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from custom_components.haanim.ha.subscriptions import Subscriptions
from haanim.types import StateChangedEvent, StateVal

_LOGGER = logging.getLogger(__name__)

__all__ = ["StateChangedEvent", "StateManager", "StateVal"]


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
        self._subscriptions: Subscriptions[StateChangedEvent] = Subscriptions("state")
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

        await self._subscriptions.close()

    @callback
    def _handle_state_changed(self, event: Event[EventStateChangedData]) -> None:
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

        self._subscriptions.deliver(entity_id, notification)
        self._subscriptions.deliver_to_all(notification)

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
        return self._subscriptions.add(entity_id)

    def unsubscribe(
        self, queue: asyncio.Queue[StateChangedEvent | None], entity_id: str | None = None
    ) -> None:
        """Unsubscribe from state changes.

        Args:
            queue: The queue to remove.
            entity_id: Entity ID if subscribed to specific entity.
        """
        self._subscriptions.remove(queue, entity_id)

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
