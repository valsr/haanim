"""Tests for the action dispatcher: execution modes, queues and re-entrant calls.

See "Execution Modes" and "Queue Configuration" in the design. The first part
drives the dispatcher with plain functions; the second part goes through loaded
automations.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from haanim.const import DEFAULT_ACTION_QUEUE_SIZE, TRIGGER_STATE, ActionMode
from haanim.engine.action_dispatcher import (
    REASON_REENTRANT,
    REASON_SHUTDOWN,
    REASON_SUPERSEDED,
    SHUTDOWN_WAIT_SECONDS,
    ActionDispatcher,
)
from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.automation_context import TriggerDefinition
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.errors import (
    ActionCancelledError,
    ActionDroppedError,
    ActionTimeOutError,
    PoolExhaustedError,
    QueueFullError,
)
from haanim.engine.lifecycle import REASON_STOPPED, AutomationState, LifecycleSettings
from haanim.engine.triggers.manager import TriggerManager
from haanim.testing import FakeClock, FakeStateProvider, make_host
from haanim.testing.fakes import DEFAULT_NOW
from tests.engine.test_lifecycle import World, world  # noqa: F401  pylint: disable=unused-import

DROP, QUEUE, CANCEL = ActionMode.DROP, ActionMode.QUEUE, ActionMode.CANCEL
MODES = [DROP, QUEUE, CANCEL]


class Bench:
    """A dispatcher on a fake clock, and an action whose executions the test ends one by one."""

    def __init__(self, queue_size: int = DEFAULT_ACTION_QUEUE_SIZE, max_workers: int = 20) -> None:
        self.clock = FakeClock()
        self.pool = ActionWorkerPool(
            status_manager=AutomationStatusManager(), clock=self.clock, max_workers=max_workers
        )
        self.dispatcher = ActionDispatcher(self.pool, queue_size=queue_size)
        self.started: list[str] = []
        self.ended: list[str] = []
        self.gates: defaultdict[str, asyncio.Event] = defaultdict(asyncio.Event)

    async def work(self, label: str) -> str:
        """Run until the test releases this execution."""
        self.started.append(label)
        try:
            await self.gates[label].wait()
            return f"{label} done"
        finally:
            self.ended.append(label)

    async def request(
        self, label: str, mode: ActionMode, action: str = "work", automation: str = "auto"
    ) -> asyncio.Task[Any]:
        """Request an execution from a task of its own and let it get as far as it can."""
        task = asyncio.create_task(self.dispatcher.dispatch(automation, action, self.work, label, mode=mode))
        await self.clock.settle()
        return task

    async def release(self, label: str) -> None:
        """Let an execution end."""
        self.gates[label].set()
        await self.clock.settle()


@pytest.fixture
async def make_bench() -> AsyncIterator[Callable[..., Bench]]:
    """Build benches whose leftover executions are cancelled when the test ends."""
    benches: list[Bench] = []

    def build(**kwargs: Any) -> Bench:
        benches.append(Bench(**kwargs))
        return benches[-1]

    yield build
    for bench in benches:
        for gate in bench.gates.values():
            gate.set()
        await bench.dispatcher.shutdown()


@pytest.fixture
def bench(make_bench: Callable[..., Bench]) -> Bench:
    """A dispatcher with the default queue size."""
    return make_bench()


async def outcome(task: asyncio.Task[Any]) -> BaseException:
    """Return the exception a request ended with."""
    with pytest.raises(BaseException) as exc_info:  # noqa: PT011
        await task
    return exc_info.value


class TestIdleAction:
    """A request for an action that is not running starts at once, in every mode."""

    @pytest.mark.parametrize("mode", MODES)
    async def test_runs_and_returns_the_result(self, bench: Bench, mode: ActionMode) -> None:
        """The caller receives what the action returns."""
        task = await bench.request("a", mode)
        assert bench.started == ["a"]
        assert bench.dispatcher.is_running("auto", "work")

        await bench.release("a")
        assert await task == "a done"
        assert not bench.dispatcher.is_running("auto", "work")

    @pytest.mark.parametrize("mode", MODES)
    async def test_runs_again_once_finished(self, bench: Bench, mode: ActionMode) -> None:
        """Only an execution that is still running affects a new request."""
        first = await bench.request("a", mode)
        await bench.release("a")
        second = await bench.request("b", mode)
        await bench.release("b")
        assert [await first, await second] == ["a done", "b done"]

    @pytest.mark.parametrize("mode", MODES)
    async def test_the_actions_own_exception_reaches_the_caller(self, bench: Bench, mode: ActionMode) -> None:
        """An exception raised by the action is raised to the caller as the same object."""
        error = KeyError("room")

        async def failing() -> None:
            raise error

        with pytest.raises(KeyError) as exc_info:
            await bench.dispatcher.dispatch("auto", "failing", failing, mode=mode)
        assert exc_info.value is error
        assert bench.dispatcher.is_idle()

    async def test_default_mode_is_drop(self, bench: Bench) -> None:
        """Without a mode the request is handled as DROP."""
        first = asyncio.create_task(bench.dispatcher.dispatch("auto", "work", bench.work, "a"))
        await bench.clock.settle()
        with pytest.raises(ActionDroppedError):
            await bench.dispatcher.dispatch("auto", "work", bench.work, "b")
        await bench.release("a")
        assert await first == "a done"


class TestDropMode:
    """DROP: a new request is discarded and the running execution continues."""

    async def test_new_request_is_dropped(self, bench: Bench) -> None:
        """The caller of the new request receives ActionDroppedError."""
        await bench.request("a", DROP)
        dropped = await bench.request("b", DROP)

        error = await outcome(dropped)
        assert type(error) is ActionDroppedError
        assert (error.automation_id, error.action_name, error.reason) == ("auto", "work", "already executing")
        assert bench.started == ["a"]

    async def test_running_execution_continues(self, bench: Bench) -> None:
        """Dropping a request does not disturb the execution that is running."""
        running = await bench.request("a", DROP)
        await outcome(await bench.request("b", DROP))

        assert not running.done()
        await bench.release("a")
        assert await running == "a done"

    async def test_dropped_request_is_not_kept(self, bench: Bench) -> None:
        """A dropped request never runs, not even after the running execution has ended."""
        running = await bench.request("a", DROP)
        await outcome(await bench.request("b", DROP))
        await bench.release("a")
        await running

        assert bench.started == ["a"]
        assert bench.dispatcher.is_idle()


class TestQueueMode:
    """QUEUE: new requests wait and run one at a time in request order."""

    async def test_new_request_waits(self, bench: Bench) -> None:
        """A request made while the action runs does not start until that execution ends."""
        first = await bench.request("a", QUEUE)
        second = await bench.request("b", QUEUE)
        assert bench.started == ["a"]
        assert not second.done()
        assert bench.dispatcher.queued_count("auto", "work") == 1

        await bench.release("a")
        assert bench.started == ["a", "b"]
        assert await first == "a done"

        await bench.release("b")
        assert await second == "b done"

    async def test_runs_in_request_order_one_at_a_time(self, bench: Bench) -> None:
        """Executions never overlap and follow the order of the requests."""
        tasks = [await bench.request(label, QUEUE) for label in "abcd"]

        for position, label in enumerate("abcd"):
            assert bench.started == list("abcd")[: position + 1]
            assert bench.ended == list("abcd")[:position]
            await bench.release(label)

        assert [await task for task in tasks] == ["a done", "b done", "c done", "d done"]
        assert bench.dispatcher.is_idle()

    async def test_each_caller_gets_its_own_result(self, bench: Bench) -> None:
        """A queued caller receives the result of its own execution, not of an earlier one."""
        first = await bench.request("a", QUEUE)
        second = await bench.request("b", QUEUE)
        await bench.release("b")
        assert not second.done()

        await bench.release("a")
        assert (await first, await second) == ("a done", "b done")

    async def test_a_failing_execution_does_not_stop_the_queue(self, bench: Bench) -> None:
        """When an execution raises, its caller gets the exception and the next request runs."""
        calls: list[int] = []

        async def flaky(number: int) -> int:
            calls.append(number)
            await bench.gates[str(number)].wait()
            if number == 1:
                raise ValueError("first fails")
            return number

        first = asyncio.create_task(bench.dispatcher.dispatch("auto", "flaky", flaky, 1, mode=QUEUE))
        second = asyncio.create_task(bench.dispatcher.dispatch("auto", "flaky", flaky, 2, mode=QUEUE))
        await bench.clock.settle()
        await bench.release("1")
        await bench.release("2")

        assert type(await outcome(first)) is ValueError
        assert await second == 2
        assert calls == [1, 2]

    async def test_queue_full(self, make_bench: Callable[..., Bench]) -> None:
        """A request beyond the queue size is rejected with QueueFullError."""
        bench = make_bench(queue_size=2)
        running = await bench.request("a", QUEUE)
        waiting = [await bench.request("b", QUEUE), await bench.request("c", QUEUE)]

        error = await outcome(await bench.request("d", QUEUE))
        assert type(error) is QueueFullError
        assert (error.automation_id, error.action_name, error.queue_size) == ("auto", "work", 2)

        # The requests that did fit are unaffected
        for label in "abc":
            await bench.release(label)
        assert [await task for task in (running, *waiting)] == ["a done", "b done", "c done"]
        assert bench.started == ["a", "b", "c"]

    async def test_the_running_execution_does_not_count_towards_the_queue_size(
        self, make_bench: Callable[..., Bench]
    ) -> None:
        """The size limits the waiting requests; the one executing is not in the queue."""
        bench = make_bench(queue_size=1)
        await bench.request("a", QUEUE)
        waiting = await bench.request("b", QUEUE)
        assert not waiting.done()
        assert bench.dispatcher.queued_count("auto", "work") == 1

    async def test_queue_has_room_again_when_a_request_starts(self, make_bench: Callable[..., Bench]) -> None:
        """Once a waiting request starts executing, another one fits in the queue."""
        bench = make_bench(queue_size=1)
        await bench.request("a", QUEUE)
        await bench.request("b", QUEUE)
        assert type(await outcome(await bench.request("c", QUEUE))) is QueueFullError

        await bench.release("a")
        fits = await bench.request("d", QUEUE)
        assert not fits.done()

    async def test_default_queue_size(self, bench: Bench) -> None:
        """The default queue holds 100 requests."""
        assert bench.dispatcher.queue_size == DEFAULT_ACTION_QUEUE_SIZE == 100
        await bench.request("a", QUEUE)
        for number in range(100):
            asyncio.create_task(
                bench.dispatcher.dispatch("auto", "work", bench.work, f"q{number}", mode=QUEUE)
            )
        await bench.clock.settle()
        assert bench.dispatcher.queued_count("auto", "work") == 100

        with pytest.raises(QueueFullError) as exc_info:
            await bench.dispatcher.dispatch("auto", "work", bench.work, "one too many", mode=QUEUE)
        assert exc_info.value.queue_size == 100


class TestCancelMode:
    """CANCEL: the running execution is cancelled and the new request runs."""

    async def test_running_execution_is_cancelled(self, bench: Bench) -> None:
        """The caller of the cancelled execution receives ActionCancelledError."""
        first = await bench.request("a", CANCEL)
        second = await bench.request("b", CANCEL)

        error = await outcome(first)
        assert type(error) is ActionCancelledError
        assert (error.action_name, error.reason) == ("work", REASON_SUPERSEDED)
        assert bench.ended == ["a"]
        assert not second.done()

    async def test_new_request_runs_and_returns_the_result(self, bench: Bench) -> None:
        """The new request's caller receives the action's result."""
        await bench.request("a", CANCEL)
        second = await bench.request("b", CANCEL)
        assert bench.started == ["a", "b"]

        await bench.release("b")
        assert await second == "b done"
        assert bench.dispatcher.is_idle()

    async def test_new_request_starts_after_the_cancelled_one_has_ended(self, bench: Bench) -> None:
        """The executions do not overlap: the cancelled one finishes its cleanup first."""
        order: list[str] = []
        cleanup = asyncio.Event()

        async def careful(label: str) -> str:
            order.append(f"{label} started")
            try:
                await bench.gates[label].wait()
            finally:
                if label == "a":
                    await cleanup.wait()
                order.append(f"{label} ended")
            return label

        first = asyncio.create_task(bench.dispatcher.dispatch("auto", "careful", careful, "a", mode=CANCEL))
        await bench.clock.settle()
        second = asyncio.create_task(bench.dispatcher.dispatch("auto", "careful", careful, "b", mode=CANCEL))
        await bench.clock.settle()
        assert order == ["a started"]

        cleanup.set()
        await bench.clock.settle()
        assert order == ["a started", "a ended", "b started"]

        await bench.release("b")
        assert await second == "b"
        assert type(await outcome(first)) is ActionCancelledError

    async def test_a_request_that_never_started_is_replaced_too(self, bench: Bench) -> None:
        """Of several requests made while one execution is ending, only the newest runs."""
        cleanup = asyncio.Event()

        async def slow_to_stop(label: str) -> str:
            bench.started.append(label)
            try:
                await bench.gates[label].wait()
            finally:
                if label == "a":
                    await cleanup.wait()
            return label

        tasks = []
        for label in "abc":
            tasks.append(
                asyncio.create_task(
                    bench.dispatcher.dispatch("auto", "slow", slow_to_stop, label, mode=CANCEL)
                )
            )
            await bench.clock.settle()

        middle = await outcome(tasks[1])
        assert type(middle) is ActionCancelledError
        assert middle.reason == REASON_SUPERSEDED

        cleanup.set()
        await bench.release("c")
        assert bench.started == ["a", "c"]
        assert await tasks[2] == "c"
        assert type(await outcome(tasks[0])) is ActionCancelledError

    async def test_three_requests_in_a_row(self, bench: Bench) -> None:
        """Each new request cancels the execution before it."""
        tasks = [await bench.request(label, CANCEL) for label in "abc"]
        await bench.release("c")

        assert type(await outcome(tasks[0])) is ActionCancelledError
        assert type(await outcome(tasks[1])) is ActionCancelledError
        assert await tasks[2] == "c done"
        assert bench.started == ["a", "b", "c"]
        assert bench.ended == ["a", "b", "c"]


class TestModeIsPerAction:
    """Different actions never affect each other."""

    @pytest.mark.parametrize("mode", MODES)
    async def test_other_action_of_the_same_automation(self, bench: Bench, mode: ActionMode) -> None:
        """A running action does not drop, delay or cancel a request for another action."""
        first = await bench.request("a", mode, action="one")
        second = await bench.request("b", mode, action="two")
        assert bench.started == ["a", "b"]

        await bench.release("a")
        await bench.release("b")
        assert (await first, await second) == ("a done", "b done")

    @pytest.mark.parametrize("mode", MODES)
    async def test_same_action_name_in_another_automation(self, bench: Bench, mode: ActionMode) -> None:
        """Actions of different automations are different actions, even with the same name."""
        first = await bench.request("a", mode, automation="lights")
        second = await bench.request("b", mode, automation="heating")
        assert bench.started == ["a", "b"]

        await bench.release("a")
        await bench.release("b")
        assert (await first, await second) == ("a done", "b done")


class TestOutcomesAreDistinguishable:
    """Each way a request can fail to return a result has an error type of its own."""

    async def test_dropped_cancelled_and_queue_full(self, make_bench: Callable[..., Bench]) -> None:
        """Dropped, cancelled and queue-full requests raise three different errors."""
        bench = make_bench(queue_size=0)
        await bench.request("a", DROP, action="dropping")
        dropped = await outcome(await bench.request("b", DROP, action="dropping"))

        await bench.request("c", QUEUE, action="queueing")
        queue_full = await outcome(await bench.request("d", QUEUE, action="queueing"))

        replaced = await bench.request("e", CANCEL, action="cancelling")
        await bench.request("f", CANCEL, action="cancelling")
        cancelled = await outcome(replaced)

        kinds = [type(dropped), type(queue_full), type(cancelled)]
        assert kinds == [ActionDroppedError, QueueFullError, ActionCancelledError]
        for kind in kinds:
            others = [
                other for other in (*kinds, ActionTimeOutError, PoolExhaustedError) if other is not kind
            ]
            assert not any(issubclass(kind, other) for other in others)


class TestCancelledCaller:
    """A request does not depend on its caller still waiting for it."""

    @pytest.mark.parametrize("mode", MODES)
    async def test_running_request_continues(self, bench: Bench, mode: ActionMode) -> None:
        """Cancelling the waiting caller does not cancel the execution."""
        caller = await bench.request("a", mode)
        caller.cancel()
        await bench.clock.settle()
        assert caller.cancelled()
        assert bench.ended == []

        await bench.release("a")
        assert bench.ended == ["a"]
        assert bench.dispatcher.is_idle()

    async def test_queued_request_stays_queued(self, bench: Bench) -> None:
        """A queued request whose caller is cancelled still runs when its turn comes."""
        await bench.request("a", QUEUE)
        caller = await bench.request("b", QUEUE)
        caller.cancel()
        await bench.clock.settle()
        assert bench.dispatcher.queued_count("auto", "work") == 1

        await bench.release("a")
        assert bench.started == ["a", "b"]

    async def test_unobserved_failure_is_not_reported_by_the_loop(
        self, bench: Bench, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An exception nobody waits for does not end up as 'exception was never retrieved'."""

        async def failing() -> None:
            await bench.gates["x"].wait()
            raise ValueError("nobody listens")

        caller = asyncio.create_task(bench.dispatcher.dispatch("auto", "failing", failing))
        await bench.clock.settle()
        caller.cancel()
        with caplog.at_level(logging.ERROR, logger="asyncio"):
            await bench.release("x")
            await asyncio.gather(caller, return_exceptions=True)
            del caller
            gc.collect()
            await bench.clock.settle()
        assert bench.dispatcher.is_idle()
        # Only this test's exception counts: another test's leftovers may be collected here too
        leaked = [
            record
            for record in caplog.records
            if "never retrieved" in record.getMessage()
            and record.exc_info is not None
            and isinstance(record.exc_info[1], ValueError)
        ]
        assert leaked == []


