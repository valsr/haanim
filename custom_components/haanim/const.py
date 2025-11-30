"""Constants for the HAAnim integration."""

from typing import Final

DOMAIN: Final = "haanim"
NAME: Final = "HAAnim"
VERSION: Final = "0.1.0"

# Default values
DEFAULT_NAME: Final = "HAAnim"

# Configuration keys
CONF_SCRIPT_PATH: Final = "script_path"
CONF_IMPORT_ALLOWLIST: Final = "import_allowlist"
CONF_ALLOW_ALL_IMPORTS: Final = "allow_all_imports"

# Default configuration values
DEFAULT_SCRIPT_PATH: Final = "/config/haanim"
DEFAULT_ALLOW_ALL_IMPORTS: Final = False

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

# Decorator names
DECORATOR_SCENE: Final = "scene"
DECORATOR_STATE_TRIGGER: Final = "state_trigger"
DECORATOR_TIME_TRIGGER: Final = "time_trigger"
DECORATOR_EVENT_TRIGGER: Final = "event_trigger"
DECORATOR_TIME_ACTIVE: Final = "time_active"
DECORATOR_STATE_ACTIVE: Final = "state_active"
DECORATOR_SERVICE: Final = "service"

# Script execution modes
EXEC_MODE_MANUAL: Final = "manual"
EXEC_MODE_TRIGGER: Final = "trigger"

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

# Attributes for script metadata
ATTR_SCRIPT_NAME: Final = "script_name"
ATTR_SCRIPT_PATH: Final = "script_path"
ATTR_ACTION_NAME: Final = "action_name"
ATTR_MANUAL: Final = "manual"
