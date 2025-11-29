"""Home Assistant event integration for HAAnim.

This module provides event listening and firing capabilities
for use within HAAnim scripts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.core import Event, HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)


class EventManager:
    """Manages event listening and firing for HAAnim scripts.

    Provides methods to listen for Home Assistant events and fire custom events,
    with notification queues for trigger evaluation.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the event manager.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._listeners: dict[str, list[asyncio.Queue]] = {}
        self._global_listeners: list[asyncio.Queue] = []
        self._unsub_callbacks: list[Callable[[], None]] = []

    async def async_setup(self) -> None:
        """Set up the event manager."""
        _LOGGER.debug("Event manager set up")

    async def async_teardown(self) -> None:
        """Tear down the event manager."""
        # Unsubscribe all listeners
        for unsub in self._unsub_callbacks:
            unsub()
        self._unsub_callbacks.clear()

        # Clear all queues
        for queues in self._listeners.values():
            for queue in queues:
                await queue.put(None)
        self._listeners.clear()

        for queue in self._global_listeners:
            await queue.put(None)
        self._global_listeners.clear()

    def subscribe(
        self,
        event_type: str | None = None,
        event_filter: dict[str, Any] | None = None,
    ) -> asyncio.Queue:
        """Subscribe to events.

        Args:
            event_type: Event type to listen for, or None for all events.
            event_filter: Optional filter for event data fields.

        Returns:
            Queue that receives event notifications.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        if event_type:
            if event_type not in self._listeners:
                self._listeners[event_type] = []
                # Register listener with HA
                unsub = self.hass.bus.async_listen(
                    event_type,
                    lambda event, et=event_type, ef=event_filter: self._handle_event(event, et, ef),
                )
                self._unsub_callbacks.append(unsub)

            self._listeners[event_type].append(queue)
        else:
            self._global_listeners.append(queue)

        return queue

    def unsubscribe(self, queue: asyncio.Queue, event_type: str | None = None) -> None:
        """Unsubscribe from events.

        Args:
            queue: The queue to remove.
            event_type: Event type if subscribed to specific type.
        """
        if event_type and event_type in self._listeners:
            try:
                self._listeners[event_type].remove(queue)
            except ValueError:
                pass
        else:
            try:
                self._global_listeners.remove(queue)
            except ValueError:
                pass

    @callback
    def _handle_event(
        self,
        event: Event,
        event_type: str,
        event_filter: dict[str, Any] | None,
    ) -> None:
        """Handle an event from Home Assistant.

        Args:
            event: The event object.
            event_type: The event type.
            event_filter: Optional filter for event data.
        """
        # Apply filter if specified
        if event_filter:
            for key, value in event_filter.items():
                if event.data.get(key) != value:
                    return

        notification = {
            "event_type": event.event_type,
            "data": dict(event.data),
            "origin": event.origin.name if event.origin else None,
            "time_fired": event.time_fired,
            "context": {
                "id": event.context.id,
                "parent_id": event.context.parent_id,
                "user_id": event.context.user_id,
            },
        }

        # Notify type-specific listeners
        if event_type in self._listeners:
            for queue in self._listeners[event_type]:
                try:
                    queue.put_nowait(notification)
                except asyncio.QueueFull:
                    _LOGGER.warning("Event notification queue full for %s", event_type)

        # Notify global listeners
        for queue in self._global_listeners:
            try:
                queue.put_nowait(notification)
            except asyncio.QueueFull:
                _LOGGER.warning("Global event notification queue full")

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


# Convenience functions for use in scripts


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
