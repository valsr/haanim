"""Switches automations declare with ``@switch_entity``; turning one on or off runs its hook."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.components.switch.const import SwitchDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from haanim.const import EntityCommand, EntityPlatform, OPTION_DEVICE_CLASS
from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform


class DeclaredSwitch(DeclaredEntity, SwitchEntity):
    """A switch an automation declares."""

    @property
    def is_on(self) -> bool | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        value: bool | None = self.state_value
        return value

    @property
    def device_class(self) -> SwitchDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared device class."""
        value = self.declaration.get(OPTION_DEVICE_CLASS)
        return SwitchDeviceClass(value) if value else None

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Run the ``turn_on`` hook."""
        await self.async_command(EntityCommand.TURN_ON)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Run the ``turn_off`` hook."""
        await self.async_command(EntityCommand.TURN_OFF)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the switches automations declare."""
    await async_setup_declared_platform(
        hass, entry, async_add_entities, EntityPlatform.SWITCH, DeclaredSwitch
    )
