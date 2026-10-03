"""Time trigger for HAAnim.

This module provides time-based triggers:
- time_trigger: Decorator to trigger functions at specific times
- TimeTrigger: The runtime trigger class that fires at scheduled times

Example:
    @time_trigger("cron(0 8 * * *)")  # 8 AM daily
    def morning_routine():
        '''Called every morning at 8 AM.'''
        pass
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, TypeVar
from collections.abc import Callable


from typing import TYPE_CHECKING

from haanim.const import DECORATOR_TIME_TRIGGER
from haanim.engine.triggers.base import BaseTrigger, TriggerInfo
from haanim.interfaces import Host

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


def time_trigger(
    *trigger_specs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function at specific times.

    Schedule functions to run at specific times using various time specifications.
    Multiple specifications can be provided - the function triggers at whichever
    time comes next.

    Args:
        trigger_specs: One or more time specifications. Supports:
            - Cron expressions: "cron(0 8 * * *)" (8 AM daily)
            - Time of day: "time(08:00:00)" or "time(08:00)"
            - Periods: "period(0:00, 1 hour)" (every hour starting at midnight)
            - Sunrise/sunset: "sunrise", "sunset", "sunrise + 30m", "sunset - 15m"
            - Startup: "startup" (run when Home Assistant starts)
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @time_trigger("cron(0 8 * * *)")  # 8 AM daily
        def morning_routine():
            '''Runs every morning at 8 AM.'''
            pass

        @time_trigger("sunrise + 30m", "sunset - 15m")
        def lighting_automation():
            '''Runs 30 min after sunrise AND 15 min before sunset.'''
            pass

        @time_trigger("period(6:00, 30 min)")
        def every_30_minutes():
            '''Runs every 30 minutes starting at 6 AM.'''
            pass

        @time_trigger("startup")
        def on_startup():
            '''Runs once when Home Assistant starts.'''
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_expr: str | list[str] = list(trigger_specs) if len(trigger_specs) != 1 else trigger_specs[0]
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_TIME_TRIGGER,
            trigger_expr=trigger_expr,
            kwargs=kwargs,
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


class TimeTrigger(BaseTrigger):
    """Trigger that fires at specific times.

    Supports various time specifications including cron expressions, specific times,
    periodic intervals, and sunrise/sunset with optional offsets.
    """

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
    ) -> None:
        """Initialize the time trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition from the automation.
        """
        super().__init__(host, trigger_def)

        self._startup_triggered = False

    async def async_start(self) -> None:
        """Start the time trigger."""
        self._task = asyncio.create_task(
            self._time_loop(),
            name=f"haanim_time_trigger_{self.trigger_def.automation_id}_{self.trigger_def.func_name}",
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
                now = self.host.clock.now()
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
        now = self.host.clock.now()
        next_times: list[datetime] = []

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
        sun_match = re.match(
            r"(sunrise|sunset)\s*([+-]\s*\d+)?\s*(m|min|minutes?|h|hours?)?", spec, re.IGNORECASE
        )
        if sun_match:
            event = sun_match.group(1).lower()
            offset_val = sun_match.group(2)
            offset_unit = sun_match.group(3)

            sun_time = self.host.sun.next_event(event, now)
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

    def _cron_field_matches(self, value: int, field: str, _: int, __: int) -> bool:
        """Check if value matches a cron field.

        Args:
            value: Value to check.
            field: Cron field pattern.
            _: Minimum valid value (unused, for interface compatibility).
            __: Maximum valid value (unused, for interface compatibility).

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
