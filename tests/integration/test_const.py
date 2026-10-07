"""Tests for the HAAnim constants module."""

from __future__ import annotations

from custom_components.haanim.const import (
    ATTRIBUTE_MANUAL,
    ATTRIBUTE_AUTOMATION_PATH,
    ATTRIBUTE_ACTION,
    ATTRIBUTE_DATA,
    ATTRIBUTE_AUTOMATION_ID,
    CONFIG_ALLOW_ALL_IMPORTS,
    CONFIG_IMPORT_ALLOWLIST,
    CONFIG_AUTOMATION_PATH,
    CONFIG_AUTOMATION_REFRESH_INTERVAL,
    TRIGGER_EVENT,
    CONSTRAINT_STATE,
    TRIGGER_STATE,
    CONSTRAINT_TIME,
    TRIGGER_TIME,
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
    NAME,
    RESTRICTED_BUILTINS,
    SERVICE_RELOAD,
    SERVICE_LIST_ACTIONS,
    SERVICE_LIST_AUTOMATIONS,
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
        assert VERSION == "0.2.0"


class TestKindConstants:
    """Tests for the trigger and constraint kind constants."""

    def test_kinds(self) -> None:
        """Test the kinds are named after what the decorators are called, without the on_ prefix."""
        assert TRIGGER_STATE == "state"
        assert TRIGGER_TIME == "time"
        assert TRIGGER_EVENT == "event"
        assert CONSTRAINT_TIME == "time"
        assert CONSTRAINT_STATE == "state"


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
        assert SERVICE_RELOAD == "reload"
        assert SERVICE_RUN_ACTION == "run_action"
        assert SERVICE_LIST_AUTOMATIONS == "list_automations"
        assert SERVICE_LIST_ACTIONS == "list_actions"


class TestAttributeConstants:
    """Tests for attribute constants."""

    def test_attribute_names(self) -> None:
        """Test all attribute name constants."""
        assert ATTRIBUTE_AUTOMATION_ID == "automation_id"
        assert ATTRIBUTE_AUTOMATION_PATH == "automation_path"
        assert ATTRIBUTE_ACTION == "action"
        assert ATTRIBUTE_DATA == "data"
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


class TestEngineConstantsReExported:
    """The integration constants module re-exports the engine constants unchanged."""

    def test_engine_constants_are_re_exported(self) -> None:
        """Test every engine constant is available from the integration module as the same object."""
        from custom_components.haanim import (
            const as integration_const,
        )  # pylint: disable=import-outside-toplevel
        from haanim import const as engine_const  # pylint: disable=import-outside-toplevel

        for name in engine_const.__all__:
            assert name in integration_const.__all__
            assert getattr(integration_const, name) is getattr(engine_const, name)

    def test_no_duplicate_exports(self) -> None:
        """Test no name is exported twice."""
        from custom_components.haanim import (
            const as integration_const,
        )  # pylint: disable=import-outside-toplevel

        assert len(integration_const.__all__) == len(set(integration_const.__all__))
