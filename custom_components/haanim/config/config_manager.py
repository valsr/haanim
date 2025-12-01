"""Configuration manager for HAAnim.

This module provides the singleton ConfigManager that handles all configuration
options, validation, and schema generation.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .config_group import ConfigGroup
from .config_option import ConfigOption
from .config_type import ConfigType

_LOGGER = logging.getLogger(__name__)


class ConfigManager:
    """Singleton configuration manager for HAAnim.

    Manages all configuration options, provides validation, schema generation,
    and access to current configuration values.
    """

    _instance: ConfigManager | None = None
    _initialized: bool = False

    def __new__(cls) -> ConfigManager:
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the configuration manager."""
        if ConfigManager._initialized:
            return

        self._hass: HomeAssistant | None = None
        self._entry_id: str | None = None
        self._groups: dict[str, ConfigGroup] = {}
        self._options: dict[str, ConfigOption] = {}
        self._values: dict[str, Any] = {}

        # Register default configuration options
        self._register_default_options()
        ConfigManager._initialized = True

    def _register_default_options(self) -> None:
        """Register all default configuration options."""
        # General settings group
        general_group = ConfigGroup(
            name="general",
            label="General Settings",
            description="Basic HAAnim configuration",
            options=[
                ConfigOption(
                    key="name",
                    config_type=ConfigType.STRING,
                    default="HAAnim",
                    required=True,
                    label="Name",
                    description="Display name for the integration",
                    show_in_options=False,
                ),
                ConfigOption(
                    key="script_path",
                    config_type=ConfigType.STRING,
                    default="/config/haanim",
                    required=True,
                    label="Script Path",
                    description="Path for automation scripts (absolute path)",
                ),
            ],
        )
        self.register_group(general_group)

        # Security settings group
        security_group = ConfigGroup(
            name="security",
            label="Security Settings",
            description="Security-related configuration",
            options=[
                ConfigOption(
                    key="allow_all_imports",
                    config_type=ConfigType.BOOLEAN,
                    default=False,
                    required=True,
                    label="Allow All Imports",
                    description="If enabled, scripts can import any Python module. Use with caution!",
                ),
                ConfigOption(
                    key="import_allowlist",
                    config_type=ConfigType.LIST,
                    default=[
                        "asyncio",
                        "datetime",
                        "json",
                        "logging",
                        "math",
                        "random",
                        "re",
                        "time",
                        "typing",
                        "collections",
                        "functools",
                        "itertools",
                        "operator",
                        "statistics",
                        "decimal",
                        "fractions",
                        "enum",
                        "dataclasses",
                    ],
                    required=False,
                    label="Import Allowlist",
                    description="List of allowed module names for import",
                    show_in_setup=False,
                ),
            ],
        )
        self.register_group(security_group)

    def register_group(self, group: ConfigGroup) -> None:
        """Register a configuration group.

        Args:
            group: The configuration group to register.
        """
        self._groups[group.name] = group
        for option in group.options:
            self._options[option.key] = option
            # Set default value
            if option.key not in self._values:
                self._values[option.key] = option.default

    def register_option(self, group_name: str, option: ConfigOption) -> None:
        """Register a single configuration option to a group.

        Args:
            group_name: The name of the group to add the option to.
            option: The configuration option to register.
        """
        if group_name not in self._groups:
            self._groups[group_name] = ConfigGroup(name=group_name, label=group_name.title())

        self._groups[group_name].options.append(option)
        self._options[option.key] = option
        if option.key not in self._values:
            self._values[option.key] = option.default

    def setup(self, hass: HomeAssistant, entry_id: str | None = None) -> None:
        """Set up the configuration manager with Home Assistant instance.

        Args:
            hass: Home Assistant instance.
            entry_id: Optional config entry ID.
        """
        self._hass = hass
        self._entry_id = entry_id
        self._load_from_entry()

    def _load_from_entry(self) -> None:
        """Load configuration values from config entry."""
        if not self._hass or not self._entry_id:
            return

        from ..const import DOMAIN

        data = self._hass.data.get(DOMAIN, {}).get(self._entry_id, {})
        if isinstance(data, dict) and "entry" in data:
            entry = data["entry"]  # type: ignore
            if not isinstance(entry, ConfigEntry):
                return

            # Load from options first, then data
            for key in self._options:
                if key in entry.options:
                    self._values[key] = entry.options[key]
                elif key in entry.data:
                    self._values[key] = entry.data[key]

    def load_from_dict(self, data: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> None:
        """Load configuration values from dictionaries.

        Args:
            data: Configuration data dictionary.
            options: Optional options dictionary (takes precedence).
        """
        for key in self._options:
            if options and key in options:
                self._values[key] = options[key]
            elif key in data:
                self._values[key] = data[key]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: The configuration key.
            default: Default value if key not found.

        Returns:
            The configuration value.
        """
        if key in self._values:
            return self._values[key]
        if key in self._options:
            return self._options[key].default
        return default

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.

        Args:
            key: The configuration key.
            value: The value to set.
        """
        self._values[key] = value

    def get_all(self) -> dict[str, Any]:
        """Get all configuration values.

        Returns:
            Dictionary of all configuration values.
        """
        result: dict[str, Any] = {}
        for key, option in self._options.items():
            result[key] = self._values.get(key, option.default)
        return result

    def get_option(self, key: str) -> ConfigOption | None:
        """Get a configuration option definition.

        Args:
            key: The configuration key.

        Returns:
            The ConfigOption if found, None otherwise.
        """
        return self._options.get(key)

    def get_all_options(self) -> dict[str, ConfigOption]:
        """Get all configuration option definitions.

        Returns:
            Dictionary of all ConfigOptions.
        """
        return self._options.copy()

    def get_groups(self) -> dict[str, ConfigGroup]:
        """Get all configuration groups.

        Returns:
            Dictionary of all ConfigGroups.
        """
        return self._groups.copy()

    def get_defaults(self) -> dict[str, Any]:
        """Get all default values.

        Returns:
            Dictionary of all default values.
        """
        return {key: opt.default for key, opt in self._options.items()}

    def dump(self) -> dict[str, Any]:
        """Dump complete configuration information.

        Returns:
            Dictionary with all config info including options, values, and metadata.
        """
        groups_dump = {}
        for name, group in self._groups.items():
            groups_dump[name] = {
                "label": group.label,
                "description": group.description,
                "options": [
                    {
                        "key": opt.key,
                        "type": opt.config_type.value,
                        "default": opt.default,
                        "required": opt.required,
                        "label": opt.label,
                        "description": opt.description,
                        "value": self._values.get(opt.key, opt.default),
                        "show_in_setup": opt.show_in_setup,
                        "show_in_options": opt.show_in_options,
                    }
                    for opt in group.options
                ],
            }

        return {
            "groups": groups_dump,
            "values": self.get_all(),
            "defaults": self.get_defaults(),
        }

    def generate_setup_schema(self) -> vol.Schema:
        """Generate voluptuous schema for initial setup.

        Returns:
            Schema for the setup flow.
        """
        schema_dict: dict[vol.Required | vol.Optional, Any] = {}
        for option in self._options.values():
            if not option.show_in_setup:
                continue
            schema_dict.update(self._option_to_schema(option))
        return vol.Schema(schema_dict)

    def generate_options_schema(self, current_values: dict[str, Any] | None = None) -> vol.Schema:
        """Generate voluptuous schema for options flow.

        Args:
            current_values: Current configuration values for defaults.

        Returns:
            Schema for the options flow.
        """
        values = current_values or self._values
        schema_dict: dict[vol.Required | vol.Optional, Any] = {}
        for option in self._options.values():
            if not option.show_in_options:
                continue
            current = values.get(option.key, option.default)
            schema_dict.update(self._option_to_schema(option, current))
        return vol.Schema(schema_dict)

    def _option_to_schema(
        self, option: ConfigOption, current_value: Any | None = None
    ) -> dict[vol.Required | vol.Optional, Any]:
        """Convert a ConfigOption to a voluptuous schema entry.

        Args:
            option: The configuration option.
            current_value: Current value to use as default.

        Returns:
            Dictionary with schema key and validator.
        """
        default = current_value if current_value is not None else option.default

        # Determine the validator based on type
        if option.validator:
            validator = option.validator
        elif option.config_type == ConfigType.STRING:
            validator = cv.string
        elif option.config_type == ConfigType.BOOLEAN:
            validator = cv.boolean
        elif option.config_type == ConfigType.INTEGER:
            validator = vol.Coerce(int)
        elif option.config_type == ConfigType.FLOAT:
            validator = vol.Coerce(float)
        elif option.config_type == ConfigType.LIST:
            validator = cv.ensure_list
        elif option.config_type == ConfigType.SELECT and option.options:
            validator = vol.In(option.options)
        else:
            validator = cv.string

        # Create the schema key
        if option.required:
            key = vol.Required(option.key, default=default)
        else:
            key = vol.Optional(option.key, default=default)

        return {key: validator}

    def validate_script_path(self, path: str) -> tuple[bool, str | None]:
        """Validate a script path.

        Args:
            path: The path to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if not self._hass:
            return True, None

        if os.path.isabs(path):
            folder_path = path
        else:
            folder_path = os.path.join(self._hass.config.config_dir, path)

        parent_dir = os.path.dirname(folder_path)
        if parent_dir and not os.path.exists(parent_dir):
            return False, f"Parent directory does not exist: {parent_dir}"

        return True, None

    def get_script_path(self) -> str:
        """Get the full path to the script folder.

        Returns:
            Absolute path to the script folder.
        """
        path = self.get("script_path", "/config/haanim")

        if not self._hass:
            return path

        if os.path.isabs(path):
            return path

        return os.path.join(self._hass.config.config_dir, path)


def get_config_manager() -> ConfigManager:
    """Get the singleton ConfigManager instance.

    Returns:
        The ConfigManager singleton.
    """
    return ConfigManager()
