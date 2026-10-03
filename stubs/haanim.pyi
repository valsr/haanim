"""Type stubs for the HAAnim virtual module.

This file provides type hints for the 'haanim' module that is available
to user automations. It allows IDE features like autocompletion,
type checking, and documentation to work properly.

Note: This module is virtual and provided by the HAAnim integration at runtime.
The actual implementations are in custom_components/haanim/engine/.

Auto-generated - do not edit manually
"""

# pyright: reportUnusedParameter=false
# pyright: reportUnnecessaryTypeIgnoreComment=false
# pyright: reportUnusedExpression=false
# pylint: disable=unused-argument,unnecessary-ellipsis

from datetime import datetime
from enum import Enum
from typing import Any, Callable, TypeVar, overload

from homeassistant.core import State

F = TypeVar("F", bound=Callable[..., Any])

# =============================================================================
# Enums
# =============================================================================

class ActionMode(Enum):
    """Action execution modes for concurrent action handling."""

    DROP: str  # Drop new execution if action already running
    QUEUE: str  # Queue new execution to run after current completes
    CANCEL: str  # Cancel current execution and start new one

# =============================================================================
# Errors
# =============================================================================

class HAAnimError(Exception):
    """Base class of all HAAnim errors."""

    lineno: int | None
    col_offset: int | None

class AutomationSyntaxError(HAAnimError):
    """Code or an expression cannot be parsed, or uses an unsupported construct."""

class AutomationSecurityError(HAAnimError):
    """A disallowed import, builtin or module member is used."""

class NonExistingAutomationError(HAAnimError):
    """The named automation does not exist."""

    automation_id: str

class AutomationNotLoadedError(HAAnimError):
    """The automation exists but is not loaded."""

    automation_id: str

class AutomationNotRunningError(HAAnimError):
    """The automation is not running."""

    automation_id: str

class AutomationAlreadyRunningError(HAAnimError):
    """The automation is already running."""

    automation_id: str

class AutomationDisabledError(HAAnimError):
    """The automation is disabled."""

    automation_id: str

class ActionNotFoundError(HAAnimError):
    """The action name is unknown, or the action is disabled."""

    automation_id: str
    action_name: str

class ActionDroppedError(HAAnimError):
    """The request was dropped (DROP mode, or a re-entrant call)."""

    automation_id: str
    action_name: str
    reason: str

class QueueFullError(HAAnimError):
    """The action's queue is full (QUEUE mode)."""

    automation_id: str
    action_name: str
    queue_size: int

class PoolExhaustedError(HAAnimError):
    """The concurrency limit is reached."""

    max_workers: int

class ActionTimeOutError(HAAnimError):
    """The action exceeded its timeout."""

    automation_id: str
    action_name: str
    timeout: float

class ActionCancelledError(HAAnimError):
    """The action was cancelled."""

    action_name: str
    reason: str

class NonExistingEntityError(HAAnimError):
    """A conversion was applied to an entity that does not exist."""

    entity_id: str

class NonExistingServiceError(HAAnimError):
    """A service that does not exist was called."""

    domain: str
    service: str

# =============================================================================
# Event Classes
# =============================================================================

class ActionEvent:
    """Base event class for action invocations."""

    call_time: datetime
    automation_id: str
    source: str  # 'trigger', 'manual', or 'automation'
    caller: str | None  # Automation ID if source == 'automation'

class TimeEvent(ActionEvent):
    """Event for time-based triggers."""

    trigger_time: datetime

class IntervalEvent(ActionEvent):
    """Event for interval-based triggers."""

    interval_seconds: float
    execution_count: int

class CronEvent(ActionEvent):
    """Event for cron-based triggers."""

    cron_expression: str
    trigger_time: datetime

class StateEvent(ActionEvent):
    """Event for state change triggers."""

    entity_id: str
    old_state: State | None
    new_state: State | None

class EventTriggerEvent(ActionEvent):
    """Event for Home Assistant event triggers."""

    event_type: str
    event_data: dict[str, Any]

class ManualEvent(ActionEvent):
    """Event for manual UI-triggered actions."""

    ...

class AutomationEvent(ActionEvent):
    """Event for automation-to-automation action calls."""

    ...

# =============================================================================
# HAAnim API Classes
# =============================================================================

class HAAnimServiceCall:
    """Result of a service call."""

    success: bool
    error: str | None
    error_code: str | None
    response_data: dict[str, Any] | None
    call_time: datetime
    complete_time: datetime | None

    def is_success(self) -> bool: ...
    def is_failure(self) -> bool: ...
    def get_response(self) -> dict[str, Any] | None: ...

