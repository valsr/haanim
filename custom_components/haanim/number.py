"""Numbers automations declare with ``@number_entity``; setting one runs its ``set_value`` hook."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform
from haanim.const import (
    EntityCommand,
    EntityPlatform,
    OPTION_DEVICE_CLASS,
    OPTION_MAX,
    OPTION_MIN,
    OPTION_MODE,
    OPTION_STEP,
    OPTION_UNIT,
)
from haanim.engine.device_entities import NUMBER_MAX, NUMBER_MIN


class DeclaredNumber(DeclaredEntity, NumberEntity):
    """A number an automation declares."""

    @property
    def native_value(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        value: float | None = self.state_value
        return value

    @property
    def native_min_value(self) -> float:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared minimum."""
        return float(self.declaration.get(OPTION_MIN, NUMBER_MIN))

    @property
    def native_max_value(self) -> float:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared maximum."""
        return float(self.declaration.get(OPTION_MAX, NUMBER_MAX))

    @property
    def native_step(self) -> float | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared step."""
        step = self.declaration.get(OPTION_STEP)
        return float(step) if step is not None else None

    @property
    def native_unit_of_measurement(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared unit."""
        return self.declaration.get(OPTION_UNIT)

    @property
    def mode(self) -> NumberMode:  # pyright: ignore[reportIncompatibleVariableOverride]
        """How the frontend shows the number."""
        return NumberMode(self.declaration.get(OPTION_MODE, NumberMode.AUTO))

    @property
    def device_class(self) -> NumberDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared device class."""
        value = self.declaration.get(OPTION_DEVICE_CLASS)
        return NumberDeviceClass(value) if value else None

    async def async_set_native_value(self, value: float) -> None:
        """Run the ``set_value`` hook."""
        await self.async_command(EntityCommand.SET_VALUE, value)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the numbers automations declare."""
    await async_setup_declared_platform(
        hass, entry, async_add_entities, EntityPlatform.NUMBER, DeclaredNumber
    )
