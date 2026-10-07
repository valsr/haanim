"""State trigger: fires when a state expression becomes true.

See "State Trigger" in the design. The trigger subscribes to the entities its
expression refers to and re-evaluates the expression each time the state or an
attribute of one of them changes. It is edge-triggered: it fires when the
result changes from false to true.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from haanim.engine.durations import parse_duration
from haanim.engine.expression_eval import parse_expression
from haanim.engine.triggers.base import BaseTrigger
from haanim.events import StateEvent
from haanim.interfaces import Host, TimerHandle
from haanim.types import StateChangedEvent, StateVal

if TYPE_CHECKING:
    from haanim.engine.action_dispatcher import ActionDispatcher
    from haanim.engine.automation_context import TriggerDefinition

HOLD_WITH_EVERY_CHANGE = "hold cannot be combined with every_change=True"


class StateTrigger(BaseTrigger):
    """Fires an action when a state expression becomes true."""

    def __init__(
        self,
        host: Host,
        trigger_def: TriggerDefinition,
        dispatcher: ActionDispatcher | None = None,
    ) -> None:
        """Initialize the state trigger.

        Args:
            host: The host the engine runs in.
            trigger_def: The trigger definition. Its expression is the state
                expression; ``every_change`` and ``hold`` are options.
            dispatcher: Where the action is requested when the trigger fires.

        Raises:
            AutomationSyntaxError: If the expression is not a state expression.
            ValueError: If ``hold`` is not a duration, or is combined with ``every_change``.
        """
        super().__init__(host, trigger_def, dispatcher)
        self._expression = parse_expression(trigger_def.trigger_expr)
        self._every_change = bool(trigger_def.kwargs.get("every_change"))
        hold = trigger_def.kwargs.get("hold")
        self._hold_seconds = parse_duration(hold) if hold is not None else None
        if self._every_change and self._hold_seconds is not None:
            raise ValueError(HOLD_WITH_EVERY_CHANGE)

        # The states the expression is evaluated against: those of the last change seen
        self._states: dict[str, StateVal] = {}
        self._result = False
        self._queues: dict[str, asyncio.Queue[StateChangedEvent | None]] = {}
        self._watchers: list[asyncio.Task[None]] = []
        self._hold_timer: TimerHandle | None = None
        self._firing: set[asyncio.Future[Any]] = set()

    @property
    def entities(self) -> frozenset[str]:
        """The entities the expression refers to; changes to any other entity are not looked at."""
        return self._expression.entities

    @property
    def result(self) -> bool:
        """The result of the last evaluation."""
        return self._result

    @property
    def hold_pending(self) -> bool:
        """Whether the expression is true and the hold duration is running."""
        return self._hold_timer is not None

    async def async_start(self) -> None:
        """Subscribe to the entities and take the baseline, without firing."""
        await self.async_stop()
        for entity_id in sorted(self._expression.entities):
            self._states[entity_id] = self.state_manager.get(entity_id)
            queue = self.state_manager.subscribe(entity_id)
            self._queues[entity_id] = queue
            self._watchers.append(asyncio.ensure_future(self._watch(queue)))
        # The baseline: a trigger started while its expression is true fires only
        # after the expression has been false in between
        self._result = self._evaluate()

    async def async_stop(self) -> None:
        """Unsubscribe and discard a pending hold."""
        self._discard_hold()
        for entity_id, queue in self._queues.items():
            self.state_manager.unsubscribe(queue, entity_id)
        self._queues.clear()
        for watcher in self._watchers:
            watcher.cancel()
        self._watchers.clear()
        self._states.clear()
        self._result = False

    def _evaluate(self) -> bool:
        """Evaluate the expression against the states last seen. An unusable value makes it false."""
        return self._expression.holds(self._states.get)

    async def _watch(self, queue: asyncio.Queue[StateChangedEvent | None]) -> None:
        """Re-evaluate for every change of one entity."""
        while True:
            notification = await queue.get()
            if notification is None:
                return
            self._on_change(notification)

    def _on_change(self, notification: StateChangedEvent) -> None:
        """The state or an attribute of a referenced entity changed: evaluate once and act on the result."""
        self._states[notification.entity_id] = notification.new_state
        previous, self._result = self._result, self._evaluate()

        if self._every_change:
            if self._result:
                self._fire(notification)
        elif self._hold_seconds is None:
            if self._result and not previous:
                self._fire(notification)
        elif not self._result:
            # False before the duration elapsed: the pending fire is discarded
            self._discard_hold()
        elif not previous:
            # The event of the fire describes this change, the one that made the expression true
            self._hold_timer = self.host.clock.call_later(
                self._hold_seconds, lambda: self._hold_elapsed(notification)
            )

    def _hold_elapsed(self, notification: StateChangedEvent) -> None:
        """The expression has been true for the whole hold duration."""
        self._hold_timer = None
        self._fire(notification)

    def _discard_hold(self) -> None:
        """Cancel a pending hold, if any."""
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _fire(self, notification: StateChangedEvent) -> None:
        """Fire for a change, without waiting for the action."""
        firing = asyncio.ensure_future(self._fire_checked(notification))
        self._firing.add(firing)
        firing.add_done_callback(self._firing.discard)

    async def _fire_checked(self, notification: StateChangedEvent) -> None:
        """Request the action, unless a constraint blocks the fire."""
        if not await self._check_constraints():
            return
        await self._execute_function(self._state_event(notification))

    def _state_event(self, notification: StateChangedEvent) -> StateEvent:
        """Build the StateEvent of a fire: the change that caused the evaluation that fired."""
        return self._event(
            StateEvent,
            entity_id=notification.entity_id,
            old_state=_present(notification.old_state),
            new_state=_present(notification.new_state),
        )


def _present(state: StateVal | None) -> StateVal | None:
    """Return a state, or None for an entity that does not exist (just created, or removed)."""
    if state is None or state.state is None:
        return None
    return state
