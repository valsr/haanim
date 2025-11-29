"""The HAAnim integration."""

from __future__ import annotations

import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, NAME
from .ha_events import EventManager
from .ha_services import ServiceManager
from .ha_state import StateManager
from .script_manager import ScriptManager
from .triggers import TriggerManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = []  # Add platforms like Platform.SENSOR, Platform.SWITCH, etc.


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # noqa: ARG001
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

    # Initialize managers
    state_manager = StateManager(hass)
    event_manager = EventManager(hass)
    service_manager = ServiceManager(hass)
    trigger_manager = TriggerManager(hass, state_manager, event_manager)
    script_manager = ScriptManager(hass, entry)

    # Set up managers
    await state_manager.async_setup()
    await event_manager.async_setup()
    await service_manager.async_setup()
    await trigger_manager.async_setup()
    await script_manager.async_setup()

    # Store managers in hass.data
    hass.data[DOMAIN][entry.entry_id] = {
        "entry": entry,
        "manager": script_manager,
        "state_manager": state_manager,
        "event_manager": event_manager,
        "service_manager": service_manager,
        "trigger_manager": trigger_manager,
    }

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
    """Register the HAAnim panel.

    Args:
        hass: Home Assistant instance.
    """
    from homeassistant.components import frontend

    # Get the path to the panel files
    panel_dir = os.path.join(os.path.dirname(__file__), "ui")
    panel_html_path = os.path.join(panel_dir, "panel.html")
    panel_css_path = os.path.join(panel_dir, "panel.css")
    panel_js_path = os.path.join(panel_dir, "panel.js")

    # Read the panel files
    with open(panel_html_path, encoding="utf-8") as file:
        panel_html = file.read()

    with open(panel_css_path, encoding="utf-8") as file:
        panel_css = file.read()

    with open(panel_js_path, encoding="utf-8") as file:
        panel_js = file.read()

    # Inline CSS and JS into HTML
    panel_html = panel_html.replace('<link rel="stylesheet" href="panel.css">', f"<style>{panel_css}</style>")
    panel_html = panel_html.replace('<script src="panel.js"></script>', f"<script>{panel_js}</script>")

    # Register as a custom panel with embedded HTML
    frontend.async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title=NAME,
        sidebar_icon="mdi:animation",
        frontend_url_path=DOMAIN,
        config={
            "url": f"data:text/html;charset=utf-8,{panel_html.replace('#', '%23').replace('\n', '').replace('  ', '')}"
        },
        require_admin=False,
    )

    _LOGGER.info("HAAnim panel registered successfully")


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

    # Tear down managers in reverse order
    if "trigger_manager" in data:
        await data["trigger_manager"].async_teardown()

    if "service_manager" in data:
        await data["service_manager"].async_teardown()

    if "event_manager" in data:
        await data["event_manager"].async_teardown()

    if "state_manager" in data:
        await data["state_manager"].async_teardown()

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
