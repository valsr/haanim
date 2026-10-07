"""Event data classes for HAAnim triggers.

This module defines event objects that contain trigger-specific data passed to actions.
Each trigger type has its own event class inheriting from ActionEvent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from haanim.types import StateVal

SOURCE_TRIGGER = "trigger"
SOURCE_MANUAL = "manual"
SOURCE_AUTOMATION = "automation"


@dataclass(frozen=True, kw_only=True)
class ActionEvent:
    """What an action is told about the call: when, by whom, and with what data.

    Every event type derives from this class.
    """

    call_time: datetime
    """Timestamp when the action was called."""

    automation_id: str
    """ID of the automation the action belongs to."""

    source: str
    """How the action was invoked: ``"trigger"``, ``"manual"`` or ``"automation"``."""

    caller: str | None = None
    """ID of the calling automation; only when ``source == "automation"``."""

    data: dict[str, Any] = field(default_factory=dict)
    """Arguments passed by the caller; empty for trigger-fired calls."""


@dataclass(frozen=True, kw_only=True)
class TimeEvent(ActionEvent):
    """Event data for time-based triggers.

    Contains information about when a time trigger fired.
    """

    trigger_time: datetime
    """The time that triggered this event."""


@dataclass(frozen=True, kw_only=True)
class IntervalEvent(ActionEvent):
    """Event data for interval-based triggers.

    Contains information about interval trigger execution.
    """

    interval_seconds: float
    """The interval duration in seconds."""

    execution_count: int
    """Number of times this interval trigger has executed."""


@dataclass(frozen=True, kw_only=True)
class CronEvent(ActionEvent):
    """Event data for cron-based triggers.

    Contains information about cron trigger execution.
    """

    cron_expression: str
    """The cron expression that triggered this event."""

    trigger_time: datetime
    """The time that matched the cron expression."""


@dataclass(frozen=True, kw_only=True)
class StateEvent(ActionEvent):
    """Event data for state change triggers.

    Contains information about the entity state change that triggered the action.
    """

    entity_id: str
    """The entity ID that triggered the state change."""

    old_state: StateVal | None
    """The previous state of the entity."""

    new_state: StateVal | None
    """The new state of the entity."""


@dataclass(frozen=True, kw_only=True)
class EventTriggerEvent(ActionEvent):
    """Event data for event triggers.

    Contains information about the event that was fired.
    """

    event_type: str
    """The type of event that was triggered."""

    event_data: dict[str, Any]
    """Data associated with the event."""

    time_fired: datetime
    """When the host fired the event."""

    user_id: str | None = None
    """The user that caused the event, if any."""


@dataclass(frozen=True, kw_only=True)
class ManualEvent(ActionEvent):
    """Event for an action run by hand, from the GUI or a service call.

    Also what a trigger function receives when it is run by hand.
    """

    source: str = SOURCE_MANUAL


@dataclass(frozen=True, kw_only=True)
class AutomationEvent(ActionEvent):
    """Event for an action called by an automation; ``caller`` names it.

    Also what a trigger function receives when an automation calls it.
    """

    source: str = SOURCE_AUTOMATION
