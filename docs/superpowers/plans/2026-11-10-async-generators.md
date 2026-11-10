# Async Generators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automation code defines and uses async generators (`yield` in `async def`, `async for`, async comprehensions, async generator expressions) with Python's semantics, on Home Assistant's event loop.

**Architecture:** An async generator function's call returns a real Python async generator (`drive_async_generator`) that steps the body's interpreter coroutine: `YieldPoint` markers are yielded to the consumer, and every other awaitable the body yields (futures, checkpoints) is awaited by the driver through a pass-through awaitable, so it reaches the event loop. Closing reuses `CarriedGeneratorExit`. `async for` and async comprehension clauses iterate with `aiter`/`anext`.

**Tech Stack:** Python 3.14, HAAnim's AST interpreter (`src/haanim/engine`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-async-generators-design.md`

## Global Constraints

- Objects are real async generators (`inspect.isasyncgen` true), registered in `AUTOMATION_ASYNC_GENERATORS` (a `weakref.WeakSet`).
- Validation messages (exact): "'yield from' inside async function"; "'return' with value in async generator"; "asynchronous comprehension outside of an asynchronous function"; "'yield' in a lambda is not supported: use a def" (unchanged).
- Runtime messages (exact): `RuntimeError("async generator raised StopIteration")`, `RuntimeError("async generator raised StopAsyncIteration")`, `RuntimeError("async generator ignored GeneratorExit")`.
- No hard limit, no draining for async generators. No real time in the engine or its tests.

## Review Focus

1. **The action is cancelled while the async generator is suspended in its own `await` (a sleep), not at a `yield`:** `CancelledError` reaches the body at that `await`, its `finally` runs, and the action ends cancelled. Test in Task 1.
2. **The body awaits an automation coroutine that awaits in turn (nested awaits):** passes through to the event loop and resumes correctly. Test in Task 1.
3. **`break` out of `async for`:** the generator is not closed at once; once collected, the event loop's finalizer closes it and its `finally` runs. Test in Task 2.
4. **An exception raised in the body during `asend()`:** reaches the caller of `asend()` with its type and message. Test in Task 1.
5. **Two consumers calling `anext()` on one generator at once:** `RuntimeError` ("asynchronous generator is already running"), as in Python. Test in Task 1.

---

### Task 1: Async generator functions

