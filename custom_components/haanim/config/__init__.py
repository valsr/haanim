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


def get_automation_refresh_interval() -> int:
    """Get the automation refresh interval in seconds.

    Returns:
        Refresh interval in seconds.
    """
    return get_config_manager().get_automation_refresh_interval()


def get_max_concurrent_actions():
    """Get the maximum number of concurrent actions.

    Returns:
        Maximum number of concurrent actions.
    """
    return get_config_manager().get_max_concurrent_actions()


def get_worker_shutdown_timeout() -> float:
    """Get the worker shutdown timeout in seconds.

    Returns:
        Worker shutdown timeout in seconds.
    """
    return get_config_manager().get_worker_shutdown_timeout()
