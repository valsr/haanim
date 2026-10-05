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
from typing import TYPE_CHECKING, Any

from haanim.const import DEFAULT_ACTION_QUEUE_SIZE, ActionMode
from haanim.engine.errors import ActionCancelledError, ActionDroppedError, QueueFullError

if TYPE_CHECKING:
    from haanim.engine.action_pool import ActionWorkerPool

_LOGGER = logging.getLogger(__name__)

# An action: (automation ID, action name).
ActionKey = tuple[str, str]

# The actions the current code was called through, outermost first. A context
# variable follows the code into the tasks it starts, and nowhere else.
_CALL_CHAIN: contextvars.ContextVar[tuple[ActionKey, ...]] = contextvars.ContextVar(
    "haanim_call_chain", default=()
)

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
        task: The task executing the request, once it has started.
        cancel_reason: Why the execution was cancelled, once it has been.
    """

    automation_id: str
    action_name: str
    func: Callable[..., Any]
    args: tuple[Any, ...]
    outcome: asyncio.Future[Any]
    context: contextvars.Context
    chain: tuple[ActionKey, ...] = ()
    is_lifecycle: bool = False
    task: asyncio.Task[None] | None = None
    cancel_reason: str | None = None


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

    def __init__(self, pool: ActionWorkerPool, *, queue_size: int = DEFAULT_ACTION_QUEUE_SIZE) -> None:
        """Initialize the dispatcher.

        Args:
            pool: The worker pool that executes the requests.
            queue_size: How many requests may wait for one ``QUEUE`` action.
        """
        self._pool = pool
        self._queue_size = queue_size
        self._slots: dict[ActionKey, _Slot] = {}
        self._handlers: set[_Request] = set()
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
            triggered: Whether a trigger fired the action. Such a request starts
                a call chain of its own, whatever code caused the trigger to fire.

        Returns:
            What the action returns.

        Raises:
            ActionDroppedError: If the call is re-entrant, or the action is
                running and its mode is ``DROP``.
            QueueFullError: If the action's queue is full (``QUEUE``).
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

        if slot.running is None:
            self._start(request, slot)
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
        """Start executing a request, in a task of its own and in the requester's context."""
        if slot is not None:
            slot.running = request
        request.task = asyncio.get_running_loop().create_task(
            self._run(request, slot), context=request.context
        )

    async def _run(self, request: _Request, slot: _Slot | None) -> None:
        """Execute a request and deliver its outcome."""
        _CALL_CHAIN.set(request.chain)
        try:
            result = await self._pool.submit_action(
                request.automation_id,
                request.action_name,
                request.func,
                *request.args,
                is_lifecycle=request.is_lifecycle,
            )
        except asyncio.CancelledError:
            # Only the dispatcher cancels this task; the caller learns why
            reason = request.cancel_reason or "cancelled"
            request.outcome.set_exception(ActionCancelledError(request.action_name, reason))
        except Exception as err:  # pylint: disable=broad-exception-caught
            # The caller receives the action's own exception object
            request.outcome.set_exception(err)
        else:
            request.outcome.set_result(result)
        finally:
            if not request.outcome.done():
                request.outcome.cancel()
            self._ended(request, slot)

    def _ended(self, request: _Request, slot: _Slot | None) -> None:
        """Record that an execution has ended and start the request waiting for it, if any."""
        if slot is None:
            self._handlers.discard(request)
        else:
            slot.running = None
            if slot.waiting:
                self._start(slot.waiting.popleft(), slot)
            else:
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
