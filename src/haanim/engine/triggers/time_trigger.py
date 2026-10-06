"""Time trigger: fires at the instants a date and time expression names.

See "Time Trigger" in the design.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from haanim.engine.time_expr import ONCE
from haanim.engine.time_schedule import TimeSchedule, next_fire
from haanim.engine.triggers.scheduled import ScheduledTrigger
from haanim.events import TimeEvent
from haanim.interfaces import Host

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


class TimeTrigger(ScheduledTrigger):
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

    @property
    def schedule(self) -> TimeSchedule:
        """The parsed expression and its day restrictions."""
        return self._schedule

    async def async_start(self) -> None:
        """Schedule the first fire after now; warn if a one-time date has already passed."""
        await super().async_start()
        if self._next is None and self._schedule.expression.recurrence == ONCE:
            # Not an error: the automation may simply have been started after the date
            self._logger.warning(
                "Automation '%s': '%s' of %s is in the past and will not fire",
                self.trigger_def.automation_id,
                self._schedule.expression.source,
                self.trigger_def.func_name,
            )

    def _next_after(self, instant: datetime) -> datetime | None:
        """Return the first fire after an instant."""
        return next_fire(self._schedule, instant, self.host.sun)

    def _event_for(self, due: datetime) -> TimeEvent:
        """Build the TimeEvent of a fire."""
        return self._event(TimeEvent, trigger_time=due)
