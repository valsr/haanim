"""Tests for script execution status tracking (engine/script_status.py)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from custom_components.haanim.engine.script_status import (
    ScriptRunState,
    ScriptStatus,
    ScriptStatusManager,
    get_status_manager,
    reset_status_manager,
)


@pytest.fixture
def manager() -> ScriptStatusManager:
    """Create a fresh status manager."""
    return ScriptStatusManager()


@pytest.fixture
def clean_global_manager() -> Generator[None]:
    """Reset the global status manager around a test."""
    reset_status_manager()
    yield
    reset_status_manager()


class TestScriptRunState:
    """Tests for the ScriptRunState enum."""

    @pytest.mark.parametrize(
        ("state", "value"),
        [
            (ScriptRunState.IDLE, "idle"),
            (ScriptRunState.RUNNING, "running"),
            (ScriptRunState.STARTUP, "startup"),
            (ScriptRunState.SHUTDOWN, "shutdown"),
        ],
    )
    def test_values(self, state: ScriptRunState, value: str) -> None:
        """Test each run state has the expected value."""
        assert state.value == value


class TestScriptStatus:
    """Tests for the ScriptStatus dataclass."""

    def test_defaults(self) -> None:
        """Test a new status is idle with no actions or error."""
        status = ScriptStatus(script_name="test")
        assert status.script_name == "test"
        assert status.run_state == ScriptRunState.IDLE
        assert status.running_actions == {}
        assert status.last_error is None
        assert status.is_running is False

    def test_is_running_with_actions(self) -> None:
        """Test is_running reflects running actions."""
        status = ScriptStatus(script_name="test", running_actions={"id1": "action"})
        assert status.is_running is True

    def test_running_actions_not_shared(self) -> None:
        """Test each status gets its own running_actions dictionary."""
        first = ScriptStatus(script_name="a")
        second = ScriptStatus(script_name="b")
        first.running_actions["id1"] = "action"
        assert second.running_actions == {}


class TestScriptStatusManager:
    """Tests for ScriptStatusManager."""

    def test_get_status_creates_and_caches(self, manager: ScriptStatusManager) -> None:
        """Test get_status creates a status once and returns the same object after."""
        status = manager.get_status("script")
        assert status.script_name == "script"
        assert manager.get_status("script") is status

    @pytest.mark.parametrize(
        ("is_startup", "is_shutdown", "expected"),
        [
            (False, False, ScriptRunState.RUNNING),
            (True, False, ScriptRunState.STARTUP),
            (False, True, ScriptRunState.SHUTDOWN),
            (True, True, ScriptRunState.STARTUP),
        ],
    )
    def test_add_running_action_sets_state(
        self,
        manager: ScriptStatusManager,
        is_startup: bool,
        is_shutdown: bool,
        expected: ScriptRunState,
    ) -> None:
        """Test add_running_action records the action and sets the run state."""
        manager.add_running_action("script", "action", "id1", is_startup=is_startup, is_shutdown=is_shutdown)
        status = manager.get_status("script")
        assert status.running_actions == {"id1": "action"}
        assert status.run_state == expected
        assert status.is_running is True

    def test_remove_last_action_sets_idle(self, manager: ScriptStatusManager) -> None:
        """Test removing the only running action returns the script to idle."""
        manager.add_running_action("script", "action", "id1")
        manager.remove_running_action("script", "id1")
        status = manager.get_status("script")
        assert status.running_actions == {}
        assert status.run_state == ScriptRunState.IDLE
        assert status.last_error is None

    def test_remove_one_of_two_stays_running(self, manager: ScriptStatusManager) -> None:
        """Test the script stays running while another action is active."""
        manager.add_running_action("script", "first", "id1")
        manager.add_running_action("script", "second", "id2")
        manager.remove_running_action("script", "id1")
        status = manager.get_status("script")
        assert status.running_actions == {"id2": "second"}
        assert status.run_state == ScriptRunState.RUNNING

    def test_remove_with_error_records_error(self, manager: ScriptStatusManager) -> None:
        """Test an error passed on removal is stored."""
        manager.add_running_action("script", "action", "id1")
        manager.remove_running_action("script", "id1", error="boom")
        assert manager.get_status("script").last_error == "boom"

    def test_remove_unknown_execution_is_ignored(self, manager: ScriptStatusManager) -> None:
        """Test removing an execution that is not running does nothing."""
        manager.add_running_action("script", "action", "id1")
        manager.remove_running_action("script", "other")
        assert manager.get_status("script").running_actions == {"id1": "action"}

    @pytest.mark.parametrize(("error", "expected"), [(None, None), ("failed", "failed")])
    def test_set_idle(self, manager: ScriptStatusManager, error: str | None, expected: str | None) -> None:
        """Test set_idle clears running actions and optionally records an error."""
        manager.add_running_action("script", "action", "id1")
        manager.set_idle("script", error=error)
        status = manager.get_status("script")
        assert status.run_state == ScriptRunState.IDLE
        assert status.running_actions == {}
        assert status.last_error == expected

    def test_set_idle_without_error_keeps_previous_error(self, manager: ScriptStatusManager) -> None:
        """Test set_idle without an error leaves an earlier error in place."""
        manager.set_idle("script", error="earlier")
        manager.set_idle("script")
        assert manager.get_status("script").last_error == "earlier"

    def test_clear_error(self, manager: ScriptStatusManager) -> None:
        """Test clear_error removes the stored error."""
        manager.set_idle("script", error="failed")
        manager.clear_error("script")
        assert manager.get_status("script").last_error is None

    def test_set_status_message(self, manager: ScriptStatusManager) -> None:
        """Test set_status_message stores the message (currently in last_error)."""
        manager.set_status_message("script", "working")
        assert manager.get_status("script").last_error == "working"

    def test_get_all_statuses_returns_copy(self, manager: ScriptStatusManager) -> None:
        """Test get_all_statuses returns every status in a separate dictionary."""
        manager.get_status("a")
        manager.get_status("b")
        statuses = manager.get_all_statuses()
        assert set(statuses) == {"a", "b"}
        statuses.clear()
        assert set(manager.get_all_statuses()) == {"a", "b"}


class TestGlobalStatusManager:
    """Tests for the module-level status manager accessors."""

    def test_get_status_manager_is_singleton(self, clean_global_manager: None) -> None:
        """Test get_status_manager returns the same instance each time."""
        assert get_status_manager() is get_status_manager()

    def test_reset_status_manager(self, clean_global_manager: None) -> None:
        """Test reset_status_manager discards the current instance."""
        first = get_status_manager()
        reset_status_manager()
        assert get_status_manager() is not first
