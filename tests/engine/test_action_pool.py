"""Tests for the HAAnim action pool module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.haanim.engine.action_pool import (
    ActionExecution,
    ActionState,
    ActionWorkerPool,
)
from custom_components.haanim.engine.errors import (
    ActionCancelledError,
    PoolExhaustedError,
)


class TestActionState:
    """Tests for ActionState enum."""

    def test_values(self) -> None:
        """Test all enum values exist."""
        assert ActionState.PENDING.value == "pending"
        assert ActionState.RUNNING.value == "running"
        assert ActionState.COMPLETED.value == "completed"
        assert ActionState.CANCELLED.value == "cancelled"
        assert ActionState.FAILED.value == "failed"


class TestActionExecution:
    """Tests for ActionExecution dataclass."""

    def test_defaults(self) -> None:
        """Test default values."""

        async def dummy() -> None:
            pass

        execution = ActionExecution(
            automation_id="test_automation",
            action_name="test_action",
            func=dummy,
        )
        assert execution.automation_id == "test_automation"
        assert execution.action_name == "test_action"
        assert execution.state == ActionState.PENDING
        assert execution.task is None
        assert execution.started_at is None
        assert execution.completed_at is None
        assert execution.result is None
        assert execution.error is None
        assert execution.is_lifecycle is False


# class TestQueuedAction - REMOVED (queue functionality removed)


class TestActionWorkerPool:
    """Tests for ActionWorkerPool."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        pool = ActionWorkerPool()
        assert pool.max_workers == 20
        assert pool.active_count == 0
        assert pool.available_workers == 20
        assert pool.is_shutting_down is False

    def test_init_custom_workers(self) -> None:
        """Test initialization with custom worker count."""
        pool = ActionWorkerPool(max_workers=5)
        assert pool.max_workers == 5
        assert pool.available_workers == 5

    def test_is_automation_busy_not_busy(self) -> None:
        """Test is_automation_busy when automation is not busy."""
        pool = ActionWorkerPool()
        assert pool.is_automation_shutting_down("some_automation") is False

    def test_get_active_action_none(self) -> None:
        """Test get_active_action when no action is active."""
        pool = ActionWorkerPool()
        assert pool.get_all_active_actions() == []

    @pytest.mark.asyncio
    async def test_submit_action_simple(self) -> None:
        """Test submitting a simple action."""
        pool = ActionWorkerPool()
        result_value = "test_result"

        async def test_action() -> str:
            return result_value

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            result = await pool.submit_action("automation", "action", test_action)

        assert result == result_value
        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_submit_action_sync_function(self) -> None:
        """Test submitting a sync function (gets wrapped as async)."""
        pool = ActionWorkerPool()

        def sync_action() -> str:
            return "sync_result"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            result = await pool.submit_action("automation", "action", sync_action)

        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_submit_action_different_automations(self) -> None:
        """Test that different automations can run concurrently."""
        pool = ActionWorkerPool()
        automation1_started = asyncio.Event()
        finish = asyncio.Event()

        async def action1() -> str:
            automation1_started.set()
            await finish.wait()
            return "automation1"

        async def action2() -> str:
            return "automation2"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            # Start automation1's action
            task1 = asyncio.create_task(pool.submit_action("automation1", "action", action1))
            await automation1_started.wait()

            # Automation2 should be able to run
            result2 = await pool.submit_action("automation2", "action", action2)
            assert result2 == "automation2"

            # Cleanup
            finish.set()
            result1 = await task1
            assert result1 == "automation1"

    @pytest.mark.asyncio
    async def test_submit_action_cancelled_pool_shutting_down(self) -> None:
        """Test that actions are cancelled when pool is shutting down."""
        pool = ActionWorkerPool()
        pool._shutting_down = True

        async def test_action() -> None:
            pass

        with pytest.raises(ActionCancelledError) as exc_info:
            await pool.submit_action("automation", "action", test_action)

        assert "pool is shutting down" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_submit_action_cancelled_automation_shutting_down(self) -> None:
        """Test that actions are cancelled when automation is shutting down."""
        pool = ActionWorkerPool()
        pool._automations_shutting_down.add("automation")

        async def test_action() -> None:
            pass

        with pytest.raises(ActionCancelledError) as exc_info:
            await pool.submit_action("automation", "action", test_action)

        assert "automation is shutting down" in exc_info.value.reason

    @pytest.mark.asyncio
    async def test_pool_exhausted_error(self) -> None:
        """Test PoolExhaustedError when all workers are busy."""
        pool = ActionWorkerPool(max_workers=1)
        started = asyncio.Event()
        finish = asyncio.Event()

        async def blocking_action() -> None:
            started.set()
            await finish.wait()

        async def another_action() -> None:
            pass

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            # Start first action (uses the only worker)
            task = asyncio.create_task(pool.submit_action("automation1", "blocking", blocking_action))
            await started.wait()

            # Wait a bit for the semaphore to be acquired
            await asyncio.sleep(0.01)

            # Try to submit another action from different automation - should fail
            with pytest.raises(PoolExhaustedError) as exc_info:
                await pool.submit_action("automation2", "another", another_action)

            assert exc_info.value.max_workers == 1

            # Cleanup
            finish.set()
            await task

    @pytest.mark.asyncio
    async def test_submit_action_with_args_kwargs(self) -> None:
        """Test submitting action with arguments."""
        pool = ActionWorkerPool()

        async def action_with_args(x: int, y: int, multiplier: int = 1) -> int:
            return (x + y) * multiplier

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            result = await pool.submit_action(
                "automation",
                "action",
                action_with_args,
                5,
                3,
                multiplier=2,
            )

        assert result == 16

    @pytest.mark.asyncio
    async def test_submit_lifecycle_action_during_shutdown(self) -> None:
        """Test that lifecycle actions can run during shutdown."""
        pool = ActionWorkerPool()
        pool._shutting_down = True

        async def shutdown_handler() -> str:
            return "shutdown_complete"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            # Lifecycle actions should still be allowed
            result = await pool.submit_action(
                "automation",
                "__shutdown__",
                shutdown_handler,
                is_lifecycle=True,
            )

        assert result == "shutdown_complete"


