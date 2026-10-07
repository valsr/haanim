"""Tests for the concurrency limit and action timeouts.

See "Concurrency Limit" and "Timeouts" in the design.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from haanim.const import DEFAULT_ACTION_TIMEOUT, DEFAULT_MAX_CONCURRENT_ACTIONS, TRIGGER_STATE, ActionMode
from haanim.engine import action_pool
from haanim.engine.action_dispatcher import REASON_SUPERSEDED, ActionDispatcher
from haanim.engine.action_pool import ActionState, ActionWorkerPool
from haanim.engine.automation_context import TriggerDefinition
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionTimeOutError,
    PoolExhaustedError,
    QueueFullError,
)
from haanim.engine.triggers.manager import TriggerManager
from haanim.testing import FakeClock, FakeStateProvider, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.helpers import fire_trigger
from tests.engine.test_action_dispatcher import (  # noqa: F401  pylint: disable=unused-import
    Bench,
    bench,
    make_bench,
    outcome,
)
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

DROP, QUEUE, CANCEL = ActionMode.DROP, ActionMode.QUEUE, ActionMode.CANCEL
MODES = [DROP, QUEUE, CANCEL]


class TestNoWaitingPath:
    """The limit is a counter: the pool has nothing a request could wait on."""

    def test_no_semaphore_and_no_lock(self) -> None:
        """The pool's source uses no asyncio synchronisation primitive."""
        tree = ast.parse(Path(action_pool.__file__).read_text(encoding="utf-8"))
        names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        names |= {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & {
            "Semaphore",
            "BoundedSemaphore",
            "Lock",
            "Condition",
            "Event",
            "Queue",
            "wait_for",
        }

    def test_the_only_await_is_the_action_itself(self) -> None:
        """Nothing is awaited before the action's function is called."""
        tree = ast.parse(Path(action_pool.__file__).read_text(encoding="utf-8"))
        awaited = [ast.unparse(node.value) for node in ast.walk(tree) if isinstance(node, ast.Await)]
        assert sorted(awaited) == [
            "execution.func(*execution.args, **execution.kwargs)",
            "self.run(execution)",
        ]

    def test_taking_and_returning_a_slot_is_synchronous(self) -> None:
        """A slot is taken or refused on the spot."""
        assert not inspect.iscoroutinefunction(ActionWorkerPool.begin)
        assert not inspect.iscoroutinefunction(ActionWorkerPool.end)

    def test_default_limit(self) -> None:
        """The default limit is 20 concurrent actions."""
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=FakeClock())
        assert pool.max_workers == DEFAULT_MAX_CONCURRENT_ACTIONS == 20
        assert (pool.used_slots, pool.available_workers) == (0, 20)


