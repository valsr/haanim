"""Action worker pool: executes the requests the dispatcher lets through.

The pool enforces the global limit on concurrently executing actions (see
"Concurrency Limit" in the design) and records each execution. The limit is a
counter checked when an execution is about to start: a request that does not
fit is rejected, it never waits. Execution modes, queues, timeouts and
cancellation belong to the dispatcher (``action_dispatcher.py``).
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
    """Executes actions on the event loop and limits how many execute at once.

    An execution holds a slot from ``begin()`` until ``end()``. The
    ``@startup`` and ``@shutdown`` handlers are recorded like actions but take
    no slot: the limit never keeps an automation from starting or stopping.
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

        # Executions that have begun and not ended, by execution_id
        self._active_executions: dict[str, ActionExecution] = {}

        _LOGGER.debug("ActionWorkerPool initialized with max_workers=%d", max_workers)

    @property
    def max_workers(self) -> int:
        """Get the maximum number of concurrent workers."""
        return self._max_workers

    @property
    def active_count(self) -> int:
        """Get the number of active executions, lifecycle handlers included."""
        return len(self._active_executions)

    @property
    def used_slots(self) -> int:
        """Get the number of slots in use: the active executions that count against the limit."""
        return sum(not execution.is_lifecycle for execution in self._active_executions.values())

    @property
    def available_workers(self) -> int:
        """Get the number of available worker slots."""
        return self._max_workers - self.used_slots

    @property
    def clock(self) -> Clock:
        """The clock this pool takes its time from."""
        return self._clock

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

    def begin(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        is_lifecycle: bool = False,
        **kwargs: Any,
    ) -> ActionExecution:
        """Take a slot for an execution that is about to start.

        The slot is held until ``end()`` is called with the execution.

        Args:
            automation_id: Name of the automation requesting the action.
            action_name: Name of the action to execute.
            func: The function to execute (def or async def).
            *args: Positional arguments for the function.
            is_lifecycle: Whether this is ``@startup`` or ``@shutdown``; those take no slot.
            **kwargs: Keyword arguments for the function.

        Returns:
            The execution, to pass to ``run()`` and ``end()``.

        Raises:
            PoolExhaustedError: If the limit of concurrent actions is reached.
        """
        if not is_lifecycle and self.used_slots >= self._max_workers:
            _LOGGER.error(
                "Limit of %d concurrent actions reached, cannot run action '%s' of automation '%s'",
                self._max_workers,
                action_name,
                automation_id,
            )
            raise PoolExhaustedError(self._max_workers)

        execution = ActionExecution(
            automation_id=automation_id,
            action_name=action_name,
            # Everything runs on the event loop, whether written def or async def
            func=as_coroutine_function(func),
            args=args,
            kwargs=kwargs,
            is_lifecycle=is_lifecycle,
        )
        self._active_executions[execution.execution_id] = execution
        return execution

    def end(self, execution: ActionExecution) -> None:
        """Give back the slot of an execution. Does nothing if it was given back before.

        Args:
            execution: An execution returned by ``begin()``.
        """
        if self._active_executions.pop(execution.execution_id, None) is None:
            return
        if execution.state is ActionState.PENDING:
            # It was cancelled before it ran at all
            execution.state = ActionState.CANCELLED
            execution.completed_at = self._clock.now()

    async def submit_action(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        is_lifecycle: bool = False,
        **kwargs: Any,
    ) -> Any:
        """Take a slot, execute a function in the current task and give the slot back.

        Args:
            automation_id: Name of the automation requesting the action.
            action_name: Name of the action to execute.
            func: The function to execute (def or async def).
            *args: Positional arguments for the function.
            is_lifecycle: Whether this is a lifecycle action (startup/shutdown).
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the action execution.

        Raises:
            PoolExhaustedError: If the limit of concurrent actions is reached.
            asyncio.CancelledError: If the execution was cancelled.
        """
        execution = self.begin(automation_id, action_name, func, *args, is_lifecycle=is_lifecycle, **kwargs)
        try:
            return await self.run(execution)
        finally:
            self.end(execution)

    async def run(self, execution: ActionExecution) -> Any:
        """Execute an execution that has begun, in the current task.

        Args:
            execution: An execution returned by ``begin()``.

        Returns:
            The result of the action.

        Raises:
            asyncio.CancelledError: If the execution was cancelled.
            Exception: Any exception from the action itself.
        """
        status_manager = self._status_manager

        execution.state = ActionState.RUNNING
        execution.started_at = self._clock.now()
        execution.task = asyncio.current_task()

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
            self.used_slots,
            self._max_workers,
        )

        try:
            result = await execution.func(*execution.args, **execution.kwargs)

        except asyncio.CancelledError:
            execution.state = ActionState.CANCELLED
            execution.completed_at = self._clock.now()
            _LOGGER.warning(
                "Action '%s' for automation '%s' was cancelled",
                execution.action_name,
                execution.automation_id,
            )
            status_manager.remove_running_action(execution.automation_id, execution.execution_id)
            raise

        except Exception as err:
            execution.state = ActionState.FAILED
            execution.error = err
            execution.completed_at = self._clock.now()
            _LOGGER.debug(
                "Action '%s' for automation '%s' failed: %s",
                execution.action_name,
                execution.automation_id,
                err,
            )
            status_manager.remove_running_action(
                execution.automation_id, execution.execution_id, error=str(err)
            )
            raise

        execution.state = ActionState.COMPLETED
        execution.result = result
        execution.completed_at = self._clock.now()

        _LOGGER.debug(
            "Completed action '%s' for automation '%s'",
            execution.action_name,
            execution.automation_id,
        )
        status_manager.remove_running_action(execution.automation_id, execution.execution_id)
        return result
