"""Configuration option definition for HAAnim."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custom_components.haanim.config.config_type import ConfigType


@dataclass
class ConfigOption:
    """Represents a single configuration option.

    A ConfigOption defines a single configuration value that can be set by
    the user during setup or in the options flow.

    Args:
        key: The configuration key name.
        config_type: The type of the configuration value.
        default: The default value.
        required: Whether the option is required.
        description: Human-readable description.
        label: Human-readable label for UI.
        options: For SELECT type, list of valid options.
        validator: Optional custom validator function.
        show_in_options: Whether to show in options flow.
        show_in_setup: Whether to show in initial setup.
        sensitive: Whether this is a sensitive value (e.g., password).
    """

    key: str
    config_type: ConfigType
    default: Any
    required: bool = True
    description: str = ""
    label: str = ""
    options: list[Any] | None = None
    validator: Any | None = None
    show_in_options: bool = True
    show_in_setup: bool = True
    sensitive: bool = False
