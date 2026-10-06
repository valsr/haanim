"""Event trigger: fires when an event of a type is fired on the host's bus.

See "Event Trigger" in the design. An optional ``data`` filter restricts the
trigger to events whose data has those values.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from haanim.engine.triggers.base import BaseTrigger
from haanim.events import EventTriggerEvent
from haanim.interfaces import Host
from haanim.types import EventData

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


def data_matches(data_filter: Mapping[str, Any] | None, event_data: Mapping[str, Any]) -> bool:
    """Return whether an event's data passes a ``data`` filter.

    Every key of the filter must be in the event's data with an equal value.
    Keys of the event that the filter does not name are ignored. A nested
    value (a list or a dictionary) must be equal as a whole.

    Args:
        data_filter: The filter; None or empty for no filter.
        event_data: The data of the event.
    """
    if not data_filter:
        return True
    return all(key in event_data and event_data[key] == value for key, value in data_filter.items())


class EventTrigger(BaseTrigger):
    """Fires an action when an event is fired on the host's event bus."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize the event trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition. Its expression is the event
                type; the ``data`` option is the filter.
            dispatcher: Where the action is requested when the trigger fires.
        """
        super().__init__(host, trigger_def, dispatcher)
        self._event_type: str = trigger_def.trigger_expr
        self._data_filter: Mapping[str, Any] | None = trigger_def.kwargs.get("data")
        self._queue: asyncio.Queue[EventData | None] | None = None
        self._watcher: asyncio.Future[None] | None = None
        self._firing: set[asyncio.Future[Any]] = set()

    @property
    def event_type(self) -> str:
        """The event type the trigger listens for."""
        return self._event_type

    @property
    def data_filter(self) -> Mapping[str, Any] | None:
        """The values an event's data must have; None for no filter."""
        return self._data_filter

    async def async_start(self) -> None:
        """Subscribe to the event type."""
        await self.async_stop()
        self._queue = self.event_manager.subscribe(self._event_type)
        self._watcher = asyncio.ensure_future(self._watch(self._queue))

    async def async_stop(self) -> None:
        """Unsubscribe."""
        if self._queue is not None:
            self.event_manager.unsubscribe(self._queue, self._event_type)
            self._queue = None
        if self._watcher is not None:
            self._watcher.cancel()
            self._watcher = None

    async def _watch(self, queue: asyncio.Queue[EventData | None]) -> None:
        """Fire for every event that passes the filter."""
        while True:
            notification = await queue.get()
            if notification is None:
                return
            # The filter is applied here, before anything is requested
            if data_matches(self._data_filter, notification.data):
                firing = asyncio.ensure_future(self._fire(notification))
                self._firing.add(firing)
                firing.add_done_callback(self._firing.discard)

    async def _fire(self, notification: EventData) -> None:
        """Request the action for an event, unless a constraint blocks the fire."""
        if not await self._check_constraints():
            return
        event = self._event(
            EventTriggerEvent,
            event_type=notification.event_type,
            event_data=notification.data,
            time_fired=notification.time_fired,
            user_id=notification.context_user_id,
        )
        await self._execute_function(event)
