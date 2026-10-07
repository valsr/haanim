"""Triggers that fire at instants computed one after the other.

The time trigger and the cron trigger share this: one timer on the clock for
the next fire, and the following one computed when that fire is due, so the
schedule never depends on how long the action takes.
"""

from __future__ import annotations

import asyncio
from abc import abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any

from haanim.engine.triggers.base import BaseTrigger
from haanim.events import ActionEvent
from haanim.interfaces import Host, TimerHandle

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


class ScheduledTrigger(BaseTrigger):
    """A trigger whose fires are instants on the clock."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize the trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition.
            dispatcher: Where the action is requested when the trigger fires.
        """
        super().__init__(host, trigger_def, dispatcher)
        self._timer: TimerHandle | None = None
        self._next: datetime | None = None
        self._active = False
        self._firing: set[asyncio.Future[Any]] = set()

    @abstractmethod
    def _next_after(self, instant: datetime) -> datetime | None:
        """Return the first fire after an instant; None if there is none."""

    @abstractmethod
    def _event_for(self, due: datetime) -> ActionEvent:
        """Build the event of the fire scheduled for an instant."""

    @property
    def next_fire_time(self) -> datetime | None:
        """When the trigger fires next; None if it is stopped or has nothing left to fire."""
        return self._next

    async def async_start(self) -> None:
        """Schedule the first fire after now. Times that have passed are not caught up."""
        await self.async_stop()
        self._active = True
        self._schedule_after(self.host.clock.now())

    async def async_stop(self) -> None:
        """Cancel the pending fire."""
        self._active = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        self._next = None

    def _schedule_after(self, instant: datetime) -> None:
        """Set the timer for the first fire after an instant, if there is one."""
        self._next = self._next_after(instant)
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
        await self._execute_function(self._event_for(due))
