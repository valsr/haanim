"""Config flow for HAAnim integration."""

from __future__ import annotations

import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .const import (
    CONF_ALLOW_ALL_IMPORTS,
    CONF_IMPORT_ALLOWLIST,
    CONF_SCRIPT_FOLDER,
    DEFAULT_ALLOW_ALL_IMPORTS,
    DEFAULT_IMPORT_ALLOWLIST,
    DEFAULT_NAME,
    DEFAULT_SCRIPT_FOLDER,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

# Configuration schema for user input
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required("name", default=DEFAULT_NAME): str,
        vol.Required(CONF_SCRIPT_FOLDER, default=DEFAULT_SCRIPT_FOLDER): str,
        vol.Required(CONF_ALLOW_ALL_IMPORTS, default=DEFAULT_ALLOW_ALL_IMPORTS): bool,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input.

    Args:
        hass: Home Assistant instance.
        data: User input data.

    Returns:
        Dictionary containing the validated data.

    Raises:
        InvalidScriptFolder: If the script folder path is invalid.
    """
    script_folder = data.get(CONF_SCRIPT_FOLDER, DEFAULT_SCRIPT_FOLDER)

    # Validate script folder path
    if os.path.isabs(script_folder):
        folder_path = script_folder
    else:
        folder_path = os.path.join(hass.config.config_dir, script_folder)

    # Check if parent directory exists (folder will be created if needed)
    parent_dir = os.path.dirname(folder_path)
    if parent_dir and not os.path.exists(parent_dir):
        raise InvalidScriptFolder(f"Parent directory does not exist: {parent_dir}")

    return {"title": data.get("name", DEFAULT_NAME)}


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HAAnim."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step.

        Args:
            user_input: User input data.

        Returns:
            The flow result showing the form or creating the entry.
        """
        errors: dict[str, str] = {}

        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidScriptFolder:
                errors["base"] = "invalid_folder"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        "name": user_input.get("name", DEFAULT_NAME),
                        CONF_SCRIPT_FOLDER: user_input.get(CONF_SCRIPT_FOLDER, DEFAULT_SCRIPT_FOLDER),
                        CONF_ALLOW_ALL_IMPORTS: user_input.get(CONF_ALLOW_ALL_IMPORTS, DEFAULT_ALLOW_ALL_IMPORTS),
                        CONF_IMPORT_ALLOWLIST: DEFAULT_IMPORT_ALLOWLIST,
                    },
                )

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> OptionsFlowHandler:
        """Get the options flow handler.

        Args:
            config_entry: The config entry.

        Returns:
            The options flow handler.
        """
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for HAAnim."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow.

        Args:
            config_entry: The config entry.
        """
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle options flow.

        Args:
            user_input: User input data.

        Returns:
            The flow result.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate script folder
            script_folder = user_input.get(CONF_SCRIPT_FOLDER, DEFAULT_SCRIPT_FOLDER)
            if os.path.isabs(script_folder):
                folder_path = script_folder
            else:
                folder_path = os.path.join(self.hass.config.config_dir, script_folder)

            parent_dir = os.path.dirname(folder_path)
            if parent_dir and not os.path.exists(parent_dir):
                errors[CONF_SCRIPT_FOLDER] = "invalid_folder"
            else:
                # Parse import allowlist from comma-separated string
                allowlist_str = user_input.get("import_allowlist_str", "")
                if allowlist_str:
                    allowlist = [m.strip() for m in allowlist_str.split(",") if m.strip()]
                else:
                    allowlist = DEFAULT_IMPORT_ALLOWLIST

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCRIPT_FOLDER: script_folder,
                        CONF_ALLOW_ALL_IMPORTS: user_input.get(CONF_ALLOW_ALL_IMPORTS, DEFAULT_ALLOW_ALL_IMPORTS),
                        CONF_IMPORT_ALLOWLIST: allowlist,
                    },
                )

        # Get current values
        current_folder = self.config_entry.options.get(
            CONF_SCRIPT_FOLDER,
            self.config_entry.data.get(CONF_SCRIPT_FOLDER, DEFAULT_SCRIPT_FOLDER),
        )
        current_allow_all = self.config_entry.options.get(
            CONF_ALLOW_ALL_IMPORTS,
            self.config_entry.data.get(CONF_ALLOW_ALL_IMPORTS, DEFAULT_ALLOW_ALL_IMPORTS),
        )
        current_allowlist = self.config_entry.options.get(
            CONF_IMPORT_ALLOWLIST,
            self.config_entry.data.get(CONF_IMPORT_ALLOWLIST, DEFAULT_IMPORT_ALLOWLIST),
        )

        # Convert allowlist to comma-separated string for display
        allowlist_str = ", ".join(current_allowlist) if current_allowlist else ""

        options_schema = vol.Schema(
            {
                vol.Required(CONF_SCRIPT_FOLDER, default=current_folder): str,
                vol.Required(CONF_ALLOW_ALL_IMPORTS, default=current_allow_all): bool,
                vol.Optional("import_allowlist_str", default=allowlist_str): str,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "default_allowlist": ", ".join(DEFAULT_IMPORT_ALLOWLIST[:5]) + "...",
            },
        )


class InvalidScriptFolder(HomeAssistantError):
    """Error to indicate invalid script folder."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
