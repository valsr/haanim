"""Tests for async generators in automations: yield in async def, async for, async comprehensions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.errors import ActionTimeOutError
from haanim.testing import AutomationHarness

HELPERS = """
from haanim import action, haa

log = []

def note(text):
    log.append(text)

async def count_up_async(n):
    i = 0
    while i < n:
        yield i
        i += 1

@action
def logged(event):
    return log

@action
def other(event):
    return "other ran"
"""


def write(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "agens"
    folder.mkdir(exist_ok=True)
    (folder / "main.py").write_text(HELPERS + body)
    return folder


async def run(tmp_path: Path, body: str, action: str = "go", **harness: Any) -> Any:
    async with AutomationHarness(write(tmp_path, body), **harness) as automation:
        return await automation.call(action)


async def load_error(tmp_path: Path, body: str) -> str | None:
    async with AutomationHarness(write(tmp_path, body), start=False) as automation:
        assert not await automation.load()
        return automation.error


# --- Async generator functions ------------------------------------------------------


async def test_anext_and_exhaustion(tmp_path: Path) -> None:
    body = """
@action
async def go(event):
    ag = count_up_async(2)
    out = [await anext(ag), await anext(ag)]
    try:
        await anext(ag)
    except StopAsyncIteration:
        out.append("stopped")
    out.append(await anext(ag, "done"))
    return out
"""
    assert await run(tmp_path, body) == [0, 1, "stopped", "done"]


async def test_asend(tmp_path: Path) -> None:
    body = """
async def echo():
    received = []
    while True:
        value = yield len(received)
        received.append(value)

@action
async def go(event):
    ag = echo()
    return [await ag.asend(None), await ag.asend("x"), await ag.asend("y")]
"""
    assert await run(tmp_path, body) == [0, 1, 2]


async def test_athrow_caught_at_the_yield(tmp_path: Path) -> None:
    body = """
async def careful():
    while True:
        try:
            yield "ready"
        except ValueError:
            yield "caught"

@action
async def go(event):
    ag = careful()
    await anext(ag)
    return await ag.athrow(ValueError("x"))
"""
    assert await run(tmp_path, body) == "caught"


async def test_aclose_runs_a_finally_that_awaits_loops_and_calls(tmp_path: Path) -> None:
    body = """
async def tidy():
    try:
        yield 1
        yield 2
    finally:
        await haa.sleep(0)
        for _ in range(3):
            pass
        note("closed")

@action
async def go(event):
    ag = tidy()
    await anext(ag)
    await ag.aclose()
    return log
"""
    assert await run(tmp_path, body) == ["closed"]


async def test_except_generator_exit_in_the_body(tmp_path: Path) -> None:
    body = """
async def watcher():
    try:
        yield 1
    except GeneratorExit:
        note("exit")
        raise
    except Exception:
        note("never")

@action
async def go(event):
    ag = watcher()
    await anext(ag)
    await ag.aclose()
    return log
"""
    assert await run(tmp_path, body) == ["exit"]


async def test_body_exception_reaches_asend_caller(tmp_path: Path) -> None:
    body = """
async def broken():
    yield 1
    raise ValueError("bad")

@action
async def go(event):
    ag = broken()
    await ag.asend(None)
    try:
        await ag.asend("x")
    except ValueError as err:
        return str(err)
"""
    assert await run(tmp_path, body) == "bad"


@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
async def test_closed_before_start(tmp_path: Path) -> None:
    body = """
async def tracked():
    note("started")
    yield 1

@action
async def go(event):
    ag = tracked()
    await ag.aclose()
    return log
"""
    assert await run(tmp_path, body) == []


async def test_is_a_real_async_generator(tmp_path: Path) -> None:
    body = "import inspect\n@action\ndef go(event):\n    return inspect.isasyncgen(count_up_async(1))\n"
    assert await run(tmp_path, body, additional_imports=["inspect"]) is True


SLEEPY = """
async def slow_items():
    i = 0
    while i < 3:
        await haa.sleep(1)
        yield i
        i += 1

async def helper():
    await haa.sleep(1)
    return "helped"

async def nested():
    value = await helper()
    yield value

@action
async def go(event):
    ag = slow_items()
    return [await anext(ag), await anext(ag), await anext(ag)]

@action
async def go_nested(event):
    return await anext(nested())

