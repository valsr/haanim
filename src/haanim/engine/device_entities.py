"""Entity declarations: the decorators that declare an automation's device entities.

See "Automation devices and declared entities" in
``docs/superpowers/specs/2026-11-09-automation-devices-design.md``. A decorator
only records an ``EntityDeclaration`` on the class; the automation context
collects the declared classes after ``main.py`` has run.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from haanim.const import ActionMode
from haanim.engine.automation_ids import automation_id as slug
from haanim.engine.errors import AutomationDefinitionError

ENTITY_ATTRIBUTE = "_haanim_entity"

# The options every decorator takes; they are not platform options
COMMON_OPTIONS = frozenset({"name", "icon", "id", "attributes", "initial", "action_mode"})

STATE_CLASSES = frozenset({"measurement", "total", "total_increasing"})

# Home Assistant's device classes per platform; the engine cannot import Home Assistant
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
)  # fmt: skip
DEVICE_CLASSES: dict[str, frozenset[str]] = {
    "sensor": _MEASURED | {"date", "enum", "timestamp", "uptime"},
    "number": _MEASURED,
    "binary_sensor": frozenset(
        {
            "battery", "battery_charging", "carbon_monoxide", "cold", "connectivity", "door",
            "garage_door", "gas", "heat", "light", "lock", "moisture", "motion", "moving", "occupancy",
            "opening", "plug", "power", "presence", "problem", "running", "safety", "smoke", "sound",
            "tamper", "update", "vibration", "window",
        }
    ),  # fmt: skip
    "switch": frozenset({"outlet", "switch"}),
    "button": frozenset({"identify", "restart", "update"}),
}


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
    "sensor": PlatformSpec(frozenset({"device_class", "unit", "state_class", "precision"}), ()),
    "binary_sensor": PlatformSpec(frozenset({"device_class"}), ()),
    "switch": PlatformSpec(frozenset({"device_class"}), ("turn_on", "turn_off")),
    "number": PlatformSpec(
        frozenset({"min", "max", "step", "unit", "mode", "device_class"}), ("set_value",)
    ),
    "select": PlatformSpec(frozenset({"options"}), ("select_option",)),
    "button": PlatformSpec(frozenset({"device_class"}), ("press",), stateful=False),
    "text": PlatformSpec(frozenset({"min_length", "max_length", "pattern", "mode"}), ("set_value",)),
}

_MODES = {"number": frozenset({"auto", "box", "slider"}), "text": frozenset({"text", "password"})}


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
            "name": self.name,
            "icon": self.icon,
            "initial": self.initial,
            "initial_attributes": dict(self.attributes),
            **self.options,
        }


def get_declaration(cls: Any) -> EntityDeclaration | None:
    """Return the declaration an entity decorator recorded on a class, or None."""
    declaration = getattr(cls, "__dict__", {}).get(ENTITY_ATTRIBUTE)
    return declaration if isinstance(declaration, EntityDeclaration) else None


def _check_options(platform: str, where: str, options: Mapping[str, Any]) -> None:
    """Raise AutomationDefinitionError unless the platform options fit together."""
    spec = PLATFORMS[platform]
    for option in options:
        if option not in spec.options:
            raise AutomationDefinitionError(f"{where}: a {platform} entity has no option '{option}'")

    device_class = options.get("device_class")
    if device_class is not None and device_class not in DEVICE_CLASSES.get(platform, frozenset()):
        raise AutomationDefinitionError(f"{where}: '{device_class}' is not a device_class of a {platform}")
    state_class = options.get("state_class")
    if state_class is not None and state_class not in STATE_CLASSES:
        raise AutomationDefinitionError(f"{where}: state_class must be one of {', '.join(sorted(STATE_CLASSES))}")
    mode = options.get("mode")
    if mode is not None and mode not in _MODES[platform]:
        raise AutomationDefinitionError(f"{where}: mode must be one of {', '.join(sorted(_MODES[platform]))}")

    if platform == "number":
        low, high = options.get("min", 0), options.get("max", 100)
        if low > high:
            raise AutomationDefinitionError(f"{where}: min {low} is greater than max {high}")
        if options.get("step", 1) <= 0:
            raise AutomationDefinitionError(f"{where}: step must be greater than 0")
    if platform == "select":
        choices = options.get("options")
        if not isinstance(choices, (list, tuple)) or not choices or not all(isinstance(c, str) for c in choices):
            raise AutomationDefinitionError(f"{where}: options must be a non-empty list of strings")
    if platform == "text" and "pattern" in options:
        try:
            re.compile(options["pattern"])
        except (re.error, TypeError) as err:
            raise AutomationDefinitionError(f"{where}: pattern is not a valid regular expression: {err}") from None


def _entity_decorator(platform: str) -> Callable[..., Any]:
    """Build the decorator of one platform."""

    def declare(cls: Any, given: dict[str, Any]) -> Any:
        if not isinstance(cls, type):
            raise AutomationDefinitionError(f"@{platform}_entity decorates a class, not {type(cls).__name__}")
        where = f"Entity class '{cls.__name__}'"
        common = {key: value for key, value in given.items() if key in COMMON_OPTIONS}
        options = {key: value for key, value in given.items() if key not in COMMON_OPTIONS}
        _check_options(platform, where, options)
        if not PLATFORMS[platform].stateful and common.get("initial") is not None:
            raise AutomationDefinitionError(f"{where}: a {platform} has no state, so no initial")

        object_id = slug(str(common.get("id") or cls.__name__))
        if not object_id:
            raise AutomationDefinitionError(f"{where}: the name gives no object ID; give one with id=")
        action_mode = common.get("action_mode", ActionMode.DROP)
        if not isinstance(action_mode, ActionMode):
            raise AutomationDefinitionError(f"{where}: action_mode must be an ActionMode")
        declaration = EntityDeclaration(
            object_id=object_id,
            platform=platform,
            name=str(common.get("name") or cls.__name__.replace("_", " ")),
            icon=common.get("icon"),
            options=options,
            attributes=dict(common.get("attributes") or {}),
            initial=common.get("initial"),
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


sensor_entity = _entity_decorator("sensor")
binary_sensor_entity = _entity_decorator("binary_sensor")
switch_entity = _entity_decorator("switch")
number_entity = _entity_decorator("number")
select_entity = _entity_decorator("select")
button_entity = _entity_decorator("button")
text_entity = _entity_decorator("text")

DECORATORS: dict[str, Callable[..., Any]] = {
    f"{platform}_entity": globals()[f"{platform}_entity"] for platform in PLATFORMS
}
