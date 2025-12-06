"""Constants for the HAAnim integration."""

from typing import Final

__all__ = [
    # Core constants
    "DOMAIN",
    "NAME",
    "VERSION",
    # Decorator names
    "DECORATOR_SCENE",
    "DECORATOR_STATE_TRIGGER",
    "DECORATOR_TIME_TRIGGER",
    "DECORATOR_EVENT_TRIGGER",
    "DECORATOR_TIME_ACTIVE",
    "DECORATOR_STATE_ACTIVE",
    "DECORATOR_SERVICE",
    # Execution modes
    "EXEC_MODE_MANUAL",
    "EXEC_MODE_TRIGGER",
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
    "ATTR_SCRIPT_PATH",
    "ATTRIBUTE_ACTION_NAME",
    "ATTR_MANUAL",
    # Configuration keys
    "CONFIG_SCRIPT_PATH",
    "CONFIG_IMPORT_ALLOWLIST",
    "CONFIG_ALLOW_ALL_IMPORTS",
    "CONFIG_SCRIPT_REFRESH_INTERVAL",
    # Default configuration values
    "DEFAULT_NAME",
    "DEFAULT_SCRIPT_PATH",
    "DEFAULT_ALLOW_ALL_IMPORTS",
    "DEFAULT_SCRIPT_REFRESH_INTERVAL",
    "DEFAULT_IMPORT_ALLOWLIST",
    # Security
    "RESTRICTED_BUILTINS",
]

DOMAIN: Final = "haanim"
NAME: Final = "HAAnim"
VERSION: Final = "0.1.0"

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
SERVICE_GET_CONFIG: Final = "get_config"

# Attributes for script metadata
ATTRIBUTE_SCRIPT_NAME: Final = "script_name"
ATTR_SCRIPT_PATH: Final = "script_path"
ATTRIBUTE_ACTION_NAME: Final = "action_name"
ATTR_MANUAL: Final = "manual"

# Configuration keys
CONFIG_SCRIPT_PATH: Final = "script_path"
CONFIG_IMPORT_ALLOWLIST: Final = "import_allowlist"
CONFIG_ALLOW_ALL_IMPORTS: Final = "allow_all_imports"
CONFIG_SCRIPT_REFRESH_INTERVAL: Final = "script_refresh_interval"

# Default configuration values
DEFAULT_NAME: Final = "HAAnim"
DEFAULT_SCRIPT_PATH: Final = "/config/haanim"
DEFAULT_ALLOW_ALL_IMPORTS: Final = False
DEFAULT_SCRIPT_REFRESH_INTERVAL: Final = 10

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
