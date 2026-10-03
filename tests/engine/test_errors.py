"""Tests for the HAAnim engine errors."""

from __future__ import annotations

import pytest

from typing import Any

from haanim.engine import errors
from haanim.engine.errors import (
    PUBLIC_ERRORS,
    ActionCancelledError,
    ActionDroppedError,
    HAAnimError,
    AutomationRuntimeError,
    AutomationSecurityError,
    AutomationSyntaxError,
    PoolExhaustedError,
    ShutdownTimeoutError,
)

# The Errors table in _design.md ("HAAnim Instance and Event Objects" > "Errors"), one name per row.
DESIGN_ERRORS = [
    "AutomationSyntaxError",
    "AutomationSecurityError",
    "NonExistingAutomationError",
    "AutomationNotLoadedError",
    "AutomationNotRunningError",
    "AutomationAlreadyRunningError",
    "AutomationDisabledError",
    "ActionNotFoundError",
    "ActionDroppedError",
    "QueueFullError",
    "PoolExhaustedError",
    "ActionTimeOutError",
    "ActionCancelledError",
    "NonExistingEntityError",
    "NonExistingServiceError",
]


class TestErrorsTable:
    """Every error in the design's Errors table exists, derives from HAAnimError and is public."""

    @pytest.mark.parametrize("name", DESIGN_ERRORS)
    def test_error_exists_and_derives_from_base(self, name: str) -> None:
        """Test each documented error is defined and is an HAAnimError."""
        error_class = getattr(errors, name)
        assert issubclass(error_class, HAAnimError)
        assert error_class is not HAAnimError

    @pytest.mark.parametrize("name", DESIGN_ERRORS)
    def test_error_is_public(self, name: str) -> None:
        """Test each documented error is exported to automations."""
        assert getattr(errors, name) in PUBLIC_ERRORS

    def test_public_errors_are_exactly_the_table_plus_base(self) -> None:
        """Test nothing undocumented is exported."""
        assert {cls.__name__ for cls in PUBLIC_ERRORS} == {"HAAnimError", *DESIGN_ERRORS}

    def test_removed_errors_are_gone(self) -> None:
        """Test errors the design removed no longer exist."""
        assert not hasattr(errors, "ActionFailedError")


class TestErrorConstruction:
    """Each error stores its arguments and mentions them in its message."""

    @pytest.mark.parametrize(
        ("name", "args", "attributes"),
        [
            ("AutomationDisabledError", ("auto",), {"automation_id": "auto"}),
            ("AutomationNotLoadedError", ("auto",), {"automation_id": "auto"}),
            ("AutomationAlreadyRunningError", ("auto",), {"automation_id": "auto"}),
            ("AutomationNotRunningError", ("auto",), {"automation_id": "auto"}),
            ("NonExistingAutomationError", ("auto",), {"automation_id": "auto"}),
            ("NonExistingEntityError", ("sensor.temp",), {"entity_id": "sensor.temp"}),
            ("NonExistingServiceError", ("light", "turn_on"), {"domain": "light", "service": "turn_on"}),
            ("ActionNotFoundError", ("auto", "act"), {"automation_id": "auto", "action_name": "act"}),
            (
                "ActionDroppedError",
                ("auto", "act", "re-entrant call"),
                {"automation_id": "auto", "action_name": "act", "reason": "re-entrant call"},
            ),
            (
                "ActionTimeOutError",
                ("auto", "act", 30.5),
                {"automation_id": "auto", "action_name": "act", "timeout": 30.5},
            ),
            (
                "QueueFullError",
                ("auto", "act", 100),
                {"automation_id": "auto", "action_name": "act", "queue_size": 100},
            ),
        ],
    )
    def test_init(self, name: str, args: tuple[Any, ...], attributes: dict[str, Any]) -> None:
        """Test the error keeps its arguments as attributes and in its message."""
        error = getattr(errors, name)(*args)
        assert isinstance(error, HAAnimError)
        for attribute, value in attributes.items():
            assert getattr(error, attribute) == value
            assert str(value) in str(error)
        assert error.lineno is None
        assert error.col_offset is None

    def test_action_dropped_default_reason(self) -> None:
        """Test ActionDroppedError defaults to the DROP-mode reason."""
        error = ActionDroppedError("auto", "act")
        assert error.reason == "already executing"
        assert "already executing" in str(error)


class TestHAAnimError:
    """Tests for the base HAAnimError class."""

    @pytest.mark.parametrize(
        ("message", "lineno", "col_offset"),
        [
            ("Simple error", None, None),
            ("Error with line", 10, None),
            ("Error with line and col", 10, 5),
            ("", None, None),
        ],
    )
    def test_init(self, message: str, lineno: int | None, col_offset: int | None) -> None:
        """Test HAAnimError initialization with various parameters."""
        error = HAAnimError(message, lineno, col_offset)
        assert str(error) == message
        assert error.lineno == lineno
        assert error.col_offset == col_offset


class TestAutomationSecurityError:
    """Tests for AutomationSecurityError."""

    def test_is_haanim_error(self) -> None:
        """Test that AutomationSecurityError is an HAAnimError subclass."""
        error = AutomationSecurityError("Security violation")
        assert isinstance(error, HAAnimError)
        assert str(error) == "Security violation"


class TestAutomationSyntaxError:
    """Tests for AutomationSyntaxError."""

    def test_with_location(self) -> None:
        """Test AutomationSyntaxError with line and column information."""
        error = AutomationSyntaxError("Invalid syntax", lineno=5, col_offset=10)
        assert error.lineno == 5
        assert error.col_offset == 10


class TestAutomationRuntimeError:
    """Tests for AutomationRuntimeError."""

    def test_is_haanim_error(self) -> None:
        """Test that AutomationRuntimeError is an HAAnimError subclass."""
        error = AutomationRuntimeError("Runtime error occurred")
        assert isinstance(error, HAAnimError)


class TestPoolExhaustedError:
    """Tests for PoolExhaustedError."""

    def test_init(self) -> None:
        """Test PoolExhaustedError initialization."""
        error = PoolExhaustedError(20)
        assert error.max_workers == 20
        assert "20" in str(error)
        assert "exhausted" in str(error).lower()


class TestActionCancelledError:
    """Tests for ActionCancelledError."""

    @pytest.mark.parametrize(
        ("action_name", "reason"),
        [
            ("my_action", "shutdown requested"),
            ("another_action", "user cancelled"),
            ("test", "automation reload"),
        ],
    )
    def test_init(self, action_name: str, reason: str) -> None:
        """Test ActionCancelledError with various reasons."""
        error = ActionCancelledError(action_name, reason)
        assert error.action_name == action_name
        assert error.reason == reason
        assert action_name in str(error)
        assert reason in str(error)

    def test_default_reason(self) -> None:
        """Test ActionCancelledError with default reason."""
        error = ActionCancelledError("my_action")
        assert error.reason == "shutdown requested"


class TestShutdownTimeoutError:
    """Tests for ShutdownTimeoutError."""

    def test_init(self) -> None:
        """Test ShutdownTimeoutError initialization."""
        error = ShutdownTimeoutError("my_automation", 0.2)
        assert error.automation_id == "my_automation"
        assert error.timeout == 0.2
        assert "my_automation" in str(error)
        assert "200ms" in str(error)
