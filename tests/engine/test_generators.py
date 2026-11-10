"""Tests for generators in automations: yield, yield from, generator expressions, and what keeps them safe."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from haanim.testing import AutomationHarness

HELPERS = """
import itertools
from haanim import action, haa

def count_up(n):
    i = 0
    while i < n:
        yield i
        i += 1

def forever():
    i = 0
    while True:
        yield i
        i += 1
"""


def write(tmp_path: Path, body: str) -> Path:
    folder = tmp_path / "gens"
    folder.mkdir(exist_ok=True)
    (folder / "main.py").write_text(HELPERS + body)
    return folder


async def run(tmp_path: Path, body: str, action: str = "go", **harness: Any) -> Any:
    """Load an automation made of the helpers and a body, and return what one of its actions returns."""
    async with AutomationHarness(write(tmp_path, body), **harness) as automation:
        return await automation.call(action)


async def load_error(tmp_path: Path, body: str) -> str | None:
    async with AutomationHarness(write(tmp_path, body), start=False) as automation:
        assert not await automation.load()
        return automation.error


# --- Generators ---------------------------------------------------------------------


async def test_list_sum_sorted(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    return [list(count_up(5)), sum(count_up(101)), sorted(count_up(4), reverse=True)]\n"
    assert await run(tmp_path, body) == [[0, 1, 2, 3, 4], 5050, [3, 2, 1, 0]]


async def test_for_loop_and_comprehension(tmp_path: Path) -> None:
    body = (
        "@action\ndef go(event):\n    total = 0\n    for x in count_up(4):\n        total += x\n"
        "    return [total, [x * 2 for x in count_up(3)]]\n"
    )
    assert await run(tmp_path, body) == [6, [0, 2, 4]]


async def test_lazy_infinite_with_islice(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    return list(itertools.islice(forever(), 5))\n"
    assert await run(tmp_path, body) == [0, 1, 2, 3, 4]


async def test_send(tmp_path: Path) -> None:
    body = """
def echo():
    received = []
    while True:
        value = yield len(received)
        if value is None:
            break
        received.append(value)
    return received

def wrapper():
    result = yield from echo()
    yield result

@action
def go(event):
    gen = echo()
    first = next(gen)
    a = gen.send("x")
    b = gen.send("y")
    ended = next(gen, "ended")
    w = wrapper()
    next(w)
    w.send("z")
    return [first, a, b, ended, next(w)]
"""
    assert await run(tmp_path, body) == [0, 1, 2, "ended", ["z"]]


async def test_throw(tmp_path: Path) -> None:
    body = """
def careful():
    while True:
        try:
            yield "ready"
        except ValueError:
            yield "caught"

@action
def go(event):
    gen = careful()
    next(gen)
    return gen.throw(ValueError("x"))
"""
    assert await run(tmp_path, body) == "caught"


async def test_close_runs_finally(tmp_path: Path) -> None:
    body = """
log = []

def guarded():
    try:
        yield 1
        yield 2
    finally:
        log.append("closed")

@action
def go(event):
    g = guarded()
    next(g)
    g.close()
    return log
"""
    assert await run(tmp_path, body) == ["closed"]


async def test_close_with_except_exception_around_yield(tmp_path: Path) -> None:
    body = """
def stubborn():
    while True:
        try:
            yield 1
        except Exception:
            pass

@action
def go(event):
    g = stubborn()
    next(g)
    g.close()
    return list(g)
"""
    assert await run(tmp_path, body) == []


async def test_return_value_and_yield_from(tmp_path: Path) -> None:
    body = """
def inner():
    yield "a"
    yield "b"
    return "done"

def outer():
    result = yield from inner()
    yield result

@action
def go(event):
    return list(outer())
"""
    assert await run(tmp_path, body) == ["a", "b", "done"]


async def test_generator_expression(tmp_path: Path) -> None:
    body = (
        "@action\ndef go(event):\n"
        "    return [sum(x * x for x in range(10)), ','.join(str(x) for x in range(4) if x % 2 == 0),"
        " any(x > 3 for x in forever())]\n"
    )
    assert await run(tmp_path, body) == [285, "0,2", True]


async def test_generator_method_and_iter(tmp_path: Path) -> None:
    body = """
class Tree:
    def __init__(self, items):
        self.items = items
    def __iter__(self):
        for item in self.items:
            yield item * 10
    def doubled(self):
        yield from (item * 2 for item in self.items)

@action
def go(event):
    tree = Tree([1, 2])
    return [list(tree), list(tree.doubled())]
"""
    assert await run(tmp_path, body) == [[10, 20], [2, 4]]


async def test_body_exception_reaches_consumer(tmp_path: Path) -> None:
    body = """
def broken():
    yield 1
    raise ValueError("bad")

