"""Base classes shared by all trigger types."""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import TYPE_CHECKING, Any, TypeVar

from haanim import const
from haanim.engine.callables import as_coroutine_function, event_arguments
from haanim.events import SOURCE_TRIGGER, ActionEvent
from haanim.interfaces import EventBus, Host, StateProvider

if TYPE_CHECKING:
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
    ) -> None:
        """Initialize the trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition from the automation.
        """
        self.host = host
        self.trigger_def = trigger_def
        self.state_manager: StateProvider = host.states
        self.event_manager: EventBus = host.events

        self._task: asyncio.Task[None] | None = None
        self._enabled = True
        self._constraints: list[dict[str, Any]] = []
        self._logger = logging.getLogger(f"{__name__}.{trigger_def.automation_id}.{trigger_def.func_name}")

    @abstractmethod
    async def async_start(self) -> None:
        """Start the trigger."""

    @abstractmethod
    async def async_stop(self) -> None:
        """Stop the trigger."""

    def set_constraints(self, constraints: list[dict[str, Any]]) -> None:
        """Set constraints for this trigger.

        Args:
            constraints: List of constraint definitions.
        """
        self._constraints = constraints

    async def _check_constraints(self) -> bool:
        """Check if all constraints are satisfied.

        Returns:
            True if all constraints pass, False otherwise.
        """
        for constraint in self._constraints:
            constraint_type = constraint.get("type")

            if constraint_type == const.CONSTRAINT_TIME:
                if not await self._check_time_constraint(constraint):
                    return False

            elif constraint_type == const.CONSTRAINT_STATE:
                if not await self._check_state_constraint(constraint):
                    return False

        return True

    async def _check_time_constraint(self, constraint: dict[str, Any]) -> bool:
        """Check a time constraint.

        Args:
            constraint: The constraint definition.

        Returns:
            True if constraint is satisfied.
        """
        specs = constraint.get("specs", [])
        now = self.host.clock.now()

        for spec in specs:
            if self._evaluate_time_spec(spec, now):
                return True

        return len(specs) == 0  # No specs means always active

    def _evaluate_time_spec(self, spec: str, now: datetime) -> bool:
        """Evaluate a time specification.

        Args:
            spec: Time specification string.
            now: Current datetime.

        Returns:
            True if current time matches spec.
        """
        # Handle range(start, end)
        range_match = re.match(r"range\(([^,]+),\s*([^)]+)\)", spec)
        if range_match:
            start_str, end_str = range_match.groups()
            start_time = self._parse_time_value(start_str.strip(), now)
            end_time = self._parse_time_value(end_str.strip(), now)

            if start_time and end_time:
                current_time = now.time()
                if start_time <= end_time:
                    return start_time <= current_time <= end_time
                else:
                    # Overnight range (e.g., 22:00 to 06:00)
                    return current_time >= start_time or current_time <= end_time

        return False

    def _parse_time_value(self, value: str, now: datetime) -> time | None:
        """Parse a time value (HH:MM, sunrise, sunset, etc.).

        Args:
            value: Time value string.
            now: Current datetime for sun calculations.

        Returns:
            Time object, or None if parsing fails.
        """
        # Handle sunrise/sunset
        if "sunrise" in value.lower():
            sun_time = self.host.sun.next_event("sunrise", now)
            if sun_time:
                return sun_time.time()
            return None

        if "sunset" in value.lower():
            sun_time = self.host.sun.next_event("sunset", now)
            if sun_time:
                return sun_time.time()
            return None

        # Handle HH:MM format
        time_match = re.match(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", value)
        if time_match:
            hour, minute = int(time_match.group(1)), int(time_match.group(2))
            second = int(time_match.group(3)) if time_match.group(3) else 0
            return time(hour, minute, second)

        return None

    async def _check_state_constraint(self, constraint: dict[str, Any]) -> bool:
        """Check a state constraint.

        Args:
            constraint: The constraint definition.

        Returns:
            True if constraint is satisfied.
        """
        exprs = constraint.get("exprs", [])

        for expr in exprs:
            if not self._evaluate_state_expr(expr):
                return False

        return True

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
