# Generators Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automation code defines and uses lazy generators (`yield`, `yield from`, generator expressions) with Python's semantics, without being able to freeze Home Assistant.

**Architecture:** A generator function's call returns a real Python generator (`drive_generator`) that steps the body's interpreter coroutine, passing checkpoints over and handing each `yield` (a `YieldPoint` awaitable) to the consumer. The interpreter drains automation generators passed to consume-all builtins with checkpoints between items, every synchronous run gets a hard limit, and `StopIteration` is carried across interpreter frames so it behaves as in Python.

**Tech Stack:** Python 3.14, HAAnim's AST interpreter (`src/haanim/engine`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-10-generators-design.md`
**Spike (reference only, do not merge):** branch `spike-generators`, commit `08144d7` — `drive_generator`, `YieldPoint`, `_eval_yield*` there are a working starting point.

## Global Constraints

- Supported: `yield`, `yield from` in `def` functions and methods; generator expressions. Rejected with file and line: `yield`/`yield from` in a lambda ("'yield' in a lambda is not supported: use a def"); in an `async def` ("async generators are not supported").
- Generator objects are real Python generators (`inspect.isgenerator` true), registered in a module-level `weakref.WeakSet` (`AUTOMATION_GENERATORS`).
- Drained calls: `list`, `tuple`, `set`, `frozenset`, `dict`, `sorted`, `sum` (first positional argument); `min`, `max` (only when that is the only positional argument); `str.join` (its argument). Nothing else is drained.
- Hard limit: `NATIVE_CALL_LIMIT_SECONDS = 10.0` (host clock) or `NATIVE_CALL_STEP_LIMIT = 5_000_000` checkpoints; message (exact): `function '<name>' ran for more than 10 seconds without returning to the interpreter, and was stopped: it blocks Home Assistant while it runs`, raised as `TimeoutError` inside the running code. Warning at `NATIVE_CALL_WARNING_SECONDS` (1.0) unchanged.
- `StopIteration` from a generator body → `RuntimeError("generator raised StopIteration")`.
- No real time in the engine or its tests (`tests/engine/test_no_real_time.py`).

## Review Focus

1. **A generator abandoned while suspended (action cancelled during `list(forever())`):** its `finally` blocks run (the drain closes it). Test in Task 3.
2. **An exhausted generator used again:** `next(g)` raises `StopIteration` (catchable), `list(g)` is `[]`. Test in Task 1 (re-use) and Task 2 (catchable).
3. **An exception inside a generator body:** reaches the consumer as the same type with its message, in interpreter loops and in native consumers. Test in Task 1.
4. **A drained call whose generator raises midway:** the exception propagates and nothing partial is returned. Test in Task 3.
5. **A generator suspended at a `yield` inside `try/except Exception`, then closed:** `GeneratorExit` is not swallowed by `except Exception` (it is a `BaseException`), so `close()` completes. Test in Task 1.

---

### Task 1: Generator functions, `yield from` and generator expressions

**Files:**
- Modify: `src/haanim/engine/eval_function.py` (`YieldPoint`, `drive_generator`, `AUTOMATION_GENERATORS`, `EvalFunction.is_generator`, `EvalFunction.make_generator`, `_has_yield`)
- Modify: `src/haanim/engine/ast_evaluator.py` (dispatch `ast.Yield`, `ast.YieldFrom`, `ast.GeneratorExp`; `call()` returns `make_generator(...)` for generator functions)
- Modify: `src/haanim/engine/callables.py` (an action or handler that is a generator function: calling it returns the generator, as in Python)
- Modify: `src/haanim/engine/validation.py` (stop rejecting the three nodes; add the lambda and `async def` rules)
- Modify: the tests that use `yield` as their unsupported example — `tests/engine/test_validation.py`, `test_discovery.py`, `test_lifecycle.py`, `test_guard_rails.py`, `test_interpreter.py` — switch them to `match x:\n    case 1:\n        pass` with the message "'match' statements are not supported"
- Test: `tests/engine/test_generators.py` (new; harness-driven with a `tmp_path` automation, like `tests/engine/test_device_api.py`)

**Interfaces:**
- Produces:
  - `class YieldPoint` (awaitable; `__await__` yields a private `_Yielded(value)` and returns what is sent back).
  - `drive_generator(coro: Coroutine[Any, Any, Any], name: str, on_checkpoint: Callable[[], None] | None = None) -> Generator[Any, Any, Any]` — adds the generator to `AUTOMATION_GENERATORS` before returning it (wrap: an inner generator function, created, registered, returned).
  - `is_automation_generator(obj: Any) -> bool`.
  - `EvalFunction.is_generator: bool`, `EvalFunction.make_generator(*args, **kwargs) -> Generator`.

