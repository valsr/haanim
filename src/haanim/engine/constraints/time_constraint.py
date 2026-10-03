"""Time-based constraint decorator for HAAnim triggers.

This module provides the time_active decorator that constrains when trigger functions can execute
based on time specifications. It does NOT apply to manual execution via @action decorator.
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

from haanim.const import DECORATOR_TIME_ACTIVE

# Avoid circular import by importing the metadata function only when needed
F = TypeVar("F", bound=Callable[..., Any])


def _get_or_create_metadata(func: Callable) -> Any:
    """Get or create function metadata.

    Args:
        func: The function to get/create metadata for.

    Returns:
        The function metadata object.
    """
    # Import here to avoid circular dependencies
    from haanim.engine.decorators import (
        _get_or_create_metadata as get_metadata,
    )

    return get_metadata(func)


def time_active(
    *time_specs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to constrain when a triggered function can run based on time.

    This decorator adds time-based constraints to a trigger. The decorated function
    will only execute if the current time matches one of the specifications.
    Does NOT apply to manual execution via @action.

    Args:
        time_specs: Time specifications for when the function is active.
            Supports range specifications: "range(start, end)"
            Times can be specified as HH:MM or sunrise/sunset.
        **kwargs: Additional configuration.

    Returns:
        Decorator function.

    Example:
        @time_active("range(sunset, sunrise)")
        @state_trigger("binary_sensor.motion == 'on'")
        def night_motion_light():
            '''Only triggers between sunset and sunrise.'''
            pass

        @time_active("range(08:00, 17:00)")
        @state_trigger("binary_sensor.office_motion == 'on'")
        def office_hours_automation():
            '''Only triggers during office hours.'''
            pass

        @time_active("range(22:00, 06:00)")  # Overnight range
        @event_trigger("custom_event")
        def night_handler():
            '''Active from 10 PM to 6 AM (overnight).'''
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
