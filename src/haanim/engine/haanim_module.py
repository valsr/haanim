"""The ``haanim`` module an automation imports.

``haanim`` is not one module shared by all automations. Each automation gets
its own module object, built when the automation is loaded: its ``haa``
instance, decorators that register to that automation, and its logger.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import Any

from haanim import const, events
from haanim.engine import decorators
from haanim.engine.errors import PUBLIC_ERRORS
from haanim.engine.card import HAAnimCard
from haanim.engine.haanim_api import HAAnim, HAAnimAutomationProxy, HAAnimServiceCall, HAAnimServiceProxy
from haanim.entity import HAAnimEntity
from haanim.engine.logging_wrapper import LoggerWrapper

# Decorators of the engine, by the name automations import them under.
DECORATORS: dict[str, Callable[..., Any]] = {
    "action": decorators.action,
    "startup": decorators.startup,
    "shutdown": decorators.shutdown,
    "on_time": decorators.on_time,
    "on_interval": decorators.on_interval,
    "on_cron": decorators.on_cron,
    "on_event": decorators.on_event,
    "on_state": decorators.on_state,
}

EVENT_CLASSES = (
    events.ActionEvent,
    events.TimeEvent,
    events.IntervalEvent,
    events.CronEvent,
    events.StateEvent,
    events.EventTriggerEvent,
    events.ManualEvent,
    events.AutomationEvent,
)


class DecoratorRegistry:
    """The decorated functions of one automation.

    The decorators an automation imports from ``haanim`` are bound to its
    registry, so a function decorated in any file of the automation is
    registered to that automation and to no other.
    """

    def __init__(self) -> None:
        """Initialize an empty registry."""
        self._functions: list[Callable[..., Any]] = []

    @property
    def functions(self) -> list[Callable[..., Any]]:
        """The decorated functions, in the order they were first decorated."""
        return list(self._functions)

    def clear(self) -> None:
        """Forget every registered function."""
        self._functions.clear()

    def _register(self, func: Any) -> None:
        """Record a decorated function once."""
        if callable(func) and not any(func is known for known in self._functions):
            self._functions.append(func)

    def bind(self, decorator: Callable[..., Any]) -> Callable[..., Any]:
        """Return a decorator that also records what it decorates in this registry.

        Works for both ways a decorator is written: ``@action`` applied to the
        function directly, and ``@action(...)`` or ``@state("...")``, which
        return the decorator to apply.

        Args:
            decorator: A decorator of the engine.
        """

        def bound(*args: Any, **kwargs: Any) -> Any:
            result = decorator(*args, **kwargs)

            if len(args) == 1 and not kwargs and result is args[0]:
                # @decorator: the function came straight back.
                self._register(result)
                return result

            if not callable(result):
                return result

            def apply(func: Any) -> Any:
                # @decorator(...): what came back is the decorator to apply.
                decorated = result(func)
                self._register(decorated)
                return decorated

            return apply

        bound.__name__ = getattr(decorator, "__name__", "decorator")
        bound.__doc__ = decorator.__doc__
        return bound


def build_haanim_module(
    *,
    haa: Any,
    registry: DecoratorRegistry,
    logging_wrapper: LoggerWrapper,
    hass: Any,
    helpers: dict[str, Any] | None = None,
) -> types.ModuleType:
    """Build the ``haanim`` module of one automation.

    Args:
        haa: The automation's ``HAAnim`` instance.
        registry: Where the automation's decorated functions are recorded.
        logging_wrapper: What ``from haanim import logging`` gives.
        hass: What ``from haanim import hass`` gives; None if the host has none.
        helpers: Further names to put in the module.

    Returns:
        A module object that belongs to this automation only.
    """
    module = types.ModuleType("haanim", "The HAAnim API of one automation.")
    names: dict[str, Any] = {
        "haa": haa,
        "hass": hass,
        "logging": logging_wrapper,
        "ActionMode": const.ActionMode,
        "HAAnim": HAAnim,
        "HAAnimAutomationProxy": HAAnimAutomationProxy,
        "HAAnimCard": HAAnimCard,
        "HAAnimEntity": HAAnimEntity,
        "HAAnimServiceCall": HAAnimServiceCall,
        "HAAnimServiceProxy": HAAnimServiceProxy,
    }
    names.update({name: registry.bind(decorator) for name, decorator in DECORATORS.items()})
    names.update({event_class.__name__: event_class for event_class in EVENT_CLASSES})
    names.update({error_class.__name__: error_class for error_class in PUBLIC_ERRORS})
    names.update(helpers or {})

    for name, value in names.items():
        setattr(module, name, value)
    module.__all__ = sorted(names)  # type: ignore[attr-defined]
    return module