async def sleepy_with_finally():
    try:
        await haa.sleep(10)
        yield 1
    finally:
        note("finally")

@action(timeout=2)
async def go_timeout(event):
    return await anext(sleepy_with_finally())

async def slow_one():
    await haa.sleep(1)
    yield 1

@action
async def go_two(event):
    import asyncio
    ag = slow_one()
    results = await asyncio.gather(anext(ag), anext(ag), return_exceptions=True)
    return [type(r).__name__ if isinstance(r, Exception) else r for r in results] + [
        str(r) for r in results if isinstance(r, Exception)
    ]
"""


async def test_sleep_between_items(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path, SLEEPY)) as automation:
        task = asyncio.ensure_future(automation.call("go"))
        await automation.clock.settle()
        assert await automation.call("other") == "other ran"
        for _ in range(3):
            await automation.advance_time(seconds=1)
        assert await task == [0, 1, 2]


async def test_nested_awaits_pass_through(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path, SLEEPY)) as automation:
        task = asyncio.ensure_future(automation.call("go_nested"))
        await automation.clock.settle()
        await automation.advance_time(seconds=1)
        assert await task == "helped"


@pytest.mark.timeout(20)
async def test_cancel_while_sleeping_runs_finally(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path, SLEEPY)) as automation:
        task = asyncio.ensure_future(automation.call("go_timeout"))
        await automation.clock.settle()
        await automation.advance_time(seconds=3)
        with pytest.raises(ActionTimeOutError):
            await task
        assert await automation.call("logged") == ["finally"]


async def test_two_consumers_at_once(tmp_path: Path) -> None:
    async with AutomationHarness(write(tmp_path, SLEEPY), additional_imports=["asyncio"]) as automation:
        task = asyncio.ensure_future(automation.call("go_two"))
        await automation.clock.settle()
        await automation.advance_time(seconds=1)
        result = await task
        assert result[:2] == [1, "RuntimeError"]
        assert "already running" in result[2]


async def test_stop_iteration_in_body_is_runtime_error(tmp_path: Path) -> None:
    body = """
async def leaky():
    yield 1
    next(iter([]))

@action
async def go(event):
    ag = leaky()
    await anext(ag)
    try:
        await anext(ag)
    except RuntimeError as err:
        return str(err)
"""
    assert await run(tmp_path, body) == "async generator raised StopIteration"


async def test_yield_from_in_async_def_rejected(tmp_path: Path) -> None:
    assert "'yield from' inside async function" in (
        await load_error(tmp_path, "async def g():\n    yield from [1]\n") or ""
    )


async def test_return_value_in_async_generator_rejected(tmp_path: Path) -> None:
    assert "'return' with value in async generator" in (
        await load_error(tmp_path, "async def g():\n    yield 1\n    return 2\n") or ""
    )


# --- async for ----------------------------------------------------------------------


async def test_async_for_over_an_automation_generator(tmp_path: Path) -> None:
    body = "@action\nasync def go(event):\n    out = []\n    async for x in count_up_async(3):\n        out.append(x)\n    return out\n"
    assert await run(tmp_path, body) == [0, 1, 2]


async def test_async_for_over_a_native_async_iterator(tmp_path: Path) -> None:
    body = """
class Countdown:
    def __init__(self, n):
        self.n = n
    def __aiter__(self):
        return self
    async def __anext__(self):
        if self.n == 0:
            raise StopAsyncIteration
        self.n -= 1
        return self.n

@action
async def go(event):
    out = []
    async for x in Countdown(3):
        out.append(x)
    return out
"""
    assert await run(tmp_path, body) == [2, 1, 0]


async def test_async_for_break_continue_else(tmp_path: Path) -> None:
    body = """
@action
async def go(event):
    out = []
    async for x in count_up_async(5):
        if x == 1:
            continue
        if x == 3:
            break
        out.append(x)
    else:
        out.append("no break")
    async for x in count_up_async(2):
        out.append(x)
    else:
        out.append("else")
    return out
"""
    assert await run(tmp_path, body) == [0, 2, 0, 1, "else"]


async def test_async_for_over_a_non_async_iterable(tmp_path: Path) -> None:
    body = "@action\nasync def go(event):\n    try:\n        async for x in [1, 2]:\n            pass\n    except TypeError:\n        return 'type error'\n"
    assert await run(tmp_path, body) == "type error"


async def test_break_leaves_the_generator_to_the_finalizer(tmp_path: Path) -> None:
    body = """
