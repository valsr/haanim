"""Trigger system for HAAnim.

This module handles trigger registration, evaluation, and execution for
state triggers, time triggers, and event triggers.
"""

from __future__ import annotations

import asyncio
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.sun import get_astral_event_next
from homeassistant.util import dt as dt_util

from .const import (
    DECORATOR_EVENT_TRIGGER,
    DECORATOR_STATE_ACTIVE,
    DECORATOR_STATE_TRIGGER,
    DECORATOR_TIME_ACTIVE,
    DECORATOR_TIME_TRIGGER,
)
from .ha_state import StateManager
from .ha_events import EventManager
from .script_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)


class BaseTrigger(ABC):
    """Base class for all trigger types."""

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the trigger.

        Args:
            hass: Home Assistant instance.
            trigger_def: The trigger definition from the script.
            state_manager: State manager instance.
            event_manager: Event manager instance.
        """
        self.hass = hass
        self.trigger_def = trigger_def
        self.state_manager = state_manager
        self.event_manager = event_manager

        self._task: asyncio.Task | None = None
        self._enabled = True
        self._constraints: list[dict[str, Any]] = []
        self._logger = logging.getLogger(
            f"{__name__}.{trigger_def.script_name}.{trigger_def.func_name}"
        )

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

            if constraint_type == DECORATOR_TIME_ACTIVE:
                if not await self._check_time_constraint(constraint):
                    return False

            elif constraint_type == DECORATOR_STATE_ACTIVE:
                if not await self._check_state_constraint(constraint):
                    return False

        return True

    async def _check_time_constraint(self, constraint: dict[str, Any]) -> bool:
        """Check a time_active constraint.

        Args:
            constraint: The constraint definition.

        Returns:
            True if constraint is satisfied.
        """
        specs = constraint.get("specs", [])
        now = dt_util.now()

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
            sun_time = get_astral_event_next(self.hass, "sunrise", now)
            if sun_time:
                return sun_time.time()
            return None

        if "sunset" in value.lower():
            sun_time = get_astral_event_next(self.hass, "sunset", now)
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
        """Check a state_active constraint.

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

    async def _execute_function(self, **kwargs: Any) -> Any:
        """Execute the trigger function.

        Args:
            **kwargs: Arguments to pass to the function.

        Returns:
            Return value from the function.
        """
        func = self.trigger_def.func
        kwargs["manual"] = False

        try:
            if asyncio.iscoroutinefunction(func):
                return await func(**kwargs)
            else:
                return await self.hass.async_add_executor_job(lambda: func(**kwargs))
        except Exception as err:
            self._logger.error(
                "Trigger function %s.%s failed: %s",
                self.trigger_def.script_name,
                self.trigger_def.func_name,
                err,
            )
            raise


