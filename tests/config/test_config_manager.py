"""Tests for the HAAnim configuration manager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.haanim.config.config_group import ConfigGroup
from custom_components.haanim.config.config_manager import ConfigManager, get_config_manager
from custom_components.haanim.config.config_option import ConfigOption
from custom_components.haanim.config.config_type import ConfigType


@pytest.fixture
def reset_config_manager() -> None:
    """Reset the ConfigManager singleton before and after test."""
    # Reset before test
    ConfigManager._instance = None
    ConfigManager._initialized = False
    yield
    # Reset after test
    ConfigManager._instance = None
    ConfigManager._initialized = False


class TestConfigManagerSingleton:
    """Tests for ConfigManager singleton behavior."""

    def test_singleton_pattern(self, reset_config_manager: None) -> None:
        """Test that ConfigManager is a singleton."""
        manager1 = ConfigManager()
        manager2 = ConfigManager()
        assert manager1 is manager2

    def test_get_config_manager(self, reset_config_manager: None) -> None:
        """Test get_config_manager returns singleton."""
        manager1 = get_config_manager()
        manager2 = get_config_manager()
        assert manager1 is manager2


class TestConfigManagerDefaults:
    """Tests for ConfigManager default configuration."""

    def test_has_default_groups(self, reset_config_manager: None) -> None:
        """Test that default groups are registered."""
        manager = ConfigManager()
        groups = manager.get_groups()

        assert "general" in groups
        assert "security" in groups

    def test_has_default_options(self, reset_config_manager: None) -> None:
        """Test that default options are registered."""
        manager = ConfigManager()
        options = manager.get_all_options()

        assert "name" in options
        assert "script_path" in options
        assert "allow_all_imports" in options
        assert "import_allowlist" in options

    def test_get_defaults(self, reset_config_manager: None) -> None:
        """Test getting default values."""
        manager = ConfigManager()
        defaults = manager.get_defaults()

        assert defaults["name"] == "HAAnim"
        assert defaults["script_path"] == "/config/haanim"
        assert defaults["allow_all_imports"] is False
        assert isinstance(defaults["import_allowlist"], list)


class TestConfigManagerGetSet:
    """Tests for ConfigManager get/set operations."""

    def test_get_existing_value(self, reset_config_manager: None) -> None:
        """Test getting an existing value."""
        manager = ConfigManager()
        manager.set("name", "Custom Name")

        assert manager.get("name") == "Custom Name"

    def test_get_with_default_fallback(self, reset_config_manager: None) -> None:
        """Test getting value falls back to option default."""
        manager = ConfigManager()
        # name should have default "HAAnim"
        assert manager.get("name") == "HAAnim"

    def test_get_unknown_key(self, reset_config_manager: None) -> None:
        """Test getting unknown key returns None."""
        manager = ConfigManager()
        assert manager.get("unknown_key") is None

    def test_get_unknown_key_with_default(self, reset_config_manager: None) -> None:
        """Test getting unknown key with explicit default."""
        manager = ConfigManager()
        assert manager.get("unknown_key", "my_default") == "my_default"

    def test_set_value(self, reset_config_manager: None) -> None:
        """Test setting a value."""
        manager = ConfigManager()
        manager.set("script_path", "/custom/path")

        assert manager.get("script_path") == "/custom/path"

    def test_get_all(self, reset_config_manager: None) -> None:
        """Test getting all values."""
        manager = ConfigManager()
        manager.set("name", "Test")
        manager.set("script_path", "/test")

        all_values = manager.get_all()

        assert all_values["name"] == "Test"
        assert all_values["script_path"] == "/test"
        assert "allow_all_imports" in all_values


class TestConfigManagerRegistration:
    """Tests for registering options and groups."""

    def test_register_group(self, reset_config_manager: None) -> None:
        """Test registering a new group."""
        manager = ConfigManager()

        new_group = ConfigGroup(
            name="custom",
            label="Custom Settings",
            description="Custom group",
            options=[
                ConfigOption(key="custom_opt", config_type=ConfigType.STRING, default="value")
            ],
        )
        manager.register_group(new_group)

        groups = manager.get_groups()
        assert "custom" in groups
        assert manager.get_option("custom_opt") is not None

    def test_register_option_creates_group(self, reset_config_manager: None) -> None:
        """Test registering option to non-existent group creates it."""
        manager = ConfigManager()

        option = ConfigOption(key="new_opt", config_type=ConfigType.INTEGER, default=42)
        manager.register_option("new_group", option)

        groups = manager.get_groups()
        assert "new_group" in groups
        assert manager.get_option("new_opt") is not None

    def test_register_duplicate_option_skipped(self, reset_config_manager: None) -> None:
        """Test that duplicate options are skipped."""
        manager = ConfigManager()

        option1 = ConfigOption(key="dup_key", config_type=ConfigType.STRING, default="first")
        option2 = ConfigOption(key="dup_key", config_type=ConfigType.STRING, default="second")

        manager.register_option("group1", option1)
        manager.register_option("group2", option2)  # Should be skipped

        # Should still have first value
        assert manager.get_option("dup_key").default == "first"


class TestConfigManagerLoadFromDict:
    """Tests for loading configuration from dictionary."""

    def test_load_from_data(self, reset_config_manager: None) -> None:
        """Test loading from data dictionary."""
        manager = ConfigManager()

        data = {
            "name": "From Dict",
            "script_path": "/dict/path",
        }
        manager.load_from_dict(data)

        assert manager.get("name") == "From Dict"
        assert manager.get("script_path") == "/dict/path"

    def test_load_from_options_takes_precedence(self, reset_config_manager: None) -> None:
        """Test that options take precedence over data."""
        manager = ConfigManager()

        data = {"name": "From Data"}
        options = {"name": "From Options"}

        manager.load_from_dict(data, options)

        assert manager.get("name") == "From Options"

    def test_load_ignores_unknown_keys(self, reset_config_manager: None) -> None:
        """Test that unknown keys are ignored."""
        manager = ConfigManager()

        data = {
            "name": "Valid",
            "unknown_key": "Ignored",
        }
        manager.load_from_dict(data)

        assert manager.get("name") == "Valid"
        assert manager.get("unknown_key") is None


class TestConfigManagerSchema:
    """Tests for schema generation."""

    def test_generate_setup_schema(self, reset_config_manager: None) -> None:
        """Test generating setup schema."""
        manager = ConfigManager()
        schema = manager.generate_setup_schema()

        assert schema is not None
        # Schema should be callable
        result = schema({"name": "Test", "script_path": "/path"})
        assert result["name"] == "Test"

    def test_generate_options_schema(self, reset_config_manager: None) -> None:
        """Test generating options schema."""
        manager = ConfigManager()
        manager.set("script_path", "/current/path")

        schema = manager.generate_options_schema()
        assert schema is not None


class TestConfigManagerDump:
    """Tests for configuration dump."""

    def test_dump_contains_groups(self, reset_config_manager: None) -> None:
        """Test that dump contains groups."""
        manager = ConfigManager()
        dump = manager.dump()

        assert "groups" in dump
        assert "general" in dump["groups"]
        assert "security" in dump["groups"]

    def test_dump_contains_values(self, reset_config_manager: None) -> None:
        """Test that dump contains values."""
        manager = ConfigManager()
        manager.set("name", "Dumped")

        dump = manager.dump()

        assert "values" in dump
        assert dump["values"]["name"] == "Dumped"

    def test_dump_contains_defaults(self, reset_config_manager: None) -> None:
        """Test that dump contains defaults."""
        manager = ConfigManager()
        dump = manager.dump()

        assert "defaults" in dump
        assert "name" in dump["defaults"]


class TestConfigManagerHelpers:
    """Tests for helper methods."""

    def test_get_option(self, reset_config_manager: None) -> None:
        """Test getting option definition."""
        manager = ConfigManager()
        option = manager.get_option("name")

        assert option is not None
        assert option.key == "name"
        assert option.config_type == ConfigType.STRING

    def test_get_option_unknown(self, reset_config_manager: None) -> None:
        """Test getting unknown option returns None."""
        manager = ConfigManager()
        assert manager.get_option("unknown") is None

    def test_get_import_allowlist(self, reset_config_manager: None) -> None:
        """Test getting import allowlist."""
        manager = ConfigManager()
        allowlist = manager.get_import_allowlist()

        assert isinstance(allowlist, list)
        assert "asyncio" in allowlist
        assert "datetime" in allowlist

    def test_get_allow_all_imports_default_false(self, reset_config_manager: None) -> None:
        """Test allow_all_imports defaults to False."""
        manager = ConfigManager()
        assert manager.get_allow_all_imports() is False

    def test_get_allow_all_imports_true(self, reset_config_manager: None) -> None:
        """Test allow_all_imports when set to True."""
        manager = ConfigManager()
        manager.set("allow_all_imports", True)
        assert manager.get_allow_all_imports() is True

    def test_get_script_refresh_interval(self, reset_config_manager: None) -> None:
        """Test getting script refresh interval."""
        manager = ConfigManager()
        interval = manager.get_script_refresh_interval()

        assert isinstance(interval, int)
        assert interval > 0

    def test_get_script_path_absolute(self, reset_config_manager: None) -> None:
        """Test getting absolute script path."""
        manager = ConfigManager()
        manager.set("script_path", "/absolute/path")

        path = manager.get_script_path()
        assert path == "/absolute/path"


class TestConfigManagerValidation:
    """Tests for validation methods."""

    def test_validate_script_path_no_hass(self, reset_config_manager: None) -> None:
        """Test validation without hass returns True."""
        manager = ConfigManager()
        is_valid, error = manager.validate_script_path("/any/path")

        assert is_valid is True
        assert error is None

    def test_validate_script_path_with_hass(self, reset_config_manager: None) -> None:
        """Test validation with hass and existing parent."""
        manager = ConfigManager()

        # Create mock hass with config_dir
        mock_hass = MagicMock()
        mock_hass.config.config_dir = "/tmp"
        manager._hass = mock_hass

        # Path with existing parent (/tmp always exists)
        is_valid, error = manager.validate_script_path("/tmp/haanim")

        assert is_valid is True
        assert error is None
