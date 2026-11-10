"""Entity declarations: the decorators that declare an automation's device entities.

See "Automation devices and declared entities" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. A decorator
only records an ``EntityDeclaration`` on the class; the automation context
collects the declared classes after ``main.py`` has run.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from haanim.const import (
    OPTION_ACTION_MODE,
    OPTION_ATTRIBUTES,
    OPTION_DEVICE_CLASS,
    OPTION_ICON,
    OPTION_ID,
    OPTION_INITIAL,
    OPTION_INITIAL_ATTRIBUTES,
    OPTION_MAX,
    OPTION_MAX_LENGTH,
    OPTION_MIN,
    OPTION_MIN_LENGTH,
    OPTION_MODE,
    OPTION_NAME,
    OPTION_OPTIONS,
    OPTION_PATTERN,
    OPTION_PRECISION,
    OPTION_STATE_CLASS,
    OPTION_STEP,
    OPTION_UNIT,
    ActionMode,
    EntityCommand,
    EntityPlatform,
    NumberMode,
    StateClass,
    TextMode,
)
from haanim.engine.automation_ids import automation_id as slug
from haanim.engine.errors import AutomationDefinitionError
from haanim.engine.variables import _check_json

ENTITY_ATTRIBUTE = "_haanim_entity"

# The options every decorator takes; they are not platform options
COMMON_OPTIONS = frozenset(
    {OPTION_NAME, OPTION_ICON, OPTION_ID, OPTION_ATTRIBUTES, OPTION_INITIAL, OPTION_ACTION_MODE}
)

STATE_CLASSES = frozenset(StateClass)

# Home Assistant's device classes per platform; the engine cannot import Home Assistant
# fmt: off
_MEASURED = frozenset(
    {
        "absolute_humidity", "apparent_power", "aqi", "area", "atmospheric_pressure", "battery",
        "blood_glucose_concentration", "carbon_dioxide", "carbon_monoxide", "conductivity", "current",
        "data_rate", "data_size", "distance", "duration", "energy", "energy_distance", "energy_storage",
        "frequency", "gas", "humidity", "illuminance", "irradiance", "moisture", "monetary",
        "nitrogen_dioxide", "nitrogen_monoxide", "nitrous_oxide", "ozone", "ph", "pm1", "pm10", "pm25",
        "pm4", "power", "power_factor", "precipitation", "precipitation_intensity", "pressure", "radon",
        "reactive_energy", "reactive_power", "signal_strength", "sound_pressure", "speed",
        "sulphur_dioxide", "temperature", "temperature_delta", "volatile_organic_compounds",
        "volatile_organic_compounds_parts", "voltage", "volume", "volume_flow_rate", "volume_storage",
        "water", "weight", "wind_direction", "wind_speed",
    }
)
DEVICE_CLASSES: dict[str, frozenset[str]] = {
    # Not date, enum, timestamp and uptime: Home Assistant wants other types than JSON for those
    EntityPlatform.SENSOR: _MEASURED,
    EntityPlatform.NUMBER: _MEASURED,
    EntityPlatform.BINARY_SENSOR: frozenset(
        {
            "battery", "battery_charging", "carbon_monoxide", "cold", "connectivity", "door",
            "garage_door", "gas", "heat", "light", "lock", "moisture", "motion", "moving", "occupancy",
            "opening", "plug", "power", "presence", "problem", "running", "safety", "smoke", "sound",
            "tamper", "update", "vibration", "window",
        }
    ),
    EntityPlatform.SWITCH: frozenset({"outlet", "switch"}),
    EntityPlatform.BUTTON: frozenset({"identify", "restart", "update"}),
}
# fmt: on


@dataclass(frozen=True)
class PlatformSpec:
    """What a platform's decorator accepts and which hooks its entities have.

    Args:
        options: The platform options the decorator takes besides the common ones.
        hooks: The commands from Home Assistant, by the method name that handles them.
        stateful: Whether the entity has a state; a button has none.
    """

    options: frozenset[str]
    hooks: tuple[str, ...]
    stateful: bool = True


PLATFORMS: dict[str, PlatformSpec] = {
    EntityPlatform.SENSOR: PlatformSpec(
        frozenset({OPTION_DEVICE_CLASS, OPTION_UNIT, OPTION_STATE_CLASS, OPTION_PRECISION}), ()
    ),
    EntityPlatform.BINARY_SENSOR: PlatformSpec(frozenset({OPTION_DEVICE_CLASS}), ()),
    EntityPlatform.SWITCH: PlatformSpec(
        frozenset({OPTION_DEVICE_CLASS}), (EntityCommand.TURN_ON, EntityCommand.TURN_OFF)
    ),
    EntityPlatform.NUMBER: PlatformSpec(
        frozenset({OPTION_MIN, OPTION_MAX, OPTION_STEP, OPTION_UNIT, OPTION_MODE, OPTION_DEVICE_CLASS}),
        (EntityCommand.SET_VALUE,),
    ),
    EntityPlatform.SELECT: PlatformSpec(frozenset({OPTION_OPTIONS}), (EntityCommand.SELECT_OPTION,)),
    EntityPlatform.BUTTON: PlatformSpec(
        frozenset({OPTION_DEVICE_CLASS}), (EntityCommand.PRESS,), stateful=False
    ),
    EntityPlatform.TEXT: PlatformSpec(
        frozenset({OPTION_MIN_LENGTH, OPTION_MAX_LENGTH, OPTION_PATTERN, OPTION_MODE}),
        (EntityCommand.SET_VALUE,),
    ),
}

# Home Assistant's defaults for options a declaration leaves out
NUMBER_MIN, NUMBER_MAX = 0.0, 100.0
TEXT_MIN_LENGTH, TEXT_MAX_LENGTH = 0, 255

_MODES: dict[str, frozenset[str]] = {
    EntityPlatform.NUMBER: frozenset(NumberMode),
    EntityPlatform.TEXT: frozenset(TextMode),
}


@dataclass(frozen=True)
class EntityDeclaration:  # pylint: disable=too-many-instance-attributes
    """What an entity decorator was given.

    Args:
        object_id: The entity's object ID within the automation.
        platform: The Home Assistant platform: one of ``PLATFORMS``.
        name: The friendly name.
        icon: An ``mdi:`` icon, or None.
        options: The platform options, as given.
        attributes: The attributes the entity starts with.
        initial: The state the entity starts with; None for unknown.
        action_mode: How concurrent hook calls are handled.
        cls: The decorated class.
        line: The line the class is defined on, if known.
    """

    object_id: str
    platform: str
    name: str
    icon: str | None
    options: dict[str, Any]
    attributes: dict[str, Any]
    initial: Any
    action_mode: ActionMode
    cls: type
    line: int | None = field(default=None, compare=False)

    def as_stored(self) -> dict[str, Any]:
        """Return what is stored as the entity's ``options``: the declaration without the class."""
        return {
            OPTION_NAME: self.name,
            OPTION_ICON: self.icon,
            OPTION_INITIAL: self.initial,
            OPTION_INITIAL_ATTRIBUTES: dict(self.attributes),
            **self.options,
        }


