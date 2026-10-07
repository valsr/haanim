"""Tests for the ha/services.py module."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.haanim.const import DOMAIN
from custom_components.haanim.ha.services import (
    SERVICES,
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

        registered = [call[0][1] for call in mock_hass.services.async_register.call_args_list]
        assert sorted(registered) == sorted(SERVICES)
        assert len(SERVICES) == 11

    async def test_async_teardown_removes_services(
        self, service_manager: ServiceManager, mock_hass: MagicMock
    ) -> None:
        """Test async_teardown unregisters services."""
        await service_manager.async_setup()
        await service_manager.async_teardown()

        removed = [call[0][1] for call in mock_hass.services.async_remove.call_args_list]
        assert sorted(removed) == sorted(SERVICES)

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
