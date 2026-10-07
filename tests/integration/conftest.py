"""Fixtures for the Home Assistant integration tests.

The Home Assistant test plugin itself is loaded by ``tests/conftest.py``, because
pytest only accepts ``pytest_plugins`` in the top-level conftest.
"""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import CONF_NAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.haanim.const import DOMAIN


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable custom integrations for all tests.

    Args:
        enable_custom_integrations: Fixture that enables custom integrations.
    """
    # This fixture automatically enables custom integrations for all tests


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry.

    Returns:
        A mock configuration entry for testing.
    """
    return MockConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="HAAnim",
        data={CONF_NAME: "HAAnim"},
        options={},
        source="user",
        entry_id="test_entry_id",
        unique_id="haanim_unique_id",
    )


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock, None, None]:
    """Override async_setup_entry for testing.

    Yields:
        An AsyncMock that replaces async_setup_entry.
    """
    with patch(
        "custom_components.haanim.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        mock_setup.return_value = True
        yield mock_setup


@pytest.fixture
def mock_unload_entry() -> Generator[AsyncMock, None, None]:
    """Override async_unload_entry for testing.

    Yields:
        An AsyncMock that replaces async_unload_entry.
    """
    with patch(
        "custom_components.haanim.async_unload_entry",
        return_value=True,
    ) as mock_unload:
        mock_unload.return_value = True
        yield mock_unload


@pytest.fixture
def mock_automation_manager() -> Generator[MagicMock, None, None]:
    """Create a mock AutomationManager for testing.

    Yields:
        A MagicMock that replaces AutomationManager.
    """
    with (
        patch("custom_components.haanim.AutomationManager") as mock_manager_class,
        patch("custom_components.haanim.StateManager") as mock_state_class,
        patch("custom_components.haanim.EventManager") as mock_event_class,
        patch("custom_components.haanim.ServiceManager") as mock_service_class,
        patch("custom_components.haanim.TriggerManager") as mock_trigger_class,
        patch("custom_components.haanim.get_config_manager") as mock_config_manager,
        patch("custom_components.haanim.async_register_api"),
        patch("custom_components.haanim._async_register_panel", new=AsyncMock()),
        patch("custom_components.haanim._async_unregister_panel", new=AsyncMock()),
    ):
        # Mock ConfigManager
        config_mock = MagicMock()
        config_mock.setup = MagicMock()
        mock_config_manager.return_value = config_mock

        # Mock StateManager
        state_mock = MagicMock()
        state_mock.async_setup = AsyncMock(return_value=None)
        state_mock.async_teardown = AsyncMock(return_value=None)
        mock_state_class.return_value = state_mock

        # Mock EventManager
        event_mock = MagicMock()
        event_mock.async_setup = AsyncMock(return_value=None)
        event_mock.async_teardown = AsyncMock(return_value=None)
        mock_event_class.return_value = event_mock

        # Mock ServiceManager
        service_mock = MagicMock()
        service_mock.async_setup = AsyncMock(return_value=None)
        service_mock.async_teardown = AsyncMock(return_value=None)
        mock_service_class.return_value = service_mock

        # Mock TriggerManager
        trigger_mock = MagicMock()
        trigger_mock.async_setup = AsyncMock(return_value=None)
        trigger_mock.async_teardown = AsyncMock(return_value=None)
        mock_trigger_class.return_value = trigger_mock

        # Mock AutomationManager
        mock_manager = MagicMock()
        mock_manager.async_setup = AsyncMock(return_value=None)
        mock_manager.async_load_all_automations = AsyncMock(return_value=None)
        mock_manager.async_shutdown = AsyncMock(return_value=None)
        mock_manager.get_all_contexts = MagicMock(return_value=[])
        mock_manager.get_failed_automations = MagicMock(return_value={})
        mock_manager_class.return_value = mock_manager
        yield mock_manager


@pytest.fixture
def mock_action_pool() -> Generator[MagicMock, None, None]:
    """Create a mock ActionWorkerPool for testing.

    Yields:
        A MagicMock that replaces ActionWorkerPool.
    """
    with patch("haanim.engine.action_pool.ActionWorkerPool") as mock_pool_class:
        mock_pool = MagicMock()
        mock_pool.submit_action = AsyncMock(return_value=None)
        mock_pool.shutdown = AsyncMock(return_value=None)
        mock_pool.max_workers = 20
        mock_pool.active_count = 0
        mock_pool.available_workers = 20
        mock_pool.is_shutting_down = False
        mock_pool_class.return_value = mock_pool
        yield mock_pool
