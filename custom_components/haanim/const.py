"""Constants for the HAAnim integration."""

from typing import Final

from haanim import const as _engine_const
from haanim.const import (  # pylint: disable=unused-import
    DECORATOR_ACTION,
    DECORATOR_CRON_TRIGGER,
    DECORATOR_EVENT_TRIGGER,
    DECORATOR_INTERVAL_TRIGGER,
    DECORATOR_SERVICE,
    DECORATOR_SHUTDOWN,
    DECORATOR_STARTUP,
    DECORATOR_STATE_ACTIVE,
    DECORATOR_STATE_TRIGGER,
    DECORATOR_TIME_ACTIVE,
    DECORATOR_TIME_TRIGGER,
    DEFAULT_ACTION_QUEUE_SIZE,
    DEFAULT_ACTION_TIMEOUT,
    DEFAULT_IMPORT_ALLOWLIST,
    DEFAULT_MAX_CONCURRENT_ACTIONS,
    DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
    DISABLED_LOOP_MEMBERS,
    DISABLED_MODULE_MEMBERS,
    EVENT_HOST_STARTED,
    EXEC_MODE_AUTOMATION,
    EXEC_MODE_MANUAL,
    EXEC_MODE_TRIGGER,
    LOOP_GETTERS,
    RESTRICTED_BUILTINS,
    ActionMode,
)

# Integration constants, followed by the engine constants re-exported from haanim.const.
__all__ = [
    "DOMAIN",
    "NAME",
    "VERSION",
    "EVENT_AUTOMATION_LOADED",
    "EVENT_AUTOMATION_UNLOADED",
    "EVENT_AUTOMATION_ERROR",
    "EVENT_AUTOMATION_EXECUTED",
    "SERVICE_RELOAD_AUTOMATIONS",
    "SERVICE_RUN_ACTION",
    "SERVICE_LIST_AUTOMATIONS",
    "SERVICE_LIST_ACTIONS",
    "SERVICE_GET_CONFIG",
    "ATTRIBUTE_AUTOMATION_ID",
    "ATTRIBUTE_AUTOMATION_PATH",
    "ATTRIBUTE_ACTION_NAME",
    "ATTRIBUTE_MANUAL",
    "CONFIG_AUTOMATION_PATH",
    "CONFIG_IMPORT_ALLOWLIST",
    "CONFIG_ALLOW_ALL_IMPORTS",
    "CONFIG_AUTOMATION_REFRESH_INTERVAL",
    "DEFAULT_AUTOMATION_PATH",
    "DEFAULT_ALLOW_ALL_IMPORTS",
    "DEFAULT_AUTOMATION_REFRESH_INTERVAL",
]
__all__ += _engine_const.__all__

DOMAIN: Final = "haanim"
NAME: Final = "HAAnim"
VERSION: Final = "0.1.0"


# Events
EVENT_AUTOMATION_LOADED: Final = f"{DOMAIN}_automation_loaded"
EVENT_AUTOMATION_UNLOADED: Final = f"{DOMAIN}_automation_unloaded"
EVENT_AUTOMATION_ERROR: Final = f"{DOMAIN}_automation_error"
EVENT_AUTOMATION_EXECUTED: Final = f"{DOMAIN}_automation_executed"

# Services
SERVICE_RELOAD_AUTOMATIONS: Final = "reload_automations"
SERVICE_RUN_ACTION: Final = "run_action"
SERVICE_LIST_AUTOMATIONS: Final = "list_automations"
SERVICE_LIST_ACTIONS: Final = "list_actions"
SERVICE_GET_CONFIG: Final = "get_config"

# Attributes for automation metadata
ATTRIBUTE_AUTOMATION_ID: Final = "automation_id"
ATTRIBUTE_AUTOMATION_PATH: Final = "automation_path"
ATTRIBUTE_ACTION_NAME: Final = "action_name"
ATTRIBUTE_MANUAL: Final = "manual"

# Configuration keys
CONFIG_NAME: Final = "name"
CONFIG_AUTOMATION_PATH: Final = "automation_path"
CONFIG_IMPORT_ALLOWLIST: Final = "import_allowlist"
CONFIG_ALLOW_ALL_IMPORTS: Final = "allow_all_imports"
CONFIG_AUTOMATION_REFRESH_INTERVAL: Final = "automation_refresh_interval"
CONFIG_MAX_CONCURRENT_ACTIONS: Final = "max_concurrent_actions"
CONFIG_WORKER_SHUTDOWN_TIMEOUT: Final = "shutdown_timeout"

# Default configuration values
DEFAULT_AUTOMATION_PATH: Final = "/config/haanim/automations"
DEFAULT_ALLOW_ALL_IMPORTS: Final = False
DEFAULT_AUTOMATION_REFRESH_INTERVAL: Final = 10
