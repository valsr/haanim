"""Trigger manager: the triggers of the running automations.

Each trigger kind is a class that watches for its own condition (a state
change, an instant on the clock, an event) and requests its action through the
dispatcher when it fires. The manager creates the trigger for a definition
when an automation starts and stops it when the automation stops.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from haanim import const
from haanim.engine.action_dispatcher import ActionDispatcher
from haanim.engine.triggers.base import BaseTrigger
from haanim.engine.triggers.cron_trigger import CronTrigger
from haanim.engine.triggers.event_trigger import EventTrigger
from haanim.engine.triggers.interval_trigger import IntervalTrigger
from haanim.engine.triggers.state_trigger import StateTrigger
from haanim.engine.triggers.time_trigger import TimeTrigger
from haanim.interfaces import Host

if TYPE_CHECKING:
    from haanim.engine.automation_context import TriggerDefinition

_LOGGER = logging.getLogger(__name__)

# The class of each trigger kind
TRIGGER_CLASSES: dict[str, type[BaseTrigger]] = {
    const.TRIGGER_CRON: CronTrigger,
    const.TRIGGER_EVENT: EventTrigger,
    const.TRIGGER_INTERVAL: IntervalTrigger,
    const.TRIGGER_STATE: StateTrigger,
    const.TRIGGER_TIME: TimeTrigger,
}


class TriggerManager:
    """Creates, starts and stops the triggers of running automations."""

    def __init__(self, host: Host, dispatcher: ActionDispatcher) -> None:
        """Initialize the trigger manager.

        Args:
            host: The host the engine runs in.
            dispatcher: Where the triggered actions are requested.
        """
        self.host = host
        self.dispatcher = dispatcher
        self._triggers: dict[str, BaseTrigger] = {}

    async def async_teardown(self) -> None:
        """Stop every trigger."""
        for trigger in self._triggers.values():
            await trigger.async_stop()
        self._triggers.clear()

    async def register_trigger(self, trigger_def: TriggerDefinition) -> str:
        """Create the trigger for a definition and start it.

        The trigger is active from now on: an interval is counted from this
        moment and a state trigger takes its baseline now. This is called when
        an automation starts, after its ``@startup`` has completed.

        Args:
            trigger_def: The trigger definition. Its constraints are those of its decorator.

        Returns:
            Unique ID for the registered trigger.

        Raises:
            ValueError: If the trigger kind is unknown or the definition cannot be read.
        """
        trigger_class = TRIGGER_CLASSES.get(trigger_def.trigger_type)
        if trigger_class is None:
            raise ValueError(f"Unknown trigger type: {trigger_def.trigger_type}")

        trigger_id = self._get_trigger_id(trigger_def)
        trigger = trigger_class(self.host, trigger_def, self.dispatcher)
        self._triggers[trigger_id] = trigger
        try:
            await trigger.async_start()
        except BaseException:
            del self._triggers[trigger_id]
            raise

        _LOGGER.debug("Registered trigger: %s", trigger_id)
        return trigger_id

    def _get_trigger_id(self, trigger_def: TriggerDefinition) -> str:
        """Generate a unique trigger ID.

        Args:
            trigger_def: The trigger definition.

        Returns:
            Unique trigger ID.
        """
        prefix = f"{trigger_def.automation_id}.{trigger_def.func_name}."
        ids = [int(key.split(".")[-1]) for key in self._triggers if key.startswith(prefix)]
        if not ids:
            return prefix + "0"
        return prefix + str(max(ids) + 1)

    async def unregister_trigger(self, trigger_id: str) -> bool:
        """Stop a trigger and forget it.

        Args:
            trigger_id: The trigger ID.

        Returns:
            True if trigger was unregistered.
        """
        trigger = self._triggers.pop(trigger_id, None)
        if trigger is None:
            return False
        await trigger.async_stop()
        _LOGGER.debug("Unregistered trigger: %s", trigger_id)
        return True

    async def unregister_automation_triggers(self, automation_id: str) -> int:
        """Stop every trigger of an automation, discarding pending timers and holds.

        Args:
            automation_id: ID of the automation.

        Returns:
            Number of triggers unregistered.
        """
        to_remove = [
            trigger_id for trigger_id in self._triggers if trigger_id.startswith(f"{automation_id}.")
        ]
        for trigger_id in to_remove:
            await self.unregister_trigger(trigger_id)
        return len(to_remove)

    def get_trigger(self, trigger_id: str) -> BaseTrigger | None:
        """Return a registered trigger, or None if there is none with that ID."""
        return self._triggers.get(trigger_id)

    def get_trigger_ids(self, automation_id: str | None = None) -> list[str]:
        """Return the IDs of the registered triggers, optionally of one automation only."""
        return [
            trigger_id
            for trigger_id in self._triggers
            if automation_id is None or trigger_id.startswith(f"{automation_id}.")
        ]

    def get_trigger_count(self) -> int:
        """Get the number of registered triggers.

        Returns:
            Number of triggers.
        """
        return len(self._triggers)
