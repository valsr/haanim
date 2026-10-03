"""Tests for checkpoints and single-loop execution of automation code."""

from __future__ import annotations

import ast
import asyncio
import logging
import threading
from collections.abc import Coroutine
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.action_pool import ActionWorkerPool
from haanim.engine.ast_evaluator import DEFAULT_CHECKPOINT_INTERVAL, AstEvaluator
from haanim.engine.automation_status import AutomationStatusManager
from haanim.engine.callables import as_coroutine_function
from haanim.engine.errors import ActionCancelledError
from haanim.engine.eval_function import CHECKPOINT, NATIVE_CALL_WARNING_SECONDS, run_to_completion
from haanim.testing import FakeClock, LocalFileSystem, make_host
from tests.engine.helpers import automation_file, make_context

ENGINE_DIR = Path(__file__).parents[2] / "src" / "haanim" / "engine"


class SteppingClock:
    """A clock whose time moves by a fixed step every time it is read.

    Stands in for the passage of time inside code that never yields, which a
    FakeClock cannot express because it only moves when a test advances it.
    """

    def __init__(self, step: float) -> None:
        self.step = timedelta(seconds=step)
        self.current = datetime(2025, 1, 6, 12, 0, tzinfo=timezone.utc)
        self.reads = 0

    def now(self) -> datetime:
        """Return the time, then move it on."""
        self.reads += 1
        self.current += self.step
        return self.current


async def load(source: str, **kwargs: Any) -> dict[str, Any]:
    """Run a source in the interpreter and return its module-level names."""
    evaluator = AstEvaluator(name="auto", **kwargs)
    evaluator.parse(source, filename="main.py")
    return await evaluator.execute()


def count_yields(coro: Coroutine[Any, Any, Any]) -> tuple[int, Any]:
    """Drive a coroutine by hand and return how often it yielded, and its result."""
    yields = 0
    try:
        while True:
            assert coro.send(None) is None
            yields += 1
    except StopIteration as stop:
        return yields, stop.value


async def yields_of(source: str, call: str = "run", *args: Any, **kwargs: Any) -> tuple[int, Any]:
    """Load a source and count the checkpoints one call of a function of it passes."""
    symbols = await load(source, **kwargs)
    return count_yields(as_coroutine_function(symbols[call])(*args))


