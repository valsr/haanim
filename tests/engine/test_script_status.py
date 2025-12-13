"""Tests for the HAAnim script status module."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.haanim.engine.script_status import (
    ScriptRunState,
    ScriptStatus,
    ScriptStatusManager,
    get_status_manager,
    reset_status_manager,
)


class TestScriptRunState:
    """Tests for ScriptRunState enum."""

    def test_values(self) -> None:
        """Test all enum values exist."""
        assert ScriptRunState.IDLE.value == "idle"
        assert ScriptRunState.RUNNING.value == "running"
        assert ScriptRunState.STARTUP.value == "starting"
        assert ScriptRunState.SHUTDOWN.value == "stopping"


class TestScriptStatus:
    """Tests for ScriptStatus dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""
        status = ScriptStatus(script_name="test")
        assert status.script_name == "test"
        assert status.run_state == ScriptRunState.IDLE
        assert status.action_name is None
        assert status.status_message is None
        assert status.last_action is None
        assert status.last_action_completed_at is None
        assert status.last_error is None

    def test_get_elapsed_seconds(self) -> None:
        """Test elapsed time calculation."""
        status = ScriptStatus(script_name="test")
        # State changed at should be now, so elapsed should be close to 0
        elapsed = status.get_elapsed_seconds()
        assert 0 <= elapsed < 1

    @pytest.mark.parametrize(
        ("seconds", "expected_pattern"),
        [
            (5, "5s"),
            (30, "30s"),
            (65, "1m 5s"),
            (125, "2m 5s"),
            (3665, "1h 1m"),
            (7325, "2h 2m"),
        ],
    )
    def test_get_elapsed_formatted(self, seconds: int, expected_pattern: str) -> None:
        """Test formatted elapsed time."""
        status = ScriptStatus(script_name="test")
        status.state_changed_at = datetime.now() - timedelta(seconds=seconds)
        formatted = status.get_elapsed_formatted()
        assert formatted == expected_pattern

    def test_get_display_status_idle(self) -> None:
        """Test display status when idle."""
        status = ScriptStatus(script_name="test")
        assert status.get_display_status() == "Idle"

    def test_get_display_status_running(self) -> None:
        """Test display status when running."""
        status = ScriptStatus(
            script_name="test",
            run_state=ScriptRunState.RUNNING,
            action_name="my_action",
        )
        display = status.get_display_status()
        assert "Running" in display
        assert "my_action" in display

    def test_get_display_status_with_message(self) -> None:
        """Test display status with custom message."""
        status = ScriptStatus(
            script_name="test",
            run_state=ScriptRunState.RUNNING,
            action_name="process",
            status_message="Processing step 2 of 5",
        )
        display = status.get_display_status()
        assert "Processing step 2 of 5" in display

    def test_get_display_status_no_action_name(self) -> None:
        """Test display status running without action name."""
        status = ScriptStatus(
            script_name="test",
            run_state=ScriptRunState.STARTUP,
        )
        display = status.get_display_status()
        assert "Starting" in display

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        status = ScriptStatus(
            script_name="test_script",
            run_state=ScriptRunState.RUNNING,
            action_name="test_action",
            status_message="Testing",
            last_action="previous_action",
            last_error="Some error",
        )
        status.last_action_completed_at = datetime(2024, 1, 1, 12, 0, 0)

        result = status.to_dict()

        assert result["script_name"] == "test_script"
        assert result["run_state"] == "running"
        assert result["action_name"] == "test_action"
        assert result["status_message"] == "Testing"
        assert result["last_action"] == "previous_action"
        assert result["last_error"] == "Some error"
        assert result["last_action_completed_at"] == "2024-01-01T12:00:00"
        assert "elapsed_seconds" in result
        assert "elapsed_formatted" in result
        assert "display_status" in result

    def test_to_dict_no_completed_time(self) -> None:
        """Test to_dict when last_action_completed_at is None."""
        status = ScriptStatus(script_name="test")
        result = status.to_dict()
        assert result["last_action_completed_at"] is None


