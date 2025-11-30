"""AST-based Python script execution engine for HAAnim.

This module provides a secure, sandboxed Python execution environment using
AST (Abstract Syntax Tree) evaluation instead of exec/eval for better security.
"""

from __future__ import annotations

import ast
import asyncio
import builtins
import logging
from typing import Any, Callable

from .const import DEFAULT_IMPORT_ALLOWLIST, RESTRICTED_BUILTINS

_LOGGER = logging.getLogger(__name__)


class ScriptError(Exception):
    """Base exception for script execution errors."""

    def __init__(self, message: str, lineno: int | None = None, col_offset: int | None = None) -> None:
        """Initialize the script error.

        Args:
            message: Error message.
            lineno: Line number where error occurred.
            col_offset: Column offset where error occurred.
        """
        super().__init__(message)
        self.lineno = lineno
        self.col_offset = col_offset


class ScriptSecurityError(ScriptError):
    """Exception raised for security violations in scripts."""


class ScriptSyntaxError(ScriptError):
    """Exception raised for syntax errors in scripts."""


class ScriptRuntimeError(ScriptError):
    """Exception raised for runtime errors in scripts."""


class SafeBuiltins:
    """Provides a filtered set of Python builtins for script execution."""

    def __init__(
        self,
        restricted: set[str] | None = None,
        additional_allowed: dict[str, Any] | None = None,
    ) -> None:
        """Initialize safe builtins.

        Args:
            restricted: Set of builtin names to restrict. Defaults to RESTRICTED_BUILTINS.
            additional_allowed: Additional names to make available.
        """
        self._restricted = restricted or RESTRICTED_BUILTINS
        self._builtins: dict[str, Any] = {}

        # Copy allowed builtins
        for name in dir(builtins):
            if not name.startswith("_") and name not in self._restricted:
                self._builtins[name] = getattr(builtins, name)

        # Add additional allowed items
        if additional_allowed:
            self._builtins.update(additional_allowed)

    def get_builtins(self) -> dict[str, Any]:
        """Get the filtered builtins dictionary.

        Returns:
            Dictionary of allowed builtins.
        """
        return self._builtins.copy()


class ImportController:
    """Controls which modules can be imported in scripts."""

    def __init__(
        self,
        allowlist: list[str] | None = None,
        allow_all: bool = False,
    ) -> None:
        """Initialize the import controller.

        Args:
            allowlist: List of allowed module names. Defaults to DEFAULT_IMPORT_ALLOWLIST.
            allow_all: If True, allow all imports (use with caution).
        """
        self._allowlist = set(allowlist or DEFAULT_IMPORT_ALLOWLIST)
        self._allow_all = allow_all
        self._imported_modules: dict[str, Any] = {}
        self._virtual_modules: dict[str, Any] = {}

    def register_virtual_module(self, name: str, module: Any) -> None:
        """Register a virtual module that can be imported by scripts.

        Args:
            name: The module name (e.g., 'haanim').
            module: The module object or namespace to expose.
        """
        self._virtual_modules[name] = module
        self._allowlist.add(name)

    def is_allowed(self, module_name: str) -> bool:
        """Check if a module is allowed to be imported.

        Args:
            module_name: The module name to check.

        Returns:
            True if the module can be imported.
        """
        if self._allow_all:
            return True

        # Check the top-level module name
        top_level = module_name.split(".")[0]
        return top_level in self._allowlist

    def safe_import(self, module_name: str, fromlist: list[str] | None = None) -> Any:
        """Safely import a module if allowed.

        Args:
            module_name: The module to import.
            fromlist: List of names to import from the module.

        Returns:
            The imported module.

        Raises:
            ScriptSecurityError: If the module is not allowed.
        """
        # Check for virtual modules first
        if module_name in self._virtual_modules:
            return self._virtual_modules[module_name]

        if not self.is_allowed(module_name):
            _LOGGER.error("Import blocked - module '%s' is not in allowlist", module_name)
            raise ScriptSecurityError(f"Import of module '{module_name}' is not allowed")

        import importlib

        try:
            module = importlib.import_module(module_name)
            self._imported_modules[module_name] = module
            return module
        except ImportError as err:
            _LOGGER.error("Failed to import module '%s': %s", module_name, err)
            raise ScriptRuntimeError(f"Failed to import module '{module_name}': {err}") from err


