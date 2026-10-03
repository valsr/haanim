"""Event data classes for HAAnim triggers.

This module defines event objects that contain trigger-specific data passed to actions.
Each trigger type has its own event class inheriting from ActionEvent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.core import State


@dataclass(frozen=True, kw_only=True)
class ActionEvent:
    """Base event class containing caller information.

    This class represents the context of an action call, including when it was called,
    the current automation ID, and information about what triggered the call.
    """

    call_time: datetime
    """Timestamp when the action was called."""

    automation_id: str
    """ID of the current automation."""

    source: str
    """How the action was invoked ('trigger', 'manual', or 'automation')."""

    caller: str | None = None
    """ID of the calling automation (only when source == 'automation')."""


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

    old_state: State | None
    """The previous state of the entity."""

    new_state: State | None
    """The new state of the entity."""


@dataclass(frozen=True, kw_only=True)
class EventTriggerEvent(ActionEvent):
    """Event data for Home Assistant event triggers.

    Contains information about Home Assistant events.
    """

    event_type: str
    """The type of event that was triggered."""

    event_data: dict[str, Any]
    """Data associated with the event."""


@dataclass(frozen=True, kw_only=True)
class ManualEvent(ActionEvent):
    """Event data for manually triggered actions.

    Represents an action called manually from the UI or other manual trigger.
    This class has predefined source and caller values.
    """

    source: str = "manual"  # type: ignore[assignment]
    caller: str | None = None  # type: ignore[assignment]


@dataclass(frozen=True, kw_only=True)
class AutomationEvent(ActionEvent):
    """Event data for automation-to-automation calls.

    Represents an action called by another automation.
    This class has predefined source value.
    """

    source: str = "automation"  # type: ignore[assignment]


def create_manual_event(call_time: datetime, automation_id: str) -> ManualEvent:
    """Create a manual event.

    Args:
        call_time: When the action was called.
        automation_id: ID of the current automation.

    Returns:
        ManualEvent instance.
    """
    return ManualEvent(
        call_time=call_time,
        automation_id=automation_id,
        source="manual",
        caller=None,
    )


def create_automation_event(call_time: datetime, automation_id: str, caller: str) -> AutomationEvent:
    """Create an automation-to-automation call event.

    Args:
        call_time: When the action was called.
        automation_id: ID of the current automation.
        caller: ID of the calling automation.

    Returns:
        AutomationEvent instance.
    """
    return AutomationEvent(
        call_time=call_time,
        automation_id=automation_id,
        source="automation",
        caller=caller,
    )
