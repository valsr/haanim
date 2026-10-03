"""Constants for the HAAnim integration."""

from enum import Enum
from typing import Final


class ActionMode(Enum):
    """Action execution modes for handling concurrent calls.

    DROP: Drop new action request if already executing.
    QUEUE: Queue action request to execute sequentially.
    CANCEL: Cancel current action and start new execution.
    """

    DROP = "drop"
    QUEUE = "queue"
    CANCEL = "cancel"


__all__ = [
    # Core constants
    "DOMAIN",
    "NAME",
    "VERSION",
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
    # Execution modes
    "EXEC_MODE_MANUAL",
    "EXEC_MODE_TRIGGER",
    "EXEC_MODE_SCRIPT",
    # Events
    "EVENT_SCRIPT_LOADED",
    "EVENT_SCRIPT_UNLOADED",
    "EVENT_SCRIPT_ERROR",
    "EVENT_SCRIPT_EXECUTED",
    # Services
    "SERVICE_RELOAD_SCRIPTS",
    "SERVICE_RUN_ACTION",
    "SERVICE_LIST_SCRIPTS",
    "SERVICE_LIST_ACTIONS",
    "SERVICE_GET_CONFIG",
    # Attributes
    "ATTRIBUTE_SCRIPT_NAME",
    "ATTRIBUTE_SCRIPT_PATH",
    "ATTRIBUTE_ACTION_NAME",
    "ATTRIBUTE_MANUAL",
    # Configuration keys
    "CONFIG_SCRIPT_PATH",
    "CONFIG_IMPORT_ALLOWLIST",
    "CONFIG_ALLOW_ALL_IMPORTS",
    "CONFIG_SCRIPT_REFRESH_INTERVAL",
    # Default configuration values
    "DEFAULT_SCRIPT_PATH",
    "DEFAULT_ALLOW_ALL_IMPORTS",
    "DEFAULT_SCRIPT_REFRESH_INTERVAL",
    "DEFAULT_IMPORT_ALLOWLIST",
    "DEFAULT_MAX_CONCURRENT_ACTIONS",
    "DEFAULT_WORKER_SHUTDOWN_TIMEOUT",
    "DEFAULT_ACTION_QUEUE_SIZE",
    "DEFAULT_ACTION_TIMEOUT",
    # Security
    "RESTRICTED_BUILTINS",
]

DOMAIN: Final = "haanim"
NAME: Final = "HAAnim"
VERSION: Final = "0.1.0"

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

# Script execution modes
EXEC_MODE_MANUAL: Final = "manual"
EXEC_MODE_TRIGGER: Final = "trigger"
EXEC_MODE_SCRIPT: Final = "script"

# Events
EVENT_SCRIPT_LOADED: Final = f"{DOMAIN}_script_loaded"
EVENT_SCRIPT_UNLOADED: Final = f"{DOMAIN}_script_unloaded"
EVENT_SCRIPT_ERROR: Final = f"{DOMAIN}_script_error"
EVENT_SCRIPT_EXECUTED: Final = f"{DOMAIN}_script_executed"

# Services
SERVICE_RELOAD_SCRIPTS: Final = "reload_scripts"
SERVICE_RUN_ACTION: Final = "run_action"
SERVICE_LIST_SCRIPTS: Final = "list_scripts"
SERVICE_LIST_ACTIONS: Final = "list_actions"
SERVICE_GET_CONFIG: Final = "get_config"

# Attributes for script metadata
ATTRIBUTE_SCRIPT_NAME: Final = "script_name"
ATTRIBUTE_SCRIPT_PATH: Final = "script_path"
ATTRIBUTE_ACTION_NAME: Final = "action_name"
ATTRIBUTE_MANUAL: Final = "manual"

# Configuration keys
CONFIG_NAME: Final = "name"
CONFIG_SCRIPT_PATH: Final = "script_path"
CONFIG_IMPORT_ALLOWLIST: Final = "import_allowlist"
CONFIG_ALLOW_ALL_IMPORTS: Final = "allow_all_imports"
CONFIG_SCRIPT_REFRESH_INTERVAL: Final = "script_refresh_interval"
CONFIG_MAX_CONCURRENT_ACTIONS: Final = "max_concurrent_actions"
CONFIG_WORKER_SHUTDOWN_TIMEOUT: Final = "shutdown_timeout"

# Default configuration values
DEFAULT_SCRIPT_PATH: Final = "/config/haanim/scripts"
DEFAULT_ALLOW_ALL_IMPORTS: Final = False
DEFAULT_SCRIPT_REFRESH_INTERVAL: Final = 10
DEFAULT_MAX_CONCURRENT_ACTIONS: Final = 20
DEFAULT_WORKER_SHUTDOWN_TIMEOUT: Final = 0.2  # 200ms
DEFAULT_ACTION_QUEUE_SIZE: Final = 100
DEFAULT_ACTION_TIMEOUT: Final = 0  # 0 = no timeout

# Default import allowlist - safe modules for automation scripts
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

# Restricted builtins that should not be available in scripts
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
