"""Helpers for calling functions defined in automations."""

from __future__ import annotations

import inspect
from typing import Any

__all__ = ["is_coroutine_callable"]


def is_coroutine_callable(func: Any) -> bool:
    """Return whether calling ``func`` gives a coroutine that must be awaited.

    True for ``async def`` functions and for objects whose ``__call__`` is one.
    The second case matters: every function defined in an automation is an
    ``EvalFunction`` object with an async ``__call__``, whether the automation
    wrote ``def`` or ``async def``. ``asyncio.iscoroutinefunction`` alone
    reports those as synchronous.

    Args:
        func: Any callable.
    """
    if inspect.iscoroutinefunction(func):
        return True
    return inspect.iscoroutinefunction(getattr(func, "__call__", None))
