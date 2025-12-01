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
    # Attributes
    "ATTR_SCRIPT_NAME",
    "ATTR_SCRIPT_PATH",
    "ATTR_ACTION_NAME",
    "ATTR_MANUAL",
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

# Attributes for script metadata
ATTR_SCRIPT_NAME: Final = "script_name"
ATTR_SCRIPT_PATH: Final = "script_path"
ATTR_ACTION_NAME: Final = "action_name"
ATTR_MANUAL: Final = "manual"