class TestWhereCheckpointsAre:
    """The interpreter yields at every loop iteration and at every call of an automation function."""

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ("def run():\n    x = 1\n    y = x + 1\n    return y\n", 1),
            ("def run():\n    for i in range(5):\n        pass\n", 1 + 5),
            ("def run():\n    i = 0\n    while i < 4:\n        i += 1\n", 1 + 4),
            ("def run():\n    return [i for i in range(3)]\n", 1 + 3),
            ("def run():\n    return {i for i in range(3)}\n", 1 + 3),
            ("def run():\n    return {i: i for i in range(3)}\n", 1 + 3),
            ("def run():\n    return [(i, j) for i in range(2) for j in range(3)]\n", 1 + 2 + 6),
            ("def helper():\n    return 1\ndef run():\n    return helper() + helper()\n", 1 + 2),
            ("def run():\n    f = lambda: 1\n    return f() + f() + f()\n", 1 + 3),
            (
                "def fact(n):\n    return 1 if n <= 1 else n * fact(n - 1)\ndef run():\n    return fact(5)\n",
                1 + 5,
            ),
            ("def run():\n    for i in range(3):\n        for j in range(2):\n            pass\n", 1 + 3 + 6),
            ("def run():\n    for i in range(10):\n        if i == 2:\n            break\n", 1 + 3),
            ("def run():\n    return len([1, 2]) + abs(-1)\n", 1),
            (
                "class A:\n    def m(self):\n        return 1\ndef run():\n    a = A()\n    return a.m() + a.m()\n",
                1 + 2,
            ),
        ],
        ids=[
            "straight-line code",
            "for",
            "while",
            "list comprehension",
            "set comprehension",
            "dict comprehension",
            "nested comprehension",
            "calls",
            "lambda calls",
            "recursion",
            "nested loops",
            "break",
            "native calls",
            "method calls",
        ],
    )
    async def test_number_of_checkpoints(self, source: str, expected: int) -> None:
        """One checkpoint for the call itself, plus one per iteration and per call inside."""
        yields, _ = await yields_of(source)

        assert yields == expected

    async def test_async_def_has_the_same_checkpoints(self) -> None:
        """An async def is suspended at the same places as a def."""
        sync_yields, _ = await yields_of("def run():\n    for i in range(5):\n        pass\n")
        async_yields, _ = await yields_of("async def run():\n    for i in range(5):\n        pass\n")

        assert sync_yields == async_yields == 6

    async def test_result_is_unaffected(self) -> None:
        """Checkpoints do not change what the code computes."""
        _, result = await yields_of("def run(n):\n    return sum([i * i for i in range(n)])\n", "run", 10)

        assert result == 285

    @pytest.mark.parametrize(("interval", "expected"), [(1, 101), (10, 10), (100, 1), (1000, 0)])
    async def test_checkpoint_interval(self, interval: int, expected: int) -> None:
        """With an interval of N the interpreter yields at every Nth checkpoint."""
        source = "def run():\n    for i in range(100):\n        pass\n"

        yields, _ = await yields_of(source, checkpoint_interval=interval)

        assert yields == expected

    def test_default_is_every_checkpoint(self) -> None:
        """By default every checkpoint yields, as the design says."""
        assert DEFAULT_CHECKPOINT_INTERVAL == 1

    async def test_checkpoint_yields_once(self) -> None:
        """A checkpoint gives the event loop exactly one turn."""
        order: list[str] = []

        async def other() -> None:
            order.append("other")

        task = asyncio.create_task(other())
        order.append("before")
        await CHECKPOINT
        order.append("after")
        await task

        assert order == ["before", "other", "after"]


