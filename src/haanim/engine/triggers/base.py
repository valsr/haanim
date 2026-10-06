"""Base classes shared by all trigger types."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeVar

from haanim.engine.callables import as_coroutine_function, event_arguments
from haanim.engine.constraints.rules import Constraints
from haanim.events import SOURCE_TRIGGER, ActionEvent
from haanim.interfaces import EventBus, Host, StateProvider

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)

E = TypeVar("E", bound=ActionEvent)


class BaseTrigger(ABC):
    """Base class for all trigger types.

    Provides common functionality for state, time, and event triggers including:
    - Constraint checking (time and state constraints)
    - Function execution
    - Lifecycle management (start/stop)
    """

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize the trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition from the automation.
            dispatcher: Where the action is requested when the trigger fires.
                Without one the function is called directly.
        """
        self.host = host
        self.trigger_def = trigger_def
        self._dispatcher = dispatcher
        self.state_manager: StateProvider = host.states
        self.event_manager: EventBus = host.events

        self._task: asyncio.Task[None] | None = None
        self._enabled = True
        self._constraints = Constraints.parse(trigger_def.constraints)
        self._logger = trigger_def.logger or logging.getLogger(
            f"{__name__}.{trigger_def.automation_id}.{trigger_def.func_name}"
        )

    @abstractmethod
    async def async_start(self) -> None:
        """Start the trigger."""

    @abstractmethod
    async def async_stop(self) -> None:
        """Stop the trigger."""

    async def _check_constraints(self) -> bool:
        """Return whether this trigger's constraints allow it to fire now.

        The constraints are those of this trigger's decorator; they are
        evaluated in the host's time zone at the moment the trigger fires.
        """
        return self._constraints.allows(self.host.clock.now(), self.state_manager.get, self.host.sun)

    def _evaluate_state_expr(self, expr: str) -> bool:
        """Evaluate a state expression.

        Args:
            expr: State expression string (e.g., "sensor.temp > 25").

        Returns:
            True if expression evaluates to true.
        """
        # Simple expression parser for common patterns
        # Supports: entity_id == 'value', entity_id > number, etc.

        patterns = [
            (r"([a-z_]+\.[a-z0-9_]+)\s*==\s*['\"]([^'\"]+)['\"]", "eq_str"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*!=\s*['\"]([^'\"]+)['\"]", "neq_str"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*==\s*(\d+(?:\.\d+)?)", "eq_num"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*!=\s*(\d+(?:\.\d+)?)", "neq_num"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*>\s*(\d+(?:\.\d+)?)", "gt"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*>=\s*(\d+(?:\.\d+)?)", "gte"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*<\s*(\d+(?:\.\d+)?)", "lt"),
            (r"([a-z_]+\.[a-z0-9_]+)\s*<=\s*(\d+(?:\.\d+)?)", "lte"),
        ]

        for pattern, op_type in patterns:
            match = re.match(pattern, expr.strip(), re.IGNORECASE)
            if match:
                entity_id, value = match.groups()
                state = self.state_manager.get(entity_id)

                if not state.is_available():
                    return False

                if op_type == "eq_str":
                    return state.state == value
                elif op_type == "neq_str":
                    return state.state != value
                elif op_type in ("eq_num", "neq_num", "gt", "gte", "lt", "lte"):
                    try:
                        if not state.state:
                            _LOGGER.warning("State is not available for entity: %s", entity_id)
                            return False
                        state_val = float(state.state)
                        compare_val = float(value)

                        if op_type == "eq_num":
                            return state_val == compare_val
                        elif op_type == "neq_num":
                            return state_val != compare_val
                        elif op_type == "gt":
                            return state_val > compare_val
                        elif op_type == "gte":
                            return state_val >= compare_val
                        elif op_type == "lt":
                            return state_val < compare_val
                        elif op_type == "lte":
                            return state_val <= compare_val
                    except (ValueError, TypeError):
                        return False

        self._logger.warning("Could not evaluate state expression: %s", expr)
        return False

    def _event(self, event_class: type[E], **fields: Any) -> E:
        """Build the event of a firing of this trigger.

        Args:
            event_class: The event type of this kind of trigger.
            **fields: The fields specific to that type.
        """
        return event_class(
            call_time=self.host.clock.now(),
            automation_id=self.trigger_def.automation_id or "",
            source=SOURCE_TRIGGER,
            **fields,
        )

    async def _execute_function(self, event: ActionEvent) -> Any:
        """Call the trigger function with the event of this firing, if it takes one.

        Args:
            event: The event of the firing.

        Returns:
            Return value from the function.
        """
        func = self.trigger_def.func

        if self._dispatcher is not None:
            # A trigger function is an action: its mode and timeout apply, and a
            # failure is recorded on the automation; there is no caller to raise to
            return await self._dispatcher.fire(
                self.trigger_def.automation_id or "",
                self.trigger_def.action_name or self.trigger_def.func_name,
                func,
                *event_arguments(func, event),
                mode=self.trigger_def.execution_mode,
                timeout=self.trigger_def.timeout,
            )

        try:
            return await as_coroutine_function(func)(*event_arguments(func, event))
        except Exception as err:
            self._logger.error(
                "Trigger function %s.%s failed: %s",
                self.trigger_def.automation_id,
                self.trigger_def.func_name,
                err,
            )
            raise
