"""Comprehensions and generators in automation code.

List, set and dict comprehensions and generator expressions share one walker
over their ``for`` and ``if`` clauses, with a checkpoint at every item. A
generator is a real Python generator that steps the interpreter coroutine of
its body (``eval_function.drive_generator``); see
``docs/superpowers/specs/2026-11-10-generators-design.md``.
"""

from __future__ import annotations

import ast
import builtins
from collections.abc import Awaitable, Callable, Generator, Iterable
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from haanim.engine.eval_function import CHECKPOINT, NativeCallWatch, YieldPoint, drive_generator
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


async def yield_from(iterable: Any) -> Any:
    """Pass every item of an iterable on from a generator body, with what is sent; return its return value."""
    iterator = iter(iterable)
    sent: Any = None
    while True:
        try:
            item = iterator.send(sent) if sent is not None else next(iterator)
        except StopIteration as stop:
            return stop.value
        sent = await YieldPoint(item)


async def walk_comprehension(
    engine: AstEvaluator,
    clauses: list[ast.comprehension],
    scope: SymbolTable,
    on_item: Callable[[SymbolTable], Awaitable[None]],
    first: Iterable[Any] | None = None,
) -> None:
    """Run ``on_item`` in the scope of every combination the ``for`` and ``if`` clauses give.

    Each item is a checkpoint. ``first`` is the first clause's iterable when it
    was evaluated already (a generator expression evaluates it when it is made).
    """

    async def process(index: int, local_scope: SymbolTable) -> None:
        if index >= len(clauses):
            await on_item(local_scope)
            return
        clause = clauses[index]
        iterable = first if index == 0 and first is not None else await engine.aeval(clause.iter, local_scope)
        for item in iterable:
            if engine.checkpoint_due():
                await CHECKPOINT
            inner_scope = local_scope.create_child(SCOPE_COMPREHENSION)
            await engine.assign_target(clause.target, item, inner_scope)
            passed = True
            for condition in clause.ifs:
                if not await engine.aeval(condition, inner_scope):
                    passed = False
                    break
            if passed:
                await process(index + 1, inner_scope)

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
) -> Generator[Any, Any, Any]:
    """Return the lazy generator of a generator expression.

    As in Python, the first ``for``'s iterable is evaluated now; the rest as items are pulled.
    """
    first = iter(await engine.aeval(node.generators[0].iter, scope))

    async def hand_out(local_scope: SymbolTable) -> None:
        await YieldPoint(await engine.aeval(node.elt, local_scope))

    watch = NativeCallWatch(SimpleNamespace(name="<genexpr>", lineno=node.lineno, engine=engine))
    return drive_generator(
        lambda: walk_comprehension(engine, node.generators, scope, hand_out, first), "<genexpr>", watch
    )
