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
    "DEFAULT_IMPORT_ALLOWLIST",
    # Security
    "RESTRICTED_BUILTINS",
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

# Default import allowlist - safe modules for automations
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
]

# Restricted builtins that should not be available in automations
RESTRICTED_BUILTINS: Final[set[str]] = {
    "eval",
    "exec",
    "compile",
    "open",
    "input",
    "__import__",
    "breakpoint",
    "memoryview",
    "globals",
    "locals",
    "vars",
    "dir",
    "delattr",
    "setattr",
    "getattr",
}
