"""Trigger manager for HAAnim.

This module provides the TriggerManager class that manages all triggers
for HAAnim scripts, including registration, lifecycle, and execution.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant

from typing import TYPE_CHECKING

from custom_components.haanim.const import (
    DECORATOR_EVENT_TRIGGER,
    DECORATOR_STATE_TRIGGER,
    DECORATOR_TIME_TRIGGER,
)
from custom_components.haanim.ha.state import StateManager
from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.engine.triggers.base import BaseTrigger

if TYPE_CHECKING:
    from custom_components.haanim.engine.script_context import TriggerDefinition
from custom_components.haanim.engine.triggers.state_trigger import StateTrigger
from custom_components.haanim.engine.triggers.time_trigger import TimeTrigger
from custom_components.haanim.engine.triggers.event_trigger import EventTrigger

_LOGGER = logging.getLogger(__name__)


class TriggerManager:
    """Manages all triggers for HAAnim scripts.

    The TriggerManager is responsible for:
    - Registering triggers from decorated functions
    - Starting/stopping triggers based on Home Assistant lifecycle
    - Routing triggers to the appropriate trigger class
    - Managing trigger constraints
    """

    def __init__(
        self,
        hass: HomeAssistant,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the trigger manager.

        Args:
            hass: Home Assistant instance.
            state_manager: State manager instance.
            event_manager: Event manager instance.
        """
        self.hass = hass
        self.state_manager = state_manager
        self.event_manager = event_manager

        self._triggers: dict[str, BaseTrigger] = {}
        self._started = False

    async def async_setup(self) -> None:
        """Set up the trigger manager."""
        self.hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED,
            self._on_ha_started,
        )

    async def _on_ha_started(self, _: Event) -> None:
        """Handle Home Assistant started event."""
        self._started = True

        # Start all registered triggers
        for trigger in self._triggers.values():
            await trigger.async_start()

        _LOGGER.info("Trigger manager started with %d triggers", len(self._triggers))

    async def async_teardown(self) -> None:
        """Tear down the trigger manager."""
        for trigger in self._triggers.values():
            await trigger.async_stop()
        self._triggers.clear()

    async def register_trigger(
        self,
        trigger_def: TriggerDefinition,
        constraints: list[dict[str, Any]] | None = None,
    ) -> str:
        """Register a trigger.

        Args:
            trigger_def: The trigger definition.
            constraints: Optional constraints for the trigger.

        Returns:
            Unique ID for the registered trigger.
        """
        trigger_id = f"{trigger_def.script_name}.{trigger_def.func_name}.{len(self._triggers)}"

        # Create appropriate trigger type
        trigger: BaseTrigger | None = None

        if trigger_def.trigger_type == DECORATOR_STATE_TRIGGER:
            trigger = StateTrigger(
                self.hass,
                trigger_def,
                self.state_manager,
                self.event_manager,
            )
        elif trigger_def.trigger_type == DECORATOR_TIME_TRIGGER:
            trigger = TimeTrigger(
                self.hass,
                trigger_def,
                self.state_manager,
                self.event_manager,
            )
        elif trigger_def.trigger_type == DECORATOR_EVENT_TRIGGER:
            trigger = EventTrigger(
                self.hass,
                trigger_def,
                self.state_manager,
                self.event_manager,
            )
        else:
            _LOGGER.error("Unknown trigger type: %s", trigger_def.trigger_type)
            return ""

        # Set constraints
        if constraints:
            trigger.set_constraints(constraints)

        self._triggers[trigger_id] = trigger

        # Start immediately if HA is already running
        if self._started:
            await trigger.async_start()

        _LOGGER.debug("Registered trigger: %s", trigger_id)
        return trigger_id

    async def unregister_trigger(self, trigger_id: str) -> bool:
        """Unregister a trigger.

        Args:
            trigger_id: The trigger ID.

        Returns:
            True if trigger was unregistered.
        """
        if trigger_id not in self._triggers:
            return False

        trigger = self._triggers.pop(trigger_id)
        await trigger.async_stop()

        _LOGGER.debug("Unregistered trigger: %s", trigger_id)
        return True

    async def unregister_script_triggers(self, script_name: str) -> int:
        """Unregister all triggers for a script.

        Args:
            script_name: Name of the script.

        Returns:
            Number of triggers unregistered.
        """
        to_remove = [tid for tid in self._triggers.keys() if tid.startswith(f"{script_name}.")]

        for trigger_id in to_remove:
            await self.unregister_trigger(trigger_id)

        return len(to_remove)

    def get_trigger_count(self) -> int:
        """Get the number of registered triggers.

        Returns:
            Number of triggers.
        """
        return len(self._triggers)
