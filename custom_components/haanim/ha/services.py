"""Home Assistant service integration for HAAnim.

This module provides service calling capabilities and the ability to
expose automation functions as Home Assistant services.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from custom_components.haanim.automation_manager import AutomationManager, async_get_manager
from custom_components.haanim.const import (
    ATTRIBUTE_ACTION,
    ATTRIBUTE_AUTOMATION_ID,
    ATTRIBUTE_DATA,
    DOMAIN,
    SERVICE_DISABLE,
    SERVICE_ENABLE,
    SERVICE_LIST_ACTIONS,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_RELOAD,
    SERVICE_RESTART,
    SERVICE_RUN_ACTION,
    SERVICE_START,
    SERVICE_STOP,
)
from haanim.engine.callables import as_coroutine_function
from haanim.engine.errors import HAAnimError

_LOGGER = logging.getLogger(__name__)

CONTROL_SERVICES = (SERVICE_ENABLE, SERVICE_DISABLE, SERVICE_START, SERVICE_STOP, SERVICE_RESTART)
SERVICES = (
    SERVICE_RUN_ACTION,
    *CONTROL_SERVICES,
    SERVICE_RELOAD,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_LIST_ACTIONS,
)
"""The nine services of the design's table."""


@contextmanager
def service_errors() -> Iterator[None]:
    """Turn a HAAnim error into a service error carrying the error's type and message."""
    try:
        yield
    except HAAnimError as err:
        raise HomeAssistantError(f"{type(err).__name__}: {err}") from err


class ServiceManager:
    """Manages service calls and service registration for HAAnim automations.

    Provides methods to call Home Assistant services and expose automation
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
        """Set up the service manager and register the HAAnim services."""
        automation = vol.Schema({vol.Required(ATTRIBUTE_AUTOMATION_ID): cv.string})
        register = self.hass.services.async_register

        register(
            DOMAIN,
            SERVICE_RUN_ACTION,
            self._handle_run_action,
            schema=vol.Schema(
                {
                    vol.Required(ATTRIBUTE_AUTOMATION_ID): cv.string,
                    vol.Required(ATTRIBUTE_ACTION): cv.string,
                    vol.Optional(ATTRIBUTE_DATA, default=dict): dict,
                }
            ),
            supports_response=SupportsResponse.OPTIONAL,
        )
        for service in CONTROL_SERVICES:
            register(DOMAIN, service, self._handle_control, schema=automation)
        register(
            DOMAIN,
            SERVICE_RELOAD,
            self._handle_reload,
            schema=vol.Schema({vol.Optional(ATTRIBUTE_AUTOMATION_ID): cv.string}),
        )
        register(
            DOMAIN,
            SERVICE_LIST_AUTOMATIONS,
            self._handle_list_automations,
            schema=vol.Schema({}),
            supports_response=SupportsResponse.ONLY,
        )
        register(
            DOMAIN,
            SERVICE_LIST_ACTIONS,
            self._handle_list_actions,
            schema=automation,
            supports_response=SupportsResponse.ONLY,
        )

        _LOGGER.debug("Service manager set up")

    async def async_teardown(self) -> None:
        """Tear down the service manager."""
        for service in SERVICES:
            self.hass.services.async_remove(DOMAIN, service)

        # Unregister automation services
        for service_name in list(self._registered_services.keys()):
            await self.async_unregister_service(service_name)

    async def _manager(self) -> AutomationManager:
        """Return the automation manager.

        Raises:
            HomeAssistantError: If HAAnim is not set up.
        """
        manager = await async_get_manager(self.hass)
        if manager is None:
            raise HomeAssistantError("HAAnim is not set up")
        return manager

    async def _handle_run_action(self, call: ServiceCall) -> ServiceResponse:
        """Run an action as a manual call and return its result as response data."""
        manager = await self._manager()
        with service_errors():
            result = await manager.async_call_action(
                call.data[ATTRIBUTE_AUTOMATION_ID],
                call.data[ATTRIBUTE_ACTION],
                dict(call.data[ATTRIBUTE_DATA]),
            )
        return {"result": result} if call.return_response else None

    async def _handle_control(self, call: ServiceCall) -> None:
        """Enable, disable, start, stop or restart an automation."""
        manager = await self._manager()
        operation = {
            SERVICE_ENABLE: manager.async_enable_automation,
            SERVICE_DISABLE: manager.async_disable_automation,
            SERVICE_START: manager.async_start_automation,
            SERVICE_STOP: manager.async_stop_automation,
            SERVICE_RESTART: manager.async_restart_automation,
        }[call.service]
        with service_errors():
            await operation(call.data[ATTRIBUTE_AUTOMATION_ID])

    async def _handle_reload(self, call: ServiceCall) -> None:
        """Rescan now and reload one automation, or all without an ID."""
        manager = await self._manager()
        with service_errors():
            await manager.async_reload(call.data.get(ATTRIBUTE_AUTOMATION_ID))

    async def _handle_list_automations(self, _: ServiceCall) -> ServiceResponse:
        """Return ID, name, state and enabled flag of every automation."""
        manager = await self._manager()
        return {
            "automations": [
                {
                    "id": automation_id,
                    "name": manager.automation_name(automation_id),
                    "state": manager.automation_state(automation_id),
                    "enabled": manager.is_automation_enabled(automation_id),
                }
                for automation_id in manager.automation_ids()
            ]
        }

    async def _handle_list_actions(self, call: ServiceCall) -> ServiceResponse:
        """Return the actions of an automation with name, aliases and description."""
        manager = await self._manager()
        with service_errors():
            actions = manager.automation_actions(call.data[ATTRIBUTE_AUTOMATION_ID])
        return {
            "actions": [
                {
                    "name": action.name,
                    "aliases": list(action.aliases),
                    "description": action.description or "",
                }
                for action in actions
            ]
        }

    async def call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        *,
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
        """Register an automation function as a Home Assistant service.

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
                return await as_coroutine_function(handler)(**call.data)
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
        """Unregister an automation service.

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
        """Get list of registered automation services.

        Returns:
            List of service names.
        """
        return list(self._registered_services.keys())


# Convenience functions for use in automations


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
