"""Texts automations declare with ``@text_entity``; setting one runs its ``set_value`` hook."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.haanim.entities import DeclaredEntity, async_setup_declared_platform
from haanim.engine.device_entities import TEXT_MAX_LENGTH, TEXT_MIN_LENGTH


class DeclaredText(DeclaredEntity, TextEntity):
    """A text an automation declares."""

    @property
    def native_value(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The stored state; None while unknown."""
        return self.state_value

    @property
    def native_min(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared minimum length."""
        return int(self.declaration.get("min_length", TEXT_MIN_LENGTH))

    @property
    def native_max(self) -> int:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared maximum length."""
        return int(self.declaration.get("max_length", TEXT_MAX_LENGTH))

    @property
    def pattern(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """The declared pattern."""
        return self.declaration.get("pattern")

    @property
    def mode(self) -> TextMode:  # pyright: ignore[reportIncompatibleVariableOverride]
        """How the frontend shows the text."""
        return TextMode(self.declaration.get("mode", "text"))

    async def async_set_value(self, value: str) -> None:
        """Run the ``set_value`` hook."""
        await self.async_command("set_value", value)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the texts automations declare."""
    await async_setup_declared_platform(hass, entry, async_add_entities, "text", DeclaredText)