@action
def go(event):
    seen = []
    try:
        for x in broken():
            seen.append(x)
    except ValueError as err:
        seen.append(str(err))
    try:
        list(broken())
    except ValueError as err:
        seen.append("list: " + str(err))
    return seen
"""
    assert await run(tmp_path, body) == [1, "bad", "list: bad"]


async def test_exhausted_generator(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    g = count_up(2)\n    return [list(g), list(g)]\n"
    assert await run(tmp_path, body) == [[0, 1], []]


@pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning")
async def test_closed_before_start(tmp_path: Path) -> None:
    body = """
ran = []

def tracked():
    ran.append("started")
    yield 1

@action
def go(event):
    g = tracked()
    g.close()
    return [list(g), ran]
"""
    assert await run(tmp_path, body) == [[], []]


async def test_nested_generators(tmp_path: Path) -> None:
    body = """
def evens():
    yield from (x for x in count_up(10) if x % 2 == 0)

@action
def go(event):
    return list(x * 10 for x in evens())
"""
    assert await run(tmp_path, body) == [0, 20, 40, 60, 80]


async def test_is_a_real_generator(tmp_path: Path) -> None:
    body = "import inspect\n@action\ndef go(event):\n    return inspect.isgenerator(count_up(1))\n"
    assert await run(tmp_path, body, additional_imports=["inspect"]) is True


async def test_yield_in_lambda_rejected(tmp_path: Path) -> None:
    error = await load_error(tmp_path, "f = lambda: (yield 1)\n")
    assert "'yield' in a lambda is not supported: use a def" in (error or "")


async def test_async_generator_rejected(tmp_path: Path) -> None:
    error = await load_error(tmp_path, "async def agen():\n    yield 1\n")
    assert "async generators are not supported" in (error or "")


# --- StopIteration ------------------------------------------------------------------


async def test_stop_iteration_is_caught(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    try:\n        next(iter([]))\n    except StopIteration:\n        return 'caught'\n"
    assert await run(tmp_path, body) == "caught"


async def test_stop_iteration_value(tmp_path: Path) -> None:
    body = """
def seven():
    return 7
    yield

@action
def go(event):
    g = seven()
    try:
        next(g)
    except StopIteration as stop:
        return stop.value
"""
    assert await run(tmp_path, body) == 7


async def test_except_exception_catches_it(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    try:\n        next(count_up(0))\n    except Exception as err:\n        return type(err).__name__\n"
    assert await run(tmp_path, body) == "StopIteration"


async def test_raise_stop_iteration_statement_is_caught(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    try:\n        raise StopIteration(5)\n    except StopIteration as stop:\n        return stop.value\n"
    assert await run(tmp_path, body) == 5


async def test_stop_iteration_reaches_a_native_caller(tmp_path: Path) -> None:
    body = """
def f(x):
    raise StopIteration

@action
def go(event):
    return list(map(f, [1, 2]))
"""
    assert await run(tmp_path, body) == []


async def test_stop_iteration_leaving_a_generator_body_is_runtime_error(tmp_path: Path) -> None:
    body = """
def leaky():
    yield 1
    next(iter([]))

@action
def go(event):
    try:
        list(leaky())
    except RuntimeError as err:
        return str(err)
"""
    assert await run(tmp_path, body) == "generator raised StopIteration"


# --- Draining in consume-all calls --------------------------------------------------


@pytest.mark.parametrize(
    "expression, expected",
    [
        ("list(count_up(3))", [0, 1, 2]),
        ("tuple(count_up(3))", [0, 1, 2]),
        ("sorted(set(count_up(3)))", [0, 1, 2]),
        ("sorted(frozenset(count_up(3)))", [0, 1, 2]),
        ("dict((x, x * x) for x in count_up(3))", {"0": 0, "1": 1, "2": 4}),
        ("sorted(count_up(4), key=lambda x: -x)", [3, 2, 1, 0]),
        ("sum(count_up(4), 10)", 16),
        ("min(count_up(4), key=lambda x: (x - 2) ** 2)", 2),
        ("max(count_up(4))", 3),
        ("'-'.join(str(x) for x in count_up(3))", "0-1-2"),
    ],
)
async def test_drained_calls_give_python_results(tmp_path: Path, expression: str, expected: Any) -> None:
    body = f"@action\ndef go(event):\n    result = {expression}\n    return {{str(k): v for k, v in result.items()}} if isinstance(result, dict) else list(result) if isinstance(result, tuple) else result\n"
    assert await run(tmp_path, body) == expected


INFINITE = """
from haanim import ActionMode
log = []

def endless():
    try:
        i = 0
        while True:
            yield i
            i += 1
    finally:
        log.append("closed")

@action(timeout=2)
def all_of_it(event):
    return list(endless())

@action
def other(event):
    return "other ran"

@action
def closed(event):
    return log