class TestInterleaving:
    """Actions interleave at checkpoints and awaits, and nowhere else."""

    SOURCE = (
        "log = []\n"
        "\n"
        "def work(name, n):\n"
        "    for i in range(n):\n"
        "        log.append((name, i))\n"
        "\n"
        "async def async_work(name, n):\n"
        "    for i in range(n):\n"
        "        log.append((name, i))\n"
        "\n"
        "def atomic(name):\n"
        "    log.append((name, 'start'))\n"
        "    value = len(log)\n"
        "    value = value * 2 + 1\n"
        "    log.append((name, 'middle'))\n"
        "    text = str(value) + name\n"
        "    log.append((name, 'end'))\n"
    )

    @pytest.mark.parametrize("function", ["work", "async_work"])
    async def test_two_actions_alternate_at_every_iteration(self, function: str) -> None:
        """A def and an async def both give way at each loop iteration."""
        symbols = await load(self.SOURCE)
        run = as_coroutine_function(symbols[function])

        await asyncio.gather(run("a", 3), run("b", 3))

        assert symbols["log"] == [("a", 0), ("b", 0), ("a", 1), ("b", 1), ("a", 2), ("b", 2)]

    async def test_def_and_async_def_interleave_with_each_other(self) -> None:
        """A def action behaves like an async def action."""
        symbols = await load(self.SOURCE)

        await asyncio.gather(
            as_coroutine_function(symbols["work"])("def", 2),
            as_coroutine_function(symbols["async_work"])("async", 2),
        )

        assert symbols["log"] == [("def", 0), ("async", 0), ("def", 1), ("async", 1)]

    async def test_code_without_a_checkpoint_is_atomic(self) -> None:
        """Statements with no loop, call or await between them are never interleaved."""
        symbols = await load(self.SOURCE)
        run = as_coroutine_function(symbols["atomic"])

        await asyncio.gather(run("a"), run("b"), run("c"))

        assert symbols["log"] == [(name, step) for name in "abc" for step in ("start", "middle", "end")]

    async def test_no_interleaving_between_checkpoints_of_an_interval(self) -> None:
        """With an interval of N, N iterations run without giving way."""
        symbols = await load(self.SOURCE, checkpoint_interval=4)
        run = as_coroutine_function(symbols["work"])

        await asyncio.gather(run("a", 6), run("b", 6))

        names = "".join(name for name, _ in symbols["log"])
        assert sorted(names) == sorted("a" * 6 + "b" * 6)
        assert names != "ab" * 6
        assert "aa" in names and "bb" in names

    async def test_function_called_by_python_is_atomic(self) -> None:
        """A def that Python itself calls runs to completion without giving way."""
        symbols = await load(
            "log = []\n"
            "def key(v):\n"
            "    for i in range(3):\n"
            "        log.append(('key', v, i))\n"
            "    return v\n"
            "async def sorting():\n"
            "    return sorted([2, 1], key=key)\n"
            "async def other():\n"
            "    for i in range(3):\n"
            "        log.append(('other', i))\n"
        )

        result, _ = await asyncio.gather(symbols["sorting"](), symbols["other"]())

        assert result == [1, 2]
        keys = [index for index, entry in enumerate(symbols["log"]) if entry[0] == "key"]
        assert keys == list(range(keys[0], keys[0] + 6))

    async def test_long_loop_does_not_starve_another_task(self) -> None:
        """While an automation loops, other work on the event loop keeps running."""
        symbols = await load(
            "def run(n):\n    total = 0\n    for i in range(n):\n        total += i\n    return total\n"
        )
        turns = 0

        async def heartbeat() -> None:
            nonlocal turns
            while True:
                turns += 1
                await asyncio.sleep(0)

        beat = asyncio.create_task(heartbeat())
        result = await as_coroutine_function(symbols["run"])(200)
        beat.cancel()

        assert result == 19900
        assert turns >= 200


class TestCancellation:
    """A pending cancellation or timeout is delivered at the next checkpoint."""

    @pytest.mark.parametrize(
        "source",
        [
            "def run():\n    while True:\n        pass\n",
            "async def run():\n    while True:\n        pass\n",
            "def run():\n    def again():\n        return again()\n    return again()\n",
            "def spin():\n    while True:\n        pass\ndef run():\n    spin()\n",
        ],
        ids=["def loop", "async def loop", "endless recursion", "loop in a called function"],
    )
    async def test_endless_code_is_cancellable(self, source: str) -> None:
        """Code that never awaits and never ends can be cancelled, and does not block other work."""
        symbols = await load(source)
        task = asyncio.create_task(as_coroutine_function(symbols["run"])())
        progress: list[int] = []

        for step in range(5):
            await asyncio.sleep(0)
            progress.append(step)

        assert progress == [0, 1, 2, 3, 4]
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    async def test_endless_action_does_not_block_another_action(self, tmp_path: Path) -> None:
        """While one action loops forever, another action of the automation runs and returns."""
        path = automation_file(tmp_path, "auto")
        path.write_text(
            "from haanim import action\n"
            "@action\ndef forever():\n    while True:\n        pass\n\n@action\ndef quick():\n    return 'done'\n",
            encoding="utf-8",
        )
        context = make_context(str(path))
        await context.load()
        endless = asyncio.create_task(context.run_action("forever"))
        await asyncio.sleep(0)

        assert await context.run_action("quick") == "done"
        assert not endless.done()

        endless.cancel()
        with pytest.raises(asyncio.CancelledError):
            await endless

    async def test_timeout_is_delivered(self) -> None:
        """A timeout on the clock ends an endless loop at its next checkpoint."""
        clock = FakeClock()
        symbols = await load("steps = []\ndef run():\n    while True:\n        steps.append(1)\n")
        waiting = asyncio.create_task(clock.wait_for(as_coroutine_function(symbols["run"])(), timeout=5))

        await clock.advance(seconds=4)
        assert not waiting.done()
        running = len(symbols["steps"])
        assert running > 0

        await clock.advance(seconds=1)
        with pytest.raises(TimeoutError):
            await waiting
        stopped = len(symbols["steps"])
        await clock.settle()
        assert len(symbols["steps"]) == stopped > running

    async def test_cancellation_runs_finally_and_can_be_caught(self) -> None:
        """Cancellation arrives as CancelledError inside the automation's code."""
        symbols = await load(
            "import asyncio\n"
            "log = []\n"
            "def run():\n"
            "    try:\n"
            "        while True:\n"
            "            pass\n"
            "    except asyncio.CancelledError:\n"
            "        log.append('cancelled')\n"
            "        raise\n"
            "    finally:\n"
            "        log.append('finally')\n"
        )
        task = asyncio.create_task(as_coroutine_function(symbols["run"])())
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert symbols["log"] == ["cancelled", "finally"]

    async def test_pool_cancels_an_endless_def_action(self) -> None:
        """The pool can cancel a def action that loops forever."""
        clock = FakeClock()
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock)
        symbols = await load(
            "started = []\ndef forever():\n    started.append(1)\n    while True:\n        pass\n"
        )
        submitted = asyncio.create_task(pool.submit_action("auto", "forever", symbols["forever"]))
        await clock.settle()
        assert symbols["started"] == [1]
        assert len(pool.get_active_actions("auto")) == 1

        assert await pool.cancel_automation_actions("auto") == 1
        with pytest.raises(ActionCancelledError):
            await submitted

        assert pool.get_active_actions("auto") == []


