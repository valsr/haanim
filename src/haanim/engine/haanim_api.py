"""HAAnim API providing access to Home Assistant entities, services, and automations.

This module implements the `haa` instance that is injected into automation namespaces,
providing a clean API for interacting with Home Assistant and other automations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from haanim.engine.errors import (
    NonExistingAutomationError,
    NonExistingEntityError,
    NonExistingServiceError,
    ServiceCallError,
)

if TYPE_CHECKING:
    from haanim.interfaces import AutomationRegistry, Host

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

    def mark_success(self, complete_time: datetime, response_data: dict[str, Any] | None = None) -> None:
        """Mark the service call as successful.

        Args:
            complete_time: When the call finished.
            response_data: Optional response data from the service.
        """
        self.complete_time = complete_time
        self.success = True
        if response_data:
            self.response_data = response_data

    def mark_failure(self, complete_time: datetime, error: str, error_code: str | None = None) -> None:
        """Mark the service call as failed.

        Args:
            complete_time: When the call finished.
            error: Error message.
            error_code: Optional error code.
        """
        self.complete_time = complete_time
        self.success = False
        self.error = error
        self.error_code = error_code


class HAAnimServiceProxy:
    """Proxy object for a Home Assistant service."""

    def __init__(
        self,
        host: Host,
        domain: str,
        service: str,
    ) -> None:
        """Initialize service proxy.

        Args:
            host: The host the engine runs in.
            domain: Service domain.
            service: Service name.
        """
        self._host = host
        self.domain = domain
        self.name = service
        self._service_key = f"{domain}.{service}"

        self.description = ""
        self.param_info: dict[str, Any] = {}
        for info in host.services.services():
            if info.domain == domain and info.name == service:
                self.description = info.description
                self.param_info = dict(info.fields)
                break

    async def call(self, **params: Any) -> HAAnimServiceCall:
        """Call the service with the given parameters.

        Args:
            **params: Service parameters.

        Returns:
            HAAnimServiceCall result object.

        Raises:
            NonExistingServiceError: If the service doesn't exist.
        """
        clock = self._host.clock
        result = HAAnimServiceCall(self.domain, self.name, clock.now())

        try:
            # Check if service exists
            if not self._host.services.has_service(self.domain, self.name):
                raise NonExistingServiceError(self.domain, self.name)

            # Call the service
            response = await self._host.services.async_call(
                self.domain,
                self.name,
                params,
                return_response=True,
            )

            # Mark success - response is either None or a dict
            if response is not None:
                result.mark_success(clock.now(), response)
            else:
                result.mark_success(clock.now())

        except NonExistingServiceError:
            raise
        except ServiceCallError as err:
            result.mark_failure(clock.now(), err.reason, "home_assistant_error")
        except Exception as err:  # pylint: disable=broad-exception-caught
            result.mark_failure(clock.now(), str(err), "unknown_error")
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


class HAAnimAutomationProxy:
    """Proxy object for interacting with another automation."""

    def __init__(
        self,
        automation_id: str,
        automation_manager: AutomationRegistry,
    ) -> None:
        """Initialize automation proxy.

        Args:
            automation_id: The automation ID.
            automation_manager: The automation manager instance.
        """
        self.id = automation_id
        self._manager = automation_manager

    @property
    def state(self) -> str:
        """Get the current state of the automation: ``unavailable``, ``off``, ``on`` or ``error``."""
        return self._manager.automation_state(self.id)

    @property
    def message(self) -> str:
        """Get the automation's status message."""
        context = self._manager.get_context_by_name(self.id)
        if not context:
            return ""
        return context._metadata.message or "" if context._metadata else ""

    @property
    def file_path(self) -> str:
        """Get the automation's file path."""
        context = self._manager.get_context_by_name(self.id)
        if not context:
            return ""
        return context.automation_path

    @property
    def load_time(self) -> datetime | None:
        """Get when the automation was loaded."""
        context = self._manager.get_context_by_name(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.loaded_at

    @property
    def run_time(self) -> datetime | None:
        """Get when the automation was last started."""
        context = self._manager.get_context_by_name(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.run_time if hasattr(context._metadata, "run_time") else None

    @property
    def actions(self) -> list[str]:
        """Get list of action names."""
        context = self._manager.get_context_by_name(self.id)
        if not context or not context._metadata:
            return []
        return [action.name for action in context._metadata.actions]

    @property
    def last_action_time(self) -> datetime | None:
        """Get timestamp of last action execution."""
        context = self._manager.get_context_by_name(self.id)
        if not context or not context._metadata:
            return None
        return context._metadata.last_action_time if hasattr(context._metadata, "last_action_time") else None

    @property
    def error_message(self) -> str | None:
        """Get why the automation is in the ``error`` state, or None if it is not."""
        return self._manager.automation_message(self.id)

    def is_running(self) -> bool:
        """Check if the automation is running."""
        return self.state == "on"

    def is_enabled(self) -> bool:
        """Check if the automation is enabled."""
        return self._manager.is_automation_enabled(self.id)

    async def call(self, action_name: str, **kwargs: Any) -> Any:
        """Call an action in this automation.

        Args:
            action_name: Name of the action to call.
            **kwargs: Arguments to pass to the action.

        Returns:
            The result of the action call.

        Raises:
            NonExistingAutomationError: If the automation doesn't exist.
            AutomationNotLoadedError: If the automation is not loaded.
            ActionNotFoundError: If the action doesn't exist.
        """
        return await self._manager.async_call_action(self.id, action_name, **kwargs)

    async def enable(self) -> None:
        """Enable and start the automation."""
        await self._manager.async_enable_automation(self.id)

    async def disable(self) -> None:
        """Disable and stop the automation."""
        await self._manager.async_disable_automation(self.id)

    async def start(self) -> None:
        """Start the automation if enabled."""
        await self._manager.async_start_automation(self.id)

    async def stop(self) -> None:
        """Stop the automation if running."""
        await self._manager.async_stop_automation(self.id)

    async def restart(self) -> None:
        """Restart the automation."""
        await self._manager.async_restart_automation(self.id)


class EntityProxy:
    """Proxy for accessing entity states and attributes."""

    def __init__(self, host: Host, domain: str) -> None:
        """Initialize entity proxy for a domain.

        Args:
            host: The host the engine runs in.
            domain: Entity domain (e.g., 'sensor', 'light').
        """
        self._host = host
        self._domain = domain

    def __getattr__(self, entity_name: str) -> str | None:
        """Get entity state by name.

        Args:
            entity_name: The entity name (without domain prefix).

        Returns:
            The entity state as a string, or None if not found.
        """
        entity_id = f"{self._domain}.{entity_name}"
        return self._host.states.get(entity_id).state

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
        if not self._host.states.exists(entity_id):
            raise NonExistingEntityError(entity_id)
        state = self._host.states.get(entity_id)
        return {"state": state.state, **state.attributes}


class ServiceDomainProxy:
    """Proxy for accessing services in a domain."""

    def __init__(self, host: Host, domain: str) -> None:
        """Initialize service domain proxy.

        Args:
            host: The host the engine runs in.
            domain: Service domain.
        """
        self._host = host
        self._domain = domain

    def __getattr__(self, service_name: str) -> HAAnimServiceProxy:
        """Get a service proxy by name.

        Args:
            service_name: The service name.

        Returns:
            HAAnimServiceProxy for the service.
        """
        return HAAnimServiceProxy(self._host, self._domain, service_name)


class HAAnim:
    """Main HAAnim API object providing access to Home Assistant and automations.

    This object is injected into automation namespaces as `haa` and provides
    a clean interface for:
    - Accessing entity states and attributes
    - Calling Home Assistant services
    - Interacting with other automations
    - Persistent storage
    - Automation control
    """

    def __init__(
        self,
        host: Host,
        automation_id: str,
        automation_manager: AutomationRegistry,
        storage_path: str,
    ) -> None:
        """Initialize HAAnim API.

        Args:
            host: The host the engine runs in.
            automation_id: The current automation's ID.
            automation_manager: The automation manager instance.
            storage_path: Path to storage directory.
        """
        self._host = host
        self._automation_id = automation_id
        self._manager = automation_manager
        self._storage_path = Path(storage_path)
        self._storage_file = self._storage_path / f"{automation_id}.json"
        self._storage_lock = asyncio.Lock()
        self._storage_cache: dict[str, str] = {}

        # Ensure storage directory exists
        self._storage_path.mkdir(parents=True, exist_ok=True)

        # Load storage cache
        self._load_storage()

    @property
    def id(self) -> str:
        """Get the current automation's ID."""
        return self._automation_id

    def now(self) -> datetime:
        """Get the current time.

        Returns:
            The current time as a timezone-aware datetime in the host's time zone.
            This is the clock that drives triggers and timeouts, so it follows
            a test that freezes or advances time; ``datetime.now()`` does not.
        """
        return self._host.clock.now()

    def __getattr__(self, domain: str) -> EntityProxy | _ServiceAccessor:
        """Get entity proxy for a domain.

        Args:
            domain: Entity domain.

        Returns:
            EntityProxy for accessing entities in the domain, or _ServiceAccessor for 'service'.
        """
        # Check if it's a service access
        if domain == "service":
            return self._ServiceAccessor(self._host)  # type: ignore[return-value]
        return EntityProxy(self._host, domain)

    class _ServiceAccessor:
        """Internal accessor for services."""

        def __init__(self, host: Host) -> None:
            """Initialize service accessor.

            Args:
                host: The host the engine runs in.
            """
            self._host = host

        def __getattr__(self, domain: str) -> ServiceDomainProxy:
            """Get service domain proxy.

            Args:
                domain: Service domain.

            Returns:
                ServiceDomainProxy for the domain.
            """
            return ServiceDomainProxy(self._host, domain)

    @property
    def service(self) -> _ServiceAccessor:
        """Get service accessor."""
        return self._ServiceAccessor(self._host)

    def services(self) -> list[HAAnimServiceProxy]:
        """Get list of all available service proxies.

        Returns:
            List of HAAnimServiceProxy objects.
        """
        result = []
        for info in self._host.services.services():
            result.append(HAAnimServiceProxy(self._host, info.domain, info.name))
        return result

    def automation(self, automation_id: str) -> HAAnimAutomationProxy:
        """Get a proxy for another automation.

        Args:
            automation_id: The automation ID.

        Returns:
            HAAnimAutomationProxy for the automation.

        Raises:
            NonExistingAutomationError: If automation doesn't exist.
        """
        if self._manager.get_context_by_name(automation_id) is None:
            raise NonExistingAutomationError(automation_id)
        return HAAnimAutomationProxy(automation_id, self._manager)

    def automations(self) -> list[HAAnimAutomationProxy]:
        """Get list of all automation proxies.

        Returns:
            List of HAAnimAutomationProxy objects for all loaded automations.
        """
        return [
            HAAnimAutomationProxy(context.automation_id, self._manager)
            for context in self._manager.get_all_contexts()
        ]

    async def call(self, action_name: str, **kwargs: Any) -> Any:
        """Call an action in the current automation.

        Args:
            action_name: Name of the action.
            **kwargs: Arguments to pass to the action.

        Returns:
            The result of the action call.
        """
        return await self._manager.async_call_action(self._automation_id, action_name, **kwargs)

    async def disable(self) -> None:
        """Disable the current automation, which stops it. The calling action ends at this call."""
        await self._manager.async_disable_automation(self._automation_id)

    async def stop(self) -> None:
        """Stop the current automation. The calling action ends at this call."""
        await self._manager.async_stop_automation(self._automation_id)

    async def restart(self) -> None:
        """Restart the current automation. The calling action ends at this call."""
        await self._manager.async_restart_automation(self._automation_id)

    def set_message(self, message: str) -> None:
        """Set the automation's status message.

        Args:
            message: The status message to set.
        """
        context = self._manager.get_context_by_name(self._automation_id)
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
                _LOGGER.error("Failed to load storage for %s: %s", self._automation_id, err)
                self._storage_cache = {}
        else:
            self._storage_cache = {}

    def _save_storage(self) -> None:
        """Save storage to disk."""
        try:
            with open(self._storage_file, "w", encoding="utf-8") as f:
                json.dump(self._storage_cache, f, indent=2)
        except Exception as err:  # pylint: disable=broad-exception-caught
            _LOGGER.error("Failed to save storage for %s: %s", self._automation_id, err)

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