def get_declaration(cls: Any) -> EntityDeclaration | None:
    """Return the declaration an entity decorator recorded on a class, or None."""
    declaration = getattr(cls, "__dict__", {}).get(ENTITY_ATTRIBUTE)
    return declaration if isinstance(declaration, EntityDeclaration) else None


def _check_options(  # pylint: disable=too-many-branches
    platform: str, where: str, options: Mapping[str, Any]
) -> None:
    """Raise AutomationDefinitionError unless the platform options fit together."""
    spec = PLATFORMS[platform]
    for option in options:
        if option not in spec.options:
            raise AutomationDefinitionError(f"{where}: a {platform} entity has no option '{option}'")

    device_class = options.get(OPTION_DEVICE_CLASS)
    if device_class is not None and device_class not in DEVICE_CLASSES.get(platform, frozenset()):
        raise AutomationDefinitionError(f"{where}: '{device_class}' is not a device_class of a {platform}")
    state_class = options.get(OPTION_STATE_CLASS)
    if state_class is not None and state_class not in STATE_CLASSES:
        raise AutomationDefinitionError(
            f"{where}: state_class must be one of {', '.join(sorted(STATE_CLASSES))}"
        )
    mode = options.get(OPTION_MODE)
    if mode is not None and mode not in _MODES[platform]:
        raise AutomationDefinitionError(f"{where}: mode must be one of {', '.join(sorted(_MODES[platform]))}")

    if platform == EntityPlatform.NUMBER:
        for name in (OPTION_MIN, OPTION_MAX, OPTION_STEP):
            value = options.get(name, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AutomationDefinitionError(f"{where}: {name} must be a number, not {value!r}")
        low, high = options.get(OPTION_MIN, 0), options.get(OPTION_MAX, 100)
        if low > high:
            raise AutomationDefinitionError(f"{where}: min {low} is greater than max {high}")
        if options.get(OPTION_STEP, 1) <= 0:
            raise AutomationDefinitionError(f"{where}: step must be greater than 0")
    if platform == EntityPlatform.SELECT:
        choices = options.get(OPTION_OPTIONS)
        if (
            not isinstance(choices, (list, tuple))
            or not choices
            or not all(isinstance(c, str) for c in choices)
        ):
            raise AutomationDefinitionError(f"{where}: options must be a non-empty list of strings")
    if platform == EntityPlatform.TEXT and OPTION_PATTERN in options:
        try:
            re.compile(options[OPTION_PATTERN])
        except (re.error, TypeError) as err:
            raise AutomationDefinitionError(
                f"{where}: pattern is not a valid regular expression: {err}"
            ) from None


def _number(value: Any, what: str) -> float:
    """Return a value as a float; raise ValueError for a bool, infinity, NaN or what is not a number."""
    if isinstance(value, bool):
        raise ValueError(f"{what} must be a number, not a bool")
    try:
        number = float(value)
    except TypeError, ValueError:
        raise ValueError(f"{what} must be a number, not {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{what} must be a finite number, not {value!r}")
    return number


def is_numeric_sensor(options: Mapping[str, Any]) -> bool:
    """Return whether a sensor's state is a number, as Home Assistant decides it.

    It is with a unit, a state class, a precision or a device class (every
    device class a declaration accepts is a measured one).
    """
    return any(
        options.get(name) is not None
        for name in (OPTION_UNIT, OPTION_STATE_CLASS, OPTION_PRECISION, OPTION_DEVICE_CLASS)
    )


def validate_state(  # pylint: disable=too-many-return-statements,too-many-branches
    platform: str, options: Mapping[str, Any], value: Any
) -> Any:
    """Check a state against an entity's declaration and return it as it is stored.

    None (unknown) is always allowed, except for a button, which has no state.

    Args:
        platform: The entity's platform.
        options: The entity's platform options (extra keys are ignored).
        value: The new state.

    Returns:
        The state as stored: a float for numeric sensors and numbers, a bool for
        binary sensors and switches, else the value itself.

    Raises:
        ValueError: If the declaration does not allow the value.
    """
    if not PLATFORMS[platform].stateful:
        raise ValueError(f"a {platform} has no state")
    if value is None:
        return None

    if platform in (EntityPlatform.BINARY_SENSOR, EntityPlatform.SWITCH):
        if isinstance(value, bool):
            return value
        if value in ("on", "off"):
            return value == "on"
        raise ValueError(f"the state of a {platform} must be True or False, not {value!r}")

    if platform == EntityPlatform.NUMBER or (
        platform == EntityPlatform.SENSOR and is_numeric_sensor(options)
    ):
        number = _number(value, f"the state of this {platform}")
        if platform == EntityPlatform.NUMBER:
            low, high = options.get(OPTION_MIN, NUMBER_MIN), options.get(OPTION_MAX, NUMBER_MAX)
            if not low <= number <= high:
                raise ValueError(f"{number:g} is outside {low:g} to {high:g}")
        return number

    if platform == EntityPlatform.SELECT:
        if value not in options.get(OPTION_OPTIONS, ()):
            raise ValueError(f"{value!r} is not one of the options {list(options.get('options', ()))}")
        return value

    if platform == EntityPlatform.TEXT:
        if not isinstance(value, str):
            raise ValueError(f"the state of a text must be a string, not {type(value).__name__}")
        low, high = options.get(OPTION_MIN_LENGTH, TEXT_MIN_LENGTH), options.get(
            OPTION_MAX_LENGTH, TEXT_MAX_LENGTH
        )
        if not low <= len(value) <= high:
            raise ValueError(f"the text must be {low} to {high} characters long, not {len(value)}")
        pattern = options.get(OPTION_PATTERN)
        if pattern is not None and re.fullmatch(pattern, value) is None:
            raise ValueError(f"{value!r} does not match the pattern {pattern!r}")
        return value

    try:
        _check_json(value, "the state")
    except TypeError as err:
        raise ValueError(str(err)) from None
    return value


def _entity_decorator(platform: str) -> Callable[..., Any]:
    """Build the decorator of one platform."""

    def declare(cls: Any, given: dict[str, Any]) -> Any:
        if not isinstance(cls, type):
            raise AutomationDefinitionError(f"@{platform}_entity decorates a class, not {type(cls).__name__}")
        where = f"Entity class '{cls.__name__}'"
        common = {key: value for key, value in given.items() if key in COMMON_OPTIONS}
        options = {key: value for key, value in given.items() if key not in COMMON_OPTIONS}
        _check_options(platform, where, options)
        if not PLATFORMS[platform].stateful and common.get(OPTION_INITIAL) is not None:
            raise AutomationDefinitionError(f"{where}: a {platform} has no state, so no initial")

        initial = common.get(OPTION_INITIAL)
        if initial is not None:
            try:
                common[OPTION_INITIAL] = validate_state(platform, options, initial)
            except ValueError as err:
                raise AutomationDefinitionError(f"{where}: initial: {err}") from None

        object_id = slug(str(common.get(OPTION_ID) or cls.__name__))
        if not object_id:
            raise AutomationDefinitionError(f"{where}: the name gives no object ID; give one with id=")
        action_mode = common.get(OPTION_ACTION_MODE, ActionMode.DROP)
        if not isinstance(action_mode, ActionMode):
            raise AutomationDefinitionError(f"{where}: action_mode must be an ActionMode")
        declaration = EntityDeclaration(
            object_id=object_id,
            platform=platform,
            name=str(common.get(OPTION_NAME) or cls.__name__.replace("_", " ")),
            icon=common.get(OPTION_ICON),
            options=options,
            attributes=dict(common.get(OPTION_ATTRIBUTES) or {}),
            initial=common.get(OPTION_INITIAL),
            action_mode=action_mode,
            cls=cls,
            line=cls.__dict__.get("__firstlineno__"),
        )
        setattr(cls, ENTITY_ATTRIBUTE, declaration)
        return cls

    def decorator(cls: Any = None, /, **given: Any) -> Any:
        if cls is not None:
            return declare(cls, given)
        return lambda target: declare(target, given)

    decorator.__name__ = decorator.__qualname__ = f"{platform}_entity"
    return decorator


sensor_entity = _entity_decorator(EntityPlatform.SENSOR)
binary_sensor_entity = _entity_decorator(EntityPlatform.BINARY_SENSOR)
switch_entity = _entity_decorator(EntityPlatform.SWITCH)
number_entity = _entity_decorator(EntityPlatform.NUMBER)
select_entity = _entity_decorator(EntityPlatform.SELECT)
button_entity = _entity_decorator(EntityPlatform.BUTTON)
text_entity = _entity_decorator(EntityPlatform.TEXT)

DECORATORS: dict[str, Callable[..., Any]] = {
    f"{platform}_entity": globals()[f"{platform}_entity"] for platform in PLATFORMS
}