class SymbolTable:
    """Manages variable scopes during script execution."""

    def __init__(self, parent: SymbolTable | None = None) -> None:
        """Initialize a symbol table.

        Args:
            parent: Parent symbol table for scope chain.
        """
        self._symbols: dict[str, Any] = {}
        self._parent = parent

    def get(self, name: str, default: Any = None) -> Any:
        """Get a symbol value.

        Args:
            name: The symbol name.
            default: Default value if not found.

        Returns:
            The symbol value or default.
        """
        if name in self._symbols:
            return self._symbols[name]
        if self._parent:
            return self._parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set a symbol value in the current scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        self._symbols[name] = value

    def set_global(self, name: str, value: Any) -> None:
        """Set a symbol value in the global scope.

        Args:
            name: The symbol name.
            value: The value to set.
        """
        if self._parent:
            self._parent.set_global(name, value)
        else:
            self._symbols[name] = value

    def exists(self, name: str) -> bool:
        """Check if a symbol exists.

        Args:
            name: The symbol name.

        Returns:
            True if the symbol exists in this or parent scope.
        """
        if name in self._symbols:
            return True
        if self._parent:
            return self._parent.exists(name)
        return False

    def delete(self, name: str) -> bool:
        """Delete a symbol from the current scope.

        Args:
            name: The symbol name.

        Returns:
            True if the symbol was deleted.
        """
        if name in self._symbols:
            del self._symbols[name]
            return True
        return False

    def as_dict(self) -> dict[str, Any]:
        """Get all symbols as a dictionary.

        Returns:
            Dictionary of all symbols in scope chain.
        """
        result = {}
        if self._parent:
            result.update(self._parent.as_dict())
        result.update(self._symbols)
        return result

    def create_child(self) -> SymbolTable:
        """Create a child scope.

        Returns:
            A new SymbolTable with this as parent.
        """
        return SymbolTable(parent=self)


