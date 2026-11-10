"""Comprehensions, async for loops and generators in automation code.

List, set and dict comprehensions and generator expressions share one walker
over their ``for`` and ``if`` clauses, with a checkpoint at every item. A
generator is a real Python generator that steps the interpreter coroutine of
its body (``eval_function.drive_generator``); see
``docs/superpowers/specs/2026-11-10-generators-design.md``.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine, Generator
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from haanim.engine.eval_function import (
    CHECKPOINT,
    CarriedGeneratorExit,
    NativeCallWatch,
    YieldPoint,
    drive_async_generator,
    drive_generator,
    is_automation_generator,
)
from haanim.engine.symbol_table import SCOPE_COMPREHENSION, SymbolTable

if TYPE_CHECKING:
    from haanim.engine.ast_evaluator import AstEvaluator

# The calls that consume every item of an iterable: an automation generator given to them is drained first
DRAINED_FIRST_ARGUMENT = frozenset(
    {
        builtins.list,
        builtins.tuple,
        builtins.set,
        builtins.frozenset,
        builtins.dict,
        builtins.sorted,
        builtins.sum,
    }
)
# ... and those that do so only when the iterable is their only positional argument
DRAINED_ONLY_ARGUMENT = frozenset({builtins.min, builtins.max})


def drains(func: Any, args: tuple[Any, ...]) -> bool:
    """Return whether a call consumes every item of its first argument, so that it can be drained first."""
    return (
        func in DRAINED_FIRST_ARGUMENT
        or (func in DRAINED_ONLY_ARGUMENT and len(args) == 1)
        or (isinstance(getattr(func, "__self__", None), str) and getattr(func, "__name__", "") == "join")
    )


async def drain(engine: AstEvaluator, generator: Generator[Any, Any, Any]) -> list[Any]:
    """Return every item of an automation generator, with checkpoints between them; close it if stopped.

    ``list(forever())`` then runs with the event loop free, so timeouts and
    stopping the automation work; the call's result is the same.
    """
    items: list[Any] = []
    try:
        while True:
            try:
                items.append(next(generator))
            except StopIteration:
                return items
            if engine.checkpoint_due():
                await CHECKPOINT
    except BaseException:
        generator.close()
        raise


async def all_items(engine: AstEvaluator, value: Any) -> Any:
    """Return what to take every item from: an automation generator drained with checkpoints, or the value."""
    return await drain(engine, value) if is_automation_generator(value) else value


async def contains(engine: AstEvaluator, container: Any, item: Any) -> bool:
    """Evaluate ``item in container``; an automation generator is searched with checkpoints between items."""
    if not is_automation_generator(container):
        return item in container
    try:
        while True:
            try:
                candidate = next(container)
            except StopIteration:
                return False
            if candidate is item or candidate == item:
                return True
            if engine.checkpoint_due():
                await CHECKPOINT
    except BaseException:
        container.close()
        raise


async def yield_from(iterable: Any) -> Any:
    """Pass every item of an iterable on from a generator body; return its return value.

    As in Python, what is sent goes to the iterable, an exception thrown in is
    thrown into it, and closing the generator closes it.
    """
    iterator = iter(iterable)
    sent: Any = None
    thrown: BaseException | None = None
    while True:
        try:
            if thrown is not None:
                throw = getattr(iterator, "throw", None)
                if throw is None:
                    raise thrown
                item = throw(thrown)
            elif sent is not None:
                item = iterator.send(sent)
            else:
                item = next(iterator)
        except StopIteration as stop:
            return stop.value
        sent, thrown = None, None
        try:
            sent = await YieldPoint(item)
        except GeneratorExit, CarriedGeneratorExit:
            close = getattr(iterator, "close", None)
            if close is not None:
                close()
            raise
        except BaseException as err:  # pylint: disable=broad-exception-caught
            thrown = err


async def walk_comprehension(
    engine: AstEvaluator,
    clauses: list[ast.comprehension],
    scope: SymbolTable,
    on_item: Callable[[SymbolTable], Awaitable[None]],
    first: Any = None,
) -> None:
    """Run ``on_item`` in the scope of every combination the ``for`` and ``if`` clauses give.

    Each item is a checkpoint. ``first`` is the first clause's iterable when it
    was evaluated already (a generator expression evaluates it when it is made).
    """

    async def handle(clause: ast.comprehension, index: int, item: Any, local_scope: SymbolTable) -> None:
        if engine.checkpoint_due():
            await CHECKPOINT
        inner_scope = local_scope.create_child(SCOPE_COMPREHENSION)
        await engine.assign_target(clause.target, item, inner_scope)
        for condition in clause.ifs:
            if not await engine.aeval(condition, inner_scope):
                return
        await process(index + 1, inner_scope)

    async def process(index: int, local_scope: SymbolTable) -> None:
        if index >= len(clauses):
            await on_item(local_scope)
            return
        clause = clauses[index]
        iterable = first if index == 0 and first is not None else await engine.aeval(clause.iter, local_scope)
        if not clause.is_async:
            for item in iterable:
                await handle(clause, index, item, local_scope)
            return
        # async for: the items are awaited from an async iterator
        iterator = aiter(iterable)
        while True:
            try:
                item = await anext(iterator)
            except StopAsyncIteration:
                return
            await handle(clause, index, item, local_scope)

    await process(0, scope)


async def comprehension(
    engine: AstEvaluator, node: ast.ListComp | ast.SetComp, scope: SymbolTable
) -> list[Any]:
    """Return the items of a list or set comprehension, in order."""
    results: list[Any] = []

    async def collect(local_scope: SymbolTable) -> None:
        results.append(await engine.aeval(node.elt, local_scope))

    await walk_comprehension(engine, node.generators, scope, collect)
    return results


async def dict_comprehension(engine: AstEvaluator, node: ast.DictComp, scope: SymbolTable) -> dict[Any, Any]:
    """Return the dictionary of a dict comprehension."""
    result: dict[Any, Any] = {}

    async def collect(local_scope: SymbolTable) -> None:
        key = await engine.aeval(node.key, local_scope)
        result[key] = await engine.aeval(node.value, local_scope)

    await walk_comprehension(engine, node.generators, scope, collect)
    return result


async def generator_expression(
    engine: AstEvaluator, node: ast.GeneratorExp, scope: SymbolTable
) -> Generator[Any, Any, Any] | AsyncGenerator[Any, Any]:
    """Return the lazy generator of a generator expression.

    As in Python, the first ``for``'s iterable is evaluated now; the rest as items are pulled.
    """
    is_async = any(clause.is_async for clause in node.generators) or _awaits(node)
    evaluated = await engine.aeval(node.generators[0].iter, scope)
    first = aiter(evaluated) if node.generators[0].is_async else iter(evaluated)

    async def hand_out(local_scope: SymbolTable) -> None:
        await YieldPoint(await engine.aeval(node.elt, local_scope))

    def body() -> Coroutine[Any, Any, None]:
        return walk_comprehension(engine, node.generators, scope, hand_out, first)

    if is_async:
        # An async generator expression, as in Python: it has async for or await
        return drive_async_generator(body, "<genexpr>")
    watch = NativeCallWatch(SimpleNamespace(name="<genexpr>", lineno=node.lineno, engine=engine))
    return drive_generator(body, "<genexpr>", watch)


def _awaits(node: ast.GeneratorExp) -> bool:
    """Return whether a generator expression awaits, not counting functions and lambdas inside it."""
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, ast.Await):
            return True
        if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            stack.extend(ast.iter_child_nodes(child))
    return False


async def async_for(
    engine: AstEvaluator,
    node: ast.AsyncFor,
    scope: SymbolTable,
    loop_signals: tuple[type[BaseException], type[BaseException]],
) -> None:
    """Run an async for loop: await each item of an async iterator, with a checkpoint per item.

    ``loop_signals`` are the evaluator's break and continue signals, in that order.
    """
    stop, skip = loop_signals
    iterator = aiter(await engine.aeval(node.iter, scope))
    while True:
        try:
            item = await anext(iterator)
        except StopAsyncIteration:
            for stmt in node.orelse:
                await engine.aeval(stmt, scope)
            return
        if engine.checkpoint_due():
            await CHECKPOINT
        await engine.assign_target(node.target, item, scope)
        try:
            for stmt in node.body:
                await engine.aeval(stmt, scope)
        except stop:
            return
        except skip:
            continue