class TestLimitReached:
    """A request that would exceed the limit is rejected, whatever the action's mode."""

    @pytest.mark.parametrize("mode", MODES)
    async def test_rejected_with_pool_exhausted_error(
        self, make_bench: Callable[..., Bench], mode: ActionMode
    ) -> None:
        """The request fails at once; it is not queued and not retried."""
        bench = make_bench(max_workers=2)
        await bench.request("a", mode, action="one")
        await bench.request("b", mode, action="two")

        error = await outcome(await bench.request("c", mode, action="three"))
        assert type(error) is PoolExhaustedError
        assert error.max_workers == 2
        assert bench.started == ["a", "b"]
        assert not bench.dispatcher.is_running("auto", "three")
        assert bench.dispatcher.queued_count("auto", "three") == 0
        assert bench.clock.now() == DEFAULT_NOW

    async def test_not_retried_when_a_slot_becomes_free(self, make_bench: Callable[..., Bench]) -> None:
        """A rejected request stays rejected; the next request gets the free slot."""
        bench = make_bench(max_workers=1)
        await bench.request("a", DROP, action="one")
        await outcome(await bench.request("b", DROP, action="two"))

        await bench.release("a")
        assert bench.started == ["a"]

        again = await bench.request("c", DROP, action="two")
        await bench.release("c")
        assert await again == "c done"

    async def test_twenty_actions_run_and_the_next_is_rejected(self, bench: Bench) -> None:
        """With the default limit, the twenty-first concurrent action is rejected."""
        for number in range(20):
            await bench.request(f"r{number}", DROP, action=f"action{number}")
        assert bench.pool.used_slots == 20

        error = await outcome(await bench.request("extra", DROP, action="one_more"))
        assert type(error) is PoolExhaustedError and error.max_workers == 20

    @pytest.mark.parametrize("ending", ["returns", "raises", "cancelled", "times out"])
    async def test_slot_is_given_back_however_the_execution_ends(
        self, make_bench: Callable[..., Bench], ending: str
    ) -> None:
        """Success, failure, cancellation and timeout all free the slot."""
        bench = make_bench(max_workers=1)

        async def action() -> None:
            await bench.gates["go"].wait()
            if ending == "raises":
                raise ValueError("boom")

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "one", action, timeout=5))
        await bench.clock.settle()
        assert bench.pool.used_slots == 1

        if ending == "cancelled":
            bench.dispatcher.cancel_running("auto", "test")
            await bench.clock.settle()
        elif ending == "times out":
            await bench.clock.advance(seconds=5)
        else:
            await bench.release("go")
        await asyncio.gather(running, return_exceptions=True)

        assert bench.pool.used_slots == 0
        assert bench.pool.get_all_active_actions() == []

    async def test_execution_cancelled_before_it_ran_gives_its_slot_back(self, bench: Bench) -> None:
        """An execution cancelled before its first step is cleaned up like any other."""
        caller = asyncio.create_task(bench.dispatcher.dispatch("auto", "work", bench.work, "a"))
        await asyncio.sleep(0)
        assert bench.pool.used_slots == 1
        (execution,) = bench.pool.get_all_active_actions()
        assert execution.state is ActionState.PENDING

        assert bench.dispatcher.cancel_running("auto", "too early") == 1
        error = await outcome(caller)

        assert type(error) is ActionCancelledError and error.reason == "too early"
        assert bench.started == []
        assert execution.state is ActionState.CANCELLED
        assert bench.pool.used_slots == 0
        assert bench.dispatcher.is_idle()


class TestModeIsAppliedBeforeTheLimit:
    """The limit is checked after the execution mode has been applied."""

    async def test_dropped_request_does_not_count(self, make_bench: Callable[..., Bench]) -> None:
        """A dropped request takes no slot and is reported as dropped, not as over the limit."""
        bench = make_bench(max_workers=2)
        await bench.request("a", DROP, action="one")
        error = await outcome(await bench.request("b", DROP, action="one"))
        assert type(error) is ActionDroppedError
        assert bench.pool.used_slots == 1

        fits = await bench.request("c", DROP, action="two")
        await bench.release("c")
        assert await fits == "c done"

    async def test_dropped_even_when_the_limit_is_reached(self, make_bench: Callable[..., Bench]) -> None:
        """With the pool full, a request for a running DROP action is still a dropped request."""
        bench = make_bench(max_workers=1)
        await bench.request("a", DROP)
        assert type(await outcome(await bench.request("b", DROP))) is ActionDroppedError

    async def test_queued_requests_do_not_count(self, make_bench: Callable[..., Bench]) -> None:
        """Requests waiting in a queue take no slot."""
        bench = make_bench(max_workers=2)
        for label in "abcde":
            await bench.request(label, QUEUE, action="queueing")
        assert bench.dispatcher.queued_count("auto", "queueing") == 4
        assert bench.pool.used_slots == 1

        fits = await bench.request("x", DROP, action="other")
        await bench.release("x")
        assert await fits == "x done"

    async def test_queueing_is_possible_when_the_limit_is_reached(
        self, make_bench: Callable[..., Bench]
    ) -> None:
        """A request for a running QUEUE action is queued, not rejected, while the pool is full."""
        bench = make_bench(max_workers=1)
        await bench.request("a", QUEUE)
        queued = await bench.request("b", QUEUE)
        assert not queued.done()

        await bench.release("a")
        await bench.release("b")
        assert await queued == "b done"

    async def test_queue_full_even_when_the_limit_is_reached(self, make_bench: Callable[..., Bench]) -> None:
        """A full queue is reported as such."""
        bench = make_bench(max_workers=1, queue_size=0)
        await bench.request("a", QUEUE)
        assert type(await outcome(await bench.request("b", QUEUE))) is QueueFullError

    async def test_reentrant_call_is_dropped_when_the_limit_is_reached(
        self, make_bench: Callable[..., Bench]
    ) -> None:
        """A re-entrant call is rejected as such, not as over the limit."""
        bench = make_bench(max_workers=1)
        errors: list[BaseException] = []

        async def recursive() -> None:
            try:
                await bench.dispatcher.dispatch("auto", "recursive", recursive)
            except ActionDroppedError as err:
                errors.append(err)

        await bench.dispatcher.dispatch("auto", "recursive", recursive)
        assert len(errors) == 1


