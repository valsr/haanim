"""Trigger system for HAAnim.

This package provides the trigger system for HAAnim, including:
- State triggers: Fire when entity state conditions are met
- Time triggers: Fire at specific times (cron, sunrise/sunset, etc.)
- Event triggers: Fire when Home Assistant events occur

Each trigger type has its own module with both the trigger class and decorator.
"""

from __future__ import annotations

# Base classes and common types
from custom_components.haanim.engine.triggers.base import (
    BaseTrigger,
    TriggerInfo,
)

# State trigger
from custom_components.haanim.engine.triggers.state_trigger import (
    StateTrigger,
    state_trigger,
    state_active,
)

# Time trigger
from custom_components.haanim.engine.triggers.time_trigger import (
    TimeTrigger,
    time_trigger,
    time_active,
)

# Event trigger
from custom_components.haanim.engine.triggers.event_trigger import (
    EventTrigger,
    event_trigger,
)

# Trigger manager
from custom_components.haanim.engine.triggers.manager import TriggerManager

__all__ = [
    # Base
    "BaseTrigger",
    "TriggerInfo",
    # State
    "StateTrigger",
    "state_trigger",
    "state_active",
    # Time
    "TimeTrigger",
    "time_trigger",
    "time_active",
    # Event
    "EventTrigger",
    "event_trigger",
    # Manager
    "TriggerManager",
]
