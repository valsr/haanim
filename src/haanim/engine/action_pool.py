"""Action worker pool: executes the requests the dispatcher lets through.

The pool enforces the global limit on concurrently executing actions and records
each execution. Execution modes, queues and cancellation belong to the
dispatcher (``action_dispatcher.py``), which is the only caller of the pool.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from haanim.const import DEFAULT_MAX_CONCURRENT_ACTIONS
from haanim.engine.callables import as_coroutine_function
from haanim.engine.errors import PoolExhaustedError
from haanim.engine.automation_status import AutomationStatusManager
from haanim.interfaces import Clock

_LOGGER = logging.getLogger(__name__)


class ActionState(Enum):
    """State of an action execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ActionExecution:
    """Represents a single action execution.

    Args:
        automation_id: Name of the automation executing the action.
        action_name: Name of the action being executed.
        func: The async callable to execute.
        args: Positional arguments for the function.
        kwargs: Keyword arguments for the function.
        state: Current state of the execution.
        task: The asyncio task running this action.
        started_at: When the action started executing.
        completed_at: When the action completed.
        result: The result of the action execution.
        error: Any error that occurred during execution.
        is_lifecycle: Whether this is a lifecycle action (startup/shutdown).
    """

    automation_id: str
    action_name: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    state: ActionState = ActionState.PENDING
    task: asyncio.Task[Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: BaseException | None = None
    is_lifecycle: bool = False
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)


class ActionWorkerPool:
    """Pool for managing concurrent action execution across automations.

    Executes actions on the event loop, enforces the global maximum of
    concurrent actions and records what is executing.
    """

    def __init__(
        self,
        status_manager: AutomationStatusManager,
        clock: Clock,
        max_workers: int = DEFAULT_MAX_CONCURRENT_ACTIONS,
    ) -> None:
        """Initialize the action worker pool.

        Args:
            status_manager: Where the running actions of each automation are recorded.
            clock: Source of timestamps, delays and timeouts.
            max_workers: Maximum number of concurrent actions allowed.
        """
        self._status_manager = status_manager
        self._clock = clock
        self._max_workers = max_workers

        # Track active executions by execution_id
        self._active_executions: dict[str, ActionExecution] = {}

        # Semaphore to limit concurrent actions
        self._semaphore = asyncio.Semaphore(self._max_workers)

        # Lock for modifying active executions
        self._lock = asyncio.Lock()

        _LOGGER.debug("ActionWorkerPool initialized with max_workers=%d", max_workers)

    @property
    def max_workers(self) -> int:
        """Get the maximum number of concurrent workers."""
        return self._max_workers

    @property
    def active_count(self) -> int:
        """Get the number of currently active actions."""
        return len(self._active_executions)

    @property
    def available_workers(self) -> int:
        """Get the number of available worker slots."""
        return self._max_workers - len(self._active_executions)

    def get_active_actions(self, automation_id: str) -> list[ActionExecution]:
        """Get all currently active actions for an automation.

        Args:
            automation_id: Name of the automation.

        Returns:
            List of active ActionExecution instances for the automation.
        """
        return [
            exec_info
            for exec_info in self._active_executions.values()
            if exec_info.automation_id == automation_id
        ]

    def get_all_active_actions(self) -> list[ActionExecution]:
        """Get all currently active action executions.

        Returns:
            List of all active ActionExecution instances.
        """
        return list(self._active_executions.values())

    async def submit_action(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        is_lifecycle: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Submit an action for execution.

        Args:
            automation_id: Name of the automation requesting the action.
            action_name: Name of the action to execute.
            func: The function to execute (sync or async).
            *args: Positional arguments for the function.
            is_lifecycle: Whether this is a lifecycle action (startup/shutdown).
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the action execution.

        Raises:
            PoolExhaustedError: If no workers are available.
            asyncio.CancelledError: If the execution was cancelled.
        """
        async with self._lock:
            # Check if pool has available workers (non-blocking check)
            if self._semaphore.locked() and self.available_workers <= 0:
                _LOGGER.error(
                    "Action worker pool exhausted (max=%d), cannot run action '%s' for " "automation '%s'",
                    self._max_workers,
                    action_name,
                    automation_id,
                )
                raise PoolExhaustedError(self._max_workers)

            # Everything runs on the event loop, whether written def or async def
            async_func = as_coroutine_function(func)

            # Create execution record
            execution = ActionExecution(
                automation_id=automation_id,
                action_name=action_name,
                func=async_func,
                args=args,
                kwargs=kwargs,
                is_lifecycle=is_lifecycle,
            )

            # Register the execution
            self._active_executions[execution.execution_id] = execution

        # Execute outside the lock
        try:
            return await self._execute_action(execution)
        finally:
            async with self._lock:
                # Clean up after execution
                if execution.execution_id in self._active_executions:
                    del self._active_executions[execution.execution_id]

    @property
    def clock(self) -> Clock:
        """The clock this pool takes its time from."""
        return self._clock

    async def _execute_action(self, execution: ActionExecution) -> Any:
        """Execute an action with semaphore limiting.

        Args:
            execution: The action execution to run.

        Returns:
            The result of the action.

        Raises:
            asyncio.CancelledError: If the execution was cancelled.
            Exception: Any exception from the action itself.
        """
        status_manager = self._status_manager

        async with self._semaphore:
            execution.state = ActionState.RUNNING
            execution.started_at = self._clock.now()

            # Update automation status to running
            status_manager.add_running_action(
                automation_id=execution.automation_id,
                action_name=execution.action_name,
                execution_id=execution.execution_id,
                is_startup=execution.action_name == "__startup__",
                is_shutdown=execution.action_name == "__shutdown__",
            )

            _LOGGER.debug(
                "Starting action '%s' for automation '%s' (active: %d/%d)",
                execution.action_name,
                execution.automation_id,
                self.active_count,
                self._max_workers,
            )

            try:
                # Create task for the action
                execution.task = asyncio.current_task()

                # Execute the action
                result = await execution.func(*execution.args, **execution.kwargs)

                execution.state = ActionState.COMPLETED
                execution.result = result
                execution.completed_at = self._clock.now()

                _LOGGER.debug(
                    "Completed action '%s' for automation '%s'",
                    execution.action_name,
                    execution.automation_id,
                )

                # Update status - remove this action
                status_manager.remove_running_action(execution.automation_id, execution.execution_id)

                return result

            except asyncio.CancelledError:
                execution.state = ActionState.CANCELLED
                execution.completed_at = self._clock.now()
                _LOGGER.warning(
                    "Action '%s' for automation '%s' was cancelled",
                    execution.action_name,
                    execution.automation_id,
                )
                # Update status - remove this action
                status_manager.remove_running_action(execution.automation_id, execution.execution_id)
                raise

            except Exception as err:
                execution.state = ActionState.FAILED
                execution.error = err
                execution.completed_at = self._clock.now()
                _LOGGER.error(
                    "Action '%s' for automation '%s' failed: %s",
                    execution.action_name,
                    execution.automation_id,
                    err,
                )
                # Update status - remove this action with error
                status_manager.remove_running_action(
                    execution.automation_id, execution.execution_id, error=str(err)
                )
                raise
