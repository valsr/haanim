"""Cron trigger implementation for HAAnim.

Triggers based on cron expressions.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from croniter import croniter

from custom_components.haanim.const import DECORATOR_CRON_TRIGGER
from custom_components.haanim.engine.triggers.base import BaseTrigger, TriggerInfo

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.haanim.engine.automation_context import TriggerDefinition
    from custom_components.haanim.ha.events import EventManager
    from custom_components.haanim.ha.state import StateManager

_LOGGER = logging.getLogger(__name__)


def _get_or_create_metadata(func: Callable[..., Any]) -> Any:
    """Get or create function metadata.

    Imported lazily to avoid a circular import with the decorators module.
    """
    # pylint: disable-next=import-outside-toplevel
    from custom_components.haanim.engine.decorators import _get_or_create_metadata as get_metadata

    return get_metadata(func)


def cron(
    cron_expr: str,
    **kwargs: Any,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for cron-based triggers.

    Args:
        cron_expr: Cron expression (e.g., "0 9 * * 1-5" for 9 AM on weekdays).
        **kwargs: Additional constraint parameters.

    Returns:
        Decorated function.

    Example:
        @cron("0 9 * * 1-5")
        def weekday_morning_task():
            pass
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_CRON_TRIGGER,
            trigger_expr=cron_expr,
            kwargs=kwargs,
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


class CronTrigger(BaseTrigger):
    """Cron-based trigger."""

    def __init__(
        self,
        hass: HomeAssistant,
        trigger_def: TriggerDefinition,
        state_manager: StateManager,
        event_manager: EventManager,
    ) -> None:
        """Initialize cron trigger.

        Args:
            hass: Home Assistant instance.
            trigger_def: Trigger definition.
            state_manager: State manager.
            event_manager: Event manager.
        """
        super().__init__(hass, trigger_def, state_manager, event_manager)

        cron_str = (
            trigger_def.trigger_expr
            if isinstance(trigger_def.trigger_expr, str)
            else trigger_def.trigger_expr[0]
        )
        self._cron_expr = cron_str
        self._task: asyncio.Task[Any] | None = None

        # Validate cron expression
        try:
            croniter(self._cron_expr)
        except Exception as err:
            raise ValueError(f"Invalid cron expression '{self._cron_expr}': {err}") from err

    async def async_start(self) -> None:
        """Start the cron trigger."""
        self._task = asyncio.create_task(self._run_cron())

    async def async_stop(self) -> None:
        """Stop the cron trigger."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run_cron(self) -> None:
        """Run the cron loop."""
        cron_iter = croniter(self._cron_expr, datetime.now())

        while True:
            try:
                # Get next execution time
                next_time = cron_iter.get_next(datetime)
                now = datetime.now()

                # Wait until next execution
                wait_seconds = (next_time - now).total_seconds()
                if wait_seconds > 0:
                    await asyncio.sleep(wait_seconds)

                # Check constraints
                if await self._check_constraints():
                    await self._execute_function()

            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Error in cron trigger: %s", err)
                await asyncio.sleep(60)  # Wait a minute before retrying
