"""Tests for the HAAnim config module."""

from __future__ import annotations

import pytest

from custom_components.haanim.config.config_group import ConfigGroup
from custom_components.haanim.config.config_option import ConfigOption
from custom_components.haanim.config.config_type import ConfigType


class TestConfigType:
    """Tests for ConfigType enum."""

    def test_all_types_exist(self) -> None:
        """Test all expected config types exist."""
        assert ConfigType.STRING.value == "string"
        assert ConfigType.INTEGER.value == "integer"
        assert ConfigType.FLOAT.value == "float"
        assert ConfigType.BOOLEAN.value == "boolean"
        assert ConfigType.SELECT.value == "select"
        assert ConfigType.LIST.value == "list"


class TestConfigOption:
    """Tests for ConfigOption dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        option = ConfigOption(
            key="test_key",
            config_type=ConfigType.STRING,
            default="test_value",
        )
        assert option.key == "test_key"
        assert option.config_type == ConfigType.STRING
        assert option.default == "test_value"
        assert option.required is True
        assert option.description == ""
        assert option.label == ""
        assert option.options is None
        assert option.validator is None
        assert option.show_in_options is True
        assert option.show_in_setup is True
        assert option.sensitive is False

    def test_all_fields(self) -> None:
        """Test setting all fields."""
        option = ConfigOption(
            key="password",
            config_type=ConfigType.STRING,
            default="",
            required=False,
            description="Enter your password",
            label="Password",
            options=None,
            validator=None,
            show_in_options=True,
            show_in_setup=False,
            sensitive=True,
        )
        assert option.sensitive is True
        assert option.show_in_setup is False

    @pytest.mark.parametrize(
        ("config_type", "default"),
        [
            (ConfigType.STRING, "hello"),
            (ConfigType.INTEGER, 42),
            (ConfigType.FLOAT, 3.14),
            (ConfigType.BOOLEAN, True),
            (ConfigType.LIST, ["a", "b", "c"]),
            (ConfigType.SELECT, "option1"),
        ],
    )
    def test_various_types(self, config_type: ConfigType, default: object) -> None:
        """Test ConfigOption with various types."""
        option = ConfigOption(
            key=f"test_{config_type.value}",
            config_type=config_type,
            default=default,
        )
        assert option.config_type == config_type
        assert option.default == default


class TestConfigGroup:
    """Tests for ConfigGroup dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        group = ConfigGroup(
            name="test_group",
            label="Test Group",
        )
        assert group.name == "test_group"
        assert group.label == "Test Group"
        assert group.description == ""
        assert group.options == []

    def test_with_options(self) -> None:
        """Test group with options."""
        options = [
            ConfigOption(key="opt1", config_type=ConfigType.STRING, default="a"),
            ConfigOption(key="opt2", config_type=ConfigType.INTEGER, default=1),
        ]
        group = ConfigGroup(
            name="my_group",
            label="My Group",
            description="A group of options",
            options=options,
        )
        assert len(group.options) == 2
        assert group.options[0].key == "opt1"
        assert group.options[1].key == "opt2"

    def test_empty_options_list(self) -> None:
        """Test that options defaults to empty list."""
        group = ConfigGroup(name="empty", label="Empty")
        assert isinstance(group.options, list)
        assert len(group.options) == 0
