"""Constants for the HAAnim engine."""

from enum import Enum, StrEnum
from typing import Final

__all__ = [
    # Enums
    "ActionMode",
    # Device entities
    "EntityPlatform",
    "EntityCommand",
    "StateClass",
    "NumberMode",
    "TextMode",
    "OPTION_NAME",
    "OPTION_ICON",
    "OPTION_ID",
    "OPTION_ATTRIBUTES",
    "OPTION_INITIAL",
    "OPTION_INITIAL_ATTRIBUTES",
    "OPTION_ACTION_MODE",
    "OPTION_DEVICE_CLASS",
    "OPTION_UNIT",
    "OPTION_STATE_CLASS",
    "OPTION_PRECISION",
    "OPTION_MIN",
    "OPTION_MAX",
    "OPTION_STEP",
    "OPTION_MODE",
    "OPTION_OPTIONS",
    "OPTION_MIN_LENGTH",
    "OPTION_MAX_LENGTH",
    "OPTION_PATTERN",
    # Long-term statistics
    "Period",
    "STAT_START",
    "STAT_END",
    "STAT_USAGE",
    "STAT_MEAN",
    "STAT_MIN",
    "STAT_MAX",
    "STAT_STATE",
    "STAT_SUM",
    "STAT_CHANGE",
    # Units, with Home Assistant's names and values
    "UnitOfEnergy",
    "UnitOfPower",
    "UnitOfTemperature",
    "UnitOfTime",
    "UnitOfVolume",
    "UnitOfPressure",
    "UnitOfElectricCurrent",
    "UnitOfElectricPotential",
    "PERCENTAGE",
    # Trigger kinds
    "TRIGGER_TIME",
    "TRIGGER_INTERVAL",
    "TRIGGER_CRON",
    "TRIGGER_EVENT",
    "TRIGGER_STATE",
    # Constraint kinds
    "CONSTRAINT_TIME",
    "CONSTRAINT_STATE",
    # Host events
    "EVENT_HOST_STARTED",
    "EVENT_ACTION_ERROR",
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
    # Services
    "ResponseSupport",
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


class ResponseSupport(StrEnum):
    """Whether a service gives response data, as Home Assistant's ``SupportsResponse``."""

    NONE = "none"
    """It never responds; most services, such as ``light.turn_on``."""
    OPTIONAL = "optional"
    """It responds when asked."""
    ONLY = "only"
    """It must be asked for its response."""


# --- Device entities --------------------------------------------------------------
# Each is its string (a StrEnum), so declarations written with plain strings mean the same.


class EntityPlatform(StrEnum):
    """The Home Assistant platforms of the entities an automation declares."""

    SENSOR = "sensor"
    BINARY_SENSOR = "binary_sensor"
    SWITCH = "switch"
    NUMBER = "number"
    SELECT = "select"
    BUTTON = "button"
    TEXT = "text"


class EntityCommand(StrEnum):
    """The commands Home Assistant sends to an entity; each is handled by the class method of that name."""

    TURN_ON = "turn_on"
    TURN_OFF = "turn_off"
    SET_VALUE = "set_value"
    SELECT_OPTION = "select_option"
    PRESS = "press"


class StateClass(StrEnum):
    """The state classes of a sensor; they decide which long-term statistics it has."""

    MEASUREMENT = "measurement"
    TOTAL = "total"
    TOTAL_INCREASING = "total_increasing"


class NumberMode(StrEnum):
    """How the frontend shows a number entity."""

    AUTO = "auto"
    BOX = "box"
    SLIDER = "slider"


class TextMode(StrEnum):
    """How the frontend shows a text entity."""

    TEXT = "text"
    PASSWORD = "password"


# The options of the entity decorators, as they are stored
OPTION_NAME: Final = "name"
OPTION_ICON: Final = "icon"
OPTION_ID: Final = "id"
OPTION_ATTRIBUTES: Final = "attributes"
OPTION_INITIAL: Final = "initial"
OPTION_INITIAL_ATTRIBUTES: Final = "initial_attributes"
OPTION_ACTION_MODE: Final = "action_mode"
OPTION_DEVICE_CLASS: Final = "device_class"
OPTION_UNIT: Final = "unit"
OPTION_STATE_CLASS: Final = "state_class"
OPTION_PRECISION: Final = "precision"
OPTION_MIN: Final = "min"
OPTION_MAX: Final = "max"
OPTION_STEP: Final = "step"
OPTION_MODE: Final = "mode"
OPTION_OPTIONS: Final = "options"
OPTION_MIN_LENGTH: Final = "min_length"
OPTION_MAX_LENGTH: Final = "max_length"
OPTION_PATTERN: Final = "pattern"

# --- Long-term statistics ---------------------------------------------------------


class Period(StrEnum):
    """The periods long-term statistics are queried by."""

    FIVE_MINUTES = "5minute"
    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


# The fields of a statistics row
STAT_START: Final = "start"
STAT_END: Final = "end"
STAT_USAGE: Final = "usage"
STAT_MEAN: Final = "mean"
STAT_MIN: Final = "min"
STAT_MAX: Final = "max"
STAT_STATE: Final = "state"
STAT_SUM: Final = "sum"
STAT_CHANGE: Final = "change"

# --- Units ------------------------------------------------------------------------
# Common units, with the names and values Home Assistant gives them; any other unit string works too.


class UnitOfEnergy(StrEnum):
    """Units of energy."""

    WATT_HOUR = "Wh"
    KILO_WATT_HOUR = "kWh"
    MEGA_WATT_HOUR = "MWh"


class UnitOfPower(StrEnum):
    """Units of power."""

    WATT = "W"
    KILO_WATT = "kW"


class UnitOfTemperature(StrEnum):
    """Units of temperature."""

    CELSIUS = "°C"
    FAHRENHEIT = "°F"
    KELVIN = "K"


class UnitOfTime(StrEnum):
    """Units of time."""

    SECONDS = "s"
    MINUTES = "min"
    HOURS = "h"
    DAYS = "d"


class UnitOfVolume(StrEnum):
    """Units of volume."""

    LITERS = "L"
    CUBIC_METERS = "m³"


class UnitOfPressure(StrEnum):
    """Units of pressure."""

    HPA = "hPa"
    KPA = "kPa"
    BAR = "bar"


class UnitOfElectricCurrent(StrEnum):
    """Units of electric current."""

    AMPERE = "A"


class UnitOfElectricPotential(StrEnum):
    """Units of electric potential."""

    VOLT = "V"


PERCENTAGE: Final = "%"

# The kinds of trigger; each is attached with the decorator ``on_<kind>``
TRIGGER_TIME: Final = "time"
TRIGGER_INTERVAL: Final = "interval"
TRIGGER_CRON: Final = "cron"
TRIGGER_EVENT: Final = "event"
TRIGGER_STATE: Final = "state"

# The kinds of constraint a trigger can carry
CONSTRAINT_TIME: Final = "time"
CONSTRAINT_STATE: Final = "state"

# Event the host fires once it has finished starting
EVENT_HOST_STARTED: Final = "homeassistant_started"

# Fired when an action called by a trigger fails (see "Trigger Functions Are Actions" in the design)
EVENT_ACTION_ERROR: Final = "haanim_action_error"

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
    "html",
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
