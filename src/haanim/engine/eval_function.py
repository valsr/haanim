"""Functions defined in automation code and executed by the AST evaluator."""

from __future__ import annotations

import ast
import inspect
import types
import weakref
from collections.abc import Callable, Coroutine, Generator
from datetime import datetime
from typing import TYPE_CHECKING, Any

from haanim.engine.symbol_table import SCOPE_FUNCTION, SymbolTable
from haanim.engine.validation import yields_in

if TYPE_CHECKING:
    from haanim.engine.ast_evaluator import AstEvaluator

# How long a function called from outside the interpreter may run before a warning is logged.
NATIVE_CALL_WARNING_SECONDS = 1.0

# A synchronous run of automation code that goes on longer than this is stopped: it blocks the host.
# The step limit also stops it when the clock does not move (in tests).
NATIVE_CALL_LIMIT_SECONDS = 10.0
NATIVE_CALL_STEP_LIMIT = 5_000_000

# Attribute of the Python function that holds the EvalFunction it belongs to.
FUNCTION_ATTRIBUTE = "__haanim_function__"


class ControlFlow(BaseException):
    """Base of the exceptions the evaluator uses for ``return``, ``break`` and ``continue``.

    Derived from BaseException so that ``except Exception`` in automation code
    does not catch them.
    """


class ReturnValue(ControlFlow):
    """Used to propagate return values up the call stack."""

    def __init__(self, value: Any) -> None:
        """Initialize with return value.

        Args:
            value: The value being returned.
        """
        super().__init__()
        self.value = value


class Checkpoint:
    """Awaitable that gives the event loop one turn.

    This is where an action can be suspended, cancelled or timed out without
    an ``await`` in the automation's code. It counts how often it was passed:
    the test harness tells a computing action from a waiting one by it.
    """

    def __init__(self) -> None:
        """Initialize with nothing passed."""
        self.passed = 0

    def __await__(self) -> Generator[None]:
        """Yield to whatever is running the coroutine, once."""
        self.passed += 1
        yield


CHECKPOINT = Checkpoint()


class CarriedStopIteration(Exception):
    """A ``StopIteration`` on its way through the interpreter's frames.

    Python turns a ``StopIteration`` that leaves a coroutine into
    ``RuntimeError`` (PEP 479), and the interpreter's frames are coroutines.
    It travels wrapped in this, and automation code only ever sees ``stop``.
    """

    def __init__(self, stop: StopIteration) -> None:
        """Carry a StopIteration."""
        super().__init__(stop)
        self.stop = stop