class TestSingleLoop:
    """All automation code runs on the event loop; nothing is handed to a thread."""

    FORBIDDEN = {"run_in_executor", "async_add_executor_job", "to_thread", "ThreadPoolExecutor"}
    # Modules that only name these, to disable them for automations.
    NAMING_ONLY = {"guards.py"}

    @pytest.mark.parametrize("path", sorted(ENGINE_DIR.rglob("*.py")), ids=lambda path: path.name)
    def test_engine_does_not_use_executors(self, path: Path) -> None:
        """No engine module refers to an executor."""
        if path.name in self.NAMING_ONLY:
            return
        tree = ast.parse(path.read_text(encoding="utf-8"))
        used = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Attribute, ast.Name))
        }

        assert not used & self.FORBIDDEN

    @pytest.mark.parametrize("definition", ["def", "async def"])
    async def test_action_runs_on_the_event_loop_thread(self, tmp_path: Path, definition: str) -> None:
        """Through the context, a def and an async def action both run on the calling thread."""
        threads: list[int] = []
        path = automation_file(tmp_path, "auto")
        path.write_text(
            "from haanim import action\n" f"@action\n{definition} where():\n    return record()\n",
            encoding="utf-8",
        )
        context = make_context(str(path), host=make_host(files=LocalFileSystem()))
        context.set_symbol("record", lambda: threads.append(threading.get_ident()))
        await context.load()

        await context.run_action("where")
        await context.run_function("where")

        assert threads == [threading.get_ident()] * 2

    async def test_pool_runs_a_native_sync_function_on_the_loop(self) -> None:
        """The pool calls a plain Python function directly, not in a thread."""
        clock = FakeClock()
        pool = ActionWorkerPool(status_manager=AutomationStatusManager(), clock=clock)

        assert await pool.submit_action("auto", "where", threading.get_ident) == threading.get_ident()


