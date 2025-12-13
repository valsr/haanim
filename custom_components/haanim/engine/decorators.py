"""Decorators for HAAnim automation scripts.

This module provides decorators that users can use in their automation scripts to define triggers, actions,
and metadata. Trigger-specific decorators are implemented in their own modules under engine/triggers/ and
re-exported here for convenience.

Decorator Categories:
- Triggers: @state_trigger, @time_trigger, @event_trigger (from engine/triggers/)
- Constraints: @state_active, @time_active (from engine/triggers/)
- Actions: @action, @service, @startup, @shutdown (defined here)
- Metadata: FunctionMetadata, TriggerInfo, ActionInfo (defined here)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TypeVar
from collections.abc import Callable

_LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# =============================================================================
# Metadata Classes
# =============================================================================


@dataclass
class ActionInfo:
    """Information about an action (act/scene) decorated function.

    Args:
        name: Display name for the action.
        description: Optional description of what the action does.
        func: The decorated function.
        queue: Whether to queue the action if the script is busy.
        queue_timeout: Timeout in seconds for queued actions (0 = wait indefinitely).
        preempt: Whether to cancel any running action and run this one immediately.
    """

    name: str | None = None
    description: str | None = None
    func: Callable[..., Any] | None = None
    queue: bool = False
    queue_timeout: float = 10.0
    preempt: bool = False


@dataclass
class FunctionMetadata:
    """Metadata collected from decorators on a function.

    Args:
        custom_name: Custom name from @action("name") decorator.
        is_action: Whether function is marked as an action (@action).
        action_info: Information about the action if is_action is True.
        triggers: List of triggers attached to this function.
        constraints: List of constraints (time_active, state_active).
        is_service: Whether function should be exposed as HA service.
        service_schema: Schema for service parameters if is_service.
        is_startup: Whether function is a startup handler (@startup).
        is_shutdown: Whether function is a shutdown handler (@shutdown).
    """

    custom_name: str | None = None
    is_action: bool = False
    action_info: ActionInfo | None = None
    triggers: list[Any] = field(default_factory=list)  # TriggerInfo from triggers.base
    constraints: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    is_service: bool = False
    service_schema: dict[str, Any] | None = None
    is_startup: bool = False
    is_shutdown: bool = False


# Attribute name for storing metadata on decorated functions
METADATA_ATTR = "_haanim_metadata"


def _get_or_create_metadata(func: Callable[..., Any]) -> FunctionMetadata:
    """Get or create FunctionMetadata for a function.

    Args:
        func: The function to get/create metadata for.

    Returns:
        The FunctionMetadata instance attached to the function.
    """
    if not hasattr(func, METADATA_ATTR):
        setattr(func, METADATA_ATTR, FunctionMetadata())
    return getattr(func, METADATA_ATTR)


def get_metadata(func: Callable[..., Any]) -> FunctionMetadata | None:
    """Get the metadata from a decorated function.

    Args:
        func: The function to get metadata from.

    Returns:
        The FunctionMetadata if present, None otherwise.
    """
    return getattr(func, METADATA_ATTR, None)


def has_metadata(func: Callable[..., Any]) -> bool:
    """Check if a function has HAAnim metadata.

    Args:
        func: The function to check.

    Returns:
        True if the function has HAAnim metadata.
    """
    return hasattr(func, METADATA_ATTR)


def action(
    name_or_func: str | F | None = None,
    *,
    description: str | None = None,
    queue: bool = False,
    queue_timeout: float = 10.0,
    preempt: bool = False,
) -> F | Callable[[F], F]:
    """Decorator to mark a function as an action, manually executable from the UI.

    When a function is decorated with @action, it becomes available in the HAAnim
    UI for manual execution. Manual execution bypasses all trigger constraints.

    Args:
        name_or_func: Optional display name for the action, or the function if
            used without arguments.
        description: Optional description of what the action does.
        queue: If True, queue the action when the script is busy instead of
            raising an error. The action will run after the current action completes.
        queue_timeout: Maximum time in seconds to wait in queue before the action
            is discarded. Use 0 to wait indefinitely. Default is 10 seconds.
        preempt: If True, cancel any currently running action and run this one
            immediately. Takes precedence over queue. Use with caution as it
            may leave the system in an unexpected state.

    Returns:
        Decorated function or decorator.

    Example:
        @action
        def turn_on_lights():
            pass

        @action("Morning Routine")
        def morning_routine():
            pass

        @action("Evening Action", description="Activates evening lighting")
        @time_trigger("sunset")
        def evening_action():
            pass

        @action("Queued Action", queue=True, queue_timeout=30)
        def my_queued_action():
            # This action will wait up to 30 seconds if the script is busy
            pass

        @action(queue=True, queue_timeout=0)
        def wait_forever_action():
            # This action will wait indefinitely in the queue
            pass

        @action(preempt=True)
        def emergency_stop():
            # This action will cancel any running action and execute immediately
            pass
    """
    # Handle @action without parentheses
    if callable(name_or_func):
        func = name_or_func
        metadata = _get_or_create_metadata(func)
        metadata.is_action = True
        metadata.action_info = ActionInfo(func=func)
        return func

    # Handle @action() or @action("name") or @action(description="...")
    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.is_action = True
        metadata.action_info = ActionInfo(
            name=name_or_func if isinstance(name_or_func, str) else None,
            description=description,
            func=func,
            queue=queue,
            queue_timeout=queue_timeout,
            preempt=preempt,
        )
        # Also set custom_name for consistency
        if isinstance(name_or_func, str):
            metadata.custom_name = name_or_func
        return func

    return decorator


# =============================================================================
# Lifecycle Decorators
# =============================================================================


def service(
    name_or_func: str | F | None = None,
    *,
    schema: dict[str, Any] | None = None,
    description: str | None = None,
) -> F | Callable[[F], F]:
    """Decorator to expose a function as a Home Assistant service.

    Args:
        name_or_func: Optional service name, or the function if used without arguments.
        schema: Optional voluptuous schema for service parameters.
        description: Optional description for the service.

    Returns:
        Decorated function or decorator.

    Example:
        @service
        def my_custom_service(entity_id: str):
            pass

        @service("custom_action", description="Does something custom")
        def custom_action(target: str, value: int):
            pass
    """
    # Handle @service without parentheses
    if callable(name_or_func):
        func = name_or_func
        metadata = _get_or_create_metadata(func)
        metadata.is_service = True
        return func

    # Handle @service() or @service("name", ...)
    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.is_service = True
        metadata.service_schema = {
            "name": name_or_func if isinstance(name_or_func, str) else None,
            "schema": schema,
            "description": description,
        }
        return func

    return decorator


def startup(func: F) -> F:
    """Decorator to mark a function as a startup handler.

    Functions decorated with @startup are called once when the script is loaded
    and Home Assistant has started. Only one startup handler per script is allowed.
    If multiple are defined, only the last one will be executed.

    Startup handlers:
    - Run after the script is fully loaded and parsed
    - Are executed through the action worker pool (count toward concurrency limits)
    - Should complete quickly to not delay loading of other scripts
    - Cannot be triggered manually from the UI

    Args:
        func: The function to mark as a startup handler.

    Returns:
        The decorated function.

    Example:
        @startup
        async def on_startup():
            log_info("Script initialized!")
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

    Functions decorated with @shutdown are called when the script is being unloaded,
    reloaded, or when Home Assistant is stopping. Only one shutdown handler per
    script is allowed.

    Shutdown handlers:
    - Run when the script is unloaded, reloaded, or HA stops
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
            log_info("Script shutting down...")
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
# These are the primary interface for user scripts
from custom_components.haanim.engine.triggers.base import TriggerInfo
from custom_components.haanim.engine.triggers.state_trigger import state_trigger, state_active
from custom_components.haanim.engine.triggers.time_trigger import time_trigger, time_active
from custom_components.haanim.engine.triggers.event_trigger import event_trigger


# Export all decorators for use in scripts
__all__ = [
    # Action decorators
    "action",
    "service",
    "startup",
    "shutdown",
    # Trigger decorators (re-exported from engine/triggers/)
    "state_trigger",
    "time_trigger",
    "event_trigger",
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
    "METADATA_ATTR",
]