class Chain:
    """Actions that call each other through the dispatcher, as ``haa.call`` does."""

    def __init__(self, bench: Bench, mode: ActionMode) -> None:
        self.bench = bench
        self.mode = mode
        self.calls: list[str] = []
        self.errors: list[BaseException] = []

    def action(self, name: str, *then: str, automation: str = "auto") -> Callable[[], Any]:
        """Build an action that records itself and then calls the named actions, in order."""

        async def run() -> str:
            self.calls.append(name)
            for target in then:
                try:
                    await self.call(target)
                except ActionDroppedError as err:
                    self.errors.append(err)
            return name

        self.actions[name] = (automation, run)
        return run

    actions: dict[str, tuple[str, Callable[[], Any]]]

    async def call(self, name: str) -> Any:
        """Call an action by name."""
        automation, func = self.actions[name]
        return await self.bench.dispatcher.dispatch(automation, name, func, mode=self.mode)


@pytest.fixture
def chain(bench: Bench, request: pytest.FixtureRequest) -> Chain:
    """Actions in the execution mode the test is parametrized with."""
    result = Chain(bench, request.param)
    result.actions = {}
    return result


@pytest.mark.parametrize("chain", MODES, indirect=True)
class TestReentrantCalls:
    """An action that calls itself, directly or through other actions, is rejected in every mode."""

    async def test_direct(self, chain: Chain) -> None:
        """An action calling itself gets ActionDroppedError."""
        chain.action("a", "a")
        assert await chain.call("a") == "a"

        (error,) = chain.errors
        assert type(error) is ActionDroppedError
        assert (error.automation_id, error.action_name, error.reason) == ("auto", "a", REASON_REENTRANT)
        assert chain.calls == ["a"]

    async def test_through_another_action(self, chain: Chain) -> None:
        """A calls B and B calls A: B's call is rejected and both finish."""
        chain.action("a", "b")
        chain.action("b", "a")
        assert await chain.call("a") == "a"

        (error,) = chain.errors
        assert (error.action_name, error.reason) == ("a", REASON_REENTRANT)
        assert chain.calls == ["a", "b"]

    async def test_through_a_longer_chain_and_another_automation(self, chain: Chain) -> None:
        """The rule follows the whole chain, across automations."""
        chain.action("a", "b")
        chain.action("b", "c", automation="heating")
        chain.action("c", "a", "b", automation="garden")
        assert await chain.call("a") == "a"

        assert [(error.automation_id, error.action_name) for error in chain.errors] == [
            ("auto", "a"),
            ("heating", "b"),
        ]
        assert all(error.reason == REASON_REENTRANT for error in chain.errors)
        assert chain.calls == ["a", "b", "c"]

    async def test_calling_another_action_twice_is_not_reentrant(self, chain: Chain) -> None:
        """Only an action that is in the chain of callers is rejected."""
        chain.action("a", "b", "b")
        chain.action("b")
        assert await chain.call("a") == "a"
        assert chain.errors == []
        assert chain.calls == ["a", "b", "b"]

    async def test_same_name_in_another_automation_is_another_action(
        self, chain: Chain, bench: Bench
    ) -> None:
        """An action is identified by automation and name together."""
        calls: list[str] = []

        async def inner() -> str:
            calls.append("heating.a")
            return "inner"

        async def outer() -> str:
            calls.append("lights.a")
            return await bench.dispatcher.dispatch("heating", "a", inner, mode=chain.mode)

        assert await bench.dispatcher.dispatch("lights", "a", outer, mode=chain.mode) == "inner"
        assert calls == ["lights.a", "heating.a"]

    async def test_chain_ends_with_the_call(self, chain: Chain) -> None:
        """Once the outer call has returned, the action can be called again."""
        chain.action("a", "a")
        await chain.call("a")
        await chain.call("a")
        assert chain.calls == ["a", "a"]

    async def test_tasks_started_by_the_action_belong_to_the_chain(self, chain: Chain, bench: Bench) -> None:
        """A call made from a task the action started is still a call by that action."""
        errors: list[BaseException] = []

        async def spawning() -> None:
            async def later() -> None:
                try:
                    await bench.dispatcher.dispatch("auto", "spawning", spawning, mode=chain.mode)
                except ActionDroppedError as err:
                    errors.append(err)

            await asyncio.create_task(later())

        await bench.dispatcher.dispatch("auto", "spawning", spawning, mode=chain.mode)
        assert [error.reason for error in errors] == [REASON_REENTRANT]


