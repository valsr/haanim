"""Cron trigger: fires when a cron expression matches.

See "Cron Trigger" in the design.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from haanim.engine.cron_schedule import next_cron_fire, validate_cron
from haanim.engine.triggers.scheduled import ScheduledTrigger
from haanim.events import CronEvent
from haanim.interfaces import Host

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition


class CronTrigger(ScheduledTrigger):
    """Fires an action on a cron schedule."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize cron trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: Trigger definition. Its expression is the cron expression.
            dispatcher: Where the action is requested when the trigger fires.

        Raises:
            ValueError: If the expression is not a five-field cron expression.
        """
        super().__init__(host, trigger_def, dispatcher)
        try:
            self._cron_expr = validate_cron(trigger_def.trigger_expr)
        except ValueError as err:
            raise ValueError(f"Invalid cron expression: {err}") from None

    @property
    def cron_expression(self) -> str:
        """The cron expression."""
        return self._cron_expr

    def _next_after(self, instant: datetime) -> datetime | None:
        """Return the first match after an instant."""
        return next_cron_fire(self._cron_expr, instant)

    def _event_for(self, due: datetime) -> CronEvent:
        """Build the CronEvent of a fire."""
        return self._event(CronEvent, cron_expression=self._cron_expr, trigger_time=due)
