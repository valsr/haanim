"""Texts automations declare with ``@text_entity``; setting one runs its ``set_value`` hook."""

# Home Assistant's entity classes define these properties as cached properties; ours read the store
# pyright: reportIncompatibleVariableOverride=false

from __future__ import annotations

# Home Assistant calls the async_ command methods; the sync ones are not used
# pylint: disable=abstract-method

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform
from haanim.const import (
    EntityCommand,
    EntityPlatform,
    OPTION_MAX_LENGTH,
    OPTION_MIN_LENGTH,
    OPTION_MODE,
    OPTION_PATTERN,
)
from haanim.engine.device_entities import TEXT_MAX_LENGTH, TEXT_MIN_LENGTH


class DeclaredText(DeclaredEntity, TextEntity):
    """A text an automation declares."""

    @property
    def native_value(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        value: str | None = self.state_value
        return value

    @property
    def native_min(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared minimum length."""
        return int(self.declaration.get(OPTION_MIN_LENGTH, TEXT_MIN_LENGTH))

    @property
    def native_max(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared maximum length."""
        return int(self.declaration.get(OPTION_MAX_LENGTH, TEXT_MAX_LENGTH))

    @property
    def pattern(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared pattern."""
        return self.declaration.get(OPTION_PATTERN)

    @property
    def mode(self) -> TextMode:  # pyright: ignore[reportIncompatibleVariableOverride]
        """How the frontend shows the text."""
        return TextMode(self.declaration.get(OPTION_MODE, EntityPlatform.TEXT))

    async def async_set_value(self, value: str) -> None:
        """Run the ``set_value`` hook."""
        await self.async_command(EntityCommand.SET_VALUE, value)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the texts automations declare."""
    await async_setup_declared_platform(hass, entry, async_add_entities, EntityPlatform.TEXT, DeclaredText)