class TestCallChains:
    """Which calls belong to a chain."""

    async def test_unrelated_callers_have_separate_chains(self, bench: Bench) -> None:
        """An action running for one caller does not make another caller's request re-entrant."""
        await bench.request("a", QUEUE)
        second = await bench.request("b", QUEUE)
        await bench.release("a")
        await bench.release("b")
        assert await second == "b done"

    async def test_queued_request_keeps_the_chain_of_its_requester(self, bench: Bench) -> None:
        """A queued request is started by another execution ending, yet runs in its own caller's chain."""
        errors: list[BaseException] = []
        results: list[Any] = []

        async def queued(label: str) -> str:
            await bench.gates[label].wait()
            if label == "from relay":
                try:
                    await bench.dispatcher.dispatch("auto", "relay", relay, mode=DROP)
                except ActionDroppedError as err:
                    errors.append(err)
            return label

        async def relay() -> None:
            results.append(
                await bench.dispatcher.dispatch("auto", "queued", queued, "from relay", mode=QUEUE)
            )

        plain = asyncio.create_task(bench.dispatcher.dispatch("auto", "queued", queued, "plain", mode=QUEUE))
        await bench.clock.settle()
        relaying = asyncio.create_task(bench.dispatcher.dispatch("auto", "relay", relay, mode=DROP))
        await bench.clock.settle()

        await bench.release("plain")
        await bench.release("from relay")
        await relaying
        assert await plain == "plain"
        assert results == ["from relay"]
        assert [error.reason for error in errors] == [REASON_REENTRANT]

    @pytest.mark.parametrize("mode", MODES)
    async def test_a_triggered_request_starts_a_new_chain(self, bench: Bench, mode: ActionMode) -> None:
        """A trigger firing is not a call: the action's mode decides, not the re-entrancy rule."""
        requests: list[asyncio.Task[Any]] = []

        async def loops(run: str) -> str:
            if run == "first":
                # What a trigger does when this action's own state change fires it
                requests.append(
                    asyncio.create_task(
                        bench.dispatcher.dispatch("auto", "loops", loops, "second", mode=mode, triggered=True)
                    )
                )
                await bench.gates["first"].wait()
            return run

        first = asyncio.create_task(bench.dispatcher.dispatch("auto", "loops", loops, "first", mode=mode))
        await bench.clock.settle()
        (request,) = requests

        if mode is DROP:
            error = await outcome(request)
            assert type(error) is ActionDroppedError and error.reason == "already executing"
            await bench.release("first")
            assert await first == "first"
        elif mode is QUEUE:
            assert not request.done()
            await bench.release("first")
            assert (await first, await request) == ("first", "second")
        else:
            assert type(await outcome(first)) is ActionCancelledError
            assert await request == "second"


