"""REST API views for HAAnim.

This module provides HTTP API endpoints for the HAAnim frontend panel.
"""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from homeassistant.core import HomeAssistant
from homeassistant.helpers.http import HomeAssistantView

from custom_components.haanim.const import DOMAIN, VERSION
from custom_components.haanim.ha.assets import AssetView
from custom_components.haanim.automation_manager import async_get_manager, get_config_manager

_LOGGER = logging.getLogger(__name__)


class HAAnimAPIView(HomeAssistantView):
    """Base class for HAAnim API views.

    All API endpoints require authentication. The Web Component panel receives
    the hass object directly from Home Assistant, which includes the user's
    authentication context for API calls.
    """

    requires_auth = True


class AutomationsListView(HAAnimAPIView):
    """API view to list all automations."""

    url = f"/api/{DOMAIN}/automations"
    name = f"api:{DOMAIN}:automations"

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request for automations list.

        Args:
            request: The HTTP request.

        Returns:
            JSON response with automations list.
        """
        hass: HomeAssistant = request.app["hass"]

        manager = await async_get_manager(hass)
        if not manager:
            return self.json({"automations": [], "error": "Automation manager not available"})

        automations: list[dict[str, Any]] = []
        for metadata in manager.get_all_metadata():
            automations.append(
                {
                    "name": metadata.id,
                    "path": metadata.path,
                    "actions": [{"name": a.name, "func_name": a.func_name} for a in metadata.actions],
                    "triggers": len(metadata.triggers),
                    "enabled": metadata.enabled,
                }
            )

        return self.json({"automations": automations})


class ActionsListView(HAAnimAPIView):
    """API view to list all actions."""

    url = f"/api/{DOMAIN}/actions"
    name = f"api:{DOMAIN}:actions"

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request for actions list.

        Args:
            request: The HTTP request.

        Returns:
            JSON response with actions list.
        """
        hass: HomeAssistant = request.app["hass"]

        manager = await async_get_manager(hass)
        if not manager:
            return self.json({"actions": [], "error": "Automation manager not available"})

        automation_id = request.query.get("automation_id")

        actions: list[dict[str, Any]] = []
        for action in manager.get_all_actions():
            if automation_id and action.automation_id != automation_id:
                continue

            actions.append(
                {
                    "name": action.name,
                    "func_name": action.func_name,
                    "automation_id": action.automation_id,
                    "description": action.description,
                }
            )

        return self.json({"actions": actions})


class ConfigView(HAAnimAPIView):
    """API view to get configuration."""

    url = f"/api/{DOMAIN}/config"
    name = f"api:{DOMAIN}:config"

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request for configuration.

        Args:
            request: The HTTP request.

        Returns:
            JSON response with configuration values.
        """
        hass: HomeAssistant = request.app["hass"]
        config_mgr = get_config_manager()

        # Get the config entry data
        for _entry_id, data in hass.data.get(DOMAIN, {}).items():
            if isinstance(data, dict) and "entry" in data:
                entry = data["entry"]
                config_mgr.load_from_dict(entry.data, entry.options)
                break

        # Return all config values plus version
        config = config_mgr.get_all()
        config["version"] = VERSION

        return self.json(config)


class RunActionView(HAAnimAPIView):
    """API view to run an action."""

    url = f"/api/{DOMAIN}/run_action"
    name = f"api:{DOMAIN}:run_action"

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request to run an action.

        Args:
            request: The HTTP request.

        Returns:
            JSON response with result.
        """
        hass: HomeAssistant = request.app["hass"]

        try:
            data = await request.json()
        except ValueError:
            return self.json({"success": False, "error": "Invalid JSON"}, status_code=400)

        automation_id = data.get("automation_id")
        action_name = data.get("action_name")

        if not automation_id or not action_name:
            return self.json(
                {"success": False, "error": "Missing automation_id or action_name"},
                status_code=400,
            )

        manager = await async_get_manager(hass)
        if not manager:
            return self.json({"success": False, "error": "Automation manager not available"})

        try:
            await manager.async_run_action(automation_id, action_name)
            return self.json({"success": True})
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Failed to run action %s.%s: %s", automation_id, action_name, err)
            return self.json({"success": False, "error": str(err)})


class ReloadAutomationsView(HAAnimAPIView):
    """API view to reload automations."""

    url = f"/api/{DOMAIN}/reload"
    name = f"api:{DOMAIN}:reload"

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request to reload automations.

        Args:
            request: The HTTP request.

        Returns:
            JSON response with result.
        """
        hass: HomeAssistant = request.app["hass"]

        manager = await async_get_manager(hass)
        if not manager:
            return self.json({"success": False, "error": "Automation manager not available"})

        try:
            await manager.async_reload_all_automations()
            return self.json({"success": True})
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.error("Failed to reload automations: %s", err)
            return self.json({"success": False, "error": str(err)})


def async_register_api(hass: HomeAssistant) -> None:
    """Register all API views.

    Args:
        hass: Home Assistant instance.
    """
    hass.http.register_view(AutomationsListView())
    hass.http.register_view(ActionsListView())
    hass.http.register_view(ConfigView())
    hass.http.register_view(RunActionView())
    hass.http.register_view(ReloadAutomationsView())
    hass.http.register_view(AssetView())

    _LOGGER.debug("HAAnim API views registered")
