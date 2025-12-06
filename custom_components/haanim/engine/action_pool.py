"""Action worker pool for managing concurrent action execution.

This module provides a pool-based execution model for running script actions
concurrently while respecting per-script and global concurrency limits.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from custom_components.haanim.const import DEFAULT_MAX_CONCURRENT_ACTIONS, DEFAULT_SHUTDOWN_TIMEOUT
from custom_components.haanim.engine.errors import (
    ActionBusyError,
    ActionCancelledError,
    ActionQueueTimeoutError,
    PoolExhaustedError,
    ShutdownTimeoutError,
)
from custom_components.haanim.engine.script_status import get_status_manager

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
        script_name: Name of the script executing the action.
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

    script_name: str
    action_name: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    state: ActionState = ActionState.PENDING
    task: asyncio.Task[Any] | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: Any = None
    error: Exception | None = None
    is_lifecycle: bool = False


@dataclass
class QueuedAction:
    """Represents an action waiting in the queue.

    Args:
        script_name: Name of the script.
        action_name: Name of the action.
        func: The async callable to execute.
        args: Positional arguments for the function.
        kwargs: Keyword arguments for the function.
        queued_at: When the action was queued.
        timeout: Queue timeout in seconds (0 = wait indefinitely).
        future: Future to set the result or exception when done.
    """

    script_name: str
    action_name: str
    func: Callable[..., Coroutine[Any, Any, Any]]
    args: tuple[Any, ...] = field(default_factory=tuple)
    kwargs: dict[str, Any] = field(default_factory=dict[str, Any])
    queued_at: datetime = field(default_factory=datetime.now)
    timeout: float = 10.0
    future: asyncio.Future[Any] | None = None

    def is_expired(self) -> bool:
        """Check if this queued action has exceeded its timeout.

        Returns:
            True if the action has timed out (and timeout > 0).
        """
        if self.timeout <= 0:
            return False  # 0 means wait indefinitely
        elapsed = (datetime.now() - self.queued_at).total_seconds()
        return elapsed > self.timeout

    def get_wait_time(self) -> float:
        """Get the time this action has been waiting.

        Returns:
            Wait time in seconds.
        """
        return (datetime.now() - self.queued_at).total_seconds()


class ActionWorkerPool:
    """Pool for managing concurrent action execution across scripts.

    Manages a pool of workers that can execute actions concurrently. Enforces:
    - Maximum one action per script at a time
    - Global maximum concurrent actions limit
    - Script shutdown handling with timeout
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_CONCURRENT_ACTIONS,
        shutdown_timeout: float = DEFAULT_SHUTDOWN_TIMEOUT,
    ) -> None:
        """Initialize the action worker pool.

        Args:
            max_workers: Maximum number of concurrent actions allowed.
            shutdown_timeout: Timeout for shutdown actions in seconds.
        """
        self._max_workers = max_workers
        self._shutdown_timeout = shutdown_timeout

        # Track active executions by script name
        self._active_executions: dict[str, ActionExecution] = {}

        # Semaphore to limit concurrent actions
        self._semaphore = asyncio.Semaphore(max_workers)

        # Lock for modifying active executions and queues
        self._lock = asyncio.Lock()

        # Flag indicating pool is shutting down
        self._shutting_down = False

        # Scripts that are in shutdown mode (no new actions allowed)
        self._scripts_shutting_down: set[str] = set()

        # Queue of pending actions per script (FIFO order)
        self._action_queues: dict[str, list[QueuedAction]] = {}

        # Events to signal when a script becomes available
        self._script_available_events: dict[str, asyncio.Event] = {}

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

    def is_script_busy(self, script_name: str) -> bool:
        """Check if a script is currently executing an action.

        Args:
            script_name: Name of the script to check.

        Returns:
            True if the script has an active action.
        """
        return script_name in self._active_executions

    def is_script_shutting_down(self, script_name: str) -> bool:
        """Check if a script is in shutdown mode.

        Args:
            script_name: Name of the script to check.

        Returns:
            True if the script is shutting down.
        """
        return script_name in self._scripts_shutting_down

    def get_active_action(self, script_name: str) -> ActionExecution | None:
        """Get the currently active action for a script.

        Args:
            script_name: Name of the script.

        Returns:
            The active ActionExecution, or None if not busy.
        """
        return self._active_executions.get(script_name)

    def get_all_active_actions(self) -> list[ActionExecution]:
        """Get all currently active action executions.

        Returns:
            List of all active ActionExecution instances.
        """
        return list(self._active_executions.values())

    async def submit_action(
        self,
        script_name: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        is_lifecycle: bool = False,
        queue: bool = False,
        queue_timeout: float = 10.0,
        preempt: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Submit an action for execution.

        Args:
            script_name: Name of the script requesting the action.
            action_name: Name of the action to execute.
            func: The function to execute (sync or async).
            *args: Positional arguments for the function.
            is_lifecycle: Whether this is a lifecycle action (startup/shutdown).
            queue: If True, queue the action when the script is busy.
            queue_timeout: Timeout for queued actions (0 = wait indefinitely).
            preempt: If True, cancel any running action and run this one immediately.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the action execution.

        Raises:
            ActionBusyError: If the script is already executing an action and queue=False.
            PoolExhaustedError: If no workers are available.
            ActionCancelledError: If the action was cancelled.
            ActionQueueTimeoutError: If the queued action times out.
        """
        async with self._lock:
            # Check if pool is shutting down (for non-shutdown actions)
            if self._shutting_down and not is_lifecycle:
                raise ActionCancelledError(action_name, "pool is shutting down")

            # Check if script is in shutdown mode
            if script_name in self._scripts_shutting_down and not is_lifecycle:
                raise ActionCancelledError(action_name, "script is shutting down")

            # Check if script is already running an action
            if script_name in self._active_executions:
                current = self._active_executions[script_name]

                if preempt:
                    # Cancel the current action and proceed with this one
                    _LOGGER.info(
                        "Preempting action '%s' for script '%s' with action '%s'",
                        current.action_name,
                        script_name,
                        action_name,
                    )
                    # Release lock temporarily to cancel
                    self._lock.release()
                    try:
                        await self.cancel_action(script_name, f"preempted by {action_name}")
                        # Wait briefly for the cancelled action to clean up
                        await asyncio.sleep(0.01)
                    finally:
                        await self._lock.acquire()
                elif queue:
                    # Queue the action instead of raising an error
                    return await self._queue_action(
                        script_name, action_name, func, args, kwargs, queue_timeout
                    )
                else:
                    _LOGGER.error(
                        "Script '%s' is busy executing action '%s', cannot run '%s'",
                        script_name,
                        current.action_name,
                        action_name,
                    )
                    raise ActionBusyError(script_name, current.action_name)

            # Check if pool has available workers (non-blocking check)
            if self._semaphore.locked() and self.available_workers <= 0:
                _LOGGER.error(
                    "Action worker pool exhausted (max=%d), cannot run action '%s' for script '%s'",
                    self._max_workers,
                    action_name,
                    script_name,
                )
                raise PoolExhaustedError(self._max_workers)

            # Wrap sync functions as async
            async_func = self._wrap_sync_func(func)

            # Create execution record
            execution = ActionExecution(
                script_name=script_name,
                action_name=action_name,
                func=async_func,
                args=args,
                kwargs=kwargs,
                is_lifecycle=is_lifecycle,
            )

            # Register the execution
            self._active_executions[script_name] = execution

        # Execute outside the lock
        try:
            return await self._execute_action(execution)
        finally:
            async with self._lock:
                # Clean up after execution
                if script_name in self._active_executions:
                    del self._active_executions[script_name]

            # Process any queued actions for this script
            await self._process_queue(script_name)

    def _wrap_sync_func(self, func: Callable[..., Any]) -> Callable[..., Coroutine[Any, Any, Any]]:
        """Wrap a sync function as async if needed.

        Args:
            func: The function to wrap.

        Returns:
            An async function.
        """
        if asyncio.iscoroutinefunction(func):
            return func

        original_func = func

        async def async_wrapper(*a: Any, **kw: Any) -> Any:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, lambda: original_func(*a, **kw))

        return async_wrapper

    async def _queue_action(
        self,
        script_name: str,
        action_name: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        timeout: float,
    ) -> Any:
        """Queue an action to run when the script becomes available.

        This method is called with the lock held.

        Args:
            script_name: Name of the script.
            action_name: Name of the action.
            func: The function to execute.
            args: Positional arguments.
            kwargs: Keyword arguments.
            timeout: Queue timeout in seconds.

        Returns:
            The result of the action when it completes.

        Raises:
            ActionQueueTimeoutError: If the action times out in the queue.
            ActionCancelledError: If the action is cancelled.
        """
        # Create a future for the result
        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()

        # Wrap sync functions as async
        async_func = self._wrap_sync_func(func)

        # Create queued action
        queued = QueuedAction(
            script_name=script_name,
            action_name=action_name,
            func=async_func,
            args=args,
            kwargs=kwargs,
            timeout=timeout,
            future=future,
        )

        # Add to queue
        if script_name not in self._action_queues:
            self._action_queues[script_name] = []
        self._action_queues[script_name].append(queued)

        _LOGGER.info(
            "Action '%s' for script '%s' queued (timeout: %s)",
            action_name,
            script_name,
            f"{timeout}s" if timeout > 0 else "indefinite",
        )

        # Release the lock and wait for the result
        # We need to release the lock before waiting
        self._lock.release()
        try:
            if timeout > 0:
                try:
                    return await asyncio.wait_for(future, timeout=timeout)
                except asyncio.TimeoutError as exc:
                    # Remove from queue if still there
                    async with self._lock:
                        if script_name in self._action_queues:
                            self._action_queues[script_name] = [
                                q for q in self._action_queues[script_name] if q.future is not future
                            ]
                    _LOGGER.warning(
                        "Queued action '%s' for script '%s' timed out after %.1fs",
                        action_name,
                        script_name,
                        timeout,
                    )
                    raise ActionQueueTimeoutError(script_name, action_name, timeout) from exc
            else:
                # Wait indefinitely
                return await future
        finally:
            # Re-acquire the lock (the caller expects us to have it)
            await self._lock.acquire()

    async def _process_queue(self, script_name: str) -> None:
        """Process the next queued action for a script.

        Args:
            script_name: Name of the script whose queue to process.
        """
        async with self._lock:
            if script_name not in self._action_queues:
                return

            queue = self._action_queues[script_name]
            if not queue:
                del self._action_queues[script_name]
                return

            # Find the first non-expired action
            while queue:
                queued = queue[0]

                if queued.is_expired():
                    # Remove expired action and set error on its future
                    queue.pop(0)
                    if queued.future and not queued.future.done():
                        queued.future.set_exception(
                            ActionQueueTimeoutError(script_name, queued.action_name, queued.timeout)
                        )
                    _LOGGER.warning(
                        "Queued action '%s' for script '%s' expired after %.1fs",
                        queued.action_name,
                        script_name,
                        queued.get_wait_time(),
                    )
                    continue

                # Found a valid action, remove from queue and execute
                queue.pop(0)
                if not queue:
                    del self._action_queues[script_name]

                # Check if script is shutting down
                if script_name in self._scripts_shutting_down:
                    if queued.future and not queued.future.done():
                        queued.future.set_exception(
                            ActionCancelledError(queued.action_name, "script is shutting down")
                        )
                    return

                # Check if pool is shutting down
                if self._shutting_down:
                    if queued.future and not queued.future.done():
                        queued.future.set_exception(
                            ActionCancelledError(queued.action_name, "pool is shutting down")
                        )
                    return

                _LOGGER.info(
                    "Processing queued action '%s' for script '%s' (waited %.1fs)",
                    queued.action_name,
                    script_name,
                    queued.get_wait_time(),
                )

                # Create execution record
                execution = ActionExecution(
                    script_name=script_name,
                    action_name=queued.action_name,
                    func=queued.func,
                    args=queued.args,
                    kwargs=queued.kwargs,
                )

                # Register the execution
                self._active_executions[script_name] = execution

                # Execute outside the lock
                self._lock.release()
                try:
                    result = await self._execute_action(execution)
                    if queued.future and not queued.future.done():
                        queued.future.set_result(result)
                except BaseException as err:  # pylint: disable=broad-except
                    # Forward any exception to the waiting future
                    if queued.future and not queued.future.done():
                        queued.future.set_exception(err)
                finally:
                    await self._lock.acquire()
                    # Clean up after execution
                    if script_name in self._active_executions:
                        del self._active_executions[script_name]

                # Only process one action at a time
                break

        # Check if there are more queued actions
        if script_name in self._action_queues and self._action_queues[script_name]:
            # Schedule processing of next action
            asyncio.create_task(self._process_queue(script_name))

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

            # Update script status to running
            status_manager.set_running(
                script_name=execution.script_name,
                action_name=execution.action_name,
                is_startup=execution.action_name == "__startup__",
                is_shutdown=execution.action_name == "__shutdown__",
            )

            _LOGGER.debug(
                "Starting action '%s' for script '%s' (active: %d/%d)",
                execution.action_name,
                execution.script_name,
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
                    "Completed action '%s' for script '%s'",
                    execution.action_name,
                    execution.script_name,
                )

                # Update status to idle
                status_manager.set_idle(execution.script_name)

                return result

            except asyncio.CancelledError as exc:
                execution.state = ActionState.CANCELLED
                execution.completed_at = datetime.now()
                _LOGGER.warning(
                    "Action '%s' for script '%s' was cancelled",
                    execution.action_name,
                    execution.script_name,
                )
                # Update status to idle
                status_manager.set_idle(execution.script_name)
                raise ActionCancelledError(execution.action_name) from exc

            except Exception as err:
                execution.state = ActionState.FAILED
                execution.error = err
                execution.completed_at = datetime.now()
                _LOGGER.error(
                    "Action '%s' for script '%s' failed: %s",
                    execution.action_name,
                    execution.script_name,
                    err,
                )
                # Update status to idle with error
                status_manager.set_idle(execution.script_name, error=str(err))
                raise

    async def cancel_action(self, script_name: str, reason: str = "cancelled") -> bool:
        """Cancel a running action for a script.

        Args:
            script_name: Name of the script whose action should be cancelled.
            reason: Reason for cancellation.

        Returns:
            True if an action was cancelled, False if no action was running.
        """
        async with self._lock:
            execution = self._active_executions.get(script_name)
            if not execution or not execution.task:
                return False

            _LOGGER.info(
                "Cancelling action '%s' for script '%s': %s",
                execution.action_name,
                script_name,
                reason,
            )

            execution.task.cancel()
            return True

    async def run_shutdown_action(
        self,
        script_name: str,
        shutdown_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a shutdown action with timeout and proper handling.

        This method:
        1. Marks the script as shutting down (prevents new actions)
        2. Cancels any currently running action for the script
        3. Runs the shutdown function with a timeout
        4. Cleans up script state

        Args:
            script_name: Name of the script shutting down.
            shutdown_func: The shutdown function to execute.
            *args: Positional arguments for the shutdown function.
            **kwargs: Keyword arguments for the shutdown function.

        Returns:
            The result of the shutdown function, or None if timed out.

        Raises:
            ShutdownTimeoutError: If the shutdown action exceeds the timeout.
        """
        # Mark script as shutting down
        self._scripts_shutting_down.add(script_name)

        try:
            # Cancel any currently running action
            await self.cancel_action(script_name, "shutdown requested")

            # Wait briefly for cancellation to propagate
            await asyncio.sleep(0)

            # Run shutdown action with timeout
            try:
                result = await asyncio.wait_for(
                    self.submit_action(
                        script_name,
                        "__shutdown__",
                        shutdown_func,
                        *args,
                        is_lifecycle=True,
                        **kwargs,
                    ),
                    timeout=self._shutdown_timeout,
                )
                return result

            except asyncio.TimeoutError as exc:
                _LOGGER.error(
                    "Shutdown action for script '%s' exceeded timeout of %.0fms",
                    script_name,
                    self._shutdown_timeout * 1000,
                )
                # Force cancel the shutdown action
                await self.cancel_action(script_name, "timeout exceeded")
                raise ShutdownTimeoutError(script_name, self._shutdown_timeout) from exc

            except ActionCancelledError as exc:
                # This can happen if the action was cancelled due to timeout
                # We need to check if we're still in the timeout window
                _LOGGER.error(
                    "Shutdown action for script '%s' exceeded timeout of %.0fms",
                    script_name,
                    self._shutdown_timeout * 1000,
                )
                raise ShutdownTimeoutError(script_name, self._shutdown_timeout) from exc

        finally:
            # Clean up shutdown state
            self._scripts_shutting_down.discard(script_name)

    async def run_startup_action(
        self,
        script_name: str,
        startup_func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Run a startup action for a script.

        Args:
            script_name: Name of the script starting up.
            startup_func: The startup function to execute.
            *args: Positional arguments for the startup function.
            **kwargs: Keyword arguments for the startup function.

        Returns:
            The result of the startup function.

        Raises:
            ActionBusyError: If the script already has an action running.
            PoolExhaustedError: If no workers are available.
        """
        _LOGGER.debug("Running startup action for script '%s'", script_name)
        return await self.submit_action(
            script_name,
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
            script_names = list(self._active_executions.keys())

        for script_name in script_names:
            await self.cancel_action(script_name, "pool shutdown")

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
            _LOGGER.debug("Pool shutdown complete")

    def reset(self) -> None:
        """Reset the pool state.

        This clears all tracking data and resets the shutdown flag.
        Should only be used for testing or reinitialization.
        """
        self._active_executions.clear()
        self._scripts_shutting_down.clear()
        self._shutting_down = False
        self._semaphore = asyncio.Semaphore(self._max_workers)
        _LOGGER.debug("Action worker pool reset")