**Files:**
- Modify: `src/haanim/engine/eval_function.py` (`drive_async_generator`, `_adrive`, `_Forward`, `_aclose_body`, `AUTOMATION_ASYNC_GENERATORS`, `is_automation_async_generator`; `EvalFunction.is_async_generator`, `EvalFunction.make_async_generator`; the `async_function` wrapper returns the async generator for an async generator function)
- Modify: `src/haanim/engine/ast_evaluator.py` (`call()`: an async generator function's call returns `make_async_generator(...)`, not a coroutine)
- Modify: `src/haanim/engine/callables.py` (an action that is an async generator function returns its generator)
- Modify: `src/haanim/engine/validation.py` (allow `yield` in `async def`; reject `yield from` in `async def` and `return <value>` in an async generator with the exact messages)
- Modify: the tests that use `async def gen():\n    yield 1` as their unsupported example (`test_validation.py`, `test_discovery.py`, `test_lifecycle.py`, `test_guard_rails.py`, `test_interpreter.py`) → `match 1:\n    case _:\n        pass` with "'match' statements are not supported", adjusting line numbers
- Test: `tests/engine/test_async_generators.py` (new; harness-driven like `tests/engine/test_generators.py`)

**Interfaces:**
- Consumes: `YieldPoint`, `_Yielded`, `CarriedGeneratorExit`, `CarriedStopIteration`, `validation.yields_in` (generators work).
- Produces:
  - `drive_async_generator(body: Callable[[], Coroutine[Any, Any, Any]], name: str) -> AsyncGenerator[Any, Any]` (registers the generator).
  - `is_automation_async_generator(obj: Any) -> bool`.
  - `EvalFunction.is_async_generator: bool` (`is_async and yields_in(body)`); `EvalFunction.make_async_generator(*args, **kwargs) -> AsyncGenerator`.

- [ ] **Step 1: Write the failing tests** (each an automation with an `async def` action returning the checked value):
  `test_anext_and_exhaustion` (`await anext(ag)` ×3 over `count_up_async(2)`, third raises `StopAsyncIteration` caught; `await anext(ag, "done")`);
  `test_asend` (echo async generator: `await ag.asend(None)`, then `asend("x")`, `asend("y")`);
  `test_athrow_caught_at_the_yield`;
  `test_aclose_runs_a_finally_that_awaits_loops_and_calls` (finally: `await haa.sleep(0)`, a `for` loop, a function call, appending to a log);
  `test_except_generator_exit_in_the_body`;
  `test_body_exception_reaches_asend_caller` (Review Focus 4: `ValueError("bad")` from the body during `asend`);
  `test_closed_before_start` (no body code ran; filter `error::pytest.PytestUnraisableExceptionWarning`);
  `test_is_a_real_async_generator` (`inspect.isasyncgen`, `inspect` in `additional_imports`);
  `test_sleep_between_items` (generator awaits `haa.sleep(1)` before each `yield`; action consumes 3 items; driven with `asyncio.ensure_future` + `advance_time(seconds=1)` ×3; another action runs meanwhile);
  `test_nested_awaits_pass_through` (Review Focus 2: body awaits an automation `async def` that awaits `haa.sleep(1)`);
  `test_cancel_while_sleeping_runs_finally` (Review Focus 1: `@action(timeout=2)`, generator sleeps 10 s inside `try/finally` that logs; after `advance_time(seconds=3)` the call raises `ActionTimeOutError` and the log has the entry);
  `test_two_consumers_at_once` (Review Focus 5: `asyncio.gather(anext(ag), anext(ag))` where the body sleeps → one `RuntimeError` matching "already running"; `asyncio` in `additional_imports`);
  `test_stop_iteration_in_body_is_runtime_error` (message per Global Constraints);
  `test_yield_from_in_async_def_rejected`, `test_return_value_in_async_generator_rejected` (load errors, exact messages).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_async_generators.py -q --no-cov -n 0 --timeout=30` — Expected: FAIL ("async generators are not supported").
- [ ] **Step 3: Implement.** `_adrive` is an `async def` with `yield` (a real async generator):

```python
class _Forward:
    """Awaitable that hands what the body yielded (a future, or None for a checkpoint) to the event loop."""
    def __init__(self, message): self.message = message
    def __await__(self): return (yield self.message)

async def _adrive(body, name):
    coro = body()
    value_in, error_in = None, None
    while True:
        try:
            message = coro.throw(error_in) if error_in is not None else coro.send(value_in)
        except StopIteration:
            return
        except CarriedStopIteration as carried:
            raise RuntimeError("async generator raised StopIteration") from carried.stop
        except StopAsyncIteration as err:
            raise RuntimeError("async generator raised StopAsyncIteration") from err
        value_in, error_in = None, None
        if isinstance(message, _Yielded):
            try:
                value_in = yield message.value
            except GeneratorExit:
                await _aclose_body(coro)
                raise
            except BaseException as err:
                error_in = err
        else:
            try:
                value_in = await _Forward(message)
            except BaseException as err:  # CancelledError and a future's exception go into the body
                error_in = err
```

  `_aclose_body(coro)` is `eval_function._close_body` for async: throw `CarriedGeneratorExit()`, then step; `None`/future messages are awaited through `_Forward`; a `_Yielded` closes the coroutine and raises `RuntimeError("async generator ignored GeneratorExit")`; `StopIteration`, `GeneratorExit`, `CarriedGeneratorExit` end it. `drive_async_generator` creates the body coroutine lazily (inside `_adrive`, as `_drive` does) so a generator closed before it starts leaves none.
- [ ] **Step 4: Run** the tests, then `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Async generators: yield in async def"`

### Task 2: `async for`

**Files:**
- Modify: `src/haanim/engine/ast_evaluator.py` (dispatch `ast.AsyncFor` → `_eval_async_for`)
- Modify: `src/haanim/engine/validation.py` (stop rejecting `ast.AsyncFor`)
- Test: `tests/engine/test_async_generators.py`

**Interfaces:**
- Produces: `AstEvaluator._eval_async_for(node: ast.AsyncFor, scope: SymbolTable) -> None`.

- [ ] **Step 1: Write the failing tests**:
  `test_async_for_over_an_automation_generator`;
  `test_async_for_over_a_native_async_iterator` (an automation class with `__aiter__` returning `self` and `async def __anext__` raising `StopAsyncIteration` after 3);
  `test_async_for_break_continue_else`;
  `test_async_for_over_a_non_async_iterable` (`TypeError`);
  `test_break_leaves_the_generator_to_the_finalizer` (Review Focus 3: break after the first item; `del ag`; `gc.collect()` then `await haa.sleep(0)` twice; the generator's `finally` logged — `gc` in `additional_imports`).
- [ ] **Step 2: Run** — Expected: FAIL ("'async for' is not supported").
- [ ] **Step 3: Implement** `_eval_async_for`: `iterator = aiter(await self.aeval(node.iter, scope))`; loop `item = await anext(iterator)` catching `StopAsyncIteration` (then run `orelse`); checkpoint per item; `BreakLoop`/`ContinueLoop` as `_eval_for`.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "async for"`

### Task 3: Async comprehensions and async generator expressions

**Files:**
- Modify: `src/haanim/engine/comprehensions.py` (`walk_comprehension` iterates a clause with `is_async` by `aiter`/`anext`; `generator_expression` returns `drive_async_generator(...)` when any clause is async or the element/conditions contain `await`)
- Modify: `src/haanim/engine/validation.py` (async comprehension allowed only inside `async def`: "asynchronous comprehension outside of an asynchronous function"; remove "async comprehensions are not supported")
- Test: `tests/engine/test_async_generators.py`

**Interfaces:**
- Consumes: `drive_async_generator` (Task 1).

- [ ] **Step 1: Write the failing tests**:
  `test_async_list_set_dict_comprehensions`;
  `test_await_in_element_and_condition`;
  `test_async_generator_expression_is_lazy_and_async` (`inspect.isasyncgen`; consuming only the first item runs the body once);
  `test_async_comprehension_outside_async_def_rejected`;
  `test_sync_comprehension_inside_async_def_with_await` (`[await f(x) for x in range(3)]` — as in Python, a list comprehension with `await` in an `async def` is allowed).
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement.** Detect "contains `await`" with an `ast.walk` over the generator expression not descending into nested function scopes.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Async comprehensions and async generator expressions"`

### Task 4: Documentation

**Files:**
- Modify: `docs/AUTOMATIONS.md` ("Async generators" after "Generators": a runnable example awaiting `haa.sleep()`, consumed with `async for`; remove "Async generators (`yield` in an `async def`) are not supported")
- Modify: `_design.md` (local, gitignored: remove the async bullet)
- Modify: `CHANGELOG.md` (0.4.0 Added: async generators, `async for`, async comprehensions)

- [ ] **Step 1:** Write the example and run it through the harness as a script (it awaits a sleep: drive it with `advance_time`), then through `tests/engine/test_docs.py`.
- [ ] **Step 2: Run** `uv run pytest -q -n auto`, `scripts/test-frontend.sh`, mypy, pyright and pylint on the changed files — Expected: all pass; `ast_evaluator.py` stays under 1000 lines (move code into `comprehensions.py` or `eval_function.py` if needed).
- [ ] **Step 3: Commit** `git commit -m "Docs: async generators"`
