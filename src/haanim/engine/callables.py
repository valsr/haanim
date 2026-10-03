"""Helpers for calling functions defined in automations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from haanim.engine.eval_function import get_eval_function

__all__ = ["as_coroutine_function", "event_arguments", "signature_problem", "takes_event"]


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


def takes_event(func: Callable[..., Any]) -> bool:
    """Return whether a function declares a parameter for the event.

    The event parameter is optional: an action is written ``def f():`` or
    ``def f(event):``. A callable whose signature cannot be inspected is
    given the event.

    Args:
        func: The action, trigger or lifecycle function.
    """
    try:
        parameters = inspect.signature(func).parameters.values()
    except (TypeError, ValueError):
        return True
    positional = (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.VAR_POSITIONAL,
    )
    return any(parameter.kind in positional for parameter in parameters)


def event_arguments(func: Callable[..., Any], event: Any) -> tuple[Any, ...]:
    """Return the positional arguments to call a function with: the event, or nothing.

    Args:
        func: The action, trigger or lifecycle function.
        event: The event of the call.
    """
    return (event,) if takes_event(func) else ()


def signature_problem(func: Callable[..., Any]) -> str | None:
    """Return why a function cannot be called with at most the event, or None if it can.

    Data is never bound to parameters, so a function that requires more than
    one argument could not be called at all.

    Args:
        func: The action, trigger or lifecycle function.
    """
    try:
        parameters = list(inspect.signature(func).parameters.values())
    except (TypeError, ValueError):
        return None

    empty = inspect.Parameter.empty
    required = [
        parameter.name
        for parameter in parameters
        if parameter.default is empty
        and parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    keyword_only = [
        parameter.name
        for parameter in parameters
        if parameter.default is empty and parameter.kind is inspect.Parameter.KEYWORD_ONLY
    ]
    if len(required) > 1:
        return f"it requires the parameters {', '.join(required)}; it can take the event only"
    if keyword_only:
        return f"it requires the keyword argument {keyword_only[0]}; it can take the event only"
    return None