class TestQueuedRequestAtTheFront:
    """A QUEUE request meets the limit when its turn comes, not when it is made."""

    async def test_takes_the_slot_its_predecessor_gives_back(self, make_bench: Callable[..., Bench]) -> None:
        """With the pool full, the next queued request runs in the slot that has just become free."""
        bench = make_bench(max_workers=2)
        await bench.request("a", QUEUE, action="queueing")
        await bench.request("x", DROP, action="other")
        queued = await bench.request("b", QUEUE, action="queueing")

        # Someone else asking in the meantime is rejected: there is no free slot
        assert type(await outcome(await bench.request("y", DROP, action="third"))) is PoolExhaustedError

        await bench.release("a")
        assert bench.started == ["a", "x", "b"]
        assert bench.pool.used_slots == 2
        await bench.release("b")
        assert await queued == "b done"

    async def test_no_request_can_take_the_slot_in_between(self, make_bench: Callable[..., Bench]) -> None:
        """A request made the moment the predecessor ends does not get ahead of the queue."""
        bench = make_bench(max_workers=1)
        competitor: list[asyncio.Task[Any]] = []

        async def first() -> str:
            await bench.gates["a"].wait()
            # Asked for from inside the ending execution: as early as anyone could
            competitor.append(
                asyncio.create_task(
                    bench.dispatcher.dispatch("auto", "other", bench.work, "x", triggered=True)
                )
            )
            return "a done"

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "queueing", first, mode=QUEUE))
        await bench.clock.settle()
        queued = asyncio.create_task(
            bench.dispatcher.dispatch("auto", "queueing", bench.work, "b", mode=QUEUE)
        )
        await bench.clock.settle()

        await bench.release("a")
        assert await running == "a done"
        assert bench.started == ["b"]
        assert type(await outcome(competitor[0])) is PoolExhaustedError
        await bench.release("b")
        assert await queued == "b done"

    async def test_rejected_if_the_limit_is_reached_at_that_moment(
        self, make_bench: Callable[..., Bench]
    ) -> None:
        """If there is no slot when its turn comes, the queued request gets PoolExhaustedError."""
        bench = make_bench(max_workers=2)
        await bench.request("a", QUEUE, action="queueing")
        await bench.request("x", DROP, action="other")
        queued = [await bench.request(label, QUEUE, action="queueing") for label in "bc"]

        # The only way a predecessor's slot is not there to take over: the limit itself shrank
        bench.pool._max_workers = 1  # pylint: disable=protected-access
        await bench.release("a")

        for task in queued:
            error = await outcome(task)
            assert type(error) is PoolExhaustedError
        assert bench.started == ["a", "x"]
        assert bench.dispatcher.is_idle("auto") is False  # "x" still runs
        assert not bench.dispatcher.is_running("auto", "queueing")
        assert bench.dispatcher.queued_count("auto", "queueing") == 0


class TestCancelTakesOverTheSlot:
    """A CANCEL request is never rejected by the limit: it uses the slot of the execution it cancels."""

    async def test_runs_with_the_pool_full(self, make_bench: Callable[..., Bench]) -> None:
        """With the limit reached by the action itself, the new request still runs."""
        bench = make_bench(max_workers=1)
        first = await bench.request("a", CANCEL)
        second = await bench.request("b", CANCEL)

        error = await outcome(first)
        assert type(error) is ActionCancelledError and error.reason == REASON_SUPERSEDED
        assert bench.started == ["a", "b"]
        assert bench.pool.used_slots == 1
        await bench.release("b")
        assert await second == "b done"

    async def test_slot_cannot_be_taken_in_between(self, make_bench: Callable[..., Bench]) -> None:
        """A request made while the cancelled execution cleans up does not get the slot."""
        bench = make_bench(max_workers=1)
        competitor: list[asyncio.Task[Any]] = []

        async def cleaning_up() -> None:
            try:
                await bench.gates["never"].wait()
            finally:
                competitor.append(
                    asyncio.create_task(
                        bench.dispatcher.dispatch("auto", "other", bench.work, "x", triggered=True)
                    )
                )

        first = asyncio.create_task(bench.dispatcher.dispatch("auto", "latest", cleaning_up, mode=CANCEL))
        await bench.clock.settle()
        second = asyncio.create_task(
            bench.dispatcher.dispatch("auto", "latest", bench.work, "b", mode=CANCEL)
        )
        await bench.clock.settle()

        assert type(await outcome(first)) is ActionCancelledError
        assert bench.started == ["b"]
        assert type(await outcome(competitor[0])) is PoolExhaustedError
        await bench.release("b")
        assert await second == "b done"


