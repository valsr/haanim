"""Selects automations declare with ``@select_entity``; choosing an option runs its ``select_option`` hook."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform


class DeclaredSelect(DeclaredEntity, SelectEntity):
    """A select an automation declares."""

    @property
    def options(self) -> list[str]:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared options."""
        return list(self.declaration.get("options", []))

    @property
    def current_option(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        value: str | None = self.state_value
        return value

    async def async_select_option(self, option: str) -> None:
        """Run the ``select_option`` hook."""
        await self.async_command("select_option", option)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the selects automations declare."""
    await async_setup_declared_platform(hass, entry, async_add_entities, "select", DeclaredSelect)
