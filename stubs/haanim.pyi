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
    data: dict[str, Any]  # Arguments passed by the caller; empty for trigger-fired calls

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
    time_fired: datetime
    user_id: str | None

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

    domain: str
    service: str
    success: bool
    error: str | None
    error_code: str | None
    response_data: dict[str, Any]
    call_time: datetime
    complete_time: datetime

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

class HAAnimEntity:
    """A snapshot of an entity: its state, attributes and timestamps.

    Comparing the object compares its state with the conversion rules of
    trigger expressions.
    """

    @property
    def entity_id(self) -> str:
        """Full entity ID, such as 'sensor.temperature'."""
        ...

    @property
    def exists(self) -> bool:
        """False if Home Assistant has no such entity."""
        ...

    @property
    def state(self) -> str | None:
        """Raw state string, None if the entity does not exist."""
        ...

    @property
    def attributes(self) -> dict[str, Any]:
        """All attributes (empty if the entity does not exist)."""
        ...

    @property
    def last_changed(self) -> datetime | None:
        """When the state last changed."""
        ...

    @property
    def last_updated(self) -> datetime | None:
        """When the state or an attribute last changed."""
        ...

    def __getitem__(self, attribute: str) -> Any:
        """Single attribute, None if missing."""
        ...

    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __lt__(self, other: Any) -> bool: ...
    def __le__(self, other: Any) -> bool: ...
    def __gt__(self, other: Any) -> bool: ...
    def __ge__(self, other: Any) -> bool: ...
    def __contains__(self, item: Any) -> bool: ...
    def __bool__(self) -> bool: ...
    def __float__(self) -> float: ...
    def __int__(self) -> int: ...
    def upper(self) -> str: ...
    def lower(self) -> str: ...
    def strip(self, chars: str | None = None) -> str: ...
    def startswith(self, prefix: str | tuple[str, ...]) -> bool: ...
    def endswith(self, suffix: str | tuple[str, ...]) -> bool: ...
    def split(self, sep: str | None = None, maxsplit: int = -1) -> list[str]: ...

class EntityDomain:
    """The entities of one domain: haa.entity.<domain>."""

    def __getattr__(self, name: str) -> HAAnimEntity:
        """Read the entity <domain>.<name> as it is now."""
        ...

class EntityNamespace:
    """All entities: haa.entity.<domain>.<name> and haa.entity["<domain>.<name>"]."""

    def __getattr__(self, domain: str) -> EntityDomain:
        """The entities of a domain."""
        ...

    def __getitem__(self, entity_id: str) -> HAAnimEntity:
        """Read an entity by its ID."""
        ...

class ServiceDomainProxy:
    """Proxy for accessing services in a domain."""

    def __getattr__(self, service_name: str) -> HAAnimServiceProxy:
        """Get service proxy."""
        ...

class HAAnimCard:
    """The content of the automation's card (haa.card): an ordered list of blocks."""

    def text(self, id: str, markdown: str) -> None:
        """Show markdown text (at most 10 000 characters)."""
        ...

    def image(self, id: str, asset: str | None = None, url: str | None = None, alt: str = "") -> None:
        """Show an image from assets/ or from a URL (exactly one of the two)."""
        ...

    def value(self, id: str, label: str, value: str | int | float | bool, unit: str = "") -> None:
        """Show a labelled value."""
        ...

    def entity(self, id: str, entity_id: str) -> None:
        """Show the live state of a Home Assistant entity."""
        ...

    def button(self, id: str, label: str, action: str, confirm: str | None = None, **data: Any) -> None:
        """Show a button that runs one of the automation's actions."""
        ...

    def remove(self, id: str) -> None:
        """Remove a block; does nothing if the ID is not present."""
        ...

    def clear(self) -> None:
        """Remove all blocks."""
        ...

    @property
    def blocks(self) -> list[dict[str, Any]]:
        """Read-only list of the current blocks."""
        ...

