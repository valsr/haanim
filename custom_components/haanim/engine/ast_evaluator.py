""" """

import ast
import asyncio
import logging
import sys
from collections.abc import Callable
from typing import Any

from custom_components.haanim.engine.eval_function import EvalFunction, ReturnValue
from custom_components.haanim.engine.import_controller import ImportController
from custom_components.haanim.engine.safe_builtins import SafeBuiltins
from custom_components.haanim.engine.symbol_table import SymbolTable
from custom_components.haanim.engine.errors import (
    ScriptError,
    ScriptRuntimeError,
    ScriptSecurityError,
    ScriptSyntaxError,
)

_LOGGER = logging.getLogger(__name__)


class BreakLoop(Exception):
    """Used to break out of loops."""


class ContinueLoop(Exception):
    """Used to continue to next iteration."""


class AstEvaluator:
    """AST-based Python code evaluator with security restrictions."""

    def __init__(
        self,
        name: str,
        global_symbols: SymbolTable | None = None,
        import_controller: ImportController | None = None,
        safe_builtins: SafeBuiltins | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        """Initialize the AST evaluator.

        Args:
            name: Name of the script being evaluated.
            global_symbols: Global symbol table for the script.
            import_controller: Controller for safe imports.
            safe_builtins: Provider of safe builtin functions.
            logger: Logger instance for this evaluator.
        """
        self.name = name
        self._logger = logger or _LOGGER
        self._import_controller = import_controller or ImportController()
        self._safe_builtins = safe_builtins or SafeBuiltins()
        self._global_symbols = global_symbols or SymbolTable()
        self._ast: ast.Module | None = None
        self._source: str | None = None

        # Add builtins to global scope
        for name, value in self._safe_builtins.get_builtins().items():
            self._global_symbols.set(name, value)

        # Register evaluators
        self._evaluators: dict[type[ast.AST], Callable[[Any, SymbolTable], Any]] = {
            # Expression evaluators
            ast.Constant: self._eval_constant,
            ast.Num: self._eval_num,  # pyright: ignore[reportDeprecated]
            ast.Str: self._eval_str,  # pyright: ignore[reportDeprecated]
            ast.Index: self._eval_index,  # pyright: ignore[reportDeprecated]
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
        }

    def parse(self, source: str, filename: str = "<script>") -> None:
        """Parse Python source code into an AST.

        Args:
            source: Python source code.
            filename: Filename for error messages.

        Raises:
            ScriptSyntaxError: If the source has syntax errors.
        """
        self._source = source
        try:
            self._ast = ast.parse(source, filename=filename, mode="exec")
        except SyntaxError as err:
            raise ScriptSyntaxError(
                f"Syntax error: {err.msg}",
                lineno=err.lineno,
                col_offset=err.offset,
            ) from err

    async def execute(self) -> dict[str, Any]:
        """Execute the parsed AST.

        Returns:
            Dictionary of names defined in the script (functions, variables, etc.)

        Raises:
            ScriptRuntimeError: If execution fails.
        """
        if self._ast is None:
            raise ScriptRuntimeError("No AST to execute. Call parse() first.")

        try:
            for node in self._ast.body:
                await self.aeval(node, self._global_symbols)
        except Exception as err:
            if isinstance(err, (ScriptError, ReturnValue, BreakLoop, ContinueLoop)):
                self._logger.error("Script execution error: %s", err)
                raise
            self._logger.exception("Unexpected error during script execution")
            raise ScriptRuntimeError(f"Runtime error: {err}") from err

        return self._global_symbols.as_dict()

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
            raise ScriptRuntimeError(
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

    async def _eval_num(self, node: ast.Num, _: SymbolTable) -> Any:  # pyright: ignore[reportDeprecated]
        """Evaluate a number (Python 3.7 compatibility)."""
        return node.n  # pyright: ignore[reportDeprecated]

    async def _eval_str(self, node: ast.Str, _: SymbolTable) -> Any:  # pyright: ignore[reportDeprecated]
        """Evaluate a string (Python 3.7 compatibility)."""
        return node.s  # pyright: ignore[reportDeprecated]

    async def _eval_index(
        self, node: ast.Index, scope: SymbolTable  # pyright: ignore[reportDeprecated]
    ) -> Any:
        """Evaluate an index (Python 3.8 compatibility)."""
        return await self.aeval(node.value, scope)  # type: ignore

    async def _eval_name(self, node: ast.Name, scope: SymbolTable) -> Any:
        """Evaluate a name reference."""
        name = node.id
        if scope.exists(name):
            return scope.get(name)
        raise ScriptRuntimeError(f"Name '{name}' is not defined", lineno=node.lineno)

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

    async def _eval_list(self, node: ast.List, scope: SymbolTable) -> list[Any]:
        """Evaluate a list literal."""
        return [await self.aeval(elt, scope) for elt in node.elts]

    async def _eval_tuple(self, node: ast.Tuple, scope: SymbolTable) -> tuple[Any, ...]:
        """Evaluate a tuple literal."""
        values = [await self.aeval(elt, scope) for elt in node.elts]
        return tuple(values)

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
        return {await self.aeval(elt, scope) for elt in node.elts}

    async def _eval_binary_operation(self, node: ast.BinOp, scope: SymbolTable) -> Any:
        """Evaluate a binary operation."""
        left = await self.aeval(node.left, scope)
        right = await self.aeval(node.right, scope)

        ops: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a**b,
            ast.LShift: lambda a, b: a << b,
            ast.RShift: lambda a, b: a >> b,
            ast.BitOr: lambda a, b: a | b,
            ast.BitXor: lambda a, b: a ^ b,
            ast.BitAnd: lambda a, b: a & b,
            ast.MatMult: lambda a, b: a @ b,
        }

        op_func = ops.get(type(node.op))
        if op_func is None:
            raise ScriptRuntimeError(f"Unsupported binary operator: {type(node.op).__name__}")
        return op_func(left, right)

    async def _eval_unary_operator(self, node: ast.UnaryOp, scope: SymbolTable) -> Any:
        """Evaluate a unary operation."""
        operand = await self.aeval(node.operand, scope)

        ops: dict[type[ast.unaryop], Callable[[Any], Any]] = {
            ast.UAdd: lambda a: +a,
            ast.USub: lambda a: -a,
            ast.Not: lambda a: not a,
            ast.Invert: lambda a: ~a,
        }

        op_func = ops.get(type(node.op))
        if op_func is None:
            raise ScriptRuntimeError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(operand)

    async def _eval_bool_operator(self, node: ast.BoolOp, scope: SymbolTable) -> Any:
        """Evaluate a boolean operation (and/or)."""
        if isinstance(node.op, ast.And):
            for value in node.values:
                result: bool = await self.aeval(value, scope)
                if not result:
                    return False
            return True
        else:  # ast.Or
            for value in node.values:
                result = await self.aeval(value, scope)
                if result:
                    return True
            return False

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
                raise ScriptRuntimeError(f"Unsupported comparison operator: {type(op).__name__}")
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
        args = [await self.aeval(arg, scope) for arg in node.args]
        kwargs: dict[str, Any] = {}
        for keyword in node.keywords:
            if keyword.arg is None:
                # **kwargs unpacking
                kwargs.update(await self.aeval(keyword.value, scope))
            else:
                kwargs[keyword.arg] = await self.aeval(keyword.value, scope)

        # Call the function
        if asyncio.iscoroutinefunction(func) or isinstance(func, EvalFunction):
            return await func(*args, **kwargs)
        return func(*args, **kwargs)

    async def _eval_lambda(self, node: ast.Lambda, scope: SymbolTable) -> Callable[..., Any]:
        """Evaluate a lambda expression."""

        # Create a wrapper function for the lambda
        async def lambda_wrapper(*args: Any, **kwargs: Any) -> Any:
            local_scope = scope.create_child()
            arg_names = [arg.arg for arg in node.args.args]
            for name, value in zip(arg_names, args):
                local_scope.set(name, value)
            for name, value in kwargs.items():
                local_scope.set(name, value)
            return await self.aeval(node.body, local_scope)

        return lambda_wrapper

    async def _eval_list_comprehension(self, node: ast.ListComp, scope: SymbolTable) -> list[Any]:
        """Evaluate a list comprehension."""
        return await self._eval_comprehension(node, scope, list)

    async def _eval_set_comprehension(self, node: ast.SetComp, scope: SymbolTable) -> set[Any]:
        """Evaluate a set comprehension."""
        return await self._eval_comprehension(node, scope, set)

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
                inner_scope = local_scope.create_child()
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
        container_type: type,
    ) -> Any:
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
                inner_scope = local_scope.create_child()
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
        return container_type(results)

    async def _eval_joined_str(self, node: ast.JoinedStr, scope: SymbolTable) -> str:
        """Evaluate an f-string."""
        parts: list[str] = []
        for value in node.values:
            parts.append(str(await self.aeval(value, scope)))
        return "".join(parts)

    async def _eval_formatted_value(self, node: ast.FormattedValue, scope: SymbolTable) -> str:
        """Evaluate a formatted value in an f-string."""
        value = await self.aeval(node.value, scope)
        if node.format_spec:
            format_spec = await self.aeval(node.format_spec, scope)
            return format(value, format_spec)
        return str(value)

    # -------------------------------------------------------------------------
    # Statement evaluators
    # -------------------------------------------------------------------------

    async def _eval_module(self, node: ast.Module, scope: SymbolTable) -> None:
        """Evaluate a module."""
        for stmt in node.body:
            await self.aeval(stmt, scope)

    async def _eval_expression(self, node: ast.Expr, scope: SymbolTable) -> Any:
        """Evaluate an expression statement."""
        return await self.aeval(node.value, scope)

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

    async def _eval_augmented_assignment(self, node: ast.AugAssign, scope: SymbolTable) -> None:
        """Evaluate an augmented assignment (+=, -=, etc.)."""
        current = await self.aeval(node.target, scope)
        value = await self.aeval(node.value, scope)

        ops: dict[type[ast.operator], Callable[[Any, Any], Any]] = {
            ast.Add: lambda a, b: a + b,
            ast.Sub: lambda a, b: a - b,
            ast.Mult: lambda a, b: a * b,
            ast.Div: lambda a, b: a / b,
            ast.FloorDiv: lambda a, b: a // b,
            ast.Mod: lambda a, b: a % b,
            ast.Pow: lambda a, b: a**b,
            ast.LShift: lambda a, b: a << b,
            ast.RShift: lambda a, b: a >> b,
            ast.BitOr: lambda a, b: a | b,
            ast.BitXor: lambda a, b: a ^ b,
            ast.BitAnd: lambda a, b: a & b,
        }

        op_func = ops.get(type(node.op))
        if op_func is None:
            raise ScriptRuntimeError(f"Unsupported augmented assignment operator: {type(node.op).__name__}")

        result = op_func(current, value)
        await self._assign_target(node.target, result, scope)

    async def _assign_target(self, target: ast.AST, value: Any, scope: SymbolTable) -> None:
        """Assign a value to a target (name, tuple, list, etc.)."""
        if isinstance(target, ast.Name):
            scope.set(target.id, value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            if not hasattr(value, "__iter__"):
                raise ScriptRuntimeError("Cannot unpack non-iterable")
            values = list(value)
            if len(values) != len(target.elts):
                raise ScriptRuntimeError(
                    f"Cannot unpack: expected {len(target.elts)} values, got {len(values)}"
                )
            for t, v in zip(target.elts, values):
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
            raise ScriptRuntimeError(f"Unsupported assignment target: {type(target).__name__}")

    async def _eval_if(self, node: ast.If, scope: SymbolTable) -> Any:
        """Evaluate an if statement."""
        test = await self.aeval(node.test, scope)
        if test:
            for stmt in node.body:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        elif node.orelse:
            for stmt in node.orelse:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        return None

    async def _eval_for(self, node: ast.For, scope: SymbolTable) -> Any:
        """Evaluate a for loop."""
        iterable = await self.aeval(node.iter, scope)
        for item in iterable:
            await self._assign_target(node.target, item, scope)
            try:
                for stmt in node.body:
                    result = await self.aeval(stmt, scope)
                    if isinstance(result, ReturnValue):
                        return result
            except BreakLoop:
                break
            except ContinueLoop:
                continue
        else:
            # Execute else clause if loop completed without break
            for stmt in node.orelse:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        return None

    async def _eval_while(self, node: ast.While, scope: SymbolTable) -> Any:
        """Evaluate a while loop."""
        while await self.aeval(node.test, scope):
            try:
                for stmt in node.body:
                    result = await self.aeval(stmt, scope)
                    if isinstance(result, ReturnValue):
                        return result
            except BreakLoop:
                break
            except ContinueLoop:
                continue
        else:
            for stmt in node.orelse:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
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
        # Evaluate decorators
        decorators: list[Any] = []
        for decorator in node.decorator_list:
            dec = await self.aeval(decorator, scope)
            decorators.append(dec)

        # Create the function
        func = EvalFunction(
            name=node.name,
            args=node.args,
            body=node.body,
            decorators=decorators,
            engine=self,
            closure=scope,
            is_async=False,
        )

        # Apply decorators in reverse order
        result: Any = func
        for decorator in reversed(decorators):
            if callable(decorator):
                result = decorator(result)

        scope.set(node.name, result)

    async def _eval_async_function_def(self, node: ast.AsyncFunctionDef, scope: SymbolTable) -> None:
        """Evaluate an async function definition."""
        # Evaluate decorators
        decorators: list[Any] = []
        for decorator in node.decorator_list:
            dec = await self.aeval(decorator, scope)
            decorators.append(dec)

        # Create the function
        func = EvalFunction(
            name=node.name,
            args=node.args,
            body=node.body,
            decorators=decorators,
            engine=self,
            closure=scope,
            is_async=True,
        )

        # Apply decorators in reverse order
        result: Any = func
        for decorator in reversed(decorators):
            if callable(decorator):
                result = decorator(result)

        scope.set(node.name, result)

    async def _eval_class_def(self, node: ast.ClassDef, scope: SymbolTable) -> None:
        """Evaluate a class definition."""
        # Evaluate bases
        bases = [await self.aeval(base, scope) for base in node.bases]

        # Evaluate keywords (metaclass, etc.)
        keywords = {}
        for keyword in node.keywords:
            keywords[keyword.arg] = await self.aeval(keyword.value, scope)

        # Create class namespace
        class_scope = scope.create_child()

        # Execute class body
        for stmt in node.body:
            await self.aeval(stmt, class_scope)

        # Create the class
        class_dict = {k: v for k, v in class_scope.as_dict().items() if not k.startswith("__")}

        # Use type() to create the class
        cls = type(node.name, tuple(bases) or (object,), class_dict)

        # Apply decorators
        for decorator in reversed(node.decorator_list):
            dec = await self.aeval(decorator, scope)
            cls = dec(cls)

        scope.set(node.name, cls)

    async def _eval_import(self, node: ast.Import, scope: SymbolTable) -> None:
        """Evaluate an import statement."""
        for alias in node.names:
            module = self._import_controller.safe_import(alias.name)
            name = alias.asname or alias.name.split(".")[0]
            scope.set(name, module)

    async def _eval_import_from(self, node: ast.ImportFrom, scope: SymbolTable) -> None:
        """Evaluate a from ... import statement."""
        module = self._import_controller.safe_import(node.module or "")
        for alias in node.names:
            if alias.name == "*":
                raise ScriptSecurityError("Wildcard imports are not allowed")
            obj = getattr(module, alias.name)
            name = alias.asname or alias.name
            scope.set(name, obj)

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
            raise ScriptRuntimeError("No active exception to re-raise")
        exc = await self.aeval(node.exc, scope)
        if node.cause:
            cause = await self.aeval(node.cause, scope)
            raise exc from cause
        raise exc

    async def _eval_try(self, node: ast.Try, scope: SymbolTable) -> Any:
        """Evaluate a try statement."""
        try:
            for stmt in node.body:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        except Exception as err:  # pylint: disable=broad-exception-caught
            # Find matching handler
            handled = False
            for handler in node.handlers:
                if handler.type is None:
                    # Bare except
                    matched = True
                else:
                    exc_type = await self.aeval(handler.type, scope)
                    matched = isinstance(err, exc_type)

                if matched:
                    handler_scope = scope.create_child()
                    if handler.name:
                        handler_scope.set(handler.name, err)

                    for stmt in handler.body:
                        result = await self.aeval(stmt, handler_scope)
                        if isinstance(result, ReturnValue):
                            return result
                    handled = True
                    break

            if not handled:
                raise
        else:
            # Execute else clause if no exception
            for stmt in node.orelse:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        finally:
            # Always execute finally clause
            for stmt in node.finalbody:
                await self.aeval(stmt, scope)

        return None

    async def _eval_with(self, node: ast.With, scope: SymbolTable) -> Any:
        """Evaluate a with statement."""
        # Get context managers
        cms: list[tuple[Any, ast.expr | None]] = []
        for item in node.items:
            cm = await self.aeval(item.context_expr, scope)
            cms.append((cm, item.optional_vars))

        # Enter context managers
        values: list[Any] = []
        try:
            for cm, _ in cms:
                value = cm.__enter__()
                values.append(value)

            # Assign values
            for (cm, target), value in zip(cms, values):
                if target:
                    await self._assign_target(target, value, scope)

            # Execute body
            for stmt in node.body:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        finally:
            # Exit context managers in reverse order
            for cm, _ in reversed(cms):
                cm.__exit__(None, None, None)

        return None

    async def _eval_async_with(self, node: ast.AsyncWith, scope: SymbolTable) -> Any:
        """Evaluate an async with statement."""
        cms: list[tuple[Any, ast.expr | None]] = []
        for item in node.items:
            cm = await self.aeval(item.context_expr, scope)
            cms.append((cm, item.optional_vars))

        values: list[Any] = []
        try:
            for cm, _ in cms:
                value = await cm.__aenter__()
                values.append(value)

            for (cm, target), value in zip(cms, values):
                if target:
                    await self._assign_target(target, value, scope)

            for stmt in node.body:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        finally:
            for cm, _ in reversed(cms):
                await cm.__aexit__(None, None, None)

        return None

    async def _eval_await(self, node: ast.Await, scope: SymbolTable) -> Any:
        """Evaluate an await expression."""
        value = await self.aeval(node.value, scope)
        if asyncio.iscoroutine(value):
            return await value
        return value

    async def _eval_assert(self, node: ast.Assert, scope: SymbolTable) -> None:
        """Evaluate an assert statement."""
        test = await self.aeval(node.test, scope)
        if not test:
            msg = await self.aeval(node.msg, scope) if node.msg else "Assertion failed"
            raise AssertionError(msg)

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

    async def _eval_global(self, _: ast.Global, __: SymbolTable) -> None:
        """Evaluate a global statement (marks names as global)."""
        # In our implementation, globals are handled via set_global
        pass  # pylint: disable=unnecessary-pass

    async def _eval_nonlocal(self, _: ast.Nonlocal, __: SymbolTable) -> None:
        """Evaluate a nonlocal statement."""
        # Handled by scope chain
        pass  # pylint: disable=unnecessary-pass

    async def _eval_named_expression(self, node: ast.NamedExpr, scope: SymbolTable) -> Any:
        """Evaluate a walrus operator (:=)."""
        value = await self.aeval(node.value, scope)
        await self._assign_target(node.target, value, scope)
        return value

    def get_global_symbols(self) -> SymbolTable:
        """Get the global symbol table.

        Returns:
            The global symbol table.
        """
        return self._global_symbols
