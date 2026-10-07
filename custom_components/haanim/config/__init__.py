"""Configuration management for HAAnim.

This package provides centralized configuration management including
option definitions, validation, and schema generation.
"""

from __future__ import annotations

from custom_components.haanim.config.config_group import ConfigGroup
from custom_components.haanim.config.config_manager import ConfigManager, get_config_manager
from custom_components.haanim.config.config_option import ConfigOption
from custom_components.haanim.config.config_type import ConfigType

__all__ = [
    "ConfigGroup",
    "ConfigManager",
    "ConfigOption",
    "ConfigType",
    "get_config_manager",
]


def get_automation_path() -> str:
    """Get the full path to the automation folder.

    Returns:
        Absolute path to the automation folder.
    """
    return get_config_manager().get_automation_path()


def get_import_allowlist() -> list[str]:
    """Get the list of allowed imports.

    Returns:
        List of allowed module names.
    """
    return get_config_manager().get_import_allowlist()


def get_allow_all_imports() -> bool:
    """Check if all imports are allowed.

    Returns:
        True if all imports are allowed, False otherwise.
    """
    return get_config_manager().get_allow_all_imports()
