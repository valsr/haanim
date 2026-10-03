"""Decorator definitions for HAAnim automations.

This module provides decorators for defining actions, lifecycle hooks, and triggers
in HAAnim automations.

Decorator Types:
- Actions: @action (from this module)
- Lifecycle: @startup, @shutdown (from this module)
- Triggers: @state, @time, @interval, @cron, @event (from engine/triggers/)
- Constraints: @state_active, @time_active (from engine/constraints/)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar
from collections.abc import Callable

from custom_components.haanim.const import ActionMode

_LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# Metadata Classes
# =============================================================================


@dataclass
class ActionInfo:
    """Information about an action decorated function.

    Args:
        name: Display name for the action.
        description: Optional description of what the action does.
        func: The decorated function.
        execution_mode: How to handle concurrent calls (DROP, QUEUE, CANCEL).
        timeout: Timeout in seconds (0 = no timeout).
        queue_size: Maximum queue size for QUEUE mode.
    """

    name: str | None = None
    description: str | None = None
    func: Callable[..., Any] | None = None
    execution_mode: ActionMode = ActionMode.DROP
    timeout: float = 0
    queue_size: int = 100


@dataclass
class FunctionMetadata:
    """Metadata collected from decorators on a function.

    Args:
        custom_name: Custom name from @action("name") decorator.
        is_marked_as_action: Whether function is explicitly marked with @action decorator.
        action_info: Information about the action (name, description, queue settings).
        triggers: List of triggers attached to this function. Functions with triggers
            are automatically callable as actions, even without @action decorator.
        constraints: List of constraints (time_active, state_active).
        is_startup: Whether function is a startup handler (@startup).
        is_shutdown: Whether function is a shutdown handler (@shutdown).
    """

    custom_name: str | None = None
    is_marked_as_action: bool = False
    action_info: ActionInfo | None = None
    triggers: list[Any] = field(default_factory=list)  # TriggerInfo from triggers.base
    constraints: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    is_startup: bool = False
    is_shutdown: bool = False


# Attribute name for storing metadata on decorated functions
METADATA_ATTRIBUTE = "_haanim_metadata"


def _get_or_create_metadata(func: Callable[..., Any]) -> FunctionMetadata:
    """Get or create FunctionMetadata for a function.

    Args:
        func: The function to get/create metadata for.

    Returns:
        The FunctionMetadata instance attached to the function.
    """
    if not hasattr(func, METADATA_ATTRIBUTE):
        setattr(func, METADATA_ATTRIBUTE, FunctionMetadata())
    return getattr(func, METADATA_ATTRIBUTE)


def get_metadata(func: Callable[..., Any]) -> FunctionMetadata | None:
    """Get the metadata from a decorated function.

    Args:
        func: The function to get metadata from.

    Returns:
        The FunctionMetadata if present, None otherwise.
    """
    return getattr(func, METADATA_ATTRIBUTE, None)


def has_metadata(func: Callable[..., Any]) -> bool:
    """Check if a function has HAAnim metadata.

    Args:
        func: The function to check.

    Returns:
        True if the function has HAAnim metadata.
    """
    return hasattr(func, METADATA_ATTRIBUTE)


def action(
    name_or_func: str | F | None = None,
    *,
    description: str | None = None,
    execution_mode: ActionMode = ActionMode.DROP,
    timeout: float = 0,
    queue_size: int = 100,
) -> F | Callable[[F], F]:
    """Decorator to mark a function as an action and add metadata.

    Functions with triggers are automatically actions and callable from the UI.
    The @action decorator is optional but allows you to:
    - Provide a custom display name and description
    - Control execution mode (DROP, QUEUE, CANCEL)
    - Set timeout
    - Configure queue size (for QUEUE mode)

    Note: Functions with only triggers (no @action) are still callable from the UI
    but use default settings (function name as display name, DROP mode).

    Args:
        name_or_func: Optional display name for the action, or the function if
            used without arguments.
        description: Optional description of what the action does.
        execution_mode: How to handle concurrent calls (DROP, QUEUE, CANCEL).
        timeout: Action timeout in seconds (0 = no timeout).
        queue_size: Maximum queue size for QUEUE mode (default 100).

    Returns:
        Decorated function or decorator.

    Example:
        # Triggered function (automatically an action)
        @time("sunset")
        def evening_lights():
            pass

        # Manual action only (no triggers)
        @action
        def turn_on_lights():
            pass

        # Triggered with custom metadata
        @action("Evening Scene", description="Activates evening lighting")
        @time("sunset")
        def evening_action():
            pass

        # Action with execution mode
        @action(execution_mode=ActionMode.QUEUE)
        def queued_action():
            pass

        # Action with timeout
        @action(timeout=30)
        async def timed_action():
            await long_operation()
    """
    # Handle @action without parentheses
    if callable(name_or_func):
        func = name_or_func
        metadata = _get_or_create_metadata(func)
        metadata.is_marked_as_action = True
        metadata.action_info = ActionInfo(func=func)
        return func

    # Handle @action() or @action("name") or @action(description="...")
    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.is_marked_as_action = True
        metadata.action_info = ActionInfo(
            name=name_or_func if isinstance(name_or_func, str) else None,
            description=description,
            func=func,
            execution_mode=execution_mode,
            timeout=timeout,
            queue_size=queue_size,
        )
        # Also set custom_name for consistency
        if isinstance(name_or_func, str):
            metadata.custom_name = name_or_func
        return func

    return decorator


# =============================================================================
# Lifecycle Decorators
# =============================================================================


def startup(func: F) -> F:
    """Decorator to mark a function as a startup handler.

    Functions decorated with @startup are called once when the automation is loaded
    and Home Assistant has started. Only one startup handler per automation is allowed.
    If multiple are defined, only the last one will be executed.

    Startup handlers:
    - Run after the automation is fully loaded and parsed
    - Are executed through the action worker pool (count toward concurrency limits)
    - Should complete quickly to not delay loading of other automations
    - Cannot be triggered manually from the UI

    Args:
        func: The function to mark as a startup handler.

    Returns:
        The decorated function.

    Example:
        @startup
        async def on_startup():
            log_info("Automation initialized!")
            # Perform one-time setup tasks

        @startup
        def sync_startup():
            # Sync functions are also supported
            pass
    """
    metadata = _get_or_create_metadata(func)
    metadata.is_startup = True
    return func


def shutdown(func: F) -> F:
    """Decorator to mark a function as a shutdown handler.

    Functions decorated with @shutdown are called when the automation is being unloaded,
    reloaded, or when Home Assistant is stopping. Only one shutdown handler per
    automation is allowed.

    Shutdown handlers:
    - Run when the automation is unloaded, reloaded, or HA stops
    - Have a strict timeout (200ms by default) - must complete quickly
    - Will be forcefully terminated if they exceed the timeout
    - If an action is running when shutdown is requested, it will be cancelled first
    - Cannot be triggered manually from the UI
    - Are executed through the action worker pool

    Args:
        func: The function to mark as a shutdown handler.

    Returns:
        The decorated function.

    Example:
        @shutdown
        async def on_shutdown():
            log_info("Automation shutting down...")
            # Clean up resources, save state, etc.
            # Keep it fast! Max 200ms allowed

        @shutdown
        def sync_shutdown():
            # Sync functions are also supported
            pass
    """
    metadata = _get_or_create_metadata(func)
    metadata.is_shutdown = True
    return func


# =============================================================================
# Re-export Trigger Decorators from engine/triggers/
# =============================================================================

# Import trigger decorators from their respective modules
# These are the primary interface for user automations
from custom_components.haanim.engine.triggers.base import TriggerInfo  # pylint: disable=wrong-import-order
from custom_components.haanim.engine.triggers.state_trigger import (
    state_trigger,
)  # pylint: disable=wrong-import-order
from custom_components.haanim.engine.triggers.time_trigger import (
    time_trigger,
)  # pylint: disable=wrong-import-order
from custom_components.haanim.engine.triggers.interval_trigger import (
    interval,
)  # pylint: disable=wrong-import-order
from custom_components.haanim.engine.triggers.cron_trigger import (
    cron,
)  # pylint: disable=wrong-import-order
from custom_components.haanim.engine.triggers.event_trigger import (
    event_trigger,
)  # pylint: disable=wrong-import-order

# Import constraint decorators from constraints module
from custom_components.haanim.engine.constraints import (
    state_active,
    time_active,
)  # pylint: disable=wrong-import-order

# Create aliases for more intuitive naming in automations
time = time_trigger
state = state_trigger
event = event_trigger

# Export all decorators for use in automations
__all__ = [
    # Action decorators
    "action",
    "startup",
    "shutdown",
    # Trigger decorators (re-exported from engine/triggers/)
    "state_trigger",
    "state",
    "time_trigger",
    "time",
    "interval",
    "cron",
    "event_trigger",
    "event",
    # Constraint decorators (re-exported from engine/triggers/)
    "state_active",
    "time_active",
    # Metadata utilities
    "get_metadata",
    "has_metadata",
    "_get_or_create_metadata",
    # Metadata classes
    "FunctionMetadata",
    "TriggerInfo",
    "ActionInfo",
    "METADATA_ATTRIBUTE",
]
