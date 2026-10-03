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

from haanim.const import TRIGGER_CRON
from haanim.engine.triggers.base import BaseTrigger
from haanim.interfaces import Host

if TYPE_CHECKING:

    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)


class CronTrigger(BaseTrigger):
    """Cron-based trigger."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
    ) -> None:
        """Initialize cron trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: Trigger definition.
        """
        super().__init__(host, trigger_def)

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
        cron_iter = croniter(self._cron_expr, self.host.clock.now())

        while True:
            try:
                # Get next execution time
                next_time = cron_iter.get_next(datetime)
                now = self.host.clock.now()

                # Wait until next execution
                wait_seconds = (next_time - now).total_seconds()
                if wait_seconds > 0:
                    await self.host.clock.sleep(wait_seconds)

                # Check constraints
                if await self._check_constraints():
                    await self._execute_function()

            except asyncio.CancelledError:
                break
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.exception("Error in cron trigger: %s", err)
                await self.host.clock.sleep(60)  # Wait a minute before retrying
