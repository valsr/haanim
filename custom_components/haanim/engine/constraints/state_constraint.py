"""State-based constraint decorator for HAAnim.

This module provides the state_active decorator for constraining when triggered
functions can execute based on entity state conditions.
"""

from __future__ import annotations

from typing import Any, TypeVar
from collections.abc import Callable

from custom_components.haanim.const import DECORATOR_STATE_ACTIVE

F = TypeVar("F", bound=Callable[..., Any])


def _get_or_create_metadata(func: Callable[..., Any]) -> Any:
    """Get or create FunctionMetadata for a function.

    This imports from decorators to avoid circular imports.

    Args:
        func: The function to get/create metadata for.

    Returns:
        The FunctionMetadata instance attached to the function.
    """
    # Import here to avoid circular dependency
    # pylint: disable=import-outside-toplevel
    from custom_components.haanim.engine.decorators import (
        _get_or_create_metadata as get_metadata,
    )

    return get_metadata(func)


def state_active(
    *state_exprs: str,
    **kwargs: Any,
) -> Callable[[F], F]:
    """Decorator to constrain when a triggered function can run based on state.

    This decorator adds state-based constraints to a trigger. The decorated function
    will only execute if ALL state expressions evaluate to true when the trigger fires.
    Does NOT apply to manual execution via @action.

    Args:
        state_exprs: State expressions that must all be true for the trigger to fire.
            Examples: "input_boolean.automation_enabled == 'on'"
        **kwargs: Additional configuration.

    Returns:
        Decorator function.

    Example:
        @state_active("input_boolean.night_mode == 'on'")
        @state_trigger("binary_sensor.motion == 'on'")
        def night_only_automation():
            '''Only runs if night_mode is on when motion is detected.'''
            pass

        @state_active(
            "input_boolean.vacation_mode == 'off'",
            "binary_sensor.someone_home == 'on'",
        )
        @time_trigger("sunset")
        def evening_lights():
            '''Only runs if not in vacation mode AND someone is home.'''
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
