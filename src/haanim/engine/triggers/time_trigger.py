"""Time trigger: fires at the instants a date and time expression names.

See "Time Trigger" in the design. The trigger asks ``next_fire()`` for the next
instant, sets one timer on the clock for it, and asks again when it has fired.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING, Any

from haanim.engine.time_schedule import TimeSchedule, next_fire
from haanim.engine.time_expr import ONCE
from haanim.engine.triggers.base import BaseTrigger
from haanim.events import TimeEvent
from haanim.interfaces import Host, TimerHandle

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


class TimeTrigger(BaseTrigger):
    """Fires an action at a date and/or time."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize the time trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition. Its expression is the date and
                time expression; ``day_of_week`` and ``day_of_month`` are options.
            dispatcher: Where the action is requested when the trigger fires.

        Raises:
            ValueError: If the expression or a day restriction cannot be read.
        """
        super().__init__(host, trigger_def, dispatcher)
        self._schedule = TimeSchedule.parse(
            trigger_def.trigger_expr,
            trigger_def.kwargs.get("day_of_week"),
            trigger_def.kwargs.get("day_of_month"),
        )
        self._timer: TimerHandle | None = None
        self._next: datetime | None = None
        self._active = False
        self._firing: set[asyncio.Future[Any]] = set()

    @property
    def schedule(self) -> TimeSchedule:
        """The parsed expression and its day restrictions."""
        return self._schedule

    @property
    def next_fire_time(self) -> datetime | None:
        """When the trigger fires next; None if it is stopped or has nothing left to fire."""
        return self._next

    async def async_start(self) -> None:
        """Schedule the first fire after now. Times that have passed are not caught up."""
        await self.async_stop()
        self._active = True
        self._schedule_after(self.host.clock.now())
        if self._next is None and self._schedule.expression.recurrence == ONCE:
            # Not an error: the automation may simply have been started after the date
            self._logger.warning(
                "Automation '%s': '%s' of %s is in the past and will not fire",
                self.trigger_def.automation_id,
                self._schedule.expression.source,
                self.trigger_def.func_name,
            )

    async def async_stop(self) -> None:
        """Cancel the pending fire."""
        self._active = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._next = None

    def _schedule_after(self, instant: datetime) -> None:
        """Set the timer for the first fire after an instant, if there is one."""
        self._next = next_fire(self._schedule, instant, self.host.sun)
        self._timer = self.host.clock.call_at(self._next, self._on_due) if self._next is not None else None

    def _on_due(self) -> None:
        """The scheduled instant has come: schedule the one after it, then fire."""
        due = self._next
        if not self._active or due is None:
            return
        self._schedule_after(due)

        firing = asyncio.ensure_future(self._fire(due))
        self._firing.add(firing)
        firing.add_done_callback(self._firing.discard)

    async def _fire(self, due: datetime) -> None:
        """Fire for a scheduled instant, unless a constraint blocks it."""
        if not await self._check_constraints():
            return
        await self._execute_function(self._event(TimeEvent, trigger_time=due))