class TestWaitIdle:
    """wait_idle completes when nothing is running or waiting."""

    async def test_idle_dispatcher_returns_at_once(self, bench: Bench) -> None:
        """Waiting on an idle dispatcher does not wait."""
        await bench.dispatcher.wait_idle()
        await bench.dispatcher.wait_idle("auto")
        assert bench.dispatcher.is_idle()

    async def test_waits_for_the_running_action(self, bench: Bench) -> None:
        """The wait ends when the running execution does."""
        await bench.request("a", DROP)
        waiter = asyncio.create_task(bench.dispatcher.wait_idle())
        await bench.clock.settle()
        assert not waiter.done()

        await bench.release("a")
        assert waiter.done()

    async def test_waits_for_queued_requests(self, bench: Bench) -> None:
        """Requests that are still waiting their turn keep the dispatcher busy."""
        await bench.request("a", QUEUE)
        await bench.request("b", QUEUE)
        waiter = asyncio.create_task(bench.dispatcher.wait_idle("auto"))

        await bench.release("a")
        assert not waiter.done()
        await bench.release("b")
        assert waiter.done()

    async def test_per_automation(self, bench: Bench) -> None:
        """Waiting for one automation ignores the actions of another."""
        await bench.request("a", DROP, automation="other")
        await bench.dispatcher.wait_idle("auto")
        assert bench.dispatcher.is_idle("auto")
        assert not bench.dispatcher.is_idle("other")

        waiter = asyncio.create_task(bench.dispatcher.wait_idle("other"))
        await bench.clock.settle()
        assert not waiter.done()
        await bench.release("a")
        assert waiter.done()

    async def test_idle_after_a_failed_action(self, bench: Bench) -> None:
        """An action that raises still leaves the dispatcher idle."""

        async def failing() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await bench.dispatcher.dispatch("auto", "failing", failing)
        await bench.dispatcher.wait_idle()

    async def test_waits_for_a_lifecycle_handler(self, bench: Bench) -> None:
        """A running @startup or @shutdown handler keeps its automation busy."""
        handler = asyncio.create_task(bench.dispatcher.run_handler("auto", "__startup__", bench.work, "h"))
        await bench.clock.settle()
        assert not bench.dispatcher.is_idle("auto")

        await bench.release("h")
        assert await handler == "h done"
        assert bench.dispatcher.is_idle("auto")


