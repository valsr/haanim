"""Tests for automation execution status tracking (engine/automation_status.py)."""

from __future__ import annotations

from collections.abc import Generator

import pytest

from haanim.engine.automation_status import (
    AutomationRunState,
    AutomationStatus,
    AutomationStatusManager,
    get_status_manager,
    reset_status_manager,
)


@pytest.fixture
def manager() -> AutomationStatusManager:
    """Create a fresh status manager."""
    return AutomationStatusManager()


@pytest.fixture
def clean_global_manager() -> Generator[None]:
    """Reset the global status manager around a test."""
    reset_status_manager()
    yield
    reset_status_manager()


class TestAutomationRunState:
    """Tests for the AutomationRunState enum."""

    @pytest.mark.parametrize(
        ("state", "value"),
        [
            (AutomationRunState.IDLE, "idle"),
            (AutomationRunState.RUNNING, "running"),
            (AutomationRunState.STARTUP, "startup"),
            (AutomationRunState.SHUTDOWN, "shutdown"),
        ],
    )
    def test_values(self, state: AutomationRunState, value: str) -> None:
        """Test each run state has the expected value."""
        assert state.value == value


class TestAutomationStatus:
    """Tests for the AutomationStatus dataclass."""

    def test_defaults(self) -> None:
        """Test a new status is idle with no actions or error."""
        status = AutomationStatus(automation_id="test")
        assert status.automation_id == "test"
        assert status.run_state == AutomationRunState.IDLE
        assert status.running_actions == {}
        assert status.last_error is None
        assert status.is_running is False

    def test_is_running_with_actions(self) -> None:
        """Test is_running reflects running actions."""
        status = AutomationStatus(automation_id="test", running_actions={"id1": "action"})
        assert status.is_running is True

    def test_running_actions_not_shared(self) -> None:
        """Test each status gets its own running_actions dictionary."""
        first = AutomationStatus(automation_id="a")
        second = AutomationStatus(automation_id="b")
        first.running_actions["id1"] = "action"
        assert second.running_actions == {}


class TestAutomationStatusManager:
    """Tests for AutomationStatusManager."""

    def test_get_status_creates_and_caches(self, manager: AutomationStatusManager) -> None:
        """Test get_status creates a status once and returns the same object after."""
        status = manager.get_status("automation")
        assert status.automation_id == "automation"
        assert manager.get_status("automation") is status

    @pytest.mark.parametrize(
        ("is_startup", "is_shutdown", "expected"),
        [
            (False, False, AutomationRunState.RUNNING),
            (True, False, AutomationRunState.STARTUP),
            (False, True, AutomationRunState.SHUTDOWN),
            (True, True, AutomationRunState.STARTUP),
        ],
    )
    def test_add_running_action_sets_state(
        self,
        manager: AutomationStatusManager,
        is_startup: bool,
        is_shutdown: bool,
        expected: AutomationRunState,
    ) -> None:
        """Test add_running_action records the action and sets the run state."""
        manager.add_running_action(
            "automation", "action", "id1", is_startup=is_startup, is_shutdown=is_shutdown
        )
        status = manager.get_status("automation")
        assert status.running_actions == {"id1": "action"}
        assert status.run_state == expected
        assert status.is_running is True

    def test_remove_last_action_sets_idle(self, manager: AutomationStatusManager) -> None:
        """Test removing the only running action returns the automation to idle."""
        manager.add_running_action("automation", "action", "id1")
        manager.remove_running_action("automation", "id1")
        status = manager.get_status("automation")
        assert status.running_actions == {}
        assert status.run_state == AutomationRunState.IDLE
        assert status.last_error is None

    def test_remove_one_of_two_stays_running(self, manager: AutomationStatusManager) -> None:
        """Test the automation stays running while another action is active."""
        manager.add_running_action("automation", "first", "id1")
        manager.add_running_action("automation", "second", "id2")
        manager.remove_running_action("automation", "id1")
        status = manager.get_status("automation")
        assert status.running_actions == {"id2": "second"}
        assert status.run_state == AutomationRunState.RUNNING

    def test_remove_with_error_records_error(self, manager: AutomationStatusManager) -> None:
        """Test an error passed on removal is stored."""
        manager.add_running_action("automation", "action", "id1")
        manager.remove_running_action("automation", "id1", error="boom")
        assert manager.get_status("automation").last_error == "boom"

    def test_remove_unknown_execution_is_ignored(self, manager: AutomationStatusManager) -> None:
        """Test removing an execution that is not running does nothing."""
        manager.add_running_action("automation", "action", "id1")
        manager.remove_running_action("automation", "other")
        assert manager.get_status("automation").running_actions == {"id1": "action"}

    @pytest.mark.parametrize(("error", "expected"), [(None, None), ("failed", "failed")])
    def test_set_idle(
        self, manager: AutomationStatusManager, error: str | None, expected: str | None
    ) -> None:
        """Test set_idle clears running actions and optionally records an error."""
        manager.add_running_action("automation", "action", "id1")
        manager.set_idle("automation", error=error)
        status = manager.get_status("automation")
        assert status.run_state == AutomationRunState.IDLE
        assert status.running_actions == {}
        assert status.last_error == expected

    def test_set_idle_without_error_keeps_previous_error(self, manager: AutomationStatusManager) -> None:
        """Test set_idle without an error leaves an earlier error in place."""
        manager.set_idle("automation", error="earlier")
        manager.set_idle("automation")
        assert manager.get_status("automation").last_error == "earlier"

    def test_clear_error(self, manager: AutomationStatusManager) -> None:
        """Test clear_error removes the stored error."""
        manager.set_idle("automation", error="failed")
        manager.clear_error("automation")
        assert manager.get_status("automation").last_error is None

    def test_set_status_message(self, manager: AutomationStatusManager) -> None:
        """Test set_status_message stores the message (currently in last_error)."""
        manager.set_status_message("automation", "working")
        assert manager.get_status("automation").last_error == "working"

    def test_get_all_statuses_returns_copy(self, manager: AutomationStatusManager) -> None:
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
