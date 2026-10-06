"""The single entry point for running an automation's actions.

Every request to run an action comes through the dispatcher, which applies the
action's execution mode (see "Execution Modes" in the design), rejects
re-entrant calls, and knows which requests are running or waiting. The worker
pool behind it executes the requests the dispatcher lets through.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from haanim.const import DEFAULT_ACTION_QUEUE_SIZE, DEFAULT_ACTION_TIMEOUT, ActionMode
from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionTimeOutError,
    PoolExhaustedError,
    QueueFullError,
)

if TYPE_CHECKING:
    from haanim.engine.action_pool import ActionExecution, ActionWorkerPool
    from haanim.interfaces import TimerHandle

_LOGGER = logging.getLogger(__name__)

# An action: (automation ID, action name).
ActionKey = tuple[str, str]

# The actions the current code was called through, outermost first. A context
# variable follows the code into the tasks it starts, and nowhere else.
_CALL_CHAIN: contextvars.ContextVar[tuple[ActionKey, ...]] = contextvars.ContextVar(
    "haanim_call_chain", default=()
)

# Told about the failure of an action a trigger fired: (action name, error).
FailureHandler = Callable[[str, BaseException], None]

# How long cancelled actions get to finish when the dispatcher shuts down.
SHUTDOWN_WAIT_SECONDS = 1.0

REASON_REENTRANT = "re-entrant call"
REASON_SUPERSEDED = "a newer request replaced it"
REASON_SHUTDOWN = "HAAnim is shutting down"


@dataclass(eq=False)
class _Request:
    """One request to run a function of an automation.

    Args:
        automation_id: ID of the automation.
        action_name: Name of the action, or of the lifecycle handler.
        func: The function to run.
        args: What to call the function with.
        outcome: Receives the result or the exception of the request.
        context: The context of the requester; the function runs in it.
        chain: The actions the function is called through, itself included.
        is_lifecycle: Whether this is ``@startup`` or ``@shutdown`` rather than an action.
        timeout: How long the execution may take, in seconds; 0 or less for no limit.
        execution: The pool's record of the execution, once it has started.
        task: The task executing the request, once it has started.
        timer: The timer of the timeout, while the execution runs.
        cancel_reason: Why the execution was cancelled, once it has been.
        timed_out: Whether it was cancelled for reaching its timeout.
    """

    automation_id: str
    action_name: str
    func: Callable[..., Any]
    args: tuple[Any, ...]
    outcome: asyncio.Future[Any]
    context: contextvars.Context
    chain: tuple[ActionKey, ...] = ()
    is_lifecycle: bool = False
    timeout: float = 0
    execution: ActionExecution | None = None
    task: asyncio.Task[Any] | None = None
    timer: TimerHandle | None = None
    cancel_reason: str | None = None
    timed_out: bool = False


@dataclass
class _Slot:
    """The requests of one action: the one executing and the ones waiting for it to end."""

    running: _Request | None = None
    waiting: deque[_Request] = field(default_factory=deque[_Request])


def _retrieve_exception(outcome: asyncio.Future[Any]) -> None:
    """Mark the exception of a request as seen, for when its caller is no longer waiting for it."""
    if not outcome.cancelled():
        outcome.exception()


class ActionDispatcher:
    """Applies execution modes and the re-entrancy rule to action requests.

    At most one execution of an action runs at a time. What happens to a
    request that arrives while the action is running is decided by the action's
    mode: ``DROP`` rejects it, ``QUEUE`` makes it wait its turn, ``CANCEL``
    cancels the running execution and runs the request once that has ended.
    """

    def __init__(
        self,
        pool: ActionWorkerPool,
        *,
        queue_size: int = DEFAULT_ACTION_QUEUE_SIZE,
        default_timeout: float = DEFAULT_ACTION_TIMEOUT,
    ) -> None:
        """Initialize the dispatcher.

        Args:
            pool: The worker pool that executes the requests.
            queue_size: How many requests may wait for one ``QUEUE`` action.
            default_timeout: Timeout in seconds of actions that do not set one; 0 for none.
        """
        self._pool = pool
        self._queue_size = queue_size
        self._default_timeout = default_timeout
        self._slots: dict[ActionKey, _Slot] = {}
        self._handlers: set[_Request] = set()
        self._failure_handlers: dict[str, FailureHandler] = {}
        self._last_started: dict[str, datetime] = {}
        # Set each time a request ends or is removed; lets wait_idle() wake up and re-check.
        self._changed = asyncio.Event()
        self._shutting_down = False

    @property
    def pool(self) -> ActionWorkerPool:
        """The worker pool that executes the requests."""
        return self._pool

    @property
    def queue_size(self) -> int:
        """How many requests may wait for one ``QUEUE`` action."""
        return self._queue_size

    @property
    def default_timeout(self) -> float:
        """Timeout in seconds of actions that do not set one; 0 for none."""
        return self._default_timeout

    @property
    def is_shutting_down(self) -> bool:
        """Whether the dispatcher has been shut down and accepts no more requests."""
        return self._shutting_down

    # --- Requests -----------------------------------------------------------------

    async def dispatch(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        mode: ActionMode = ActionMode.DROP,
        timeout: float | None = None,
        triggered: bool = False,
    ) -> Any:
        """Request an execution of an action and wait for its outcome.

        If the waiting caller is cancelled, the request is not: it runs, or
        stays queued, as if the caller were still there.

        Args:
            automation_id: ID of the automation the action belongs to.
            action_name: The action's name (not an alias).
            func: The action's function.
            *args: What to call the function with.
            mode: The action's execution mode.
            timeout: How long the execution may take, in seconds. The default
                timeout if None; no limit if 0 or less. Time spent waiting
                in the queue does not count.
            triggered: Whether a trigger fired the action. Such a request starts
                a call chain of its own, whatever code caused the trigger to fire.

        Returns:
            What the action returns.

        Raises:
            ActionDroppedError: If the call is re-entrant, or the action is
                running and its mode is ``DROP``.
            QueueFullError: If the action's queue is full (``QUEUE``).
            PoolExhaustedError: If the limit of concurrent actions is reached
                when the execution is about to start.
            ActionTimeOutError: If the execution reached its timeout.
            ActionCancelledError: If the execution was cancelled, the request
                was removed from the queue or replaced by a newer one
                (``CANCEL``), or the dispatcher is shutting down.
            Exception: Whatever the action raises.
        """
        key = (automation_id, action_name)
        chain = () if triggered else _CALL_CHAIN.get()

        # In every mode: a QUEUE action would wait for itself, a CANCEL action cancel its caller
        if key in chain:
            _LOGGER.debug("Action '%s' of '%s': re-entrant call rejected", action_name, automation_id)
            raise ActionDroppedError(automation_id, action_name, REASON_REENTRANT)

        if self._shutting_down:
            raise ActionCancelledError(action_name, REASON_SHUTDOWN)

        slot = self._slots.setdefault(key, _Slot())
        request = self._request(automation_id, action_name, func, args, chain=(*chain, key))
        request.timeout = self._default_timeout if timeout is None else timeout

        if slot.running is None:
            # The mode has been applied; now the limit is checked
            try:
                self._start(request, slot)
            except PoolExhaustedError:
                self._slots.pop(key, None)
                raise
            return await self._outcome(request)

        if mode is ActionMode.DROP:
            _LOGGER.debug(
                "Action '%s' of '%s': request dropped, already executing", action_name, automation_id
            )
            raise ActionDroppedError(automation_id, action_name)

        if mode is ActionMode.QUEUE:
            if len(slot.waiting) >= self._queue_size:
                raise QueueFullError(automation_id, action_name, self._queue_size)
        else:
            # A request that never started is replaced like the running execution is
            self._reject(slot.waiting, REASON_SUPERSEDED)
            self._cancel(slot.running, REASON_SUPERSEDED)

        slot.waiting.append(request)
        return await self._outcome(request)

    def set_failure_handler(self, automation_id: str, handler: FailureHandler | None) -> None:
        """Set who is told when an action of an automation fails with no caller to raise to.

        Args:
            automation_id: ID of the automation.
            handler: Called with the action's name and the error. None removes the handler.
        """
        if handler is None:
            self._failure_handlers.pop(automation_id, None)
        else:
            self._failure_handlers[automation_id] = handler

    async def fire(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        *args: Any,
        mode: ActionMode = ActionMode.DROP,
        timeout: float | None = None,
    ) -> Any:
        """Request an execution of an action on behalf of a trigger and wait for it.

        A trigger has no caller to raise to. If the action raises, times out,
        is dropped, finds its queue full or hits the concurrency limit, the
        failure is reported to the automation's failure handler and nothing
        is raised. A cancelled execution (the automation was stopped, or a
        newer ``CANCEL`` request replaced it) is not a failure.

        Args:
            automation_id: ID of the automation the action belongs to.
            action_name: The action's name (not an alias).
            func: The action's function.
            *args: What to call the function with.
            mode: The action's execution mode.
            timeout: As for ``dispatch()``.

        Returns:
            What the action returns; None if it failed or was cancelled.
        """
        try:
            return await self.dispatch(
                automation_id, action_name, func, *args, mode=mode, timeout=timeout, triggered=True
            )
        except ActionCancelledError as err:
            if err.action_name != action_name:
                # Raised by an action this one called, and not handled there
                self._report_failure(automation_id, action_name, err)
        except Exception as err:  # pylint: disable=broad-exception-caught
            self._report_failure(automation_id, action_name, err)
        return None

    def _report_failure(self, automation_id: str, action_name: str, error: BaseException) -> None:
        """Tell the automation's failure handler about a failure; log it if there is none."""
        handler = self._failure_handlers.get(automation_id)
        if handler is None:
            _LOGGER.error(
                "Action '%s' of '%s' failed: %s: %s", action_name, automation_id, type(error).__name__, error
            )
            return
        handler(action_name, error)

    async def run_handler(
        self, automation_id: str, handler_name: str, func: Callable[..., Any], *args: Any
    ) -> Any:
        """Run a ``@startup`` or ``@shutdown`` handler and wait for it.

        A handler is not an action: it has no execution mode and is not part of
        a call chain. Unlike an action, it is cancelled when the waiting caller
        is, which is how the lifecycle enforces its time limits.

        Args:
            automation_id: ID of the automation.
            handler_name: Name the execution is recorded under.
            func: The handler.
            *args: What to call the handler with.

        Returns:
            What the handler returns.
        """
        request = self._request(automation_id, handler_name, func, args, is_lifecycle=True)
        self._handlers.add(request)
        self._start(request, None)
        try:
            return await self._outcome(request)
        except asyncio.CancelledError:
            self._cancel(request, "the time limit was reached")
            raise

    def _request(
        self,
        automation_id: str,
        action_name: str,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        *,
        chain: tuple[ActionKey, ...] = (),
        is_lifecycle: bool = False,
    ) -> _Request:
        """Build a request made by the current code."""
        outcome: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        outcome.add_done_callback(_retrieve_exception)
        return _Request(
            automation_id=automation_id,
            action_name=action_name,
            func=func,
            args=args,
            outcome=outcome,
            context=contextvars.copy_context(),
            chain=chain,
            is_lifecycle=is_lifecycle,
        )

    @staticmethod
    async def _outcome(request: _Request) -> Any:
        """Wait for the outcome of a request without tying the request to the waiting caller."""
        return await asyncio.shield(request.outcome)

    # --- Execution ----------------------------------------------------------------

    def _start(self, request: _Request, slot: _Slot | None) -> None:
        """Start executing a request, in a task of its own and in the requester's context.

        Raises:
            PoolExhaustedError: If the limit of concurrent actions is reached; nothing was started.
        """
        # The slot is taken here, not in the task: nothing can take it in between
        request.execution = self._pool.begin(
            request.automation_id,
            request.action_name,
            request.func,
            *request.args,
            is_lifecycle=request.is_lifecycle,
        )
        if slot is not None:
            slot.running = request
            self._last_started[request.automation_id] = self._pool.clock.now()
        request.task = asyncio.get_running_loop().create_task(self._run(request), context=request.context)
        # A callback, not a finally in the task: it also runs for a task cancelled before its first step
        request.task.add_done_callback(lambda task: self._finished(request, slot, task))

        # The timeout measures execution time: it starts now, not when the request was made
        if request.timeout > 0:
            request.timer = self._pool.clock.call_later(request.timeout, lambda: self._expire(request))

    async def _run(self, request: _Request) -> Any:
        """Execute a request."""
        _CALL_CHAIN.set(request.chain)
        assert request.execution is not None
        return await self._pool.run(request.execution)

    def _expire(self, request: _Request) -> None:
        """Cancel an execution that has reached its timeout."""
        if request.cancel_reason is None and request.task is not None and not request.task.done():
            _LOGGER.warning(
                "Action '%s' of '%s' exceeded its timeout of %gs",
                request.action_name,
                request.automation_id,
                request.timeout,
            )
            request.timed_out = True
            self._cancel(request, "timeout")

    def _finished(self, request: _Request, slot: _Slot | None, task: asyncio.Task[Any]) -> None:
        """Deliver the outcome of an execution that has ended and start the request waiting for it."""
        if request.timer is not None:
            request.timer.cancel()
        if request.execution is not None:
            self._pool.end(request.execution)

        if task.cancelled():
            # Only the dispatcher cancels this task; the caller learns why
            if request.timed_out:
                error: BaseException = ActionTimeOutError(
                    request.automation_id, request.action_name, request.timeout
                )
            else:
                error = ActionCancelledError(request.action_name, request.cancel_reason or "cancelled")
            request.outcome.set_exception(error)
        elif (raised := task.exception()) is not None:
            # The caller receives the action's own exception object
            request.outcome.set_exception(raised)
        else:
            request.outcome.set_result(task.result())

        self._ended(request, slot)

    def _ended(self, request: _Request, slot: _Slot | None) -> None:
        """Record that an execution has ended and start the request waiting for it, if any."""
        if slot is None:
            self._handlers.discard(request)
        else:
            slot.running = None
            # The waiting request takes over the slot this execution has just given back
            while slot.waiting and slot.running is None:
                waiting = slot.waiting.popleft()
                try:
                    self._start(waiting, slot)
                except PoolExhaustedError as err:
                    waiting.outcome.set_exception(err)
            if slot.running is None:
                self._slots.pop((request.automation_id, request.action_name), None)
        self._changed.set()

    @staticmethod
    def _cancel(request: _Request, reason: str) -> bool:
        """Cancel a running execution, once. Returns whether this call cancelled it."""
        if request.cancel_reason is not None or request.task is None or request.task.done():
            return False
        request.cancel_reason = reason
        request.task.cancel()
        return True

    def _reject(self, waiting: deque[_Request], reason: str) -> int:
        """Remove requests that have not started; their callers receive ``ActionCancelledError``."""
        count = len(waiting)
        while waiting:
            request = waiting.popleft()
            request.outcome.set_exception(ActionCancelledError(request.action_name, reason))
        if count:
            self._changed.set()
        return count

    # --- Queries ------------------------------------------------------------------

    def last_action_time(self, automation_id: str) -> datetime | None:
        """Return when an action of an automation last started executing; None if none has."""
        return self._last_started.get(automation_id)

    def is_running(self, automation_id: str, action_name: str) -> bool:
        """Return whether an execution of the action is running."""
        slot = self._slots.get((automation_id, action_name))
        return slot is not None and slot.running is not None

    def queued_count(self, automation_id: str, action_name: str) -> int:
        """Return how many requests are waiting for the action."""
        slot = self._slots.get((automation_id, action_name))
        return len(slot.waiting) if slot is not None else 0

    def _running(self, automation_id: str | None) -> list[_Request]:
        """Return the requests that are executing, optionally for one automation only."""
        running = [slot.running for slot in self._slots.values() if slot.running is not None]
        running.extend(self._handlers)
        return [
            request for request in running if automation_id is None or request.automation_id == automation_id
        ]

    def _slots_of(self, automation_id: str | None) -> list[_Slot]:
        """Return the slots of the actions of one automation, or of all automations."""
        return [
            slot
            for (owner, _), slot in self._slots.items()
            if automation_id is None or owner == automation_id
        ]

    def is_idle(self, automation_id: str | None = None) -> bool:
        """Return whether no request is running or waiting.

        Args:
            automation_id: Look at this automation only. All automations if omitted.
        """
        return not self._running(automation_id) and not any(
            slot.waiting for slot in self._slots_of(automation_id)
        )

    async def wait_idle(self, automation_id: str | None = None) -> None:
        """Wait until no request is running or waiting.

        Returns at once if there is none. This does not stop new requests from
        being made while waiting; it returns the first time the dispatcher is
        found idle.

        Args:
            automation_id: Wait only for this automation's requests. All automations if omitted.
        """
        while not self.is_idle(automation_id):
            self._changed.clear()
            await self._changed.wait()

    # --- Stopping -----------------------------------------------------------------

    def remove_queued(self, automation_id: str | None, reason: str) -> int:
        """Remove the requests that are waiting for an action to end.

        Their callers receive ``ActionCancelledError``. Running executions are
        left alone.

        Args:
            automation_id: The automation whose queues to empty. All automations if None.
            reason: Why, for the error the callers receive.

        Returns:
            How many requests were removed.
        """
        return sum(self._reject(slot.waiting, reason) for slot in self._slots_of(automation_id))

    def cancel_running(self, automation_id: str | None, reason: str) -> int:
        """Cancel the running executions, lifecycle handlers included.

        The callers receive ``ActionCancelledError``. The cancellation is
        delivered at the action's next ``await`` or checkpoint.

        Args:
            automation_id: The automation whose executions to cancel. All automations if None.
            reason: Why, for the error the callers receive.

        Returns:
            How many executions were cancelled.
        """
        count = sum(self._cancel(request, reason) for request in self._running(automation_id))
        if count:
            _LOGGER.info(
                "Cancelled %d action(s)%s: %s",
                count,
                f" of automation '{automation_id}'" if automation_id is not None else "",
                reason,
            )
        return count

    def runs_in_current_task(self, automation_id: str) -> bool:
        """Return whether the current task is executing an action or handler of the automation."""
        current = asyncio.current_task()
        return any(request.task is current for request in self._running(automation_id))

    async def shutdown(self) -> None:
        """Stop accepting requests, remove the queued ones and cancel the running ones."""
        self._shutting_down = True
        self.remove_queued(None, REASON_SHUTDOWN)
        self.cancel_running(None, REASON_SHUTDOWN)

        try:
            await self._pool.clock.wait_for(self.wait_idle(), SHUTDOWN_WAIT_SECONDS)
        except TimeoutError:
            _LOGGER.warning("Dispatcher shut down with %d action(s) still running", len(self._running(None)))
