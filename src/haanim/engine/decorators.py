"""The decorators an automation uses to define its actions, triggers and lifecycle handlers.

See "Actions", "Triggers" and "Special Triggers" in the design:

- ``@action`` makes a function an action and configures it.
- ``@on_time``, ``@on_interval``, ``@on_cron``, ``@on_event`` and ``@on_state``
  attach a trigger. A function with a trigger is an action too.
- ``@startup`` and ``@shutdown`` mark the lifecycle handlers.

A decorator only records what it was given on the function. An automation
gets these decorators bound to its own registry from its ``haanim`` module.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar, overload

from haanim.engine.durations import parse_duration
from haanim.engine.time_expr import parse_day_of_week
from haanim.engine.time_schedule import TimeSchedule
from haanim.const import (
    TRIGGER_CRON,
    TRIGGER_EVENT,
    TRIGGER_INTERVAL,
    TRIGGER_STATE,
    TRIGGER_TIME,
    ActionMode,
)

F = TypeVar("F", bound=Callable[..., Any])

# Attribute name for storing metadata on decorated functions
METADATA_ATTRIBUTE = "_haanim_metadata"

# The constraint keyword arguments every trigger decorator accepts
CONSTRAINT_ARGUMENTS = (
    "start_time",
    "end_time",
    "start_date",
    "end_date",
    "day_of_week",
    "when",
    "when_not",
)


@dataclass
class ActionInfo:
    """What ``@action`` was given.

    Args:
        name: The action's name. The function name if None.
        aliases: Additional names for the action.
        description: What the action does.
        execution_mode: How concurrent calls are handled (DROP, QUEUE, CANCEL).
        timeout: Time limit in seconds; None for the default timeout.
        disabled: Whether the action is listed but cannot be called.
    """

    name: str | None = None
    aliases: tuple[str, ...] = ()
    description: str | None = None
    execution_mode: ActionMode = ActionMode.DROP
    timeout: float | None = None
    disabled: bool = False


@dataclass
class TriggerInfo:
    """One trigger attached to a function.

    Args:
        trigger_type: The kind of trigger: one of the ``TRIGGER_*`` constants.
        trigger_expr: The trigger's expression: a time, interval, cron or
            state expression, or an event type.
        kwargs: The trigger's own options.
        constraints: The constraint arguments given, by name.
    """

    trigger_type: str
    trigger_expr: Any
    kwargs: dict[str, Any] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass
class FunctionMetadata:
    """What the decorators on a function recorded.

    Args:
        action_info: What ``@action`` was given; None if the function has no ``@action``.
        triggers: The triggers attached to the function, in source order (top decorator first).
        is_startup: Whether the function is the ``@startup`` handler.
        is_shutdown: Whether the function is the ``@shutdown`` handler.
    """

    action_info: ActionInfo | None = None
    triggers: list[TriggerInfo] = field(default_factory=list)
    is_startup: bool = False
    is_shutdown: bool = False

    @property
    def is_action(self) -> bool:
        """Whether the function is an action: it has ``@action`` or a trigger."""
        return self.action_info is not None or bool(self.triggers)


def _get_or_create_metadata(func: Callable[..., Any]) -> FunctionMetadata:
    """Return the metadata of a function, creating it on first use."""
    if not hasattr(func, METADATA_ATTRIBUTE):
        setattr(func, METADATA_ATTRIBUTE, FunctionMetadata())
    metadata: FunctionMetadata = getattr(func, METADATA_ATTRIBUTE)
    return metadata


def get_metadata(func: Callable[..., Any]) -> FunctionMetadata | None:
    """Return what the decorators recorded on a function, or None if it has none.

    Args:
        func: The function.
    """
    return getattr(func, METADATA_ATTRIBUTE, None)


def has_metadata(func: Callable[..., Any]) -> bool:
    """Return whether a function carries a HAAnim decorator.

    Args:
        func: The function.
    """
    return hasattr(func, METADATA_ATTRIBUTE)


def _require_function(decorator: str, func: Any) -> None:
    """Raise if what is being decorated is not callable."""
    if not callable(func):
        raise TypeError(f"@{decorator} must decorate a function, not {type(func).__name__}")


def _require_name(decorator: str, argument: str, value: Any) -> str:
    """Return a name argument, raising if it is not a non-empty string."""
    if not isinstance(value, str):
        raise TypeError(f"@{decorator}: {argument} must be a string, not {type(value).__name__}")
    if not value.strip():
        raise ValueError(f"@{decorator}: {argument} must not be empty")
    return value


# =============================================================================
# Actions
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
) -> Callable[[F], F]: ...


def action(
    func: Any = None,
    /,
    *,
    name: str | None = None,
    aliases: list[str] | tuple[str, ...] | None = None,
    description: str | None = None,
    execution_mode: ActionMode = ActionMode.DROP,
    timeout: float | None = None,
    disabled: bool = False,
) -> Any:
    """Make a function an action, or configure the action of a trigger function.

    Used as ``@action`` or with keyword arguments. A function with a trigger
    decorator is an action without ``@action``; add ``@action(...)`` to give it
    a name, aliases, an execution mode or a timeout. The order of the
    decorators does not matter.

    Args:
        func: The function, when used as ``@action`` without arguments.
        name: The action's name. The function name if omitted.
        aliases: Additional names for the action.
        description: What the action does.
        execution_mode: How concurrent calls are handled (DROP, QUEUE, CANCEL).
        timeout: Time limit in seconds. The default timeout if omitted.
        disabled: List the action but do not let it be called, and do not
            register its triggers.

    Raises:
        TypeError: If an argument has the wrong type.
        ValueError: If a name is empty or the timeout is negative.

    Example:
        @action
        def my_action():
            pass

        @action(name="evening scene", aliases=["evening"], timeout=30)
        @on_time("sunset")
        async def evening():
            pass
    """
    if func is not None and not callable(func):
        raise TypeError("@action takes keyword arguments only: write @action(name=...)")

    if name is not None:
        _require_name("action", "name", name)
    if aliases is not None and (isinstance(aliases, str) or not isinstance(aliases, (list, tuple))):
        raise TypeError("@action: aliases must be a list of strings")
    checked_aliases = tuple(_require_name("action", "an alias", alias) for alias in aliases or ())
    if description is not None and not isinstance(description, str):
        raise TypeError(f"@action: description must be a string, not {type(description).__name__}")
    if not isinstance(execution_mode, ActionMode):
        raise TypeError("@action: execution_mode must be an ActionMode")
    if timeout is not None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError(f"@action: timeout must be a number of seconds, not {type(timeout).__name__}")
        if timeout < 0:
            raise ValueError("@action: timeout must not be negative")
    if not isinstance(disabled, bool):
        raise TypeError(f"@action: disabled must be True or False, not {type(disabled).__name__}")

    info = ActionInfo(
        name=name,
        aliases=checked_aliases,
        description=description,
        execution_mode=execution_mode,
        timeout=timeout,
        disabled=disabled,
    )

    def decorator(target: F) -> F:
        _require_function("action", target)
        metadata = _get_or_create_metadata(target)
        if metadata.action_info is not None:
            raise ValueError(f"@action is used more than once on '{getattr(target, '__name__', target)}'")
        metadata.action_info = info
        return target

    return decorator(func) if func is not None else decorator


# =============================================================================
# Lifecycle
# =============================================================================


def startup(func: F) -> F:
    """Mark a function as the automation's startup handler.

    It is called once each time the automation starts, before the triggers
    are registered. An automation has at most one.

    Args:
        func: The function.
    """
    _require_function("startup", func)
    _get_or_create_metadata(func).is_startup = True
    return func


def shutdown(func: F) -> F:
    """Mark a function as the automation's shutdown handler.

    It is called once each time the automation stops, after its triggers are
    unregistered and its running actions have ended. An automation has at
    most one.

    Args:
        func: The function.
    """
    _require_function("shutdown", func)
    _get_or_create_metadata(func).is_shutdown = True
    return func


# =============================================================================
# Triggers
# =============================================================================


def _constraints(decorator: str, given: dict[str, Any]) -> dict[str, Any]:
    """Return the constraint arguments that were given, checking their types.

    The values are stored as written. They are parsed and evaluated when the
    trigger fires.
    """
    constraints: dict[str, Any] = {}
    for name in CONSTRAINT_ARGUMENTS:
        value = given.get(name)
        if value is None:
            continue
        allowed: tuple[type, ...] = (str, int) if name == "day_of_week" else (str,)
        if isinstance(value, bool) or not isinstance(value, allowed):
            raise TypeError(f"@{decorator}: {name} must be a string, not {type(value).__name__}")
        if name == "day_of_week":
            try:
                parse_day_of_week(value)
            except ValueError as err:
                raise ValueError(f"@{decorator}: {err}") from None
        constraints[name] = value
    return constraints


def _trigger(
    decorator: str,
    trigger_type: str,
    expr: Any,
    kwargs: dict[str, Any],
    constraints: dict[str, Any],
) -> Callable[[F], F]:
    """Build the decorator that attaches one trigger to a function."""
    info = TriggerInfo(
        trigger_type=trigger_type,
        trigger_expr=expr,
        kwargs={name: value for name, value in kwargs.items() if value is not None},
        constraints=_constraints(decorator, constraints),
    )

    def decorate(func: F) -> F:
        _require_function(decorator, func)
        # Decorators run bottom up; inserting at the front keeps source order.
        _get_or_create_metadata(func).triggers.insert(0, info)
        return func

    return decorate


def _require_duration(decorator: str, argument: str, value: Any) -> None:
    """Raise if a value is not a duration, naming the decorator and the value."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"@{decorator}: {argument} must be seconds or 'HH:MM:SS', not {type(value).__name__}")
    try:
        parse_duration(value)
    except ValueError as err:
        raise ValueError(f"@{decorator}: {argument} {value!r} is not valid: {err}") from None


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
    """Call the function at a date and/or time.

    Args:
        expr: The date and/or time expression, such as ``"09:00"`` or ``"sunset - 30 minutes"``.
        day_of_week: Only on these days of the week.
        day_of_month: Only on these days of the month.
        start_time: Constraint: only from this time of day.
        end_time: Constraint: only before this time of day.
        start_date: Constraint: only from this date.
        end_date: Constraint: only before this date.
        when: Constraint: only while this state expression is true.
        when_not: Constraint: only while this state expression is false.
    """
    _require_name("on_time", "the time expression", expr)
    if day_of_month is not None and (
        isinstance(day_of_month, bool) or not isinstance(day_of_month, (str, int))
    ):
        raise TypeError(f"@on_time: day_of_month must be a string, not {type(day_of_month).__name__}")
    constraints: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "start_date": start_date,
        "end_date": end_date,
    }
    constraints.update(when=when, when_not=when_not)
    options: dict[str, Any] = {"day_of_week": day_of_week, "day_of_month": day_of_month}
    # day_of_week does the same job for the trigger and as a constraint; it is checked once, here.
    _constraints("on_time", {"day_of_week": day_of_week})
    try:
        TimeSchedule.parse(expr, day_of_week, day_of_month)
    except ValueError as err:
        raise ValueError(f"@on_time: {err}") from None
    return _trigger("on_time", TRIGGER_TIME, expr, options, constraints)


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
    """Call the function repeatedly, a fixed time apart.

    Args:
        interval: Time between calls: seconds, or ``"HH:MM:SS"``.
        delay: Time before the first call, in the same formats. The interval if omitted.
        start_time: Constraint: only from this time of day.
        end_time: Constraint: only before this time of day.
        start_date: Constraint: only from this date.
        end_date: Constraint: only before this date.
        day_of_week: Constraint: only on these days of the week.
        when: Constraint: only while this state expression is true.
        when_not: Constraint: only while this state expression is false.
    """
    _require_duration("on_interval", "the interval", interval)
    if delay is not None:
        _require_duration("on_interval", "delay", delay)
    constraints: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "start_date": start_date,
        "end_date": end_date,
    }
    constraints.update(day_of_week=day_of_week, when=when, when_not=when_not)
    return _trigger("on_interval", TRIGGER_INTERVAL, interval, {"delay": delay}, constraints)


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
    """Call the function when a cron expression matches.

    Args:
        expr: The cron expression, such as ``"30 8 * * 1-5"``.
        start_time: Constraint: only from this time of day.
        end_time: Constraint: only before this time of day.
        start_date: Constraint: only from this date.
        end_date: Constraint: only before this date.
        day_of_week: Constraint: only on these days of the week.
        when: Constraint: only while this state expression is true.
        when_not: Constraint: only while this state expression is false.
    """
    _require_name("on_cron", "the cron expression", expr)
    constraints: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "start_date": start_date,
        "end_date": end_date,
    }
    constraints.update(day_of_week=day_of_week, when=when, when_not=when_not)
    return _trigger("on_cron", TRIGGER_CRON, expr, {}, constraints)


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
    """Call the function when an event of a type is fired.

    Args:
        event_type: The type of event.
        data: Only for events whose data has these keys with these values.
        start_time: Constraint: only from this time of day.
        end_time: Constraint: only before this time of day.
        start_date: Constraint: only from this date.
        end_date: Constraint: only before this date.
        day_of_week: Constraint: only on these days of the week.
        when: Constraint: only while this state expression is true.
        when_not: Constraint: only while this state expression is false.
    """
    _require_name("on_event", "the event type", event_type)
    if data is not None and not isinstance(data, dict):
        raise TypeError(f"@on_event: data must be a dict, not {type(data).__name__}")
    constraints: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "start_date": start_date,
        "end_date": end_date,
    }
    constraints.update(day_of_week=day_of_week, when=when, when_not=when_not)
    return _trigger(
        "on_event", TRIGGER_EVENT, event_type, {"data": dict(data) if data else None}, constraints
    )


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
    """Call the function when a state expression becomes true.

    Args:
        expr: The state expression, such as ``"sensor.temperature > 30"``.
        every_change: Call on every change while the expression is true, not
            only when it becomes true.
        hold: The expression must stay true this long first: seconds, or ``"HH:MM:SS"``.
        start_time: Constraint: only from this time of day.
        end_time: Constraint: only before this time of day.
        start_date: Constraint: only from this date.
        end_date: Constraint: only before this date.
        day_of_week: Constraint: only on these days of the week.
        when: Constraint: only while this state expression is true.
        when_not: Constraint: only while this state expression is false.
    """
    _require_name("on_state", "the state expression", expr)
    if not isinstance(every_change, bool):
        raise TypeError(f"@on_state: every_change must be True or False, not {type(every_change).__name__}")
    if hold is not None:
        _require_duration("on_state", "hold", hold)
    constraints: dict[str, Any] = {
        "start_time": start_time,
        "end_time": end_time,
        "start_date": start_date,
        "end_date": end_date,
    }
    constraints.update(day_of_week=day_of_week, when=when, when_not=when_not)
    options: dict[str, Any] = {"every_change": every_change or None, "hold": hold}
    return _trigger("on_state", TRIGGER_STATE, expr, options, constraints)


__all__ = [
    "CONSTRAINT_ARGUMENTS",
    "METADATA_ATTRIBUTE",
    "ActionInfo",
    "FunctionMetadata",
    "TriggerInfo",
    "action",
    "get_metadata",
    "has_metadata",
    "on_cron",
    "on_event",
    "on_interval",
    "on_state",
    "on_time",
    "shutdown",
    "startup",
]
