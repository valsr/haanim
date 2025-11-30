"""Configuration group definition for HAAnim."""

from __future__ import annotations

from dataclasses import dataclass, field

from .config_option import ConfigOption


@dataclass
class ConfigGroup:
    """A group of related configuration options.

    ConfigGroups organize related configuration options together for better
    organization in the UI and logical grouping.

    Args:
        name: Group name/identifier.
        label: Human-readable label.
        description: Human-readable description.
        options: List of ConfigOption in this group.
    """

    name: str
    label: str
    description: str = ""
    options: list[ConfigOption] = field(default_factory=list)
