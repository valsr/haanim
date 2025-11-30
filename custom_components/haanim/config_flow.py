"""Config flow for HAAnim integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

from .config import get_config_manager
from .const import (
    CONF_ALLOW_ALL_IMPORTS,
    CONF_IMPORT_ALLOWLIST,
    CONF_SCRIPT_PATH,
    DEFAULT_ALLOW_ALL_IMPORTS,
    DEFAULT_IMPORT_ALLOWLIST,
    DEFAULT_NAME,
    DEFAULT_SCRIPT_PATH,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input.

    Args:
        hass: Home Assistant instance.
        data: User input data.

    Returns:
        Dictionary containing the validated data.

    Raises:
        InvalidScriptPath: If the script path is invalid.
    """
    config_mgr = get_config_manager()
    config_mgr.setup(hass)

    script_path = data.get(CONF_SCRIPT_PATH, DEFAULT_SCRIPT_PATH)
    is_valid, error = config_mgr.validate_script_path(script_path)

    if not is_valid:
        raise InvalidScriptPath(error)

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
        config_mgr = get_config_manager()
        config_mgr.setup(self.hass)

        # Only allow one instance
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidScriptPath:
                errors["base"] = "invalid_folder"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                defaults = config_mgr.get_defaults()
                return self.async_create_entry(
                    title=info["title"],
                    data={
                        "name": user_input.get("name", defaults.get("name", DEFAULT_NAME)),
                        CONF_SCRIPT_PATH: user_input.get(
                            CONF_SCRIPT_PATH, defaults.get("script_path", DEFAULT_SCRIPT_PATH)
                        ),
                        CONF_ALLOW_ALL_IMPORTS: user_input.get(
                            CONF_ALLOW_ALL_IMPORTS,
                            defaults.get("allow_all_imports", DEFAULT_ALLOW_ALL_IMPORTS),
                        ),
                        CONF_IMPORT_ALLOWLIST: defaults.get("import_allowlist", DEFAULT_IMPORT_ALLOWLIST),
                    },
                )

        # Generate schema from ConfigManager
        setup_schema = config_mgr.generate_setup_schema()
        return self.async_show_form(step_id="user", data_schema=setup_schema, errors=errors)

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
        config_mgr = get_config_manager()
        config_mgr.setup(self.hass)

        if user_input is not None:
            # Validate script path using ConfigManager
            script_path = user_input.get(CONF_SCRIPT_PATH, DEFAULT_SCRIPT_PATH)
            is_valid, _error = config_mgr.validate_script_path(script_path)

            if not is_valid:
                errors[CONF_SCRIPT_PATH] = "invalid_path"
            else:
                # Parse import allowlist from comma-separated string
                allowlist_str = user_input.get("import_allowlist_str", "")
                if allowlist_str:
                    allowlist = [m.strip() for m in allowlist_str.split(",") if m.strip()]
                else:
                    allowlist = config_mgr.get("import_allowlist", DEFAULT_IMPORT_ALLOWLIST)

                return self.async_create_entry(
                    title="",
                    data={
                        CONF_SCRIPT_PATH: script_path,
                        CONF_ALLOW_ALL_IMPORTS: user_input.get(
                            CONF_ALLOW_ALL_IMPORTS, DEFAULT_ALLOW_ALL_IMPORTS
                        ),
                        CONF_IMPORT_ALLOWLIST: allowlist,
                    },
                )

        # Load current values from entry
        config_mgr.load_from_dict(self.config_entry.data, self.config_entry.options)

        # Get current values
        current_path = config_mgr.get("script_path", DEFAULT_SCRIPT_PATH)
        current_allow_all = config_mgr.get("allow_all_imports", DEFAULT_ALLOW_ALL_IMPORTS)
        current_allowlist = config_mgr.get("import_allowlist", DEFAULT_IMPORT_ALLOWLIST)

        # Convert allowlist to comma-separated string for display
        allowlist_str = ", ".join(current_allowlist) if current_allowlist else ""

        options_schema = vol.Schema(
            {
                vol.Required(CONF_SCRIPT_PATH, default=current_path): str,
                vol.Required(CONF_ALLOW_ALL_IMPORTS, default=current_allow_all): bool,
                vol.Optional("import_allowlist_str", default=allowlist_str): str,
            }
        )

        # Get defaults for description placeholder
        defaults = config_mgr.get_defaults()
        default_allowlist = defaults.get("import_allowlist", DEFAULT_IMPORT_ALLOWLIST)

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "default_allowlist": ", ".join(default_allowlist[:5]) + "...",
            },
        )


class InvalidScriptPath(HomeAssistantError):
    """Error to indicate invalid script path."""


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
