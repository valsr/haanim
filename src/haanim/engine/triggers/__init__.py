"""Trigger system for HAAnim.

This package provides the trigger classes and the manager that registers them:
state, time, interval, cron and event triggers. The decorators that attach a
trigger to a function are in ``haanim.engine.decorators``.
"""

from haanim.engine.triggers.base import BaseTrigger
from haanim.engine.triggers.cron_trigger import CronTrigger
from haanim.engine.triggers.event_trigger import EventTrigger
from haanim.engine.triggers.interval_trigger import IntervalTrigger
from haanim.engine.triggers.manager import TriggerManager
from haanim.engine.triggers.state_trigger import StateTrigger
from haanim.engine.triggers.time_trigger import TimeTrigger

__all__ = [
    "BaseTrigger",
    "CronTrigger",
    "EventTrigger",
    "IntervalTrigger",
    "StateTrigger",
    "TimeTrigger",
    "TriggerManager",
]
