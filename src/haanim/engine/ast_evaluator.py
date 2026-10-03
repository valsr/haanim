"""Interpreter that executes automation source by walking its AST."""

from __future__ import annotations

import ast
import inspect
import logging
import sys
import types
import typing
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from haanim.engine.eval_function import (
    CHECKPOINT,
    ControlFlow,
    EvalFunction,
    ReturnValue,
    NATIVE_CALL_WARNING_SECONDS,
    get_eval_function,
)
from haanim.engine import operators
from haanim.engine.automation_module import ModuleLoader
from haanim.engine.import_controller import ImportController
from haanim.engine.safe_builtins import SafeBuiltins
from haanim.engine.symbol_table import SCOPE_CLASS, SCOPE_COMPREHENSION, SCOPE_MODULE, SymbolTable
from haanim.engine.errors import (
    HAAnimError,
    AutomationRuntimeError,
    AutomationSecurityError,
)
from haanim.engine.validation import validate_source

if TYPE_CHECKING:
    from haanim.interfaces import Clock, FileSystem

_LOGGER = logging.getLogger(__name__)

# Yield to the event loop at every this many checkpoints.
DEFAULT_CHECKPOINT_INTERVAL = 1


class BreakLoop(ControlFlow):
    """Used to break out of loops."""


class ContinueLoop(ControlFlow):
    """Used to continue to next iteration."""