class HAAnim:
    """Main HAAnim API object (haa instance).

    Provides access to entities, services, automations, and storage.
    """

    @property
    def id(self) -> str:
        """Get current automation ID."""
        ...

    def now(self) -> datetime:
        """Get the current time, timezone-aware, from the clock that drives triggers and timeouts."""
        ...

    @property
    def entity(self) -> EntityNamespace:
        """Access entities.

        Examples:
            haa.entity.sensor.temperature        # HAAnimEntity
            haa.entity["sensor.3d_printer"]      # by entity ID string
            haa.entity.light.living_room["brightness"]
        """
        ...

    def state(self, entity_id: str) -> str | None:
        """Get the raw state string of an entity, None if it does not exist."""
        ...

    async def sleep(self, duration: str | float) -> None:
        """Suspend the current action: seconds, or "HH:MM:SS"."""
        ...

    async def wait_for(self, expr: str, timeout: str | float | None = None) -> bool:
        """Suspend until a state expression is true; False if the timeout passes first."""
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

    def set_variable(self, key: str, value: Any) -> None:
        """Store a persistent variable: any JSON value. Raises TypeError for anything else."""
        ...

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Get a persistent variable, or the default if it is not set."""
        ...

    def unset_variable(self, key: str) -> None:
        """Remove a persistent variable; does nothing if it is not set."""
        ...

    def clear_variables(self) -> None:
        """Clear all persistent variables."""
        ...

    @property
    def card(self) -> HAAnimCard:
        """The content of the automation's card."""
        ...

    async def read_asset(self, name: str, text: bool = False) -> bytes | str:
        """Read a file from the automation's assets/ folder, as bytes or as UTF-8 text."""
        ...

    def asset_url(self, name: str, expires: float | None = None) -> str:
        """URL path of an asset; with expires (seconds) it works without login until then."""
        ...

# Global haa instance (injected at runtime)
haa: HAAnim

hass: Any
"""The running Home Assistant instance. Also available as ``import hass``."""

# =============================================================================
# Decorators
# =============================================================================

@overload
def action(func: F, /) -> F: ...
@overload
def action(
    *,
    name: str | None = None,
    aliases: list[str] | tuple[str, ...] | None = None,
    description: str | None = None,
    execution_mode: ActionMode = ActionMode.DROP,
    timeout: float | None = None,
    disabled: bool = False,
) -> Callable[[F], F]:
    """Make a function an action, or configure the action of a trigger function.

    A function with a trigger decorator is an action without ``@action``. The
    order of ``@action`` and the trigger decorators does not matter.

    Args:
        name: The action's name. The function name if omitted.
        aliases: Additional names for the action.
        description: What the action does.
        execution_mode: How concurrent calls are handled.
        timeout: Time limit in seconds. The default timeout if omitted.
        disabled: List the action but do not let it be called, and do not register its triggers.
    """
    ...

def on_time(
    expr: str,
    *,
    day_of_week: str | int | None = None,
    day_of_month: str | int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    when: str | None = None,
    when_not: str | None = None,
) -> Callable[[F], F]:
    """Call the function at a date and/or time, such as ``"09:00"`` or ``"sunset - 30 minutes"``."""
    ...

def on_interval(
    interval: str | float,
    *,
    delay: str | float | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    day_of_week: str | int | None = None,
    when: str | None = None,
    when_not: str | None = None,
) -> Callable[[F], F]:
    """Call the function repeatedly, a fixed time apart: seconds, or ``"HH:MM:SS"``."""
    ...

def on_cron(
    expr: str,
    *,
    start_time: str | None = None,
    end_time: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    day_of_week: str | int | None = None,
    when: str | None = None,
    when_not: str | None = None,
) -> Callable[[F], F]:
    """Call the function when a cron expression matches."""
    ...

def on_event(
    event_type: str,
    *,
    data: dict[str, Any] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    day_of_week: str | int | None = None,
    when: str | None = None,
    when_not: str | None = None,
) -> Callable[[F], F]:
    """Call the function when an event of a type is fired, optionally only with matching data."""
    ...

def on_state(
    expr: str,
    *,
    every_change: bool = False,
    hold: str | float | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    day_of_week: str | int | None = None,
    when: str | None = None,
    when_not: str | None = None,
) -> Callable[[F], F]:
    """Call the function when a state expression becomes true."""
    ...

def startup(func: F) -> F:
    """Mark the function as the automation's startup handler. An automation has at most one."""
    ...

def shutdown(func: F) -> F:
    """Mark the function as the automation's shutdown handler. An automation has at most one."""
    ...

# =============================================================================
# Status and logging
# =============================================================================

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
