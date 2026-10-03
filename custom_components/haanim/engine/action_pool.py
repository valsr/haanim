"""Action worker pool for managing concurrent action execution.

This module provides a pool-based execution model for running automation actions
concurrently while respecting per-automation and global concurrency limits.
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

from custom_components.haanim.config import get_config_manager
from custom_components.haanim.engine.errors import (
    ActionCancelledError,
    PoolExhaustedError,
    ShutdownTimeoutError,
)
from custom_components.haanim.engine.automation_status import get_status_manager

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

    Manages a pool of workers that can execute actions concurrently. Enforces:
    - Global maximum concurrent actions limit
    - Automation shutdown handling with timeout
    """

    def __init__(
        self,
        max_workers: int | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        """Initialize the action worker pool.

        Args:
            max_workers: Maximum number of concurrent actions allowed.
            shutdown_timeout: Timeout for shutdown actions in seconds.
        """
        self._max_workers = max_workers or get_config_manager().get_max_concurrent_actions()
        self._shutdown_timeout = shutdown_timeout or get_config_manager().get_worker_shutdown_timeout()

        # Track active executions by execution_id
        self._active_executions: dict[str, ActionExecution] = {}

        # Semaphore to limit concurrent actions
        self._semaphore = asyncio.Semaphore(self._max_workers)

        # Lock for modifying active executions
        self._lock = asyncio.Lock()

        # Flag indicating pool is shutting down
        self._shutting_down = False

        # Automations that are in shutdown mode (no new actions allowed)
        self._automations_shutting_down: set[str] = set()

        _LOGGER.debug(
            "ActionWorkerPool initialized with max_workers=%d, shutdown_timeout=%.3fs",
            max_workers,
            shutdown_timeout,
        )

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

    @property
    def is_shutting_down(self) -> bool:
        """Check if the pool is shutting down."""
        return self._shutting_down

    def is_automation_shutting_down(self, automation_id: str) -> bool:
        """Check if an automation is in shutdown mode.

        Args:
            automation_id: Name of the automation to check.

        Returns:
            True if the automation is shutting down.
        """
        return automation_id in self._automations_shutting_down

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
            ActionCancelledError: If the action was cancelled.
        """
        async with self._lock:
            # Check if pool is shutting down (for non-shutdown actions)
            if self._shutting_down and not is_lifecycle:
                raise ActionCancelledError(action_name, "pool is shutting down")

            # Check if automation is in shutdown mode
            if automation_id in self._automations_shutting_down and not is_lifecycle:
                raise ActionCancelledError(action_name, "automation is shutting down")

            # Check if pool has available workers (non-blocking check)
            if self._semaphore.locked() and self.available_workers <= 0:
                _LOGGER.error(
                    "Action worker pool exhausted (max=%d), cannot run action '%s' for " "automation '%s'",
                    self._max_workers,
                    action_name,
                    automation_id,
                )
                raise PoolExhaustedError(self._max_workers)

            # Wrap sync functions as async
            async_func = self._wrap_sync_func(func)

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

    def _wrap_sync_func(self, func: Callable[..., Any]) -> Callable[..., Coroutine[Any, Any, Any]]:
        """Wrap a sync function as async.

        Args:
            func: The function to wrap.

        Returns:
            An async wrapper function.
        """
        if asyncio.iscoroutinefunction(func):
            return func

        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: func(*args, **kwargs))

        return wrapper

    async def _execute_action(self, execution: ActionExecution) -> Any:
        """Execute an action with semaphore limiting.

        Args:
            execution: The action execution to run.

        Returns:
            The result of the action.

        Raises:
            ActionCancelledError: If the action was cancelled.
            Exception: Any exception from the action itself.
        """
        status_manager = get_status_manager()

        async with self._semaphore:
            execution.state = ActionState.RUNNING
            execution.started_at = datetime.now()

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
                execution.completed_at = datetime.now()

                _LOGGER.debug(
                    "Completed action '%s' for automation '%s'",
                    execution.action_name,
                    execution.automation_id,
                )

                # Update status - remove this action
                status_manager.remove_running_action(execution.automation_id, execution.execution_id)

                return result

            except asyncio.CancelledError as exc:
                execution.state = ActionState.CANCELLED
                execution.completed_at = datetime.now()
                _LOGGER.warning(
                    "Action '%s' for automation '%s' was cancelled",
                    execution.action_name,
                    execution.automation_id,
                )
                # Update status - remove this action
                status_manager.remove_running_action(execution.automation_id, execution.execution_id)
                raise ActionCancelledError(execution.action_name) from exc

            except Exception as err:
                execution.state = ActionState.FAILED
                execution.error = err
                execution.completed_at = datetime.now()
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

    async def cancel_automation_actions(self, automation_id: str, reason: str = "cancelled") -> int:
        """Cancel all running actions for an automation.

        Args:
            automation_id: Name of the automation whose actions should be cancelled.
            reason: Reason for cancellation.

        Returns:
            Number of actions cancelled.
        """
        async with self._lock:
            executions = [
                exec_info
                for exec_info in self._active_executions.values()
                if exec_info.automation_id == automation_id and exec_info.task
            ]

        if not executions:
            return 0

        _LOGGER.info(
            "Cancelling %d action(s) for automation '%s': %s",
            len(executions),
            automation_id,
            reason,
        )

        for execution in executions:
            if execution.task:
                execution.task.cancel()

        return len(executions)

    async def run_shutdown_action(
        self,
        automation_id: str,
        shutdown_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a shutdown action with timeout and proper handling.

        This method:
        1. Marks the automation as shutting down (prevents new actions)
        2. Cancels any currently running actions for the automation
        3. Runs the shutdown function with a timeout
        4. Cleans up automation state

        Args:
            automation_id: Name of the automation shutting down.
            shutdown_func: The shutdown function to execute.
            *args: Positional arguments for the shutdown function.
            **kwargs: Keyword arguments for the shutdown function.

        Returns:
            The result of the shutdown function, or None if timed out.

        Raises:
            ShutdownTimeoutError: If the shutdown action exceeds the timeout.
        """
        # Mark automation as shutting down
        self._automations_shutting_down.add(automation_id)

        try:
            # Cancel any currently running actions
            await self.cancel_automation_actions(automation_id, "automation shutdown")

            # Wait briefly for cancelled actions to clean up
            await asyncio.sleep(0.05)

            # Execute shutdown with timeout
            _LOGGER.debug("Running shutdown action for automation '%s'", automation_id)
            try:
                return await asyncio.wait_for(
                    self.submit_action(
                        automation_id,
                        "__shutdown__",
                        shutdown_func,
                        *args,
                        is_lifecycle=True,
                        **kwargs,
                    ),
                    timeout=self._shutdown_timeout,
                )
            except asyncio.TimeoutError as exc:
                _LOGGER.error(
                    "Shutdown action for automation '%s' timed out after %.0fs",
                    automation_id,
                    self._shutdown_timeout,
                )
                raise ShutdownTimeoutError(automation_id, self._shutdown_timeout) from exc
            except ActionCancelledError as exc:
                # This can happen if the action was cancelled due to timeout
                _LOGGER.error(
                    "Shutdown action for automation '%s' exceeded timeout of %.0fms",
                    automation_id,
                    self._shutdown_timeout * 1000,
                )
                raise ShutdownTimeoutError(automation_id, self._shutdown_timeout) from exc

        finally:
            # Clean up shutdown state
            self._automations_shutting_down.discard(automation_id)

    async def run_startup_action(
        self,
        automation_id: str,
        startup_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a startup action for an automation.

        Args:
            automation_id: Name of the automation starting up.
            startup_func: The startup function to execute.
            *args: Positional arguments for the startup function.
            **kwargs: Keyword arguments for the startup function.

        Returns:
            The result of the startup function.

        Raises:
            PoolExhaustedError: If no workers are available.
        """
        _LOGGER.debug("Running startup action for automation '%s'", automation_id)
        return await self.submit_action(
            automation_id,
            "__startup__",
            startup_func,
            *args,
            is_lifecycle=True,
            **kwargs,
        )

    async def shutdown(self) -> None:
        """Shutdown the worker pool.

        This will:
        1. Set the shutting down flag
        2. Cancel all running actions
        3. Wait for all actions to complete or be cancelled
        """
        _LOGGER.info("Shutting down action worker pool")
        self._shutting_down = True

        # Cancel all running actions
        async with self._lock:
            execution_ids = list(self._active_executions.keys())

        for execution_id in execution_ids:
            execution = self._active_executions.get(execution_id)
            if execution and execution.task:
                execution.task.cancel()

        # Wait for all actions to complete
        max_wait = 1.0  # Maximum 1 second wait
        waited = 0.0
        while self.active_count > 0 and waited < max_wait:
            await asyncio.sleep(0.01)
            waited += 0.01

        if self.active_count > 0:
            _LOGGER.warning(
                "Pool shutdown complete with %d actions still active",
                self.active_count,
            )
        else:
            _LOGGER.info("Action worker pool shutdown complete")

    def reset(self) -> None:
        """Reset the pool state.

        This clears all tracking data and resets the shutdown flag.
        Should only be used for testing or reinitialization.
        """
        self._active_executions.clear()
        self._automations_shutting_down.clear()
        self._shutting_down = False
        self._semaphore = asyncio.Semaphore(self._max_workers)
        _LOGGER.debug("Action worker pool reset")
