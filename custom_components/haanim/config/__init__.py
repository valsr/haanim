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