"""


@pytest.mark.timeout(20)
async def test_list_of_infinite_generator_is_cancelled_by_the_timeout(tmp_path: Path) -> None:
    import asyncio  # pylint: disable=import-outside-toplevel

    from haanim.engine.errors import ActionTimeOutError  # pylint: disable=import-outside-toplevel

    async with AutomationHarness(write(tmp_path, INFINITE)) as automation:
        task = asyncio.ensure_future(automation.call("all_of_it"))
        await automation.clock.settle()
        assert await automation.call("other") == "other ran"
        await automation.advance_time(seconds=3)
        with pytest.raises(ActionTimeOutError):
            await task
        assert await automation.call("closed") == ["closed"]


async def test_generator_raising_midway_in_a_drained_call(tmp_path: Path) -> None:
    body = """
def broken():
    yield 1
    raise ValueError("midway")

@action
def go(event):
    result = None
    try:
        result = list(broken())
    except ValueError as err:
        return [result, str(err)]
"""
    assert await run(tmp_path, body) == [None, "midway"]


async def test_min_with_two_arguments_is_not_drained(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    try:\n        min(count_up(1), count_up(2))\n    except TypeError:\n        return 'compared the generators'\n"
    assert await run(tmp_path, body) == "compared the generators"


async def test_any_on_infinite_generator_stops_early(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    return any(x == 3 for x in forever())\n"
    assert await run(tmp_path, body) is True


# --- Hard limit on synchronous runs -------------------------------------------------

LIMIT_MESSAGE = (
    r"function '(forever|<genexpr>|spin)' ran for more than 10 seconds without returning to the interpreter, "
    r"and was stopped: it blocks Home Assistant while it runs"
)


@pytest.fixture
def small_step_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from haanim.engine import eval_function  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(eval_function, "NATIVE_CALL_STEP_LIMIT", 10_000)


@pytest.mark.timeout(30)
@pytest.mark.usefixtures("small_step_limit")
async def test_infinite_generator_pulled_by_any_hits_the_limit(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    try:\n        any(x < 0 for x in forever())\n    except TimeoutError as err:\n        return str(err)\n"
    assert re.fullmatch(LIMIT_MESSAGE, await run(tmp_path, body))


@pytest.mark.timeout(30)
@pytest.mark.usefixtures("small_step_limit")
async def test_endless_sorted_key_function_hits_the_limit(tmp_path: Path) -> None:
    body = """
log = []

def spin(x):
    try:
        while True:
            pass
    finally:
        log.append("finally")

@action
def go(event):
    try:
        sorted([1, 2], key=spin)
    except TimeoutError as err:
        return [str(err), log]
"""
    message, log = await run(tmp_path, body)
    assert re.fullmatch(LIMIT_MESSAGE, message)
    assert log == ["finally"]


@pytest.mark.usefixtures("small_step_limit")
async def test_long_iteration_returning_to_the_interpreter_is_not_limited(tmp_path: Path) -> None:
    body = "@action\ndef go(event):\n    total = 0\n    for x in count_up(30000):\n        total += 1\n    return [total, sum(count_up(30000))]\n"
    assert await run(tmp_path, body) == [30000, sum(range(30000))]


class Clock:
    """A clock that moves on by a step each time it is read."""

    def __init__(self, step: float) -> None:
        self.now_value = datetime(2026, 1, 1, tzinfo=UTC)
        self.step = timedelta(seconds=step)

    def now(self) -> datetime:
        self.now_value += self.step
        return self.now_value


class Engine:
    def __init__(self, step: float) -> None:
        self.clock = Clock(step)
        self.warned: list[str] = []

    def warn_blocking(self, function: Any) -> None:
        self.warned.append(function.name)


def watch(step: float) -> Any:
    from haanim.engine.eval_function import NativeCallWatch  # pylint: disable=import-outside-toplevel

    function = SimpleNamespace(name="slow", engine=Engine(step), lineno=1)
    return NativeCallWatch(function)


def test_time_limit() -> None:
    w = watch(11)
    assert w() is None  # the first checkpoint starts the watch
    error = w()
    assert isinstance(error, TimeoutError)
    assert "function 'slow' ran for more than 10 seconds" in str(error)


def test_warning_still_logged_after_one_second() -> None:
    w = watch(1.5)
    assert w() is None
    assert w() is None
    assert w._function.engine.warned == ["slow"]  # pylint: disable=protected-access


def test_restart_starts_the_count_again(monkeypatch: pytest.MonkeyPatch) -> None:
    from haanim.engine import eval_function  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(eval_function, "NATIVE_CALL_STEP_LIMIT", 3)
    w = watch(0)
    assert [w(), w(), w()] == [None, None, None]
    w.restart()
    assert [w(), w(), w()] == [None, None, None]
    assert isinstance(w(), TimeoutError)
