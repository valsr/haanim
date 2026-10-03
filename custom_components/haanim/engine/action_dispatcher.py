"""Action dispatcher with execution mode support.

This module provides action dispatching with support for DROP, QUEUE, and CANCEL
execution modes, as well as timeout handling.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from custom_components.haanim.const import ActionMode
from custom_components.haanim.engine.errors import (
    ActionTimeOutError,
    QueueFullError,
)

if TYPE_CHECKING:
    from custom_components.haanim.engine.action_pool import ActionWorkerPool

_LOGGER = logging.getLogger(__name__)


class ActionDispatcher:
    """Dispatches actions with support for execution modes and timeouts."""

    def __init__(self, action_pool: ActionWorkerPool) -> None:
        """Initialize the action dispatcher.

        Args:
            action_pool: The underlying action worker pool.
        """
        self._pool = action_pool

        # Track running actions by (automation_id, action_name)
        self._running_actions: dict[tuple[str, str], asyncio.Task[Any]] = {}

        # Action queues by (automation_id, action_name)
        self._action_queues: dict[tuple[str, str], asyncio.Queue[dict[str, Any]]] = defaultdict(asyncio.Queue)

        # Queue processing tasks
        self._queue_processors: dict[tuple[str, str], asyncio.Task[Any]] = {}

        # Lock for modifying state
        self._lock = asyncio.Lock()

    async def dispatch_action(
        self,
        automation_id: str,
        action_name: str,
        func: Any,
        execution_mode: ActionMode,
        timeout: float,
        queue_size: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Dispatch an action with execution mode handling.

        Args:
            automation_id: The automation ID.
            action_name: The action name.
            func: The function to execute.
            execution_mode: How to handle concurrent calls.
            timeout: Timeout in seconds (0 = no timeout).
            queue_size: Maximum queue size for QUEUE mode.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            The result of the action execution.

        Raises:
            ActionTimeOutError: If action times out.
            ActionCancelledError: If action is cancelled.
            QueueFullError: If queue is full (QUEUE mode).
        """
        action_key = (automation_id, action_name)

        async with self._lock:
            is_running = action_key in self._running_actions

            if execution_mode == ActionMode.DROP:
                if is_running:
                    _LOGGER.debug(
                        "Action %s.%s already running, dropping new request (DROP mode)",
                        automation_id,
                        action_name,
                    )
                    return None

            elif execution_mode == ActionMode.CANCEL:
                if is_running:
                    _LOGGER.debug(
                        "Action %s.%s already running, cancelling current (CANCEL mode)",
                        automation_id,
                        action_name,
                    )
                    # Cancel the running action
                    self._running_actions[action_key].cancel()
                    try:
                        await self._running_actions[action_key]
                    except asyncio.CancelledError:
                        pass
                    del self._running_actions[action_key]

            elif execution_mode == ActionMode.QUEUE:
                if is_running or action_key in self._queue_processors:
                    # Check queue size
                    queue = self._action_queues[action_key]
                    if queue.qsize() >= queue_size:
                        raise QueueFullError(automation_id, action_name, queue_size)

                    # Add to queue
                    _LOGGER.debug(
                        "Action %s.%s already running, queueing request (QUEUE mode)",
                        automation_id,
                        action_name,
                    )
                    await queue.put({"args": args, "kwargs": kwargs})

                    # Start queue processor if not running
                    if action_key not in self._queue_processors:
                        self._queue_processors[action_key] = asyncio.create_task(
                            self._process_queue(automation_id, action_name, func, timeout)
                        )

                    return None

        # Execute the action
        return await self._execute_with_timeout(automation_id, action_name, func, timeout, *args, **kwargs)

    async def _execute_with_timeout(
        self,
        automation_id: str,
        action_name: str,
        func: Any,
        timeout: float,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute an action with optional timeout.

        Args:
            automation_id: The automation ID.
            action_name: The action name.
            func: The function to execute.
            timeout: Timeout in seconds (0 = no timeout).
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The result of the action.

        Raises:
            ActionTimeOutError: If action times out.
        """
        action_key = (automation_id, action_name)

        # Create the execution task
        task = asyncio.create_task(
            self._pool.submit_action(automation_id, action_name, func, *args, **kwargs)
        )

        async with self._lock:
            self._running_actions[action_key] = task

        try:
            if timeout > 0:
                # Execute with timeout
                try:
                    result = await asyncio.wait_for(task, timeout=timeout)
                    return result
                except asyncio.TimeoutError as err:
                    task.cancel()
                    raise ActionTimeOutError(automation_id, action_name, timeout) from err
            else:
                # Execute without timeout
                return await task

        finally:
            async with self._lock:
                if action_key in self._running_actions:
                    del self._running_actions[action_key]

    async def _process_queue(
        self,
        automation_id: str,
        action_name: str,
        func: Any,
        timeout: float,
    ) -> None:
        """Process queued action requests.

        Args:
            automation_id: The automation ID.
            action_name: The action name.
            func: The function to execute.
            timeout: Timeout in seconds.
        """
        action_key = (automation_id, action_name)
        queue = self._action_queues[action_key]

        try:
            while True:
                # Get next item from queue
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Check if queue is empty
                    if queue.empty():
                        break
                    continue

                # Execute the action
                args = item["args"]
                kwargs = item["kwargs"]

                try:
                    await self._execute_with_timeout(
                        automation_id, action_name, func, timeout, *args, **kwargs
                    )
                except Exception as err:  # pylint: disable=broad-exception-caught
                    _LOGGER.exception(
                        "Error executing queued action %s.%s: %s", automation_id, action_name, err
                    )

        finally:
            async with self._lock:
                if action_key in self._queue_processors:
                    del self._queue_processors[action_key]

    async def cancel_automation_actions(self, automation_id: str) -> None:
        """Cancel all running and queued actions for an automation.

        Args:
            automation_id: The automation ID.
        """
        async with self._lock:
            # Cancel running actions
            for (sid, _), task in list(self._running_actions.items()):
                if sid == automation_id:
                    task.cancel()

            # Clear queues
            for sid, action_name in list(self._action_queues.keys()):
                if sid == automation_id:
                    queue = self._action_queues[(sid, action_name)]
                    while not queue.empty():
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    del self._action_queues[(sid, action_name)]

            # Cancel queue processors
            for (sid, _), task in list(self._queue_processors.items()):
                if sid == automation_id:
                    task.cancel()

        # Also cancel in the pool
        await self._pool.cancel_automation_actions(automation_id, "automation shutdown")