class TestNestedCalls:
    """An action suspended in a call to another action keeps its slot."""

    @staticmethod
    def nested(bench: Bench, depth: int) -> tuple[list[Callable[[], Any]], list[Any]]:
        """Build actions that call each other in a chain; the innermost waits for the test."""
        results: list[Any] = []
        levels: list[Callable[[], Any]] = []

        def level(number: int) -> Callable[[], Any]:
            async def run() -> str:
                if number + 1 == depth:
                    await bench.gates["innermost"].wait()
                    return f"level {number}"
                try:
                    inner = await bench.dispatcher.dispatch("auto", f"level{number + 1}", levels[number + 1])
                except PoolExhaustedError as err:
                    results.append(err)
                    return f"level {number} (limit)"
                return f"level {number} <- {inner}"

            return run

        levels.extend(level(number) for number in range(depth))
        return levels, results

    async def test_one_slot_per_level(self, make_bench: Callable[..., Bench]) -> None:
        """A chain of three nested calls uses three slots."""
        bench = make_bench(max_workers=3)
        levels, _ = self.nested(bench, 3)
        outer = asyncio.create_task(bench.dispatcher.dispatch("auto", "level0", levels[0]))
        await bench.clock.settle()
        assert bench.pool.used_slots == 3

        await bench.release("innermost")
        assert await outer == "level 0 <- level 1 <- level 2"
        assert bench.pool.used_slots == 0

    async def test_chain_deeper_than_the_limit(self, make_bench: Callable[..., Bench]) -> None:
        """The call that needs one slot too many raises PoolExhaustedError in the calling action."""
        bench = make_bench(max_workers=2)
        levels, errors = self.nested(bench, 3)

        assert await bench.dispatcher.dispatch("auto", "level0", levels[0]) == "level 0 <- level 1 (limit)"
        assert [type(error) for error in errors] == [PoolExhaustedError]
        assert bench.pool.used_slots == 0


class TestLifecycleHandlersAndTheLimit:
    """@startup and @shutdown are not actions and take no slot."""

    async def test_handler_runs_with_the_pool_full(self, make_bench: Callable[..., Bench]) -> None:
        """An automation can be started and stopped while the limit is reached."""
        bench = make_bench(max_workers=1)
        await bench.request("a", DROP)

        async def handler() -> str:
            return "ran"

        assert await bench.dispatcher.run_handler("auto", "__shutdown__", handler) == "ran"

    async def test_handler_takes_no_slot(self, make_bench: Callable[..., Bench]) -> None:
        """A running handler leaves all slots to actions."""
        bench = make_bench(max_workers=1)
        handler = asyncio.create_task(bench.dispatcher.run_handler("auto", "__startup__", bench.work, "h"))
        await bench.clock.settle()
        assert (bench.pool.active_count, bench.pool.used_slots) == (1, 0)

        action = await bench.request("a", DROP)
        await bench.release("a")
        await bench.release("h")
        assert (await action, await handler) == ("a done", "h done")


LIMIT_SOURCE = """
from haanim import PoolExhaustedError, action, haa

@action
async def outer(event):
    try:
        return await haa.call("inner")
    except PoolExhaustedError as err:
        return f"limit of {err.max_workers} reached"

@action
async def inner(event):
    return await haa.automation("processor").call("process_data")
"""

PROCESSOR_SOURCE = """
from haanim import action

@action
def process_data(event):
    return "processed"
"""


class SmallWorld(World):
    """A world whose pool has room for two concurrent actions."""

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.pool = ActionWorkerPool(
            status_manager=AutomationStatusManager(), clock=self.clock, max_workers=2
        )
        self.dispatcher = ActionDispatcher(self.pool)


