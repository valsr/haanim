"""Tests for the HAAnim config flow."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim.config_flow import OptionsFlowHandler
from custom_components.haanim.const import DOMAIN


@pytest.fixture
def mock_config_manager() -> Generator[MagicMock, None, None]:
    """Create a mock ConfigManager that passes validation.

    Yields:
        A MagicMock for the ConfigManager.
    """
    with patch("custom_components.haanim.config_flow.get_config_manager") as mock_get:
        mock_manager = MagicMock()
        mock_manager.setup = MagicMock()
        mock_manager.validate_script_path = MagicMock(return_value=(True, None))
        mock_manager.get_defaults = MagicMock(
            return_value={
                "name": "HAAnim",
                "script_path": "/config/haanim",
                "allow_all_imports": False,
                "import_allowlist": [],
            }
        )
        # Return a proper voluptuous schema so input validation works correctly
        mock_manager.generate_setup_schema = MagicMock(
            return_value=vol.Schema(
                {
                    vol.Optional("name", default="HAAnim"): str,
                    vol.Optional("script_path", default="/config/haanim"): str,
                    vol.Optional("allow_all_imports", default=False): bool,
                }
            )
        )
        mock_get.return_value = mock_manager
        yield mock_manager


@pytest.mark.asyncio
async def test_form(hass: HomeAssistant, mock_config_manager: MagicMock) -> None:
    """Test the config flow form is shown.

    Args:
        hass: Home Assistant instance.
        mock_config_manager: Mock config manager.
    """
    _ = mock_config_manager  # Fixture provides mocking
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"
    assert result.get("errors") is None or result.get("errors") == {}


@pytest.mark.asyncio
async def test_user_input_creates_entry(hass: HomeAssistant, mock_config_manager: MagicMock) -> None:
    """Test user input creates a config entry.

    Args:
        hass: Home Assistant instance.
        mock_config_manager: Mock config manager.
    """
    _ = mock_config_manager  # Fixture provides mocking
    # Start the flow
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Submit user input
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={"name": "Test HAAnim"},
    )

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("title") == "Test HAAnim"


@pytest.mark.asyncio
async def test_user_input_default_name(hass: HomeAssistant, mock_config_manager: MagicMock) -> None:
    """Test user input with default name creates a config entry.

    Args:
        hass: Home Assistant instance.
        mock_config_manager: Mock config manager.
    """
    _ = mock_config_manager  # Fixture provides mocking
    # Start the flow
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    # Submit empty user input (should use defaults)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("title") == "HAAnim"


@pytest.mark.asyncio
async def test_invalid_script_path(hass: HomeAssistant) -> None:
    """Test that invalid script path shows an error.

    Args:
        hass: Home Assistant instance.
    """
    with patch("custom_components.haanim.config_flow.get_config_manager") as mock_get:
        mock_manager = MagicMock()
        mock_manager.setup = MagicMock()
        mock_manager.validate_script_path = MagicMock(return_value=(False, "Path does not exist"))
        mock_get.return_value = mock_manager

        # Start the flow
        result: ConfigFlowResult = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        # Submit user input with invalid path
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input={"name": "Test", "script_path": "/invalid/path"},
        )

        assert result.get("type") == FlowResultType.FORM
        errors = result.get("errors") or {}
        assert errors.get("base") == "invalid_folder"


@pytest.mark.asyncio
async def test_single_instance_only(hass: HomeAssistant, mock_config_manager: MagicMock) -> None:
    """Test that only one instance is allowed.

    Args:
        hass: Home Assistant instance.
        mock_config_manager: Mock config manager.
        mock_config_manager: Mock config manager.
    """

    # Create an existing entry
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, data={"name": "Existing"})
    entry.add_to_hass(hass)

    # Try to create another entry
    result: ConfigFlowResult = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "already_configured"


@pytest.mark.asyncio
async def test_options_flow_init(hass: HomeAssistant) -> None:
    """Test the options flow initialization.

    Args:
        hass: Home Assistant instance.
    """

    # Create an entry with options
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={
            "name": "HAAnim",
            "script_path": "/config/haanim",
            "allow_all_imports": False,
            "import_allowlist": ["datetime", "math"],
        },
        options={},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.haanim.config_flow.get_config_manager") as mock_get:
        mock_manager = MagicMock()
        mock_manager.setup = MagicMock()
        mock_manager.load_from_dict = MagicMock()
        test_data = {
            "script_path": "/config/haanim",
            "allow_all_imports": False,
            "import_allowlist": ["datetime", "math"],
        }
        mock_manager.get = MagicMock(side_effect=test_data.get)
        mock_manager.get_defaults = MagicMock(return_value={
            "import_allowlist": ["datetime", "math", "json"],
        })
        mock_get.return_value = mock_manager

        handler = OptionsFlowHandler(entry)
        handler.hass = hass

        result = await handler.async_step_init(user_input=None)

        assert result.get("type") == FlowResultType.FORM
        assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_submit_valid(hass: HomeAssistant) -> None:
    """Test submitting valid options.

    Args:
        hass: Home Assistant instance.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"name": "HAAnim", "script_path": "/config/haanim"},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.haanim.config_flow.get_config_manager") as mock_get:
        mock_manager = MagicMock()
        mock_manager.setup = MagicMock()
        mock_manager.validate_script_path = MagicMock(return_value=(True, None))
        mock_manager.get = MagicMock(return_value=[])
        mock_get.return_value = mock_manager

        handler = OptionsFlowHandler(entry)
        handler.hass = hass

        result = await handler.async_step_init(user_input={
            "script_path": "/config/haanim",
            "allow_all_imports": True,
            "import_allowlist_str": "datetime, json, math",
        })

        assert result.get("type") == FlowResultType.CREATE_ENTRY
        assert result.get("data", {}).get("allow_all_imports") is True
        assert result.get("data", {}).get("import_allowlist") == ["datetime", "json", "math"]


@pytest.mark.asyncio
async def test_options_flow_invalid_path(hass: HomeAssistant) -> None:
    """Test submitting invalid path in options flow.

    Args:
        hass: Home Assistant instance.
    """

    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=DOMAIN,
        data={"name": "HAAnim", "script_path": "/config/haanim"},
    )
    entry.add_to_hass(hass)

    with patch("custom_components.haanim.config_flow.get_config_manager") as mock_get:
        mock_manager = MagicMock()
        mock_manager.setup = MagicMock()
        mock_manager.validate_script_path = MagicMock(return_value=(False, "Invalid path"))
        test_data = {
            "script_path": "/config/haanim",
            "allow_all_imports": False,
            "import_allowlist": [],
        }
        mock_manager.get = MagicMock(side_effect=test_data.get)
        mock_manager.get_defaults = MagicMock(return_value={"import_allowlist": []})
        mock_get.return_value = mock_manager

        handler = OptionsFlowHandler(entry)
        handler.hass = hass

        result = await handler.async_step_init(user_input={
            "script_path": "/invalid/path",
            "allow_all_imports": False,
        })

        assert result.get("type") == FlowResultType.FORM
        errors = result.get("errors") or {}
        assert errors.get("script_path") == "invalid_path"
