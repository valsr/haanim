"""Trigger system for HAAnim.

This package provides the trigger system for HAAnim, including:
- State triggers: Fire when entity state conditions are met
- Time triggers: Fire at specific times (cron, sunrise/sunset, etc.)
- Event triggers: Fire when Home Assistant events occur

Each trigger type has its own module with both the trigger class and decorator.
"""

from haanim.engine.triggers.base import BaseTrigger, TriggerInfo
from haanim.engine.triggers.cron_trigger import CronTrigger, cron
from haanim.engine.triggers.event_trigger import EventTrigger, event_trigger
from haanim.engine.triggers.interval_trigger import IntervalTrigger, interval
from haanim.engine.triggers.manager import TriggerManager
from haanim.engine.triggers.state_trigger import StateTrigger, state_trigger
from haanim.engine.triggers.time_trigger import TimeTrigger, time_trigger

__all__ = [
    # Base
    "BaseTrigger",
    "TriggerInfo",
    # State
    "StateTrigger",
    "state_trigger",
    # Time
    "TimeTrigger",
    "time_trigger",
    # Interval
    "IntervalTrigger",
    "interval",
    # Cron
    "CronTrigger",
    "cron",
    # Event
    "EventTrigger",
    "event_trigger",
    # Manager
    "TriggerManager",
]