class TestActionWorkerPoolAdvanced:
    """Advanced tests for ActionWorkerPool methods."""

    @pytest.mark.asyncio
    async def test_run_startup_action(self) -> None:
        """Test run_startup_action executes startup handler."""
        pool = ActionWorkerPool()

        async def startup_handler() -> str:
            return "started"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            result = await pool.run_startup_action("automation", startup_handler)

        assert result == "started"

    @pytest.mark.asyncio
    async def test_run_shutdown_action_success(self) -> None:
        """Test run_shutdown_action executes successfully."""
        pool = ActionWorkerPool(shutdown_timeout=5.0)

        async def shutdown_handler() -> str:
            return "shutdown_complete"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            result = await pool.run_shutdown_action("automation", shutdown_handler)

        assert result == "shutdown_complete"
        assert "automation" not in pool._automations_shutting_down

    @pytest.mark.asyncio
    async def test_run_shutdown_action_cancels_running(self) -> None:
        """Test run_shutdown_action cancels any running action first."""
        pool = ActionWorkerPool(shutdown_timeout=5.0)
        running_started = asyncio.Event()
        running_finish = asyncio.Event()

        async def running_action() -> None:
            running_started.set()
            await running_finish.wait()

        async def shutdown_handler() -> str:
            return "shutdown_done"

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            # Start a running action
            running_task = asyncio.create_task(pool.submit_action("automation", "running", running_action))
            await running_started.wait()

            # Run shutdown - should cancel the running action
            result = await pool.run_shutdown_action("automation", shutdown_handler)
            assert result == "shutdown_done"

            # The running task should have been cancelled
            with pytest.raises(ActionCancelledError):
                await running_task

    @pytest.mark.asyncio
    async def test_shutdown_pool(self) -> None:
        """Test pool shutdown cancels all actions."""
        pool = ActionWorkerPool()
        started = asyncio.Event()
        finish = asyncio.Event()

        async def slow_action() -> None:
            started.set()
            await finish.wait()

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            task = asyncio.create_task(pool.submit_action("automation", "slow", slow_action))
            await started.wait()

            # Shutdown the pool
            await pool.shutdown()

            assert pool.is_shutting_down is True

            # Allow task to finish
            finish.set()
            try:
                await task
            except ActionCancelledError:
                pass

    def test_reset_pool(self) -> None:
        """Test pool reset clears state."""
        pool = ActionWorkerPool()
        pool._shutting_down = True
        pool._automations_shutting_down.add("automation1")

        pool.reset()

        assert pool._shutting_down is False
        assert len(pool._automations_shutting_down) == 0

    @pytest.mark.asyncio
    async def test_action_with_exception(self) -> None:
        """Test action that raises an exception."""
        pool = ActionWorkerPool()

        async def failing_action() -> None:
            raise ValueError("test error")

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            with pytest.raises(ValueError, match="test error"):
                await pool.submit_action("automation", "failing", failing_action)

        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_get_all_active_actions_returns_list(self) -> None:
        """Test get_all_active_actions returns all running executions."""
        pool = ActionWorkerPool()
        started1 = asyncio.Event()
        started2 = asyncio.Event()
        finish = asyncio.Event()

        async def action1() -> None:
            started1.set()
            await finish.wait()

        async def action2() -> None:
            started2.set()
            await finish.wait()

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            task1 = asyncio.create_task(pool.submit_action("automation1", "action1", action1))
            task2 = asyncio.create_task(pool.submit_action("automation2", "action2", action2))
            await started1.wait()
            await started2.wait()

            actions = pool.get_all_active_actions()
            assert len(actions) == 2
            action_names = {a.action_name for a in actions}
            assert action_names == {"action1", "action2"}

            finish.set()
            await task1
            await task2