class TestBlockingWarning:
    """A function called from outside the interpreter that runs long is reported."""

    SOURCE = (
        "def slow(n):\n"
        "    for i in range(n):\n"
        "        pass\n"
        "    return n\n"
        "\n"
        "async def via_sorted(n):\n"
        "    return sorted([n], key=slow)\n"
    )

    async def test_warns_once_after_one_second(self, caplog: pytest.LogCaptureFixture) -> None:
        """One warning names the file, line, function and automation."""
        clock = SteppingClock(step=0.3)
        symbols = await load(self.SOURCE, clock=clock)

        with caplog.at_level(logging.WARNING):
            assert symbols["slow"](20) == 20

        warnings = [
            record.getMessage() for record in caplog.records if "without yielding" in record.getMessage()
        ]
        assert len(warnings) == 1
        assert warnings[0].startswith(
            "main.py:1: function 'slow' of automation 'auto' has been running for more than 1 second"
        )
        assert NATIVE_CALL_WARNING_SECONDS == 1.0

    async def test_no_warning_for_a_short_call(self, caplog: pytest.LogCaptureFixture) -> None:
        """A call that stays under a second is not reported."""
        clock = SteppingClock(step=0.3)
        symbols = await load(self.SOURCE, clock=clock)

        with caplog.at_level(logging.WARNING):
            symbols["slow"](3)

        assert "without yielding" not in caplog.text

    async def test_each_call_is_timed_separately(self, caplog: pytest.LogCaptureFixture) -> None:
        """Several short calls do not add up to a warning; each long call warns once."""
        clock = SteppingClock(step=0.3)
        symbols = await load(self.SOURCE, clock=clock)

        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                symbols["slow"](2)
            assert "without yielding" not in caplog.text
            symbols["slow"](20)
            symbols["slow"](20)

        assert caplog.text.count("without yielding") == 2

    async def test_warns_when_called_through_a_builtin(self, caplog: pytest.LogCaptureFixture) -> None:
        """The usual way it happens: Python calls the function as a callback."""
        clock = SteppingClock(step=0.3)
        symbols = await load(self.SOURCE, clock=clock)

        with caplog.at_level(logging.WARNING):
            assert await symbols["via_sorted"](20) == [20]

        assert caplog.text.count("function 'slow' of automation 'auto'") == 1

    async def test_no_warning_when_the_interpreter_runs_it(self, caplog: pytest.LogCaptureFixture) -> None:
        """Run on the event loop the same function yields, so there is nothing to report."""
        clock = SteppingClock(step=0.3)
        symbols = await load(self.SOURCE, clock=clock)

        with caplog.at_level(logging.WARNING):
            assert await as_coroutine_function(symbols["slow"])(20) == 20

        assert "without yielding" not in caplog.text
        assert clock.reads == 0

    async def test_no_warning_without_a_clock(self, caplog: pytest.LogCaptureFixture) -> None:
        """An evaluator without a clock cannot time calls and stays silent."""
        symbols = await load(self.SOURCE)

        with caplog.at_level(logging.WARNING):
            assert symbols["slow"](20) == 20

        assert "without yielding" not in caplog.text

    async def test_loaded_automation_uses_the_host_clock(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An automation loaded through the context is timed with the host's clock."""
        clock = SteppingClock(step=0.6)
        host = make_host(files=LocalFileSystem())
        object.__setattr__(host.clock, "now", clock.now)
        path = automation_file(tmp_path, "lights")
        path.write_text(
            "from haanim import action\n"
            "def slow(v):\n    for i in range(10):\n        pass\n    return v\n\n"
            "@action\nasync def order():\n    return sorted([2, 1], key=slow)\n",
            encoding="utf-8",
        )
        context = make_context(str(path), host=host)
        await context.load()

        with caplog.at_level(logging.WARNING):
            assert await context.run_action("order") == [1, 2]

        assert "main.py:2: function 'slow' of automation 'lights'" in caplog.text

    def test_run_to_completion_reports_each_checkpoint(self) -> None:
        """The driver calls back once per skipped checkpoint."""
        seen: list[int] = []

        async def three() -> str:
            for _ in range(3):
                await CHECKPOINT
            return "done"

        assert run_to_completion(three(), "three", lambda: seen.append(1)) == "done"
        assert len(seen) == 3
