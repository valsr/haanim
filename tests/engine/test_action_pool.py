"""Tests for the HAAnim action pool module."""

from __future__ import annotations

import asyncio

import pytest

from haanim.engine.action_pool import (
    ActionExecution,
    ActionState,
    ActionWorkerPool,
)
from haanim.engine.automation_status import AutomationStatusManager
from haanim.testing import FakeClock
from haanim.engine.errors import PoolExhaustedError


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
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        assert pool.max_workers == 20
        assert pool.active_count == 0
        assert pool.available_workers == 20

    def test_init_custom_workers(self) -> None:
        """Test initialization with custom worker count."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock(), max_workers=5)
        assert pool.max_workers == 5
        assert pool.available_workers == 5

    def test_get_active_action_none(self) -> None:
        """Test get_active_action when no action is active."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        assert pool.get_all_active_actions() == []

    @pytest.mark.asyncio
    async def test_submit_action_simple(self) -> None:
        """Test submitting a simple action."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        result_value = "test_result"

        async def test_action() -> str:
            return result_value

        result = await pool.submit_action("automation", "action", test_action)

        assert result == result_value
        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_submit_action_sync_function(self) -> None:
        """Test submitting a sync function (gets wrapped as async)."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())

        def sync_action() -> str:
            return "sync_result"

        result = await pool.submit_action("automation", "action", sync_action)

        assert result == "sync_result"

    @pytest.mark.asyncio
    async def test_submit_action_different_automations(self) -> None:
        """Test that different automations can run concurrently."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        automation1_started = asyncio.Event()
        finish = asyncio.Event()

        async def action1() -> str:
            automation1_started.set()
            await finish.wait()
            return "automation1"

        async def action2() -> str:
            return "automation2"

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
    async def test_pool_exhausted_error(self) -> None:
        """Test PoolExhaustedError when all workers are busy."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock(), max_workers=1)
        started = asyncio.Event()
        finish = asyncio.Event()

        async def blocking_action() -> None:
            started.set()
            await finish.wait()

        async def another_action() -> None:
            pass

        # Start first action (uses the only worker)
        task = asyncio.create_task(pool.submit_action("automation1", "blocking", blocking_action))
        await started.wait()

        # Wait a bit for the semaphore to be acquired
        await asyncio.sleep(0)

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
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())

        async def action_with_args(x: int, y: int, multiplier: int = 1) -> int:
            return (x + y) * multiplier

        result = await pool.submit_action(
            "automation",
            "action",
            action_with_args,
            5,
            3,
            multiplier=2,
        )

        assert result == 16


class TestActionWorkerPoolAdvanced:
    """Advanced tests for ActionWorkerPool methods."""

    @pytest.mark.asyncio
    async def test_action_with_exception(self) -> None:
        """Test action that raises an exception."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())

        async def failing_action() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            await pool.submit_action("automation", "failing", failing_action)

        assert pool.active_count == 0

    @pytest.mark.asyncio
    async def test_get_all_active_actions_returns_list(self) -> None:
        """Test get_all_active_actions returns all running executions."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        started1 = asyncio.Event()
        started2 = asyncio.Event()
        finish = asyncio.Event()

        async def action1() -> None:
            started1.set()
            await finish.wait()

        async def action2() -> None:
            started2.set()
            await finish.wait()

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
    async def test_available_workers(self) -> None:
        """Test available_workers property."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock(), max_workers=3)
        assert pool.available_workers == 3