class _Yielded:
    """What a generator body hands up through its coroutine at a ``yield``: the value."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        """Hold a yielded value."""
        self.value = value


class YieldPoint:
    """Awaitable for a ``yield`` in a generator body: passes the value up, returns what is sent back."""

    __slots__ = ("value",)

    def __init__(self, value: Any) -> None:
        """Hold the value to yield."""
        self.value = value

    def __await__(self) -> Generator[Any, Any, Any]:
        """Hand the value up to the driving generator; return what is sent back into the body."""
        sent = yield _Yielded(self.value)
        return sent


AUTOMATION_GENERATORS: weakref.WeakSet[Generator[Any, Any, Any]] = weakref.WeakSet()
"""Every generator automation code made: how the interpreter knows its own generators."""


def is_automation_generator(obj: Any) -> bool:
    """Return whether an object is a generator automation code made."""
    try:
        return obj in AUTOMATION_GENERATORS
    except TypeError:  # not hashable, so not a generator
        return False


def drive_generator(
    body: Callable[[], Coroutine[Any, Any, Any]], name: str, watch: NativeCallWatch | None = None
) -> Generator[Any, Any, Any]:
    """Return a Python generator that runs the coroutine of a generator body.

    The body's checkpoints are passed over; each ``yield`` (a ``YieldPoint``)
    hands its value to whoever called ``next()`` or ``send()``; ``send``,
    ``throw`` and ``close`` go back into the body at that ``yield``.
    """
    generator = _drive(body, name, watch)
    AUTOMATION_GENERATORS.add(generator)
    return generator


def _drive(
    body: Callable[[], Coroutine[Any, Any, Any]], name: str, watch: NativeCallWatch | None
) -> Generator[Any, Any, Any]:
    """The generator ``drive_generator`` returns.

    The body's coroutine is made on the first ``next()``: a generator closed
    before it starts leaves no coroutine that was never awaited.
    """
    coro = body()
    value_in: Any = None
    error_in: BaseException | None = None
    while True:
        try:
            message = coro.throw(error_in) if error_in is not None else coro.send(value_in)
        except StopIteration as stop:
            return stop.value
        except CarriedStopIteration as carried:
            # As in Python, a StopIteration leaving a generator body is an error
            raise RuntimeError("generator raised StopIteration") from carried.stop
        value_in, error_in = None, None
        if message is None:
            if watch is not None:
                error_in = watch()
            continue
        if isinstance(message, _Yielded):
            try:
                value_in = yield message.value
                if watch is not None:
                    # Resumed: the limit is on each run between returns to the interpreter
                    watch.restart()
            except GeneratorExit:
                coro.close()
                raise
            except BaseException as err:  # pylint: disable=broad-exception-caught
                error_in = err
            continue
        coro.close()
        raise RuntimeError(f"Generator '{name}' cannot wait for anything")


def run_to_completion(
    coro: Coroutine[Any, Any, Any],
    name: str,
    on_checkpoint: Callable[[], BaseException | None] | None = None,
) -> Any:
    """Run a coroutine of a ``def`` function to its end without an event loop.

    Used when code outside the interpreter calls a function of an automation.
    The body of a ``def`` cannot await, so the coroutine only ever pauses at
    interpreter checkpoints, which are skipped here.

    Args:
        coro: The coroutine to run.
        name: Function name for the error message.
        on_checkpoint: Called at every skipped checkpoint; an error it returns is raised in the code.

    Returns:
        The coroutine's result.

    Raises:
        RuntimeError: If the coroutine waits for something.
    """
    error: BaseException | None = None
    while True:
        try:
            # The watch's error is raised inside the code, so its finally blocks run
            message = coro.throw(error) if error is not None else coro.send(None)
        except StopIteration as done:
            return done.value
        except CarriedStopIteration as carried:
            # Leaving an ordinary function, it reaches the native caller as itself
            raise carried.stop from None
        error = None
        if message is not None:
            coro.close()
            raise RuntimeError(
                f"Function '{name}' cannot wait for anything: it was called from outside the interpreter"
            )
        if on_checkpoint is not None:
            error = on_checkpoint()


class SynchronousRun:
    """Steps and start time of automation code running synchronously, which blocks the event loop."""

    def __init__(self) -> None:
        """Start counting."""
        self.steps = 0
        self.started: datetime | None = None

    def tick(self, clock: Any) -> tuple[int, float]:
        """Count a checkpoint; return the steps and the seconds since the first one (0 without a clock)."""
        self.steps += 1
        if clock is None:
            return self.steps, 0.0
        now = clock.now()
        if self.started is None:
            self.started = now
        return self.steps, (now - self.started).total_seconds()


class NativeSection:
    """The run native code has while the interpreter waits for it to return.

    While native code the interpreter called (``any``, ``sorted``, ...) runs,
    nothing returns to the event loop, however often it pulls a generator or
    calls back into automation code: the watches inside count against this run.
    """

    current: SynchronousRun | None = None
    """The run of the native code running now; None while the interpreter has control."""

    @classmethod
    def enter(cls) -> SynchronousRun | None:
        """Start a run unless one is going on; return the run started, for leave()."""
        if cls.current is not None:
            return None
        cls.current = SynchronousRun()
        return cls.current

    @classmethod
    def leave(cls, run: SynchronousRun | None) -> None:
        """End the run enter() started."""
        if run is not None:
            cls.current = None


class NativeCallWatch:
    """Watches automation code run synchronously, outside the interpreter's control: a call or a generator.

    Such a run does not yield to the event loop, so it blocks the host for as
    long as it takes. It is warned about after ``NATIVE_CALL_WARNING_SECONDS``
    and stopped after ``NATIVE_CALL_LIMIT_SECONDS`` or ``NATIVE_CALL_STEP_LIMIT``
    checkpoints. The time is read at the skipped checkpoints only.

    Inside a native section the run is the section's, whatever the generators
    in it yield; outside one, it is this watch's since it started or restarted.
    """

    def __init__(self, function: Any) -> None:
        """Initialize the watch for one run.

        Args:
            function: What runs: anything with ``name``, ``lineno`` and ``engine``.
        """
        self._function = function
        self._run = SynchronousRun()
        self._warned = False

    def restart(self) -> None:
        """Start counting again: the code returned to the interpreter (a generator yielded)."""
        self._run = SynchronousRun()
        self._warned = False

    def __call__(self) -> BaseException | None:
        """Check at a skipped checkpoint; return the error that stops the run, or None."""
        run = NativeSection.current or self._run
        steps, elapsed = run.tick(self._function.engine.clock)
        if elapsed > NATIVE_CALL_WARNING_SECONDS and not self._warned:
            self._warned = True
            self._function.engine.warn_blocking(self._function)
        if elapsed > NATIVE_CALL_LIMIT_SECONDS or steps > NATIVE_CALL_STEP_LIMIT:
            return TimeoutError(
                f"function '{self._function.name}' ran for more than {NATIVE_CALL_LIMIT_SECONDS:g} seconds "
                "without returning to the interpreter, and was stopped: it blocks Home Assistant while it runs"
            )
        return None


class EvalFunction:
    """A function, method or lambda defined in an automation.

    ``function`` is the Python callable that automation code and Python itself
    see. For ``async def`` it is a coroutine function. For ``def`` and lambdas
    it is a plain function that runs the body to completion; the interpreter
    bypasses it and awaits ``invoke()`` directly so the body runs as a
    coroutine on the event loop.
    """

    def __init__(
        self,
        name: str,
        args: ast.arguments,
        body: list[ast.stmt] | ast.expr,
        *,
        engine: AstEvaluator,
        closure: SymbolTable,
        is_async: bool = False,
        defaults: list[Any] | None = None,
        kw_defaults: dict[str, Any] | None = None,
        doc: str | None = None,
        lineno: int | None = None,
    ) -> None:
        """Initialize an evaluated function.

        Args:
            name: Function name.
            args: AST arguments node.
            body: The statements of the function body, or the expression of a lambda.
            engine: The AstEvaluator instance.
            closure: The symbol table at function definition time.
            is_async: Whether this is an async function.
            defaults: Values of the positional defaults, evaluated at definition.
            kw_defaults: Values of the keyword-only defaults, evaluated at definition.
            doc: The function's docstring.
            lineno: Line the function is defined on.
        """
        self.name = name
        self.args = args
        self.body = body
        self.engine = engine
        self.closure = closure
        self.is_async = is_async
        self.lineno = lineno
        self.defaults = defaults or []
        self.kw_defaults = kw_defaults or {}
        self._positional = [arg.arg for arg in (*args.posonlyargs, *args.args)]
        self._keyword_only = [arg.arg for arg in args.kwonlyargs]
        self.is_generator = isinstance(body, list) and bool(yields_in(body))
        self.function = self._build_function(doc)

    def _build_function(self, doc: str | None) -> Callable[..., Any]:
        """Create the Python callable for this function."""
        function: Callable[..., Any]

        if self.is_generator and not self.is_async:

            def generator_function(*args: Any, **kwargs: Any) -> Any:
                return self.make_generator(*args, **kwargs)

            function = generator_function
        elif self.is_async:

            async def async_function(*args: Any, **kwargs: Any) -> Any:
                return await self.invoke(*args, **kwargs)

            function = async_function
        else:

            def sync_function(*args: Any, **kwargs: Any) -> Any:
                return run_to_completion(self.invoke(*args, **kwargs), self.name, NativeCallWatch(self))

            function = sync_function

        function.__name__ = self.name
        function.__qualname__ = self.name
        function.__module__ = self.engine.name
        function.__doc__ = doc
        setattr(function, "__signature__", self._signature())
        setattr(function, FUNCTION_ATTRIBUTE, self)
        return function

    def _signature(self) -> inspect.Signature:
        """Build the signature Python reports for the function."""
        empty = inspect.Parameter.empty
        first_default = len(self._positional) - len(self.defaults)
        posonly = len(self.args.posonlyargs)
        parameters: list[inspect.Parameter] = []

        for index, name in enumerate(self._positional):
            kind = (
                inspect.Parameter.POSITIONAL_ONLY
                if index < posonly
                else inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
            default = self.defaults[index - first_default] if index >= first_default else empty
            parameters.append(inspect.Parameter(name, kind, default=default))
        if self.args.vararg:
            parameters.append(inspect.Parameter(self.args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
        for name in self._keyword_only:
            default = self.kw_defaults.get(name, empty)
            parameters.append(inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default))
        if self.args.kwarg:
            parameters.append(inspect.Parameter(self.args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))

        return inspect.Signature(parameters)

    def bind(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> SymbolTable:
        """Create the local scope of a call with the arguments bound to the parameters.

        Args:
            args: Positional arguments of the call.
            kwargs: Keyword arguments of the call.

        Returns:
            The local scope.

        Raises:
            TypeError: If the arguments do not match the parameters.
        """
        scope = self.closure.create_child(SCOPE_FUNCTION)
        scope.first_arg = args[0] if args else None
        positional = self._positional
        bound: dict[str, Any] = dict(zip(positional, args))

        extra_args = args[len(positional) :]
        if extra_args and not self.args.vararg:
            raise TypeError(
                f"{self.name}() takes {len(positional)} positional arguments but {len(args)} were given"
            )

        extra_kwargs = self._bind_keywords(bound, kwargs)

        first_default = len(positional) - len(self.defaults)
        for index, name in enumerate(positional):
            if name not in bound and index >= first_default:
                bound[name] = self.defaults[index - first_default]
        for name in self._keyword_only:
            if name not in bound and name in self.kw_defaults:
                bound[name] = self.kw_defaults[name]

        missing = [name for name in (*positional, *self._keyword_only) if name not in bound]
        if missing:
            names = ", ".join(f"'{name}'" for name in missing)
            raise TypeError(f"{self.name}() missing required arguments: {names}")

        if self.args.vararg:
            bound[self.args.vararg.arg] = tuple(extra_args)
        if self.args.kwarg:
            bound[self.args.kwarg.arg] = extra_kwargs

        for name, value in bound.items():
            scope.set(name, value)
        return scope

    def _bind_keywords(self, bound: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        """Bind the keyword arguments of a call.

        Args:
            bound: The parameters bound so far; the matching keywords are added.
            kwargs: Keyword arguments of the call.

        Returns:
            The keywords that match no parameter, for ``**kwargs``.
        """
        keyword_names = set(self._positional[len(self.args.posonlyargs) :]) | set(self._keyword_only)
        extra_kwargs: dict[str, Any] = {}
        for name, value in kwargs.items():
            if name in keyword_names:
                if name in bound:
                    raise TypeError(f"{self.name}() got multiple values for argument '{name}'")
                bound[name] = value
            elif self.args.kwarg:
                extra_kwargs[name] = value
            else:
                raise TypeError(f"{self.name}() got an unexpected keyword argument '{name}'")
        return extra_kwargs

    def make_generator(self, *args: Any, **kwargs: Any) -> Any:
        """Return the generator a call of a generator function gives: nothing of the body runs yet."""
        scope = self.bind(args, kwargs)
        return drive_generator(lambda: self._run_body(scope), self.name, NativeCallWatch(self))

    async def _run_body(self, scope: SymbolTable) -> Any:
        """Run a generator's body; its ``return`` value ends the generator."""
        try:
            for stmt in self.body:  # type: ignore[union-attr]
                await self.engine.aeval(stmt, scope)
        except ReturnValue as ret:
            return ret.value
        return None

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Run the function body on the event loop.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The function return value.
        """
        scope = self.bind(args, kwargs)
        if self.engine.checkpoint_due():
            await CHECKPOINT

        if isinstance(self.body, ast.expr):
            return await self.engine.aeval(self.body, scope)

        try:
            for stmt in self.body:
                await self.engine.aeval(stmt, scope)
        except ReturnValue as ret:
            return ret.value
        return None


def get_eval_function(func: Any) -> tuple[EvalFunction, tuple[Any, ...]] | None:
    """Return the EvalFunction behind a callable, if it is defined in an automation.

    Args:
        func: Any callable. A function or a bound method.

    Returns:
        The EvalFunction and the arguments to put before the call's own (the
        instance, for a bound method), or None for any other callable.
    """
    target = func
    prefix: tuple[Any, ...] = ()
    if isinstance(func, types.MethodType):
        target = func.__func__
        prefix = (func.__self__,)

    if not isinstance(target, types.FunctionType):
        return None
    eval_function = target.__dict__.get(FUNCTION_ATTRIBUTE)
    # functools.wraps copies the attribute onto wrappers, which are not the function.
    if isinstance(eval_function, EvalFunction) and eval_function.function is target:
        return eval_function, prefix
    return None
