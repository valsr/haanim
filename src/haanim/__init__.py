"""HAAnim: Python automations for Home Assistant.

This package holds the automation engine and the test harness
(``haanim.testing``). The Home Assistant integration in
``custom_components/haanim`` is the glue that connects the engine to a running
instance. Importing this package does not import Home Assistant.

It also carries the type information for what an automation imports::

    from haanim import haa, action, on_state, StateEvent

Inside Home Assistant, and inside the test harness, each automation gets these
names from the interpreter, bound to that automation. Here they are the same
classes and decorators, so editors and type checkers see the real signatures.
``haa``, ``hass`` and ``logging`` belong to a running automation and exist here
for type checking only.
"""

from typing import TYPE_CHECKING, Any

from haanim.const import ActionMode
from haanim.engine.card import HAAnimCard
from haanim.engine.card_elements import (
    BadgeElement,
    ButtonElement,
    CardElement,
    CardLayout,
    CardRow,
    EntityElement,
    GaugeElement,
    GraphElement,
    HtmlElement,
    IconElement,
    ImageElement,
    TextElement,
    ValueElement,
)
from haanim.engine.decorators import (
    action,
    on_cron,
    on_event,
    on_interval,
    on_state,
    on_time,
    shutdown,
    startup,
)
from haanim.engine.errors import (
    PUBLIC_ERRORS,
    ActionCancelledError,
    ActionDroppedError,
    ActionNotFoundError,
    ActionTimeOutError,
    AutomationAlreadyRunningError,
    AutomationDisabledError,
    AutomationNotLoadedError,
    AutomationNotRunningError,
    AutomationSecurityError,
    AutomationSyntaxError,
    HAAnimError,
    NonExistingAutomationError,
    NonExistingEntityError,
    NonExistingServiceError,
    PoolExhaustedError,
    QueueFullError,
)
from haanim.engine.haanim_api import HAAnim, HAAnimAutomationProxy, HAAnimServiceCall, HAAnimServiceProxy
from haanim.engine.logging_wrapper import LoggerWrapper
from haanim.entity import HAAnimEntity
from haanim.events import (
    ActionEvent,
    AutomationEvent,
    CronEvent,
    EventTriggerEvent,
    IntervalEvent,
    ManualEvent,
    StateEvent,
    TimeEvent,
)

__version__ = "0.2.0"

RUNTIME_ONLY = ("haa", "hass", "logging")
"""Names an automation imports that exist only while it runs: the interpreter supplies them."""

if TYPE_CHECKING:
    haa: HAAnim
    hass: Any
    logging: LoggerWrapper


def __getattr__(name: str) -> Any:
    """Explain why a name of a running automation is not here."""
    if name in RUNTIME_ONLY:
        raise AttributeError(
            f"'{name}' exists only inside a running automation: Home Assistant and the test harness "
            "(haanim.testing.AutomationHarness) supply it to each automation they load"
        )
    raise AttributeError(f"module 'haanim' has no attribute '{name}'")


__all__ = [
    "__version__",
    # The API object and what it hands out
    "haa",
    "hass",
    "logging",
    "HAAnim",
    "HAAnimAutomationProxy",
    "HAAnimCard",
    "CardElement",
    "CardLayout",
    "CardRow",
    "TextElement",
    "HtmlElement",
    "ImageElement",
    "ValueElement",
    "EntityElement",
    "IconElement",
    "GaugeElement",
    "BadgeElement",
    "GraphElement",
    "ButtonElement",
    "HAAnimEntity",
    "HAAnimServiceCall",
    "HAAnimServiceProxy",
    "LoggerWrapper",
    "RUNTIME_ONLY",
    # Decorators
    "action",
    "startup",
    "shutdown",
    "on_time",
    "on_interval",
    "on_cron",
    "on_event",
    "on_state",
    "ActionMode",
    # Events
    "ActionEvent",
    "TimeEvent",
    "IntervalEvent",
    "CronEvent",
    "StateEvent",
    "EventTriggerEvent",
    "ManualEvent",
    "AutomationEvent",
    # Errors
    "PUBLIC_ERRORS",
    "HAAnimError",
    "AutomationSyntaxError",
    "AutomationSecurityError",
    "NonExistingAutomationError",
    "AutomationNotLoadedError",
    "AutomationNotRunningError",
    "AutomationAlreadyRunningError",
    "AutomationDisabledError",
    "ActionNotFoundError",
    "ActionDroppedError",
    "QueueFullError",
    "PoolExhaustedError",
    "ActionTimeOutError",
    "ActionCancelledError",
    "NonExistingEntityError",
    "NonExistingServiceError",
]
