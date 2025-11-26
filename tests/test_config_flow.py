"""Tests for the HAAnim config flow."""

from __future__ import annotations

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.haanim.const import DOMAIN


async def test_form(hass: HomeAssistant) -> None:
    """Test the config flow form.

    Args:
        hass: Home Assistant instance.
    """
    # TODO: Implement config flow tests
    # result = await hass.config_entries.flow.async_init(
    #     DOMAIN, context={"source": config_entries.SOURCE_USER}
    # )
    # assert result["type"] == "form"
    pass


async def test_user_input(hass: HomeAssistant) -> None:
    """Test user input handling in config flow.

    Args:
        hass: Home Assistant instance.
    """
    # TODO: Implement user input tests
    pass
