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