class TestLimitBetweenAutomations:
    """The limit counts the actions of all automations together."""

    async def test_automation_code_can_catch_the_error(self, tmp_path: Path) -> None:
        """The design's example: PoolExhaustedError is raised in the calling action."""
        world = SmallWorld(tmp_path)
        lights = await world.started("lights", LIMIT_SOURCE)
        await world.started("processor", PROCESSOR_SOURCE)

        # outer and inner hold the two slots; the call into the processor needs a third.
        # The error is raised in inner, propagates to outer unchanged, and outer catches it.
        assert await lights.call_action("outer") == "limit of 2 reached"
        assert world.pool.used_slots == 0

    async def test_actions_of_all_automations_share_the_limit(self, tmp_path: Path) -> None:
        """Running actions of one automation leave fewer slots for another."""
        world = SmallWorld(tmp_path)
        lights = await world.started("lights", LIMIT_SOURCE)
        processor = await world.started("processor", PROCESSOR_SOURCE)

        # outer -> inner uses both slots while inner waits for the processor: here it gets one
        world.pool._max_workers = 3  # pylint: disable=protected-access
        assert await lights.call_action("outer") == "processed"
        assert await processor.call_action("process_data") == "processed"


# --- Timeouts ---------------------------------------------------------------------------------


async def timed(bench: Bench, label: str, timeout: float | None, **kwargs: Any) -> asyncio.Task[Any]:
    """Request an execution of the bench's action with a timeout."""
    task = asyncio.create_task(
        bench.dispatcher.dispatch(
            "auto", kwargs.pop("action", "work"), bench.work, label, timeout=timeout, **kwargs
        )
    )
    await bench.clock.settle()
    return task


class TestTimeout:
    """An action that runs longer than its timeout is cancelled."""

    async def test_caller_receives_action_timeout_error(self, bench: Bench) -> None:
        """The caller gets ActionTimeOutError naming the action and the timeout."""
        running = await timed(bench, "a", 30.1)
        await bench.clock.advance(seconds=30)
        assert not running.done()

        await bench.clock.advance(seconds=0.1)
        error = await outcome(running)
        assert type(error) is ActionTimeOutError
        assert (error.automation_id, error.action_name, error.timeout) == ("auto", "work", 30.1)

    async def test_action_is_cancelled(self, bench: Bench) -> None:
        """The execution itself ends: it is cancelled at its next await."""
        await timed(bench, "a", 5)
        await bench.clock.advance(seconds=5)
        assert bench.ended == ["a"]
        assert bench.dispatcher.is_idle()
        assert bench.pool.used_slots == 0

    async def test_action_that_finishes_in_time(self, bench: Bench) -> None:
        """Within the timeout the result is returned and no timer is left behind."""
        running = await timed(bench, "a", 5)
        await bench.clock.advance(seconds=4.9)
        await bench.release("a")

        assert await running == "a done"
        assert bench.clock.pending_timers == 0

    @pytest.mark.parametrize("timeout", [0, 0.0, -1, -0.5])
    async def test_zero_or_negative_means_no_timeout(self, bench: Bench, timeout: float) -> None:
        """timeout <= 0: the action may run as long as it likes."""
        running = await timed(bench, "a", timeout)
        assert bench.clock.pending_timers == 0
        await bench.clock.advance(seconds=24 * 3600)
        assert not running.done()

        await bench.release("a")
        assert await running == "a done"

    async def test_timeout_error_is_not_a_cancellation(self, bench: Bench) -> None:
        """Timed out and cancelled are different outcomes."""
        timed_out = await timed(bench, "a", 5, action="slow")
        cancelled = await timed(bench, "b", 60, action="stopped")
        await bench.clock.advance(seconds=5)
        bench.dispatcher.cancel_running("auto", "by hand")

        kinds = [type(await outcome(timed_out)), type(await outcome(cancelled))]
        assert kinds == [ActionTimeOutError, ActionCancelledError]
        assert not issubclass(ActionTimeOutError, ActionCancelledError)
        assert not issubclass(ActionCancelledError, ActionTimeOutError)

    async def test_cancelled_action_does_not_time_out_later(self, bench: Bench) -> None:
        """Once an execution has ended, its timer is gone."""
        running = await timed(bench, "a", 5)
        bench.dispatcher.cancel_running("auto", "by hand")
        assert type(await outcome(running)) is ActionCancelledError
        assert bench.clock.pending_timers == 0

    async def test_timeout_during_cleanup_after_a_cancel_is_ignored(self, bench: Bench) -> None:
        """An execution already cancelled for another reason keeps that reason."""

        async def slow_cleanup() -> None:
            try:
                await bench.gates["run"].wait()
            finally:
                await bench.clock.sleep(10)

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "slow", slow_cleanup, timeout=5))
        await bench.clock.settle()
        bench.dispatcher.cancel_running("auto", "by hand")
        await bench.clock.advance(seconds=10)

        error = await outcome(running)
        assert type(error) is ActionCancelledError and error.reason == "by hand"


