# Generators in automations

Date: 2026-11-10
Status: proposed design, awaiting review
Spike: branch `spike-generators` (commit `08144d7`, throwaway prototype)

## Goal

Automation code can define and use generators as in Python: functions with `yield` and `yield from`,
and generator expressions. They are lazy, support the full generator protocol, and work wherever an
iterable is expected, without letting automation code freeze Home Assistant.

## Background

The interpreter runs every function body as a coroutine, so it can pause at checkpoints (each loop
iteration and call) and never block the event loop. A generator is pulled synchronously by `next()`,
often from native code (`list(gen)`, `sum(gen)`), which cannot wait. That is why `validation.py` rejects
`yield`, `yield from` and generator expressions today.

The interpreter already calls automation functions synchronously from native code
(`eval_function.run_to_completion`): a `def` body cannot `await`, so its coroutine only pauses at
checkpoints, which are skipped. The spike showed the same approach gives real generators.

## Decisions

| Topic | Decision |
| --- | --- |
| Supported | `yield` and `yield from` in `def` functions and methods; generator expressions |
| Not supported | `yield` in a lambda; `yield` in an `async def` (async generators) and `async for`, as a later feature |
| Generator objects | Real Python generators (`inspect.isgenerator` is true), so native code accepts them |
| Consume-all calls | `list`, `tuple`, `set`, `frozenset`, `dict`, `sorted`, `sum`, `min`, `max` and `str.join` drain an automation generator through the interpreter, pausing between items |
| Other native consumers | Run the generator synchronously, with the existing warning after 1 second and a new hard limit |
| Hard limit | 10 seconds by the host's clock, or 5,000,000 checkpoints, whichever comes first |
| `StopIteration` | Behaves as in Python, including `except StopIteration` in automation code |

## 1. Generators

A `def` whose body contains `yield` or `yield from` (not counting functions, lambdas and classes defined
inside it) is a generator function. Calling it runs none of the body and returns a generator object.

- The generator object is a real Python generator that drives the body's coroutine:
  - checkpoints in the body are passed over;
  - a `yield` hands its value to whoever called `next()` or `send()`;
  - `send(value)` is the result of the `yield` expression;
  - `throw(exc)` raises at the `yield`;
  - `close()` raises `GeneratorExit` at the `yield`, so `finally` blocks run.
- A `return value` in the body ends the generator, and its value is `StopIteration.value`.
- `yield from iterable` passes every item of `iterable` on, forwards `send()` to it, and is the
  iterable's return value.
- Generator expressions are generators over their comprehension: lazy, evaluated item by item. As in
  Python, the first `for`'s iterable is evaluated when the expression is.
- Generator methods, including `__iter__`, work like functions.
- If the body tries to wait for something (it cannot `await`, but a value could be an awaitable reaching
  the driver), the generator raises `RuntimeError("Generator '<name>' cannot wait for anything")`.

Every automation generator is registered in a weak set, so the interpreter can recognise its own
generators without wrapping them.

## 2. Keeping Home Assistant responsive

### Consume-all calls are drained by the interpreter

When automation code calls one of these with an automation generator as its iterable argument, the
interpreter first pulls the generator's items itself, with a checkpoint between items, and then calls
the function with a list of them:

| Call | Argument drained |
| --- | --- |
| `list(g)`, `tuple(g)`, `set(g)`, `frozenset(g)`, `dict(g)`, `sorted(g, ...)`, `sum(g, ...)` | The first positional argument |
| `min(g, ...)`, `max(g, ...)` | The first positional argument, when it is the only one |
| `separator.join(g)` on a `str` | The argument |

The results are the same as calling the function on the generator, because these functions consume
every item anyway. Between items the event loop runs, so action timeouts, stopping the automation and
other actions all work, even on an infinite generator: `list(forever())` runs until the action's
timeout cancels it.

Calls that stop early or stay lazy (`any`, `all`, `next`, `zip`, `enumerate`, `map`, `filter`,
`itertools.*`) are not drained; they keep Python's semantics.

### A hard limit on synchronous runs

Automation code run synchronously by native code (a generator pulled by `any` or `itertools.islice`, a
`key=` function of `sorted`, a callback of a library) cannot pause. Today it is warned about after
`NATIVE_CALL_WARNING_SECONDS` (1 second). New: when such a run passes `NATIVE_CALL_LIMIT_SECONDS`
(10 seconds by the host's clock) or `NATIVE_CALL_STEP_LIMIT` (5,000,000 checkpoints, which also stops it
when the clock does not move, as in tests), the interpreter raises at the next checkpoint:

> `TimeoutError: function '<name>' ran for more than 10 seconds without returning to the interpreter, and was stopped: it blocks Home Assistant while it runs`

The error is raised inside the automation code, so its `finally` blocks run, and it ends the action like
any exception (logged, `last_error`). This applies to every synchronous run, not only generators.

## 3. `StopIteration`

Python turns a `StopIteration` that leaves a coroutine into `RuntimeError` (PEP 479). The interpreter's
frames are coroutines, so today a `StopIteration` raised by `next()` or `send()` in automation code
becomes `RuntimeError` before automation code can catch it. That is an existing bug the spike exposed.

The interpreter carries a `StopIteration` from a native call across its own frames and gives it back as
itself:

- `except StopIteration` (and `except Exception`) in automation code catches it, with its `value`;
- one that leaves an ordinary function reaches the caller as `StopIteration`;
- one that leaves a generator body becomes `RuntimeError("generator raised StopIteration")`, as in Python.

## 4. Errors and validation

- `validation.py` no longer rejects `yield`, `yield from` and generator expressions.
- It rejects, with file and line:
  - `yield` or `yield from` in a lambda: "'yield' in a lambda is not supported: use a def";
  - `yield` or `yield from` in an `async def`: "async generators are not supported".
- `yield` outside a function stays a syntax error, as Python reports it.

## 5. Documentation

- `docs/AUTOMATIONS.md`: "Imports and Python" no longer says generators are unsupported. A short
  "Generators" paragraph covers the drained calls and the 10-second limit for other native consumers.
- `_design.md` "Supported Python": the generators exception is removed; async generators are listed.
- The changelog.

## 6. Testing

- **Interpreter:**
  - each protocol case from the spike: `list`, `sum`, `sorted`, `for`, comprehensions, `islice` on an
    infinite generator, laziness, `send`, `throw`, `close` with `finally`, `return` value, `yield from`
    with send forwarding and return value, generator expressions, generator methods and `__iter__`;
  - nested generators;
  - a generator whose body raises;
  - a generator closed before it starts.
- **Draining:**
  - each drained call gives the same result as Python;
  - `list(forever())` in an action is cancelled by the action timeout and leaves the event loop
    responsive (another action runs meanwhile);
  - `min(a, b)` with two arguments is not drained;
  - `any` on an infinite generator stops early.
- **Hard limit:**
  - an infinite generator pulled by `any` with no matching item raises `TimeoutError` at the step limit
    in the harness;
  - a native callback (a `sorted` key function) that loops forever does the same;
  - `finally` runs.
- **`StopIteration`:**
  - caught in automation code with its value;
  - propagated to a native caller;
  - turned into `RuntimeError` when it leaves a generator body.
- **Validation:** lambda and `async def` yields rejected; the existing tests that used `yield` as their
  example of unsupported code use another unsupported construct (`match`).
- **Docs:** the new examples run through `tests/engine/test_docs.py`.
