"""Trigger manager for HAAnim.

This module provides the TriggerManager class that manages all triggers for HAAnim automations, including
registration, lifecycle, and execution. The TriggerManager centrally listens to all Home Assistant events
and routes them to the appropriate triggers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING, Any


from haanim import const
from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.callables import event_arguments
from haanim.engine.constraints import ConstraintChecker, Constraints
from haanim.engine.triggers.base import BaseTrigger
from haanim.engine.triggers.cron_trigger import CronTrigger
from haanim.engine.triggers.interval_trigger import IntervalTrigger
from haanim.engine.triggers.time_trigger import TimeTrigger
from haanim.interfaces import EventBus, Host, StateProvider
from haanim.events import SOURCE_TRIGGER, ActionEvent, StateEvent
from haanim.types import StateChangedEvent

if TYPE_CHECKING:
    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)

# The trigger kinds that run their own schedule on the clock
_SCHEDULED: dict[str, type[IntervalTrigger] | type[TimeTrigger] | type[CronTrigger]] = {
    const.TRIGGER_CRON: CronTrigger,
    const.TRIGGER_INTERVAL: IntervalTrigger,
    const.TRIGGER_TIME: TimeTrigger,
}


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
        host: Host,
        dispatcher: ActionDispatcher,
    ) -> None:
        """Initialize the trigger manager.

        Args:
            host: The host the engine runs in.
            dispatcher: Where the triggered actions are requested.
        """
        self.host = host
        self.state_manager: StateProvider = host.states
        self.event_manager: EventBus = host.events
        self.dispatcher = dispatcher
        self.constraint_checker = ConstraintChecker(host.states)

        # Store triggers by ID
        self._triggers: dict[str, TriggerDefinition] = {}

        # Store trigger metadata (constraints, hold times, etc.)
        self._trigger_metadata: dict[str, dict[str, Any]] = {}

        # Track which entities are being watched for state triggers
        self._entity_triggers: dict[str, list[str]] = {}  # entity_id -> [trigger_ids]

        # Track event-based triggers
        self._event_triggers: dict[str, list[str]] = {}  # event_type -> [trigger_ids]

        # State change subscription queue
        self._state_queue: asyncio.Queue[StateChangedEvent | None] | None = None

        # Background tasks
        self._state_watch_task: asyncio.Task[Any] | None = None

        # Triggers that run their own schedule, by trigger ID
        self._running: dict[str, BaseTrigger] = {}

        # Hold tasks for state triggers
        self._hold_tasks: dict[str, asyncio.Task[None]] = {}  # trigger_id -> task

        self._started = False

    async def async_setup(self) -> None:
        """Set up the trigger manager."""
        self.event_manager.listen_once(const.EVENT_HOST_STARTED, self._on_ha_started)

    async def _on_ha_started(self, _: Any) -> None:
        """Handle Home Assistant started event."""
        self._started = True

        # Start watching for state changes if we have state triggers
        if self._entity_triggers:
            await self._start_state_watching()

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

        # Cancel all hold tasks
        for task in self._hold_tasks.values():
            task.cancel()

        # Unsubscribe from state changes
        if self._state_queue:
            for entity_id in self._entity_triggers.keys():
                self.state_manager.unsubscribe(self._state_queue, entity_id)

        for running in self._running.values():
            await running.async_stop()
        self._running.clear()

        self._triggers.clear()
        self._trigger_metadata.clear()
        self._entity_triggers.clear()
        self._event_triggers.clear()
        self._hold_tasks.clear()

    async def register_trigger(self, trigger_def: TriggerDefinition) -> str:
        """Register a trigger.

        Args:
            trigger_def: The trigger definition. Its constraints are those of its decorator.

        Returns:
            Unique ID for the registered trigger.
        """
        trigger_id = self._get_trigger_id(trigger_def)
        self._triggers[trigger_id] = trigger_def

        # Store metadata
        metadata: dict[str, Any] = {}

        # Handle different trigger types
        if trigger_def.trigger_type == const.TRIGGER_STATE:
            self._register_state_trigger(trigger_id, trigger_def, metadata)
        elif trigger_def.trigger_type == const.TRIGGER_EVENT:
            self._register_event_trigger(trigger_id, trigger_def, metadata)
        elif trigger_def.trigger_type in _SCHEDULED:
            # Scheduled from now: the automation's @startup has completed
            scheduled = _SCHEDULED[trigger_def.trigger_type](self.host, trigger_def, self.dispatcher)
            self._running[trigger_id] = scheduled
            await scheduled.async_start()
        else:
            _LOGGER.error("Unknown trigger type: %s", trigger_def.trigger_type)
            del self._triggers[trigger_id]
            return ""

        self._trigger_metadata[trigger_id] = metadata

        # If already started, begin watching immediately
        if self._started:
            if trigger_def.trigger_type == const.TRIGGER_STATE:
                await self._start_state_watching()

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
        state_hold = trigger_def.kwargs.get("hold")
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

        # Stop a trigger that runs its own schedule
        running = self._running.pop(trigger_id, None)
        if running is not None:
            await running.async_stop()

        # Cancel any pending hold task
        if trigger_id in self._hold_tasks:
            self._hold_tasks[trigger_id].cancel()
            del self._hold_tasks[trigger_id]

        # Remove from tracking structures
        if trigger_def.trigger_type == const.TRIGGER_STATE:
            for entity_id in metadata.get("watch_entities", []):
                if entity_id in self._entity_triggers:
                    self._entity_triggers[entity_id].remove(trigger_id)
                    if not self._entity_triggers[entity_id]:
                        del self._entity_triggers[entity_id]

        elif trigger_def.trigger_type == const.TRIGGER_EVENT:
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
                # This may require adjusting the StateProvider API
                pass

        # Start watch task
        self._state_watch_task = asyncio.create_task(
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
                    asyncio.create_task(
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
            self._hold_tasks[trigger_id] = asyncio.create_task(
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
            await self.host.clock.sleep(hold_seconds)

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
        trigger_def = self._triggers.get(trigger_id)
        if trigger_def is None:
            return False
        constraints = Constraints.parse(trigger_def.constraints)
        return constraints.allows(self.host.clock.now(), self.state_manager.get, self.host.sun)

    # =========================================================================
    # Trigger Execution
    # =========================================================================

    def _event(self, trigger_def: TriggerDefinition, notification: StateChangedEvent | None) -> ActionEvent:
        """Build the event of a firing of a trigger.

        Args:
            trigger_def: The trigger that fires.
            notification: The state change that caused it, for a state trigger.
        """
        now = self.host.clock.now()
        fields: dict[str, Any] = {
            "call_time": now,
            "automation_id": trigger_def.automation_id or "",
            "source": SOURCE_TRIGGER,
        }
        if notification is not None:
            return StateEvent(
                entity_id=notification.entity_id,
                old_state=notification.old_state,
                new_state=notification.new_state,
                **fields,
            )
        return ActionEvent(**fields)

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
            event = self._event(trigger_def, notification)

            # A trigger function is an action: its execution mode applies.
            # Its failures are recorded by the dispatcher; there is no caller to raise to
            await self.dispatcher.fire(
                trigger_def.automation_id or "",
                trigger_def.action_name or trigger_def.func_name,
                trigger_def.func,
                *event_arguments(trigger_def.func, event),
                mode=trigger_def.execution_mode,
                timeout=trigger_def.timeout,
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
