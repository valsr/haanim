"""Configuration value types for HAAnim."""

from __future__ import annotations

from enum import Enum


class ConfigType(Enum):
    """Configuration value types.

    Defines the supported types for configuration options used throughout
    the HAAnim integration.
    """

    STRING = "string"
    BOOLEAN = "boolean"
    INTEGER = "integer"
    FLOAT = "float"
    LIST = "list"
    SELECT = "select"