class HAAnimServiceProxy:
    """Proxy for calling a Home Assistant service."""

    domain: str
    name: str
    description: str
    param_info: dict[str, Any]

    async def call(self, **params: Any) -> HAAnimServiceCall:
        """Call the service with parameters."""
        ...

class HAAnimAutomationProxy:
    """Proxy for accessing another automation."""

    id: str

    @property
    def state(self) -> str: ...
    @property
    def message(self) -> str: ...
    @property
    def file_path(self) -> str: ...
    @property
    def load_time(self) -> datetime | None: ...
    @property
    def run_time(self) -> datetime | None: ...
    @property
    def actions(self) -> list[str]: ...
    @property
    def last_action_time(self) -> datetime | None: ...
    @property
    def error_message(self) -> str | None: ...
    def is_running(self) -> bool: ...
    def is_enabled(self) -> bool: ...
    async def call(self, action_name: str, *args: Any, **kwargs: Any) -> Any: ...
    async def enable(self) -> None: ...
    async def disable(self) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def restart(self) -> None: ...

class EntityProxy:
    """Proxy for accessing entity states."""

    def __getattr__(self, entity_name: str) -> str:
        """Get entity state as string."""
        ...

class ServiceDomainProxy:
    """Proxy for accessing services in a domain."""

    def __getattr__(self, service_name: str) -> HAAnimServiceProxy:
        """Get service proxy."""
        ...

class HAAnim:
    """Main HAAnim API object (haa instance).

    Provides access to entities, services, automations, and storage.
    """

    @property
    def id(self) -> str:
        """Get current automation ID."""
        ...

    def __getattr__(self, domain: str) -> EntityProxy:
        """Access entities by domain.

        Examples:
            haa.sensor.temperature  # Get sensor.temperature state
            haa.light.living_room   # Get light.living_room state
            haa.service.light.turn_on(entity_id="light.bedroom", brightness=255)
        """
        ...

    @property
    def service(self) -> Any:
        """Access services.

        Example:
            await haa.service.light.turn_on(entity_id="light.bedroom")
        """
        ...

    def automation(self, automation_id: str) -> HAAnimAutomationProxy:
        """Get proxy for another automation."""
        ...

    def automations(self) -> list[HAAnimAutomationProxy]:
        """Get list of all automation proxies."""
        ...

    async def call(self, action_name: str, *args: Any, **kwargs: Any) -> Any:
        """Call an action in this automation."""
        ...

    async def enable(self) -> None:
        """Enable this automation."""
        ...

    async def disable(self) -> None:
        """Disable this automation."""
        ...

    async def stop(self) -> None:
        """Stop this automation (run shutdown if present)."""
        ...

    async def restart(self) -> None:
        """Restart this automation."""
        ...

    def set_message(self, message: str) -> None:
        """Set status message for this automation."""
        ...

    async def set_variable(self, key: str, value: str) -> None:
        """Store a persistent variable."""
        ...

    def get_variable(self, key: str, default: str | None = None) -> str | None:
        """Get a persistent variable."""
        ...

    async def unset_variable(self, key: str) -> None:
        """Remove a persistent variable."""
        ...

    async def clear_variables(self) -> None:
        """Clear all persistent variables."""
        ...

# Global haa instance (injected at runtime)
haa: HAAnim

# =============================================================================
# Decorators
# =============================================================================

@overload
def action(func: F) -> F:
    """Mark a function as an action (no arguments)."""
    ...

@overload
def action(
    name: str | None = None,
    *,
    description: str | None = None,
    execution_mode: ActionMode = ActionMode.DROP,
    timeout: float = 0,
    queue_size: int = 100,
) -> Callable[[F], F]:
    """Expose a function as an action with configuration."""
    ...

def action(
    name_or_func: str | F | None = None,
    *,
    description: str | None = None,
    execution_mode: ActionMode = ActionMode.DROP,
    timeout: float = 0,
    queue_size: int = 100,
) -> F | Callable[[F], F]:
    """Decorator to mark a function as an action.

    Args:
        name_or_func: Optional display name for the action, or the function if used without arguments.
        description: Optional description of what the action does.
        execution_mode: How to handle concurrent executions (DROP/QUEUE/CANCEL).
        timeout: Timeout in seconds (0 = no timeout).
        queue_size: Maximum queue size when execution_mode is QUEUE.

    Returns:
        Decorated function or decorator.

    Examples:
        @action
        async def turn_on_lights():
            pass

        @action("Evening Scene", description="Activates evening lighting")
        async def evening_action():
            pass

        @action(execution_mode=ActionMode.CANCEL)
        async def emergency_stop():
            pass
    """
    ...

