"""Helpers for calling functions defined in automations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from haanim.engine.eval_function import get_eval_function

__all__ = ["accepted_kwargs", "as_coroutine_function"]


def as_coroutine_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return a coroutine function that runs ``func`` on the event loop.

    All automation code runs on the event loop; nothing is handed to a thread.

    - An ``async def`` function is returned unchanged.
    - A ``def`` function of an automation gives the interpreter's coroutine for
      its body, so that it yields at checkpoints instead of running to
      completion.
    - Any other callable is called directly. If what it returns is awaitable,
      that is awaited.

    Args:
        func: Any callable.
    """
    if inspect.iscoroutinefunction(func):
        return func

    found = get_eval_function(func)
    if found is not None:
        eval_function, prefix = found

        async def invoke(*args: Any, **kwargs: Any) -> Any:
            return await eval_function.invoke(*prefix, *args, **kwargs)

        return invoke

    async def call(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    return call


def accepted_kwargs(func: Callable[..., Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return the keyword arguments that ``func`` declares.

    The engine offers every function it runs the same context (``manual``, the
    changed entity and so on); a function takes the parts it names as
    parameters. A function with ``**kwargs`` gets all of it.

    Args:
        func: The function about to be called.
        kwargs: The context the engine offers.
    """
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return kwargs

    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters):
        return kwargs
    names = {
        parameter.name
        for parameter in parameters
        if parameter.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    return {name: value for name, value in kwargs.items() if name in names}