class TestDefaultTimeout:
    """An action without a timeout uses the default action timeout."""

    async def test_no_default_means_no_timeout(self, bench: Bench) -> None:
        """Unless configured, the default is no timeout."""
        assert bench.dispatcher.default_timeout == DEFAULT_ACTION_TIMEOUT == 0
        running = await timed(bench, "a", None)
        await bench.clock.advance(seconds=24 * 3600)
        assert not running.done()

    async def test_configured_default_applies(self) -> None:
        """With a default timeout configured, an action that sets none is limited by it."""
        bench = Bench()
        bench.dispatcher = ActionDispatcher(bench.pool, default_timeout=5)
        running = await timed(bench, "a", None)
        await bench.clock.advance(seconds=5)

        error = await outcome(running)
        assert type(error) is ActionTimeOutError and error.timeout == 5

    async def test_action_timeout_overrides_the_default(self) -> None:
        """An action's own timeout is used instead of the default, whether longer or none at all."""
        bench = Bench()
        bench.dispatcher = ActionDispatcher(bench.pool, default_timeout=5)
        longer = await timed(bench, "a", 8, action="longer")
        unlimited = await timed(bench, "b", 0, action="unlimited")

        await bench.clock.advance(seconds=7.9)
        assert not longer.done()
        await bench.clock.advance(seconds=0.1)
        assert (await outcome(longer)).timeout == 8

        await bench.clock.advance(seconds=3600)
        assert not unlimited.done()
        await bench.release("b")
        assert await unlimited == "b done"


class TestTimeoutMeasuresExecutionTime:
    """Time spent waiting in a queue does not count."""

    async def test_queue_wait_is_not_counted(self, bench: Bench) -> None:
        """A request that waited longer than its timeout still gets its full execution time."""
        first = await timed(bench, "a", 0, mode=QUEUE)
        second = await timed(bench, "b", 5, mode=QUEUE)

        await bench.clock.advance(seconds=8)
        assert not second.done()
        await bench.release("a")
        assert await first == "a done"

        await bench.clock.advance(seconds=4.9)
        assert not second.done()
        await bench.release("b")
        assert await second == "b done"

    async def test_timeout_starts_when_the_execution_starts(self, bench: Bench) -> None:
        """The queued request times out its timeout after it started, not after it was made."""
        await timed(bench, "a", 0, mode=QUEUE)
        second = await timed(bench, "b", 5, mode=QUEUE)
        assert bench.clock.pending_timers == 0

        await bench.clock.advance(seconds=8)
        await bench.release("a")
        await bench.clock.advance(seconds=4.9)
        assert not second.done()

        await bench.clock.advance(seconds=0.1)
        assert type(await outcome(second)) is ActionTimeOutError

    async def test_queue_continues_after_a_timeout(self, bench: Bench) -> None:
        """A timed-out execution makes room for the next request like any other ending."""
        first = await timed(bench, "a", 5, mode=QUEUE)
        second = await timed(bench, "b", 5, mode=QUEUE)

        await bench.clock.advance(seconds=5)
        assert type(await outcome(first)) is ActionTimeOutError
        assert bench.started == ["a", "b"]
        await bench.release("b")
        assert await second == "b done"


