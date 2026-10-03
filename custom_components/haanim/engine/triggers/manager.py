"""Trigger manager for HAAnim.

This module provides the TriggerManager class that manages all triggers for HAAnim automations, including
registration, lifecycle, and execution. The TriggerManager centrally listens to all Home Assistant events
and routes them to the appropriate triggers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant

from custom_components.haanim import const
from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.ha.state import StateManager, StateChangedEvent
from custom_components.haanim.engine.action_pool import ActionWorkerPool
from custom_components.haanim.engine.constraints import ConstraintChecker

if TYPE_CHECKING:
    from custom_components.haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)


class TriggerManager:
    """Manages all triggers for HAAnim automations.

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
        action_pool: ActionWorkerPool,
    ) -> None:
        """Initialize the trigger manager.

        Args:
            hass: Home Assistant instance.
            state_manager: State manager instance.
            event_manager: Event manager instance.
            action_pool: Action worker pool for executing triggered functions.
        """
        self.hass = hass
        self.state_manager = state_manager
        self.event_manager = event_manager
        self.action_pool = action_pool
        self.constraint_checker = ConstraintChecker(state_manager)

        # Store triggers by ID
        self._triggers: dict[str, TriggerDefinition] = {}

        # Store trigger metadata (constraints, hold times, etc.)
        self._trigger_metadata: dict[str, dict[str, Any]] = {}

        # Track which entities are being watched for state triggers
        self._entity_triggers: dict[str, list[str]] = {}  # entity_id -> [trigger_ids]

        # Track time-based triggers
        self._time_triggers: list[str] = []  # trigger_ids

        # Track event-based triggers
        self._event_triggers: dict[str, list[str]] = {}  # event_type -> [trigger_ids]

        # State change subscription queue
        self._state_queue: asyncio.Queue[StateChangedEvent | None] | None = None

        # Background tasks
        self._state_watch_task: asyncio.Task[Any] | None = None
        self._time_watch_task: asyncio.Task[Any] | None = None

        # Hold tasks for state triggers
        self._hold_tasks: dict[str, asyncio.Task[None]] = {}  # trigger_id -> task

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

        # Start watching for state changes if we have state triggers
        if self._entity_triggers:
            await self._start_state_watching()

        # Start watching for time-based triggers
        if self._time_triggers:
            await self._start_time_watching()

        _LOGGER.info("Trigger manager started with %d triggers", len(self._triggers))

    async def async_teardown(self) -> None:
        """Tear down the trigger manager."""
        self._started = False

        # Stop state watching
        if self._state_watch_task:
            self._state_watch_task.cancel()
            try:
                await self._state_watch_task
            except asyncio.CancelledError:
                pass

        # Stop time watching
        if self._time_watch_task:
            self._time_watch_task.cancel()
            try:
                await self._time_watch_task
            except asyncio.CancelledError:
                pass

        # Cancel all hold tasks
        for task in self._hold_tasks.values():
            task.cancel()

        # Unsubscribe from state changes
        if self._state_queue:
            for entity_id in self._entity_triggers.keys():
                self.state_manager.unsubscribe(self._state_queue, entity_id)

        self._triggers.clear()
        self._trigger_metadata.clear()
        self._entity_triggers.clear()
        self._time_triggers.clear()
        self._event_triggers.clear()
        self._hold_tasks.clear()

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
        trigger_id = self._get_trigger_id(trigger_def)
        self._triggers[trigger_id] = trigger_def

        # Store metadata
        metadata: dict[str, Any] = {
            "constraints": constraints or [],
        }

        # Handle different trigger types
        if trigger_def.trigger_type == const.DECORATOR_STATE_TRIGGER:
            self._register_state_trigger(trigger_id, trigger_def, metadata)
        elif trigger_def.trigger_type == const.DECORATOR_TIME_TRIGGER:
            self._register_time_trigger(trigger_id, trigger_def, metadata)
        elif trigger_def.trigger_type == const.DECORATOR_EVENT_TRIGGER:
            self._register_event_trigger(trigger_id, trigger_def, metadata)
        else:
            _LOGGER.error("Unknown trigger type: %s", trigger_def.trigger_type)
            del self._triggers[trigger_id]
            return ""

        self._trigger_metadata[trigger_id] = metadata

        # If already started, begin watching immediately
        if self._started:
            if trigger_def.trigger_type == const.DECORATOR_STATE_TRIGGER:
                await self._start_state_watching()
            elif trigger_def.trigger_type == const.DECORATOR_TIME_TRIGGER:
                await self._start_time_watching()

        _LOGGER.debug("Registered trigger: %s", trigger_id)
        return trigger_id

    def _register_state_trigger(
        self,
        trigger_id: str,
        trigger_def: TriggerDefinition,
        metadata: dict[str, Any],
    ) -> None:
        """Register a state-based trigger.

        Args:
            trigger_id: Unique trigger ID.
            trigger_def: The trigger definition.
            metadata: Trigger metadata dictionary to populate.
        """
        # Extract state_hold and state_check_now from kwargs
        state_hold = trigger_def.kwargs.get("state_hold")
        if state_hold is not None:
            try:
                state_hold = float(state_hold)
                if state_hold < 0:
                    state_hold = None
            except (ValueError, TypeError):
                state_hold = None

        metadata["state_hold"] = state_hold
        metadata["state_check_now"] = trigger_def.kwargs.get("state_check_now", False)

        # Extract entities to watch
        watch_entities = trigger_def.kwargs.get("watch") or []
        if not watch_entities:
            watch_entities = self._extract_entities(trigger_def.trigger_expr)

        metadata["watch_entities"] = watch_entities

        # Track entities
        for entity_id in watch_entities:
            if entity_id not in self._entity_triggers:
                self._entity_triggers[entity_id] = []
            self._entity_triggers[entity_id].append(trigger_id)

    def _register_time_trigger(
        self,
        trigger_id: str,
        trigger_def: TriggerDefinition,
        metadata: dict[str, Any],
    ) -> None:
        """Register a time-based trigger.

        Args:
            trigger_id: Unique trigger ID.
            trigger_def: The trigger definition.
            metadata: Trigger metadata dictionary to populate.
        """
        self._time_triggers.append(trigger_id)
        metadata["time_specs"] = trigger_def.trigger_expr

    def _register_event_trigger(
        self,
        trigger_id: str,
        trigger_def: TriggerDefinition,
        metadata: dict[str, Any],
    ) -> None:
        """Register an event-based trigger.

        Args:
            trigger_id: Unique trigger ID.
            trigger_def: The trigger definition.
            metadata: Trigger metadata dictionary to populate.
        """
        # Extract event type from trigger_expr
        event_type = trigger_def.kwargs.get("event_type", "")
        if not event_type and isinstance(trigger_def.trigger_expr, str):
            event_type = trigger_def.trigger_expr

        metadata["event_type"] = event_type

        if event_type not in self._event_triggers:
            self._event_triggers[event_type] = []
        self._event_triggers[event_type].append(trigger_id)

    def _get_trigger_id(self, trigger_def: TriggerDefinition) -> str:
        """Generate a unique trigger ID.

        Args:
            trigger_def: The trigger definition.

        Returns:
            Unique trigger ID.
        """
        prefix = f"{trigger_def.automation_id}.{trigger_def.func_name}."
        ids = [int(key.split(".")[-1]) for key in self._triggers if key.startswith(prefix)]
        if not ids:
            return prefix + "0"
        return prefix + str(max(ids) + 1)

    async def unregister_trigger(self, trigger_id: str) -> bool:
        """Unregister a trigger.

        Args:
            trigger_id: The trigger ID.

        Returns:
            True if trigger was unregistered.
        """
        if trigger_id not in self._triggers:
            return False

        trigger_def = self._triggers.pop(trigger_id)
        metadata = self._trigger_metadata.pop(trigger_id, {})

        # Cancel any pending hold task
        if trigger_id in self._hold_tasks:
            self._hold_tasks[trigger_id].cancel()
            del self._hold_tasks[trigger_id]

        # Remove from tracking structures
        if trigger_def.trigger_type == const.DECORATOR_STATE_TRIGGER:
            for entity_id in metadata.get("watch_entities", []):
                if entity_id in self._entity_triggers:
                    self._entity_triggers[entity_id].remove(trigger_id)
                    if not self._entity_triggers[entity_id]:
                        del self._entity_triggers[entity_id]

        elif trigger_def.trigger_type == const.DECORATOR_TIME_TRIGGER:
            if trigger_id in self._time_triggers:
                self._time_triggers.remove(trigger_id)

        elif trigger_def.trigger_type == const.DECORATOR_EVENT_TRIGGER:
            event_type = metadata.get("event_type", "")
            if event_type in self._event_triggers:
                self._event_triggers[event_type].remove(trigger_id)
                if not self._event_triggers[event_type]:
                    del self._event_triggers[event_type]

        _LOGGER.debug("Unregistered trigger: %s", trigger_id)
        return True

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Unregister all triggers for an automation.

        Args:
            automation_id: ID of the automation.

        Returns:
            Number of triggers unregistered.
        """
        to_remove = [tid for tid in self._triggers if tid.startswith(f"{automation_id}.")]

        for trigger_id in to_remove:
            await self.unregister_trigger(trigger_id)

        return len(to_remove)

    def get_trigger_count(self) -> int:
        """Get the number of registered triggers.

        Returns:
            Number of triggers.
        """
        return len(self._triggers)

    # =========================================================================
    # State Trigger Handling
    # =========================================================================

    async def _start_state_watching(self) -> None:
        """Start watching for state changes."""
        if self._state_watch_task:
            return  # Already watching

        # Create queue if needed
        if not self._state_queue:
            self._state_queue = asyncio.Queue()

        # Subscribe to all entities we're watching
        for entity_id in self._entity_triggers.keys():
            # Note: Each call to subscribe returns a new queue, but we want to share one queue
            # We need to modify this to use a single shared queue
            if not self._state_queue:
                self._state_queue = self.state_manager.subscribe(entity_id)
            else:
                # For additional entities, we need to subscribe them to our existing queue
                # This may require adjusting the StateManager API
                pass

        # Start watch task
        self._state_watch_task = self.hass.async_create_task(
            self._state_watch_loop(),
            name="haanim_trigger_manager_state_watch",
        )

    async def _state_watch_loop(self) -> None:
        """Watch for state changes and route to triggers."""
        if not self._state_queue:
            return

        while True:
            try:
                notification = await self._state_queue.get()
                if notification is None:
                    break

                # Find all triggers watching this entity
                trigger_ids = self._entity_triggers.get(notification.entity_id, [])

                for trigger_id in trigger_ids:
                    # Process each trigger asynchronously
                    self.hass.async_create_task(
                        self._handle_state_trigger(trigger_id, notification),
                        name=f"haanim_state_trigger_{trigger_id}",
                    )

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in state watch loop: %s", err, exc_info=True)

    async def _handle_state_trigger(
        self,
        trigger_id: str,
        notification: StateChangedEvent,
    ) -> None:
        """Handle a state change for a specific trigger.

        Args:
            trigger_id: The trigger ID.
            notification: State change notification.
        """
        trigger_def = self._triggers.get(trigger_id)
        if not trigger_def:
            return

        metadata = self._trigger_metadata.get(trigger_id, {})

        # Evaluate trigger expression
        if not self._evaluate_state_trigger(trigger_def):
            return

        # Check constraints
        if not await self._check_constraints(trigger_id):
            return

        # Handle state_hold if configured
        state_hold = metadata.get("state_hold")
        if state_hold:
            # Cancel any existing hold task for this trigger
            if trigger_id in self._hold_tasks:
                self._hold_tasks[trigger_id].cancel()

            # Start new hold task
            self._hold_tasks[trigger_id] = self.hass.async_create_task(
                self._hold_and_execute(trigger_id, notification, state_hold),
                name=f"haanim_hold_{trigger_id}",
            )
        else:
            # Execute immediately
            await self._execute_trigger(trigger_id, notification)

    async def _hold_and_execute(
        self,
        trigger_id: str,
        notification: StateChangedEvent,
        hold_seconds: float,
    ) -> None:
        """Wait for hold period and execute if condition still true.

        Args:
            trigger_id: The trigger ID.
            notification: State change notification.
            hold_seconds: Seconds to hold.
        """
        try:
            await asyncio.sleep(hold_seconds)

            # Re-check trigger condition
            trigger_def = self._triggers.get(trigger_id)
            if not trigger_def:
                return

            if self._evaluate_state_trigger(trigger_def):
                if await self._check_constraints(trigger_id):
                    await self._execute_trigger(trigger_id, notification)

        except asyncio.CancelledError:
            pass
        finally:
            # Clean up hold task
            if trigger_id in self._hold_tasks:
                del self._hold_tasks[trigger_id]

    def _evaluate_state_trigger(self, trigger_def: TriggerDefinition) -> bool:
        """Evaluate a state trigger expression.

        Args:
            trigger_def: The trigger definition.

        Returns:
            True if trigger condition is met.
        """
        expr = trigger_def.trigger_expr
        if isinstance(expr, list):
            # Any expression matching triggers
            return any(self._evaluate_state_expr(e) for e in expr)
        return self._evaluate_state_expr(expr)

    def _evaluate_state_expr(self, expr: str) -> bool:
        """Evaluate a single state expression.

        Args:
            expr: State expression like "sensor.temp > 25".

        Returns:
            True if expression evaluates to true.
        """
        return self.constraint_checker._evaluate_state_expr(expr)

    # =========================================================================
    # Time Trigger Handling
    # =========================================================================

    async def _start_time_watching(self) -> None:
        """Start watching for time-based triggers."""
        if self._time_watch_task:
            return  # Already watching

        self._time_watch_task = self.hass.async_create_task(
            self._time_watch_loop(),
            name="haanim_trigger_manager_time_watch",
        )

    async def _time_watch_loop(self) -> None:
        """Watch for time-based triggers."""
        while True:
            try:
                # Check all time triggers every minute
                await asyncio.sleep(60)

                current_time = datetime.now()

                for trigger_id in self._time_triggers:
                    if await self._should_fire_time_trigger(trigger_id, current_time):
                        self.hass.async_create_task(
                            self._handle_time_trigger(trigger_id),
                            name=f"haanim_time_trigger_{trigger_id}",
                        )

            except asyncio.CancelledError:
                break
            except Exception as err:
                _LOGGER.error("Error in time watch loop: %s", err, exc_info=True)

    async def _should_fire_time_trigger(
        self,
        trigger_id: str,
        current_time: datetime,
    ) -> bool:
        """Check if a time trigger should fire.

        Args:
            trigger_id: The trigger ID.
            current_time: Current time.

        Returns:
            True if trigger should fire.
        """
        # TODO: Implement full time trigger evaluation (cron, intervals, etc.)
        # For now, this is a placeholder
        return False

    async def _handle_time_trigger(self, trigger_id: str) -> None:
        """Handle a time-based trigger firing.

        Args:
            trigger_id: The trigger ID.
        """
        if not await self._check_constraints(trigger_id):
            return

        await self._execute_trigger(trigger_id)

    # =========================================================================
    # Constraint Checking
    # =========================================================================

    async def _check_constraints(self, trigger_id: str) -> bool:
        """Check if trigger constraints are met.

        Args:
            trigger_id: The trigger ID.

        Returns:
            True if all constraints are met.
        """
        metadata = self._trigger_metadata.get(trigger_id, {})
        constraints = metadata.get("constraints", [])
        return await self.constraint_checker.check_constraints(constraints)

    # =========================================================================
    # Trigger Execution
    # =========================================================================

    async def _execute_trigger(
        self,
        trigger_id: str,
        notification: StateChangedEvent | None = None,
    ) -> None:
        """Execute a trigger's function.

        Args:
            trigger_id: The trigger ID.
            notification: Optional state change notification for context.
        """
        trigger_def = self._triggers.get(trigger_id)
        if not trigger_def:
            return

        try:
            # Build kwargs for the function
            kwargs: dict[str, Any] = {"manual": False}

            if notification:
                kwargs["var_name"] = notification.entity_id
                kwargs["value"] = notification.new_state
                kwargs["old_value"] = notification.old_state

            # Execute through action pool
            await self.action_pool.submit_action(
                automation_id=trigger_def.automation_id or "",
                action_name=trigger_def.func_name,
                func=trigger_def.func,
                **kwargs,
            )

        except Exception as err:
            _LOGGER.error(
                "Error executing trigger %s: %s",
                trigger_id,
                err,
                exc_info=True,
            )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _extract_entities(self, expr: str | list[str]) -> list[str]:
        """Extract entity IDs from a trigger expression.

        Args:
            expr: Trigger expression or list of expressions.

        Returns:
            List of entity IDs found in the expression.
        """
        if isinstance(expr, list):
            entities: list[str] = []
            for e in expr:
                entities.extend(self._extract_entities(e))
            return list(set(entities))

        # Find entity_id patterns (domain.entity)
        pattern = r"\b([a-z_]+\.[a-z0-9_]+)\b"
        return list(set(re.findall(pattern, expr, re.IGNORECASE)))
