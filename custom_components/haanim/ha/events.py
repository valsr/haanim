"""Home Assistant event integration for HAAnim.

This module provides event listening and firing capabilities for use within HAAnim automations.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.const import MATCH_ALL
from homeassistant.core import Event, HomeAssistant, callback

from custom_components.haanim.ha.subscriptions import Subscriptions

from haanim.types import EventData

_LOGGER = logging.getLogger(__name__)

__all__ = ["EventData", "EventManager"]


class EventManager:
    """Manages event listening and firing for HAAnim automations.

    Provides methods to listen for Home Assistant events and fire custom events,
    with notification queues for trigger evaluation.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the event manager.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._subscriptions: Subscriptions[EventData] = Subscriptions("event")
        self._unsub_callbacks: list[Callable[[], None]] = []
        self._listening_to_all = False

    async def async_setup(self) -> None:
        """Set up the event manager."""
        _LOGGER.debug("Event manager set up")

    async def async_teardown(self) -> None:
        """Tear down the event manager."""
        _LOGGER.debug("Event manager tear down")

        # Unsubscribe all listeners
        for unsub in self._unsub_callbacks:
            unsub()
        self._unsub_callbacks.clear()
        self._listening_to_all = False

        await self._subscriptions.close()

    def subscribe(
        self,
        event_type: str | None = None,
        event_filter: dict[str, Any] | None = None,
    ) -> asyncio.Queue[EventData | None]:
        """Subscribe to events.

        Each subscriber has its own filter: two subscribers of one event type
        can ask for different data.

        Args:
            event_type: Event type to listen for, or None for all events.
            event_filter: Only events whose data has every listed key with an equal value.

        Returns:
            Queue that receives event notifications (EventData or None on shutdown).
        """
        if event_type:
            # One listener in Home Assistant per event type, however many subscribers there are
            if not self._subscriptions.has_key(event_type):
                self._unsub_callbacks.append(self.hass.bus.async_listen(event_type, self._handle_event))
        elif not self._listening_to_all:
            self._listening_to_all = True
            self._unsub_callbacks.append(self.hass.bus.async_listen(MATCH_ALL, self._handle_any_event))

        wanted = dict(event_filter or {})

        def accepts(event: EventData) -> bool:
            return all(event.data.get(key) == value for key, value in wanted.items())

        return self._subscriptions.add(event_type, accepts if wanted else None)

    def unsubscribe(self, queue: asyncio.Queue[EventData | None], event_type: str | None = None) -> None:
        """Unsubscribe from events.

        Args:
            queue: The queue to remove.
            event_type: Event type if subscribed to specific type.
        """
        self._subscriptions.remove(queue, event_type)

    @staticmethod
    def _notification(event: Event[Any]) -> EventData:
        """Describe a Home Assistant event for the engine."""
        return EventData(
            event_type=str(event.event_type),
            data=dict(event.data),
            origin=event.origin.name if event.origin else None,
            time_fired=event.time_fired,
            context_id=event.context.id,
            context_parent_id=event.context.parent_id,
            context_user_id=event.context.user_id,
        )

    @callback
    def _handle_event(self, event: Event[Any]) -> None:
        """Pass an event on to the subscribers of its type."""
        self._subscriptions.deliver(str(event.event_type), self._notification(event))

    @callback
    def _handle_any_event(self, event: Event[Any]) -> None:
        """Pass an event on to the subscribers of all events."""
        self._subscriptions.deliver_to_all(self._notification(event))

    def fire(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """Fire an event.

        Args:
            event_type: The event type to fire.
            event_data: Optional event data.
        """
        self.hass.bus.async_fire(event_type, event_data)

    async def async_fire(
        self,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> None:
        """Fire an event asynchronously.

        Args:
            event_type: The event type to fire.
            event_data: Optional event data.
        """
        self.hass.bus.async_fire(event_type, event_data)

    def listen_once(
        self,
        event_type: str,
        callback_func: Callable[[Event], Any],
    ) -> Callable[[], None]:
        """Listen for an event once.

        Args:
            event_type: The event type to listen for.
            callback_func: Function to call when event fires.

        Returns:
            Function to unsubscribe the listener.
        """
        return self.hass.bus.async_listen_once(event_type, callback_func)


# Convenience functions for use in automations


def event_fire(
    hass: HomeAssistant,
    event_type: str,
    event_data: dict[str, Any] | None = None,
) -> None:
    """Fire an event.

    Args:
        hass: Home Assistant instance.
        event_type: The event type to fire.
        event_data: Optional event data.
    """
    hass.bus.async_fire(event_type, event_data)


async def event_wait(
    hass: HomeAssistant,
    event_type: str,
    timeout: float | None = None,
    event_filter: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Wait for an event to fire.

    Args:
        hass: Home Assistant instance.
        event_type: The event type to wait for.
        timeout: Maximum time to wait in seconds.
        event_filter: Optional filter for event data fields.

    Returns:
        Event data dictionary, or None if timeout.
    """
    event_received = asyncio.Event()
    event_data: dict[str, Any] | None = None

    @callback
    def handle_event(event: Event) -> None:
        nonlocal event_data

        # Apply filter
        if event_filter:
            for key, value in event_filter.items():
                if event.data.get(key) != value:
                    return

        event_data = {
            "event_type": event.event_type,
            "data": dict(event.data),
            "time_fired": event.time_fired,
        }
        event_received.set()

    unsub = hass.bus.async_listen(event_type, handle_event)

    try:
        await asyncio.wait_for(event_received.wait(), timeout=timeout)
        return event_data
    except asyncio.TimeoutError:
        return None
    finally:
        unsub()
