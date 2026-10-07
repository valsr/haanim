"""Tests for the HAAnim integration setup."""

from __future__ import annotations

from unittest.mock import MagicMock

import re
from pathlib import Path

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
    mock_automation_manager: MagicMock,
) -> None:
    """Test config entry setup.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_automation_manager: Mock AutomationManager.
    """
    _ = mock_automation_manager  # Fixture provides mocking
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
    mock_automation_manager: MagicMock,
) -> None:
    """Test config entry unload.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_automation_manager: Mock AutomationManager.
    """
    _ = mock_automation_manager  # Fixture provides mocking
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
    mock_automation_manager: MagicMock,
) -> None:
    """Test config entry reload.

    Args:
        hass: Home Assistant instance.
        mock_config_entry: Mock configuration entry.
        mock_automation_manager: Mock AutomationManager.
    """
    _ = mock_automation_manager  # Fixture provides mocking
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


class TestPanelRegistration:
    """The panel and the card are served as ES modules."""

    async def test_register_and_unregister(self, hass: HomeAssistant) -> None:
        """Test the panel is a module panel and the card is loaded with the frontend, both removed again."""
        from unittest.mock import AsyncMock, MagicMock, patch  # pylint: disable=import-outside-toplevel

        import custom_components.haanim as integration  # pylint: disable=import-outside-toplevel

        http = MagicMock()
        http.async_register_static_paths = AsyncMock()
        hass.http = http
        with patch.object(integration, "frontend") as frontend:
            await integration._async_register_panel(hass)  # pylint: disable=protected-access

            (paths,), _ = http.async_register_static_paths.call_args
            assert paths[0].url_path == "/haanim/ui"
            assert paths[0].path.endswith("custom_components/haanim/ui")
            # The frontend is given an address that has the fingerprint of the files in it
            versioned = paths[1].url_path
            assert re.fullmatch(r"/haanim/ui-[0-9a-f]{12}", versioned)
            assert paths[1].path == paths[0].path
            assert versioned == integration.ui_url(integration.ui_fingerprint(paths[0].path))
            config = frontend.async_register_built_in_panel.call_args.kwargs["config"]["_panel_custom"]
            assert config["name"] == "haanim-panel"
            assert config["module_url"] == f"{versioned}/haanim-panel.js"
            assert "js_url" not in config
            frontend.add_extra_js_url.assert_called_once_with(hass, f"{versioned}/haanim-card.js")

            hass.data["frontend_panels"] = {"haanim": object()}
            await integration._async_register_panel(hass)  # pylint: disable=protected-access
            assert frontend.async_register_built_in_panel.call_count == 1

            await integration._async_unregister_panel(hass)  # pylint: disable=protected-access
            frontend.async_remove_panel.assert_called_once_with(hass, "haanim")
            frontend.remove_extra_js_url.assert_called_once_with(hass, f"{versioned}/haanim-card.js")
            await integration._async_unregister_panel(hass)  # pylint: disable=protected-access
            assert frontend.remove_extra_js_url.call_count == 1, "nothing is left to remove"

    def test_fingerprint_follows_the_files(self, tmp_path: Path) -> None:
        """Test the fingerprint changes when a file changes, appears or is renamed, and is otherwise the same."""
        import custom_components.haanim as integration  # pylint: disable=import-outside-toplevel

        (tmp_path / "a.js").write_text("one", encoding="utf-8")
        (tmp_path / "folder").mkdir()
        first = integration.ui_fingerprint(str(tmp_path))
        assert first == integration.ui_fingerprint(str(tmp_path))
        assert len(first) == 12

        (tmp_path / "a.js").write_text("two", encoding="utf-8")
        second = integration.ui_fingerprint(str(tmp_path))
        (tmp_path / "b.js").write_text("", encoding="utf-8")
        third = integration.ui_fingerprint(str(tmp_path))
        (tmp_path / "b.js").rename(tmp_path / "c.js")
        assert len({first, second, third, integration.ui_fingerprint(str(tmp_path))}) == 4
        assert integration.ui_url(first) == f"/haanim/ui-{first}"
