"""Decorators for HAAnim automation scripts.

This module provides decorators that users can use in their automation scripts
to define triggers, actions, and metadata.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from .const import (
    DECORATOR_EVENT_TRIGGER,
    DECORATOR_SCENE,
    DECORATOR_SERVICE,
    DECORATOR_STATE_ACTIVE,
    DECORATOR_STATE_TRIGGER,
    DECORATOR_TIME_ACTIVE,
    DECORATOR_TIME_TRIGGER,
)

_LOGGER = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass
class TriggerInfo:
    """Information about a trigger attached to a function.

    Args:
        trigger_type: The type of trigger (state_trigger, time_trigger, event_trigger).
        trigger_expr: The trigger expression or configuration.
        kwargs: Additional keyword arguments for the trigger.
    """

    trigger_type: str
    trigger_expr: str | list[str]
    kwargs: dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionInfo:
    """Information about an action (act/scene) decorated function.

    Args:
        name: Display name for the action.
        description: Optional description of what the action does.
        func: The decorated function.
    """

    name: str | None = None
    description: str | None = None
    func: Callable[..., Any] | None = None


@dataclass
class FunctionMetadata:
    """Metadata collected from decorators on a function.

    Args:
        custom_name: Custom name from @scene("name") decorator.
        is_action: Whether function is marked as a scene (@scene).
        action_info: Information about the scene if is_action is True.
        triggers: List of triggers attached to this function.
        constraints: List of constraints (time_active, state_active).
        is_service: Whether function should be exposed as HA service.
        service_schema: Schema for service parameters if is_service.
    """

    custom_name: str | None = None
    is_action: bool = False
    action_info: ActionInfo | None = None
    triggers: list[TriggerInfo] = field(default_factory=list)
    constraints: list[dict[str, Any]] = field(default_factory=list)
    is_service: bool = False
    service_schema: dict[str, Any] | None = None


# Attribute name for storing metadata on decorated functions
METADATA_ATTR = "_haanim_metadata"


def _get_or_create_metadata(func: F) -> FunctionMetadata:
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


def scene(
    name_or_func: str | F | None = None,
    *,
    description: str | None = None,
) -> F | Callable[[F], F]:
    """Decorator to mark a function as a scene, manually executable from the UI.

    When a function is decorated with @scene, it becomes available in the HAAnim
    UI for manual execution. Manual execution bypasses all trigger constraints.

    Args:
        name_or_func: Optional display name for the scene, or the function if
            used without arguments.
        description: Optional description of what the scene does.

    Returns:
        Decorated function or decorator.

    Example:
        @scene
        def turn_on_lights():
            pass

        @scene("Morning Routine")
        def morning_routine():
            pass

        @scene("Evening Scene", description="Activates evening lighting")
        @time_trigger("sunset")
        def evening_scene():
            pass
    """
    # Handle @scene without parentheses
    if callable(name_or_func):
        func = name_or_func
        metadata = _get_or_create_metadata(func)
        metadata.is_action = True
        metadata.action_info = ActionInfo(func=func)
        return func

    # Handle @scene() or @scene("name") or @scene(description="...")
    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.is_action = True
        metadata.action_info = ActionInfo(
            name=name_or_func if isinstance(name_or_func, str) else None,
            description=description,
            func=func,
        )
        # Also set custom_name for consistency
        if isinstance(name_or_func, str):
            metadata.custom_name = name_or_func
        return func

    return decorator


def state_trigger(
    *trigger_exprs: str,
    state_hold: float | None = None,
    state_check_now: bool = False,
    watch: list[str] | None = None,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function when state conditions are met.

    Args:
        trigger_exprs: One or more state expressions that trigger the function.
            Examples: "sensor.temperature > 25", "binary_sensor.motion == 'on'"
        state_hold: Optional seconds the condition must remain true before triggering.
        state_check_now: If True, check the condition immediately on script load.
        watch: Optional list of entity IDs to watch for changes.
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @state_trigger("sensor.temperature > 25", state_hold=60)
        def handle_high_temp():
            pass

        @state_trigger(
            "binary_sensor.motion == 'on'",
            "binary_sensor.door == 'open'",
        )
        def handle_activity():
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_STATE_TRIGGER,
            trigger_expr=list(trigger_exprs) if len(trigger_exprs) > 1 else trigger_exprs[0],
            kwargs={
                "state_hold": state_hold,
                "state_check_now": state_check_now,
                "watch": watch,
                **kwargs,
            },
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


def time_trigger(
    *trigger_specs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function at specific times.

    Args:
        trigger_specs: One or more time specifications. Supports:
            - Cron expressions: "cron(0 8 * * *)" (8 AM daily)
            - Time of day: "time(08:00:00)"
            - Periods: "period(0:00, 1 hour)" (every hour)
            - Sunrise/sunset: "sunrise", "sunset", "sunrise + 30m"
            - Startup: "startup" (run when HA starts)
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @time_trigger("cron(0 8 * * *)")  # 8 AM daily
        def morning_routine():
            pass

        @time_trigger("sunrise + 30m", "sunset - 15m")
        def lighting_automation():
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_TIME_TRIGGER,
            trigger_expr=list(trigger_specs) if len(trigger_specs) > 1 else trigger_specs[0],
            kwargs=kwargs,
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


def event_trigger(
    event_type: str,
    *,
    event_data: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to trigger a function when a Home Assistant event fires.

    Args:
        event_type: The event type to listen for (e.g., "state_changed", "call_service").
        event_data: Optional filter for event data fields.
        **kwargs: Additional trigger configuration.

    Returns:
        Decorator function.

    Example:
        @event_trigger("custom_event", event_data={"action": "button_press"})
        def handle_button():
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        trigger_info = TriggerInfo(
            trigger_type=DECORATOR_EVENT_TRIGGER,
            trigger_expr=event_type,
            kwargs={"event_data": event_data, **kwargs},
        )
        metadata.triggers.append(trigger_info)
        return func

    return decorator


def time_active(
    *time_specs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to constrain when a triggered function can run.

    This decorator adds time-based constraints. The function will only
    execute if the current time matches the specification. Does NOT
    apply to manual execution via @scene.

    Args:
        time_specs: Time specifications for when the function is active.
            Examples: "range(sunrise, sunset)", "range(08:00, 17:00)"
        **kwargs: Additional configuration.

    Returns:
        Decorator function.

    Example:
        @time_active("range(sunset, sunrise)")
        @state_trigger("binary_sensor.motion == 'on'")
        def night_motion_light():
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.constraints.append(
            {
                "type": DECORATOR_TIME_ACTIVE,
                "specs": list(time_specs),
                **kwargs,
            }
        )
        return func

    return decorator


def state_active(
    *state_exprs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to constrain when a triggered function can run based on state.

    This decorator adds state-based constraints. The function will only
    execute if all state expressions evaluate to true. Does NOT apply
    to manual execution via @scene.

    Args:
        state_exprs: State expressions that must be true.
            Examples: "input_boolean.automation_enabled == 'on'"
        **kwargs: Additional configuration.

    Returns:
        Decorator function.

    Example:
        @state_active("input_boolean.night_mode == 'on'")
        @state_trigger("binary_sensor.motion == 'on'")
        def night_only_automation():
            pass
    """

    def decorator(func: F) -> F:
        metadata = _get_or_create_metadata(func)
        metadata.constraints.append(
            {
                "type": DECORATOR_STATE_ACTIVE,
                "exprs": list(state_exprs),
                **kwargs,
            }
        )
        return func

    return decorator


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


# Export all decorators for use in scripts
__all__ = [
    "scene",
    "state_trigger",
    "time_trigger",
    "event_trigger",
    "time_active",
    "state_active",
    "service",
    "get_metadata",
    "has_metadata",
    "FunctionMetadata",
    "TriggerInfo",
    "ActionInfo",
]