import gc

async def tracked():
    try:
        yield 1
        yield 2
    finally:
        note("finalized")

@action
async def go(event):
    ag = tracked()
    async for x in ag:
        break
    before = list(log)
    del ag
    gc.collect()
    return before
"""
    async with AutomationHarness(write(tmp_path, body), additional_imports=["gc"]) as automation:
        assert await automation.call("go") == []
        # The event loop's finalizer closes the collected generator on its next turns
        await automation.clock.settle()
        assert await automation.call("logged") == ["finalized"]


# --- Async comprehensions and async generator expressions ---------------------------


async def test_async_list_set_dict_comprehensions(tmp_path: Path) -> None:
    body = """
@action
async def go(event):
    return [
        [x async for x in count_up_async(3)],
        sorted({x % 2 async for x in count_up_async(4)}),
        {str(x): x * x async for x in count_up_async(3)},
    ]
"""
    assert await run(tmp_path, body) == [[0, 1, 2], [0, 1], {"0": 0, "1": 1, "2": 4}]


async def test_await_in_element_and_condition(tmp_path: Path) -> None:
    body = """
async def double(x):
    return x * 2

async def keep(x):
    return x != 1

@action
async def go(event):
    return [await double(x) async for x in count_up_async(3) if await keep(x)]
"""
    assert await run(tmp_path, body) == [0, 4]


async def test_async_generator_expression_is_lazy_and_async(tmp_path: Path) -> None:
    body = """
import inspect

async def tracked():
    for i in range(5):
        note(i)
        yield i

@action
async def go(event):
    ag = (x * 10 async for x in tracked())
    first = await anext(ag)
    return [inspect.isasyncgen(ag), first, list(log)]
"""
    assert await run(tmp_path, body, additional_imports=["inspect"]) == [True, 0, [0]]


async def test_generator_expression_with_await_is_async(tmp_path: Path) -> None:
    body = """
async def double(x):
    return x * 2

@action
async def go(event):
    ag = (await double(x) for x in range(3))
    out = []
    async for x in ag:
        out.append(x)
    return out
"""
    assert await run(tmp_path, body) == [0, 2, 4]


async def test_async_comprehension_outside_async_def_rejected(tmp_path: Path) -> None:
    assert "asynchronous comprehension outside of an asynchronous function" in (
        await load_error(tmp_path, "r = [x async for x in count_up_async(2)]\n") or ""
    )


async def test_sync_comprehension_with_await_inside_async_def(tmp_path: Path) -> None:
    body = """
async def double(x):
    return x * 2

@action
async def go(event):
    return [await double(x) for x in range(3)]
"""
    assert await run(tmp_path, body) == [0, 2, 4]


# --- Final review fixes -------------------------------------------------------------


async def test_nested_generator_expression_that_awaits_keeps_the_outer_one_sync(tmp_path: Path) -> None:
    body = """
async def ident(x):
    return x

@action
async def go(event):
    g = ((await ident(z) for z in [x]) for x in [1, 2])
    out = []
    for inner in g:
        async for v in inner:
            out.append(v)
    return out
"""
    assert await run(tmp_path, body) == [1, 2]


async def test_async_listcomp_inside_a_generator_expression_makes_it_async(tmp_path: Path) -> None:
    body = """
@action
async def go(event):
    g = ([z async for z in count_up_async(x)] for x in [1, 2])
    out = []
    async for v in g:
        out.append(v)
    return out
"""
    assert await run(tmp_path, body) == [[0], [0, 1]]


CYCLE = """
import gc

class Holder:
    async def agen(self):
        try:
            yield 1
            yield 2
        finally:
            note("finally")

@action
async def go(event):
    holder = Holder()
    holder.g = holder.agen()
    await anext(holder.g)
    del holder
    gc.collect()
    return "dropped"
"""


# Python itself closes the body's coroutine in the same collection and reports that it could not; HAAnim cannot
# intercept that one
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
async def test_async_generator_collected_in_a_cycle_warns_clearly(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    async with AutomationHarness(write(tmp_path, CYCLE), additional_imports=["gc"]) as automation:
        assert await automation.call("go") == "dropped"
        await automation.clock.settle()
        await automation.clock.settle()
    assert "cannot reuse already awaited coroutine" not in caplog.text
    assert "garbage-collected in a reference cycle" in caplog.text
