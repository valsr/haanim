# Async generators in automations

Date: 2026-11-10
Status: proposed design, awaiting review
Builds on: `2026-11-10-generators-design.md`

## Goal

Automation code can define and use async generators as in Python: `yield` inside `async def`, `async for`,
async comprehensions and async generator expressions, with the full async generator protocol. They run on
Home Assistant's event loop like any other automation code, so they can `await` (sleeps, service calls)
without blocking anything.

## Decisions

| Topic | Decision |
| --- | --- |
| Generator objects | Real Python async generators (`inspect.isasyncgen` is true) that drive the body's interpreter coroutine |
| Event loop | Everything the body awaits other than a `yield` is passed through to the event loop; checkpoints included |
| Hard limit, draining | Not needed: an async generator never runs synchronously |
| `async for` | Any async iterator, automation or native; `else`, `break`, `continue`; a checkpoint per item |
| Async comprehensions | List, set and dict forms and async generator expressions; only inside `async def`, as in Python |
| Abandoned iteration | As in Python: not closed at `break`; the event loop closes it when it is garbage-collected |
| Rejected, with Python's messages | `yield from` in an async generator; `return` with a value in an async generator; `yield` in a lambda (unchanged) |

## 1. Async generators

An `async def` whose body contains `yield` (not counting functions, lambdas and classes inside it) is an
async generator function. Calling it runs none of the body and returns an async generator object.

- The object is a real Python async generator that steps the body's coroutine:
  - a `yield` (`YieldPoint`) hands its value to whoever awaited `__anext__()` or `asend()`;
  - anything else the body awaits (a future, a checkpoint) is awaited by the driver itself, so it reaches the
    event loop and its result goes back into the body;
  - `asend(value)` is the result of the `yield` expression;
  - `athrow(exc)` raises at the `yield`;
  - `aclose()` raises `GeneratorExit` at the `yield`, and the body's cleanup (`finally`, `except
    GeneratorExit`) may loop, call functions and `await`.
- Closing uses the `CarriedGeneratorExit` of the sync generators: Python closes a coroutine awaiting another
  by calling the inner one's `close()`, which fails when cleanup pauses, so `GeneratorExit` is thrown down
  the interpreter's frames as the carrier. Automation code sees `GeneratorExit`.
- The body ending (or a bare `return`) ends iteration with `StopAsyncIteration`.
- A `StopIteration` or `StopAsyncIteration` leaving the body becomes `RuntimeError("async generator raised
  StopIteration")` or `("async generator raised StopAsyncIteration")`, as in Python.
- Every automation async generator is registered in a weak set, like the sync ones.
- Abandoned generators are closed by the event loop's async-generator finalizer, as in Python, which runs
  their cleanup on the loop.

## 2. `async for`

`async for target in iterable:` evaluates `aiter(iterable)` and awaits `anext()` until
`StopAsyncIteration`, assigning each item to the target and running the body. `break`, `continue` and `else`
work as in Python. There is a checkpoint per item. It works with automation async generators and with any
native async iterator. An object that is not an async iterable raises `TypeError` as in Python.

## 3. Async comprehensions

- `[x async for x in ag]`, `{x async for x in ag}`, `{k: v async for k, v in ag}`: the walker of
  `engine/comprehensions.py` iterates an `async for` clause by awaiting `anext()`. `await` in the element and
  the conditions works, as in Python.
- `(x async for x in ag)` and a generator expression containing `await` are async generators, built on the
  same driver as section 1.
- As in Python, these are only allowed inside `async def`: elsewhere validation reports "asynchronous
  comprehension outside of an asynchronous function".

## 4. Errors and validation

`validation.py`:
- no longer rejects `async for`, async comprehensions, or `yield` in `async def`;
- rejects, with file and line:
  - `yield from` in an `async def`: "'yield from' inside async function";
  - `return` with a value in an async generator: "'return' with value in async generator";
  - async comprehensions outside an `async def`: "asynchronous comprehension outside of an asynchronous
    function";
  - `yield` in a lambda: unchanged.

## 5. Documentation

- `docs/AUTOMATIONS.md`: a short "Async generators" part after "Generators", with a runnable example (an
  async generator that awaits `haa.sleep()` and is consumed with `async for`); "Imports and Python" no
  longer lists async generators as unsupported.
- `_design.md` "Supported Python" (local file): the async bullet is removed.
- The changelog.

## 6. Testing

- **Protocol:** `async for` over an automation async generator; `asend`; `athrow` caught at the `yield`;
  `aclose` with a `finally` that awaits, loops and calls a function; `except GeneratorExit` in the body;
  exhaustion (`StopAsyncIteration`, then empty again); an exception in the body reaching the consumer; a
  closed-before-start generator; `inspect.isasyncgen`.
- **Event loop:** an async generator that awaits `haa.sleep(1)` between items, driven with
  `advance_time`; another action runs while it sleeps; cancelling the action mid-iteration runs the body's
  `finally` with `CancelledError`.
- **Native consumers:** `anext(ag)` and `aiter()` from Python code; an async generator awaited by
  `asyncio.wait_for` style consumers through an automation action.
- **`async for`:** over a native async iterator (a small class with `__aiter__`/`__anext__`); `break`,
  `continue`, `else`; a non-async-iterable raising `TypeError`.
- **Comprehensions:** each async comprehension form; `await` in element and condition; async generator
  expressions, lazy.
- **Validation:** each rejected form with its message; the tests that used `async def gen(): yield 1` as
  their unsupported example switch to another unsupported construct (`match`).
- **Docs:** the example runs (called, not only loaded).
