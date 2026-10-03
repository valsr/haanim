"""State trigger for HAAnim.

This module provides state-based triggers:
- state_trigger: Decorator to trigger functions when entity state conditions are met
- StateTrigger: The runtime trigger class that watches for state changes

Example:
    @state_trigger("sensor.temperature > 25", state_hold=60)
    def handle_high_temp():
        '''Called when temperature exceeds 25 for 60 seconds.'''
        pass
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, TypeVar
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from typing import TYPE_CHECKING

from custom_components.haanim.ha.state import StateManager, StateChangedEvent
from custom_components.haanim.ha.events import EventManager
from haanim.const import DECORATOR_STATE_TRIGGER
from haanim.engine.triggers.base import BaseTrigger, TriggerInfo

if TYPE_CHECKING:
    from haanim.engine.automation_context import TriggerDefinition

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
    from haanim.engine.decorators import _get_or_create_metadata as get_metadata

    return get_metadata(func)


def state_trigger(
    *trigger_exprs: str,
    state_hold: float | None = None,
    state_check_now: bool = False,
    watch: list[str] | None = None,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function when state conditions are met.

    When an entity's state changes and the trigger expression evaluates to true,
    the decorated function is called. Multiple expressions can be provided - if
    any expression matches, the function triggers.

    Args:
        trigger_exprs: One or more state expressions that trigger the function.
            Expressions support comparison operators: ==, !=, >, >=, <, <=
            Examples: "sensor.temperature > 25", "binary_sensor.motion == 'on'"
        state_hold: Optional seconds the condition must remain true before triggering.
            Useful for debouncing rapid state changes. If the condition becomes false
            before the hold period expires, the trigger is cancelled.
        state_check_now: If True, check the condition immediately on automation load
            and trigger if it's already satisfied. Default is False.
        watch: Optional list of entity IDs to watch for changes. If not provided,
            entities are automatically extracted from the trigger expressions.
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @state_trigger("sensor.temperature > 25", state_hold=60)
        def handle_high_temp():
            '''Triggers when temp > 25 for 60 seconds.'''
            pass

        @state_trigger(
            "binary_sensor.motion == 'on'",
            "binary_sensor.door == 'open'",
        )
        def handle_activity():
            '''Triggers when either motion OR door opens.'''
            pass

        @state_trigger("sensor.power > 1000", state_check_now=True)
        def high_power_usage():
            '''Also checks at automation load time.'''
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_STATE_TRIGGER,
            trigger_expr=list(trigger_exprs) if len(trigger_exprs) != 1 else trigger_exprs[0],
            kwargs={
                "state_hold": state_hold,
                "state_check_now": state_check_now,
                "watch": watch,
                **kwargs,
            },
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


class StateTrigger(BaseTrigger):
    """Trigger that fires on state changes.

    Watches specified entities for state changes and evaluates trigger expressions
    when changes occur. Supports hold times to require conditions to remain true
    for a specified duration before triggering.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the state trigger.

        Args:
            hass: Home Assistant instance.
            trigger_def: The trigger definition from the automation.
            state_manager: State manager instance.
            event_manager: Event manager instance.
        """
        super().__init__(hass, trigger_def, state_manager, event_manager)

        self._state_hold = self._get_state_hold_from_trigger(trigger_def)
        self._state_check_now = trigger_def.kwargs.get("state_check_now", False)
        self._watch_entities: list[str] = trigger_def.kwargs.get("watch") or []
        self._queue: asyncio.Queue[StateChangedEvent | None] | None = None
        self._hold_task: asyncio.Task[None] | None = None

    def _get_state_hold_from_trigger(self, trigger: TriggerDefinition) -> float | None:
        """Extract and validate state_hold from trigger definition.

        Args:
            trigger: The trigger definition.

        Returns:
            Validated state_hold value or None.
        """
        state_hold = trigger.kwargs.get("state_hold")
        if state_hold is None:
            return state_hold

        try:
            state_hold = float(state_hold)
            if state_hold < 0:
                self._logger.warning(
                    "state_hold must be a positive number, got %s. Setting to None.",
                    state_hold,
                )
                return None
            return state_hold
        except (ValueError, TypeError):
            self._logger.warning(
                "state_hold must be a number, got %s (%s). Setting to None.",
                state_hold,
                type(state_hold).__name__,
            )
            return None

    async def async_start(self) -> None:
        """Start the state trigger."""
        # Extract entities from trigger expression if not explicitly specified
        if not self._watch_entities:
            self._watch_entities = self._extract_entities(self.trigger_def.trigger_expr)

        # Subscribe to state changes
        for entity_id in self._watch_entities:
            self._queue = self.state_manager.subscribe(entity_id)

        # Start watch task
        self._task = self.hass.async_create_task(
            self._watch_loop(),
            name=f"haanim_state_trigger_{self.trigger_def.automation_id}_{self.trigger_def.func_name}",
        )

        # Check now if requested
        if self._state_check_now:
            await self._check_and_execute()

        self._logger.debug(
            "State trigger started: %s (watching %s)",
            self.trigger_def.trigger_expr,
            self._watch_entities,
        )

    async def async_stop(self) -> None:
        """Stop the state trigger."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self._hold_task:
            self._hold_task.cancel()

        if self._queue:
            for entity_id in self._watch_entities:
                self.state_manager.unsubscribe(self._queue, entity_id)

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

    async def _watch_loop(self) -> None:
        """Watch for state changes."""
        if self._queue is None:
            return

        while True:
            try:
                notification = await self._queue.get()
                if notification is None:
                    break

                # Evaluate trigger expression
                if self._evaluate_trigger():
                    # Check constraints
                    if await self._check_constraints():
                        await self._handle_trigger_match(notification)

            except asyncio.CancelledError:
                break
            except Exception as err:
                self._logger.error("Error in state trigger watch loop: %s", err)

    def _evaluate_trigger(self) -> bool:
        """Evaluate the trigger expression.

        Returns:
            True if trigger condition is met.
        """
        expr = self.trigger_def.trigger_expr
        if isinstance(expr, list):
            # Any expression matching triggers
            return any(self._evaluate_state_expr(e) for e in expr)
        return self._evaluate_state_expr(expr)

    async def _handle_trigger_match(self, notification: StateChangedEvent) -> None:
        """Handle a trigger match.

        Args:
            notification: State change notification.
        """
        if self._state_hold:
            # Cancel any pending hold task
            if self._hold_task:
                self._hold_task.cancel()

            # Start new hold task
            self._hold_task = self.hass.async_create_task(
                self._hold_and_execute(notification),
            )
        else:
            await self._execute_function(
                var_name=notification.entity_id,
                value=notification.new_state,
                old_value=notification.old_state,
            )

    async def _hold_and_execute(self, notification: StateChangedEvent) -> None:
        """Wait for hold period and execute if still true.

        Args:
            notification: State change notification.
        """
        try:
            if self._state_hold:
                await asyncio.sleep(self._state_hold)

            # Re-check trigger condition
            if self._evaluate_trigger():
                if await self._check_constraints():
                    await self._execute_function(
                        var_name=notification.entity_id,
                        value=notification.new_state,
                        old_value=notification.old_state,
                    )
        except asyncio.CancelledError:
            pass

    async def _check_and_execute(self) -> None:
        """Check trigger condition and execute if met."""
        if self._evaluate_trigger():
            if await self._check_constraints():
                await self._execute_function()
