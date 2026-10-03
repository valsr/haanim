"""Tests for the ha/services.py module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.haanim.const import (
    ATTRIBUTE_ACTION_NAME,
    ATTRIBUTE_AUTOMATION_ID,
    DOMAIN,
    SERVICE_GET_CONFIG,
    SERVICE_LIST_ACTIONS,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_RELOAD_AUTOMATIONS,
    SERVICE_RUN_ACTION,
)
from custom_components.haanim.ha.services import (
    ServiceManager,
    service_call,
    service_call_sync,
)


class TestServiceManager:
    """Tests for ServiceManager class."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.services.async_register = MagicMock()
        hass.services.async_remove = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.async_add_executor_job = AsyncMock()
        hass.data = {}
        return hass

    @pytest.fixture
    def service_manager(self, mock_hass: MagicMock) -> ServiceManager:
        """Create a ServiceManager instance."""
        return ServiceManager(mock_hass)

    async def test_async_setup_registers_services(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test async_setup registers all core services."""
        await service_manager.async_setup()

        # Should register 5 core services
        assert mock_hass.services.async_register.call_count == 5

        # Get all registered service names
        registered = [call[0][1] for call in mock_hass.services.async_register.call_args_list]
        assert SERVICE_RUN_ACTION in registered
        assert SERVICE_RELOAD_AUTOMATIONS in registered
        assert SERVICE_LIST_AUTOMATIONS in registered
        assert SERVICE_LIST_ACTIONS in registered
        assert SERVICE_GET_CONFIG in registered

    async def test_async_teardown_removes_services(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test async_teardown unregisters services."""
        await service_manager.async_setup()
        await service_manager.async_teardown()

        # Should remove 5 core services
        assert mock_hass.services.async_remove.call_count == 5

    async def test_call(self, service_manager: ServiceManager, mock_hass: MagicMock) -> None:
        """Test calling a service."""
        mock_hass.services.async_call.return_value = {"result": "ok"}

        result = await service_manager.call("light", "turn_on", {"entity_id": "light.test"}, blocking=True)

        mock_hass.services.async_call.assert_called_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.test"},
            blocking=True,
            return_response=False,
        )
        assert result == {"result": "ok"}

    async def test_call_with_return_response(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test calling a service with return_response."""
        await service_manager.call("light", "turn_on", return_response=True)

        mock_hass.services.async_call.assert_called_once_with(
            "light",
            "turn_on",
            None,
            blocking=True,
            return_response=True,
        )

    async def test_async_register_service(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test registering a custom service."""
        handler = AsyncMock()
        schema = vol.Schema({vol.Required("value"): int})

        await service_manager.async_register_service("my_service", handler, schema, "My service description")

        mock_hass.services.async_register.assert_called_once()
        assert "my_service" in service_manager._registered_services

    async def test_async_register_service_replaces_existing(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test registering an existing service replaces it."""
        handler1 = AsyncMock()
        handler2 = AsyncMock()

        await service_manager.async_register_service("my_service", handler1)
        await service_manager.async_register_service("my_service", handler2)

        # Should have called unregister for the first one
        mock_hass.services.async_remove.assert_called_once_with(DOMAIN, "my_service")

    async def test_async_unregister_service(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test unregistering a service."""
        handler = AsyncMock()
        await service_manager.async_register_service("my_service", handler)

        result = await service_manager.async_unregister_service("my_service")

        assert result is True
        assert "my_service" not in service_manager._registered_services
        mock_hass.services.async_remove.assert_called_with(DOMAIN, "my_service")

    async def test_async_unregister_service_not_registered(self, service_manager: ServiceManager) -> None:
        """Test unregistering non-existent service returns False."""
        result = await service_manager.async_unregister_service("nonexistent")
        assert result is False

    def test_get_registered_services(self, service_manager: ServiceManager) -> None:
        """Test getting list of registered services."""
        service_manager._registered_services = {
            "service1": {},
            "service2": {},
        }

        result = service_manager.get_registered_services()
        assert result == ["service1", "service2"]

    def test_get_registered_services_empty(self, service_manager: ServiceManager) -> None:
        """Test getting list when no services registered."""
        result = service_manager.get_registered_services()
        assert result == []


class TestServiceHandlers:
    """Tests for service handler methods."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.services.async_register = MagicMock()
        hass.services.async_remove = MagicMock()
        hass.data = {}
        return hass

    @pytest.fixture
    def service_manager(self, mock_hass: MagicMock) -> ServiceManager:
        """Create a ServiceManager instance."""
        return ServiceManager(mock_hass)

    @pytest.fixture
    def mock_service_call(self) -> MagicMock:
        """Create a mock service call."""
        call = MagicMock()
        call.data = {}
        return call

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_run_action(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_run_action calls automation manager."""
        mock_manager = MagicMock()
        mock_manager.async_run_action = AsyncMock()
        mock_get_manager.return_value = mock_manager

        mock_service_call.data = {
            ATTRIBUTE_AUTOMATION_ID: "test_automation",
            ATTRIBUTE_ACTION_NAME: "test_action",
        }

        await service_manager._handle_run_action(mock_service_call)

        mock_manager.async_run_action.assert_called_once_with("test_automation", "test_action")

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_run_action_no_manager(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_run_action when manager not available."""
        mock_get_manager.return_value = None
        mock_service_call.data = {
            ATTRIBUTE_AUTOMATION_ID: "test_automation",
            ATTRIBUTE_ACTION_NAME: "test_action",
        }

        # Should not raise, just log error
        await service_manager._handle_run_action(mock_service_call)

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_reload_automations(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_reload_automations calls automation manager."""
        mock_manager = MagicMock()
        mock_manager.async_reload_all_automations = AsyncMock()
        mock_get_manager.return_value = mock_manager

        await service_manager._handle_reload_automations(mock_service_call)

        mock_manager.async_reload_all_automations.assert_called_once()

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_list_automations(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_list_automations returns automation info."""
        mock_manager = MagicMock()
        mock_metadata = MagicMock()
        mock_metadata.id = "test_automation"
        mock_metadata.path = "/path/to/automation.py"
        mock_metadata.actions = []
        mock_metadata.triggers = []
        mock_metadata.enabled = True
        mock_manager.get_all_metadata.return_value = [mock_metadata]
        mock_get_manager.return_value = mock_manager

        result = await service_manager._handle_list_automations(mock_service_call)

        assert "automations" in result
        assert len(result["automations"]) == 1
        assert result["automations"][0]["name"] == "test_automation"

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_list_automations_no_manager(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_list_automations when manager not available."""
        mock_get_manager.return_value = None

        result = await service_manager._handle_list_automations(mock_service_call)

        assert result == {"automations": []}

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_list_actions(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_list_actions returns action info."""
        mock_manager = MagicMock()
        mock_action = MagicMock()
        mock_action.name = "my_action"
        mock_action.func_name = "my_func"
        mock_action.automation_id = "test_automation"
        mock_action.description = "An action"
        mock_manager.get_all_actions.return_value = [mock_action]
        mock_get_manager.return_value = mock_manager

        result = await service_manager._handle_list_actions(mock_service_call)

        assert "actions" in result
        assert len(result["actions"]) == 1
        assert result["actions"][0]["name"] == "my_action"

    @patch("custom_components.haanim.ha.services.async_get_manager")
    async def test_handle_list_actions_filtered_by_automation(
        self,
        mock_get_manager: MagicMock,
        service_manager: ServiceManager,
        mock_service_call: MagicMock,
    ) -> None:
        """Test _handle_list_actions filters by automation name."""
        mock_manager = MagicMock()
        mock_action1 = MagicMock()
        mock_action1.name = "action1"
        mock_action1.func_name = "func1"
        mock_action1.automation_id = "automation1"
        mock_action1.description = ""
        mock_action2 = MagicMock()
        mock_action2.name = "action2"
        mock_action2.func_name = "func2"
        mock_action2.automation_id = "automation2"
        mock_action2.description = ""
        mock_manager.get_all_actions.return_value = [mock_action1, mock_action2]
        mock_get_manager.return_value = mock_manager

        mock_service_call.data = {ATTRIBUTE_AUTOMATION_ID: "automation1"}

        result = await service_manager._handle_list_actions(mock_service_call)

        assert len(result["actions"]) == 1
        assert result["actions"][0]["automation_id"] == "automation1"


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    async def test_service_call(self) -> None:
        """Test service_call function."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        await service_call(hass, "light", "turn_on", {"entity_id": "light.test"})

        hass.services.async_call.assert_called_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.test"},
            blocking=True,
        )

    async def test_service_call_non_blocking(self) -> None:
        """Test service_call with non-blocking."""
        hass = MagicMock()
        hass.services.async_call = AsyncMock()

        await service_call(hass, "light", "turn_on", blocking=False)

        hass.services.async_call.assert_called_once_with(
            "light",
            "turn_on",
            None,
            blocking=False,
        )

    def test_service_call_sync(self) -> None:
        """Test service_call_sync function."""
        hass = MagicMock()

        service_call_sync(hass, "light", "turn_on", {"entity_id": "light.test"})

        hass.services.call.assert_called_once_with(
            "light",
            "turn_on",
            {"entity_id": "light.test"},
            blocking=True,
        )


class TestServiceHandler:
    """Tests for service handler wrapper functionality."""

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.services.async_register = MagicMock()
        hass.services.async_remove = MagicMock()
        hass.async_add_executor_job = AsyncMock()
        hass.data = {}
        return hass

    @pytest.fixture
    def service_manager(self, mock_hass: MagicMock) -> ServiceManager:
        """Create a ServiceManager instance."""
        return ServiceManager(mock_hass)

    async def test_service_handler_calls_async_handler(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test service handler calls async handler correctly."""
        handler = AsyncMock(return_value="result")

        await service_manager.async_register_service("my_service", handler)

        # Get the registered handler - uses positional args: domain, service, handler
        registered_handler = mock_hass.services.async_register.call_args[0][2]

        # Create mock call
        mock_call = MagicMock()
        mock_call.data = {"arg1": "value1"}

        result = await registered_handler(mock_call)

        handler.assert_called_once_with(arg1="value1")
        assert result == "result"

    async def test_service_handler_calls_sync_handler(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test service handler calls a sync handler on the event loop, not in a thread."""

        def sync_handler(**kwargs: Any) -> str:
            return "sync_result"

        await service_manager.async_register_service("my_service", sync_handler)

        # Get the registered handler - uses positional args
        registered_handler = mock_hass.services.async_register.call_args[0][2]

        # Create mock call
        mock_call = MagicMock()
        mock_call.data = {}

        result = await registered_handler(mock_call)

        mock_hass.async_add_executor_job.assert_not_called()
        assert result == "sync_result"
