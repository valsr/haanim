"""Interval trigger: fires at a fixed rate.

See "Interval Trigger" in the design. Fires are scheduled from the moment the
trigger is started: at ``delay``, ``delay + interval``, ``delay + 2 * interval``
and so on. The schedule does not depend on how long the action takes.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from haanim.engine.durations import parse_duration
from haanim.engine.triggers.base import BaseTrigger
from haanim.events import IntervalEvent
from haanim.interfaces import Host, TimerHandle

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


class IntervalTrigger(BaseTrigger):
    """Fires an action repeatedly, a fixed time apart."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize interval trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: Trigger definition. Its expression is the interval;
                the ``delay`` option is the time before the first fire.
            dispatcher: Where the action is requested when the trigger fires.

        Raises:
            ValueError: If the interval or the delay is not a duration.
        """
        super().__init__(host, trigger_def, dispatcher)

        self._interval_seconds = parse_duration(trigger_def.trigger_expr)
        delay = trigger_def.kwargs.get("delay")
        # Without a delay the first fire is one interval after the start
        self._delay_seconds = parse_duration(delay) if delay is not None else self._interval_seconds

        self._started_at: datetime | None = None
        self._timer: TimerHandle | None = None
        self._fires_scheduled = 0
        self._execution_count = 0
        self._firing: set[asyncio.Future[Any]] = set()

    @property
    def interval_seconds(self) -> float:
        """The time between fires, in seconds."""
        return self._interval_seconds

    @property
    def delay_seconds(self) -> float:
        """The time between the start and the first fire, in seconds."""
        return self._delay_seconds

    @property
    def execution_count(self) -> int:
        """How often the trigger has fired since it was started, dropped fires included."""
        return self._execution_count

    async def async_start(self) -> None:
        """Start the schedule from now. The count starts again at zero."""
        await self.async_stop()
        self._started_at = self.host.clock.now()
        self._fires_scheduled = 0
        self._execution_count = 0
        self._schedule_next()

    async def async_stop(self) -> None:
        """Stop the schedule. Fires missed while stopped are not caught up."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._started_at = None

    def _schedule_next(self) -> None:
        """Set the timer for the next fire, at its fixed place in the schedule."""
        assert self._started_at is not None
        offset = self._delay_seconds + self._fires_scheduled * self._interval_seconds
        self._timer = self.host.clock.call_at(self._started_at + timedelta(seconds=offset), self._on_due)

    def _on_due(self) -> None:
        """A fire is due: schedule the one after it, then fire without waiting for the action."""
        if self._started_at is None:
            return
        self._fires_scheduled += 1
        self._schedule_next()

        firing = asyncio.ensure_future(self._fire())
        self._firing.add(firing)
        firing.add_done_callback(self._firing.discard)

    async def _fire(self) -> None:
        """Fire once, unless a constraint blocks it."""
        if not await self._check_constraints():
            return
        # Counted before the request is made: a dropped fire is a fire too
        self._execution_count += 1
        event = self._event(
            IntervalEvent,
            interval_seconds=self._interval_seconds,
            execution_count=self._execution_count,
        )
        await self._execute_function(event)
