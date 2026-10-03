"""Functions defined in automation code and executed by the AST evaluator."""

from __future__ import annotations

import ast
import inspect
import types
from collections.abc import Callable, Coroutine
from typing import TYPE_CHECKING, Any

from haanim.engine.symbol_table import SCOPE_FUNCTION, SymbolTable

if TYPE_CHECKING:
    from haanim.engine.ast_evaluator import AstEvaluator

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


def run_to_completion(coro: Coroutine[Any, Any, Any], name: str) -> Any:
    """Run a coroutine of a ``def`` function to its end without an event loop.

    Used when code outside the interpreter calls a function of an automation.
    The body of a ``def`` cannot await, so the coroutine only ever pauses at
    interpreter checkpoints, which are skipped here.

    Args:
        coro: The coroutine to run.
        name: Function name for the error message.

    Returns:
        The coroutine's result.

    Raises:
        RuntimeError: If the coroutine waits for something.
    """
    try:
        while True:
            if coro.send(None) is not None:
                coro.close()
                raise RuntimeError(
                    f"Function '{name}' cannot wait for anything: it was called from outside the interpreter"
                )
    except StopIteration as stop:
        return stop.value


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
        """
        self.name = name
        self.args = args
        self.body = body
        self.engine = engine
        self.closure = closure
        self.is_async = is_async
        self.defaults = defaults or []
        self.kw_defaults = kw_defaults or {}
        self._positional = [arg.arg for arg in (*args.posonlyargs, *args.args)]
        self._keyword_only = [arg.arg for arg in args.kwonlyargs]
        self.function = self._build_function(doc)

    def _build_function(self, doc: str | None) -> Callable[..., Any]:
        """Create the Python callable for this function."""
        function: Callable[..., Any]

        if self.is_async:

            async def async_function(*args: Any, **kwargs: Any) -> Any:
                return await self.invoke(*args, **kwargs)

            function = async_function
        else:

            def sync_function(*args: Any, **kwargs: Any) -> Any:
                return run_to_completion(self.invoke(*args, **kwargs), self.name)

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

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        """Run the function body on the event loop.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The function return value.
        """
        scope = self.bind(args, kwargs)

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