class TestScriptStatusManager:
    """Tests for ScriptStatusManager."""

    def test_get_status_creates_new(self) -> None:
        """Test get_status creates new status if not exists."""
        manager = ScriptStatusManager()
        status = manager.get_status("new_script")
        assert status.script_name == "new_script"
        assert status.run_state == ScriptRunState.IDLE

    def test_get_status_returns_existing(self) -> None:
        """Test get_status returns existing status."""
        manager = ScriptStatusManager()
        status1 = manager.get_status("script")
        status1.status_message = "Modified"
        status2 = manager.get_status("script")
        assert status2.status_message == "Modified"

    def test_get_all_statuses(self) -> None:
        """Test get_all_statuses returns copy of all statuses."""
        manager = ScriptStatusManager()
        manager.get_status("script1")
        manager.get_status("script2")
        all_statuses = manager.get_all_statuses()
        assert len(all_statuses) == 2
        assert "script1" in all_statuses
        assert "script2" in all_statuses

    @pytest.mark.parametrize(
        ("is_startup", "is_shutdown", "expected_state"),
        [
            (False, False, ScriptRunState.RUNNING),
            (True, False, ScriptRunState.STARTUP),
            (False, True, ScriptRunState.SHUTDOWN),
        ],
    )
    def test_set_running(
        self,
        is_startup: bool,
        is_shutdown: bool,
        expected_state: ScriptRunState,
    ) -> None:
        """Test set_running with different lifecycle flags."""
        manager = ScriptStatusManager()
        manager.set_running("script", "action", is_startup=is_startup, is_shutdown=is_shutdown)
        status = manager.get_status("script")
        assert status.run_state == expected_state
        assert status.action_name == "action"

    def test_set_idle(self) -> None:
        """Test set_idle transitions to idle state."""
        manager = ScriptStatusManager()
        manager.set_running("script", "action")
        manager.set_idle("script")
        status = manager.get_status("script")
        assert status.run_state == ScriptRunState.IDLE
        assert status.action_name is None
        assert status.last_action == "action"
        assert status.last_action_completed_at is not None

    def test_set_idle_with_error(self) -> None:
        """Test set_idle records error."""
        manager = ScriptStatusManager()
        manager.set_running("script", "action")
        manager.set_idle("script", error="Something went wrong")
        status = manager.get_status("script")
        assert status.last_error == "Something went wrong"

    def test_set_status_message(self) -> None:
        """Test setting custom status message."""
        manager = ScriptStatusManager()
        manager.set_status_message("script", "Processing...")
        status = manager.get_status("script")
        assert status.status_message == "Processing..."

    def test_clear_status_message(self) -> None:
        """Test clearing status message."""
        manager = ScriptStatusManager()
        manager.set_status_message("script", "Processing...")
        manager.clear_status_message("script")
        status = manager.get_status("script")
        assert status.status_message is None

    def test_remove_script(self) -> None:
        """Test removing script status."""
        manager = ScriptStatusManager()
        manager.get_status("script")
        assert "script" in manager.get_all_statuses()
        manager.remove_script("script")
        assert "script" not in manager.get_all_statuses()

    def test_remove_nonexistent_script(self) -> None:
        """Test removing non-existent script does not error."""
        manager = ScriptStatusManager()
        manager.remove_script("nonexistent")  # Should not raise

    def test_register_callback(self) -> None:
        """Test registering and receiving callbacks."""
        manager = ScriptStatusManager()
        callback = MagicMock()
        manager.register_callback(callback)

        manager.set_running("script", "action")
        callback.assert_called_once()
        call_args = callback.call_args[0]
        assert call_args[0] == "script"
        assert isinstance(call_args[1], ScriptStatus)

    def test_unregister_callback(self) -> None:
        """Test unregistering callback."""
        manager = ScriptStatusManager()
        callback = MagicMock()
        manager.register_callback(callback)
        manager.unregister_callback(callback)

        manager.set_running("script", "action")
        callback.assert_not_called()

    def test_callback_error_handling(self) -> None:
        """Test that callback errors don't break status updates."""
        manager = ScriptStatusManager()
        bad_callback = MagicMock(side_effect=ValueError("Callback error"))
        good_callback = MagicMock()
        manager.register_callback(bad_callback)
        manager.register_callback(good_callback)

        # Should not raise, and good callback should still be called
        manager.set_running("script", "action")
        good_callback.assert_called_once()


class TestGlobalStatusManager:
    """Tests for global status manager functions."""

    def teardown_method(self) -> None:
        """Reset global state after each test."""
        reset_status_manager()

    def test_get_status_manager_singleton(self) -> None:
        """Test get_status_manager returns same instance."""
        reset_status_manager()
        manager1 = get_status_manager()
        manager2 = get_status_manager()
        assert manager1 is manager2

    def test_reset_status_manager(self) -> None:
        """Test reset_status_manager creates new instance."""
        manager1 = get_status_manager()
        manager1.get_status("test")
        reset_status_manager()
        manager2 = get_status_manager()
        assert manager1 is not manager2
        assert len(manager2.get_all_statuses()) == 0
