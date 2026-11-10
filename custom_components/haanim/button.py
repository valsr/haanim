"""Buttons automations declare with ``@button_entity``; pressing one runs its ``press`` hook."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform


class DeclaredButton(DeclaredEntity, ButtonEntity):
    """A button an automation declares."""

    @property
    def device_class(self) -> ButtonDeviceClass | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared device class."""
        value = self.declaration.get("device_class")
        return ButtonDeviceClass(value) if value else None

    async def async_press(self) -> None:
        """Run the ``press`` hook."""
        await self.async_command("press")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the buttons automations declare."""
    await async_setup_declared_platform(hass, entry, async_add_entities, "button", DeclaredButton)
