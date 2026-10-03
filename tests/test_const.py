"""Tests for the HAAnim constants module."""

from __future__ import annotations

from custom_components.haanim.const import (
    ATTRIBUTE_MANUAL,
    ATTRIBUTE_AUTOMATION_PATH,
    ATTRIBUTE_ACTION_NAME,
    ATTRIBUTE_AUTOMATION_ID,
    CONFIG_ALLOW_ALL_IMPORTS,
    CONFIG_IMPORT_ALLOWLIST,
    CONFIG_AUTOMATION_PATH,
    CONFIG_AUTOMATION_REFRESH_INTERVAL,
    DECORATOR_ACTION,
    DECORATOR_EVENT_TRIGGER,
    DECORATOR_SERVICE,
    DECORATOR_SHUTDOWN,
    DECORATOR_STARTUP,
    DECORATOR_STATE_ACTIVE,
    DECORATOR_STATE_TRIGGER,
    DECORATOR_TIME_ACTIVE,
    DECORATOR_TIME_TRIGGER,
    DEFAULT_ALLOW_ALL_IMPORTS,
    DEFAULT_IMPORT_ALLOWLIST,
    DEFAULT_MAX_CONCURRENT_ACTIONS,
    DEFAULT_AUTOMATION_PATH,
    DEFAULT_AUTOMATION_REFRESH_INTERVAL,
    DEFAULT_WORKER_SHUTDOWN_TIMEOUT,
    DOMAIN,
    NAME,
    EVENT_AUTOMATION_ERROR,
    EVENT_AUTOMATION_EXECUTED,
    EVENT_AUTOMATION_LOADED,
    EVENT_AUTOMATION_UNLOADED,
    EXEC_MODE_MANUAL,
    EXEC_MODE_TRIGGER,
    NAME,
    RESTRICTED_BUILTINS,
    SERVICE_GET_CONFIG,
    SERVICE_LIST_ACTIONS,
    SERVICE_LIST_AUTOMATIONS,
    SERVICE_RELOAD_AUTOMATIONS,
    SERVICE_RUN_ACTION,
    VERSION,
)


class TestCoreConstants:
    """Tests for core constants."""

    def test_domain(self) -> None:
        """Test domain constant."""
        assert DOMAIN == "haanim"

    def test_name(self) -> None:
        """Test name constant."""
        assert NAME == "HAAnim"

    def test_version(self) -> None:
        """Test version constant."""
        assert VERSION == "0.1.0"


class TestDecoratorConstants:
    """Tests for decorator name constants."""

    def test_decorator_names(self) -> None:
        """Test all decorator name constants."""
        assert DECORATOR_ACTION == "action"
        assert DECORATOR_STATE_TRIGGER == "state_trigger"
        assert DECORATOR_TIME_TRIGGER == "time_trigger"
        assert DECORATOR_EVENT_TRIGGER == "event_trigger"
        assert DECORATOR_TIME_ACTIVE == "time_active"
        assert DECORATOR_STATE_ACTIVE == "state_active"
        assert DECORATOR_SERVICE == "service"
        assert DECORATOR_STARTUP == "startup"
        assert DECORATOR_SHUTDOWN == "shutdown"


class TestExecutionModes:
    """Tests for execution mode constants."""

    def test_execution_modes(self) -> None:
        """Test execution mode constants."""
        assert EXEC_MODE_MANUAL == "manual"
        assert EXEC_MODE_TRIGGER == "trigger"


class TestEventConstants:
    """Tests for event constants."""

    def test_events_have_domain_prefix(self) -> None:
        """Test events include domain prefix."""
        assert EVENT_AUTOMATION_LOADED.startswith(DOMAIN)
        assert EVENT_AUTOMATION_UNLOADED.startswith(DOMAIN)
        assert EVENT_AUTOMATION_ERROR.startswith(DOMAIN)
        assert EVENT_AUTOMATION_EXECUTED.startswith(DOMAIN)


class TestServiceConstants:
    """Tests for service constants."""

    def test_service_names(self) -> None:
        """Test all service name constants."""
        assert SERVICE_RELOAD_AUTOMATIONS == "reload_automations"
        assert SERVICE_RUN_ACTION == "run_action"
        assert SERVICE_LIST_AUTOMATIONS == "list_automations"
        assert SERVICE_LIST_ACTIONS == "list_actions"
        assert SERVICE_GET_CONFIG == "get_config"


class TestAttributeConstants:
    """Tests for attribute constants."""

    def test_attribute_names(self) -> None:
        """Test all attribute name constants."""
        assert ATTRIBUTE_AUTOMATION_ID == "automation_id"
        assert ATTRIBUTE_AUTOMATION_PATH == "automation_path"
        assert ATTRIBUTE_ACTION_NAME == "action_name"
        assert ATTRIBUTE_MANUAL == "manual"


class TestConfigConstants:
    """Tests for configuration constants."""

    def test_config_keys(self) -> None:
        """Test configuration key constants."""
        assert CONFIG_AUTOMATION_PATH == "automation_path"
        assert CONFIG_IMPORT_ALLOWLIST == "import_allowlist"
        assert CONFIG_ALLOW_ALL_IMPORTS == "allow_all_imports"
        assert CONFIG_AUTOMATION_REFRESH_INTERVAL == "automation_refresh_interval"


class TestDefaultValues:
    """Tests for default value constants."""

    def test_default_values(self) -> None:
        """Test all default value constants."""
        assert NAME == "HAAnim"
        assert DEFAULT_AUTOMATION_PATH == "/config/haanim/automations"
        assert DEFAULT_ALLOW_ALL_IMPORTS is False
        assert DEFAULT_AUTOMATION_REFRESH_INTERVAL == 10
        assert isinstance(DEFAULT_IMPORT_ALLOWLIST, list)
        assert len(DEFAULT_IMPORT_ALLOWLIST) > 0
        assert DEFAULT_MAX_CONCURRENT_ACTIONS == 20
        assert DEFAULT_WORKER_SHUTDOWN_TIMEOUT == 0.2


class TestSecurityConstants:
    """Tests for security constants."""

    def test_restricted_builtins(self) -> None:
        """Test restricted builtins is a set with dangerous functions."""
        assert isinstance(RESTRICTED_BUILTINS, set)
        assert "eval" in RESTRICTED_BUILTINS
        assert "exec" in RESTRICTED_BUILTINS
        assert "__import__" in RESTRICTED_BUILTINS
        assert "compile" in RESTRICTED_BUILTINS
        assert "open" in RESTRICTED_BUILTINS