class AstEvaluator:
    """AST-based Python code evaluator with security restrictions."""

    def __init__(
        self,
        name: str,
        *,
        global_symbols: SymbolTable | None = None,
        import_controller: ImportController | None = None,
        safe_builtins: SafeBuiltins | None = None,
        logger: logging.Logger | None = None,
        files: FileSystem | None = None,
        path: Path | None = None,
        loader: ModuleLoader | None = None,
        clock: Clock | None = None,
        checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL,
    ) -> None:
        """Initialize the AST evaluator.

        Args:
            name: Name of the automation being evaluated.
            global_symbols: Global symbol table for the automation.
            import_controller: Controller for safe imports.
            safe_builtins: Provider of safe builtin functions.
            logger: Logger instance for this evaluator.
            files: File system to read relatively imported files from. Without
                it relative imports are not available.
            path: Path of the file being evaluated; relative imports are
                resolved against its directory and must stay within it.
            loader: The loader shared by the files of an automation. Created
                from ``files`` and ``path`` if omitted.
            clock: Clock used to notice functions that block the event loop.
                Without it no such warning is logged.
            checkpoint_interval: Yield to the event loop at every this many
                checkpoints.
        """
        self.name = name
        self._logger = logger or _LOGGER
        self._import_controller = import_controller or ImportController()
        self._safe_builtins = safe_builtins or SafeBuiltins()
        self._global_symbols = global_symbols or SymbolTable()
        self._ast: ast.Module | None = None
        self._source: str | None = None
        self._filename = "<automation>"
        self._files = files
        self._path = path
        self.loader = loader
        if loader is None and files is not None and path is not None:
            self.loader = ModuleLoader(name, files, path.parent, self._run_module)
        self.clock = clock
        self._checkpoint_interval = max(1, checkpoint_interval)
        self._checkpoints = 0

        # Add builtins to global scope
        for builtin_name, value in self._safe_builtins.get_builtins().items():
            self._global_symbols.set(builtin_name, value)
        if not self._global_symbols.exists("__name__"):
            self._global_symbols.set("__name__", name)

        # Register evaluators
        self._evaluators: dict[type[ast.AST], Callable[[Any, SymbolTable], Any]] = {
            # Expression evaluators
            ast.Constant: self._eval_constant,
            ast.Name: self._eval_name,
            ast.Attribute: self._eval_attribute,
            ast.Subscript: self._eval_subscript,
            ast.Slice: self._eval_slice,
            ast.List: self._eval_list,
            ast.Tuple: self._eval_tuple,
            ast.Dict: self._eval_dict,
            ast.Set: self._eval_set,
            ast.BinOp: self._eval_binary_operation,
            ast.BoolOp: self._eval_bool_operator,
            ast.UnaryOp: self._eval_unary_operator,
            ast.Compare: self._eval_compare,
            ast.IfExp: self._eval_if_expression,
            ast.Call: self._eval_call,
            ast.Lambda: self._eval_lambda,
            ast.ListComp: self._eval_list_comprehension,
            ast.SetComp: self._eval_set_comprehension,
            ast.DictComp: self._eval_dict_comprehension,
            ast.JoinedStr: self._eval_joined_str,
            ast.FormattedValue: self._eval_formatted_value,
            ast.Module: self._eval_module,
            ast.Expr: self._eval_expression,
            ast.Assign: self._eval_assign,
            ast.AnnAssign: self._eval_annotated_assignment,
            ast.AugAssign: self._eval_augmented_assignment,
            ast.If: self._eval_if,
            ast.For: self._eval_for,
            ast.While: self._eval_while,
            ast.Break: self._eval_break,
            ast.Continue: self._eval_continue,
            ast.Return: self._eval_return,
            ast.FunctionDef: self._eval_function_def,
            ast.AsyncFunctionDef: self._eval_async_function_def,
            ast.ClassDef: self._eval_class_def,
            ast.Import: self._eval_import,
            ast.ImportFrom: self._eval_import_from,
            ast.Pass: self._eval_pass,
            ast.Raise: self._eval_raise,
            ast.Try: self._eval_try,
            ast.With: self._eval_with,
            ast.AsyncWith: self._eval_async_with,
            ast.Await: self._eval_await,
            ast.Assert: self._eval_assert,
            ast.Delete: self._eval_delete,
            ast.Global: self._eval_global,
            ast.Nonlocal: self._eval_nonlocal,
            ast.NamedExpr: self._eval_named_expression,
            ast.TypeAlias: self._eval_type_alias,
        }

    def parse(self, source: str, filename: str = "<automation>") -> None:
        """Parse Python source code into an AST.

        Args:
            source: Python source code.
            filename: Filename for error messages.

        Raises:
            AutomationSyntaxError: If the source has syntax errors or uses
                Python the interpreter does not support.
            AutomationSecurityError: If the source uses a disallowed import or
                builtin.
        """
        self._source = source
        self._filename = filename
        self._ast = validate_source(
            source,
            filename=filename,
            imports=self._import_controller,
            restricted_builtins=self._safe_builtins.restricted,
        )

    async def execute(self) -> dict[str, Any]:
        """Execute the parsed AST.

        Returns:
            Dictionary of names defined in the automation (functions, variables, etc.)

        Raises:
            AutomationRuntimeError: If execution fails.
        """
        if self._ast is None:
            raise AutomationRuntimeError("No AST to execute. Call parse() first.")

        try:
            for node in self._ast.body:
                await self.aeval(node, self._global_symbols)
        except Exception as err:
            if isinstance(err, HAAnimError):
                self._logger.error("Automation execution error: %s", err)
                raise
            self._logger.exception("Unexpected error during automation execution")
            raise AutomationRuntimeError(f"Runtime error: {err}") from err

        return self._global_symbols.as_dict()

    def checkpoint_due(self) -> bool:
        """Count a checkpoint and return whether to yield to the event loop at it.

        Checkpoints are every loop iteration and every call of a function of
        the automation. Use as ``if self.checkpoint_due(): await CHECKPOINT``.
        """
        self._checkpoints += 1
        if self._checkpoints < self._checkpoint_interval:
            return False
        self._checkpoints = 0
        return True

    def warn_blocking(self, function: EvalFunction) -> None:
        """Log that a function called from outside the interpreter has been running long."""
        self._logger.warning(
            "%s:%s: function '%s' of automation '%s' has been running for more than %g second"
            " without yielding; it was called from outside the interpreter and blocks Home Assistant"
            " until it returns",
            self._filename,
            function.lineno,
            function.name,
            self.name,
            NATIVE_CALL_WARNING_SECONDS,
        )

    async def aeval(self, node: ast.AST, scope: SymbolTable) -> Any:
        """Asynchronously evaluate an AST node.

        Args:
            node: The AST node to evaluate.
            scope: The current symbol table scope.

        Returns:
            The result of evaluating the node.
        """
        method: Callable[[Any, SymbolTable], Any] | None = self._evaluators.get(type(node), None)

        if method is None:
            raise AutomationRuntimeError(
                f"Unsupported AST node type: {node.__class__.__name__}",
                lineno=getattr(node, "lineno", None),
            )

        return await method(node, scope)

    # -------------------------------------------------------------------------
    # Expression evaluators
    # -------------------------------------------------------------------------
    async def _eval_constant(self, node: ast.Constant, _: SymbolTable) -> Any:
        """Evaluate a constant value."""
        return node.value

    async def _eval_name(self, node: ast.Name, scope: SymbolTable) -> Any:
        """Evaluate a name reference."""
        name = node.id
        if scope.exists(name):
            return scope.get(name)
        if name in self._safe_builtins.restricted:
            raise AutomationSecurityError(f"Builtin '{name}' is not available in automations")
        raise NameError(f"name '{name}' is not defined")

    async def _eval_attribute(self, node: ast.Attribute, scope: SymbolTable) -> Any:
        """Evaluate an attribute access."""
        obj = await self.aeval(node.value, scope)
        return getattr(obj, node.attr)

    async def _eval_subscript(self, node: ast.Subscript, scope: SymbolTable) -> Any:
        """Evaluate a subscript operation."""
        obj = await self.aeval(node.value, scope)
        index = await self.aeval(node.slice, scope)
        return obj[index]

    async def _eval_slice(self, node: ast.Slice, scope: SymbolTable) -> Any:
        """Evaluate a slice."""
        lower = await self.aeval(node.lower, scope) if node.lower else None
        upper = await self.aeval(node.upper, scope) if node.upper else None
        step = await self.aeval(node.step, scope) if node.step else None
        return slice(lower, upper, step)

    async def _eval_elements(self, elts: list[ast.expr], scope: SymbolTable) -> list[Any]:
        """Evaluate the elements of a display or the arguments of a call, unpacking ``*`` elements."""
        values: list[Any] = []
        for elt in elts:
            if isinstance(elt, ast.Starred):
                values.extend(await self.aeval(elt.value, scope))
            else:
                values.append(await self.aeval(elt, scope))
        return values

    async def _eval_list(self, node: ast.List, scope: SymbolTable) -> list[Any]:
        """Evaluate a list literal."""
        return await self._eval_elements(node.elts, scope)

    async def _eval_tuple(self, node: ast.Tuple, scope: SymbolTable) -> tuple[Any, ...]:
        """Evaluate a tuple literal."""
        return tuple(await self._eval_elements(node.elts, scope))

    async def _eval_dict(self, node: ast.Dict, scope: SymbolTable) -> dict[Any, Any]:
        """Evaluate a dict literal."""
        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values):
            if key is None:
                # Handle dict unpacking **d
                d = await self.aeval(value, scope)
                result.update(d)
            else:
                k = await self.aeval(key, scope)
                v = await self.aeval(value, scope)
                result[k] = v
        return result

    async def _eval_set(self, node: ast.Set, scope: SymbolTable) -> set[Any]:
        """Evaluate a set literal."""
        return set(await self._eval_elements(node.elts, scope))

    async def _eval_binary_operation(self, node: ast.BinOp, scope: SymbolTable) -> Any:
        """Evaluate a binary operation."""
        left = await self.aeval(node.left, scope)
        right = await self.aeval(node.right, scope)
        return operators.BINARY[type(node.op)](left, right)

    async def _eval_unary_operator(self, node: ast.UnaryOp, scope: SymbolTable) -> Any:
        """Evaluate a unary operation."""
        return operators.UNARY[type(node.op)](await self.aeval(node.operand, scope))

    async def _eval_bool_operator(self, node: ast.BoolOp, scope: SymbolTable) -> Any:
        """Evaluate a boolean operation (and/or).

        As in Python, the result is the operand that decided it, not a bool.
        """
        stop_on = isinstance(node.op, ast.Or)
        result: Any = None
        for value in node.values:
            result = await self.aeval(value, scope)
            if bool(result) is stop_on:
                break
        return result

    async def _eval_compare(self, node: ast.Compare, scope: SymbolTable) -> bool:
        """Evaluate a comparison."""
        left = await self.aeval(node.left, scope)

        ops: dict[type[ast.cmpop], Callable[[Any, Any], bool]] = {
            ast.Eq: lambda a, b: a == b,
            ast.NotEq: lambda a, b: a != b,
            ast.Lt: lambda a, b: a < b,
            ast.LtE: lambda a, b: a <= b,
            ast.Gt: lambda a, b: a > b,
            ast.GtE: lambda a, b: a >= b,
            ast.Is: lambda a, b: a is b,
            ast.IsNot: lambda a, b: a is not b,
            ast.In: lambda a, b: a in b,
            ast.NotIn: lambda a, b: a not in b,
        }

        for op, comparator in zip(node.ops, node.comparators):
            right = await self.aeval(comparator, scope)
            op_func = ops.get(type(op))
            if op_func is None:
                raise AutomationRuntimeError(f"Unsupported comparison operator: {type(op).__name__}")
            if not op_func(left, right):
                return False
            left = right

        return True

    async def _eval_if_expression(self, node: ast.IfExp, scope: SymbolTable) -> Any:
        """Evaluate a conditional expression (ternary)."""
        test = await self.aeval(node.test, scope)
        if test:
            return await self.aeval(node.body, scope)
        return await self.aeval(node.orelse, scope)

    async def _eval_call(self, node: ast.Call, scope: SymbolTable) -> Any:
        """Evaluate a function call."""
        func = await self.aeval(node.func, scope)

        # Evaluate arguments
        args = await self._eval_elements(node.args, scope)
        kwargs: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                # **kwargs unpacking
                kwargs.update(await self.aeval(keyword.value, scope))
            else:
                kwargs[keyword.arg] = await self.aeval(keyword.value, scope)

        if not args and not kwargs:
            if func is super:
                # super() without arguments needs the class and instance of the calling method.
                return super(scope.get("__class__"), scope.enclosing_first_arg())
            if func is dir:
                # Without arguments these describe the caller's scope, which lives in the interpreter.
                return sorted(scope.function_scope().own_symbols())
            if func is vars:
                return scope.function_scope().own_symbols()

        return await self.call(func, *args, **kwargs)

    async def call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        """Call a callable the way the interpreter calls it.

        A ``def`` function of an automation is run as a coroutine on the event
        loop. Everything else is called directly; as in Python, calling an
        async function gives a coroutine that the caller has to await.

        Args:
            func: The callable.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            What the call returns.
        """
        found = get_eval_function(func)
        if found is not None and not found[0].is_async:
            eval_function, prefix = found
            return await eval_function.invoke(*prefix, *args, **kwargs)
        return func(*args, **kwargs)

    async def _make_function(
        self,
        name: str,
        args: ast.arguments,
        body: list[ast.stmt] | ast.expr,
        scope: SymbolTable,
        *,
        is_async: bool = False,
        lineno: int | None = None,
    ) -> Callable[..., Any]:
        """Create the Python callable for a function definition or lambda.

        Defaults are evaluated here, once, as in Python.
        """
        defaults = [await self.aeval(default, scope) for default in args.defaults]
        kw_defaults = {
            arg.arg: await self.aeval(default, scope)
            for arg, default in zip(args.kwonlyargs, args.kw_defaults)
            if default is not None
        }
        doc = None
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr):
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                doc = inspect.cleandoc(value.value)

        return EvalFunction(
            name=name,
            args=args,
            body=body,
            engine=self,
            closure=scope.closure_scope(),
            is_async=is_async,
            defaults=defaults,
            kw_defaults=kw_defaults,
            doc=doc,
            lineno=lineno,
        ).function

    async def _define(
        self, name: str, value: Any, decorator_list: list[ast.expr], scope: SymbolTable
    ) -> None:
        """Apply the decorators of a function or class definition and bind its name."""
        decorators = [await self.aeval(decorator, scope) for decorator in decorator_list]
        for decorator in reversed(decorators):
            value = await self.call(decorator, value)
        scope.set(name, value)

    async def _eval_lambda(self, node: ast.Lambda, scope: SymbolTable) -> Callable[..., Any]:
        """Evaluate a lambda expression."""
        return await self._make_function("<lambda>", node.args, node.body, scope, lineno=node.lineno)

    async def _eval_list_comprehension(self, node: ast.ListComp, scope: SymbolTable) -> list[Any]:
        """Evaluate a list comprehension."""
        return list(await self._eval_comprehension(node, scope))

    async def _eval_set_comprehension(self, node: ast.SetComp, scope: SymbolTable) -> set[Any]:
        """Evaluate a set comprehension."""
        return set(await self._eval_comprehension(node, scope))

    async def _eval_dict_comprehension(self, node: ast.DictComp, scope: SymbolTable) -> dict[Any, Any]:
        """Evaluate a dict comprehension."""
        result: dict[Any, Any] = {}

        async def process(generators: list[ast.comprehension], idx: int, local_scope: SymbolTable) -> None:
            if idx >= len(generators):
                key = await self.aeval(node.key, local_scope)
                value = await self.aeval(node.value, local_scope)
                result[key] = value
                return

            gen = generators[idx]
            iterable = await self.aeval(gen.iter, local_scope)
            for item in iterable:
                if self.checkpoint_due():
                    await CHECKPOINT
                inner_scope = local_scope.create_child(SCOPE_COMPREHENSION)
                await self._assign_target(gen.target, item, inner_scope)

                # Check conditions
                all_passed = True
                for if_clause in gen.ifs:
                    if not await self.aeval(if_clause, inner_scope):
                        all_passed = False
                        break

                if all_passed:
                    await process(generators, idx + 1, inner_scope)

        await process(node.generators, 0, scope)
        return result

    async def _eval_comprehension(
        self,
        node: ast.ListComp | ast.SetComp,
        scope: SymbolTable,
    ) -> list[Any]:
        """Evaluate a list or set comprehension."""
        results: list[Any] = []

        async def process(generators: list[ast.comprehension], idx: int, local_scope: SymbolTable) -> None:
            if idx >= len(generators):
                value = await self.aeval(node.elt, local_scope)
                results.append(value)
                return

            gen = generators[idx]
            iterable = await self.aeval(gen.iter, local_scope)
            for item in iterable:
                if self.checkpoint_due():
                    await CHECKPOINT
                inner_scope = local_scope.create_child(SCOPE_COMPREHENSION)
                await self._assign_target(gen.target, item, inner_scope)

                # Check conditions
                all_passed = True
                for if_clause in gen.ifs:
                    if not await self.aeval(if_clause, inner_scope):
                        all_passed = False
                        break

                if all_passed:
                    await process(generators, idx + 1, inner_scope)

        await process(node.generators, 0, scope)
        return results

    async def _eval_joined_str(self, node: ast.JoinedStr, scope: SymbolTable) -> str:
        """Evaluate an f-string."""
        parts: list[str] = []
        for value in node.values:
            parts.append(str(await self.aeval(value, scope)))
        return "".join(parts)

    async def _eval_formatted_value(self, node: ast.FormattedValue, scope: SymbolTable) -> str:
        """Evaluate a formatted value in an f-string."""
        value = await self.aeval(node.value, scope)
        conversions: dict[int, Callable[[Any], str]] = {ord("s"): str, ord("r"): repr, ord("a"): ascii}
        if node.conversion in conversions:
            value = conversions[node.conversion](value)
        format_spec = await self.aeval(node.format_spec, scope) if node.format_spec else ""
        return format(value, format_spec)

    # -------------------------------------------------------------------------
    # Statement evaluators
    # -------------------------------------------------------------------------

    async def _eval_module(self, node: ast.Module, scope: SymbolTable) -> None:
        """Evaluate a module."""
        for stmt in node.body:
            await self.aeval(stmt, scope)

    async def _eval_expression(self, node: ast.Expr, scope: SymbolTable) -> Any:
        """Evaluate an expression statement."""
        value = await self.aeval(node.value, scope)
        if inspect.iscoroutine(value):
            # Nothing can await it any more: the call was written without `await`.
            self._logger.warning(
                "%s:%d: coroutine '%s' was never awaited; write 'await' before the call",
                self._filename,
                node.lineno,
                value.__name__,
            )
            value.close()
        return value

    async def _eval_assign(self, node: ast.Assign, scope: SymbolTable) -> None:
        """Evaluate an assignment statement."""
        value = await self.aeval(node.value, scope)
        for target in node.targets:
            await self._assign_target(target, value, scope)

    async def _eval_annotated_assignment(self, node: ast.AnnAssign, scope: SymbolTable) -> None:
        """Evaluate an annotated assignment."""
        if node.value is not None:
            value = await self.aeval(node.value, scope)
            await self._assign_target(node.target, value, scope)

        # As in Python, a class or module records the annotations of its names;
        # annotations of local variables are not evaluated.
        if node.simple and isinstance(node.target, ast.Name) and scope.kind in (SCOPE_CLASS, SCOPE_MODULE):
            annotations = scope.own_symbols().get("__annotations__")
            if annotations is None:
                annotations = {}
                scope.set("__annotations__", annotations)
            annotations[node.target.id] = await self.aeval(node.annotation, scope)

    async def _eval_augmented_assignment(self, node: ast.AugAssign, scope: SymbolTable) -> None:
        """Evaluate an augmented assignment (+=, -=, etc.)."""
        current = await self.aeval(node.target, scope)
        value = await self.aeval(node.value, scope)
        await self._assign_target(node.target, operators.IN_PLACE[type(node.op)](current, value), scope)

    async def _assign_target(self, target: ast.AST, value: Any, scope: SymbolTable) -> None:
        """Assign a value to a target (name, tuple, list, etc.)."""
        if isinstance(target, ast.Name):
            scope.set(target.id, value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if not hasattr(value, "__iter__"):
                raise TypeError(f"cannot unpack non-iterable {type(value).__name__} object")
            values = list(value)
            targets = target.elts
            starred = [index for index, elt in enumerate(targets) if isinstance(elt, ast.Starred)]
            if starred:
                # a, *b, c = values: b takes whatever the others leave.
                before = starred[0]
                after = len(targets) - before - 1
                if len(values) < before + after:
                    raise ValueError(
                        f"not enough values to unpack (expected at least {before + after}, got {len(values)})"
                    )
                middle = values[before : len(values) - after]
                values = [*values[:before], middle, *values[len(values) - after :]]
            elif len(values) != len(targets):
                problem = "too many" if len(values) > len(targets) else "not enough"
                raise ValueError(f"{problem} values to unpack (expected {len(targets)}, got {len(values)})")
            for t, v in zip(targets, values):
                await self._assign_target(t, v, scope)
        elif isinstance(target, ast.Subscript):
            obj = await self.aeval(target.value, scope)
            index = await self.aeval(target.slice, scope)
            obj[index] = value
        elif isinstance(target, ast.Attribute):
            obj = await self.aeval(target.value, scope)
            setattr(obj, target.attr, value)
        elif isinstance(target, ast.Starred):
            # Handle starred targets in unpacking
            await self._assign_target(target.value, value, scope)
        else:
            raise AutomationRuntimeError(f"Unsupported assignment target: {type(target).__name__}")

    async def _eval_if(self, node: ast.If, scope: SymbolTable) -> Any:
        """Evaluate an if statement."""
        test = await self.aeval(node.test, scope)
        if test:
            for stmt in node.body:
                await self.aeval(stmt, scope)
        elif node.orelse:
            for stmt in node.orelse:
                await self.aeval(stmt, scope)
        return None

    async def _eval_for(self, node: ast.For, scope: SymbolTable) -> Any:
        """Evaluate a for loop."""
        iterable = await self.aeval(node.iter, scope)
        for item in iterable:
            if self.checkpoint_due():
                await CHECKPOINT
            await self._assign_target(node.target, item, scope)
            try:
                for stmt in node.body:
                    await self.aeval(stmt, scope)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
        else:
            # Execute else clause if loop completed without break
            for stmt in node.orelse:
                await self.aeval(stmt, scope)
        return None

    async def _eval_while(self, node: ast.While, scope: SymbolTable) -> Any:
        """Evaluate a while loop."""
        while await self.aeval(node.test, scope):
            if self.checkpoint_due():
                await CHECKPOINT
            try:
                for stmt in node.body:
                    await self.aeval(stmt, scope)
            except BreakLoop:
                break
            except ContinueLoop:
                continue
        else:
            for stmt in node.orelse:
                await self.aeval(stmt, scope)
        return None

    async def _eval_break(self, node: ast.Break, scope: SymbolTable) -> None:
        """Evaluate a break statement."""
        raise BreakLoop()

    async def _eval_continue(self, node: ast.Continue, scope: SymbolTable) -> None:
        """Evaluate a continue statement."""
        raise ContinueLoop()

    async def _eval_return(self, node: ast.Return, scope: SymbolTable) -> ReturnValue:
        """Evaluate a return statement."""
        value = await self.aeval(node.value, scope) if node.value else None
        raise ReturnValue(value)

    async def _eval_function_def(self, node: ast.FunctionDef, scope: SymbolTable) -> None:
        """Evaluate a function definition."""
        func = await self._make_function(node.name, node.args, node.body, scope, lineno=node.lineno)
        await self._define(node.name, func, node.decorator_list, scope)

    async def _eval_async_function_def(self, node: ast.AsyncFunctionDef, scope: SymbolTable) -> None:
        """Evaluate an async function definition."""
        func = await self._make_function(
            node.name, node.args, node.body, scope, is_async=True, lineno=node.lineno
        )
        await self._define(node.name, func, node.decorator_list, scope)

    async def _eval_class_def(self, node: ast.ClassDef, scope: SymbolTable) -> None:
        """Evaluate a class definition."""
        bases = await self._eval_elements(node.bases, scope)

        # Evaluate keywords (metaclass, etc.)
        keywords: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                keywords.update(await self.aeval(keyword.value, scope))
            else:
                keywords[keyword.arg] = await self.aeval(keyword.value, scope)

        # Methods close over this scope, which gives them __class__ for super().
        cell_scope = scope.create_child()
        class_scope = cell_scope.create_child(SCOPE_CLASS)
        class_scope.set("__module__", self.name)
        class_scope.set("__qualname__", node.name)

        for stmt in node.body:
            await self.aeval(stmt, class_scope)

        namespace = class_scope.own_symbols()
        docstring = ast.get_docstring(node)
        if docstring is not None:
            namespace.setdefault("__doc__", docstring)
        cls = types.new_class(node.name, tuple(bases), keywords, lambda ns: ns.update(namespace))
        cell_scope.set("__class__", cls)

        await self._define(node.name, cls, node.decorator_list, scope)

    async def _eval_import(self, node: ast.Import, scope: SymbolTable) -> None:
        """Evaluate an import statement."""
        for alias in node.names:
            module = self._import_controller.safe_import(alias.name)
            if alias.asname:
                scope.set(alias.asname, module)
            else:
                # 'import a.b' binds 'a', as in Python.
                top_level = alias.name.split(".")[0]
                scope.set(top_level, self._import_controller.safe_import(top_level))

    async def _eval_import_from(self, node: ast.ImportFrom, scope: SymbolTable) -> None:
        """Evaluate a from ... import statement."""
        if any(alias.name == "*" for alias in node.names):
            raise AutomationSecurityError("Wildcard imports are not allowed")

        if node.level > 0:
            if self.loader is None or self._path is None:
                raise ImportError("relative imports are not available here")
            await self.loader.import_from(self._path, node, scope)
            return

        module_name = node.module or ""
        module = self._import_controller.safe_import(module_name)
        for alias in node.names:
            try:
                obj = getattr(module, alias.name)
            except AttributeError:
                raise ImportError(f"cannot import name '{alias.name}' from '{module_name}'") from None
            scope.set(alias.asname or alias.name, obj)

    async def _run_module(self, path: Path, module_scope: SymbolTable) -> None:
        """Check and execute another file of the automation in its own module scope."""
        assert self._files is not None
        evaluator = AstEvaluator(
            name=self.name,
            global_symbols=module_scope,
            import_controller=self._import_controller,
            safe_builtins=self._safe_builtins,
            logger=self._logger,
            files=self._files,
            path=path,
            loader=self.loader,
            clock=self.clock,
            checkpoint_interval=self._checkpoint_interval,
        )
        filename = self.loader.display_name(path) if self.loader is not None else path.name
        evaluator.parse(await self._files.read_text(path), filename=filename)
        await evaluator.execute()

    async def _eval_pass(self, node: ast.Pass, scope: SymbolTable) -> None:
        """Evaluate a pass statement."""
        pass  # pylint: disable=unnecessary-pass

    async def _eval_raise(self, node: ast.Raise, scope: SymbolTable) -> None:
        """Evaluate a raise statement."""
        if node.exc is None:
            # Re-raise current exception - get it from sys.exc_info()
            exc_info = sys.exc_info()
            if exc_info[1] is not None:
                raise exc_info[1].with_traceback(exc_info[2])
            raise AutomationRuntimeError("No active exception to re-raise")
        exc = await self.aeval(node.exc, scope)
        if node.cause:
            cause = await self.aeval(node.cause, scope)
            raise exc from cause
        raise exc

    async def _eval_try(self, node: ast.Try, scope: SymbolTable) -> Any:
        """Evaluate a try statement."""
        try:
            for stmt in node.body:
                await self.aeval(stmt, scope)
        except ControlFlow:
            # return, break and continue pass through the handlers.
            raise
        except BaseException as err:  # pylint: disable=broad-exception-caught
            if not await self._handle_exception(node.handlers, err, scope):
                raise
        else:
            # Execute else clause if no exception
            for stmt in node.orelse:
                await self.aeval(stmt, scope)
        finally:
            # Always execute finally clause
            for stmt in node.finalbody:
                await self.aeval(stmt, scope)

        return None

    async def _handle_exception(
        self, handlers: list[ast.ExceptHandler], err: BaseException, scope: SymbolTable
    ) -> bool:
        """Run the first except clause that matches an exception.

        Returns:
            Whether a clause matched.
        """
        for handler in handlers:
            if handler.type is not None and not isinstance(err, await self.aeval(handler.type, scope)):
                continue

            if handler.name:
                scope.set(handler.name, err)
            try:
                for stmt in handler.body:
                    await self.aeval(stmt, scope)
            finally:
                # As in Python, the name is unbound when the handler ends.
                if handler.name:
                    scope.delete(handler.name)
            return True
        return False

    async def _eval_with(self, node: ast.With, scope: SymbolTable) -> Any:
        """Evaluate a with statement."""
        await self._enter_with(node, 0, scope, is_async=False)

    async def _enter_with(
        self, node: ast.With | ast.AsyncWith, index: int, scope: SymbolTable, *, is_async: bool
    ) -> None:
        """Enter the context managers of a with statement from ``index`` on, then run its body."""
        if index == len(node.items):
            for stmt in node.body:
                await self.aeval(stmt, scope)
            return

        item = node.items[index]
        manager = await self.aeval(item.context_expr, scope)
        # As in Python, the methods are looked up on the type, not the instance.
        enter_name, exit_name = ("__aenter__", "__aexit__") if is_async else ("__enter__", "__exit__")
        cls = type(manager)
        if not hasattr(cls, enter_name) or not hasattr(cls, exit_name):
            protocol = "asynchronous context manager" if is_async else "context manager"
            raise TypeError(f"'{cls.__name__}' object does not support the {protocol} protocol")

        async def leave(*exc_info: Any) -> Any:
            result = getattr(cls, exit_name)(manager, *exc_info)
            return await result if is_async else result

        value = getattr(cls, enter_name)(manager)
        if is_async:
            value = await value

        try:
            if item.optional_vars is not None:
                await self._assign_target(item.optional_vars, value, scope)
            await self._enter_with(node, index + 1, scope, is_async=is_async)
        except ControlFlow:
            # return, break and continue leave the block normally.
            await leave(None, None, None)
            raise
        except BaseException as err:  # pylint: disable=broad-exception-caught
            if not await leave(type(err), err, err.__traceback__):
                raise
        else:
            await leave(None, None, None)

    async def _eval_async_with(self, node: ast.AsyncWith, scope: SymbolTable) -> Any:
        """Evaluate an async with statement."""
        await self._enter_with(node, 0, scope, is_async=True)

    async def _eval_await(self, node: ast.Await, scope: SymbolTable) -> Any:
        """Evaluate an await expression."""
        return await (await self.aeval(node.value, scope))

    async def _eval_assert(self, node: ast.Assert, scope: SymbolTable) -> None:
        """Evaluate an assert statement."""
        test = await self.aeval(node.test, scope)
        if not test:
            if node.msg is None:
                raise AssertionError()
            raise AssertionError(await self.aeval(node.msg, scope))

    async def _eval_delete(self, node: ast.Delete, scope: SymbolTable) -> None:
        """Evaluate a delete statement."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                scope.delete(target.id)
            elif isinstance(target, ast.Subscript):
                obj = await self.aeval(target.value, scope)
                index = await self.aeval(target.slice, scope)
                del obj[index]
            elif isinstance(target, ast.Attribute):
                obj = await self.aeval(target.value, scope)
                delattr(obj, target.attr)

    async def _eval_global(self, node: ast.Global, scope: SymbolTable) -> None:
        """Evaluate a global statement."""
        for name in node.names:
            scope.declare_global(name)

    async def _eval_nonlocal(self, node: ast.Nonlocal, scope: SymbolTable) -> None:
        """Evaluate a nonlocal statement."""
        for name in node.names:
            scope.declare_nonlocal(name)

    async def _eval_named_expression(self, node: ast.NamedExpr, scope: SymbolTable) -> Any:
        """Evaluate a walrus operator (:=)."""
        value = await self.aeval(node.value, scope)
        # Inside a comprehension the name is bound in the enclosing scope.
        await self._assign_target(node.target, value, scope.function_scope())
        return value

    async def _eval_type_alias(self, node: ast.TypeAlias, scope: SymbolTable) -> None:
        """Evaluate a type alias statement."""
        value = await self.aeval(node.value, scope)
        scope.set(node.name.id, typing.TypeAliasType(node.name.id, value))

    def get_global_symbols(self) -> SymbolTable:
        """Get the global symbol table.

        Returns:
            The global symbol table.
        """
        return self._global_symbols
