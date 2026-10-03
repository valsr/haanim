"""User-defined function wrapper and return-value propagation for the AST evaluator."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Any

from custom_components.haanim.engine.symbol_table import SymbolTable

if TYPE_CHECKING:
    from custom_components.haanim.engine.ast_evaluator import AstEvaluator


class EvalFunction:
    """Wrapper for user-defined functions in automations."""

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
