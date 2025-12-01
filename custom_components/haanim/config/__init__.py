"""Configuration management for HAAnim.

This package provides centralized configuration management including
option definitions, validation, and schema generation.
"""

from __future__ import annotations

from .config_group import ConfigGroup
from .config_manager import ConfigManager, get_config_manager
from .config_option import ConfigOption
from .config_type import ConfigType
from .consts import (
    CONFIG_ALLOW_ALL_IMPORTS,
    CONFIG_IMPORT_ALLOWLIST,
    CONFIG_SCRIPT_PATH,
    DEFAULT_ALLOW_ALL_IMPORTS,
    DEFAULT_IMPORT_ALLOWLIST,
    DEFAULT_NAME,
    DEFAULT_SCRIPT_PATH,
    RESTRICTED_BUILTINS,
)

__all__ = [
    "CONFIG_ALLOW_ALL_IMPORTS",
    "CONFIG_IMPORT_ALLOWLIST",
    "CONFIG_SCRIPT_PATH",
    "ConfigGroup",
    "ConfigManager",
    "ConfigOption",
    "ConfigType",
    "DEFAULT_ALLOW_ALL_IMPORTS",
    "DEFAULT_IMPORT_ALLOWLIST",
    "DEFAULT_NAME",
    "DEFAULT_SCRIPT_PATH",
    "RESTRICTED_BUILTINS",
    "get_config_manager",
]
