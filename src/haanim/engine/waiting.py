"""Waiting until a state expression is true: the work behind ``haa.wait_for``.

See "Waiting" in the design. The wait is level-based: an expression that is
already true ends it at once. Otherwise the expression is evaluated again each
time an entity it refers to changes, against the states as of that change, as
a state trigger does.
"""

from __future__ import annotations

import asyncio
from typing import Any

from haanim.engine.expression_eval import Expression
from haanim.interfaces import Clock, StateProvider, TimerHandle
from haanim.types import StateChangedEvent


class StateWait:
    """One wait for an expression to become true."""

    def __init__(self, expression: Expression, states: StateProvider, clock: Clock) -> None:
        """Initialize the wait.

        Args:
            expression: The parsed state expression.
            states: Where the entities are read and watched.
            clock: The clock the timeout runs on.
        """
        self._expression = expression
        self._states = states
        self._clock = clock
        self._seen: dict[str, Any] = {}
        self._outcome: asyncio.Future[bool] | None = None

    async def wait(self, timeout: float | None) -> bool:
        """Wait for the expression.

        Args:
            timeout: How many seconds to wait at most; None for no limit.

        Returns:
            True when the expression is true; False if the timeout passed first.
        """
        self._outcome = asyncio.get_running_loop().create_future()
        # Subscribed before the first look, so that no change is missed in between
        queues = {
            entity_id: self._states.subscribe(entity_id) for entity_id in sorted(self._expression.entities)
        }
        watchers = [asyncio.ensure_future(self._watch(queue)) for queue in queues.values()]
        timer: TimerHandle | None = None
        try:
            self._seen.update({entity_id: self._states.get(entity_id) for entity_id in queues})
            if self._expression.holds(self._seen.get):
                return True
            if timeout is not None:
                timer = self._clock.call_later(timeout, self._timed_out)
            return await self._outcome
        finally:
            if timer is not None:
                timer.cancel()
            for watcher in watchers:
                watcher.cancel()
            for entity_id, queue in queues.items():
                self._states.unsubscribe(queue, entity_id)

    async def _watch(self, queue: asyncio.Queue[StateChangedEvent | None]) -> None:
        """Evaluate for every change of one entity."""
        while (notification := await queue.get()) is not None:
            # Each change is evaluated against the states as of that change
            self._seen[notification.entity_id] = notification.new_state
            if self._expression.holds(self._seen.get):
                self._finish(True)

    def _timed_out(self) -> None:
        """The timeout has passed."""
        self._finish(False)

    def _finish(self, result: bool) -> None:
        """Deliver the result, once."""
        if self._outcome is not None and not self._outcome.done():
            self._outcome.set_result(result)
