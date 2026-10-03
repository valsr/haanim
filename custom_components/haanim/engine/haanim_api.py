"""HAAnim API providing access to Home Assistant entities, services, and scripts.

This module implements the `haa` instance that is injected into script namespaces,
providing a clean API for interacting with Home Assistant and other scripts.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.haanim.engine.errors import (
    NonExistingEntityError,
    NonExistingScriptError,
    NonExistingServiceError,
)

if TYPE_CHECKING:
    from custom_components.haanim.script_manager import ScriptManager

_LOGGER = logging.getLogger(__name__)


class HAAnimServiceCall:
    """Result object from a service call."""

    def __init__(
        self,
        domain: str,
        service: str,
        call_time: datetime,
    ) -> None:
        """Initialize service call result.

        Args:
            domain: Service domain.
            service: Service name.
            call_time: When the service was called.
        """
        self.domain = domain
        self.service = service
        self.call_time = call_time
        self.complete_time: datetime | None = None
        self.success = False
        self.error: str | None = None
        self.error_code: str | None = None
        self.response_data: dict[str, Any] = {}

    def mark_success(self, response_data: dict[str, Any] | None = None) -> None:
        """Mark the service call as successful.

        Args:
            response_data: Optional response data from the service.
        """
        self.complete_time = datetime.now()
        self.success = True
        if response_data:
            self.response_data = response_data

    def mark_failure(self, error: str, error_code: str | None = None) -> None:
        """Mark the service call as failed.

        Args:
            error: Error message.
            error_code: Optional error code.
        """
        self.complete_time = datetime.now()
        self.success = False
        self.error = error
        self.error_code = error_code


class HAAnimServiceProxy:
    """Proxy object for a Home Assistant service."""

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        service: str,
    ) -> None:
        """Initialize service proxy.

        Args:
            hass: Home Assistant instance.
            domain: Service domain.
            service: Service name.
        """
        self._hass = hass
        self.domain = domain
        self.name = service
        self._service_key = f"{domain}.{service}"

        # Get service metadata - service_data is a Service object, not a dict
        services_dict = hass.services.async_services().get(domain, {})
        service_data = services_dict.get(service)
        if service_data:
            # Access Service object attributes, not dict keys
            self.description = service_data.description or ""  # type: ignore[union-attr]
            self.param_info = service_data.fields or {}  # type: ignore[union-attr]
        else:
            self.description = ""
            self.param_info = {}

    async def call(self, **params: Any) -> HAAnimServiceCall:
        """Call the service with the given parameters.

        Args:
            **params: Service parameters.

        Returns:
            HAAnimServiceCall result object.

        Raises:
            NonExistingServiceError: If the service doesn't exist.
        """
        result = HAAnimServiceCall(self.domain, self.name, datetime.now())

        try:
            # Check if service exists
            if not self._hass.services.has_service(self.domain, self.name):
                raise NonExistingServiceError(self.domain, self.name)

            # Call the service
            response = await self._hass.services.async_call(
                self.domain,
                self.name,
                params,
                blocking=True,
                return_response=True,
            )

            # Mark success - response is either None or a dict
            if response is not None and isinstance(response, dict):
                result.mark_success(response)
            else:
                result.mark_success()

        except NonExistingServiceError:
            raise
        except HomeAssistantError as err:
            result.mark_failure(str(err), "home_assistant_error")
        except Exception as err:  # pylint: disable=broad-exception-caught
            result.mark_failure(str(err), "unknown_error")
            _LOGGER.exception("Unexpected error calling service %s", self._service_key)

        return result

    async def __call__(self, **params: Any) -> HAAnimServiceCall:
        """Allow calling the proxy directly.

        Args:
            **params: Service parameters.

        Returns:
            HAAnimServiceCall result object.
        """
        return await self.call(**params)


class HAAnimScriptProxy:
    """Proxy object for interacting with another script."""

    def __init__(
        self,
        script_id: str,
        script_manager: ScriptManager,
    ) -> None:
        """Initialize script proxy.

        Args:
            script_id: The script ID.
            script_manager: The script manager instance.
        """
        self.id = script_id
        self._manager = script_manager

    @property
    def state(self) -> str:
        """Get the current state of the script."""
        context = self._manager._contexts.get(self.id)
        if not context:
            return "unavailable"
        return context._metadata.state or "off" if context._metadata else "off"

    @property
    def message(self) -> str:
        """Get the script's status message."""
        context = self._manager._contexts.get(self.id)
        if not context:
            return ""
        return context._metadata.message or "" if context._metadata else ""

    @property
    def file_path(self) -> str:
        """Get the script's file path."""
        context = self._manager._contexts.get(self.id)
        if not context:
            return ""
        return context.script_path

    @property
    def load_time(self) -> datetime | None:
        """Get when the script was loaded."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.loaded_at

    @property
    def run_time(self) -> datetime | None:
        """Get when the script was last started."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.run_time if hasattr(context._metadata, "run_time") else None

    @property
    def actions(self) -> list[str]:
        """Get list of action names."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return []
        return [action.name for action in context._metadata.actions]

    @property
    def last_action_time(self) -> datetime | None:
        """Get timestamp of last action execution."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.last_action_time if hasattr(context._metadata, "last_action_time") else None

    @property
    def error_message(self) -> str | None:
        """Get error message if script is in error state."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.error

    def is_running(self) -> bool:
        """Check if the script is running."""
        return self.state == "on"

    def is_enabled(self) -> bool:
        """Check if the script is enabled."""
        context = self._manager._contexts.get(self.id)
        if not context or not context._metadata:
            return False
        return context._metadata.enabled

    async def call(self, action_name: str, **kwargs: Any) -> Any:
        """Call an action in this script.

        Args:
            action_name: Name of the action to call.
            **kwargs: Arguments to pass to the action.

        Returns:
            The result of the action call.

        Raises:
            NonExistingScriptError: If the script doesn't exist.
            ScriptNotLoadedError: If the script is not loaded.
            ActionNotFoundError: If the action doesn't exist.
        """
        return await self._manager.async_call_action(self.id, action_name, **kwargs)

    async def enable(self) -> None:
        """Enable and start the script."""
        await self._manager.async_enable_script(self.id)

    async def disable(self) -> None:
        """Disable and stop the script."""
        await self._manager.async_disable_script(self.id)

    async def start(self) -> None:
        """Start the script if enabled."""
        await self._manager.async_start_script(self.id)

    async def stop(self) -> None:
        """Stop the script if running."""
        await self._manager.async_stop_script(self.id)

    async def restart(self) -> None:
        """Restart the script."""
        await self._manager.async_restart_script(self.id)


class EntityProxy:
    """Proxy for accessing entity states and attributes."""

    def __init__(self, hass: HomeAssistant, domain: str) -> None:
        """Initialize entity proxy for a domain.

        Args:
            hass: Home Assistant instance.
            domain: Entity domain (e.g., 'sensor', 'light').
        """
        self._hass = hass
        self._domain = domain

    def __getattr__(self, entity_name: str) -> str | None:
        """Get entity state by name.

        Args:
            entity_name: The entity name (without domain prefix).

        Returns:
            The entity state as a string, or None if not found.
        """
        entity_id = f"{self._domain}.{entity_name}"
        state = self._hass.states.get(entity_id)
        return state.state if state else None

    def __getitem__(self, entity_name: str) -> dict[str, Any]:
        """Get entity with full state and attributes.

        Args:
            entity_name: The entity name (without domain prefix).

        Returns:
            Dictionary with state and attributes.

        Raises:
            NonExistingEntityError: If entity doesn't exist.
        """
        entity_id = f"{self._domain}.{entity_name}"
        state = self._hass.states.get(entity_id)
        if not state:
            raise NonExistingEntityError(entity_id)
        return {"state": state.state, **state.attributes}


class ServiceDomainProxy:
    """Proxy for accessing services in a domain."""

    def __init__(self, hass: HomeAssistant, domain: str) -> None:
        """Initialize service domain proxy.

        Args:
            hass: Home Assistant instance.
            domain: Service domain.
        """
        self._hass = hass
        self._domain = domain

    def __getattr__(self, service_name: str) -> HAAnimServiceProxy:
        """Get a service proxy by name.

        Args:
            service_name: The service name.

        Returns:
            HAAnimServiceProxy for the service.
        """
        return HAAnimServiceProxy(self._hass, self._domain, service_name)


class HAAnim:
    """Main HAAnim API object providing access to Home Assistant and scripts.

    This object is injected into script namespaces as `haa` and provides
    a clean interface for:
    - Accessing entity states and attributes
    - Calling Home Assistant services
    - Interacting with other scripts
    - Persistent storage
    - Script control
    """

    def __init__(
        self,
        hass: HomeAssistant,
        script_id: str,
        script_manager: ScriptManager,
        storage_path: str,
    ) -> None:
        """Initialize HAAnim API.

        Args:
            hass: Home Assistant instance.
            script_id: The current script's ID.
            script_manager: The script manager instance.
            storage_path: Path to storage directory.
        """
        self._hass = hass
        self._script_id = script_id
        self._manager = script_manager
        self._storage_path = Path(storage_path)
        self._storage_file = self._storage_path / f"{script_id}.json"
        self._storage_lock = asyncio.Lock()
        self._storage_cache: dict[str, str] = {}

        # Ensure storage directory exists
        self._storage_path.mkdir(parents=True, exist_ok=True)

        # Load storage cache
        self._load_storage()

    @property
    def id(self) -> str:
        """Get the current script's ID."""
        return self._script_id

    def __getattr__(self, domain: str) -> EntityProxy | _ServiceAccessor:
        """Get entity proxy for a domain.

        Args:
            domain: Entity domain.

        Returns:
            EntityProxy for accessing entities in the domain, or _ServiceAccessor for 'service'.
        """
        # Check if it's a service access
        if domain == "service":
            return self._ServiceAccessor(self._hass)  # type: ignore[return-value]
        return EntityProxy(self._hass, domain)

    class _ServiceAccessor:
        """Internal accessor for services."""

        def __init__(self, hass: HomeAssistant) -> None:
            """Initialize service accessor.

            Args:
                hass: Home Assistant instance.
            """
            self._hass = hass

        def __getattr__(self, domain: str) -> ServiceDomainProxy:
            """Get service domain proxy.

            Args:
                domain: Service domain.

            Returns:
                ServiceDomainProxy for the domain.
            """
            return ServiceDomainProxy(self._hass, domain)

    @property
    def service(self) -> _ServiceAccessor:
        """Get service accessor."""
        return self._ServiceAccessor(self._hass)

    def services(self) -> list[HAAnimServiceProxy]:
        """Get list of all available service proxies.

        Returns:
            List of HAAnimServiceProxy objects.
        """
        result = []
        for domain, services in self._hass.services.async_services().items():
            for service_name in services:
                result.append(HAAnimServiceProxy(self._hass, domain, service_name))
        return result

    def script(self, script_id: str) -> HAAnimScriptProxy:
        """Get a proxy for another script.

        Args:
            script_id: The script ID.

        Returns:
            HAAnimScriptProxy for the script.

        Raises:
            NonExistingScriptError: If script doesn't exist.
        """
        if script_id not in self._manager._contexts:
            raise NonExistingScriptError(script_id)
        return HAAnimScriptProxy(script_id, self._manager)

    def scripts(self) -> list[HAAnimScriptProxy]:
        """Get list of all script proxies.

        Returns:
            List of HAAnimScriptProxy objects for all loaded scripts.
        """
        return [HAAnimScriptProxy(script_id, self._manager) for script_id in self._manager._contexts]

    async def call(self, action_name: str, **kwargs: Any) -> Any:
        """Call an action in the current script.

        Args:
            action_name: Name of the action.
            **kwargs: Arguments to pass to the action.

        Returns:
            The result of the action call.
        """
        return await self._manager.async_call_action(self._script_id, action_name, **kwargs)

    async def enable(self) -> None:
        """Enable the current script."""
        await self._manager.async_enable_script(self._script_id)

    async def disable(self) -> None:
        """Disable the current script."""
        await self._manager.async_disable_script(self._script_id)

    async def stop(self) -> None:
        """Stop the current script."""
        await self._manager.async_stop_script(self._script_id)

    async def restart(self) -> None:
        """Restart the current script."""
        await self._manager.async_restart_script(self._script_id)

    def set_message(self, message: str) -> None:
        """Set the script's status message.

        Args:
            message: The status message to set.
        """
        context = self._manager._contexts.get(self._script_id)
        if context and context._metadata:
            context._metadata.message = message

    # Storage API

    def _load_storage(self) -> None:
        """Load storage from disk."""
        if self._storage_file.exists():
            try:
                with open(self._storage_file, "r", encoding="utf-8") as f:
                    self._storage_cache = json.load(f)
            except Exception as err:  # pylint: disable=broad-exception-caught
                _LOGGER.error("Failed to load storage for %s: %s", self._script_id, err)
                self._storage_cache = {}
        else:
            self._storage_cache = {}

    def _save_storage(self) -> None:
        """Save storage to disk."""
        try:
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump(self._storage_cache, f, indent=2)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Failed to save storage for %s: %s", self._script_id, err)

    async def set_variable(self, key: str, value: str) -> None:
        """Store a persistent value.

        Args:
            key: Variable key.
            value: Variable value (must be a string).
        """
        async with self._storage_lock:
            self._storage_cache[key] = value
            self._save_storage()

    def get_variable(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a persistent value.

        Args:
            key: Variable key.
            default: Default value if key doesn't exist.

        Returns:
            The stored value or default.
        """
        return self._storage_cache.get(key, default)

    async def unset_variable(self, key: str) -> None:
        """Remove a single variable.

        Args:
            key: Variable key to remove.
        """
        async with self._storage_lock:
            if key in self._storage_cache:
                del self._storage_cache[key]
                self._save_storage()

    async def clear_variables(self) -> None:
        """Clear all stored variables."""
        async with self._storage_lock:
            self._storage_cache.clear()
            self._save_storage()
