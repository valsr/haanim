"""Event trigger for HAAnim.

This module provides event-based triggers:
- event_trigger: Decorator to trigger functions when Home Assistant events fire
- EventTrigger: The runtime trigger class that listens for events

Example:
    @event_trigger("custom_event", event_data={"action": "button_press"})
    def handle_button():
        '''Called when custom_event fires with matching data.'''
        pass
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TypeVar


from haanim import const
from haanim.engine.triggers.base import BaseTrigger
from haanim.events import EventTriggerEvent
from haanim.interfaces import Host
from haanim.types import EventData

if TYPE_CHECKING:
    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


class EventTrigger(BaseTrigger):
    """Trigger that fires on Home Assistant events.

    Subscribes to specified event types and optionally filters by event data
    before triggering the decorated function.
    """

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
    ) -> None:
        """Initialize the event trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition from the automation.
        """
        super().__init__(host, trigger_def)

        self._event_type = trigger_def.trigger_expr
        self._event_filter = trigger_def.kwargs.get("data")
        self._queue: asyncio.Queue[EventData | None] | None = None

    async def async_start(self) -> None:
        """Start the event trigger."""
        self._queue = self.event_manager.subscribe(
            self._event_type,
            self._event_filter,
        )

        self._task = asyncio.create_task(
            self._event_loop(),
            name=f"haanim_event_trigger_{self.trigger_def.automation_id}_{self.trigger_def.func_name}",
        )

        self._logger.debug("Event trigger started: %s", self._event_type)

    async def async_stop(self) -> None:
        """Stop the event trigger."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _event_loop(self) -> None:
        """Watch for events."""
        if self._queue is None:
            _LOGGER.warning("Event trigger queue is None. Exiting event loop.")
            return

        while True:
            try:
                notification = await self._queue.get()
                if notification is None:
                    break

                # Check constraints and execute
                if await self._check_constraints():
                    event = self._event(
                        EventTriggerEvent,
                        event_type=notification.event_type,
                        event_data=notification.data,
                        time_fired=notification.time_fired,
                        user_id=notification.context_user_id,
                    )
                    await self._execute_function(event)

            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                self._logger.error("Error in event trigger loop: %s", err)
