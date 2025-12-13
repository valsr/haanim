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
from typing import Any, TypeVar
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from typing import TYPE_CHECKING

from custom_components.haanim.const import DECORATOR_EVENT_TRIGGER
from custom_components.haanim.ha.state import StateManager
from custom_components.haanim.ha.events import EventManager, EventData
from custom_components.haanim.engine.triggers.base import BaseTrigger, TriggerInfo

if TYPE_CHECKING:
    from custom_components.haanim.engine.script_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def _get_or_create_metadata(func: Callable[..., Any]) -> Any:
    """Get or create FunctionMetadata for a function.

    This imports from decorators to avoid circular imports.

    Args:
        func: The function to get/create metadata for.

    Returns:
        The FunctionMetadata instance attached to the function.
    """
    # Import here to avoid circular dependency
    from custom_components.haanim.engine.decorators import _get_or_create_metadata as get_metadata

    return get_metadata(func)


def event_trigger(
    event_type: str,
    *,
    event_data: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function when a Home Assistant event fires.

    Listen for Home Assistant events and trigger the decorated function when
    an event of the specified type fires. Optionally filter by event data.

    Args:
        event_type: The event type to listen for. Common types include:
            - "state_changed": Entity state changes (usually use @state_trigger instead)
            - "call_service": Service calls
            - "automation_triggered": Automation triggers
            - Custom event types from integrations or scripts
        event_data: Optional dictionary to filter events by their data fields.
            Only events with matching data will trigger the function.
            Partial matches are supported - only specified fields are checked.
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @event_trigger("zha_event")
        def handle_any_zha_event(event_type, data):
            '''Called for any ZHA event.'''
            pass

        @event_trigger("custom_event", event_data={"action": "button_press"})
        def handle_button():
            '''Only called when action is "button_press".'''
            pass

        @event_trigger("timer.finished", event_data={"entity_id": "timer.kitchen"})
        def kitchen_timer_done(event_type, data):
            '''Called when kitchen timer finishes.'''
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_EVENT_TRIGGER,
            trigger_expr=event_type,
            kwargs={"event_data": event_data, **kwargs},
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


class EventTrigger(BaseTrigger):
    """Trigger that fires on Home Assistant events.

    Subscribes to specified event types and optionally filters by event data
    before triggering the decorated function.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the event trigger.

        Args:
            hass: Home Assistant instance.
            trigger_def: The trigger definition from the script.
            state_manager: State manager instance.
            event_manager: Event manager instance.
        """
        super().__init__(hass, trigger_def, state_manager, event_manager)

        self._event_type = trigger_def.trigger_expr
        self._event_filter = trigger_def.kwargs.get("event_data")
        self._queue: asyncio.Queue[EventData | None] | None = None

    async def async_start(self) -> None:
        """Start the event trigger."""
        self._queue = self.event_manager.subscribe(
            self._event_type,
            self._event_filter,
        )

        self._task = self.hass.async_create_task(
            self._event_loop(),
            name=f"haanim_event_trigger_{self.trigger_def.script_name}_{self.trigger_def.func_name}",
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
                    await self._execute_function(
                        event_type=notification.event_type,
                        data=notification.data,
                    )

            except asyncio.CancelledError:
                break
            except Exception as err:
                self._logger.error("Error in event trigger loop: %s", err)