class EvalFunction:
    """Wrapper for user-defined functions in scripts."""

    def __init__(
        self,
        name: str,
        args: ast.arguments,
        body: list[ast.stmt],
        decorators: list[Any],
        engine: AstEvaluator,
        closure: SymbolTable,
        is_async: bool = False,
    ) -> None:
        """Initialize an evaluated function.

        Args:
            name: Function name.
            args: AST arguments node.
            body: List of AST statement nodes for the function body.
            decorators: List of evaluated decorators.
            engine: The AstEvaluator instance.
            closure: The symbol table at function definition time.
            is_async: Whether this is an async function.
        """
        self.name = name
        self.args = args
        self.body = body
        self.decorators = decorators
        self.engine = engine
        self.closure = closure
        self.is_async = is_async
        self.__name__ = name

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the function.

        Args:
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The function return value.
        """
        # Create new scope for function execution
        local_scope = self.closure.create_child()

        # Bind positional arguments
        arg_names = [arg.arg for arg in self.args.args]
        for i, (name, value) in enumerate(zip(arg_names, args)):
            local_scope.set(name, value)

        # Bind keyword arguments
        for name, value in kwargs.items():
            local_scope.set(name, value)

        # Bind defaults for missing arguments
        defaults = self.args.defaults
        num_defaults = len(defaults)
        num_args = len(arg_names)
        for i, default in enumerate(defaults):
            arg_index = num_args - num_defaults + i
            arg_name = arg_names[arg_index]
            if not local_scope.exists(arg_name):
                default_val = await self.engine.aeval(default, local_scope)
                local_scope.set(arg_name, default_val)

        # Execute function body
        result = None
        for stmt in self.body:
            try:
                result = await self.engine.aeval(stmt, local_scope)
                if isinstance(result, ReturnValue):
                    return result.value
            except ReturnValue as ret:
                return ret.value

        return result


class ReturnValue(Exception):
    """Used to propagate return values up the call stack."""

    def __init__(self, value: Any) -> None:
        """Initialize with return value.

        Args:
            value: The value being returned.
        """
        super().__init__()
        self.value = value


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
        method_name = f"_eval_{node.__class__.__name__}"
        method = getattr(self, method_name, None)

        if method is None:
            raise ScriptRuntimeError(
                f"Unsupported AST node type: {node.__class__.__name__}",
                lineno=getattr(node, "lineno", None),
            )

        return await method(node, scope)

    # -------------------------------------------------------------------------
    # Expression evaluators
    # -------------------------------------------------------------------------

    async def _eval_Constant(self, node: ast.Constant, scope: SymbolTable) -> Any:
        """Evaluate a constant value."""
        return node.value

    async def _eval_Num(self, node: ast.Num, scope: SymbolTable) -> Any:
        """Evaluate a number (Python 3.7 compatibility)."""
        return node.n

    async def _eval_Str(self, node: ast.Str, scope: SymbolTable) -> Any:
        """Evaluate a string (Python 3.7 compatibility)."""
        return node.s

    async def _eval_Name(self, node: ast.Name, scope: SymbolTable) -> Any:
        """Evaluate a name reference."""
        name = node.id
        if scope.exists(name):
            return scope.get(name)
        raise ScriptRuntimeError(f"Name '{name}' is not defined", lineno=node.lineno)

    async def _eval_Attribute(self, node: ast.Attribute, scope: SymbolTable) -> Any:
        """Evaluate an attribute access."""
        obj = await self.aeval(node.value, scope)
        return getattr(obj, node.attr)

    async def _eval_Subscript(self, node: ast.Subscript, scope: SymbolTable) -> Any:
        """Evaluate a subscript operation."""
        obj = await self.aeval(node.value, scope)
        index = await self.aeval(node.slice, scope)
        return obj[index]

    async def _eval_Index(self, node: ast.Index, scope: SymbolTable) -> Any:
        """Evaluate an index (Python 3.8 compatibility)."""
        return await self.aeval(node.value, scope)

    async def _eval_Slice(self, node: ast.Slice, scope: SymbolTable) -> Any:
        """Evaluate a slice."""
        lower = await self.aeval(node.lower, scope) if node.lower else None
        upper = await self.aeval(node.upper, scope) if node.upper else None
        step = await self.aeval(node.step, scope) if node.step else None
        return slice(lower, upper, step)

    async def _eval_List(self, node: ast.List, scope: SymbolTable) -> list[Any]:
        """Evaluate a list literal."""
        return [await self.aeval(elt, scope) for elt in node.elts]

    async def _eval_Tuple(self, node: ast.Tuple, scope: SymbolTable) -> tuple[Any, ...]:
        """Evaluate a tuple literal."""
        return tuple(await self.aeval(elt, scope) for elt in node.elts)

    async def _eval_Dict(self, node: ast.Dict, scope: SymbolTable) -> dict[Any, Any]:
        """Evaluate a dict literal."""
        result = {}
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

    async def _eval_Set(self, node: ast.Set, scope: SymbolTable) -> set[Any]:
        """Evaluate a set literal."""
        return {await self.aeval(elt, scope) for elt in node.elts}

    async def _eval_BinOp(self, node: ast.BinOp, scope: SymbolTable) -> Any:
        """Evaluate a binary operation."""
        left = await self.aeval(node.left, scope)
        right = await self.aeval(node.right, scope)

        ops = {
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

    async def _eval_UnaryOp(self, node: ast.UnaryOp, scope: SymbolTable) -> Any:
        """Evaluate a unary operation."""
        operand = await self.aeval(node.operand, scope)

        ops = {
            ast.UAdd: lambda a: +a,
            ast.USub: lambda a: -a,
            ast.Not: lambda a: not a,
            ast.Invert: lambda a: ~a,
        }

        op_func = ops.get(type(node.op))
        if op_func is None:
            raise ScriptRuntimeError(f"Unsupported unary operator: {type(node.op).__name__}")
        return op_func(operand)

    async def _eval_BoolOp(self, node: ast.BoolOp, scope: SymbolTable) -> Any:
        """Evaluate a boolean operation (and/or)."""
        if isinstance(node.op, ast.And):
            for value in node.values:
                result = await self.aeval(value, scope)
                if not result:
                    return result
            return result
        else:  # ast.Or
            for value in node.values:
                result = await self.aeval(value, scope)
                if result:
                    return result
            return result

    async def _eval_Compare(self, node: ast.Compare, scope: SymbolTable) -> bool:
        """Evaluate a comparison."""
        left = await self.aeval(node.left, scope)

        ops = {
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

    async def _eval_IfExp(self, node: ast.IfExp, scope: SymbolTable) -> Any:
        """Evaluate a conditional expression (ternary)."""
        test = await self.aeval(node.test, scope)
        if test:
            return await self.aeval(node.body, scope)
        return await self.aeval(node.orelse, scope)

    async def _eval_Call(self, node: ast.Call, scope: SymbolTable) -> Any:
        """Evaluate a function call."""
        func = await self.aeval(node.func, scope)

        # Evaluate arguments
        args = [await self.aeval(arg, scope) for arg in node.args]
        kwargs = {}
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

    async def _eval_Lambda(self, node: ast.Lambda, scope: SymbolTable) -> Callable[..., Any]:
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

    async def _eval_ListComp(self, node: ast.ListComp, scope: SymbolTable) -> list[Any]:
        """Evaluate a list comprehension."""
        return await self._eval_comprehension(node, scope, list)

    async def _eval_SetComp(self, node: ast.SetComp, scope: SymbolTable) -> set[Any]:
        """Evaluate a set comprehension."""
        return await self._eval_comprehension(node, scope, set)

    async def _eval_DictComp(self, node: ast.DictComp, scope: SymbolTable) -> dict[Any, Any]:
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

    async def _eval_JoinedStr(self, node: ast.JoinedStr, scope: SymbolTable) -> str:
        """Evaluate an f-string."""
        parts = []
        for value in node.values:
            parts.append(str(await self.aeval(value, scope)))
        return "".join(parts)

    async def _eval_FormattedValue(self, node: ast.FormattedValue, scope: SymbolTable) -> str:
        """Evaluate a formatted value in an f-string."""
        value = await self.aeval(node.value, scope)
        if node.format_spec:
            format_spec = await self.aeval(node.format_spec, scope)
            return format(value, format_spec)
        return str(value)

    # -------------------------------------------------------------------------
    # Statement evaluators
    # -------------------------------------------------------------------------

    async def _eval_Module(self, node: ast.Module, scope: SymbolTable) -> None:
        """Evaluate a module."""
        for stmt in node.body:
            await self.aeval(stmt, scope)

    async def _eval_Expr(self, node: ast.Expr, scope: SymbolTable) -> Any:
        """Evaluate an expression statement."""
        return await self.aeval(node.value, scope)

    async def _eval_Assign(self, node: ast.Assign, scope: SymbolTable) -> None:
        """Evaluate an assignment statement."""
        value = await self.aeval(node.value, scope)
        for target in node.targets:
            await self._assign_target(target, value, scope)

    async def _eval_AnnAssign(self, node: ast.AnnAssign, scope: SymbolTable) -> None:
        """Evaluate an annotated assignment."""
        if node.value is not None:
            value = await self.aeval(node.value, scope)
            await self._assign_target(node.target, value, scope)

    async def _eval_AugAssign(self, node: ast.AugAssign, scope: SymbolTable) -> None:
        """Evaluate an augmented assignment (+=, -=, etc.)."""
        target_name = node.target.id if isinstance(node.target, ast.Name) else None
        current = await self.aeval(node.target, scope)
        value = await self.aeval(node.value, scope)

        ops = {
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

    async def _eval_If(self, node: ast.If, scope: SymbolTable) -> Any:
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

    async def _eval_For(self, node: ast.For, scope: SymbolTable) -> Any:
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

    async def _eval_While(self, node: ast.While, scope: SymbolTable) -> Any:
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

    async def _eval_Break(self, node: ast.Break, scope: SymbolTable) -> None:
        """Evaluate a break statement."""
        raise BreakLoop()

    async def _eval_Continue(self, node: ast.Continue, scope: SymbolTable) -> None:
        """Evaluate a continue statement."""
        raise ContinueLoop()

    async def _eval_Return(self, node: ast.Return, scope: SymbolTable) -> ReturnValue:
        """Evaluate a return statement."""
        value = await self.aeval(node.value, scope) if node.value else None
        raise ReturnValue(value)

    async def _eval_FunctionDef(self, node: ast.FunctionDef, scope: SymbolTable) -> None:
        """Evaluate a function definition."""
        # Evaluate decorators
        decorators = []
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

    async def _eval_AsyncFunctionDef(self, node: ast.AsyncFunctionDef, scope: SymbolTable) -> None:
        """Evaluate an async function definition."""
        # Evaluate decorators
        decorators = []
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

    async def _eval_ClassDef(self, node: ast.ClassDef, scope: SymbolTable) -> None:
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

    async def _eval_Import(self, node: ast.Import, scope: SymbolTable) -> None:
        """Evaluate an import statement."""
        for alias in node.names:
            module = self._import_controller.safe_import(alias.name)
            name = alias.asname or alias.name.split(".")[0]
            scope.set(name, module)

    async def _eval_ImportFrom(self, node: ast.ImportFrom, scope: SymbolTable) -> None:
        """Evaluate a from ... import statement."""
        module = self._import_controller.safe_import(node.module or "")
        for alias in node.names:
            if alias.name == "*":
                raise ScriptSecurityError("Wildcard imports are not allowed")
            obj = getattr(module, alias.name)
            name = alias.asname or alias.name
            scope.set(name, obj)

    async def _eval_Pass(self, node: ast.Pass, scope: SymbolTable) -> None:
        """Evaluate a pass statement."""
        pass

    async def _eval_Raise(self, node: ast.Raise, scope: SymbolTable) -> None:
        """Evaluate a raise statement."""
        if node.exc is None:
            raise  # Re-raise current exception
        exc = await self.aeval(node.exc, scope)
        if node.cause:
            cause = await self.aeval(node.cause, scope)
            raise exc from cause
        raise exc

    async def _eval_Try(self, node: ast.Try, scope: SymbolTable) -> Any:
        """Evaluate a try statement."""
        try:
            for stmt in node.body:
                result = await self.aeval(stmt, scope)
                if isinstance(result, ReturnValue):
                    return result
        except Exception as err:
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

    async def _eval_With(self, node: ast.With, scope: SymbolTable) -> Any:
        """Evaluate a with statement."""
        # Get context managers
        cms = []
        for item in node.items:
            cm = await self.aeval(item.context_expr, scope)
            cms.append((cm, item.optional_vars))

        # Enter context managers
        values = []
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

    async def _eval_AsyncWith(self, node: ast.AsyncWith, scope: SymbolTable) -> Any:
        """Evaluate an async with statement."""
        cms = []
        for item in node.items:
            cm = await self.aeval(item.context_expr, scope)
            cms.append((cm, item.optional_vars))

        values = []
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

    async def _eval_Await(self, node: ast.Await, scope: SymbolTable) -> Any:
        """Evaluate an await expression."""
        value = await self.aeval(node.value, scope)
        if asyncio.iscoroutine(value):
            return await value
        return value

    async def _eval_Assert(self, node: ast.Assert, scope: SymbolTable) -> None:
        """Evaluate an assert statement."""
        test = await self.aeval(node.test, scope)
        if not test:
            msg = await self.aeval(node.msg, scope) if node.msg else "Assertion failed"
            raise AssertionError(msg)

    async def _eval_Delete(self, node: ast.Delete, scope: SymbolTable) -> None:
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

    async def _eval_Global(self, node: ast.Global, scope: SymbolTable) -> None:
        """Evaluate a global statement (marks names as global)."""
        # In our implementation, globals are handled via set_global
        pass

    async def _eval_Nonlocal(self, node: ast.Nonlocal, scope: SymbolTable) -> None:
        """Evaluate a nonlocal statement."""
        # Handled by scope chain
        pass

    async def _eval_NamedExpr(self, node: ast.NamedExpr, scope: SymbolTable) -> Any:
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