class TestNestedTimeouts:
    """Each action has its own timeout; a called action's time counts towards the caller's too."""

    @staticmethod
    def pair(
        bench: Bench, inner_seconds: float, inner_timeout: float, calls: int = 1
    ) -> tuple[Any, list[Any]]:
        """Build an outer action that calls an inner one, which takes ``inner_seconds``."""
        log: list[Any] = []

        async def inner() -> str:
            try:
                await bench.clock.sleep(inner_seconds)
            except asyncio.CancelledError:
                log.append("inner cancelled")
                raise
            log.append("inner finished")
            return "inner"

        async def outer() -> list[str]:
            results = []
            for _ in range(calls):
                try:
                    results.append(
                        await bench.dispatcher.dispatch("auto", "inner", inner, timeout=inner_timeout)
                    )
                except ActionTimeOutError as err:
                    log.append(f"outer caught timeout of {err.action_name}")
                    results.append("timeout")
            return results

        return outer, log

    async def test_inner_time_counts_towards_the_outer_timeout(self, bench: Bench) -> None:
        """An outer action times out while it waits for the action it called."""
        outer, log = self.pair(bench, inner_seconds=10, inner_timeout=0)
        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "outer", outer, timeout=5))
        await bench.clock.advance(seconds=5)

        error = await outcome(running)
        assert type(error) is ActionTimeOutError
        assert (error.action_name, error.timeout) == ("outer", 5)

    async def test_the_call_already_made_runs_to_completion(self, bench: Bench) -> None:
        """Timing out the caller does not cancel the action it called."""
        outer, log = self.pair(bench, inner_seconds=10, inner_timeout=0)
        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "outer", outer, timeout=5))
        await bench.clock.advance(seconds=5)
        await outcome(running)
        assert log == []

        await bench.clock.advance(seconds=5)
        assert log == ["inner finished"]

    async def test_several_calls_add_up(self, bench: Bench) -> None:
        """Two calls of three seconds exceed an outer timeout of five."""
        outer, log = self.pair(bench, inner_seconds=3, inner_timeout=0, calls=2)
        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "outer", outer, timeout=5))
        await bench.clock.advance(seconds=5)

        assert type(await outcome(running)) is ActionTimeOutError
        assert log == ["inner finished"]

    async def test_inner_timeout_is_raised_in_the_outer_action(self, bench: Bench) -> None:
        """The inner action's own timeout reaches the action that called it, which can go on."""
        outer, log = self.pair(bench, inner_seconds=10, inner_timeout=3)
        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "outer", outer, timeout=20))
        await bench.clock.advance(seconds=3)

        assert await running == ["timeout"]
        assert log == ["inner cancelled", "outer caught timeout of inner"]

    async def test_uncaught_inner_timeout_names_the_inner_action(self, bench: Bench) -> None:
        """If the caller does not catch it, the inner action's error propagates unchanged."""

        async def inner() -> None:
            await bench.clock.sleep(10)

        async def outer() -> None:
            await bench.dispatcher.dispatch("auto", "inner", inner, timeout=3)

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "outer", outer, timeout=20))
        await bench.clock.advance(seconds=3)

        error = await outcome(running)
        assert type(error) is ActionTimeOutError
        assert (error.action_name, error.timeout) == ("inner", 3)


TIMEOUT_SOURCE = """
from haanim import ActionMode, ActionTimeOutError, action, haa, on_state

@action(timeout=30.1)
async def timed_action(event):
    log.append("timed_action started")
    try:
        await haa.sleep(event.data.get("seconds", 60))
    finally:
        log.append("timed_action ended")
    return "in time"

@action(timeout=1)
def spin(event):
    log.append("spin started")
    while True:
        pass

@action(timeout=1)
def spin_in_calls(event):
    def step(n):
        return n + 1
    n = 0
    while n >= 0:
        n = step(n)

@action
async def no_timeout(event):
    await haa.sleep(event.data["seconds"])
    return "finished"

@on_state("sensor.door == 'on'")
@action(name="door", timeout=4, execution_mode=ActionMode.QUEUE)
async def on_door(event):
    await haa.sleep(60)
"""

CALLER_SOURCE = """
from haanim import ActionTimeOutError, action, haa

@action
async def call_it(event):
    try:
        return await haa.automation("processor").call("timed_action")
    except ActionTimeOutError as err:
        return f"Action timed out: {err.action_name} after {err.timeout}"
"""


