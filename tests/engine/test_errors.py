"""Tests for the HAAnim engine errors."""

from __future__ import annotations

import pytest

from custom_components.haanim.engine.errors import (
    ActionCancelledError,
    PoolExhaustedError,
    ScriptError,
    ScriptRuntimeError,
    ScriptSecurityError,
    ScriptSyntaxError,
    ShutdownTimeoutError,
)


class TestScriptError:
    """Tests for the base ScriptError class."""

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
        """Test ScriptError initialization with various parameters."""
        error = ScriptError(message, lineno, col_offset)
        assert str(error) == message
        assert error.lineno == lineno
        assert error.col_offset == col_offset


class TestScriptSecurityError:
    """Tests for ScriptSecurityError."""

    def test_is_script_error(self) -> None:
        """Test that ScriptSecurityError is a ScriptError subclass."""
        error = ScriptSecurityError("Security violation")
        assert isinstance(error, ScriptError)
        assert str(error) == "Security violation"


class TestScriptSyntaxError:
    """Tests for ScriptSyntaxError."""

    def test_with_location(self) -> None:
        """Test ScriptSyntaxError with line and column information."""
        error = ScriptSyntaxError("Invalid syntax", lineno=5, col_offset=10)
        assert error.lineno == 5
        assert error.col_offset == 10


class TestScriptRuntimeError:
    """Tests for ScriptRuntimeError."""

    def test_is_script_error(self) -> None:
        """Test that ScriptRuntimeError is a ScriptError subclass."""
        error = ScriptRuntimeError("Runtime error occurred")
        assert isinstance(error, ScriptError)


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
            ("test", "script reload"),
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
        error = ShutdownTimeoutError("my_script", 0.2)
        assert error.script_name == "my_script"
        assert error.timeout == 0.2
        assert "my_script" in str(error)
        assert "200ms" in str(error)