# class TestActionWorkerPoolQueue - REMOVED (queue functionality removed)


class TestActionWorkerPoolLifecycle:
    """Tests for ActionWorkerPool lifecycle actions."""

    @pytest.mark.asyncio
    async def test_run_startup_action(self) -> None:
        """Test run_startup_action executes startup function."""
        pool = ActionWorkerPool()
        executed = False

        async def startup_func() -> None:
            nonlocal executed
            executed = True

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            await pool.run_startup_action("test_automation", startup_func)

        assert executed is True

    @pytest.mark.asyncio
    async def test_run_shutdown_action(self) -> None:
        """Test run_shutdown_action executes shutdown function."""
        pool = ActionWorkerPool()
        executed = False

        async def shutdown_func() -> None:
            nonlocal executed
            executed = True

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            await pool.run_shutdown_action("test_automation", shutdown_func)

        assert executed is True

    @pytest.mark.asyncio
    async def test_shutdown_pool(self) -> None:
        """Test shutdown method cancels running actions."""
        pool = ActionWorkerPool()
        started = asyncio.Event()

        async def long_action() -> None:
            started.set()
            await asyncio.sleep(100)

        with patch("custom_components.haanim.engine.action_pool.get_status_manager"):
            task = asyncio.create_task(pool.submit_action("automation", "action", long_action))
            await started.wait()

            # Shutdown should cancel running actions
            await pool.shutdown()

            # Task should be cancelled
            with pytest.raises((asyncio.CancelledError, ActionCancelledError)):
                await task

    @pytest.mark.asyncio
    async def test_available_workers(self) -> None:
        """Test available_workers property."""
        pool = ActionWorkerPool(max_workers=3)
        assert pool.available_workers == 3

    @pytest.mark.asyncio
    async def test_is_automation_shutting_down(self) -> None:
        """Test is_automation_shutting_down returns False when not shutting down."""
        pool = ActionWorkerPool()
        assert pool.is_automation_shutting_down("test_automation") is False
