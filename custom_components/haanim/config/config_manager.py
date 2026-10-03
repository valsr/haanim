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

from custom_components.haanim import const
from custom_components.haanim.config.config_group import ConfigGroup
from custom_components.haanim.config.config_option import ConfigOption
from custom_components.haanim.config.config_type import ConfigType


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
            description="Basic configuration",
            options=[
                ConfigOption(
                    key=const.CONFIG_NAME,
                    config_type=ConfigType.STRING,
                    default=const.NAME,
                    required=True,
                    label="Name",
                    description="Display name for the integration",
                    show_in_options=False,
                ),
                ConfigOption(
                    key=const.CONFIG_AUTOMATION_PATH,
                    config_type=ConfigType.STRING,
                    default=const.DEFAULT_AUTOMATION_PATH,
                    required=True,
                    label="Automation Path",
                    description="Path for automations (absolute path)",
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
                    key=const.CONFIG_ALLOW_ALL_IMPORTS,
                    config_type=ConfigType.BOOLEAN,
                    default=const.DEFAULT_ALLOW_ALL_IMPORTS,
                    required=True,
                    label="Allow All Imports",
                    description="If enabled, automations can import any Python module. Use with caution!",
                ),
                ConfigOption(
                    key=const.CONFIG_IMPORT_ALLOWLIST,
                    config_type=ConfigType.LIST,
                    default=const.DEFAULT_IMPORT_ALLOWLIST,
                    required=False,
                    label="Import Allowlist",
                    description="List of allowed module names for import",
                    show_in_setup=False,
                ),
            ],
        )
        self.register_group(security_group)

        # Worker settings group
        worker_group = ConfigGroup(
            name="worker",
            label="Worker/Actions Settings",
            description="Configuration for actions/workers",
            options=[
                ConfigOption(
                    key=const.CONFIG_MAX_CONCURRENT_ACTIONS,
                    config_type=ConfigType.INTEGER,
                    default=const.DEFAULT_MAX_CONCURRENT_ACTIONS,
                    required=False,
                    label="Max Concurrent Actions",
                    description="Maximum concurrent actions across all automations. Minimum value 1.",
                ),
                ConfigOption(
                    key=const.CONFIG_WORKER_SHUTDOWN_TIMEOUT,
                    config_type=ConfigType.INTEGER,
                    default=const.DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
                    required=False,
                    label="Worker Shutdown Timeout",
                    description="Timeout in seconds for worker shutdown action. <=0 will wait indefinately.",
                ),
            ],
        )
        self.register_group(worker_group)

    def register_group(self, group: ConfigGroup) -> None:
        """Register a configuration group.

        Args:
            group: The configuration group to register.
        """
        _LOGGER.debug("Registering config group: '%s' with %d options", group.name, len(group.options))
        self._groups[group.name] = group
        for option in group.options:
            self.register_option(group.name, option)

    def register_option(self, group_name: str, option: ConfigOption) -> None:
        """Register a single configuration option to a group.

        Args:
            group_name: The name of the group to add the option to.
            option: The configuration option to register.
        """
        if option.key in self._options:
            _LOGGER.warning("Configuration option '%s' is already registered, skipping", option.key)
            return

        if group_name not in self._groups:
            _LOGGER.debug("Creating new config group: '%s'", group_name)
            self._groups[group_name] = ConfigGroup(name=group_name, label=group_name.title())

        if option not in self._groups[group_name].options:
            self._groups[group_name].options.append(option)
            _LOGGER.debug("Registered option '%s' in group '%s'", option.key, group_name)

        self._options[option.key] = option
        if option.key not in self._values:
            self._values[option.key] = option.default
        _LOGGER.debug("Registered option '%s' in group '%s'", option.key, group_name)

    def setup(self, hass: HomeAssistant, entry_id: str | None = None) -> None:
        """Set up the configuration manager with Home Assistant instance.

        Args:
            hass: Home Assistant instance.
            entry_id: Optional config entry ID.
        """
        _LOGGER.debug("Setting up ConfigManager with entry_id: %s", entry_id)
        self._hass = hass
        self._entry_id = entry_id
        self._load_from_entry()
        _LOGGER.info("ConfigManager setup complete")

    def _load_from_entry(self) -> None:
        """Load configuration values from config entry."""
        if not self._hass or not self._entry_id:
            _LOGGER.debug("Skipping _load_from_entry: hass=%s, entry_id=%s", self._hass, self._entry_id)
            return

        _LOGGER.debug("Loading configuration from entry: %s", self._entry_id)
        data = self._hass.data.get(const.DOMAIN, {}).get(self._entry_id, {})
        if isinstance(data, dict) and "entry" in data:
            entry = data["entry"]  # type: ignore
            if not isinstance(entry, ConfigEntry):
                _LOGGER.warning("Invalid entry type in data: %s", type(entry))
                return

            # Load from options first, then data
            loaded_count = 0
            for key in self._options:
                if key in entry.options:
                    self._values[key] = entry.options[key]
                    loaded_count += 1
                    _LOGGER.debug("Loaded option '%s' = %s (from options)", key, entry.options[key])
                elif key in entry.data:
                    self._values[key] = entry.data[key]
                    loaded_count += 1
                    _LOGGER.debug("Loaded option '%s' = %s (from data)", key, entry.data[key])
            _LOGGER.info("Loaded %d configuration values from entry", loaded_count)

    def load_from_dict(self, data: Mapping[str, Any], options: Mapping[str, Any] | None = None) -> None:
        """Load configuration values from dictionaries.

        Args:
            data: Configuration data dictionary.
            options: Optional options dictionary (takes precedence).
        """
        _LOGGER.debug("Loading configuration from dict (options provided: %s)", options is not None)
        loaded_count = 0
        for key in self._options:
            if options and key in options:
                self._values[key] = options[key]
                loaded_count += 1
                _LOGGER.debug("Loaded option '%s' = %s (from options)", key, options[key])
            elif key in data:
                self._values[key] = data[key]
                loaded_count += 1
                _LOGGER.debug("Loaded option '%s' = %s (from data)", key, data[key])
        _LOGGER.info("Loaded %d configuration values from dict", loaded_count)

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
        old_value = self._values.get(key)
        self._values[key] = value
        if old_value != value:
            _LOGGER.debug("Configuration changed: '%s' = %s (was: %s)", key, value, old_value)
        else:
            _LOGGER.debug("Configuration set (unchanged): '%s' = %s", key, value)

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

    def validate_automation_path(self, path: str) -> tuple[bool, str | None]:
        """Validate an automation path.

        Args:
            path: The path to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        _LOGGER.debug("Validating automation path: %s", path)
        if not self._hass:
            _LOGGER.debug("No hass instance, skipping validation")
            return True, None

        if os.path.isabs(path):
            folder_path = path
        else:
            folder_path = os.path.join(self._hass.config.config_dir, path)

        parent_dir = os.path.dirname(folder_path)
        if parent_dir and not os.path.exists(parent_dir):
            _LOGGER.warning(
                "Automation path validation failed: parent directory does not exist: %s", parent_dir
            )
            return False, f"Parent directory does not exist: {parent_dir}"

        _LOGGER.debug("Automation path validated successfully: %s", folder_path)
        return True, None

    def get_automation_path(self) -> str:
        """Get the full path to the automation folder.

        Returns:
            Absolute path to the automation folder.
        """
        path = self.get(const.CONFIG_AUTOMATION_PATH, const.DEFAULT_AUTOMATION_PATH)

        if not self._hass:
            return path

        if os.path.isabs(path):
            return path

        return os.path.join(self._hass.config.config_dir, path)

    def get_import_allowlist(self) -> list[str]:
        """Get the list of allowed imports.

        Returns:
            List of allowed module names.
        """
        allowlist: Any = self.get(const.CONFIG_IMPORT_ALLOWLIST, const.DEFAULT_IMPORT_ALLOWLIST)
        if not isinstance(allowlist, list):
            _LOGGER.warning("Import allowlist is not a list, returning empty list")
            return []
        return [str(item) for item in allowlist]  # type: ignore[misc]

    def get_allow_all_imports(self) -> bool:
        """Check if all imports are allowed.

        Returns:
            True if all imports are allowed, False otherwise.
        """
        return bool(self.get(const.CONFIG_ALLOW_ALL_IMPORTS, const.DEFAULT_ALLOW_ALL_IMPORTS))

    def get_automation_refresh_interval(self) -> int:
        """Get the automation refresh interval in seconds.

        Returns:
            Refresh interval in seconds.
        """
        interval: Any = self.get(
            const.CONFIG_AUTOMATION_REFRESH_INTERVAL, const.DEFAULT_AUTOMATION_REFRESH_INTERVAL
        )
        try:
            return int(interval)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid automation refresh interval: %s, defaulting to %d seconds",
                interval,
                const.DEFAULT_AUTOMATION_REFRESH_INTERVAL,
            )
            return const.DEFAULT_AUTOMATION_REFRESH_INTERVAL

    def get_max_concurrent_actions(self):
        """Get the maximum number of concurrent actions.

        Returns:
            Maximum number of concurrent actions.
        """
        max_actions: Any = self.get(const.CONFIG_MAX_CONCURRENT_ACTIONS, const.DEFAULT_MAX_CONCURRENT_ACTIONS)
        try:
            value = int(max_actions)
            return max(1, value)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid max concurrent actions: %s, defaulting to %d",
                max_actions,
                const.DEFAULT_MAX_CONCURRENT_ACTIONS,
            )
            return const.DEFAULT_MAX_CONCURRENT_ACTIONS

    def get_worker_shutdown_timeout(self) -> float:
        """Get the worker shutdown timeout in seconds.

        Returns:
            Worker shutdown timeout in seconds.
        """
        timeout: Any = self.get(const.CONFIG_WORKER_SHUTDOWN_TIMEOUT, const.DEFAULT_WORKER_SHUTDOWN_TIMEOUT)
        try:
            return float(timeout)
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Invalid worker shutdown timeout: %s, defaulting to %.2f seconds",
                timeout,
                const.DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
            )
            return const.DEFAULT_WORKER_SHUTDOWN_TIMEOUT


def get_config_manager() -> ConfigManager:
    """Get the singleton ConfigManager instance.

    Returns:
        The ConfigManager singleton.
    """
    return ConfigManager()
