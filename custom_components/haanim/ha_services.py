"""Home Assistant service integration for HAAnim.

This module provides service calling capabilities and the ability to
expose script functions as Home Assistant services.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import ATTR_ACTION_NAME, ATTR_MANUAL, ATTR_SCRIPT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ServiceManager:
    """Manages service calls and service registration for HAAnim scripts.

    Provides methods to call Home Assistant services and expose script
    functions as services.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the service manager.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._registered_services: dict[str, dict[str, Any]] = {}

    async def async_setup(self) -> None:
        """Set up the service manager and register core services."""
        # Register the run_action service
        self.hass.services.async_register(
            DOMAIN,
            "run_action",
            self._handle_run_action,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_SCRIPT_NAME): cv.string,
                    vol.Required(ATTR_ACTION_NAME): cv.string,
                }
            ),
        )

        # Register the reload_scripts service
        self.hass.services.async_register(
            DOMAIN,
            "reload_scripts",
            self._handle_reload_scripts,
            schema=vol.Schema({}),
        )

        # Register the list_scripts service
        self.hass.services.async_register(
            DOMAIN,
            "list_scripts",
            self._handle_list_scripts,
            schema=vol.Schema({}),
        )

        # Register the list_actions service
        self.hass.services.async_register(
            DOMAIN,
            "list_actions",
            self._handle_list_actions,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_SCRIPT_NAME): cv.string,
                }
            ),
        )

        # Register the get_config service
        self.hass.services.async_register(
            DOMAIN,
            "get_config",
            self._handle_get_config,
            schema=vol.Schema({}),
        )

        _LOGGER.debug("Service manager set up")

    async def async_teardown(self) -> None:
        """Tear down the service manager."""
        # Unregister core services
        self.hass.services.async_remove(DOMAIN, "run_action")
        self.hass.services.async_remove(DOMAIN, "reload_scripts")
        self.hass.services.async_remove(DOMAIN, "list_scripts")
        self.hass.services.async_remove(DOMAIN, "list_actions")
        self.hass.services.async_remove(DOMAIN, "get_config")

        # Unregister script services
        for service_name in list(self._registered_services.keys()):
            await self.async_unregister_service(service_name)

    async def _handle_run_action(self, call: ServiceCall) -> None:
        """Handle the run_action service call.

        Args:
            call: The service call.
        """
        from .script_manager import async_get_manager

        script_name = call.data[ATTR_SCRIPT_NAME]
        action_name = call.data[ATTR_ACTION_NAME]

        manager = await async_get_manager(self.hass)
        if not manager:
            _LOGGER.error("Script manager not available")
            return

        try:
            await manager.async_run_action(script_name, action_name, manual=True)
        except Exception as err:
            _LOGGER.error("Failed to run action %s.%s: %s", script_name, action_name, err)

    async def _handle_reload_scripts(self, call: ServiceCall) -> None:
        """Handle the reload_scripts service call.

        Args:
            call: The service call.
        """
        from .script_manager import async_get_manager

        manager = await async_get_manager(self.hass)
        if not manager:
            _LOGGER.error("Script manager not available")
            return

        await manager.async_reload_all_scripts()

    async def _handle_list_scripts(self, call: ServiceCall) -> dict[str, Any]:
        """Handle the list_scripts service call.

        Args:
            call: The service call.

        Returns:
            Dictionary with script information.
        """
        from .script_manager import async_get_manager

        manager = await async_get_manager(self.hass)
        if not manager:
            return {"scripts": []}

        scripts = []
        for metadata in manager.get_all_metadata():
            scripts.append(
                {
                    "name": metadata.name,
                    "path": metadata.path,
                    "actions": [a.name for a in metadata.actions],
                    "triggers": len(metadata.triggers),
                    "enabled": metadata.enabled,
                }
            )

        return {"scripts": scripts}

    async def _handle_list_actions(self, call: ServiceCall) -> dict[str, Any]:
        """Handle the list_actions service call.

        Args:
            call: The service call.

        Returns:
            Dictionary with action information.
        """
        from .script_manager import async_get_manager

        manager = await async_get_manager(self.hass)
        if not manager:
            return {"actions": []}

        script_name = call.data.get(ATTR_SCRIPT_NAME)

        actions = []
        for action in manager.get_all_actions():
            if script_name and action.script_name != script_name:
                continue

            actions.append(
                {
                    "name": action.name,
                    "func_name": action.func_name,
                    "script_name": action.script_name,
                    "description": action.description,
                }
            )

        return {"actions": actions}

    async def _handle_get_config(self, call: ServiceCall) -> dict[str, Any]:
        """Handle the get_config service call.

        Args:
            call: The service call.

        Returns:
            Dictionary with configuration values.
        """
        from .config_manager import get_config_manager
        from .const import VERSION

        config_mgr = get_config_manager()

        # Get the config entry data
        for _entry_id, data in self.hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict) and "entry" in data:
                entry = data["entry"]
                config_mgr.load_from_dict(entry.data, entry.options)
                break

        # Return all config values plus version
        config = config_mgr.get_all()
        config["version"] = VERSION

        return config

    async def call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        blocking: bool = True,
        return_response: bool = False,
    ) -> Any:
        """Call a Home Assistant service.

        Args:
            domain: The service domain.
            service: The service name.
            service_data: Optional service data.
            blocking: If True, wait for service to complete.
            return_response: If True, return the service response.

        Returns:
            Service response if return_response is True.
        """
        return await self.hass.services.async_call(
            domain,
            service,
            service_data,
            blocking=blocking,
            return_response=return_response,
        )

    async def async_register_service(
        self,
        service_name: str,
        handler: Any,
        schema: vol.Schema | None = None,
        description: str | None = None,
    ) -> None:
        """Register a script function as a Home Assistant service.

        Args:
            service_name: The service name.
            handler: The function to call when service is invoked.
            schema: Optional voluptuous schema for service data.
            description: Optional description of the service.
        """
        full_name = f"{DOMAIN}.{service_name}"

        if service_name in self._registered_services:
            _LOGGER.warning("Service %s already registered, replacing", full_name)
            await self.async_unregister_service(service_name)

        async def service_handler(call: ServiceCall) -> Any:
            """Handle the service call."""
            try:
                if asyncio.iscoroutinefunction(handler):
                    return await handler(**call.data)
                return await self.hass.async_add_executor_job(
                    lambda: handler(**call.data)
                )
            except Exception as err:
                _LOGGER.error("Service %s failed: %s", full_name, err)
                raise

        self.hass.services.async_register(
            DOMAIN,
            service_name,
            service_handler,
            schema=schema,
        )

        self._registered_services[service_name] = {
            "handler": handler,
            "schema": schema,
            "description": description,
        }

        _LOGGER.info("Registered service: %s", full_name)

    async def async_unregister_service(self, service_name: str) -> bool:
        """Unregister a script service.

        Args:
            service_name: The service name.

        Returns:
            True if service was unregistered.
        """
        if service_name not in self._registered_services:
            return False

        self.hass.services.async_remove(DOMAIN, service_name)
        del self._registered_services[service_name]

        _LOGGER.info("Unregistered service: %s.%s", DOMAIN, service_name)
        return True

    def get_registered_services(self) -> list[str]:
        """Get list of registered script services.

        Returns:
            List of service names.
        """
        return list(self._registered_services.keys())


# Convenience functions for use in scripts


async def service_call(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
    blocking: bool = True,
) -> None:
    """Call a Home Assistant service.

    Args:
        hass: Home Assistant instance.
        domain: The service domain.
        service: The service name.
        service_data: Optional service data.
        blocking: If True, wait for service to complete.
    """
    await hass.services.async_call(
        domain,
        service,
        service_data,
        blocking=blocking,
    )


def service_call_sync(
    hass: HomeAssistant,
    domain: str,
    service: str,
    service_data: dict[str, Any] | None = None,
) -> None:
    """Call a Home Assistant service (sync version).

    Args:
        hass: Home Assistant instance.
        domain: The service domain.
        service: The service name.
        service_data: Optional service data.
    """
    hass.services.call(
        domain,
        service,
        service_data,
        blocking=True,
    )