class StateTrigger(BaseTrigger):
    """Trigger that fires on state changes."""

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the state trigger."""
        super().__init__(hass, trigger_def, state_manager, event_manager)

        self._state_hold = trigger_def.kwargs.get("state_hold")
        self._state_check_now = trigger_def.kwargs.get("state_check_now", False)
        self._watch_entities = trigger_def.kwargs.get("watch") or []
        self._queue: asyncio.Queue | None = None
        self._hold_task: asyncio.Task | None = None

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
            name=f"haanim_state_trigger_{self.trigger_def.script_name}_{self.trigger_def.func_name}",
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
            entities = []
            for e in expr:
                entities.extend(self._extract_entities(e))
            return list(set(entities))

        # Find entity_id patterns (domain.entity)
        pattern = r"\b([a-z_]+\.[a-z0-9_]+)\b"
        return list(set(re.findall(pattern, expr, re.IGNORECASE)))

    async def _watch_loop(self) -> None:
        """Watch for state changes."""
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

    async def _handle_trigger_match(self, notification: dict[str, Any]) -> None:
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
                var_name=notification.get("entity_id"),
                value=notification.get("new_state"),
                old_value=notification.get("old_state"),
            )

    async def _hold_and_execute(self, notification: dict[str, Any]) -> None:
        """Wait for hold period and execute if still true.

        Args:
            notification: State change notification.
        """
        try:
            await asyncio.sleep(self._state_hold)

            # Re-check trigger condition
            if self._evaluate_trigger():
                if await self._check_constraints():
                    await self._execute_function(
                        var_name=notification.get("entity_id"),
                        value=notification.get("new_state"),
                        old_value=notification.get("old_state"),
                    )
        except asyncio.CancelledError:
            pass

    async def _check_and_execute(self) -> None:
        """Check trigger condition and execute if met."""
        if self._evaluate_trigger():
            if await self._check_constraints():
                await self._execute_function()


class TimeTrigger(BaseTrigger):
    """Trigger that fires at specific times."""

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the time trigger."""
        super().__init__(hass, trigger_def, state_manager, event_manager)

        self._startup_triggered = False

    async def async_start(self) -> None:
        """Start the time trigger."""
        self._task = self.hass.async_create_task(
            self._time_loop(),
            name=f"haanim_time_trigger_{self.trigger_def.script_name}_{self.trigger_def.func_name}",
        )

        self._logger.debug("Time trigger started: %s", self.trigger_def.trigger_expr)

    async def async_stop(self) -> None:
        """Stop the time trigger."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _time_loop(self) -> None:
        """Main time trigger loop."""
        expr = self.trigger_def.trigger_expr
        specs = [expr] if isinstance(expr, str) else expr

        while True:
            try:
                # Calculate next trigger time
                next_time = self._calculate_next_trigger(specs)

                if next_time is None:
                    # No valid next time, check for startup trigger
                    if "startup" in str(specs) and not self._startup_triggered:
                        self._startup_triggered = True
                        if await self._check_constraints():
                            await self._execute_function()
                    await asyncio.sleep(60)  # Check again in a minute
                    continue

                # Wait until trigger time
                now = dt_util.now()
                wait_seconds = (next_time - now).total_seconds()

                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # Check constraints and execute
                if await self._check_constraints():
                    await self._execute_function()

                # Small delay to prevent rapid re-triggering
                await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception as err:
                self._logger.error("Error in time trigger loop: %s", err)
                await asyncio.sleep(60)  # Wait before retrying

    def _calculate_next_trigger(self, specs: list[str]) -> datetime | None:
        """Calculate the next trigger time from specs.

        Args:
            specs: List of time specifications.

        Returns:
            Next trigger datetime, or None if no valid time found.
        """
        now = dt_util.now()
        next_times = []

        for spec in specs:
            next_time = self._parse_time_spec(spec, now)
            if next_time and next_time > now:
                next_times.append(next_time)

        if next_times:
            return min(next_times)
        return None

    def _parse_time_spec(self, spec: str, now: datetime) -> datetime | None:
        """Parse a time specification.

        Args:
            spec: Time specification string.
            now: Current datetime.

        Returns:
            Next datetime matching the spec.
        """
        spec = spec.strip()

        # Handle cron(...)
        cron_match = re.match(r"cron\(([^)]+)\)", spec)
        if cron_match:
            return self._parse_cron(cron_match.group(1), now)

        # Handle time(HH:MM:SS)
        time_match = re.match(r"time\((\d{1,2}):(\d{2})(?::(\d{2}))?\)", spec)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            second = int(time_match.group(3)) if time_match.group(3) else 0

            target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target

        # Handle sunrise/sunset with optional offset
        sun_match = re.match(r"(sunrise|sunset)\s*([+-]\s*\d+)?\s*(m|min|minutes?|h|hours?)?", spec, re.IGNORECASE)
        if sun_match:
            event = sun_match.group(1).lower()
            offset_val = sun_match.group(2)
            offset_unit = sun_match.group(3)

            sun_time = get_astral_event_next(self.hass, event, now)
            if sun_time:
                if offset_val:
                    offset_num = int(offset_val.replace(" ", ""))
                    if offset_unit and offset_unit.startswith("h"):
                        sun_time += timedelta(hours=offset_num)
                    else:
                        sun_time += timedelta(minutes=offset_num)
                return sun_time

        # Handle period(start, interval)
        period_match = re.match(r"period\(([^,]+),\s*(.+)\)", spec)
        if period_match:
            # This is a repeating trigger - calculate next occurrence
            start_str, interval_str = period_match.groups()
            interval = self._parse_interval(interval_str.strip())

            if interval:
                # Find next period occurrence
                start_time = self._parse_time_value(start_str.strip(), now)
                if start_time:
                    base = now.replace(
                        hour=start_time.hour,
                        minute=start_time.minute,
                        second=start_time.second if hasattr(start_time, "second") else 0,
                        microsecond=0,
                    )
                    if base > now:
                        return base

                    # Calculate how many intervals have passed
                    elapsed = (now - base).total_seconds()
                    intervals_passed = int(elapsed / interval.total_seconds()) + 1
                    return base + (interval * intervals_passed)

        return None

    def _parse_cron(self, cron_expr: str, now: datetime) -> datetime | None:
        """Parse a cron expression and find next occurrence.

        Args:
            cron_expr: Cron expression (minute hour day month weekday).
            now: Current datetime.

        Returns:
            Next datetime matching the cron expression.
        """
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                return None

            minute, hour, day, month, weekday = parts

            # Simple implementation - find next matching time
            # For full cron support, consider using croniter library
            target = now + timedelta(minutes=1)
            target = target.replace(second=0, microsecond=0)

            for _ in range(60 * 24 * 7):  # Search up to a week
                if self._cron_matches(target, minute, hour, day, month, weekday):
                    return target
                target += timedelta(minutes=1)

        except Exception as err:
            self._logger.warning("Failed to parse cron expression '%s': %s", cron_expr, err)

        return None

    def _cron_matches(
        self,
        dt: datetime,
        minute: str,
        hour: str,
        day: str,
        month: str,
        weekday: str,
    ) -> bool:
        """Check if datetime matches cron fields.

        Args:
            dt: Datetime to check.
            minute: Cron minute field.
            hour: Cron hour field.
            day: Cron day field.
            month: Cron month field.
            weekday: Cron weekday field.

        Returns:
            True if datetime matches all fields.
        """
        return (
            self._cron_field_matches(dt.minute, minute, 0, 59)
            and self._cron_field_matches(dt.hour, hour, 0, 23)
            and self._cron_field_matches(dt.day, day, 1, 31)
            and self._cron_field_matches(dt.month, month, 1, 12)
            and self._cron_field_matches(dt.weekday(), weekday, 0, 6)
        )

    def _cron_field_matches(self, value: int, field: str, min_val: int, max_val: int) -> bool:
        """Check if value matches a cron field.

        Args:
            value: Value to check.
            field: Cron field pattern.
            min_val: Minimum valid value.
            max_val: Maximum valid value.

        Returns:
            True if value matches field.
        """
        if field == "*":
            return True

        # Handle */n (every n)
        if field.startswith("*/"):
            step = int(field[2:])
            return value % step == 0

        # Handle comma-separated values
        if "," in field:
            return value in [int(v) for v in field.split(",")]

        # Handle range (n-m)
        if "-" in field:
            start, end = map(int, field.split("-"))
            return start <= value <= end

        # Single value
        return value == int(field)

    def _parse_interval(self, interval_str: str) -> timedelta | None:
        """Parse an interval string.

        Args:
            interval_str: Interval string (e.g., "1 hour", "30 min", "1h30m").

        Returns:
            Timedelta for the interval.
        """
        # Handle formats like "1 hour", "30 min", "2 hours 30 minutes"
        total_seconds = 0

        # Hours
        hours_match = re.search(r"(\d+)\s*h(?:ours?)?", interval_str, re.IGNORECASE)
        if hours_match:
            total_seconds += int(hours_match.group(1)) * 3600

        # Minutes
        mins_match = re.search(r"(\d+)\s*m(?:in(?:utes?)?)?", interval_str, re.IGNORECASE)
        if mins_match:
            total_seconds += int(mins_match.group(1)) * 60

        # Seconds
        secs_match = re.search(r"(\d+)\s*s(?:ec(?:onds?)?)?", interval_str, re.IGNORECASE)
        if secs_match:
            total_seconds += int(secs_match.group(1))

        if total_seconds > 0:
            return timedelta(seconds=total_seconds)

        return None


class EventTrigger(BaseTrigger):
    """Trigger that fires on Home Assistant events."""

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize the event trigger."""
        super().__init__(hass, trigger_def, state_manager, event_manager)

        self._event_type = trigger_def.trigger_expr
        self._event_filter = trigger_def.kwargs.get("event_data")
        self._queue: asyncio.Queue | None = None

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

        if self._queue:
            self.event_manager.unsubscribe(self._queue, self._event_type)

    async def _event_loop(self) -> None:
        """Watch for events."""
        while True:
            try:
                notification = await self._queue.get()
                if notification is None:
                    break

                # Check constraints and execute
                if await self._check_constraints():
                    await self._execute_function(
                        event_type=notification.get("event_type"),
                        data=notification.get("data"),
                    )

            except asyncio.CancelledError:
                break
            except Exception as err:
                self._logger.error("Error in event trigger loop: %s", err)


class TriggerManager:
    """Manages all triggers for HAAnim scripts."""

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

    async def _on_ha_started(self, event: Event) -> None:
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
        to_remove = [
            tid for tid in self._triggers.keys()
            if tid.startswith(f"{script_name}.")
        ]

        for trigger_id in to_remove:
            await self.unregister_trigger(trigger_id)

        return len(to_remove)

    def get_trigger_count(self) -> int:
        """Get the number of registered triggers.

        Returns:
            Number of triggers.
        """
        return len(self._triggers)
