"""Constants for the HAAnim engine."""

from enum import Enum
from typing import Final

__all__ = [
    # Enums
    "ActionMode",
    # Decorator names
    "DECORATOR_ACTION",
    "DECORATOR_STATE_TRIGGER",
    "DECORATOR_TIME_TRIGGER",
    "DECORATOR_EVENT_TRIGGER",
    "DECORATOR_INTERVAL_TRIGGER",
    "DECORATOR_CRON_TRIGGER",
    "DECORATOR_TIME_ACTIVE",
    "DECORATOR_STATE_ACTIVE",
    "DECORATOR_SERVICE",
    "DECORATOR_STARTUP",
    "DECORATOR_SHUTDOWN",
    # Host events
    "EVENT_HOST_STARTED",
    # Execution sources
    "EXEC_MODE_MANUAL",
    "EXEC_MODE_TRIGGER",
    "EXEC_MODE_AUTOMATION",
    # Defaults
    "DEFAULT_ACTION_QUEUE_SIZE",
    "DEFAULT_ACTION_TIMEOUT",
    "DEFAULT_MAX_CONCURRENT_ACTIONS",
    "DEFAULT_WORKER_SHUTDOWN_TIMEOUT",
    "DEFAULT_STARTUP_TIMEOUT",
    "DEFAULT_SHUTDOWN_TIMEOUT",
    "DEFAULT_STOP_GRACE_PERIOD",
    "DEFAULT_IMPORT_ALLOWLIST",
    # Security
    "RESTRICTED_BUILTINS",
    "DISABLED_MODULE_MEMBERS",
    "DISABLED_LOOP_MEMBERS",
    "LOOP_GETTERS",
]


class ActionMode(Enum):
    """Action execution modes for handling concurrent calls.

    DROP: Drop new action request if already executing.
    QUEUE: Queue action request to execute sequentially.
    CANCEL: Cancel current action and start new execution.
    """

    DROP = "drop"
    QUEUE = "queue"
    CANCEL = "cancel"


# Decorator names
DECORATOR_ACTION: Final = "action"
DECORATOR_STATE_TRIGGER: Final = "state_trigger"
DECORATOR_TIME_TRIGGER: Final = "time_trigger"
DECORATOR_EVENT_TRIGGER: Final = "event_trigger"
DECORATOR_INTERVAL_TRIGGER: Final = "interval_trigger"
DECORATOR_CRON_TRIGGER: Final = "cron_trigger"
DECORATOR_TIME_ACTIVE: Final = "time_active"
DECORATOR_STATE_ACTIVE: Final = "state_active"
DECORATOR_SERVICE: Final = "service"
DECORATOR_STARTUP: Final = "startup"
DECORATOR_SHUTDOWN: Final = "shutdown"

# Event the host fires once it has finished starting
EVENT_HOST_STARTED: Final = "homeassistant_started"

# How an action was invoked
EXEC_MODE_MANUAL: Final = "manual"
EXEC_MODE_TRIGGER: Final = "trigger"
EXEC_MODE_AUTOMATION: Final = "automation"

# Default action settings
DEFAULT_ACTION_QUEUE_SIZE: Final = 100
DEFAULT_ACTION_TIMEOUT: Final = 0  # 0 = no timeout
DEFAULT_MAX_CONCURRENT_ACTIONS: Final = 20
DEFAULT_WORKER_SHUTDOWN_TIMEOUT: Final = 0.2  # 200ms

# Modules an automation can import by default (see "Imports" in the design).
# "hass" and "haanim" are supplied by the engine; the rest are standard modules.
DEFAULT_IMPORT_ALLOWLIST: Final[list[str]] = [
    "asyncio",
    "datetime",
    "json",
    "logging",
    "math",
    "random",
    "re",
    "time",
    "typing",
    "collections",
    "functools",
    "itertools",
    "operator",
    "statistics",
    "decimal",
    "fractions",
    "enum",
    "dataclasses",
    "hass",
    "haanim",
]

# Builtins that are not available in automations
RESTRICTED_BUILTINS: Final[set[str]] = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
    "globals",
    "locals",
}

# Members of allowed modules that block the event loop or leave it, with what to use instead
DISABLED_MODULE_MEMBERS: Final[dict[str, dict[str, str]]] = {
    "time": {
        "sleep": "use 'await haa.sleep()'",
    },
    "asyncio": {
        "run": "automations already run on the event loop",
        "new_event_loop": "automations run on Home Assistant's event loop",
        "set_event_loop": "automations run on Home Assistant's event loop",
        "to_thread": "automations do not use threads",
        "create_subprocess_exec": "automations cannot start processes",
        "create_subprocess_shell": "automations cannot start processes",
    },
}

# Methods of the event loop that are disabled for the same reason
DISABLED_LOOP_MEMBERS: Final[dict[str, str]] = {
    "run_forever": "the event loop is already running",
    "run_until_complete": "the event loop is already running; use 'await'",
    "run_in_executor": "automations do not use threads",
}

# Functions of asyncio that return the event loop
LOOP_GETTERS: Final[set[str]] = {"get_event_loop", "get_running_loop"}

# Lifecycle time limits, in seconds (see "Automation Lifecycle" in the design)
DEFAULT_STARTUP_TIMEOUT: Final = 30.0
DEFAULT_SHUTDOWN_TIMEOUT: Final = 10.0
DEFAULT_STOP_GRACE_PERIOD: Final = 0.5
