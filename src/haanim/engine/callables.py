"""Helpers for calling functions defined in automations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from haanim.engine.eval_function import get_eval_function

__all__ = ["accepted_kwargs", "as_coroutine_function", "is_coroutine_callable"]


def is_coroutine_callable(func: Any) -> bool:
    """Return whether ``func`` can be run as a coroutine on the event loop.

    True for ``async def`` functions, for objects whose ``__call__`` is one, and
    for every function defined in an automation: the interpreter runs a ``def``
    of an automation as a coroutine too. Call such a function through
    ``as_coroutine_function()``.

    Args:
        func: Any callable.
    """
    if inspect.iscoroutinefunction(func) or get_eval_function(func) is not None:
        return True
    return inspect.iscoroutinefunction(getattr(func, "__call__", None))


def as_coroutine_function(func: Callable[..., Any]) -> Callable[..., Any]:
    """Return a callable that gives a coroutine running ``func``.

    For a ``def`` function of an automation this is the interpreter's coroutine
    for its body, so that it runs on the event loop instead of to completion.
    Anything else is returned unchanged.

    Args:
        func: A callable for which ``is_coroutine_callable()`` is true.
    """
    found = get_eval_function(func)
    if found is None or found[0].is_async:
        return func

    eval_function, prefix = found

    async def invoke(*args: Any, **kwargs: Any) -> Any:
        return await eval_function.invoke(*prefix, *args, **kwargs)

    return invoke


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