class TestRemoveQueued:
    """Removing the waiting requests of an automation."""

    async def test_callers_receive_action_cancelled_error(self, bench: Bench) -> None:
        """Each removed request ends with ActionCancelledError carrying the reason."""
        await bench.request("a", QUEUE)
        waiting = [await bench.request("b", QUEUE), await bench.request("c", QUEUE)]

        assert bench.dispatcher.remove_queued("auto", "automation stopped") == 2

        for task in waiting:
            error = await outcome(task)
            assert type(error) is ActionCancelledError
            assert (error.action_name, error.reason) == ("work", "automation stopped")
        assert bench.dispatcher.queued_count("auto", "work") == 0

    async def test_running_execution_is_left_alone(self, bench: Bench) -> None:
        """Only requests that have not started are removed."""
        running = await bench.request("a", QUEUE)
        await bench.request("b", QUEUE)
        bench.dispatcher.remove_queued("auto", "automation stopped")

        await bench.release("a")
        assert await running == "a done"
        assert bench.started == ["a"]
        assert bench.dispatcher.is_idle()

    async def test_only_the_named_automation(self, bench: Bench) -> None:
        """The queues of other automations are untouched."""
        await bench.request("a", QUEUE, automation="other")
        kept = await bench.request("b", QUEUE, automation="other")

        assert bench.dispatcher.remove_queued("auto", "automation stopped") == 0
        assert not kept.done()
        assert bench.dispatcher.remove_queued(None, "everything") == 1

    async def test_removal_wakes_wait_idle(self, bench: Bench) -> None:
        """Emptying a queue counts as progress towards idle."""
        await bench.request("a", QUEUE)
        await bench.request("b", QUEUE)
        waiter = asyncio.create_task(bench.dispatcher.wait_idle())
        await bench.release("a")
        assert not waiter.done()

        bench.dispatcher.remove_queued("auto", "automation stopped")
        # "b" had already started when "a" ended; nothing was queued any more
        await bench.release("b")
        assert waiter.done()


class TestCancelRunning:
    """Cancelling the running executions of an automation."""

    async def test_callers_receive_the_reason(self, bench: Bench) -> None:
        """A cancelled execution's caller gets ActionCancelledError with the reason given."""
        running = await bench.request("a", DROP)
        assert bench.dispatcher.cancel_running("auto", "automation stopped") == 1

        error = await outcome(running)
        assert type(error) is ActionCancelledError
        assert (error.action_name, error.reason) == ("work", "automation stopped")
        assert bench.ended == ["a"]

    async def test_only_the_named_automation(self, bench: Bench) -> None:
        """Executions of other automations keep running."""
        kept = await bench.request("a", DROP, automation="other")
        assert bench.dispatcher.cancel_running("auto", "automation stopped") == 0
        await bench.release("a")
        assert await kept == "a done"

    async def test_an_execution_is_cancelled_once(self, bench: Bench) -> None:
        """Cancelling again while the action cleans up does not interrupt the cleanup."""
        cleaned: list[str] = []

        async def careful() -> None:
            try:
                await bench.gates["run"].wait()
            finally:
                await bench.gates["cleanup"].wait()
                cleaned.append("done")

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "careful", careful))
        await bench.clock.settle()
        assert bench.dispatcher.cancel_running("auto", "first") == 1
        await bench.clock.settle()
        assert bench.dispatcher.cancel_running("auto", "second") == 0

        await bench.release("cleanup")
        assert cleaned == ["done"]
        assert (await outcome(running)).reason == "first"

    async def test_queued_request_runs_after_a_cancelled_execution(self, bench: Bench) -> None:
        """Cancelling the running execution lets the next queued request start."""
        await bench.request("a", QUEUE)
        queued = await bench.request("b", QUEUE)
        bench.dispatcher.cancel_running("auto", "cancelled by hand")
        await bench.clock.settle()

        assert bench.started == ["a", "b"]
        await bench.release("b")
        assert await queued == "b done"

    async def test_runs_in_current_task(self, bench: Bench) -> None:
        """The dispatcher can tell whether the current code runs as an action of an automation."""
        seen: list[tuple[bool, bool]] = []

        async def looking() -> None:
            seen.append(
                (
                    bench.dispatcher.runs_in_current_task("auto"),
                    bench.dispatcher.runs_in_current_task("other"),
                )
            )

        await bench.dispatcher.dispatch("auto", "looking", looking)
        assert seen == [(True, False)]
        assert not bench.dispatcher.runs_in_current_task("auto")