def time_trigger(
    time_spec: str | list[str],
    *,
    offset: str | None = None,
) -> Callable[[F], F]:
    """Trigger at specific time(s).

    Args:
        time_spec: Time specification (e.g., "sunrise", "sunset", "12:00:00").
        offset: Optional time offset (e.g., "+00:30:00" for 30 minutes after).

    Returns:
        Decorator function.

    Examples:
        @time_trigger("sunrise")
        async def morning():
            pass

        @time_trigger("sunset", offset="-00:30:00")
        async def before_sunset():
            pass
    """
    ...

# Alias for time_trigger
time = time_trigger

def state_trigger(
    entity_id: str | list[str],
    *,
    condition: str | None = None,
    from_state: str | None = None,
    to_state: str | None = None,
) -> Callable[[F], F]:
    """Trigger on entity state change.

    Args:
        entity_id: Entity ID or list of entity IDs to monitor.
        condition: Optional expression condition (e.g., "new_state > 20").
        from_state: Optional previous state value.
        to_state: Optional new state value.

    Returns:
        Decorator function.

    Examples:
        @state_trigger("sensor.temperature")
        async def temp_changed():
            pass

        @state_trigger("sensor.temperature", condition="new_state > 25")
        async def temp_high():
            pass
    """
    ...

# Alias for state_trigger
state = state_trigger

def interval(
    interval_spec: str,
    *,
    delay: str | None = None,
) -> Callable[[F], F]:
    """Trigger at regular intervals.

    Args:
        interval_spec: Interval as "HH:MM:SS" or seconds.
        delay: Optional initial delay before first execution.

    Returns:
        Decorator function.

    Examples:
        @interval("00:05:00")  # Every 5 minutes
        async def check_status():
            pass

        @interval(60)  # Every 60 seconds
        async def fast_check():
            pass
    """
    ...

def cron(cron_expr: str) -> Callable[[F], F]:
    """Trigger using cron expression.

    Args:
        cron_expr: Cron expression (e.g., "0 * * * *" for top of every hour).

    Returns:
        Decorator function.

    Example:
        @cron("0 */2 * * *")  # Every 2 hours
        async def periodic_task():
            pass
    """
    ...

def event_trigger(
    event_type: str,
    *,
    event_data: dict[str, Any] | None = None,
) -> Callable[[F], F]:
    """Trigger on Home Assistant events.

    Args:
        event_type: Event type to listen for.
        event_data: Optional event data filter.

    Returns:
        Decorator function.

    Example:
        @event_trigger("custom_event")
        async def handle_event():
            pass
    """
    ...

# Alias for event_trigger
event = event_trigger

def time_active(
    time_spec: str | list[str],
    *,
    offset: str | None = None,
) -> Callable[[F], F]:
    """Constraint: only execute during specific times.

    Args:
        time_spec: Time specification.
        offset: Optional time offset.

    Returns:
        Decorator function.
    """
    ...

def state_active(
    entity_id: str,
    condition: str,
) -> Callable[[F], F]:
    """Constraint: only execute when entity state matches condition.

    Args:
        entity_id: Entity ID to check.
        condition: Expression condition.

    Returns:
        Decorator function.

    Example:
        @state_active("sensor.temperature", "state > 20")
        @time_trigger("12:00:00")
        async def noon_if_warm():
            pass
    """
    ...

def startup() -> Callable[[F], F]:
    """Mark function to run when automation is loaded.

    Returns:
        Decorator function.

    Example:
        @startup
        async def init():
            pass
    """
    ...

def shutdown() -> Callable[[F], F]:
    """Mark function to run when automation is unloaded.

    Returns:
        Decorator function.

    Example:
        @shutdown
        async def cleanup():
            pass
    """
    ...

# =============================================================================
# Utility Functions
# =============================================================================

def set_status(message: str | None) -> None:
    """Set a status message for the current automation.

    Args:
        message: Status message to display, or None to clear.
    """
    ...

async def sleep(seconds: float) -> None:
    """Sleep for the specified number of seconds.

    Args:
        seconds: Number of seconds to sleep.
    """
    ...

# =============================================================================
# Logging Functions
# =============================================================================

class Logger:
    """Logger interface for automations."""

    def debug(self, msg: str, *args: Any) -> None: ...
    def info(self, msg: str, *args: Any) -> None: ...
    def warning(self, msg: str, *args: Any) -> None: ...
    def error(self, msg: str, *args: Any) -> None: ...
    def critical(self, msg: str, *args: Any) -> None: ...
    def fatal(self, msg: str, *args: Any) -> None: ...

# Logging interface
logging: Logger
log: Logger  # Alias for the automation's logger

# Convenience logging functions
def log_debug(msg: str, *args: Any) -> None: ...
def log_info(msg: str, *args: Any) -> None: ...
def log_warning(msg: str, *args: Any) -> None: ...
def log_error(msg: str, *args: Any) -> None: ...