class TestTimeoutsOfAutomationActions:
    """The timeout given to @action."""

    async def test_the_designs_example(self, world: World) -> None:
        """A calling automation catches ActionTimeOutError for an action with timeout=30.1."""
        await world.started("processor", TIMEOUT_SOURCE)
        caller = await world.started("lights", CALLER_SOURCE)

        call = asyncio.create_task(caller.call_action("call_it"))
        await world.clock.advance(seconds=30)
        assert not call.done()
        await world.clock.advance(seconds=0.1)

        assert await call == "Action timed out: timed_action after 30.1"
        assert world.log == ["timed_action started", "timed_action ended"]

    async def test_within_the_timeout(self, world: World) -> None:
        """An action that finishes in time returns its result."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        call = asyncio.create_task(automation.call_action("timed_action", {"seconds": 30}))
        await world.clock.advance(seconds=30)
        assert await call == "in time"

    async def test_action_without_timeout_runs_as_long_as_it_needs(self, world: World) -> None:
        """Not given: the default applies, which is no timeout unless configured."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        call = asyncio.create_task(automation.call_action("no_timeout", {"seconds": 86400}))
        await world.clock.advance(seconds=86400)
        assert await call == "finished"

    async def test_loop_without_await_times_out(self, world: World) -> None:
        """A def action that loops forever is cancelled at a checkpoint when its timeout is reached."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        call = asyncio.create_task(automation.call_action("spin"))
        await world.clock.settle()
        assert world.log == ["spin started"]
        assert not call.done()

        await world.clock.advance(seconds=1)
        error = await outcome(call)
        assert type(error) is ActionTimeOutError
        assert (error.automation_id, error.action_name, error.timeout) == ("processor", "spin", 1)
        assert world.dispatcher.is_idle()

    async def test_loop_of_function_calls_times_out(self, world: World) -> None:
        """Calls of automation functions are checkpoints too."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        call = asyncio.create_task(automation.call_action("spin_in_calls"))
        await world.clock.advance(seconds=1)
        assert type(await outcome(call)) is ActionTimeOutError

    async def test_automation_stays_on_after_a_timeout(self, world: World) -> None:
        """A timed-out action does not change the automation's state, and can be called again."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        call = asyncio.create_task(automation.call_action("spin"))
        await world.clock.advance(seconds=1)
        await outcome(call)

        assert automation.state.value == "on"
        again = asyncio.create_task(automation.call_action("timed_action", {"seconds": 1}))
        await world.clock.advance(seconds=1)
        assert await again == "in time"

    async def test_trigger_definitions_carry_the_timeout(self, world: World) -> None:
        """A trigger function's timeout reaches its triggers."""
        automation = await world.started("processor", TIMEOUT_SOURCE)
        (trigger,) = automation.context.get_triggers()
        assert (trigger.action_name, trigger.timeout, trigger.execution_mode) == ("door", 4, QUEUE)

    async def test_trigger_fired_action_times_out(
        self, bench: Bench, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The timeout applies when a trigger fires the action; there is no caller to raise to."""
        states = FakeStateProvider(bench.clock)
        manager = TriggerManager(make_host(clock=bench.clock, states=states), bench.dispatcher)
        trigger_id = await manager.register_trigger(
            TriggerDefinition(
                trigger_type=TRIGGER_STATE,
                trigger_expr="sensor.door == 'on'",
                func_name="on_door",
                func=lambda: bench.work("a"),
                automation_id="auto",
                action_name="door",
                timeout=4,
            )
        )
        firing = asyncio.create_task(fire_trigger(manager, trigger_id))
        await bench.clock.advance(seconds=4)
        await firing

        assert bench.ended == ["a"]
        assert "exceeded timeout of 4" in caplog.text
        assert bench.dispatcher.is_idle()


class TestEveryOutcomeIsDistinguishable:
    """Dropped, cancelled, timed out, queue-full and over-the-limit each have their own error."""

    async def test_five_outcomes_five_errors(self, make_bench: Callable[..., Bench]) -> None:
        """One request of each kind, and no error type is a subclass of another."""
        bench = make_bench(queue_size=0, max_workers=4)
        await bench.request("a", DROP, action="dropping")
        dropped = await outcome(await bench.request("b", DROP, action="dropping"))

        await bench.request("c", QUEUE, action="queueing")
        queue_full = await outcome(await bench.request("d", QUEUE, action="queueing"))

        replaced = await bench.request("e", CANCEL, action="cancelling")
        await bench.request("f", CANCEL, action="cancelling")
        cancelled = await outcome(replaced)

        slow = await timed(bench, "g", 5, action="slow")
        over_limit = await outcome(await bench.request("h", DROP, action="one_too_many"))
        await bench.clock.advance(seconds=5)
        timed_out = await outcome(slow)

        kinds = [type(dropped), type(queue_full), type(cancelled), type(timed_out), type(over_limit)]
        assert kinds == [
            ActionDroppedError,
            QueueFullError,
            ActionCancelledError,
            ActionTimeOutError,
            PoolExhaustedError,
        ]
        for kind in kinds:
            assert not any(issubclass(kind, other) for other in kinds if other is not kind)