class TestRunHandler:
    """Lifecycle handlers go through the dispatcher but are not actions."""

    async def test_returns_the_result(self, bench: Bench) -> None:
        """The handler's return value is returned."""

        async def handler(value: int) -> int:
            return value * 2

        assert await bench.dispatcher.run_handler("auto", "__startup__", handler, 21) == 42
        assert bench.dispatcher.is_idle()

    async def test_exception_reaches_the_caller(self, bench: Bench) -> None:
        """The handler's own exception object is raised."""
        error = RuntimeError("cannot start")

        async def handler() -> None:
            raise error

        with pytest.raises(RuntimeError) as exc_info:
            await bench.dispatcher.run_handler("auto", "__startup__", handler)
        assert exc_info.value is error

    async def test_cancelled_with_its_caller(self, bench: Bench) -> None:
        """Unlike an action, a handler is cancelled when the one waiting for it is: its time limit."""
        waiting = asyncio.create_task(
            bench.clock.wait_for(bench.dispatcher.run_handler("auto", "__startup__", bench.work, "h"), 5)
        )
        await bench.clock.advance(seconds=5)

        assert type(await outcome(waiting)) is TimeoutError
        assert bench.ended == ["h"]
        assert bench.dispatcher.is_idle()

    async def test_two_handlers_at_once(self, bench: Bench) -> None:
        """Handlers have no execution mode: nothing is dropped."""
        first = asyncio.create_task(bench.dispatcher.run_handler("auto", "__startup__", bench.work, "a"))
        second = asyncio.create_task(bench.dispatcher.run_handler("auto", "__startup__", bench.work, "b"))
        await bench.clock.settle()
        assert bench.started == ["a", "b"]
        await bench.release("a")
        await bench.release("b")
        assert (await first, await second) == ("a done", "b done")

    async def test_handler_is_not_part_of_a_call_chain(self, bench: Bench) -> None:
        """An action called by a handler starts the chain; the handler itself is never re-entrant."""

        async def action() -> str:
            return "ran"

        async def handler() -> list[str]:
            return [
                await bench.dispatcher.dispatch("auto", "action", action),
                await bench.dispatcher.dispatch("auto", "action", action),
            ]

        assert await bench.dispatcher.run_handler("auto", "__startup__", handler) == ["ran", "ran"]

    async def test_cancel_running_includes_handlers(self, bench: Bench) -> None:
        """A handler still running when its automation is cleaned up is cancelled with the actions."""
        handler = asyncio.create_task(bench.dispatcher.run_handler("auto", "__shutdown__", bench.work, "h"))
        await bench.clock.settle()
        assert bench.dispatcher.cancel_running("auto", "giving up") == 1

        error = await outcome(handler)
        assert type(error) is ActionCancelledError and error.reason == "giving up"


