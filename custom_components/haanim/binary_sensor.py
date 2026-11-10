"""Binary sensors automations declare with ``@binary_sensor_entity``."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform


class DeclaredBinarySensor(DeclaredEntity, BinarySensorEntity):
    """A binary sensor an automation declares."""

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        value: bool | None = self.state_value
        return value

    @property
    def device_class(
        self,
    ) -> BinarySensorDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared device class."""
        value = self.declaration.get("device_class")
        return BinarySensorDeviceClass(value) if value else None


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the binary sensors automations declare."""
    await async_setup_declared_platform(
        hass, entry, async_add_entities, "binary_sensor", DeclaredBinarySensor
    )
