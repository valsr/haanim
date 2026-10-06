"""The HAAnim integration."""

from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig

from custom_components.haanim.api import async_register_api
from custom_components.haanim.config import get_config_manager
from custom_components.haanim.const import DOMAIN, NAME, VERSION
from custom_components.haanim.ha.events import EventManager
from custom_components.haanim.ha.host import HAServiceCaller, build_host
from custom_components.haanim.ha.services import ServiceManager
from custom_components.haanim.ha.state import StateManager
from custom_components.haanim.automation_manager import AutomationManager
from custom_components.haanim.log_buffer import AutomationLogBuffer
from custom_components.haanim.options import engine_options
from custom_components.haanim.websocket import async_register_websocket
from haanim.engine.triggers import TriggerManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]  # One enum sensor per automation

CARD_URL = f"/{DOMAIN}/ui/haanim-card.js?v={VERSION}"
"""Where the frontend loads ``custom:haanim-card`` from."""


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:  # noqa: ARG001
    """Set up the HAAnim component from yaml configuration.

    Args:
        hass: Home Assistant instance.
        config: The configuration dictionary.

    Returns:
        True if setup was successful.
    """
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up HAAnim from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.

    Returns:
        True if setup was successful.
    """
    hass.data.setdefault(DOMAIN, {})

    # Initialize the config manager
    config_manager = get_config_manager()
    config_manager.setup(hass, entry.entry_id)
    # The entry is not in hass.data yet, so the manager cannot find it itself
    config_manager.load_entry(entry.data, entry.options)

    # Initialize managers
    state_manager = StateManager(hass)
    event_manager = EventManager(hass)
    service_manager = ServiceManager(hass)
    host = build_host(hass, state_manager, event_manager)
    # Keep the recent log records of the automations, from the first one they write
    log_buffer = AutomationLogBuffer()
    log_buffer.install()
    entry.async_on_unload(log_buffer.remove)

    automation_manager = AutomationManager(
        hass, entry, host, options=engine_options({**entry.data, **entry.options})
    )
    trigger_manager = TriggerManager(host, automation_manager.dispatcher)
    automation_manager.set_trigger_registrar(trigger_manager)

    # Set up managers
    await state_manager.async_setup()
    await event_manager.async_setup()
    await service_manager.async_setup()
    if isinstance(host.services, HAServiceCaller):
        await host.services.async_refresh_descriptions()
    await automation_manager.async_setup()

    # Store managers in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "manager": automation_manager,
        "log_buffer": log_buffer,
        "state_manager": state_manager,
        "event_manager": event_manager,
        "service_manager": service_manager,
        "trigger_manager": trigger_manager,
    }

    # Register API views for the frontend
    async_register_api(hass)
    async_register_websocket(hass)

    # Register the frontend panel
    await _async_register_panel(hass)

    # Forward the setup to the platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register reload listener for options changes
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    _LOGGER.info("HAAnim integration initialized successfully")
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update.

    Args:
        hass: Home Assistant instance.
        entry: The config entry.
    """
    # Reload the integration when options change
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the HAAnim panel as a Web Component.

    Args:
        hass: Home Assistant instance.
    """

    # Check if panel is already registered
    if DOMAIN in hass.data.get("frontend_panels", {}):
        _LOGGER.debug("HAAnim panel already registered, skipping")
        return

    # Get the path to the UI directory
    ui_dir = os.path.join(os.path.dirname(__file__), "ui")

    # Register static path for serving UI assets (includes the panel JS file)
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}/ui", ui_dir, cache_headers=False)]
    )

    # Register as a custom panel using Web Component
    # haanim-panel.js is an ES module that defines the 'haanim-panel' custom element
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title=NAME,
        sidebar_icon="mdi:animation",
        frontend_url_path=DOMAIN,
        config={
            "_panel_custom": {
                "name": "haanim-panel",
                "module_url": f"/{DOMAIN}/ui/haanim-panel.js?v={VERSION}",
                "embed_iframe": False,
                "trust_external": False,
            }
        },
        require_admin=False,
    )

    # Dashboards load the card with the rest of the frontend
    frontend.add_extra_js_url(hass, CARD_URL)

    _LOGGER.info("HAAnim panel registered successfully")


async def _async_unregister_panel(hass: HomeAssistant) -> None:
    """Unregister the HAAnim panel.

    Args:
        hass: Home Assistant instance.
    """
    # Remove the panel if it exists
    if DOMAIN in hass.data.get("frontend_panels", {}):
        frontend.async_remove_panel(hass, DOMAIN)
        frontend.remove_extra_js_url(hass, CARD_URL)
        _LOGGER.debug("HAAnim panel unregistered")


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry to unload.

    Returns:
        True if unload was successful.
    """
    # Get managers
    data = hass.data[DOMAIN].get(entry.entry_id, {})

    # Stop and unload the automations first, while triggers and services still work
    if "manager" in data:
        await data["manager"].async_shutdown()

    # Tear down managers in reverse order
    if "trigger_manager" in data:
        await data["trigger_manager"].async_teardown()

    if "service_manager" in data:
        await data["service_manager"].async_teardown()

    if "event_manager" in data:
        await data["event_manager"].async_teardown()

    if "state_manager" in data:
        await data["state_manager"].async_teardown()

    # Unregister the panel
    await _async_unregister_panel(hass)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry to reload.
    """
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