class TestShutdown:
    """Shutting the dispatcher down."""

    async def test_cancels_running_and_removes_queued(self, bench: Bench) -> None:
        """Every pending caller receives ActionCancelledError, and no time passes."""
        running = await bench.request("a", QUEUE)
        queued = await bench.request("b", QUEUE)

        await bench.dispatcher.shutdown()

        for task in (running, queued):
            error = await outcome(task)
            assert type(error) is ActionCancelledError and error.reason == REASON_SHUTDOWN
        assert bench.started == ["a"]
        assert bench.clock.now() == DEFAULT_NOW
        assert bench.dispatcher.is_idle()
        assert bench.pool.active_count == 0

    async def test_new_requests_are_rejected(self, bench: Bench) -> None:
        """After shutdown no action starts."""
        assert not bench.dispatcher.is_shutting_down
        await bench.dispatcher.shutdown()
        assert bench.dispatcher.is_shutting_down

        with pytest.raises(ActionCancelledError) as exc_info:
            await bench.dispatcher.dispatch("auto", "work", bench.work, "a")
        assert exc_info.value.reason == REASON_SHUTDOWN
        assert bench.started == []

    async def test_gives_up_waiting_for_an_action_that_refuses_to_stop(
        self, bench: Bench, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Shutdown waits a bounded time on the clock for cancelled actions."""
        release = asyncio.Event()

        async def stubborn() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                raise

        running = asyncio.create_task(bench.dispatcher.dispatch("auto", "stubborn", stubborn))
        await bench.clock.settle()

        shutdown = asyncio.create_task(bench.dispatcher.shutdown())
        await bench.clock.advance(seconds=SHUTDOWN_WAIT_SECONDS - 0.1)
        assert not shutdown.done()

        await bench.clock.advance(seconds=0.1)
        await shutdown
        assert "1 action(s) still running" in caplog.text

        release.set()
        assert type(await outcome(running)) is ActionCancelledError


# --- Through loaded automations --------------------------------------------------------------

MODES_SOURCE = """
from haanim import ActionMode, ActionDroppedError, QueueFullError, ActionCancelledError
from haanim import action, on_state, sleep, haa

@action
async def dropping(event):
    log.append(f"dropping {event.data['n']}")
    await sleep(10)
    return event.data["n"]

@action(name="queue", aliases=["line"], execution_mode=ActionMode.QUEUE)
async def queueing(event):
    log.append(f"queueing {event.data['n']}")
    await sleep(10)
    return event.data["n"]

@action(execution_mode=ActionMode.CANCEL)
async def latest(event):
    log.append(f"latest {event.data['n']}")
    await sleep(10)
    return event.data["n"]

@action
async def try_all(event):
    outcomes = []
    for name in ("dropping", "queue", "latest"):
        try:
            outcomes.append(await haa.call(name, n=99))
        except (ActionDroppedError, QueueFullError, ActionCancelledError) as err:
            outcomes.append(type(err).__name__)
    return outcomes
"""


class TestModesOfAutomationActions:
    """The mode given to @action decides what callers of the automation get."""

    async def test_drop_is_the_default(self, world: World) -> None:
        """An action without a mode drops a second request with ActionDroppedError."""
        automation = await world.started("lights", MODES_SOURCE)
        first = asyncio.create_task(automation.call_action("dropping", {"n": 1}))
        await world.clock.settle()

        with pytest.raises(ActionDroppedError) as exc_info:
            await automation.call_action("dropping", {"n": 2})
        assert (exc_info.value.automation_id, exc_info.value.action_name) == ("lights", "dropping")

        await world.clock.advance(seconds=10)
        assert await first == 1
        assert world.log == ["dropping 1"]

    async def test_queue(self, world: World) -> None:
        """Requests for a QUEUE action run one after the other and each returns its own result."""
        automation = await world.started("lights", MODES_SOURCE)
        calls = [asyncio.create_task(automation.call_action("queue", {"n": n})) for n in (1, 2, 3)]
        await world.clock.settle()
        assert world.log == ["queueing 1"]

        await world.clock.advance(seconds=10)
        assert world.log == ["queueing 1", "queueing 2"]
        await world.clock.advance(seconds=20)
        assert [await call for call in calls] == [1, 2, 3]

    async def test_cancel(self, world: World) -> None:
        """A new request for a CANCEL action replaces the running one."""
        automation = await world.started("lights", MODES_SOURCE)
        first = asyncio.create_task(automation.call_action("latest", {"n": 1}))
        await world.clock.advance(seconds=4)
        second = asyncio.create_task(automation.call_action("latest", {"n": 2}))
        await world.clock.settle()

        with pytest.raises(ActionCancelledError):
            await first
        await world.clock.advance(seconds=10)
        assert await second == 2
        assert world.log == ["latest 1", "latest 2"]

    async def test_an_alias_is_the_same_action(self, world: World) -> None:
        """Requests by name and by alias share one queue."""
        automation = await world.started("lights", MODES_SOURCE)
        by_name = asyncio.create_task(automation.call_action("queue", {"n": 1}))
        by_alias = asyncio.create_task(automation.call_action("line", {"n": 2}))
        await world.clock.settle()

        assert world.log == ["queueing 1"]
        assert world.dispatcher.queued_count("lights", "queue") == 1
        await world.clock.advance(seconds=20)
        assert (await by_name, await by_alias) == (1, 2)

    async def test_errors_can_be_caught_by_the_calling_automation(self, world: World) -> None:
        """Automation code catches the errors by the names it imports from haanim."""
        automation = await world.started("lights", MODES_SOURCE)
        running = [
            asyncio.create_task(automation.call_action(name, {"n": 1}))
            for name in ("dropping", "queue", "latest")
        ]
        await world.clock.settle()

        # dropping: dropped at once; queue: waits ten seconds for its turn, then runs for ten
        attempt = asyncio.create_task(automation.call_action("try_all"))
        await world.clock.advance(seconds=30)

        assert await attempt == ["ActionDroppedError", 99, 99]
        assert [await call for call in running] == [1, 1, 1]


REENTRANT_SOURCE = """
from haanim import ActionMode, ActionDroppedError, action, haa

async def attempt(call):
    try:
        return await call
    except ActionDroppedError as err:
        return f"dropped: {err.reason}"

@action(execution_mode=ActionMode.%(mode)s, aliases=["me"])
async def direct(event):
    return await attempt(haa.call("direct"))

@action(execution_mode=ActionMode.%(mode)s)
async def by_alias(event):
    return await attempt(haa.call("me"))

@action(execution_mode=ActionMode.%(mode)s)
async def ping(event):
    return await attempt(haa.automation("heating").call("pong"))

@action(execution_mode=ActionMode.%(mode)s)
async def through_own(event):
    return await attempt(haa.call("relay"))

@action(execution_mode=ActionMode.%(mode)s)
async def relay(event):
    return await attempt(haa.call("through_own"))
"""

PONG_SOURCE = """
from haanim import ActionMode, ActionDroppedError, action, haa

@action(execution_mode=ActionMode.%(mode)s)
async def pong(event):
    try:
        return await haa.automation("lights").call("ping")
    except ActionDroppedError as err:
        return f"dropped: {err.reason}"
"""


@pytest.mark.parametrize("mode", ["DROP", "QUEUE", "CANCEL"])
class TestReentrantAutomationCalls:
    """Re-entrant calls between real automations, in each mode."""

    async def test_direct(self, world: World, mode: str) -> None:
        """An action that calls itself gets ActionDroppedError and then finishes."""
        automation = await world.started("lights", REENTRANT_SOURCE % {"mode": mode})
        assert await automation.call_action("direct") == f"dropped: {REASON_REENTRANT}"
        assert world.dispatcher.is_idle()

    async def test_by_alias(self, world: World, mode: str) -> None:
        """Calling the action by one of its aliases is still calling the action."""
        automation = await world.started("lights", REENTRANT_SOURCE % {"mode": mode})
        assert await automation.call_action("me") == f"dropped: {REASON_REENTRANT}"

    async def test_through_another_action(self, world: World, mode: str) -> None:
        """A call that comes back through another action of the automation is rejected."""
        automation = await world.started("lights", REENTRANT_SOURCE % {"mode": mode})
        assert await automation.call_action("through_own") == f"dropped: {REASON_REENTRANT}"

    async def test_through_another_automation(self, world: World, mode: str) -> None:
        """A call that comes back through another automation is rejected."""
        lights = await world.started("lights", REENTRANT_SOURCE % {"mode": mode})
        await world.started("heating", PONG_SOURCE % {"mode": mode})

        assert await lights.call_action("ping") == f"dropped: {REASON_REENTRANT}"
        assert world.dispatcher.is_idle()

    async def test_the_action_works_again_afterwards(self, world: World, mode: str) -> None:
        """A rejected re-entrant call leaves nothing behind."""
        automation = await world.started("lights", REENTRANT_SOURCE % {"mode": mode})
        for _ in range(2):
            assert await automation.call_action("direct") == f"dropped: {REASON_REENTRANT}"


STOP_SOURCE = """
from haanim import ActionMode, action, shutdown, sleep

@action(execution_mode=ActionMode.QUEUE)
async def work(event):
    log.append(f"work {event.data['n']} started")
    try:
        await sleep(event.data.get("seconds", 60))
        log.append(f"work {event.data['n']} finished")
        return event.data["n"]
    except BaseException as err:
        log.append(f"work {event.data['n']} {type(err).__name__}")
        raise

@shutdown
def on_stop():
    log.append("shutdown")
"""


class TestStopRemovesQueuedRequests:
    """Stopping an automation: "Queued action requests are removed"."""

    async def test_queued_callers_receive_action_cancelled_error(self, world: World) -> None:
        """Queued requests end at once with ActionCancelledError; they never start."""
        automation = await world.started("lights", STOP_SOURCE)
        calls = [asyncio.create_task(automation.call_action("work", {"n": n})) for n in (1, 2, 3)]
        await world.clock.settle()

        stopping = asyncio.create_task(automation.stop())
        await world.clock.settle()

        # Before the grace period is over: the queue is empty, the running action still runs
        for call in calls[1:]:
            error = await outcome(call)
            assert type(error) is ActionCancelledError
            assert (error.action_name, error.reason) == ("work", REASON_STOPPED)
        assert not calls[0].done()
        assert world.log == ["work 1 started"]

        await world.clock.advance(seconds=1)
        await stopping
        assert type(await outcome(calls[0])) is ActionCancelledError
        assert world.log == ["work 1 started", "work 1 CancelledError", "shutdown"]
        assert automation.state is AutomationState.OFF

    async def test_running_action_may_finish_within_the_grace_period(self, world: World) -> None:
        """Removing the queue does not shorten the grace period of the action that is running."""
        world.settings = LifecycleSettings(stop_grace_period=5)
        automation = await world.started("lights", STOP_SOURCE)
        running = asyncio.create_task(automation.call_action("work", {"n": 1, "seconds": 3}))
        queued = asyncio.create_task(automation.call_action("work", {"n": 2, "seconds": 3}))
        await world.clock.settle()

        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=3)
        await stopping

        assert await running == 1
        assert type(await outcome(queued)) is ActionCancelledError
        assert world.log == ["work 1 started", "work 1 finished", "shutdown"]

    async def test_a_restarted_automation_starts_with_empty_queues(self, world: World) -> None:
        """Nothing of the old run is left in the dispatcher."""
        automation = await world.started("lights", STOP_SOURCE)
        calls = [asyncio.create_task(automation.call_action("work", {"n": n})) for n in (1, 2)]
        await world.clock.settle()
        stopping = asyncio.create_task(automation.stop())
        await world.clock.advance(seconds=1)
        await stopping
        await asyncio.gather(*calls, return_exceptions=True)
        assert world.dispatcher.is_idle("lights")

        assert await automation.start()
        world.expose(automation)
        again = asyncio.create_task(automation.call_action("work", {"n": 3, "seconds": 1}))
        await world.clock.advance(seconds=1)
        assert await again == 3


FAILING_START_SOURCE = """
from haanim import ActionMode, action, startup, sleep, haa
import asyncio

started = []

@action(execution_mode=ActionMode.QUEUE)
async def work(event):
    started.append(event.data["n"])
    await sleep(60)

@startup
async def on_start():
    asyncio.ensure_future(haa.call("work", n=1))
    asyncio.ensure_future(haa.call("work", n=2))
    await sleep(0)
    raise RuntimeError("cannot start")
"""


class TestTriggeredActions:
    """A trigger function is an action: its execution mode applies when a trigger fires it."""

    @staticmethod
    def manager(bench: Bench) -> TriggerManager:
        """A trigger manager that requests its actions through the bench's dispatcher."""
        states = FakeStateProvider(bench.clock)
        return TriggerManager(make_host(clock=bench.clock, states=states), bench.dispatcher)

    @staticmethod
    def definition(func: Callable[..., Any], mode: ActionMode) -> TriggerDefinition:
        """A state trigger on an action named differently from its function."""
        return TriggerDefinition(
            trigger_type=TRIGGER_STATE,
            trigger_expr="sensor.door == 'on'",
            func_name="on_door",
            func=func,
            automation_id="auto",
            action_name="door",
            execution_mode=mode,
        )

    async def fire_twice(self, bench: Bench, mode: ActionMode) -> list[asyncio.Task[None]]:
        """Fire the same trigger twice while its action is still running."""
        counter = iter("ab")

        async def on_door() -> str:
            return await bench.work(next(counter))

        manager = self.manager(bench)
        trigger_id = await manager.register_trigger(self.definition(on_door, mode))
        fires = []
        for _ in range(2):
            # pylint: disable-next=protected-access
            fires.append(asyncio.create_task(manager._execute_trigger(trigger_id)))
            await bench.clock.settle()
        return fires

    async def test_drop(self, bench: Bench) -> None:
        """With DROP the second fire is skipped."""
        fires = await self.fire_twice(bench, DROP)
        assert bench.started == ["a"]
        assert fires[1].done()
        await bench.release("a")
        await fires[0]
        assert bench.dispatcher.is_idle()

    async def test_queue(self, bench: Bench) -> None:
        """With QUEUE the second fire runs after the first."""
        fires = await self.fire_twice(bench, QUEUE)
        assert bench.started == ["a"]
        await bench.release("a")
        assert bench.started == ["a", "b"]
        await bench.release("b")
        await asyncio.gather(*fires)

    async def test_cancel(self, bench: Bench) -> None:
        """With CANCEL the second fire replaces the first."""
        fires = await self.fire_twice(bench, CANCEL)
        assert (bench.started, bench.ended) == (["a", "b"], ["a"])
        await bench.release("b")
        await asyncio.gather(*fires)

    async def test_the_action_is_known_by_its_action_name(self, bench: Bench) -> None:
        """A trigger firing and a direct call of the same action meet in the dispatcher."""
        fires = await self.fire_twice(bench, QUEUE)
        assert bench.dispatcher.is_running("auto", "door")
        assert bench.dispatcher.queued_count("auto", "door") == 1
        assert not bench.dispatcher.is_running("auto", "on_door")
        await bench.release("a")
        await bench.release("b")
        await asyncio.gather(*fires)

    async def test_trigger_definitions_carry_the_actions_name_and_mode(self, world: World) -> None:
        """What @action says about a trigger function reaches its triggers."""
        automation = await world.started(
            "lights",
            "from haanim import ActionMode, action, on_state\n\n"
            "@on_state(\"sensor.a == 'on'\")\n@action(name='door', execution_mode=ActionMode.QUEUE)\n"
            "def on_door():\n    pass\n\n"
            "@on_state(\"sensor.b == 'on'\")\ndef plain():\n    pass\n",
        )
        triggers = {trigger.func_name: trigger for trigger in automation.context.get_triggers()}
        assert (triggers["on_door"].action_name, triggers["on_door"].execution_mode) == ("door", QUEUE)
        assert (triggers["plain"].action_name, triggers["plain"].execution_mode) == ("plain", DROP)


class TestFailedStart:
    """An automation that fails to start leaves no requests behind."""

    async def test_requests_made_by_startup_are_removed(self, world: World) -> None:
        """Running and queued requests of a failed start are cancelled and removed."""
        automation = world.add("lights", FAILING_START_SOURCE)
        assert await automation.load()
        assert not await automation.start()
        await world.clock.settle()

        assert automation.state is AutomationState.ERROR
        assert world.dispatcher.is_idle("lights")
        assert world.pool.active_count == 0