- [ ] **Step 1: Write the failing tests** — each a small automation `main.py` with an `@action` returning the value checked:
  `test_list_sum_sorted` (`list(count_up(5)) == [0..4]`, `sum(count_up(101)) == 5050`, `sorted(count_up(4), reverse=True)`);
  `test_for_loop_and_comprehension`; `test_lazy_infinite_with_islice` (`list(itertools.islice(forever(), 5))`);
  `test_send` (echo generator: `next`, two `send`s, `next(gen, "ended") == "ended"`, the returned list via `yield from` in a wrapper);
  `test_throw` (`gen.throw(ValueError("x"))` caught at the `yield` inside the body, which yields `"caught"`);
  `test_close_runs_finally`; `test_close_with_except_exception_around_yield` (Review Focus 5);
  `test_return_value_and_yield_from` (`list(outer()) == ["a", "b", "done"]`);
  `test_generator_expression` (`sum(x*x for x in range(10)) == 285`, `",".join(str(x) for x in range(4) if x % 2 == 0) == "0,2"`, `any(x > 3 for x in forever())`);
  `test_generator_method_and_iter` (`list(Tree([1, 2])) == [10, 20]`);
  `test_body_exception_reaches_consumer` (Review Focus 3: `ValueError("bad")` from the body, caught in automation code around a `for` loop and around `list(...)`);
  `test_exhausted_generator` (Review Focus 2: `list(g)` twice → second `[]`);
  `test_closed_before_start` (`g.close()` then `list(g) == []`, no body code ran);
  `test_nested_generators` (generator yielding from a generator expression over another generator);
  `test_is_a_real_generator` (`inspect.isgenerator(count_up(1))` — add `inspect` to an automation's `additional_imports` in the harness);
  `test_yield_in_lambda_rejected`, `test_async_generator_rejected` (load error messages per Global Constraints).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_generators.py -q --no-cov -n 0` — Expected: FAIL (load errors "'yield' is not supported").
- [ ] **Step 3: Implement** per Interfaces. `_has_yield(body)` walks the body, not descending into `FunctionDef`, `AsyncFunctionDef`, `Lambda`, `ClassDef`. `drive_generator`: on a `_Yielded` message yield its value; `GeneratorExit` → `coro.close()` and re-raise; any other exception thrown in → `coro.throw(err)`; a message that is neither `None` nor `_Yielded` → `coro.close()`, `RuntimeError(f"Generator '{name}' cannot wait for anything")`. Generator expressions build a body coroutine over the comprehension (use `SCOPE_COMPREHENSION` scopes like `_eval_list_comprehension`) and return `drive_generator(body, "<genexpr>")`.
- [ ] **Step 4: Run** the tests, then `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS (validation tests switched to `match`).
- [ ] **Step 5: Commit** `git commit -m "Generators: yield, yield from and generator expressions in automations"`

### Task 2: `StopIteration` behaves as in Python

**Files:**
- Modify: `src/haanim/engine/eval_function.py` (`CarriedStopIteration`; unwrap at `run_to_completion`, `drive_generator`/`_run_body`)
- Modify: `src/haanim/engine/ast_evaluator.py` (`call()` and `_eval_raise` wrap; `_handle_exception` unwraps for matching and `as` binding)
- Modify: `src/haanim/engine/callables.py` (an action whose code lets one escape: `RuntimeError("action raised StopIteration")`)
- Test: `tests/engine/test_generators.py`

**Interfaces:**
- Produces: `class CarriedStopIteration(Exception)` with attribute `stop: StopIteration` — never seen by automation code.

- [ ] **Step 1: Write the failing tests**:
  `test_stop_iteration_is_caught` (`try: next(iter([])) except StopIteration: return "caught"`);
  `test_stop_iteration_value` (generator returning 7; `try: next(g) except StopIteration as stop: return stop.value` → 7);
  `test_except_exception_catches_it`;
  `test_raise_stop_iteration_statement_is_caught`;
  `test_stop_iteration_reaches_a_native_caller` (`list(map(f, [1, 2]))` where the automation's `f` raises `StopIteration` → `[]`: `map` passes it on and `list` stops, as in Python);
  `test_stop_iteration_leaving_a_generator_body_is_runtime_error` (`RuntimeError`, message "generator raised StopIteration").
- [ ] **Step 2: Run** — Expected: FAIL (`RuntimeError: coroutine raised StopIteration`).
- [ ] **Step 3: Implement.** In `call()`: `except StopIteration as stop: raise CarriedStopIteration(stop) from None` around both the `invoke` path and the native call. `_eval_raise`: a `StopIteration` instance (or class) is raised as `CarriedStopIteration`. `_handle_exception`: match and bind `err.stop` when `err` is a `CarriedStopIteration`. `run_to_completion`: on `CarriedStopIteration` raise `err.stop`. Generator body (`_run_body` / genexp body): on `CarriedStopIteration` raise `RuntimeError("generator raised StopIteration")`.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "StopIteration in automation code behaves as in Python"`

### Task 3: Drain automation generators in consume-all calls

**Files:**
- Modify: `src/haanim/engine/ast_evaluator.py` (`call()` → `await self._drain_arguments(func, args)` before calling a native function; `_drain(generator) -> list`)
- Test: `tests/engine/test_generators.py`

**Interfaces:**
- Consumes: `is_automation_generator` (Task 1).
- Produces: `DRAINED_FIRST_ARGUMENT = frozenset({builtins.list, builtins.tuple, builtins.set, builtins.frozenset, builtins.dict, builtins.sorted, builtins.sum})`, `DRAINED_ONLY_ARGUMENT = frozenset({builtins.min, builtins.max})` in `ast_evaluator.py`; `str.join` recognised as `getattr(func, "__self__", None)` being a `str` and `func.__name__ == "join"`.

- [ ] **Step 1: Write the failing tests**:
  `test_drained_calls_give_python_results` (parametrized over every drained call, including `min`/`max` with `key=` and `sum(g, 10)`, `dict` of pairs, `"-".join`);
  `test_list_of_infinite_generator_is_cancelled_by_the_timeout` (`@action(timeout=2)` returning `list(forever())`; `call` via `asyncio.ensure_future`, `await h.advance_time(seconds=3)` → `ActionTimeOutError`);
  `test_other_actions_run_while_draining` (a second action called during the drain returns);
  `test_drain_closes_the_generator_on_cancellation` (Review Focus 1: the generator's `finally` appends to a module list; after the timeout the list has the entry);
  `test_generator_raising_midway_in_a_drained_call` (Review Focus 4: `ValueError` propagates);
  `test_min_with_two_arguments_is_not_drained` (`min(g1, g2)` compares the generator objects → `TypeError`, as in Python);
  `test_any_on_infinite_generator_stops_early`.
- [ ] **Step 2: Run** — Expected: FAIL (the timeout test hangs: run it with `pytest --timeout=20`; `pytest-timeout` is installed).
- [ ] **Step 3: Implement.** `_drain`: loop `next(generator)` with `if self.checkpoint_due(): await CHECKPOINT` between items, catching `StopIteration` inside the loop; on `BaseException` (including `CancelledError`) call `generator.close()` and re-raise.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Consume-all calls drain automation generators with checkpoints"`

### Task 4: Hard limit on synchronous runs

**Files:**
- Modify: `src/haanim/engine/eval_function.py` (`NATIVE_CALL_LIMIT_SECONDS`, `NATIVE_CALL_STEP_LIMIT`; `NativeCallWatch` counts steps and returns the `TimeoutError` to raise; `run_to_completion` and `drive_generator` throw it into the coroutine)
- Test: `tests/engine/test_generators.py`

**Interfaces:**
- Produces: `NativeCallWatch.__call__() -> BaseException | None` (was `None`): the error to throw at this checkpoint, or None. The time check reads `engine.clock` as today; the step check needs no clock.

- [ ] **Step 1: Write the failing tests** (monkeypatch `eval_function.NATIVE_CALL_STEP_LIMIT` to `10_000` so they are fast):
  `test_infinite_generator_pulled_by_any_hits_the_limit` (`any(x < 0 for x in forever())` → `TimeoutError` whose message is the exact copy from Global Constraints with the function name `<genexpr>` or `forever`);
  `test_endless_sorted_key_function_hits_the_limit` (a `key=` function with `while True: pass`);
  `test_finally_runs_when_the_limit_stops_it`;
  `test_time_limit` (a fake clock the watch reads that advances 11 seconds between checkpoints: build the `NativeCallWatch` with an engine whose `clock` is a stub returning increasing times; unit test on `NativeCallWatch` itself);
  `test_warning_still_logged_after_one_second` (existing behaviour; unit test on the watch).
- [ ] **Step 2: Run** — Expected: FAIL (hangs without the limit: run with `--timeout=20`).
- [ ] **Step 3: Implement.** In `run_to_completion` and `drive_generator`, when `on_checkpoint()` returns an error, the next step is `coro.throw(error)` instead of `coro.send(...)`; the coroutine's `finally` runs; if the error comes back out it propagates.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Synchronous runs of automation code stop after 10 seconds"`

### Task 5: Documentation

**Files:**
- Modify: `docs/AUTOMATIONS.md` ("Imports and Python": remove "Generators (`yield`) are not supported"; add a "Generators" paragraph with one runnable example and the drained calls and 10-second limit)
- Modify: `_design.md` ("Supported Python": remove the generators bullet; the `async for` bullet becomes "async generators, `async for` and async comprehensions")
- Modify: `CHANGELOG.md` (0.4.0 Added: generators; Fixed: `except StopIteration`, synchronous runs stopped after 10 seconds)

- [ ] **Step 1:** Write the docs example (a generator function used with `sum` and a `for` loop) — it runs in `tests/engine/test_docs.py`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_docs.py -q --no-cov -n auto` — Expected: PASS.
- [ ] **Step 3: Run** the full suite `uv run pytest -q -n auto`, `scripts/test-frontend.sh`, mypy, pyright and pylint on the changed files — Expected: all pass.
- [ ] **Step 4: Commit** `git commit -m "Docs: generators"`
