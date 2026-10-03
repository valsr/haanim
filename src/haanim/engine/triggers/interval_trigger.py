"""Interval trigger implementation for HAAnim.

Triggers at specific intervals with optional initial delay.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from haanim.const import DECORATOR_INTERVAL_TRIGGER
from haanim.engine.triggers.base import BaseTrigger, TriggerInfo
from haanim.interfaces import Host

if TYPE_CHECKING:

    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)


def _get_or_create_metadata(func: Callable[..., Any]) -> Any:
    """Get or create function metadata.

    Imported lazily to avoid a circular import with the decorators module.
    """
    # pylint: disable-next=import-outside-toplevel
    from haanim.engine.decorators import _get_or_create_metadata as get_metadata

    return get_metadata(func)


def interval(
    interval_spec: str,
    *,
    delay: str | None = None,
    **kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for interval-based triggers.

    Args:
        interval_spec: Interval specification (HH:MM:SS, MM:SS, or seconds).
        delay: Optional initial delay before first execution.
        **kwargs: Additional constraint parameters (when, when_not, etc.).

    Returns:
        Decorated function.

    Example:
        @interval("01:00:00")
        def hourly_task():
            pass

        @interval("00:05:00", delay="00:01:00")
        def delayed_task():
            pass
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_INTERVAL_TRIGGER,
            trigger_expr=interval_spec,
            kwargs={"delay": delay, **kwargs},
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


class IntervalTrigger(BaseTrigger):
    """Interval-based trigger."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
    ) -> None:
        """Initialize interval trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: Trigger definition.
        """
        super().__init__(host, trigger_def)

        # Parse interval
        interval_str = (
            trigger_def.trigger_expr
            if isinstance(trigger_def.trigger_expr, str)
            else trigger_def.trigger_expr[0]
        )
        self._interval_seconds = self._parse_interval(interval_str)

        # Parse delay
        delay_str = trigger_def.kwargs.get("delay")
        self._delay_seconds = self._parse_interval(delay_str) if delay_str else self._interval_seconds

        self._task: asyncio.Task[Any] | None = None
        self._execution_count = 0

    def _parse_interval(self, spec: str) -> float:
        """Parse interval specification to seconds.

        Args:
            spec: Interval spec (HH:MM:SS, MM:SS, or seconds).

        Returns:
            Interval in seconds.
        """
        parts = spec.split(":")
        if len(parts) == 3:
            # HH:MM:SS
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            # MM:SS
            return int(parts[0]) * 60 + int(parts[1])
        else:
            # Seconds
            return float(spec)

    async def async_start(self) -> None:
        """Start the interval trigger."""
        self._task = asyncio.create_task(self._run_interval())

    async def async_stop(self) -> None:
        """Stop the interval trigger."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_interval(self) -> None:
        """Run the interval loop."""
        # Initial delay
        await self.host.clock.sleep(self._delay_seconds)

        while True:
            try:
                # Check constraints
                if await self._check_constraints():
                    self._execution_count += 1
                    await self._execute_function()

                # Wait for next interval
                await self.host.clock.sleep(self._interval_seconds)

            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Error in interval trigger: %s", err)
                await self.host.clock.sleep(self._interval_seconds)
