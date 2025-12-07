"""Tests for the HAAnim integration setup."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim import DOMAIN, async_setup


@pytest.mark.asyncio
async def test_async_setup(hass: HomeAssistant) -> None:
    """Test the component setup.

    Args:
        hass: Home Assistant instance.
    """
    # Test that async_setup creates the domain data structure
    result = await async_setup(hass, {})
    assert result is True
    assert DOMAIN in hass.data


@pytest.mark.asyncio
async def test_async_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_script_manager: MagicMock,
) -> None:
    """Test config entry setup.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_script_manager: Mock ScriptManager.
    """
    _ = mock_script_manager  # Fixture provides mocking
    # Initialize domain data
    hass.data[DOMAIN] = {}

    # Add the config entry to hass
    mock_config_entry.add_to_hass(hass)

    # Setup the entry through Home Assistant's config entry system
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED
    assert mock_config_entry.entry_id in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_script_manager: MagicMock,
) -> None:
    """Test config entry unload.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_script_manager: Mock ScriptManager.
    """
    _ = mock_script_manager  # Fixture provides mocking
    # Initialize domain data
    hass.data[DOMAIN] = {}

    # Add the config entry to hass and set it up
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Now unload it
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.NOT_LOADED
    assert mock_config_entry.entry_id not in hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_reload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_script_manager: MagicMock,
) -> None:
    """Test config entry reload.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_script_manager: Mock ScriptManager.
    """
    _ = mock_script_manager  # Fixture provides mocking
    # Initialize domain data
    hass.data[DOMAIN] = {}

    # Add the config entry to hass and set it up
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Reload the entry
    await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Entry should still be loaded
    assert mock_config_entry.state == ConfigEntryState.LOADED
    assert mock_config_entry.entry_id in hass.data[DOMAIN]
