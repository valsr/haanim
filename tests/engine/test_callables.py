"""Tests for engine/callables.py."""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import pytest

from haanim.engine.callables import is_coroutine_callable
from tests.engine.helpers import make_context


def sync_function() -> int:
    """A plain function."""
    return 1


async def async_function() -> int:
    """A coroutine function."""
    return 1


class SyncCallable:
    """An object with a plain __call__."""

    def __call__(self) -> int:
        return 1


class AsyncCallable:
    """An object with an async __call__."""

    async def __call__(self) -> int:
        return 1


class TestIsCoroutineCallable:
    """Tests for is_coroutine_callable."""

    @pytest.mark.parametrize(
        ("func", "expected"),
        [
            (sync_function, False),
            (async_function, True),
            (SyncCallable(), False),
            (AsyncCallable(), True),
            (functools.partial(async_function), True),
            (functools.partial(sync_function), False),
            (lambda: 1, False),
            (len, False),
            (42, False),
            (None, False),
        ],
        ids=[
            "def",
            "async def",
            "object with def __call__",
            "object with async __call__",
            "partial of async def",
            "partial of def",
            "lambda",
            "builtin",
            "not callable",
            "None",
        ],
    )
    def test_is_coroutine_callable(self, func: Any, expected: bool) -> None:
        """Test which callables need awaiting."""
        assert is_coroutine_callable(func) is expected

    @pytest.mark.parametrize("definition", ["def", "async def"])
    async def test_automation_functions_need_awaiting(self, tmp_path: Path, definition: str) -> None:
        """Test a function defined in an automation is awaitable whether written def or async def."""
        path = tmp_path / "auto.py"
        path.write_text(f"@action\n{definition} compute():\n    return 7\n", encoding="utf-8")
        context = make_context(str(path))
        await context.load()

        action = context.get_action("compute")
        assert action is not None
        assert is_coroutine_callable(action.func) is True
        assert await action.func() == 7


AUTOMATION = """
calls = []

@action
def sync_action(value=1, **kwargs):
    calls.append(("sync", value))
    return value * 2

@action
async def async_action(value=1, **kwargs):
    calls.append(("async", value))
    return value * 3

def helper(value):
    return value + 100
"""


class TestAutomationFunctionsActuallyRun:
    """Functions defined in automations run to completion on every execution path.

    Each path used to treat them as synchronous, hand them to a thread, and get
    back a coroutine that nobody awaited, so the function body never ran.
    """

    @pytest.fixture
    async def context(self, tmp_path: Path) -> Any:
        """A loaded automation with a def action, an async def action and a helper."""
        path = tmp_path / "auto.py"
        path.write_text(AUTOMATION, encoding="utf-8")
        context = make_context(str(path))
        await context.load()
        return context

    @pytest.mark.parametrize(
        ("action", "expected", "recorded"),
        [("sync_action", 10, ("sync", 5)), ("async_action", 15, ("async", 5))],
    )
    async def test_context_run_action(
        self, context: Any, action: str, expected: int, recorded: tuple[str, int]
    ) -> None:
        """Test AutomationContext.run_action runs the body and returns its result."""
        assert await context.run_action(action, value=5) == expected
        assert context.get_symbol("calls") == [recorded]

    async def test_context_run_function(self, context: Any) -> None:
        """Test AutomationContext.run_function runs a plain helper function."""
        assert await context.run_function("helper", 1) == 101

    @pytest.mark.parametrize(
        ("action", "expected", "recorded"),
        [("sync_action", 8, ("sync", 4)), ("async_action", 12, ("async", 4))],
    )
    async def test_action_pool(
        self, context: Any, action: str, expected: int, recorded: tuple[str, int]
    ) -> None:
        """Test ActionWorkerPool.submit_action runs the body and returns its result."""
        from haanim.engine.action_pool import ActionWorkerPool  # pylint: disable=import-outside-toplevel
        from haanim.engine.automation_status import (  # pylint: disable=import-outside-toplevel
            AutomationStatusManager,
        )

        pool = ActionWorkerPool(status_manager=AutomationStatusManager())
        func = context.get_action(action).func
        assert await pool.submit_action("auto", action, func, value=4) == expected
        assert context.get_symbol("calls") == [recorded]

    @pytest.mark.parametrize(
        ("action", "expected", "recorded"),
        [("sync_action", 6, ("sync", 3)), ("async_action", 9, ("async", 3))],
    )
    async def test_trigger_execution(
        self, context: Any, action: str, expected: int, recorded: tuple[str, int]
    ) -> None:
        """Test BaseTrigger._execute_function runs the body and returns its result."""
        from haanim.engine.automation_context import (  # pylint: disable=import-outside-toplevel
            TriggerDefinition,
        )
        from haanim.engine.triggers import BaseTrigger  # pylint: disable=import-outside-toplevel
        from haanim.testing import make_host  # pylint: disable=import-outside-toplevel

        class Trigger(BaseTrigger):
            """Minimal concrete trigger."""

            async def async_start(self) -> None:
                """Start."""

            async def async_stop(self) -> None:
                """Stop."""

        trigger_def = TriggerDefinition(
            trigger_type="state_trigger",
            trigger_expr="sensor.x > 1",
            func_name=action,
            func=context.get_action(action).func,
            automation_id="auto",
        )
        trigger = Trigger(make_host(), trigger_def)
        assert await trigger._execute_function(value=3) == expected
        assert context.get_symbol("calls") == [recorded]
